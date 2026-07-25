from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.ods import get_ods_db
from app.models.user import User
from app.schemas.common import ok
from app.services.sales_sources import SALES_ORDER_TABLE_SQL


router = APIRouter(prefix="/sales", tags=["sales"])

RANGE_OPTIONS = {
    "last_30": "近30天",
    "this_month": "本月",
    "this_year": "本年",
}

ACTIVE_SALES_ORDER_SQL = "COALESCE(`订单状态`, '') NOT LIKE '%取消%'"
POSITIVE_SALES_ORDER_COUNT_SQL = "COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END)"
SALES_CACHE_TTL_SECONDS = 300
SALES_CACHE_MAX_ITEMS = 256
_sales_cache: dict[tuple, tuple[float, dict]] = {}
_sales_cache_lock = Lock()


def _cache_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(_cache_value(item) for item in value))
    return value


def _sales_cache_key(endpoint: str, **params: object) -> tuple:
    return (endpoint, tuple(sorted((key, _cache_value(value)) for key, value in params.items())))


def _get_sales_cache(key: tuple) -> dict | None:
    now = monotonic()
    with _sales_cache_lock:
        cached = _sales_cache.get(key)
        if cached is None:
            return None

        expires_at, data = cached
        if expires_at <= now:
            _sales_cache.pop(key, None)
            return None

        return deepcopy(data)


def _set_sales_cache(key: tuple, data: dict) -> None:
    now = monotonic()
    with _sales_cache_lock:
        if len(_sales_cache) >= SALES_CACHE_MAX_ITEMS:
            expired_keys = [cache_key for cache_key, (expires_at, _) in _sales_cache.items() if expires_at <= now]
            for cache_key in expired_keys:
                _sales_cache.pop(cache_key, None)
            if len(_sales_cache) >= SALES_CACHE_MAX_ITEMS:
                oldest_key = min(_sales_cache, key=lambda cache_key: _sales_cache[cache_key][0])
                _sales_cache.pop(oldest_key, None)

        _sales_cache[key] = (now + SALES_CACHE_TTL_SECONDS, deepcopy(data))


def _cached_ok(key: tuple, data: dict) -> dict:
    _set_sales_cache(key, data)
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


def _is_online_sales_channel(category: object, platform: object, channel_name: object) -> bool:
    """Classify sales channels using the confirmed business rules."""
    category_text = str(category or "").strip() or "未分类"
    platform_text = str(platform or "").strip() or "未设置"
    channel_text = str(channel_name or "").strip() or "未归类"
    if category_text == "销售部渠道":
        return False
    if category_text == "运营部线上渠道":
        return channel_text != "桢植线下快闪店"
    if category_text == "梧颜":
        return platform_text != "未设置"
    if channel_text.startswith("渠道预留"):
        return False
    if channel_text.startswith("海旅"):
        return True
    return platform_text != "未设置" or any(
        keyword in channel_text for keyword in ("快手", "微店", "微信小店", "抖店")
    )


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _range_bounds(
    range_key: str,
    as_of: date,
    custom_start_date: date | None,
    custom_end_date: date | None,
) -> tuple[date, date, str, str]:
    if custom_start_date or custom_end_date:
        if not custom_start_date or not custom_end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date must be used together")
        if custom_start_date > custom_end_date:
            raise HTTPException(status_code=400, detail="start_date cannot be later than end_date")
        return custom_start_date, custom_end_date, "自定义", "custom"

    if range_key not in RANGE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported sales range: {range_key}")

    if range_key == "last_30":
        return as_of - timedelta(days=29), as_of, RANGE_OPTIONS[range_key], range_key

    if range_key == "this_year":
        return date(as_of.year, 1, 1), as_of, RANGE_OPTIONS[range_key], range_key

    return date(as_of.year, as_of.month, 1), as_of, RANGE_OPTIONS[range_key], range_key


def _empty_sales_payload(range_key: str, start_date: date | None, end_date: date | None) -> dict:
    return {
        "as_of": None,
        "period": RANGE_OPTIONS.get(range_key, "近30天"),
        "range": "custom" if start_date or end_date else range_key,
        "start_date": None,
        "end_date": None,
    }


