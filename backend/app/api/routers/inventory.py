from copy import deepcopy
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.ads import AdsSessionLocal
from app.db.ods import get_ods_db
from app.models.user import User
from app.schemas.common import ok
from app.services.inventory_ads import (
    InventoryAdsUnavailable,
    latest_ready_inventory_batch,
    load_inventory_filter_options_from_ads,
    load_inventory_overview_from_ads,
)


router = APIRouter(prefix="/inventory", tags=["inventory"])

INVENTORY_CACHE_TTL_SECONDS = 300
INVENTORY_CACHE_MAX_ITEMS = 128
DEFAULT_INVENTORY_PRODUCT_TYPES = ("正装", "小样")
ALL_PRODUCT_TYPES_TOKEN = "__all__"
_inventory_cache: dict[tuple, tuple[float, dict]] = {}
_inventory_cache_lock = Lock()


def _cache_key(endpoint: str, **params: object) -> tuple:
    return (endpoint, tuple(sorted((key, value) for key, value in params.items())))


def _get_cache(key: tuple) -> dict | None:
    now = monotonic()
    with _inventory_cache_lock:
        cached = _inventory_cache.get(key)
        if cached is None:
            return None

        expires_at, data = cached
        if expires_at <= now:
            _inventory_cache.pop(key, None)
            return None

        return deepcopy(data)


def _set_cache(key: tuple, data: dict) -> None:
    now = monotonic()
    with _inventory_cache_lock:
        if len(_inventory_cache) >= INVENTORY_CACHE_MAX_ITEMS:
            expired_keys = [cache_key for cache_key, (expires_at, _) in _inventory_cache.items() if expires_at <= now]
            for cache_key in expired_keys:
                _inventory_cache.pop(cache_key, None)
            if len(_inventory_cache) >= INVENTORY_CACHE_MAX_ITEMS:
                oldest_key = min(_inventory_cache, key=lambda cache_key: _inventory_cache[cache_key][0])
                _inventory_cache.pop(oldest_key, None)

        _inventory_cache[key] = (now + INVENTORY_CACHE_TTL_SECONDS, deepcopy(data))


def _cached_ok(key: tuple, data: dict) -> dict:
    _set_cache(key, data)
    return ok(data)


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return 0
    return float(value)


def _int(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _text(value: object, fallback: str = "-") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def _limit(value: int) -> int:
    return max(1, min(value, 100))


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    normalized_page = max(1, page)
    normalized_size = max(10, min(page_size, 100))
    return normalized_page, normalized_size, (normalized_page - 1) * normalized_size


def _keyword_filter(keyword: str | None) -> tuple[str, dict]:
    if not keyword or not keyword.strip():
        return "", {}
    return (
        """
        AND (
          `货品编号` LIKE :keyword
          OR `货品名称` LIKE :keyword
          OR `品牌` LIKE :keyword
          OR `条码` LIKE :keyword
        )
        """,
        {"keyword": f"%{keyword.strip()}%"},
    )


def _barcode_filter(barcode: str | None) -> tuple[str, dict]:
    if not barcode or not barcode.strip():
        return "", {}
    return "AND `条码` LIKE :barcode", {"barcode": f"%{barcode.strip()}%"}


def _normalize_warehouses(warehouses: list[str] | None) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in warehouses or [] if value.strip()}))


def _warehouse_filter(
    warehouses: tuple[str, ...],
    prefix: str = "warehouse",
    column: str = "`仓库`",
) -> tuple[str, dict]:
    if not warehouses:
        return "", {}

    placeholders = []
    params = {}
    for index, warehouse in enumerate(warehouses):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = warehouse
    return (
        f"AND COALESCE(NULLIF({column}, ''), '未归类') IN ({', '.join(placeholders)})",
        params,
    )


def _normalize_product_types(product_types: list[str] | None) -> tuple[str, ...]:
    if product_types is None:
        return DEFAULT_INVENTORY_PRODUCT_TYPES
    normalized = {value.strip() for value in product_types if value.strip()}
    if ALL_PRODUCT_TYPES_TOKEN in normalized:
        return ()
    return tuple(sorted(normalized))


def _product_type_filter(
    product_types: tuple[str, ...],
    prefix: str = "product_type",
    column: str = "s.`货品分类`",
) -> tuple[str, dict]:
    if not product_types:
        return "", {}

    placeholders = []
    params = {}
    for index, product_type in enumerate(product_types):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = product_type
    return f"AND NULLIF(TRIM({column}), '') IN ({', '.join(placeholders)})", params


def _expiry_filter(expiry_range: str, column: str = "`到期日期`") -> str:
    filters = {
        "expired": f"{column} < CURDATE()",
        "0_6": f"{column} BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 6 MONTH)",
        "6_12": f"{column} > DATE_ADD(CURDATE(), INTERVAL 6 MONTH) AND {column} <= DATE_ADD(CURDATE(), INTERVAL 12 MONTH)",
        "12_24": f"{column} > DATE_ADD(CURDATE(), INTERVAL 12 MONTH) AND {column} <= DATE_ADD(CURDATE(), INTERVAL 24 MONTH)",
        "gt_24": f"{column} > DATE_ADD(CURDATE(), INTERVAL 24 MONTH)",
        "missing": f"{column} IS NULL",
    }
    condition = filters.get(expiry_range)
    return f"AND {condition}" if condition else ""


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.get("/warehouses")
def inventory_warehouses(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    response.headers["X-BI-Query-Mode"] = settings.BI_QUERY_SOURCE
    if settings.BI_QUERY_SOURCE == "ads" and AdsSessionLocal is not None:
        try:
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_inventory_batch(ads_db)
                cache_key = _cache_key(
                    "warehouses-v6",
                    query_mode="ads",
                    data_version=batch.data_version,
                )
                cached = _get_cache(cache_key)
                if cached is not None:
                    response.headers["X-BI-Response-Source"] = "ads"
                    return ok(cached)
                data = load_inventory_filter_options_from_ads(ads_db, batch)
            response.headers["X-BI-Response-Source"] = "ads"
            return _cached_ok(cache_key, data)
        except InventoryAdsUnavailable:
            pass
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Inventory ADS database is temporarily unavailable",
            ) from exc

    response.headers["X-BI-Response-Source"] = "ods"
    cache_key = _cache_key("warehouses-v6", query_mode="ods")
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    rows = db.execute(
        text(
            """
            SELECT warehouse
            FROM (
              SELECT COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse FROM `分仓库查询`
              UNION
              SELECT COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse FROM `批次货品库存查询`
            ) warehouses
            ORDER BY warehouse
            """
        )
    ).scalars().all()
    product_types = db.execute(
        text(
            """
            SELECT product_type
            FROM (
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `分仓库查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `总库存查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `批次货品库存查询`
            ) inventory_product_types
            WHERE product_type IS NOT NULL
            ORDER BY
              CASE product_type WHEN '正装' THEN 0 WHEN '小样' THEN 1 ELSE 2 END,
              product_type
            """
        )
    ).scalars().all()
    brands = db.execute(
        text(
            """
            SELECT brand
            FROM (
              SELECT DISTINCT NULLIF(TRIM(`品牌`), '') AS brand FROM `分仓库查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`品牌`), '') AS brand FROM `销售单明细账`
            ) inventory_brands
            WHERE brand IS NOT NULL AND brand <> '未归类'
            ORDER BY brand
            """
        )
    ).scalars().all()
    return _cached_ok(
        cache_key,
        {
            "warehouses": [_text(row, "未归类") for row in rows],
            "product_types": [_text(row) for row in product_types],
            "brands": [_text(row) for row in brands],
        },
    )


