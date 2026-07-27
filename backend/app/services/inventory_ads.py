from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch


INVENTORY_DATASET = "inventory_overview"
BRAND_TURNOVER_DEFAULT_WAREHOUSES = tuple(
    sorted(("上海仓库新", "【商家仓】抖超上海仓"))
)


class InventoryAdsUnavailable(RuntimeError):
    pass


def _number(value: object) -> float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _integer(value: object) -> int:
    return int(value or 0)


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def latest_ready_inventory_batch(ads_db: Session) -> AdsPublishBatch:
    batch = ads_db.scalars(
        select(AdsPublishBatch)
        .where(
            AdsPublishBatch.dataset == INVENTORY_DATASET,
            AdsPublishBatch.status == "ready",
        )
        .order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc())
        .limit(1)
    ).first()
    if batch is None:
        raise InventoryAdsUnavailable("No ready inventory ADS batch is available")
    return batch


def _filters(
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
    *,
    alias: str = "",
) -> tuple[str, dict]:
    prefix = f"{alias}." if alias else ""
    conditions = []
    params: dict[str, object] = {}
    if warehouses:
        placeholders = []
        for index, value in enumerate(warehouses):
            key = f"warehouse_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        conditions.append(f"{prefix}`warehouse` IN ({', '.join(placeholders)})")
    if product_types:
        placeholders = []
        for index, value in enumerate(product_types):
            key = f"product_type_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        conditions.append(f"{prefix}`product_type` IN ({', '.join(placeholders)})")
    return (" AND " + " AND ".join(conditions) if conditions else ""), params


def load_inventory_filter_options_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
) -> dict:
    rows = ads_db.execute(
        text(
            """
            SELECT `option_type`, `option_value`
            FROM `ads_inventory_filter_option`
            WHERE `data_version` = :data_version
            ORDER BY
              `option_type`,
              CASE `option_value` WHEN '正装' THEN 0 WHEN '小样' THEN 1 ELSE 2 END,
              `option_value`
            """
        ),
        {"data_version": batch.data_version},
    ).mappings().all()
    grouped = {"warehouse": [], "product_type": [], "brand": []}
    for row in rows:
        grouped.setdefault(str(row["option_type"]), []).append(str(row["option_value"]))
    return {
        "warehouses": grouped["warehouse"],
        "product_types": grouped["product_type"],
        "brands": grouped["brand"],
    }