def _resolve_sales_period(
    db: Session,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[dict, dict] | tuple[None, dict]:
    max_date = db.execute(
        text(f"SELECT MAX(`下单时间`) FROM {SALES_ORDER_TABLE_SQL} WHERE {ACTIVE_SALES_ORDER_SQL}")
    ).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return None, _empty_sales_payload(range_key, start_date, end_date)

    resolved_start, resolved_end, period, applied_range = _range_bounds(range_key, as_of, start_date, end_date)
    meta = {
        "as_of": as_of.isoformat(),
        "period": period,
        "range": applied_range,
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
    }
    params = {"start_date": resolved_start, "end_date": resolved_end}
    return params, meta


def _resolve_detail_sales_period(
    db: Session,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[dict, dict] | tuple[None, dict]:
    max_date = db.execute(text("SELECT MAX(`下单时间`) FROM `销售单明细账`")).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return None, _empty_sales_payload(range_key, start_date, end_date)

    resolved_start, resolved_end, period, applied_range = _range_bounds(range_key, as_of, start_date, end_date)
    meta = {
        "as_of": as_of.isoformat(),
        "period": period,
        "range": applied_range,
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
    }
    params = {"start_date": resolved_start, "end_date": resolved_end}
    return params, meta


def _sales_query_summary(db: Session, params: dict) -> dict:
    row = db.execute(
        text(
            f"""
            SELECT
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            """
        ),
        params,
    ).mappings().one()
    return {
        "paid_amount": _number(row["paid_amount"]),
        "orders": _int(row["orders"]),
        "quantity": _int(row["quantity"]),
    }


@router.get("/overview")
def sales_overview(
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    cache_key = _sales_cache_key("overview", range=range, start_date=start_date, end_date=end_date)
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_sales_period(db, range, start_date, end_date)
    if params is None:
        data = {
            **meta,
            "metrics": {
                "paid_amount": 0,
                "orders": 0,
                "quantity": 0,
                "avg_order_amount": 0,
            },
            "trend": [],
            "channels": [],
        }
        return _cached_ok(cache_key, data)

    metrics = _sales_query_summary(db, params)

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS day,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY DATE(`下单时间`)
            ORDER BY day
            """
        ),
        params,
    ).mappings().all()

    channel_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY paid_amount DESC
            LIMIT 10
            """
        ),
        params,
    ).mappings().all()

    orders = metrics["orders"]
    paid_amount = metrics["paid_amount"]
    quantity = metrics["quantity"]
    avg_order_amount = paid_amount / orders if orders else 0

    data = {
        **meta,
        "metrics": {
            "paid_amount": paid_amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": avg_order_amount,
        },
        "trend": [
            {
                "date": row["day"].isoformat(),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
            }
            for row in trend_rows
        ],
        "channels": [
            {
                "channel": row["channel"],
                "orders": orders_count,
                "paid_amount": channel_paid_amount,
                "quantity": quantity_count,
                "share": channel_paid_amount / paid_amount * 100 if paid_amount else 0,
                "avg_order_amount": channel_paid_amount / orders_count if orders_count else 0,
            }
            for row in channel_rows
            for orders_count in [_int(row["orders"])]
            for channel_paid_amount in [_number(row["paid_amount"])]
            for quantity_count in [_int(row["quantity"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/detail")
def sales_detail(
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    keyword: str | None = Query(None),
    channel: str | None = Query(None),
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    cache_key = _sales_cache_key(
        "detail",
        range=range,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
        keyword=keyword,
        channel=channel,
        status=status,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(cache_key, {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": [], "total": 0})

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
        ACTIVE_SALES_ORDER_SQL,
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("(`订单编号` LIKE :keyword OR `货品摘要` LIKE :keyword)")
    if channel:
        params["channel"] = channel
        filters.append("COALESCE(NULLIF(`销售渠道`, ''), '未归类') = :channel")
    if status:
        params["status"] = status
        filters.append("COALESCE(NULLIF(`订单状态`, ''), '未知') = :status")

    where_sql = " AND ".join(filters)
    summary_row = db.execute(
        text(
            f"""
            SELECT
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM {SALES_ORDER_TABLE_SQL} WHERE {where_sql}"),
        params,
    ).scalar()

    row_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS order_date,
              `订单编号` AS order_no,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              COALESCE(NULLIF(`订单状态`, ''), '未知') AS status,
              COALESCE(NULLIF(`结算状态`, ''), '未知') AS settlement_status,
              COALESCE(NULLIF(`货品摘要`, ''), '未命名商品') AS product,
              COALESCE(`货品数量`, 0) AS quantity,
              COALESCE(`应收合计`, 0) AS receivable_amount,
              COALESCE(`实付金额`, 0) AS paid_amount,
              COALESCE(NULLIF(`市`, ''), '-') AS city
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE {where_sql}
            ORDER BY `下单时间` DESC, `订单编号` DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": {
            "paid_amount": _number(summary_row["paid_amount"]),
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "date": row["order_date"].isoformat() if row["order_date"] else None,
                "order_no": row["order_no"],
                "channel": row["channel"],
                "status": row["status"],
                "settlement_status": row["settlement_status"],
                "product": row["product"],
                "quantity": _int(row["quantity"]),
                "receivable_amount": _number(row["receivable_amount"]),
                "paid_amount": _number(row["paid_amount"]),
                "city": row["city"],
            }
            for row in rows
        ],
        "total": _int(total),
        "page": page,
        "page_size": page_size,
    }
    return _cached_ok(cache_key, data)


@router.get("/product-rank")
def sales_product_rank(
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(30, ge=10, le=100),
    keyword: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    cache_key = _sales_cache_key(
        "product-rank-v2",
        range=range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        keyword=keyword,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(cache_key, {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": []})

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("`货品名称` LIKE :keyword")

    where_sql = " AND ".join(filters)
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    rank_paid_amount = _number(summary_row["paid_amount"])
    summary = _sales_query_summary(db, params)
    row_params = {**params, "limit": limit}
    rank_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY paid_amount DESC
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()
    quantity_rank_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY quantity DESC, paid_amount DESC
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": summary,
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": amount / rank_paid_amount * 100 if rank_paid_amount else 0,
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
        "quantity_rows": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": quantity / _int(summary_row["quantity"]) * 100 if _int(summary_row["quantity"]) else 0,
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(quantity_rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/brand-analysis")
def sales_brand_analysis(
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(30, ge=10, le=100),
    keyword: str | None = Query(None),
    product_type: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    selected_product_types = list(
        dict.fromkeys(item.strip() for item in product_type or [] if item.strip() in {"正装", "小样"})
    )
    cache_key = _sales_cache_key(
        "brand-analysis-v2",
        range=range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        keyword=keyword,
        product_type=selected_product_types,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(cache_key, {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": []})

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("(`品牌` LIKE :keyword OR `货品名称` LIKE :keyword)")
    if selected_product_types:
        product_type_params = []
        for index, item in enumerate(selected_product_types):
            param_name = f"product_type_{index}"
            params[param_name] = item
            product_type_params.append(f":{param_name}")
        filters.append(
            f"COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类') IN ({', '.join(product_type_params)})"
        )

    where_sql = " AND ".join(filters)
    brand_expr = """
        CASE
          WHEN NULLIF(`品牌`, '') IS NOT NULL THEN `品牌`
          WHEN `货品名称` LIKE '资生堂%' THEN '资生堂'
          WHEN `货品名称` LIKE '兰蔻%' THEN '兰蔻'
          WHEN `货品名称` LIKE 'YSL%' THEN 'YSL'
          WHEN `货品名称` LIKE '圣罗兰%' THEN '圣罗兰'
          WHEN `货品名称` LIKE '植村秀%' THEN '植村秀'
          WHEN `货品名称` LIKE 'HR赫莲娜%' THEN 'HR赫莲娜'
          WHEN `货品名称` LIKE '赫莲娜%' THEN '赫莲娜'
          WHEN `货品名称` LIKE '科颜氏%' THEN '科颜氏'
          WHEN `货品名称` LIKE '修丽可%' THEN '修丽可'
          WHEN `货品名称` LIKE '阿玛尼%' THEN '阿玛尼'
          WHEN `货品名称` LIKE '欧莱雅%' THEN '欧莱雅'
          WHEN `货品名称` LIKE '理肤泉%' THEN '理肤泉'
          WHEN `货品名称` LIKE '薇姿%' THEN '薇姿'
          WHEN `货品名称` LIKE '适乐肤%' THEN '适乐肤'
          ELSE '未识别品牌'
        END
    """
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    rank_paid_amount = _number(summary_row["paid_amount"])
    summary = (
        {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        }
        if selected_product_types
        else _sales_query_summary(db, params)
    )
    row_params = {**params, "limit": limit}
    rank_rows = db.execute(
        text(
            f"""
            SELECT
              {brand_expr} AS brand,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              COUNT(DISTINCT COALESCE(NULLIF(`货品名称`, ''), '未命名商品')) AS product_count,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {where_sql}
            GROUP BY {brand_expr}
            ORDER BY paid_amount DESC
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": summary,
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "rank": index + 1,
                "brand": row["brand"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": amount / rank_paid_amount * 100 if rank_paid_amount else 0,
                "product_count": _int(row["product_count"]),
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/channel-analysis")
def sales_channel_analysis(
    range: str = Query("this_year"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    keyword: str | None = Query(None),
    channel_type: str | None = Query(None),
    platform: str | None = Query(None),
    authorized: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    cache_key = _sales_cache_key(
        "channel-analysis-v6",
        range=range,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
        channel_type=channel_type,
        platform=platform,
        authorized=authorized,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "summary": {"paid_amount": 0, "orders": 0, "quantity": 0},
                "channel_summary": {
                    "total_channels": 0,
                    "active_channels": 0,
                    "authorized_channels": 0,
                    "unmatched_sales_channels": 0,
                },
                "trend": [],
                "type_summary": [],
                "platform_summary": [],
                "rows": [],
                "unmatched_channels": [],
                "filter_options": {"channel_types": [], "platforms": []},
            },
        )

    filters = []
    sales_dimension_filters = []
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append(
            "(`渠道名称` LIKE :keyword OR `渠道编号` LIKE :keyword OR `负责人` LIKE :keyword OR `线上平台` LIKE :keyword)"
        )
        sales_dimension_filters.append(
            "(c.`渠道名称` LIKE :keyword OR c.`渠道编号` LIKE :keyword OR c.`负责人` LIKE :keyword OR c.`线上平台` LIKE :keyword)"
        )
    if channel_type:
        params["channel_type"] = channel_type
        filters.append("COALESCE(NULLIF(`渠道类型`, ''), '未分类') = :channel_type")
        sales_dimension_filters.append("COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') = :channel_type")
    if platform:
        params["platform"] = platform
        filters.append("COALESCE(NULLIF(`线上平台`, ''), '未设置') = :platform")
        sales_dimension_filters.append("COALESCE(NULLIF(c.`线上平台`, ''), '未设置') = :platform")
    if authorized in {"0", "1"}:
        params["authorized"] = authorized
        filters.append("CAST(COALESCE(`是否授权`, 0) AS CHAR) = :authorized")
        sales_dimension_filters.append("CAST(COALESCE(c.`是否授权`, 0) AS CHAR) = :authorized")

    channel_where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sales_dimension_where = (
        f"AND {' AND '.join(sales_dimension_filters)}" if sales_dimension_filters else ""
    )
    monthly_channel_rows = db.execute(
        text(
            f"""
            SELECT
              DATE_FORMAT(s.`下单时间`, '%Y-%m-01') AS month,
              COALESCE(NULLIF(s.`销售渠道`, ''), '未归类') AS channel,
              COUNT(DISTINCT s.`订单编号`) AS orders,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS paid_amount,
              SUM(COALESCE(s.`数量`, 0)) AS quantity
            FROM `销售单明细账` s
            LEFT JOIN `渠道列表` c
              ON c.`渠道名称` = COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            WHERE s.`下单时间` >= :start_date
              AND s.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              {sales_dimension_where}
            GROUP BY DATE_FORMAT(s.`下单时间`, '%Y-%m-01'), COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            ORDER BY month, channel
            """
        ),
        params,
    ).mappings().all()
    trend_by_month: dict[str, dict] = {}
    facts_by_channel: dict[str, dict] = {}
    for row in monthly_channel_rows:
        month = str(row["month"])
        channel = row["channel"]
        month_item = trend_by_month.setdefault(
            month, {"month": month, "orders": 0, "paid_amount": 0.0, "quantity": 0}
        )
        channel_item = facts_by_channel.setdefault(
            channel, {"channel": channel, "orders": 0, "paid_amount": 0.0, "quantity": 0}
        )
        for item in (month_item, channel_item):
            item["orders"] += _int(row["orders"])
            item["paid_amount"] += _number(row["paid_amount"])
            item["quantity"] += _int(row["quantity"])
    trend = list(trend_by_month.values())
    summary = {
        "orders": sum(row["orders"] for row in trend),
        "paid_amount": sum(row["paid_amount"] for row in trend),
        "quantity": sum(row["quantity"] for row in trend),
    }
    dimension_rows = db.execute(
        text(
            f"""
            SELECT
              c.`渠道编号` AS channel_code,
              c.`渠道名称` AS channel_name,
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS category,
              COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COALESCE(NULLIF(c.`负责人`, ''), '-') AS owner,
              COALESCE(c.`是否授权`, 0) AS authorized
            FROM `渠道列表` c
            {channel_where}
            ORDER BY c.`渠道编号`
            """
        ),
        params,
    ).mappings().all()

    total_paid_amount = summary["paid_amount"]
    channel_rows = [
        {
            "channel_code": row["channel_code"],
            "channel_name": row["channel_name"],
            "category": row["category"],
            "channel_type": row["channel_type"],
            "platform": row["platform"],
            "owner": row["owner"],
            "authorized": str(row["authorized"]) == "1",
            "orders": orders,
            "paid_amount": paid_amount,
            "quantity": quantity,
            "share": paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
            "avg_order_amount": paid_amount / orders if orders else 0,
            "is_online": _is_online_sales_channel(
                row["category"], row["platform"], row["channel_name"]
            ),
            "matched": True,
        }
        for row in dimension_rows
        for fact in [facts_by_channel.get(row["channel_name"], {})]
        for orders in [_int(fact.get("orders"))]
        for paid_amount in [_number(fact.get("paid_amount"))]
        for quantity in [_int(fact.get("quantity"))]
    ]

    filter_option_rows = db.execute(
        text(
            """
            SELECT
              COALESCE(NULLIF(`渠道类型`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform,
              `渠道名称` AS channel_name
            FROM `渠道列表`
            """
        )
    ).mappings().all()
    channel_types = sorted({row["channel_type"] for row in filter_option_rows})
    platforms = sorted({row["platform"] for row in filter_option_rows if row["platform"] != "未设置"})
    all_channel_names = {row["channel_name"] for row in filter_option_rows}
    unmatched_rows = sorted(
        (row for name, row in facts_by_channel.items() if name not in all_channel_names),
        key=lambda row: row["paid_amount"],
        reverse=True,
    )
    channel_rows.extend(
        {
            "channel_code": None,
            "channel_name": row["channel"],
            "category": "未匹配渠道",
            "channel_type": "未匹配渠道",
            "platform": "未设置",
            "owner": "-",
            "authorized": False,
            "orders": _int(row["orders"]),
            "paid_amount": row_paid_amount,
            "quantity": _int(row["quantity"]),
            "share": row_paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
            "avg_order_amount": row_paid_amount / _int(row["orders"]) if _int(row["orders"]) else 0,
            "is_online": _is_online_sales_channel("未匹配渠道", "未设置", row["channel"]),
            "matched": False,
        }
        for row in unmatched_rows
        for row_paid_amount in [_number(row["paid_amount"])]
    )
    channel_rows.sort(key=lambda row: row["paid_amount"], reverse=True)

    def summarize_channels(field: str, include_unset: bool = True) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in channel_rows:
            key = row[field]
            if not include_unset and key == "未设置":
                continue
            item = grouped.setdefault(
                key,
                {field: key, "channels": 0, "active_channels": 0, "orders": 0, "paid_amount": 0.0, "quantity": 0},
            )
            item["channels"] += 1
            item["active_channels"] += 1 if row["orders"] > 0 else 0
            item["orders"] += row["orders"]
            item["paid_amount"] += row["paid_amount"]
            item["quantity"] += row["quantity"]
        return sorted(grouped.values(), key=lambda row: row["paid_amount"], reverse=True)

    type_summary = summarize_channels("channel_type")
    platform_summary = summarize_channels("platform", include_unset=False)[:12]

    data = {
        **meta,
        "summary": summary,
        "channel_summary": {
            "total_channels": len(channel_rows),
            "active_channels": sum(1 for row in channel_rows if row["orders"] > 0),
            "authorized_channels": sum(1 for row in channel_rows if row["authorized"]),
            "unmatched_sales_channels": len(unmatched_rows),
        },
        "trend": trend,
        "type_summary": [
            {
                "channel_type": row["channel_type"],
                "channels": _int(row["channels"]),
                "active_channels": _int(row["active_channels"]),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in type_summary
        ],
        "platform_summary": [
            {
                "platform": row["platform"],
                "channels": _int(row["channels"]),
                "active_channels": _int(row["active_channels"]),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in platform_summary
        ],
        "rows": channel_rows,
        "unmatched_channels": [
            {
                "channel": row["channel"],
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in unmatched_rows
        ],
        "filter_options": {
            "channel_types": channel_types,
            "platforms": platforms,
        },
    }
    return _cached_ok(cache_key, data)


@router.get("/channel-customer-analysis")
def sales_channel_customer_analysis(
    channel_name: str = Query(..., min_length=1),
    range: str = Query("this_year"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    """Drill an offline sales channel down to customer-level sales performance."""
    cache_key = _sales_cache_key(
        "channel-customer-analysis-v1",
        channel_name=channel_name,
        range=range,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "channel_name": channel_name.strip(),
                "owner": "-",
                "summary": {"customers": 0, "orders": 0, "quantity": 0, "paid_amount": 0},
                "pagination": {"page": page, "page_size": page_size, "total": 0},
                "rows": [],
            },
        )

    params["channel_name"] = channel_name.strip()
    customer_filter = ""
    if keyword and keyword.strip():
        params["customer_keyword"] = f"%{keyword.strip()}%"
        customer_filter = """
            WHERE customer_code LIKE :customer_keyword
               OR customer_name LIKE :customer_keyword
        """

    customer_group_sql = f"""
        SELECT
          COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置') AS customer_code,
          COALESCE(o.customer_name, '未命名客户') AS customer_name,
          COUNT(DISTINCT l.`订单编号`) AS orders,
          SUM(COALESCE(l.`数量`, 0)) AS quantity,
          SUM(COALESCE(l.`分摊后金额`, 0)) AS paid_amount
        FROM `销售单明细账` l
        LEFT JOIN (
          SELECT
            `订单编号`,
            MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
            MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
          FROM {SALES_ORDER_TABLE_SQL}
          WHERE `下单时间` >= :start_date
            AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') = :channel_name
          GROUP BY `订单编号`
        ) o ON o.`订单编号` = l.`订单编号`
        WHERE l.`下单时间` >= :start_date
          AND l.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
          AND COALESCE(NULLIF(l.`销售渠道`, ''), '未归类') = :channel_name
        GROUP BY
          COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置'),
          COALESCE(o.customer_name, '未命名客户')
    """
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS customers,
              SUM(customer_sales.orders) AS orders,
              SUM(customer_sales.quantity) AS quantity,
              SUM(customer_sales.paid_amount) AS paid_amount
            FROM ({customer_group_sql}) customer_sales
            {customer_filter}
            """
        ),
        params,
    ).mappings().one()
    total = _int(summary_row["customers"])
    total_paid_amount = _number(summary_row["paid_amount"])
    row_params = {
        **params,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    rows = db.execute(
        text(
            f"""
            SELECT customer_sales.*
            FROM ({customer_group_sql}) customer_sales
            {customer_filter}
            ORDER BY customer_sales.paid_amount DESC, customer_sales.quantity DESC, customer_sales.customer_code
            LIMIT :limit OFFSET :offset
            """
        ),
        row_params,
    ).mappings().all()
    owner = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(`负责人`), ''), '-')
            FROM `渠道列表`
            WHERE `渠道名称` = :channel_name
            LIMIT 1
            """
        ),
        params,
    ).scalar()
    data = {
        **meta,
        "channel_name": channel_name.strip(),
        "owner": owner or "-",
        "summary": {
            "customers": total,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
            "paid_amount": total_paid_amount,
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "rows": [
            {
                "customer_code": row["customer_code"],
                "customer_name": row["customer_name"],
                "orders": row_orders,
                "quantity": _int(row["quantity"]),
                "paid_amount": row_paid_amount,
                "share": row_paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
                "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
            }
            for row in rows
            for row_orders in [_int(row["orders"])]
            for row_paid_amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/brand-channel-analysis")
def sales_brand_channel_analysis(
    brand: str = Query(..., min_length=1),
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel_type: list[str] | None = Query(None),
    channel_name: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    selected_product_types = list(
        dict.fromkeys(item.strip() for item in product_type or [] if item.strip() in {"正装", "小样"})
    )
    cache_key = _sales_cache_key(
        "brand-channel-analysis-v4",
        brand=brand,
        range=range,
        start_date=start_date,
        end_date=end_date,
        channel_type=channel_type,
        channel_name=channel_name,
        product_type=selected_product_types,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "brand": brand,
                "summary": {
                    "paid_amount": 0,
                    "orders": 0,
                    "quantity": 0,
                    "avg_order_amount": 0,
                    "avg_unit_price": 0,
                },
                "trend": [],
                "channel_types": [],
                "platforms": [],
                "channels": [],
                "products": [],
                "salesperson_product_types": [],
                "sales_contribution": {
                    "online": {"paid_amount": 0, "quantity": 0},
                    "offline": {"paid_amount": 0, "quantity": 0},
                    "paid_amount_difference": 0,
                    "quantity_difference": 0,
                },
                "unmatched_channels": [],
                "filter_options": {
                    "channel_types": [],
                    "channel_names": [],
                },
            },
        )

    params["brand"] = brand.strip()
    selected_channel_types = list(dict.fromkeys(item.strip() for item in channel_type or [] if item.strip()))
    selected_channel_names = list(dict.fromkeys(item.strip() for item in channel_name or [] if item.strip()))
    channel_type_params = []
    for index, item in enumerate(selected_channel_types):
        param_name = f"channel_type_{index}"
        params[param_name] = item
        channel_type_params.append(f":{param_name}")
    channel_name_params = []
    for index, item in enumerate(selected_channel_names):
        param_name = f"channel_name_{index}"
        params[param_name] = item
        channel_name_params.append(f":{param_name}")
    brand_expr = """
        CASE
          WHEN NULLIF(`品牌`, '') IS NOT NULL THEN `品牌`
          WHEN `货品名称` LIKE '资生堂%' THEN '资生堂'
          WHEN `货品名称` LIKE '兰蔻%' THEN '兰蔻'
          WHEN `货品名称` LIKE 'YSL%' THEN 'YSL'
          WHEN `货品名称` LIKE '圣罗兰%' THEN '圣罗兰'
          WHEN `货品名称` LIKE '植村秀%' THEN '植村秀'
          WHEN `货品名称` LIKE 'HR赫莲娜%' THEN 'HR赫莲娜'
          WHEN `货品名称` LIKE '赫莲娜%' THEN '赫莲娜'
          WHEN `货品名称` LIKE '科颜氏%' THEN '科颜氏'
          WHEN `货品名称` LIKE '修丽可%' THEN '修丽可'
          WHEN `货品名称` LIKE '阿玛尼%' THEN '阿玛尼'
          WHEN `货品名称` LIKE '欧莱雅%' THEN '欧莱雅'
          WHEN `货品名称` LIKE '理肤泉%' THEN '理肤泉'
          WHEN `货品名称` LIKE '薇姿%' THEN '薇姿'
          WHEN `货品名称` LIKE '适乐肤%' THEN '适乐肤'
          ELSE '未识别品牌'
        END
    """
    fact_where = f"""
        `下单时间` >= :start_date
        AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
        AND {brand_expr} = :brand
    """
    if selected_channel_types:
        fact_where += f"""
        AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN (
          SELECT `渠道名称`
          FROM `渠道列表`
          WHERE COALESCE(NULLIF(`分类`, ''), '未分类') IN ({", ".join(channel_type_params)})
        )
        """
    if selected_channel_names:
        fact_where += f"""
        AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN ({", ".join(channel_name_params)})
        """
    if selected_product_types:
        product_type_params = []
        for index, item in enumerate(selected_product_types):
            param_name = f"product_type_{index}"
            params[param_name] = item
            product_type_params.append(f":{param_name}")
        fact_where += f"""
        AND COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类') IN ({", ".join(product_type_params)})
        """

    channel_dimension_where = []
    if selected_channel_types:
        channel_dimension_where.append(
            f"COALESCE(NULLIF(c.`分类`, ''), '未分类') IN ({', '.join(channel_type_params)})"
        )
    if selected_channel_names:
        channel_dimension_where.append(
            f"c.`渠道名称` IN ({', '.join(channel_name_params)})"
        )
    channel_dimension_clause = (
        f"WHERE {' AND '.join(channel_dimension_where)}" if channel_dimension_where else ""
    )
    platform_dimension_where = [
        *channel_dimension_where,
        "NULLIF(TRIM(c.`线上平台`), '') IS NOT NULL",
    ]
    platform_dimension_clause = f"WHERE {' AND '.join(platform_dimension_where)}"

    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {fact_where}
            """
        ),
        params,
    ).mappings().one()
    orders = _int(summary_row["orders"])
    quantity = _int(summary_row["quantity"])
    paid_amount = _number(summary_row["paid_amount"])

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS day,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {fact_where}
            GROUP BY DATE(`下单时间`)
            ORDER BY day
            """
        ),
        params,
    ).mappings().all()

    channel_fact_sql = f"""
        SELECT
          COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
          COUNT(*) AS detail_rows,
          COUNT(DISTINCT `订单编号`) AS orders,
          SUM(COALESCE(`数量`, 0)) AS quantity,
          SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
        FROM `销售单明细账`
        WHERE {fact_where}
        GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
    """

    channel_rows = db.execute(
        text(
            f"""
            SELECT
              c.`渠道编号` AS channel_code,
              c.`渠道名称` AS channel_name,
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') AS source_channel_type,
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COALESCE(NULLIF(c.`负责人`, ''), '-') AS owner,
              COALESCE(f.detail_rows, 0) AS detail_rows,
              COALESCE(f.orders, 0) AS orders,
              COALESCE(f.quantity, 0) AS quantity,
              COALESCE(f.paid_amount, 0) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {channel_dimension_clause}
            ORDER BY paid_amount DESC, orders DESC, c.`渠道编号`
            """
        ),
        params,
    ).mappings().all()

    type_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS channel_type,
              COUNT(*) AS channels,
              SUM(CASE WHEN COALESCE(f.orders, 0) > 0 THEN 1 ELSE 0 END) AS active_channels,
              SUM(COALESCE(f.orders, 0)) AS orders,
              SUM(COALESCE(f.quantity, 0)) AS quantity,
              SUM(COALESCE(f.paid_amount, 0)) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {channel_dimension_clause}
            GROUP BY COALESCE(NULLIF(c.`分类`, ''), '未分类')
            ORDER BY paid_amount DESC
            """
        ),
        params,
    ).mappings().all()

    platform_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COUNT(*) AS channels,
              SUM(CASE WHEN COALESCE(f.orders, 0) > 0 THEN 1 ELSE 0 END) AS active_channels,
              SUM(COALESCE(f.orders, 0)) AS orders,
              SUM(COALESCE(f.quantity, 0)) AS quantity,
              SUM(COALESCE(f.paid_amount, 0)) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {platform_dimension_clause}
            GROUP BY COALESCE(NULLIF(c.`线上平台`, ''), '未设置')
            ORDER BY paid_amount DESC
            LIMIT 12
            """
        ),
        params,
    ).mappings().all()

    product_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账`
            WHERE {fact_where}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY paid_amount DESC
            LIMIT 20
            """
        ),
        params,
    ).mappings().all()

    salesperson_product_type_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(c.`负责人`), ''), '未设置') AS salesperson,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类') AS product_type,
              SUM(COALESCE(s.`数量`, 0)) AS quantity,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS paid_amount
            FROM `销售单明细账` s
            LEFT JOIN `渠道列表` c
              ON c.`渠道名称` = COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            WHERE {fact_where}
              AND NULLIF(TRIM(s.`货品分类`), '') IN ('正装', '小样')
            GROUP BY
              COALESCE(NULLIF(TRIM(c.`负责人`), ''), '未设置'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类')
            ORDER BY salesperson, product_type
            """
        ),
        params,
    ).mappings().all()

    unmatched_rows = db.execute(
        text(
            f"""
            SELECT f.channel, f.orders, f.quantity, f.paid_amount
            FROM ({channel_fact_sql}) f
            LEFT JOIN `渠道列表` c ON c.`渠道名称` = f.channel
            WHERE c.`渠道名称` IS NULL
            ORDER BY f.paid_amount DESC
            """
        ),
        params,
    ).mappings().all()

    filter_option_rows = db.execute(
        text(
            """
            SELECT
              `渠道名称` AS channel_name,
              COALESCE(NULLIF(`分类`, ''), '未分类') AS channel_type
            FROM `渠道列表`
            WHERE NULLIF(`渠道名称`, '') IS NOT NULL
            ORDER BY channel_type, channel_name
            """
        )
    ).mappings().all()

    def dimension_row(row: dict, label_key: str) -> dict:
        row_paid_amount = _number(row["paid_amount"])
        row_orders = _int(row["orders"])
        row_quantity = _int(row["quantity"])
        return {
            label_key: row[label_key],
            "channels": _int(row["channels"]),
            "active_channels": _int(row["active_channels"]),
            "orders": row_orders,
            "quantity": row_quantity,
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
        }

    channel_data = [
        {
            "channel_code": row["channel_code"],
            "channel_name": row["channel_name"],
            "channel_type": row["channel_type"],
            "source_channel_type": row["source_channel_type"],
            "platform": row["platform"],
            "owner": row["owner"],
            "detail_rows": _int(row["detail_rows"]),
            "orders": row_orders,
            "quantity": row_quantity,
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
            "avg_unit_price": row_paid_amount / row_quantity if row_quantity else 0,
            "is_online": _is_online_sales_channel(row["channel_type"], row["platform"], row["channel_name"]),
            "matched": True,
        }
        for row in channel_rows
        for row_orders in [_int(row["orders"])]
        for row_quantity in [_int(row["quantity"])]
        for row_paid_amount in [_number(row["paid_amount"])]
    ]
    channel_data.extend(
        {
            "channel_code": None,
            "channel_name": row["channel"],
            "channel_type": "未匹配渠道",
            "source_channel_type": "未匹配渠道",
            "platform": "未设置",
            "owner": "-",
            "detail_rows": 0,
            "orders": _int(row["orders"]),
            "quantity": _int(row["quantity"]),
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / _int(row["orders"]) if _int(row["orders"]) else 0,
            "avg_unit_price": row_paid_amount / _int(row["quantity"]) if _int(row["quantity"]) else 0,
            "is_online": _is_online_sales_channel("未匹配渠道", "未设置", row["channel"]),
            "matched": False,
        }
        for row in unmatched_rows
        for row_paid_amount in [_number(row["paid_amount"])]
    )
    channel_data.sort(key=lambda row: row["paid_amount"], reverse=True)
    online_channel_data = [row for row in channel_data if row["is_online"]]
    offline_channel_data = [row for row in channel_data if not row["is_online"]]
    online_paid_amount = sum(row["paid_amount"] for row in online_channel_data)
    offline_paid_amount = sum(row["paid_amount"] for row in offline_channel_data)
    online_quantity = sum(row["quantity"] for row in online_channel_data)
    offline_quantity = sum(row["quantity"] for row in offline_channel_data)

    salesperson_data: dict[str, dict] = {}
    for row in salesperson_product_type_rows:
        salesperson = row["salesperson"]
        item = salesperson_data.setdefault(
            salesperson,
            {
                "salesperson": salesperson,
                "regular_quantity": 0,
                "regular_paid_amount": 0.0,
                "sample_quantity": 0,
                "sample_paid_amount": 0.0,
            },
        )
        prefix = "regular" if row["product_type"] == "正装" else "sample"
        item[f"{prefix}_quantity"] += _int(row["quantity"])
        item[f"{prefix}_paid_amount"] += _number(row["paid_amount"])
    salesperson_product_types = []
    for item in salesperson_data.values():
        item["total_quantity"] = item["regular_quantity"] + item["sample_quantity"]
        item["total_paid_amount"] = item["regular_paid_amount"] + item["sample_paid_amount"]
        salesperson_product_types.append(item)
    salesperson_product_types.sort(key=lambda row: row["total_paid_amount"], reverse=True)

    data = {
        **meta,
        "brand": brand.strip(),
        "summary": {
            "paid_amount": paid_amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": paid_amount / orders if orders else 0,
            "avg_unit_price": paid_amount / quantity if quantity else 0,
        },
        "trend": [
            {
                "date": row["day"].isoformat(),
                "orders": _int(row["orders"]),
                "quantity": _int(row["quantity"]),
                "paid_amount": _number(row["paid_amount"]),
            }
            for row in trend_rows
        ],
        "channel_types": [dimension_row(row, "channel_type") for row in type_rows],
        "platforms": [dimension_row(row, "platform") for row in platform_rows],
        "channels": channel_data,
        "sales_contribution": {
            "online": {"paid_amount": online_paid_amount, "quantity": online_quantity},
            "offline": {"paid_amount": offline_paid_amount, "quantity": offline_quantity},
            "paid_amount_difference": paid_amount - online_paid_amount - offline_paid_amount,
            "quantity_difference": quantity - online_quantity - offline_quantity,
        },
        "salesperson_product_types": salesperson_product_types,
        "products": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": row_orders,
                "quantity": row_quantity,
                "paid_amount": row_paid_amount,
                "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
                "avg_unit_price": row_paid_amount / row_quantity if row_quantity else 0,
            }
            for index, row in enumerate(product_rows)
            for row_orders in [_int(row["orders"])]
            for row_quantity in [_int(row["quantity"])]
            for row_paid_amount in [_number(row["paid_amount"])]
        ],
        "unmatched_channels": [
            {
                "channel": row["channel"],
                "orders": _int(row["orders"]),
                "quantity": _int(row["quantity"]),
                "paid_amount": _number(row["paid_amount"]),
            }
            for row in unmatched_rows
        ],
        "filter_options": {
            "channel_types": sorted({row["channel_type"] for row in filter_option_rows}),
            "channel_names": sorted({row["channel_name"] for row in filter_option_rows}),
        },
    }
    return _cached_ok(cache_key, data)