@router.get("/product-detail/{product_code}")
def inventory_product_detail(
    product_code: str,
    warehouse: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    product_code = product_code.strip()
    warehouses = _normalize_warehouses(warehouse)
    cache_key = _cache_key("product-detail-v2", product_code=product_code, warehouses=warehouses)
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    warehouse_sql, params = _warehouse_filter(warehouses, "detail_warehouse")
    params["product_code"] = product_code
    warehouse_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              MAX(`货品名称`) AS product,
              MAX(COALESCE(NULLIF(`品牌`, ''), '未归类')) AS brand,
              MAX(`条码`) AS barcode,
              SUM(COALESCE(`库存数量`, 0)) AS stock,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
              SUM(COALESCE(`近30天销量`, 0)) AS sales30,
              SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
              MAX(`updatetime`) AS updated_at
            FROM `分仓库查询`
            WHERE `货品编号` = :product_code
              {warehouse_sql}
            GROUP BY COALESCE(NULLIF(`仓库`, ''), '未归类')
            ORDER BY available_stock DESC
            """
        ),
        params,
    ).mappings().all()

    batch_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              COALESCE(NULLIF(`批次`, ''), '未标批次') AS batch,
              `生产日期` AS production_date,
              `到期日期` AS expiry_date,
              DATEDIFF(`到期日期`, CURDATE()) AS remaining_days,
              COALESCE(`库存数量`, 0) AS stock,
              COALESCE(`可用库存`, 0) AS available_stock,
              ROW_NUMBER() OVER (
                PARTITION BY COALESCE(NULLIF(`仓库`, ''), '未归类')
                ORDER BY CASE WHEN `到期日期` IS NULL THEN 1 ELSE 0 END, `到期日期`, `生产日期`, `批次`
              ) AS fefo_rank
            FROM `批次货品库存查询`
            WHERE `货品编号` = :product_code
              AND COALESCE(`可用库存`, 0) > 0
              {warehouse_sql}
            ORDER BY
              CASE WHEN `到期日期` IS NULL THEN 1 ELSE 0 END,
              `到期日期`,
              `生产日期`,
              `批次`
            """
        ),
        params,
    ).mappings().all()

    first_row = warehouse_rows[0] if warehouse_rows else None
    data = {
        "product_code": product_code,
        "product": _text(first_row["product"], "未命名商品") if first_row else "未命名商品",
        "brand": _text(first_row["brand"], "未归类") if first_row else "未归类",
        "barcode": _text(first_row["barcode"]) if first_row else "-",
        "warehouses_selected": list(warehouses),
        "metrics": {
            "warehouse_count": len(warehouse_rows),
            "batch_count": len(batch_rows),
            "stock": sum(_number(row["stock"]) for row in warehouse_rows),
            "available_stock": sum(_number(row["available_stock"]) for row in warehouse_rows),
            "stock_amount": sum(_number(row["stock_amount"]) for row in warehouse_rows),
            "sales30": sum(_number(row["sales30"]) for row in warehouse_rows),
            "sales90": sum(_number(row["sales90"]) for row in warehouse_rows),
        },
        "warehouse_rows": [
            {
                "warehouse": _text(row["warehouse"], "未归类"),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "stock_amount": _number(row["stock_amount"]),
                "sales30": _number(row["sales30"]),
                "sales90": _number(row["sales90"]),
                "updated_at": _date_text(row["updated_at"]),
            }
            for row in warehouse_rows
        ],
        "batch_rows": [
            {
                "warehouse": _text(row["warehouse"], "未归类"),
                "batch": _text(row["batch"], "未标批次"),
                "production_date": _date_text(row["production_date"]),
                "expiry_date": _date_text(row["expiry_date"]),
                "remaining_days": _int(row["remaining_days"]) if row["remaining_days"] is not None else None,
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "fefo_rank": _int(row["fefo_rank"]),
            }
            for row in batch_rows
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/overview")
def inventory_overview(
    response: Response,
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    response.headers["X-BI-Query-Mode"] = settings.BI_QUERY_SOURCE
    if settings.BI_QUERY_SOURCE == "ads" and AdsSessionLocal is not None:
        try:
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_inventory_batch(ads_db)
                cache_key = _cache_key(
                    "overview-v5",
                    warehouses=warehouses,
                    product_types=product_types,
                    query_mode="ads",
                    data_version=batch.data_version,
                )
                cached = _get_cache(cache_key)
                if cached is not None:
                    response.headers["X-BI-Response-Source"] = "ads"
                    return ok(cached)
                data = load_inventory_overview_from_ads(
                    ads_db,
                    batch,
                    warehouses,
                    product_types,
                )
            response.headers["X-BI-Response-Source"] = "ads"
            return _cached_ok(cache_key, data)
        except InventoryAdsUnavailable:
            pass
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Inventory ADS database is temporarily unavailable",
            ) from exc

    response.headers["X-BI-Response-Source"] = "ods"
    cache_key = _cache_key(
        "overview-v5",
        warehouses=warehouses,
        product_types=product_types,
        query_mode="ods",
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    total_filter, total_params = _warehouse_filter(warehouses, "total_warehouse", "s.`仓库`")
    total_type_filter, total_type_params = _product_type_filter(product_types, "total_type")
    total_params.update(total_type_params)
    total_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS product_count,
              COUNT(*) AS total_records,
              SUM(stock_quantity) AS stock_quantity,
              SUM(available_stock) AS available_stock,
              SUM(CASE WHEN stock_min > 0 AND available_stock < stock_min THEN 1 ELSE 0 END) AS below_min_count,
              SUM(CASE WHEN stock_max > 0 AND available_stock > stock_max THEN 1 ELSE 0 END) AS above_max_count,
              MAX(updated_at) AS updated_at
            FROM (
              SELECT
                s.`货品编号`,
                SUM(COALESCE(s.`库存数量`, 0)) AS stock_quantity,
                SUM(COALESCE(s.`可用库存`, 0)) AS available_stock,
                MAX(COALESCE(limits.`库存下限`, 0)) AS stock_min,
                MAX(COALESCE(limits.`库存上限`, 0)) AS stock_max,
                MAX(s.`updatetime`) AS updated_at
              FROM `分仓库查询` s
              LEFT JOIN (
                SELECT
                  `货品编号`,
                  MAX(COALESCE(`库存下限`, 0)) AS `库存下限`,
                  MAX(COALESCE(`库存上限`, 0)) AS `库存上限`
                FROM `总库存查询`
                GROUP BY `货品编号`
              ) limits ON limits.`货品编号` = s.`货品编号`
              WHERE 1 = 1
                {total_filter}
                {total_type_filter}
              GROUP BY s.`货品编号`
            ) inventory_products
            """
        ),
        total_params,
    ).mappings().one()

    warehouse_filter, warehouse_params = _warehouse_filter(warehouses, "split_warehouse")
    warehouse_type_filter, warehouse_type_params = _product_type_filter(product_types, "split_type")
    warehouse_params.update(warehouse_type_params)
    warehouse_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS warehouse_records,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
              MAX(`updatetime`) AS updated_at
            FROM `分仓库查询` s
            WHERE 1 = 1
              {warehouse_filter}
              {warehouse_type_filter}
            """
        ),
        warehouse_params,
    ).mappings().one()

    batch_filter, batch_params = _warehouse_filter(warehouses, "batch_warehouse")
    batch_type_filter, batch_type_params = _product_type_filter(product_types, "batch_type", "`货品分类`")
    batch_params.update(batch_type_params)
    batch_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS batch_records,
              SUM(CASE WHEN COALESCE(`剩余有效天数`, 999999) BETWEEN 0 AND 30 THEN 1 ELSE 0 END) AS expiring_batch_count,
              MAX(`updatetime`) AS updated_at
            FROM `批次货品库存查询`
            WHERE 1 = 1
              {batch_filter}
              {batch_type_filter}
            """
        ),
        batch_params,
    ).mappings().one()

    warehouse_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              COUNT(*) AS records,
              SUM(COALESCE(`库存数量`, 0)) AS stock_quantity,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount
            FROM `分仓库查询` s
            WHERE 1 = 1
              {warehouse_filter}
              {warehouse_type_filter}
            GROUP BY COALESCE(NULLIF(`仓库`, ''), '未归类')
            ORDER BY available_stock DESC
            LIMIT 12
            """
        ),
        warehouse_params,
    ).mappings().all()

    source_tables = [
        {
            "table": "分仓库查询",
            "records": _int(total_row["total_records"]),
            "usage": "库存概览、仓库维度库存、库存金额、销量",
            "key_fields": "仓库、货品编号、库存数量、可用库存、库存金额、近30天销量、库存上下限",
        },
        {
            "table": "批次货品库存查询",
            "records": _int(batch_row["batch_records"]),
            "usage": "库龄、效期、临期库存",
            "key_fields": "批次、生产日期、到期日期、剩余有效天数、库存数量",
        },
    ]

    updated_candidates = [total_row["updated_at"], warehouse_row["updated_at"], batch_row["updated_at"]]
    data = {
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "updated_at": max([value for value in updated_candidates if value is not None], default=None),
        "metrics": {
            "product_count": _int(total_row["product_count"]),
            "warehouse_records": _int(warehouse_row["warehouse_records"]),
            "batch_records": _int(batch_row["batch_records"]),
            "stock_quantity": _number(total_row["stock_quantity"]),
            "available_stock": _number(total_row["available_stock"]),
            "stock_amount": _number(warehouse_row["stock_amount"]),
            "below_min_count": _int(total_row["below_min_count"]),
            "above_max_count": _int(total_row["above_max_count"]),
            "expiring_batch_count": _int(batch_row["expiring_batch_count"]),
        },
        "source_tables": source_tables,
        "warehouses": [
            {
                "warehouse": _text(row["warehouse"], "未归类"),
                "records": _int(row["records"]),
                "stock_quantity": _number(row["stock_quantity"]),
                "available_stock": _number(row["available_stock"]),
                "stock_amount": _number(row["stock_amount"]),
            }
            for row in warehouse_rows
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/health")
def inventory_health(
    keyword: str | None = Query(None),
    barcode: str | None = Query(None),
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    issue_type: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    keyword = keyword.strip() if keyword else ""
    barcode = barcode.strip() if barcode else ""
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    page, page_size, offset = _pagination(page, page_size)
    cache_key = _cache_key(
        "health-v4",
        keyword=keyword,
        barcode=barcode,
        warehouses=warehouses,
        product_types=product_types,
        issue_type=issue_type,
        page=page,
        page_size=page_size,
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    keyword_sql, params = _keyword_filter(keyword)
    barcode_sql, barcode_params = _barcode_filter(barcode)
    params.update(barcode_params)
    warehouse_sql, warehouse_params = _warehouse_filter(warehouses)
    params.update(warehouse_params)
    product_type_sql, product_type_params = _product_type_filter(product_types, "health_type")
    params.update(product_type_params)
    params.update({"limit": page_size, "offset": offset})
    base_sql = f"""
      SELECT
        `货品编号` AS product_code,
        MAX(`条码`) AS barcode,
        MAX(`货品名称`) AS product,
        COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
        COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
        COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
        SUM(COALESCE(`库存数量`, 0)) AS stock,
        SUM(COALESCE(`可用库存`, 0)) AS available_stock,
        SUM(COALESCE(`近30天销量`, 0)) AS sales30,
        SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
        SUM(COALESCE(`库存金额`, 0)) AS stock_amount
      FROM `分仓库查询` s
      WHERE 1 = 1
        {keyword_sql}
        {barcode_sql}
        {warehouse_sql}
        {product_type_sql}
      GROUP BY
        `货品编号`,
        COALESCE(NULLIF(`品牌`, ''), '未归类'),
        COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
        COALESCE(NULLIF(`仓库`, ''), '未归类')
    """
    health_sql = f"""
      SELECT
        inventory_items.*,
        CASE
          WHEN available_stock < 0 THEN 'negative'
          WHEN COALESCE(NULLIF(barcode, ''), '') = '' THEN 'missing_barcode'
          WHEN stock > 0 AND available_stock <= 0 THEN 'out_of_stock'
          WHEN stock > 0 AND sales90 <= 0 THEN 'no_sales'
          WHEN sales30 > 0 AND available_stock / (sales30 / 30) < 14 THEN 'shortage'
          WHEN sales90 > 0 AND stock / (sales90 / 90) > 180 THEN 'overstock'
          ELSE 'healthy'
        END AS issue_type,
        CASE
          WHEN sales30 > 0 THEN ROUND(available_stock / (sales30 / 30), 1)
          ELSE NULL
        END AS available_days
      FROM ({base_sql}) inventory_items
    """
    issue_conditions = {
        "negative": "issue_type = 'negative'",
        "missing_barcode": "issue_type = 'missing_barcode'",
        "out_of_stock": "issue_type = 'out_of_stock'",
        "no_sales": "issue_type = 'no_sales'",
        "shortage": "issue_type = 'shortage'",
        "overstock": "issue_type = 'overstock'",
        "healthy": "issue_type = 'healthy'",
    }
    issue_where = issue_conditions.get(issue_type, "issue_type <> 'healthy'")

    metrics = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS item_count,
              SUM(issue_type = 'negative') AS negative_count,
              SUM(issue_type = 'missing_barcode') AS missing_barcode_count,
              SUM(issue_type = 'out_of_stock') AS out_of_stock_count,
              SUM(issue_type = 'no_sales') AS no_sales_count,
              SUM(issue_type = 'shortage') AS shortage_count,
              SUM(issue_type = 'overstock') AS overstock_count,
              SUM(issue_type = 'healthy') AS healthy_count
            FROM ({health_sql}) health_items
            """
        ),
        params,
    ).mappings().one()
    total = db.execute(
        text(f"SELECT COUNT(*) FROM ({health_sql}) health_items WHERE {issue_where}"),
        params,
    ).scalar_one()
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM ({health_sql}) health_items
            WHERE {issue_where}
            ORDER BY
              FIELD(issue_type, 'negative', 'out_of_stock', 'shortage', 'missing_barcode', 'no_sales', 'overstock'),
              stock_amount DESC,
              available_stock DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    issue_labels = {
        "negative": "负库存",
        "missing_barcode": "缺少条码",
        "out_of_stock": "可用库存为零",
        "no_sales": "90天无销量",
        "shortage": "不足14天",
        "overstock": "预计超180天",
        "healthy": "正常",
    }
    data = {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "issue_type": issue_type,
        "pagination": {"page": page, "page_size": page_size, "total": _int(total)},
        "metrics": {key: _int(value) for key, value in metrics.items()},
        "rows": [
            {
                "rank": offset + index + 1,
                "product_code": _text(row["product_code"]),
                "barcode": _text(row["barcode"]),
                "product": _text(row["product"], "未命名商品"),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "warehouse": _text(row["warehouse"], "未归类"),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "sales30": _number(row["sales30"]),
                "sales90": _number(row["sales90"]),
                "stock_amount": _number(row["stock_amount"]),
                "available_days": _number(row["available_days"]) if row["available_days"] is not None else None,
                "issue_type": _text(row["issue_type"]),
                "issue_label": issue_labels.get(_text(row["issue_type"]), "待检查"),
            }
            for index, row in enumerate(rows)
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/batch-expiry")
def batch_expiry_analysis(
    keyword: str | None = Query(None),
    barcode: str | None = Query(None),
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    expiry_range: str = Query("all"),
    page: int = Query(1, ge=1),
    long_page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    keyword = keyword.strip() if keyword else ""
    barcode = barcode.strip() if barcode else ""
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    page, page_size, offset = _pagination(page, page_size)
    long_page, _, long_offset = _pagination(long_page, page_size)
    cache_key = _cache_key(
        "batch-expiry-v6",
        keyword=keyword,
        barcode=barcode,
        warehouses=warehouses,
        product_types=product_types,
        expiry_range=expiry_range,
        page=page,
        long_page=long_page,
        page_size=page_size,
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    keyword_sql, params = _keyword_filter(keyword)
    barcode_sql, barcode_params = _barcode_filter(barcode)
    params.update(barcode_params)
    warehouse_sql, warehouse_params = _warehouse_filter(warehouses)
    params.update(warehouse_params)
    product_type_sql, product_type_params = _product_type_filter(product_types, "batch_expiry_type", "`货品分类`")
    params.update(product_type_params)
    params["limit"] = page_size
    params["offset"] = offset
    params["long_offset"] = long_offset
    common_where = f"""
      COALESCE(`可用库存`, 0) > 0
      {keyword_sql}
      {barcode_sql}
      {warehouse_sql}
      {product_type_sql}
    """

    metrics = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS batch_count,
              COUNT(DISTINCT `货品编号`) AS product_count,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(CASE WHEN `到期日期` < CURDATE() THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS expired_stock,
              SUM(CASE WHEN `到期日期` BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 6 MONTH)
                THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS within_6_months_stock,
              SUM(CASE WHEN `到期日期` BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 12 MONTH)
                THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS within_12_months_stock,
              SUM(CASE WHEN `到期日期` > DATE_ADD(CURDATE(), INTERVAL 24 MONTH)
                THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS over_24_months_stock,
              SUM(CASE WHEN `到期日期` IS NULL THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS missing_expiry_stock,
              MAX(`updatetime`) AS updated_at
            FROM `批次货品库存查询`
            WHERE {common_where}
            """
        ),
        params,
    ).mappings().one()

    expiry_sql = _expiry_filter(expiry_range, "expiry_date")
    raw_expiry_sql = _expiry_filter(expiry_range)
    filtered_total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM `批次货品库存查询`
            WHERE {common_where}
              {raw_expiry_sql}
            """
        ),
        params,
    ).scalar_one()
    fefo_rows = db.execute(
        text(
            f"""
            SELECT *
            FROM (
              SELECT
                COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
                `货品编号` AS product_code,
                `条码` AS barcode,
                `货品名称` AS product,
                COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
                COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类') AS product_type,
                COALESCE(NULLIF(`批次`, ''), '未标批次') AS batch,
                `生产日期` AS production_date,
                `到期日期` AS expiry_date,
                DATEDIFF(`到期日期`, CURDATE()) AS remaining_days,
                COALESCE(`库存数量`, 0) AS stock,
                COALESCE(`可用库存`, 0) AS available_stock,
                COUNT(*) OVER (
                  PARTITION BY COALESCE(NULLIF(`仓库`, ''), '未归类'), `货品编号`
                ) AS product_batch_count,
                ROW_NUMBER() OVER (
                  PARTITION BY COALESCE(NULLIF(`仓库`, ''), '未归类'), `货品编号`
                  ORDER BY CASE WHEN `到期日期` IS NULL THEN 1 ELSE 0 END, `到期日期`, `生产日期`, `批次`
                ) AS fefo_rank
              FROM `批次货品库存查询`
              WHERE {common_where}
            ) ranked_batches
            WHERE 1 = 1
              {expiry_sql}
            ORDER BY
              CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
              expiry_date,
              available_stock DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    long_expiry_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              `货品编号` AS product_code,
              MAX(`条码`) AS barcode,
              `货品名称` AS product,
              COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类') AS product_type,
              COUNT(*) AS batch_count,
              MIN(`到期日期`) AS nearest_expiry_date,
              MIN(DATEDIFF(`到期日期`, CURDATE())) AS nearest_remaining_days,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock
            FROM `批次货品库存查询`
            WHERE {common_where}
              AND `到期日期` > DATE_ADD(CURDATE(), INTERVAL 24 MONTH)
            GROUP BY
              COALESCE(NULLIF(`仓库`, ''), '未归类'),
              `货品编号`,
              `货品名称`,
              COALESCE(NULLIF(`品牌`, ''), '未归类'),
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类')
            ORDER BY available_stock DESC, nearest_expiry_date
            LIMIT :limit OFFSET :long_offset
            """
        ),
        params,
    ).mappings().all()
    long_expiry_total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse, `货品编号`
              FROM `批次货品库存查询`
              WHERE {common_where}
                AND `到期日期` > DATE_ADD(CURDATE(), INTERVAL 24 MONTH)
              GROUP BY COALESCE(NULLIF(`仓库`, ''), '未归类'), `货品编号`, COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类')
            ) long_expiry_products
            """
        ),
        params,
    ).scalar_one()

    def batch_status(remaining_days: object) -> str:
        if remaining_days is None:
            return "缺少到期日期"
        days = _int(remaining_days)
        if days < 0:
            return "已过期"
        if days <= 183:
            return "6个月内"
        if days <= 365:
            return "6-12个月"
        if days <= 730:
            return "12-24个月"
        return "24个月以上"

    data = {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "expiry_range": expiry_range,
        "pagination": {"page": page, "page_size": page_size, "total": _int(filtered_total)},
        "long_pagination": {"page": long_page, "page_size": page_size, "total": _int(long_expiry_total)},
        "updated_at": _date_text(metrics["updated_at"]),
        "metrics": {
            "batch_count": _int(metrics["batch_count"]),
            "product_count": _int(metrics["product_count"]),
            "available_stock": _number(metrics["available_stock"]),
            "expired_stock": _number(metrics["expired_stock"]),
            "within_6_months_stock": _number(metrics["within_6_months_stock"]),
            "within_12_months_stock": _number(metrics["within_12_months_stock"]),
            "over_24_months_stock": _number(metrics["over_24_months_stock"]),
            "missing_expiry_stock": _number(metrics["missing_expiry_stock"]),
        },
        "fefo_rows": [
            {
                "rank": offset + index + 1,
                "warehouse": _text(row["warehouse"], "未归类"),
                "product_code": _text(row["product_code"]),
                "barcode": _text(row["barcode"]),
                "product": _text(row["product"], "未命名商品"),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "batch": _text(row["batch"], "未标批次"),
                "production_date": _date_text(row["production_date"]),
                "expiry_date": _date_text(row["expiry_date"]),
                "remaining_days": _int(row["remaining_days"]) if row["remaining_days"] is not None else None,
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "product_batch_count": _int(row["product_batch_count"]),
                "fefo_rank": _int(row["fefo_rank"]),
                "status": batch_status(row["remaining_days"]),
            }
            for index, row in enumerate(fefo_rows)
        ],
        "long_expiry_rows": [
            {
                "rank": long_offset + index + 1,
                "warehouse": _text(row["warehouse"], "未归类"),
                "product_code": _text(row["product_code"]),
                "barcode": _text(row["barcode"]),
                "product": _text(row["product"], "未命名商品"),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "batch_count": _int(row["batch_count"]),
                "nearest_expiry_date": _date_text(row["nearest_expiry_date"]),
                "remaining_months": round(_number(row["nearest_remaining_days"]) / 30.4375, 1),
                "available_stock": _number(row["available_stock"]),
            }
            for index, row in enumerate(long_expiry_rows)
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/turnover")
def inventory_turnover(
    keyword: str | None = Query(None),
    barcode: str | None = Query(None),
    min_stock: int = Query(100, ge=0),
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    keyword = keyword.strip() if keyword else ""
    barcode = barcode.strip() if barcode else ""
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    page, page_size, offset = _pagination(page, page_size)
    cache_key = _cache_key("turnover-v9", keyword=keyword, barcode=barcode, min_stock=min_stock, warehouses=warehouses, product_types=product_types, page=page, page_size=page_size)
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    keyword_sql, params = _keyword_filter(keyword)
    barcode_sql, barcode_params = _barcode_filter(barcode)
    params.update(barcode_params)
    warehouse_sql, warehouse_params = _warehouse_filter(warehouses)
    params.update(warehouse_params)
    product_type_sql, product_type_params = _product_type_filter(product_types, "turnover_type")
    params.update(product_type_params)
    params["min_stock"] = min_stock
    params["limit"] = page_size
    params["offset"] = offset
    total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT `货品编号`, COALESCE(NULLIF(`仓库`, ''), '未归类')
              FROM `分仓库查询` s
              WHERE COALESCE(`库存数量`, 0) > 0
                {keyword_sql}
                {barcode_sql}
                {warehouse_sql}
                {product_type_sql}
              GROUP BY `货品编号`, `货品名称`, COALESCE(NULLIF(`品牌`, ''), '未归类'), COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'), COALESCE(NULLIF(`仓库`, ''), '未归类')
              HAVING SUM(COALESCE(`库存数量`, 0)) >= :min_stock
            ) turnover_products
            """
        ),
        params,
    ).scalar_one()
    rows = db.execute(
        text(
            f"""
            SELECT
              `货品编号` AS product_code,
              MAX(`条码`) AS barcode,
              `货品名称` AS product,
              COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              SUM(COALESCE(`库存数量`, 0)) AS stock,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(`近30天销量`, 0)) AS sales30,
              0 AS total_sales,
              CASE
                WHEN SUM(COALESCE(`近30天销量`, 0)) > 0
                  THEN ROUND(SUM(COALESCE(`库存数量`, 0)) / (SUM(COALESCE(`近30天销量`, 0)) / 30), 1)
                ELSE NULL
              END AS turnover_days
            FROM `分仓库查询` s
            WHERE COALESCE(`库存数量`, 0) > 0
              {keyword_sql}
              {barcode_sql}
              {warehouse_sql}
              {product_type_sql}
            GROUP BY `货品编号`, `货品名称`, COALESCE(NULLIF(`品牌`, ''), '未归类'), COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'), COALESCE(NULLIF(`仓库`, ''), '未归类')
            HAVING SUM(COALESCE(`库存数量`, 0)) >= :min_stock
            ORDER BY COALESCE(turnover_days, 999999) DESC, stock DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    data = {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "min_stock": min_stock,
        "pagination": {"page": page, "page_size": page_size, "total": _int(total)},
        "rows": [
            {
                "rank": offset + index + 1,
                "product_code": _text(row["product_code"]),
                "barcode": _text(row["barcode"]),
                "product": _text(row["product"], "未命名商品"),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "warehouse": _text(row["warehouse"], "未归类"),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "sales30": _number(row["sales30"]),
                "total_sales": _number(row["total_sales"]),
                "turnover_days": _number(row["turnover_days"]) if row["turnover_days"] is not None else None,
                "status": "无销量" if row["turnover_days"] is None else "正常" if _number(row["turnover_days"]) <= 90 else "偏慢" if _number(row["turnover_days"]) <= 180 else "过慢",
            }
            for index, row in enumerate(rows)
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/brand-turnover")
def inventory_brand_turnover(
    year: int | None = Query(None, ge=2000, le=2100),
    quarter: int | None = Query(None, ge=1, le=4),
    keyword: str | None = Query(None),
    min_stock: int = Query(100, ge=0),
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    """Estimate quarterly brand turnover using current stock as the ending-stock proxy."""
    today = date.today()
    current_quarter = (today.month - 1) // 3 + 1
    default_year = today.year if current_quarter > 1 else today.year - 1
    default_quarter = current_quarter - 1 if current_quarter > 1 else 4
    if year is None or quarter is None:
        year = default_year
        quarter = default_quarter
    keyword = keyword.strip() if keyword else ""
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    page, page_size, offset = _pagination(page, page_size)
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start_date = date(year, start_month, 1)
    end_date = date(year, end_month, monthrange(year, end_month)[1])
    period_days = (end_date - start_date).days + 1
    cache_key = _cache_key(
        "brand-turnover-v12",
        year=year,
        quarter=quarter,
        keyword=keyword,
        min_stock=min_stock,
        warehouses=warehouses,
        product_types=product_types,
        page=page,
        page_size=page_size,
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params: dict[str, object] = {"start_date": start_date, "end_date": end_date}
    brand_sql = ""
    if keyword:
        params["brand_keyword"] = keyword
        brand_sql = "AND COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类') = :brand_keyword"

    stock_warehouse_sql, stock_warehouse_params = _warehouse_filter(
        warehouses, "brand_stock_warehouse", "s.`仓库`"
    )
    sales_warehouse_sql, sales_warehouse_params = _warehouse_filter(
        warehouses, "brand_sales_warehouse", "s.`发货仓库`"
    )
    stock_type_sql, stock_type_params = _product_type_filter(
        product_types, "brand_stock_type", "s.`货品分类`"
    )
    sales_type_sql, sales_type_params = _product_type_filter(
        product_types, "brand_sales_type", "s.`货品分类`"
    )
    params.update(stock_warehouse_params)
    params.update(sales_warehouse_params)
    params.update(stock_type_params)
    params.update(sales_type_params)

    stock_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类') AS brand,
              SUM(COALESCE(s.`库存数量`, 0)) AS ending_stock,
              SUM(COALESCE(s.`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(s.`库存金额`, 0)) AS inventory_amount,
              MAX(s.`updatetime`) AS snapshot_at
            FROM `分仓库查询` s
            WHERE COALESCE(s.`库存数量`, 0) > 0
              {brand_sql}
              {stock_warehouse_sql}
              {stock_type_sql}
            GROUP BY COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')
            """
        ),
        params,
    ).mappings().all()
    sales_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类') AS brand,
              COUNT(DISTINCT s.`订单编号`) AS orders,
              SUM(COALESCE(s.`数量`, 0)) AS net_sales_quantity,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS net_sales_amount
            FROM `销售单明细账` s
            WHERE s.`下单时间` >= :start_date
              AND s.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              {brand_sql}
              {sales_warehouse_sql}
              {sales_type_sql}
            GROUP BY COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')
            """
        ),
        params,
    ).mappings().all()

    product_stock_rows = []
    product_sales_rows = []
    if keyword:
        product_stock_rows = db.execute(
            text(
                f"""
                SELECT
                  CONCAT(
                    MAX(COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')), '|',
                    MAX(COALESCE(NULLIF(TRIM(s.`货品编号`), ''), CONCAT('NAME:', COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品'))))
                  ) AS product_key,
                  MAX(s.`货品编号`) AS product_code,
                  MAX(s.`货品名称`) AS product,
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
                  SUM(COALESCE(s.`可用库存`, 0)) AS available_stock
                FROM `分仓库查询` s
                WHERE COALESCE(s.`库存数量`, 0) > 0
                  {brand_sql}
                  {stock_warehouse_sql}
                  {stock_type_sql}
                GROUP BY
                  COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品编号`), ''), CONCAT('NAME:', COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品')))
                """
            ),
            params,
        ).mappings().all()
        product_sales_rows = db.execute(
            text(
                f"""
                SELECT
                  CONCAT(
                    MAX(COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')), '|',
                    MAX(COALESCE(NULLIF(TRIM(s.`货品编号`), ''), CONCAT('NAME:', COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品'))))
                  ) AS product_key,
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
                  SUM(COALESCE(s.`数量`, 0)) AS net_sales_quantity
                FROM `销售单明细账` s
                WHERE s.`下单时间` >= :start_date
                  AND s.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
                  {brand_sql}
                  {sales_warehouse_sql}
                  {sales_type_sql}
                GROUP BY
                  COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品编号`), ''), CONCAT('NAME:', COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品')))
                """
            ),
            params,
        ).mappings().all()

    stock_by_brand = {row["brand"]: row for row in stock_rows}
    sales_by_brand = {row["brand"]: row for row in sales_rows}
    merged_rows = []
    for brand in set(stock_by_brand) | set(sales_by_brand):
        stock_row = stock_by_brand.get(brand, {})
        sales_row = sales_by_brand.get(brand, {})
        ending_stock = _number(stock_row.get("ending_stock"))
        net_sales_quantity = _number(sales_row.get("net_sales_quantity"))
        available_stock = _number(stock_row.get("available_stock"))
        turnover_rate = net_sales_quantity / available_stock if available_stock > 0 and net_sales_quantity > 0 else None
        turnover_days = period_days / turnover_rate if turnover_rate else None
        if available_stock <= 0 and net_sales_quantity > 0:
            status = "缺货风险"
        elif net_sales_quantity <= 0:
            status = "无销售"
        elif turnover_days <= 90:
            status = "正常"
        elif turnover_days <= 180:
            status = "偏慢"
        else:
            status = "过慢"
        merged_rows.append(
            {
                "brand": _text(brand, "未归类"),
                "ending_stock": ending_stock,
                "available_stock": available_stock,
                "inventory_amount": _number(stock_row.get("inventory_amount")),
                "orders": _int(sales_row.get("orders")),
                "net_sales_quantity": net_sales_quantity,
                "net_sales_amount": _number(sales_row.get("net_sales_amount")),
                "turnover_rate": round(turnover_rate, 4) if turnover_rate is not None else None,
                "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
                "snapshot_at": _date_text(stock_row.get("snapshot_at")),
                "status": status,
            }
        )

    if min_stock > 0:
        merged_rows = [row for row in merged_rows if row["available_stock"] >= min_stock]

    merged_rows.sort(
        key=lambda row: (
            row["turnover_days"] is None,
            row["turnover_days"] or 0,
            row["available_stock"],
        ),
        reverse=True,
    )
    for index, row in enumerate(merged_rows):
        row["rank"] = index + 1
    total = len(merged_rows)
    paged_rows = merged_rows[offset : offset + page_size]

    total_stock = sum(row["ending_stock"] for row in merged_rows)
    total_available_stock = sum(row["available_stock"] for row in merged_rows)
    total_sales_quantity = sum(row["net_sales_quantity"] for row in merged_rows)
    total_turnover_rate = (
        total_sales_quantity / total_available_stock
        if total_available_stock > 0 and total_sales_quantity > 0
        else None
    )
    total_turnover_days = period_days / total_turnover_rate if total_turnover_rate else None
    snapshot_at = max((row["snapshot_at"] for row in merged_rows if row["snapshot_at"]), default=None)
    product_sales_by_key = {row["product_key"]: _number(row["net_sales_quantity"]) for row in product_sales_rows}
    product_turnover_rows = []
    for row in product_stock_rows:
        available_stock = _number(row["available_stock"])
        net_sales_quantity = product_sales_by_key.get(row["product_key"], 0)
        turnover_rate = net_sales_quantity / available_stock if available_stock > 0 and net_sales_quantity > 0 else None
        turnover_days = period_days / turnover_rate if turnover_rate else None
        if available_stock <= 0:
            status = "无可用库存"
        elif net_sales_quantity <= 0:
            status = "无销售"
        elif turnover_days <= 90:
            status = "正常"
        elif turnover_days <= 180:
            status = "偏慢"
        else:
            status = "过慢"
        product_turnover_rows.append(
            {
                "product_key": _text(row["product_key"]),
                "product_code": _text(row["product_code"]),
                "product": _text(row["product"], "未命名商品"),
                "product_type": _text(row["product_type"], "未归类"),
                "available_stock": available_stock,
                "net_sales_quantity": net_sales_quantity,
                "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
                "status": status,
            }
        )

    def build_product_panel(label: str, type_names: tuple[str, ...]) -> dict:
        rows = [row for row in product_turnover_rows if row["product_type"] in type_names]
        total_available_stock = sum(row["available_stock"] for row in rows)
        total_net_sales_quantity = sum(row["net_sales_quantity"] for row in rows)
        average_turnover_days = (
            period_days * total_available_stock / total_net_sales_quantity
            if total_available_stock > 0 and total_net_sales_quantity > 0
            else None
        )
        rows.sort(key=lambda row: row["available_stock"], reverse=True)
        return {
            "label": label,
            "total_available_stock": total_available_stock,
            "average_turnover_days": round(average_turnover_days, 1) if average_turnover_days is not None else None,
            "rows": rows[:10],
        }

    product_turnover_panels = []
    if keyword:
        product_turnover_rows.sort(key=lambda row: row["available_stock"], reverse=True)
        product_turnover_panels = [
            build_product_panel("正装 + 小样", ("正装", "小样")),
            build_product_panel("正装", ("正装",)),
            build_product_panel("小样", ("小样",)),
        ]
    data = {
        "year": year,
        "quarter": quarter,
        "period": f"{year} Q{quarter}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "period_days": period_days,
        "basis": "ending_stock_proxy",
        "snapshot_at": snapshot_at,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "min_stock": min_stock,
        "summary": {
            "brand_count": total,
            "ending_stock": total_stock,
            "available_stock": total_available_stock,
            "net_sales_quantity": total_sales_quantity,
            "turnover_rate": round(total_turnover_rate, 4) if total_turnover_rate is not None else None,
            "turnover_days": round(total_turnover_days, 1) if total_turnover_days is not None else None,
            "attention_brands": sum(1 for row in merged_rows if row["status"] in {"偏慢", "过慢", "无销售"}),
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "chart_rows": merged_rows,
        "product_turnover_panels": product_turnover_panels,
        "product_turnover_rows": product_turnover_rows,
        "rows": paged_rows,
    }
    return _cached_ok(cache_key, data)


@router.get("/slow-moving")
def slow_moving_inventory(
    keyword: str | None = Query(None),
    barcode: str | None = Query(None),
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    keyword = keyword.strip() if keyword else ""
    barcode = barcode.strip() if barcode else ""
    warehouses = _normalize_warehouses(warehouse)
    product_types = _normalize_product_types(product_type)
    page, page_size, offset = _pagination(page, page_size)
    cache_key = _cache_key("slow-moving-v7", keyword=keyword, barcode=barcode, warehouses=warehouses, product_types=product_types, page=page, page_size=page_size)
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    keyword_sql, params = _keyword_filter(keyword)
    barcode_sql, barcode_params = _barcode_filter(barcode)
    params.update(barcode_params)
    warehouse_sql, warehouse_params = _warehouse_filter(warehouses)
    params.update(warehouse_params)
    product_type_sql, product_type_params = _product_type_filter(product_types, "slow_type")
    params.update(product_type_params)
    params["limit"] = page_size
    params["offset"] = offset
    total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT `货品编号`
              FROM `分仓库查询` s
              WHERE COALESCE(`库存数量`, 0) > 0
                {keyword_sql}
                {barcode_sql}
                {warehouse_sql}
                {product_type_sql}
              GROUP BY `货品编号`, `货品名称`, COALESCE(NULLIF(`品牌`, ''), '未归类'), COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类')
            ) slow_products
            """
        ),
        params,
    ).scalar_one()
    rows = db.execute(
        text(
            f"""
            SELECT
              `货品编号` AS product_code,
              MAX(`条码`) AS barcode,
              `货品名称` AS product,
              COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
              COUNT(DISTINCT COALESCE(NULLIF(`仓库`, ''), '未归类')) AS warehouse_count,
              SUM(COALESCE(`库存数量`, 0)) AS stock,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(`近30天销量`, 0)) AS sales30,
              SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount
            FROM `分仓库查询` s
            WHERE COALESCE(`库存数量`, 0) > 0
              {keyword_sql}
              {barcode_sql}
              {warehouse_sql}
              {product_type_sql}
            GROUP BY `货品编号`, `货品名称`, COALESCE(NULLIF(`品牌`, ''), '未归类'), COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类')
            ORDER BY sales90 ASC, sales30 ASC, stock_amount DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    data = {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "pagination": {"page": page, "page_size": page_size, "total": _int(total)},
        "rows": [
            {
                "rank": offset + index + 1,
                "product_code": _text(row["product_code"]),
                "barcode": _text(row["barcode"]),
                "product": _text(row["product"], "未命名商品"),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "warehouse_count": _int(row["warehouse_count"]),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "sales30": _number(row["sales30"]),
                "sales90": _number(row["sales90"]),
                "stock_amount": _number(row["stock_amount"]),
            }
            for index, row in enumerate(rows)
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/brand-monthly-arrivals")
def brand_monthly_arrivals(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    brand: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    warehouse: list[str] | None = Query(None),
    detail_product_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    """Brand receipt dashboard with exact day-level filters and traceable receipt details."""
    del current_user
    brands = tuple(sorted({value.strip() for value in brand or [] if value.strip()}))
    product_types = tuple(sorted({value.strip() for value in product_type or [] if value.strip()}))
    warehouses = tuple(sorted({value.strip() for value in warehouse or [] if value.strip()}))
    detail_product_type = (detail_product_type or "").strip()
    page, page_size, offset = _pagination(page, page_size)

    today = date.today()
    selected_start = start_date or date(today.year, 1, 1)
    selected_end = end_date or date(today.year, 12, 31)
    if selected_end < selected_start:
        selected_start, selected_end = selected_end, selected_start
    end_exclusive = selected_end + timedelta(days=1)
    cache_key = _cache_key(
        "brand-monthly-arrivals-v3",
        start_date=selected_start.isoformat(),
        end_date=selected_end.isoformat(),
        brands=brands,
        product_types=product_types,
        warehouses=warehouses,
        detail_product_type=detail_product_type,
        page=page,
        page_size=page_size,
    )
    cached = _get_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params: dict[str, object] = {
        "start_date": selected_start,
        "end_date": end_exclusive,
    }
    brand_sql = ""
    if brands:
        placeholders = []
        for index, value in enumerate(brands):
            key = f"brand_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        joined_placeholders = ", ".join(placeholders)
        brand_sql = f"AND d.`品牌` IN ({joined_placeholders})"

    product_type_sql = ""
    if product_types:
        placeholders = []
        for index, value in enumerate(product_types):
            key = f"product_type_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        product_type_sql = f"AND COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') IN ({', '.join(placeholders)})"

    warehouse_sql = ""
    if warehouses:
        placeholders = []
        for index, value in enumerate(warehouses):
            key = f"warehouse_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        warehouse_sql = f"AND COALESCE(NULLIF(TRIM(h.`入库仓库`), ''), '未设置') IN ({', '.join(placeholders)})"

    common_filter = f"""
      h.`入库时间` >= :start_date
      AND h.`入库时间` < :end_date
      {brand_sql}
      {product_type_sql}
      {warehouse_sql}
    """

    option_rows = db.execute(
        text(
            """
            SELECT DISTINCT
              YEAR(h.`入库时间`) AS receipt_year,
              d.`品牌` AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(TRIM(h.`入库仓库`), ''), '未设置') AS warehouse
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE h.`入库时间` IS NOT NULL
            ORDER BY receipt_year DESC, brand ASC, product_type ASC, warehouse ASC
            """
        )
    ).mappings().all()

    summary = db.execute(
        text(
            f"""
            SELECT
              COALESCE(SUM(d.`数量`), 0) AS net_quantity,
              COALESCE(SUM(d.`入库成本金额`), 0) AS net_cost_amount,
              COUNT(DISTINCT NULLIF(d.`品牌`, '')) AS brand_count,
              COUNT(DISTINCT h.`docId`) AS document_count,
              COUNT(DISTINCT NULLIF(d.`货品编号`, '')) AS sku_count,
              COUNT(DISTINCT NULLIF(h.`往来单位`, '')) AS supplier_count,
              MAX(GREATEST(COALESCE(h.`updatetime`, h.`入库时间`), COALESCE(d.`updatetime`, h.`入库时间`))) AS updated_at
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
            """
        ),
        params,
    ).mappings().one()

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(h.`入库时间`) AS receipt_date,
              COALESCE(SUM(d.`数量`), 0) AS net_quantity,
              COALESCE(SUM(d.`入库成本金额`), 0) AS net_cost_amount,
              COALESCE(SUM(CASE WHEN TRIM(d.`货品分类`) = '正装' THEN d.`数量` ELSE 0 END), 0) AS full_size_quantity,
              COALESCE(SUM(CASE WHEN TRIM(d.`货品分类`) = '小样' THEN d.`数量` ELSE 0 END), 0) AS sample_quantity
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
            GROUP BY DATE(h.`入库时间`)
            ORDER BY receipt_date
            """
        ),
        params,
    ).mappings().all()

    product_type_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(SUM(d.`数量`), 0) AS net_quantity,
              COALESCE(SUM(d.`入库成本金额`), 0) AS net_cost_amount,
              COUNT(DISTINCT h.`docId`) AS document_count,
              COUNT(DISTINCT NULLIF(d.`货品编号`, '')) AS sku_count
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
            GROUP BY COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')
            ORDER BY net_quantity DESC
            """
        ),
        params,
    ).mappings().all()

    product_rows = db.execute(
        text(
            f"""
            SELECT
              d.`货品编号` AS product_code,
              d.`货品名称` AS product,
              d.`品牌` AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(SUM(d.`数量`), 0) AS net_quantity,
              COALESCE(SUM(d.`入库成本金额`), 0) AS net_cost_amount,
              COUNT(DISTINCT h.`docId`) AS document_count,
              MIN(DATE(h.`入库时间`)) AS first_receipt_date,
              MAX(DATE(h.`入库时间`)) AS last_receipt_date
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
            GROUP BY d.`货品编号`, d.`货品名称`, d.`品牌`, COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')
            HAVING net_quantity <> 0 OR net_cost_amount <> 0
            ORDER BY net_quantity DESC, net_cost_amount DESC
            LIMIT 15
            """
        ),
        params,
    ).mappings().all()

    brand_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(d.`品牌`, ''), '未归类') AS brand,
              COALESCE(SUM(CASE WHEN d.`数量` > 0 THEN d.`数量` ELSE 0 END), 0) AS gross_quantity,
              COALESCE(ABS(SUM(CASE WHEN d.`数量` < 0 THEN d.`数量` ELSE 0 END)), 0) AS reversal_quantity,
              COALESCE(SUM(d.`数量`), 0) AS net_quantity,
              COALESCE(SUM(d.`入库成本金额`), 0) AS net_cost_amount,
              COUNT(DISTINCT h.`docId`) AS document_count,
              COUNT(DISTINCT NULLIF(d.`货品编号`, '')) AS sku_count,
              COUNT(DISTINCT NULLIF(h.`往来单位`, '')) AS supplier_count
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
            GROUP BY COALESCE(NULLIF(d.`品牌`, ''), '未归类')
            ORDER BY net_cost_amount DESC, net_quantity DESC
            """
        ),
        params,
    ).mappings().all()

    detail_type_sql = ""
    if detail_product_type in {"正装", "小样"}:
        params["detail_product_type"] = detail_product_type
        detail_type_sql = "AND TRIM(d.`货品分类`) = :detail_product_type"
    detail_total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
              {detail_type_sql}
            """
        ),
        params,
    ).scalar_one()
    detail_params = {**params, "limit": page_size, "offset": offset}
    detail_rows = db.execute(
        text(
            f"""
            SELECT
              h.`入库时间` AS receipt_time,
              h.`入库单号` AS receipt_number,
              h.`入库类型` AS receipt_type,
              h.`入库仓库` AS warehouse,
              h.`往来单位` AS supplier,
              h.`红冲状态` AS reversal_status,
              d.`货品编号` AS product_code,
              d.`货品名称` AS product,
              d.`品牌` AS brand,
              d.`货品分类` AS product_type,
              d.`数量` AS quantity,
              d.`入库成本单价` AS unit_cost,
              d.`入库成本金额` AS cost_amount,
              d.`批次` AS batch,
              d.`生产日期` AS production_date,
              d.`到期日期` AS expiry_date
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE {common_filter}
              {detail_type_sql}
            ORDER BY h.`入库时间` DESC, h.`入库单号` DESC, d.`recId` DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        detail_params,
    ).mappings().all()

    total_cost = _number(summary["net_cost_amount"])
    is_full_year = selected_start == date(selected_start.year, 1, 1) and selected_end == date(selected_start.year, 12, 31)
    is_current_year_to_date = selected_start == date(today.year, 1, 1) and selected_end == today
    data = {
        "year": selected_start.year,
        "period": "本年" if is_current_year_to_date else (f"{selected_start.year}年" if is_full_year else "自定义"),
        "start_date": selected_start.isoformat(),
        "end_date": selected_end.isoformat(),
        "brands_selected": list(brands),
        "product_types_selected": list(product_types),
        "warehouses_selected": list(warehouses),
        "detail_product_type": detail_product_type,
        "updated_at": summary["updated_at"].isoformat() if summary["updated_at"] else None,
        "filter_options": {
            "years": sorted({_int(row["receipt_year"]) for row in option_rows}, reverse=True),
            "brands": sorted({_text(row["brand"]) for row in option_rows if row["brand"]}),
            "product_types": sorted({_text(row["product_type"]) for row in option_rows if row["product_type"]}),
            "warehouses": sorted({_text(row["warehouse"]) for row in option_rows if row["warehouse"]}),
        },
        "summary": {
            "net_quantity": _number(summary["net_quantity"]),
            "net_cost_amount": total_cost,
            "brand_count": _int(summary["brand_count"]),
            "document_count": _int(summary["document_count"]),
            "sku_count": _int(summary["sku_count"]),
            "supplier_count": _int(summary["supplier_count"]),
        },
        "trend": [
            {
                "receipt_date": row["receipt_date"].isoformat(),
                "net_quantity": _number(row["net_quantity"]),
                "net_cost_amount": _number(row["net_cost_amount"]),
                "full_size_quantity": _number(row["full_size_quantity"]),
                "sample_quantity": _number(row["sample_quantity"]),
            }
            for row in trend_rows
        ],
        "product_type_summary": [
            {
                "product_type": _text(row["product_type"], "未归类"),
                "net_quantity": _number(row["net_quantity"]),
                "net_cost_amount": _number(row["net_cost_amount"]),
                "document_count": _int(row["document_count"]),
                "sku_count": _int(row["sku_count"]),
            }
            for row in product_type_rows
        ],
        "products": [
            {
                "rank": index + 1,
                "product_code": _text(row["product_code"]),
                "product": _text(row["product"]),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "net_quantity": _number(row["net_quantity"]),
                "net_cost_amount": _number(row["net_cost_amount"]),
                "document_count": _int(row["document_count"]),
                "first_receipt_date": row["first_receipt_date"].isoformat() if row["first_receipt_date"] else None,
                "last_receipt_date": row["last_receipt_date"].isoformat() if row["last_receipt_date"] else None,
            }
            for index, row in enumerate(product_rows)
        ],
        "brands": [
            {
                "rank": index + 1,
                "brand": _text(row["brand"], "未归类"),
                "gross_quantity": _number(row["gross_quantity"]),
                "reversal_quantity": _number(row["reversal_quantity"]),
                "net_quantity": _number(row["net_quantity"]),
                "net_cost_amount": _number(row["net_cost_amount"]),
                "share": round(_number(row["net_cost_amount"]) / total_cost * 100, 2) if total_cost else 0,
                "brand_document_count": _int(row["document_count"]),
                "monthly_sku_count": _int(row["sku_count"]),
                "monthly_supplier_count": _int(row["supplier_count"]),
            }
            for index, row in enumerate(brand_rows)
        ],
        "pagination": {"page": page, "page_size": page_size, "total": _int(detail_total)},
        "details": [
            {
                "receipt_time": row["receipt_time"].isoformat() if row["receipt_time"] else None,
                "receipt_number": _text(row["receipt_number"]),
                "receipt_type": _text(row["receipt_type"]),
                "warehouse": _text(row["warehouse"]),
                "supplier": _text(row["supplier"]),
                "reversal_status": _text(row["reversal_status"]),
                "product_code": _text(row["product_code"]),
                "product": _text(row["product"]),
                "brand": _text(row["brand"], "未归类"),
                "product_type": _text(row["product_type"], "未归类"),
                "quantity": _number(row["quantity"]),
                "unit_cost": _number(row["unit_cost"]),
                "cost_amount": _number(row["cost_amount"]),
                "batch": _text(row["batch"]),
                "production_date": row["production_date"].isoformat() if row["production_date"] else None,
                "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
            }
            for row in detail_rows
        ],
    }
    return _cached_ok(cache_key, data)