def load_inventory_overview_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
) -> dict:
    product_filter, filter_params = _filters(warehouses, product_types, alias="p")
    batch_filter, batch_params = _filters(warehouses, product_types, alias="b")
    params = {"data_version": batch.data_version, **filter_params}
    batch_query_params = {"data_version": batch.data_version, **batch_params}

    total_row = ads_db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS product_count,
              SUM(stock_quantity) AS stock_quantity,
              SUM(available_stock) AS available_stock,
              SUM(CASE WHEN stock_min > 0 AND available_stock < stock_min THEN 1 ELSE 0 END) AS below_min_count,
              SUM(CASE WHEN stock_max > 0 AND available_stock > stock_max THEN 1 ELSE 0 END) AS above_max_count,
              MAX(updated_at) AS updated_at
            FROM (
              SELECT
                p.`product_code`,
                SUM(p.`stock_quantity`) AS stock_quantity,
                SUM(p.`available_stock`) AS available_stock,
                MAX(p.`stock_min`) AS stock_min,
                MAX(p.`stock_max`) AS stock_max,
                MAX(p.`updated_at`) AS updated_at
              FROM `ads_inventory_product_warehouse` p
              WHERE p.`data_version` = :data_version
                {product_filter}
              GROUP BY p.`product_code`
            ) inventory_products
            """
        ),
        params,
    ).mappings().one()
    warehouse_summary = ads_db.execute(
        text(
            f"""
            SELECT
              COALESCE(SUM(p.`records`), 0) AS warehouse_records,
              COALESCE(SUM(p.`stock_amount`), 0) AS stock_amount,
              MAX(p.`updated_at`) AS updated_at
            FROM `ads_inventory_product_warehouse` p
            WHERE p.`data_version` = :data_version
              {product_filter}
            """
        ),
        params,
    ).mappings().one()
    batch_summary = ads_db.execute(
        text(
            f"""
            SELECT
              COALESCE(SUM(b.`batch_records`), 0) AS batch_records,
              COALESCE(SUM(b.`expiring_batch_count`), 0) AS expiring_batch_count,
              MAX(b.`updated_at`) AS updated_at
            FROM `ads_inventory_batch_summary` b
            WHERE b.`data_version` = :data_version
              {batch_filter}
            """
        ),
        batch_query_params,
    ).mappings().one()
    warehouse_rows = ads_db.execute(
        text(
            f"""
            SELECT
              p.`warehouse`,
              SUM(p.`records`) AS records,
              SUM(p.`stock_quantity`) AS stock_quantity,
              SUM(p.`available_stock`) AS available_stock,
              SUM(p.`stock_amount`) AS stock_amount
            FROM `ads_inventory_product_warehouse` p
            WHERE p.`data_version` = :data_version
              {product_filter}
            GROUP BY p.`warehouse`
            ORDER BY available_stock DESC
            LIMIT 12
            """
        ),
        params,
    ).mappings().all()

    updated_candidates = [
        total_row["updated_at"],
        warehouse_summary["updated_at"],
        batch_summary["updated_at"],
    ]
    product_count = _integer(total_row["product_count"])
    return {
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "updated_at": _date_text(
            max((value for value in updated_candidates if value is not None), default=None)
        ),
        "metrics": {
            "product_count": product_count,
            "warehouse_records": _integer(warehouse_summary["warehouse_records"]),
            "batch_records": _integer(batch_summary["batch_records"]),
            "stock_quantity": _number(total_row["stock_quantity"]),
            "available_stock": _number(total_row["available_stock"]),
            "stock_amount": _number(warehouse_summary["stock_amount"]),
            "below_min_count": _integer(total_row["below_min_count"]),
            "above_max_count": _integer(total_row["above_max_count"]),
            "expiring_batch_count": _integer(batch_summary["expiring_batch_count"]),
        },
        "source_tables": [
            {
                "table": "分仓库查询",
                "records": product_count,
                "usage": "库存概览、仓库维度库存、库存金额、销量",
                "key_fields": "仓库、货品编号、库存数量、可用库存、库存金额、近30天销量、库存上下限",
            },
            {
                "table": "批次货品库存查询",
                "records": _integer(batch_summary["batch_records"]),
                "usage": "库龄、效期、临期库存",
                "key_fields": "批次、生产日期、到期日期、剩余有效天数、库存数量",
            },
        ],
        "warehouses": [
            {
                "warehouse": str(row["warehouse"]),
                "records": _integer(row["records"]),
                "stock_quantity": _number(row["stock_quantity"]),
                "available_stock": _number(row["available_stock"]),
                "stock_amount": _number(row["stock_amount"]),
            }
            for row in warehouse_rows
        ],
    }


def load_inventory_health_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    *,
    keyword: str,
    barcode: str,
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
    issue_type: str,
    page: int,
    page_size: int,
) -> dict:
    item_filter, params = _filters(warehouses, product_types, alias="h")
    conditions = [f"h.`data_version` = :data_version{item_filter}"]
    params["data_version"] = batch.data_version
    if keyword:
        params["keyword"] = f"%{keyword}%"
        conditions.append(
            """
            (
              h.`product_code` LIKE :keyword
              OR h.`product` LIKE :keyword
              OR h.`brand` LIKE :keyword
              OR h.`barcode` LIKE :keyword
            )
            """
        )
    if barcode:
        params["barcode"] = f"%{barcode}%"
        conditions.append("h.`barcode` LIKE :barcode")
    common_where = " AND ".join(conditions)
    metrics = ads_db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS item_count,
              SUM(h.`issue_type` = 'negative') AS negative_count,
              SUM(h.`issue_type` = 'missing_barcode') AS missing_barcode_count,
              SUM(h.`issue_type` = 'out_of_stock') AS out_of_stock_count,
              SUM(h.`issue_type` = 'no_sales') AS no_sales_count,
              SUM(h.`issue_type` = 'shortage') AS shortage_count,
              SUM(h.`issue_type` = 'overstock') AS overstock_count,
              SUM(h.`issue_type` = 'healthy') AS healthy_count
            FROM `ads_inventory_health_item` h
            WHERE {common_where}
            """
        ),
        params,
    ).mappings().one()
    issue_conditions = {
        "negative": "h.`issue_type` = 'negative'",
        "missing_barcode": "h.`issue_type` = 'missing_barcode'",
        "out_of_stock": "h.`issue_type` = 'out_of_stock'",
        "no_sales": "h.`issue_type` = 'no_sales'",
        "shortage": "h.`issue_type` = 'shortage'",
        "overstock": "h.`issue_type` = 'overstock'",
        "healthy": "h.`issue_type` = 'healthy'",
    }
    issue_where = issue_conditions.get(issue_type, "h.`issue_type` <> 'healthy'")
    filtered_where = f"{common_where} AND {issue_where}"
    total = ads_db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM `ads_inventory_health_item` h
            WHERE {filtered_where}
            """
        ),
        params,
    ).scalar_one()
    offset = (page - 1) * page_size
    rows = ads_db.execute(
        text(
            f"""
            SELECT *
            FROM `ads_inventory_health_item` h
            WHERE {filtered_where}
            ORDER BY
              CASE h.`issue_type`
                WHEN 'negative' THEN 1
                WHEN 'out_of_stock' THEN 2
                WHEN 'shortage' THEN 3
                WHEN 'missing_barcode' THEN 4
                WHEN 'no_sales' THEN 5
                WHEN 'overstock' THEN 6
                ELSE 7
              END,
              h.`stock_amount` DESC,
              h.`available_stock` DESC,
              h.`product_code`,
              h.`brand`,
              h.`product_type`,
              h.`warehouse`
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": offset},
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
    return {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "issue_type": issue_type,
        "pagination": {"page": page, "page_size": page_size, "total": _integer(total)},
        "metrics": {key: _integer(value) for key, value in metrics.items()},
        "rows": [
            {
                "rank": offset + index + 1,
                "product_code": str(row["product_code"]),
                "barcode": str(row["barcode"]),
                "product": str(row["product"]),
                "brand": str(row["brand"]),
                "product_type": str(row["product_type"]),
                "warehouse": str(row["warehouse"]),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "sales30": _number(row["sales30"]),
                "sales90": _number(row["sales90"]),
                "stock_amount": _number(row["stock_amount"]),
                "available_days": (
                    _number(row["available_days"])
                    if row["available_days"] is not None
                    else None
                ),
                "issue_type": str(row["issue_type"]),
                "issue_label": issue_labels.get(str(row["issue_type"]), "待检查"),
            }
            for index, row in enumerate(rows)
        ],
    }


def load_inventory_turnover_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    *,
    keyword: str,
    barcode: str,
    min_stock: int,
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
    page: int,
    page_size: int,
) -> dict:
    item_filter, params = _filters(warehouses, product_types, alias="t")
    conditions = [
        f"t.`data_version` = :data_version{item_filter}",
        "t.`stock` >= :min_stock",
    ]
    params.update(
        {
            "data_version": batch.data_version,
            "min_stock": min_stock,
        }
    )
    if keyword:
        params["keyword"] = f"%{keyword}%"
        conditions.append(
            """
            (
              t.`product_code` LIKE :keyword
              OR t.`product` LIKE :keyword
              OR t.`brand` LIKE :keyword
              OR t.`barcode` LIKE :keyword
            )
            """
        )
    if barcode:
        params["barcode"] = f"%{barcode}%"
        conditions.append("t.`barcode` LIKE :barcode")
    common_where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    rows = ads_db.execute(
        text(
            f"""
            SELECT
              t.*,
              COUNT(*) OVER () AS total_count,
              CASE
                WHEN t.`sales30` > 0
                  THEN ROUND((t.`stock` * 30) / t.`sales30`, 1)
                ELSE NULL
              END AS turnover_days
            FROM `ads_inventory_turnover_item` t
            WHERE {common_where}
            ORDER BY
              COALESCE(turnover_days, 999999) DESC,
              t.`stock` DESC,
              t.`product_code`,
              t.`product`,
              t.`brand`,
              t.`product_type`,
              t.`warehouse`
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": offset},
    ).mappings().all()
    if rows:
        total = _integer(rows[0]["total_count"])
    elif page > 1:
        total = _integer(
            ads_db.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM `ads_inventory_turnover_item` t
                    WHERE {common_where}
                    """
                ),
                params,
            ).scalar_one()
        )
    else:
        total = 0
    return {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "min_stock": min_stock,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": _integer(total),
        },
        "rows": [
            {
                "rank": offset + index + 1,
                "product_code": str(row["product_code"] or "-"),
                "barcode": str(row["barcode"] or "-"),
                "product": str(row["product"] or "未命名商品"),
                "brand": str(row["brand"] or "未归类"),
                "product_type": str(row["product_type"] or "未归类"),
                "warehouse": str(row["warehouse"] or "未归类"),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "sales30": _number(row["sales30"]),
                "total_sales": 0,
                "turnover_days": (
                    _number(row["turnover_days"])
                    if row["turnover_days"] is not None
                    else None
                ),
                "status": (
                    "无销量"
                    if row["turnover_days"] is None
                    else "正常"
                    if _number(row["turnover_days"]) <= 90
                    else "偏慢"
                    if _number(row["turnover_days"]) <= 180
                    else "过慢"
                ),
            }
            for index, row in enumerate(rows)
        ],
    }


def load_inventory_brand_turnover_from_ads(
    ads_db: Session,
    inventory_batch: AdsPublishBatch,
    sales_batch: AdsPublishBatch,
    *,
    year: int,
    quarter: int,
    keyword: str,
    min_stock: int,
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
    page: int,
    page_size: int,
) -> dict:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start_date = date(year, start_month, 1)
    end_date = date(year, end_month, monthrange(year, end_month)[1])
    period_days = (end_date - start_date).days + 1
    stock_filter, stock_params = _filters(
        warehouses,
        product_types,
        alias="i",
    )
    sales_filter, sales_params = _filters(
        warehouses,
        product_types,
        alias="s",
    )
    if not warehouses:
        order_warehouse_scope = "__all__"
    elif set(warehouses) == set(BRAND_TURNOVER_DEFAULT_WAREHOUSES):
        order_warehouse_scope = "__default__"
    elif len(warehouses) == 1:
        order_warehouse_scope = warehouses[0]
    else:
        raise InventoryAdsUnavailable(
            "Brand turnover order scope does not cover this warehouse combination"
        )
    if not product_types:
        order_product_type_scope = "all"
    elif product_types == ("正装",):
        order_product_type_scope = "full_size"
    elif product_types == ("小样",):
        order_product_type_scope = "sample"
    elif set(product_types) == {"正装", "小样"}:
        order_product_type_scope = "selected"
    else:
        raise InventoryAdsUnavailable(
            "Brand turnover order scope does not cover this product type combination"
        )
    stock_brand_filter = ""
    sales_brand_filter = ""
    if keyword:
        stock_params["brand_keyword"] = keyword
        sales_params["brand_keyword"] = keyword
        stock_brand_filter = " AND i.`brand` = :brand_keyword"
        sales_brand_filter = " AND s.`brand` = :brand_keyword"
    order_brand_filter = " AND o.`brand` = :brand_keyword" if keyword else ""

    stock_rows = ads_db.execute(
        text(
            f"""
            SELECT
              i.`brand`,
              SUM(i.`stock`) AS ending_stock,
              SUM(i.`available_stock`) AS available_stock,
              SUM(i.`stock_amount`) AS inventory_amount,
              MAX(i.`updated_at`) AS snapshot_at
            FROM `ads_inventory_turnover_item` i
            WHERE i.`data_version` = :data_version
              {stock_filter}
              {stock_brand_filter}
            GROUP BY i.`brand`
            """
        ),
        {
            "data_version": inventory_batch.data_version,
            **stock_params,
        },
    ).mappings().all()
    sales_rows = ads_db.execute(
        text(
            f"""
            SELECT
              s.`brand`,
              SUM(s.`quantity`) AS net_sales_quantity,
              SUM(s.`paid_amount`) AS net_sales_amount
            FROM `ads_sales_brand_turnover_item` s
            WHERE s.`data_version` = :data_version
              AND s.`sales_date` BETWEEN :start_date AND :end_date
              {sales_filter}
              {sales_brand_filter}
            GROUP BY s.`brand`
            """
        ),
        {
            "data_version": sales_batch.data_version,
            "start_date": start_date,
            "end_date": end_date,
            **sales_params,
        },
    ).mappings().all()
    sales_order_rows = ads_db.execute(
        text(
            f"""
            SELECT
              o.`brand`,
              SUM(o.`orders`) AS orders
            FROM `ads_sales_brand_turnover_order` o
            WHERE o.`data_version` = :data_version
              AND o.`sales_date` BETWEEN :start_date AND :end_date
              AND o.`warehouse` = :warehouse_scope
              AND o.`product_type` = :product_type_scope
              {order_brand_filter}
            GROUP BY o.`brand`
            """
        ),
        {
            "data_version": sales_batch.data_version,
            "start_date": start_date,
            "end_date": end_date,
            "warehouse_scope": order_warehouse_scope,
            "product_type_scope": order_product_type_scope,
            **({"brand_keyword": keyword} if keyword else {}),
        },
    ).mappings().all()

    product_stock_rows = []
    product_sales_rows = []
    if keyword:
        product_stock_rows = ads_db.execute(
            text(
                f"""
                SELECT
                  CONCAT(
                    MAX(i.`brand`),
                    '|',
                    MAX(
                      COALESCE(
                        NULLIF(TRIM(i.`product_code`), ''),
                        CONCAT(
                          'NAME:',
                          COALESCE(
                            NULLIF(TRIM(i.`product`), ''),
                            '未命名商品'
                          )
                        )
                      )
                    )
                  ) AS product_key,
                  MAX(i.`product_code`) AS product_code,
                  MAX(i.`product`) AS product,
                  i.`product_type`,
                  SUM(i.`available_stock`) AS available_stock
                FROM `ads_inventory_turnover_item` i
                WHERE i.`data_version` = :data_version
                  {stock_filter}
                  {stock_brand_filter}
                GROUP BY
                  i.`brand`,
                  i.`product_type`,
                  COALESCE(
                    NULLIF(TRIM(i.`product_code`), ''),
                    CONCAT(
                      'NAME:',
                      COALESCE(NULLIF(TRIM(i.`product`), ''), '未命名商品')
                    )
                  )
                """
            ),
            {
                "data_version": inventory_batch.data_version,
                **stock_params,
            },
        ).mappings().all()
        product_sales_rows = ads_db.execute(
            text(
                f"""
                SELECT
                  s.`product_key`,
                  s.`product_type`,
                  SUM(s.`quantity`) AS net_sales_quantity
                FROM `ads_sales_brand_turnover_item` s
                WHERE s.`data_version` = :data_version
                  AND s.`sales_date` BETWEEN :start_date AND :end_date
                  {sales_filter}
                  {sales_brand_filter}
                GROUP BY s.`product_key`, s.`product_type`
                """
            ),
            {
                "data_version": sales_batch.data_version,
                "start_date": start_date,
                "end_date": end_date,
                **sales_params,
            },
        ).mappings().all()

    stock_by_brand = {row["brand"]: row for row in stock_rows}
    sales_by_brand = {row["brand"]: dict(row) for row in sales_rows}
    for row in sales_order_rows:
        sales_by_brand.setdefault(row["brand"], {})["orders"] = row["orders"]
    merged_rows = []
    for brand in set(stock_by_brand) | set(sales_by_brand):
        stock_row = stock_by_brand.get(brand, {})
        sales_row = sales_by_brand.get(brand, {})
        ending_stock = _number(stock_row.get("ending_stock"))
        available_stock = _number(stock_row.get("available_stock"))
        net_sales_quantity = _number(sales_row.get("net_sales_quantity"))
        turnover_rate = (
            net_sales_quantity / available_stock
            if available_stock > 0 and net_sales_quantity > 0
            else None
        )
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
                "brand": str(brand or "未归类"),
                "ending_stock": ending_stock,
                "available_stock": available_stock,
                "inventory_amount": _number(stock_row.get("inventory_amount")),
                "orders": _integer(sales_row.get("orders")),
                "net_sales_quantity": net_sales_quantity,
                "net_sales_amount": _number(sales_row.get("net_sales_amount")),
                "turnover_rate": (
                    round(turnover_rate, 4)
                    if turnover_rate is not None
                    else None
                ),
                "turnover_days": (
                    round(turnover_days, 1)
                    if turnover_days is not None
                    else None
                ),
                "snapshot_at": _date_text(stock_row.get("snapshot_at")),
                "status": status,
            }
        )

    if min_stock > 0:
        merged_rows = [
            row for row in merged_rows if row["available_stock"] >= min_stock
        ]
    merged_rows.sort(
        key=lambda row: (
            row["turnover_days"] is None,
            row["turnover_days"] or 0,
            row["available_stock"],
            row["brand"],
        ),
        reverse=True,
    )
    for index, row in enumerate(merged_rows):
        row["rank"] = index + 1
    total = len(merged_rows)
    offset = (page - 1) * page_size
    paged_rows = merged_rows[offset : offset + page_size]

    total_stock = sum(row["ending_stock"] for row in merged_rows)
    total_available_stock = sum(row["available_stock"] for row in merged_rows)
    total_sales_quantity = sum(row["net_sales_quantity"] for row in merged_rows)
    total_turnover_rate = (
        total_sales_quantity / total_available_stock
        if total_available_stock > 0 and total_sales_quantity > 0
        else None
    )
    total_turnover_days = (
        period_days / total_turnover_rate if total_turnover_rate else None
    )
    snapshot_at = max(
        (row["snapshot_at"] for row in merged_rows if row["snapshot_at"]),
        default=None,
    )
    product_sales_by_key = {
        row["product_key"]: _number(row["net_sales_quantity"])
        for row in product_sales_rows
    }
    product_turnover_rows = []
    for row in product_stock_rows:
        available_stock = _number(row["available_stock"])
        net_sales_quantity = product_sales_by_key.get(row["product_key"], 0)
        turnover_rate = (
            net_sales_quantity / available_stock
            if available_stock > 0 and net_sales_quantity > 0
            else None
        )
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
                "product_key": str(row["product_key"] or "-"),
                "product_code": str(row["product_code"] or "-"),
                "product": str(row["product"] or "未命名商品"),
                "product_type": str(row["product_type"] or "未归类"),
                "available_stock": available_stock,
                "net_sales_quantity": net_sales_quantity,
                "turnover_days": (
                    round(turnover_days, 1)
                    if turnover_days is not None
                    else None
                ),
                "status": status,
            }
        )

    def build_product_panel(label: str, type_names: tuple[str, ...]) -> dict:
        rows = [
            row
            for row in product_turnover_rows
            if row["product_type"] in type_names
        ]
        panel_available_stock = sum(row["available_stock"] for row in rows)
        panel_sales_quantity = sum(row["net_sales_quantity"] for row in rows)
        average_turnover_days = (
            period_days * panel_available_stock / panel_sales_quantity
            if panel_available_stock > 0 and panel_sales_quantity > 0
            else None
        )
        rows.sort(
            key=lambda row: (row["available_stock"], row["product_key"]),
            reverse=True,
        )
        return {
            "label": label,
            "total_available_stock": panel_available_stock,
            "average_turnover_days": (
                round(average_turnover_days, 1)
                if average_turnover_days is not None
                else None
            ),
            "rows": rows[:10],
        }

    product_turnover_panels = []
    if keyword:
        product_turnover_rows.sort(
            key=lambda row: (row["available_stock"], row["product_key"]),
            reverse=True,
        )
        product_turnover_panels = [
            build_product_panel("正装 + 小样", ("正装", "小样")),
            build_product_panel("正装", ("正装",)),
            build_product_panel("小样", ("小样",)),
        ]
    return {
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
            "turnover_rate": (
                round(total_turnover_rate, 4)
                if total_turnover_rate is not None
                else None
            ),
            "turnover_days": (
                round(total_turnover_days, 1)
                if total_turnover_days is not None
                else None
            ),
            "attention_brands": sum(
                1
                for row in merged_rows
                if row["status"] in {"偏慢", "过慢", "无销售"}
            ),
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "chart_rows": merged_rows,
        "product_turnover_panels": product_turnover_panels,
        "product_turnover_rows": product_turnover_rows,
        "rows": paged_rows,
    }


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _batch_status(remaining_days: int | None) -> str:
    if remaining_days is None:
        return "缺少到期日期"
    if remaining_days < 0:
        return "已过期"
    if remaining_days <= 183:
        return "6个月内"
    if remaining_days <= 365:
        return "6-12个月"
    if remaining_days <= 730:
        return "12-24个月"
    return "24个月以上"


def load_batch_expiry_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    *,
    keyword: str,
    barcode: str,
    warehouses: tuple[str, ...],
    product_types: tuple[str, ...],
    expiry_range: str,
    page: int,
    long_page: int,
    page_size: int,
) -> dict:
    item_filter, params = _filters(warehouses, product_types, alias="b")
    search_filter = ""
    if keyword:
        params["keyword"] = f"%{keyword}%"
        search_filter += """
          AND (
            b.`product_code` LIKE :keyword
            OR b.`product` LIKE :keyword
            OR b.`brand` LIKE :keyword
            OR b.`barcode` LIKE :keyword
          )
        """
    if barcode:
        params["barcode"] = f"%{barcode}%"
        search_filter += " AND b.`barcode` LIKE :barcode"
    rows = ads_db.execute(
        text(
            f"""
            SELECT *
            FROM `ads_inventory_batch_item` b
            WHERE b.`data_version` = :data_version
              {item_filter}
              {search_filter}
            """
        ),
        {"data_version": batch.data_version, **params},
    ).mappings().all()

    keyword_folded = keyword.casefold()
    barcode_folded = barcode.casefold()

    def text_value(row: dict, field: str) -> str:
        return str(row[field] or "")

    filtered_rows = []
    for row in rows:
        if keyword_folded and not any(
            keyword_folded in text_value(row, field).casefold()
            for field in ("product_code", "product", "brand", "barcode")
        ):
            continue
        if barcode_folded and barcode_folded not in text_value(row, "barcode").casefold():
            continue
        filtered_rows.append(dict(row))

    today = datetime.now(timezone(timedelta(hours=8))).date()
    month_6 = _add_months(today, 6)
    month_12 = _add_months(today, 12)
    month_24 = _add_months(today, 24)

    def expiry(row: dict) -> date | None:
        return _as_date(row["expiry_date"])

    def in_expiry_range(row: dict) -> bool:
        value = expiry(row)
        if expiry_range == "expired":
            return value is not None and value < today
        if expiry_range == "0_6":
            return value is not None and today <= value <= month_6
        if expiry_range == "6_12":
            return value is not None and month_6 < value <= month_12
        if expiry_range == "12_24":
            return value is not None and month_12 < value <= month_24
        if expiry_range == "gt_24":
            return value is not None and value > month_24
        if expiry_range == "missing":
            return value is None
        return True

    available_stock = sum(_number(row["available_stock"]) for row in filtered_rows)
    metrics = {
        "batch_count": len(filtered_rows),
        "product_count": len({row["product_code"] for row in filtered_rows}),
        "available_stock": available_stock,
        "expired_stock": sum(
            _number(row["available_stock"])
            for row in filtered_rows
            if expiry(row) is not None and expiry(row) < today
        ),
        "within_6_months_stock": sum(
            _number(row["available_stock"])
            for row in filtered_rows
            if expiry(row) is not None and today <= expiry(row) <= month_6
        ),
        "within_12_months_stock": sum(
            _number(row["available_stock"])
            for row in filtered_rows
            if expiry(row) is not None and today <= expiry(row) <= month_12
        ),
        "over_24_months_stock": sum(
            _number(row["available_stock"])
            for row in filtered_rows
            if expiry(row) is not None and expiry(row) > month_24
        ),
        "missing_expiry_stock": sum(
            _number(row["available_stock"])
            for row in filtered_rows
            if expiry(row) is None
        ),
    }
    updated_at = max(
        (row["updated_at"] for row in filtered_rows if row["updated_at"] is not None),
        default=None,
    )

    partitions: dict[tuple[str, object], list[dict]] = {}
    for row in filtered_rows:
        partitions.setdefault((str(row["warehouse"]), row["product_code"]), []).append(row)
    ranked_rows = []
    far_future = date.max
    for partition in partitions.values():
        partition.sort(
            key=lambda row: (
                expiry(row) is None,
                expiry(row) or far_future,
                _as_date(row["production_date"]) or far_future,
                text_value(row, "batch"),
            )
        )
        count = len(partition)
        for index, row in enumerate(partition, start=1):
            item = dict(row)
            item["product_batch_count"] = count
            item["fefo_rank"] = index
            ranked_rows.append(item)
    expiry_rows = [row for row in ranked_rows if in_expiry_range(row)]
    expiry_rows.sort(
        key=lambda row: (
            expiry(row) is None,
            expiry(row) or far_future,
            -_number(row["available_stock"]),
            text_value(row, "product_code"),
            str(row["warehouse"]),
            text_value(row, "batch"),
        )
    )
    offset = (page - 1) * page_size
    page_rows = expiry_rows[offset : offset + page_size]

    long_groups: dict[tuple, dict] = {}
    long_total_keys = set()
    for row in filtered_rows:
        expiry_date = expiry(row)
        if expiry_date is None or expiry_date <= month_24:
            continue
        long_total_keys.add((row["warehouse"], row["product_code"], row["product_type"]))
        key = (
            row["warehouse"],
            row["product_code"],
            row["product"],
            row["brand"],
            row["product_type"],
        )
        item = long_groups.setdefault(
            key,
            {
                "warehouse": row["warehouse"],
                "product_code": row["product_code"],
                "barcode": row["barcode"],
                "product": row["product"],
                "brand": row["brand"],
                "product_type": row["product_type"],
                "batch_count": 0,
                "nearest_expiry_date": expiry_date,
                "available_stock": 0.0,
            },
        )
        item["batch_count"] += 1
        item["available_stock"] += _number(row["available_stock"])
        item["nearest_expiry_date"] = min(item["nearest_expiry_date"], expiry_date)
        if text_value(row, "barcode") > str(item["barcode"] or ""):
            item["barcode"] = row["barcode"]
    long_rows = list(long_groups.values())
    long_rows.sort(
        key=lambda row: (
            -row["available_stock"],
            row["nearest_expiry_date"],
            str(row["product_code"] or ""),
            str(row["warehouse"]),
            str(row["brand"]),
        )
    )
    long_offset = (long_page - 1) * page_size
    long_page_rows = long_rows[long_offset : long_offset + page_size]

    return {
        "keyword": keyword,
        "barcode": barcode,
        "warehouses_selected": list(warehouses),
        "product_types_selected": list(product_types),
        "expiry_range": expiry_range,
        "pagination": {"page": page, "page_size": page_size, "total": len(expiry_rows)},
        "long_pagination": {
            "page": long_page,
            "page_size": page_size,
            "total": len(long_total_keys),
        },
        "updated_at": _date_text(updated_at),
        "metrics": metrics,
        "fefo_rows": [
            {
                "rank": offset + index + 1,
                "warehouse": str(row["warehouse"]),
                "product_code": str(row["product_code"] or "-"),
                "barcode": str(row["barcode"] or "-"),
                "product": str(row["product"] or "未命名商品"),
                "brand": str(row["brand"]),
                "product_type": str(row["product_type"]),
                "batch": str(row["batch"] or "未标批次"),
                "production_date": _date_text(row["production_date"]),
                "expiry_date": _date_text(row["expiry_date"]),
                "remaining_days": (
                    (expiry(row) - today).days if expiry(row) is not None else None
                ),
                "stock": _number(row["stock"]),
                "available_stock": _number(row["available_stock"]),
                "product_batch_count": _integer(row["product_batch_count"]),
                "fefo_rank": _integer(row["fefo_rank"]),
                "status": _batch_status(
                    (expiry(row) - today).days if expiry(row) is not None else None
                ),
            }
            for index, row in enumerate(page_rows)
        ],
        "long_expiry_rows": [
            {
                "rank": long_offset + index + 1,
                "warehouse": str(row["warehouse"]),
                "product_code": str(row["product_code"] or "-"),
                "barcode": str(row["barcode"] or "-"),
                "product": str(row["product"] or "未命名商品"),
                "brand": str(row["brand"]),
                "product_type": str(row["product_type"]),
                "batch_count": _integer(row["batch_count"]),
                "nearest_expiry_date": _date_text(row["nearest_expiry_date"]),
                "remaining_months": round(
                    (row["nearest_expiry_date"] - today).days / 30.4375,
                    1,
                ),
                "available_stock": _number(row["available_stock"]),
            }
            for index, row in enumerate(long_page_rows)
        ],
    }
