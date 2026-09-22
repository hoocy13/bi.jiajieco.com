from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


SLOW_RISK_CODES = ("no_sales", "return_anomaly", "critical", "slow")
RISK_META = {
    "no_sales": {"label": "真无动销", "order": 0},
    "return_anomaly": {"label": "净退货异常", "order": 1},
    "critical": {"label": "严重滞销", "order": 2},
    "slow": {"label": "滞销", "order": 3},
    "watch": {"label": "正常", "order": 4},
}
ALLOWED_PERIOD_DAYS = (30, 60, 90, 180)
ALLOWED_SORT_FIELDS = {
    "stock",
    "period_sales",
    "estimated_days",
    "ending_stock_ratio",
}


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _dimension(value: object, fallback: str = "未归类") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _product_key(row: dict) -> tuple[str, ...]:
    product_code = str(row.get("product_code") or "").strip()
    product_name = _dimension(row.get("product_name"), "未命名商品")
    if product_code:
        return (f"code:{product_code}",)
    return (
        f"name:{product_name}",
        _dimension(row.get("brand")),
        _dimension(row.get("product_type")),
    )


def _placeholders(prefix: str, values: tuple[str, ...], params: dict) -> str:
    names = []
    for index, value in enumerate(values):
        name = f"{prefix}_{index}"
        names.append(f":{name}")
        params[name] = value
    return ", ".join(names)


def load_completed_inventory_snapshots(ods_db: Session, limit: int = 24) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              `快照日期` AS snapshot_date,
              MAX(`完成时间`) AS completed_at
            FROM `历史库存快照批次`
            WHERE UPPER(COALESCE(`状态`, '')) = 'SUCCESS'
            GROUP BY `快照日期`
            ORDER BY `快照日期` DESC
            LIMIT :limit
            """
        ),
        {"limit": max(1, min(limit, 60))},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_current_slow_moving_stock(
    ods_db: Session,
    *,
    as_of_date: date,
    keyword: str = "",
    barcode: str = "",
    warehouses: tuple[str, ...] = (),
    product_types: tuple[str, ...] = (),
) -> list[dict]:
    params: dict[str, object] = {"snapshot_date": as_of_date.isoformat()}
    filters = ["COALESCE(s.`可用库存`, 0) <> 0"]
    if warehouses:
        filters.append(
            f"COALESCE(NULLIF(TRIM(s.`仓库`), ''), '未归类') IN ({_placeholders('current_warehouse', warehouses, params)})"
        )
    if product_types:
        filters.append(
            f"COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') IN ({_placeholders('current_product_type', product_types, params)})"
        )
    if keyword:
        params["current_keyword"] = f"%{keyword}%"
        filters.append(
            "(s.`货品编号` LIKE :current_keyword OR s.`货品名称` LIKE :current_keyword "
            "OR s.`品牌` LIKE :current_keyword OR s.`条码` LIKE :current_keyword)"
        )
    if barcode:
        params["current_barcode"] = f"%{barcode}%"
        filters.append("s.`条码` LIKE :current_barcode")

    rows = ods_db.execute(
        text(
            f"""
            SELECT
              CAST(:snapshot_date AS DATE) AS snapshot_date,
              COALESCE(NULLIF(TRIM(s.`仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(TRIM(s.`货品编号`), ''), '') AS product_code,
              COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品') AS product_name,
              COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类') AS brand,
              MAX(COALESCE(NULLIF(TRIM(s.`条码`), ''), '')) AS barcode,
              SUM(COALESCE(s.`库存数量`, 0)) AS inventory_stock_quantity,
              SUM(COALESCE(s.`可用库存`, 0)) AS stock_quantity,
              MAX(s.`updatetime`) AS updated_at
            FROM `分仓库查询` s
            WHERE {' AND '.join(filters)}
            GROUP BY
              COALESCE(NULLIF(TRIM(s.`仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品编号`), ''), ''),
              COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品'),
              COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')
            HAVING SUM(COALESCE(s.`可用库存`, 0)) > 0
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def load_slow_moving_period_source(
    ods_db: Session,
    *,
    snapshot_dates: tuple[date, ...],
    period_days: int,
    keyword: str = "",
    barcode: str = "",
    warehouses: tuple[str, ...] = (),
    product_types: tuple[str, ...] = (),
    ads_db: Session | None = None,
    sales_data_version: str | None = None,
) -> dict:
    if not snapshot_dates:
        return {"stock": [], "sales": []}

    params: dict[str, object] = {
        "sales_start": min(snapshot_dates) - timedelta(days=period_days - 1),
        "sales_end": max(snapshot_dates),
    }
    snapshot_placeholders = _placeholders(
        "snapshot", tuple(value.isoformat() for value in snapshot_dates), params
    )
    needs_product_meta = bool(keyword or barcode)
    product_meta_join = """
            LEFT JOIN (
              SELECT `货品编号` AS product_code, MAX(`条码`) AS barcode
              FROM `分仓库查询`
              WHERE NULLIF(TRIM(`货品编号`), '') IS NOT NULL
              GROUP BY `货品编号`
            ) p ON p.product_code = h.`货品编号`
    """ if needs_product_meta else ""
    barcode_select = "MAX(p.barcode)" if needs_product_meta else "''"
    filters = []
    if warehouses:
        filters.append(
            f"COALESCE(NULLIF(TRIM(h.`仓库`), ''), '未归类') IN ({_placeholders('warehouse', warehouses, params)})"
        )
    if product_types:
        filters.append(
            f"COALESCE(NULLIF(TRIM(h.`分类`), ''), '未归类') IN ({_placeholders('product_type', product_types, params)})"
        )
    if keyword:
        params["keyword"] = f"%{keyword}%"
        filters.append(
            "(h.`货品编号` LIKE :keyword OR h.`货品名称` LIKE :keyword "
            "OR h.`品牌` LIKE :keyword OR p.barcode LIKE :keyword)"
        )
    if barcode:
        params["barcode"] = f"%{barcode}%"
        filters.append("p.barcode LIKE :barcode")
    stock_filter_sql = "" if not filters else " AND " + " AND ".join(filters)

    stock_rows = ods_db.execute(
        text(
            f"""
            SELECT
              h.`快照日期` AS snapshot_date,
              COALESCE(NULLIF(TRIM(h.`仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(h.`分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(TRIM(h.`货品编号`), ''), '') AS product_code,
              COALESCE(NULLIF(TRIM(h.`货品名称`), ''), '未命名商品') AS product_name,
              COALESCE(NULLIF(TRIM(h.`品牌`), ''), '未归类') AS brand,
              {barcode_select} AS barcode,
              SUM(COALESCE(h.`库存量`, 0)) AS stock_quantity,
              MAX(h.`updatetime`) AS updated_at
            FROM `历史库存` h
            {product_meta_join}
            WHERE h.`快照日期` IN ({snapshot_placeholders})
              {stock_filter_sql}
            GROUP BY
              h.`快照日期`,
              COALESCE(NULLIF(TRIM(h.`仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(h.`分类`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(h.`货品编号`), ''), ''),
              COALESCE(NULLIF(TRIM(h.`货品名称`), ''), '未命名商品'),
              COALESCE(NULLIF(TRIM(h.`品牌`), ''), '未归类')
            HAVING SUM(COALESCE(h.`库存量`, 0)) > 0
            """
        ),
        params,
    ).mappings().all()

    if not needs_product_meta:
        product_meta_rows = ods_db.execute(
            text(
                """
                SELECT `货品编号` AS product_code, MAX(`条码`) AS barcode
                FROM `分仓库查询`
                WHERE NULLIF(TRIM(`货品编号`), '') IS NOT NULL
                GROUP BY `货品编号`
                """
            )
        ).mappings().all()
        barcode_by_code = {
            str(row["product_code"] or "").strip(): str(row["barcode"] or "").strip()
            for row in product_meta_rows
        }
        stock_rows = [
            {**dict(row), "barcode": barcode_by_code.get(str(row["product_code"] or "").strip(), "")}
            for row in stock_rows
        ]

    sales_filters = []
    sales_params: dict[str, object] = {
        "sales_start": params["sales_start"],
        "sales_end": params["sales_end"],
        "lookback_days": period_days - 1,
    }
    window_parts = []
    for index, value in enumerate(snapshot_dates):
        name = f"sales_snapshot_{index}"
        sales_params[name] = value.isoformat()
        window_parts.append(f"SELECT CAST(:{name} AS DATE) AS snapshot_date")
    sales_window_sql = " UNION ALL ".join(window_parts)
    if warehouses:
        sales_filters.append(
            f"COALESCE(NULLIF(TRIM({('s.`warehouse`' if ads_db is not None and sales_data_version else 's.`发货仓库`')}), ''), '未归类') "
            f"IN ({_placeholders('sales_warehouse', warehouses, sales_params)})"
        )
    # Product classification is taken from the selected inventory snapshot.
    # Sales-side classification can lag or differ for the same stable product code;
    # filtering it here would turn valid sales into zero and inflate retention to 100%.
    sales_filter_sql = "" if not sales_filters else " AND " + " AND ".join(sales_filters)

    if ads_db is not None and sales_data_version:
        sales_params["data_version"] = sales_data_version
        sales_rows = ads_db.execute(
            text(
                f"""
                SELECT
                  w.snapshot_date AS snapshot_date,
                  COALESCE(NULLIF(TRIM(s.`warehouse`), ''), '未归类') AS warehouse,
                  COALESCE(NULLIF(TRIM(s.`product_type`), ''), '未归类') AS product_type,
                  COALESCE(NULLIF(TRIM(s.`product_code`), ''), '') AS product_code,
                  COALESCE(NULLIF(TRIM(s.`product`), ''), '未命名商品') AS product_name,
                  COALESCE(NULLIF(TRIM(s.`brand`), ''), '未归类') AS brand,
                  SUM(COALESCE(s.`quantity`, 0)) AS sales_quantity,
                  SUM(CASE WHEN COALESCE(s.`quantity`, 0) > 0 THEN s.`quantity` ELSE 0 END) AS positive_sales_quantity,
                  SUM(CASE WHEN COALESCE(s.`quantity`, 0) < 0 THEN -s.`quantity` ELSE 0 END) AS return_quantity,
                  MAX(CASE WHEN COALESCE(s.`quantity`, 0) > 0 THEN s.`sales_date` END) AS last_sale_at
                FROM ({sales_window_sql}) w
                INNER JOIN `ads_sales_brand_turnover_item` s
                  ON s.`sales_date` BETWEEN DATE_SUB(w.snapshot_date, INTERVAL :lookback_days DAY) AND w.snapshot_date
                WHERE s.`data_version` = :data_version
                  {sales_filter_sql}
                GROUP BY
                  w.snapshot_date, s.`warehouse`, s.`product_type`,
                  s.`product_code`, s.`product`, s.`brand`
                """
            ),
            sales_params,
        ).mappings().all()
    else:
        sales_rows = ods_db.execute(
            text(
                f"""
                SELECT
                  w.snapshot_date AS snapshot_date,
                  COALESCE(NULLIF(TRIM(s.`发货仓库`), ''), '未归类') AS warehouse,
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
                  COALESCE(NULLIF(TRIM(s.`货品编号`), ''), '') AS product_code,
                  COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品') AS product_name,
                  COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类') AS brand,
                  SUM(COALESCE(s.`数量`, 0)) AS sales_quantity,
                  SUM(CASE WHEN COALESCE(s.`数量`, 0) > 0 THEN s.`数量` ELSE 0 END) AS positive_sales_quantity,
                  SUM(CASE WHEN COALESCE(s.`数量`, 0) < 0 THEN -s.`数量` ELSE 0 END) AS return_quantity,
                  MAX(CASE WHEN COALESCE(s.`数量`, 0) > 0 THEN s.`下单时间` END) AS last_sale_at
                FROM ({sales_window_sql}) w
                INNER JOIN `dwd`.`销售单明细账_品牌补全` s
                  ON s.`下单时间` >= DATE_SUB(w.snapshot_date, INTERVAL :lookback_days DAY)
                 AND s.`下单时间` < DATE_ADD(w.snapshot_date, INTERVAL 1 DAY)
                WHERE 1 = 1
                  {sales_filter_sql}
                GROUP BY
                  w.snapshot_date,
                  COALESCE(NULLIF(TRIM(s.`发货仓库`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
                  COALESCE(NULLIF(TRIM(s.`货品编号`), ''), ''),
                  COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品'),
                  COALESCE(NULLIF(TRIM(s.`品牌`), ''), '未归类')
                """
            ),
            sales_params,
        ).mappings().all()

    return {
        "stock": [dict(row) for row in stock_rows],
        "sales": [dict(row) for row in sales_rows],
    }


def _risk(
    stock: Decimal,
    net_sales: Decimal,
    positive_sales: Decimal,
    period_days: int,
) -> tuple[str, float | None]:
    if positive_sales <= 0:
        return "no_sales", None
    if net_sales <= 0:
        return "return_anomaly", None
    estimated_days = stock / net_sales * Decimal(period_days)
    if estimated_days > 180:
        return "critical", float(estimated_days)
    if estimated_days > 90:
        return "slow", float(estimated_days)
    return "watch", float(estimated_days)


def build_slow_moving_period_analysis(
    source: dict,
    *,
    snapshot_date: date,
    trend_dates: tuple[date, ...],
    period_days: int,
    risk_scope: str = "slow_all",
    retention_scope: str = "all",
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "stock",
    sort_order: str = "desc",
    basis: str = "historical_month_end_stock",
    sales_end_date: date | None = None,
) -> dict:
    if period_days not in ALLOWED_PERIOD_DAYS:
        raise ValueError("Unsupported observation period")
    sales_end_date = sales_end_date or snapshot_date
    all_dates = tuple(sorted(set((*trend_dates, snapshot_date))))

    stock_by_date: dict[date, dict[tuple[str, str, str], dict]] = defaultdict(dict)
    latest_update: datetime | None = None
    for raw in source.get("stock", []):
        row = dict(raw)
        row_date = _date(row.get("snapshot_date"))
        if row_date not in all_dates:
            continue
        key = _product_key(row)
        aggregate = stock_by_date[row_date].setdefault(
            key,
            {
                "product_code": str(row.get("product_code") or "").strip(),
                "product": _dimension(row.get("product_name"), "未命名商品"),
                "brand": _dimension(row.get("brand")),
                "product_type": _dimension(row.get("product_type")),
                "barcode": str(row.get("barcode") or "").strip(),
                "warehouses": set(),
                "inventory_stock": Decimal(0),
                "stock": Decimal(0),
            },
        )
        aggregate["warehouses"].add(_dimension(row.get("warehouse")))
        aggregate["inventory_stock"] += _decimal(
            row.get("inventory_stock_quantity", row.get("stock_quantity"))
        )
        aggregate["stock"] += _decimal(row.get("stock_quantity"))
        updated_at = row.get("updated_at")
        if isinstance(updated_at, datetime) and (latest_update is None or updated_at > latest_update):
            latest_update = updated_at

    sales_by_key: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    window_sales: dict[date, dict[tuple[str, ...], dict]] = defaultdict(dict)
    for raw in source.get("sales", []):
        row = dict(raw)
        key = _product_key(row)
        sales_metrics = {
            "net": _decimal(row.get("sales_quantity")),
            "positive": _decimal(row.get("positive_sales_quantity", max(_decimal(row.get("sales_quantity")), Decimal(0)))),
            "returns": _decimal(row.get("return_quantity")),
            "last_sale_at": row.get("last_sale_at"),
        }
        if row.get("snapshot_date") is not None:
            snapshot_metrics = window_sales[_date(row.get("snapshot_date"))].setdefault(
                key,
                {"net": Decimal(0), "positive": Decimal(0), "returns": Decimal(0), "last_sale_at": None},
            )
            snapshot_metrics["net"] += sales_metrics["net"]
            snapshot_metrics["positive"] += sales_metrics["positive"]
            snapshot_metrics["returns"] += sales_metrics["returns"]
            if sales_metrics["last_sale_at"] and (
                snapshot_metrics["last_sale_at"] is None
                or sales_metrics["last_sale_at"] > snapshot_metrics["last_sale_at"]
            ):
                snapshot_metrics["last_sale_at"] = sales_metrics["last_sale_at"]
        else:
            sales_by_key[key].append({"sales_date": _date(row.get("sales_date")), **sales_metrics})

    def snapshot_rows(value: date) -> list[dict]:
        start = value - timedelta(days=period_days - 1)
        aggregates = stock_by_date.get(value, {})
        result = []
        for key, item in aggregates.items():
            if item["stock"] <= 0:
                continue
            metrics = window_sales.get(value, {}).get(key)
            if metrics is None:
                matched_sales = [
                    sale for sale in sales_by_key.get(key, []) if start <= sale["sales_date"] <= value
                ]
                metrics = {
                    "net": sum((sale["net"] for sale in matched_sales), Decimal(0)),
                    "positive": sum((sale["positive"] for sale in matched_sales), Decimal(0)),
                    "returns": sum((sale["returns"] for sale in matched_sales), Decimal(0)),
                    "last_sale_at": max(
                        (sale["last_sale_at"] for sale in matched_sales if sale["last_sale_at"] is not None),
                        default=None,
                    ),
                }
            period_sales = metrics["net"]
            positive_sales = metrics["positive"]
            risk_code, estimated_days = _risk(item["stock"], period_sales, positive_sales, period_days)
            ending_denominator = item["stock"] + positive_sales
            result.append(
                {
                    **{key: value for key, value in item.items() if key != "warehouses"},
                    "warehouse_count": len(item["warehouses"]),
                    "period_sales": float(period_sales),
                    "positive_sales": float(positive_sales),
                    "return_quantity": float(metrics["returns"]),
                    "last_sale_at": metrics["last_sale_at"].isoformat() if metrics["last_sale_at"] else None,
                    "estimated_days": estimated_days,
                    "risk_code": risk_code,
                    "risk_label": RISK_META[risk_code]["label"],
                    "ending_stock_ratio": float(item["stock"] / ending_denominator * 100) if ending_denominator else 0,
                }
            )
        return result

    current_rows = snapshot_rows(snapshot_date)
    all_stock_quantity = sum((_decimal(row["stock"]) for row in current_rows), Decimal(0))
    slow_rows = [row for row in current_rows if row["risk_code"] in SLOW_RISK_CODES]
    slow_stock_quantity = sum((_decimal(row["stock"]) for row in slow_rows), Decimal(0))
    no_sales_stock_quantity = sum(
        (_decimal(row["stock"]) for row in current_rows if row["risk_code"] == "no_sales"),
        Decimal(0),
    )
    return_anomaly_stock_quantity = sum(
        (_decimal(row["stock"]) for row in current_rows if row["risk_code"] == "return_anomaly"),
        Decimal(0),
    )

    distribution = []
    for code in (*SLOW_RISK_CODES, "watch"):
        items = [row for row in current_rows if row["risk_code"] == code]
        stock_quantity = sum((_decimal(row["stock"]) for row in items), Decimal(0))
        distribution.append(
            {
                "risk_code": code,
                "risk_label": RISK_META[code]["label"],
                "sku_count": len(items),
                "stock_quantity": float(stock_quantity),
                "stock_quantity_share": float(stock_quantity / all_stock_quantity * 100) if all_stock_quantity else 0,
            }
        )

    trend = []
    for trend_date in sorted(trend_dates):
        rows = snapshot_rows(trend_date)
        stock_quantity = sum((_decimal(row["stock"]) for row in rows), Decimal(0))
        trend_slow_stock_quantity = sum(
            (_decimal(row["stock"]) for row in rows if row["risk_code"] in SLOW_RISK_CODES),
            Decimal(0),
        )
        stock_sku_count = len(rows)
        slow_sku_count = sum(1 for row in rows if row["risk_code"] in SLOW_RISK_CODES)
        trend.append(
            {
                "snapshot_date": trend_date.isoformat(),
                "stock_quantity": float(stock_quantity),
                "slow_stock_quantity": float(trend_slow_stock_quantity),
                "slow_stock_share": float(trend_slow_stock_quantity / stock_quantity * 100) if stock_quantity else 0,
                "stock_sku_count": stock_sku_count,
                "slow_sku_count": slow_sku_count,
                "slow_sku_share": float(Decimal(slow_sku_count) / Decimal(stock_sku_count) * 100) if stock_sku_count else 0,
            }
        )

    brand_distribution = []
    brands = sorted({row["brand"] for row in current_rows})
    for brand in brands:
        items = [row for row in current_rows if row["brand"] == brand]
        brand_stock = sum((_decimal(row["stock"]) for row in items), Decimal(0))
        brand_slow = [row for row in items if row["risk_code"] in SLOW_RISK_CODES]
        slow_stock = sum((_decimal(row["stock"]) for row in brand_slow), Decimal(0))
        if slow_stock <= 0:
            continue
        brand_distribution.append(
            {
                "brand": brand,
                "stock_quantity": float(brand_stock),
                "slow_stock_quantity": float(slow_stock),
                "slow_stock_share": float(slow_stock / brand_stock * 100) if brand_stock else 0,
                "slow_sku_count": len(brand_slow),
            }
        )
    brand_distribution.sort(key=lambda row: (row["slow_stock_quantity"], row["slow_sku_count"]), reverse=True)

    if risk_scope == "slow_all":
        filtered_rows = slow_rows
    elif risk_scope in RISK_META:
        filtered_rows = [row for row in current_rows if row["risk_code"] == risk_scope]
    else:
        filtered_rows = current_rows

    if retention_scope == "ge90":
        filtered_rows = [row for row in filtered_rows if row["ending_stock_ratio"] >= 90]
    elif retention_scope == "70_90":
        filtered_rows = [row for row in filtered_rows if 70 <= row["ending_stock_ratio"] < 90]
    elif retention_scope == "50_70":
        filtered_rows = [row for row in filtered_rows if 50 <= row["ending_stock_ratio"] < 70]
    elif retention_scope == "lt50":
        filtered_rows = [row for row in filtered_rows if row["ending_stock_ratio"] < 50]

    normalized_sort = sort_by if sort_by in ALLOWED_SORT_FIELDS else "stock"
    reverse = sort_order != "asc"

    def sort_value(row: dict) -> tuple:
        value = row.get(normalized_sort)
        if value is None:
            value = float("inf") if not reverse else -1
        return float(value), row["product_code"], row["product"]

    filtered_rows = sorted(filtered_rows, key=sort_value, reverse=reverse)
    offset = (page - 1) * page_size
    paged_rows = filtered_rows[offset : offset + page_size]
    for index, row in enumerate(paged_rows):
        row["rank"] = offset + index + 1
        row["inventory_stock"] = float(row["inventory_stock"])
        row["stock"] = float(row["stock"])

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "sales_end_date": sales_end_date.isoformat(),
        "period_days": period_days,
        "retention_scope": retention_scope,
        "period_start": (sales_end_date - timedelta(days=period_days - 1)).isoformat(),
        "basis": basis,
        "updated_at": latest_update.isoformat() if latest_update else None,
        "summary": {
            "stock_quantity": float(all_stock_quantity),
            "stock_sku_count": len(current_rows),
            "slow_stock_quantity": float(slow_stock_quantity),
            "slow_stock_share": float(slow_stock_quantity / all_stock_quantity * 100) if all_stock_quantity else 0,
            "slow_sku_count": len(slow_rows),
            "slow_sku_share": float(Decimal(len(slow_rows)) / Decimal(len(current_rows)) * 100) if current_rows else 0,
            "no_sales_stock_quantity": float(no_sales_stock_quantity),
            "no_sales_sku_count": sum(1 for row in current_rows if row["risk_code"] == "no_sales"),
            "return_anomaly_stock_quantity": float(return_anomaly_stock_quantity),
            "return_anomaly_sku_count": sum(1 for row in current_rows if row["risk_code"] == "return_anomaly"),
        },
        "risk_distribution": distribution,
        "brand_distribution": brand_distribution[:10],
        "trend": trend,
        "pagination": {"page": page, "page_size": page_size, "total": len(filtered_rows)},
        "rows": paged_rows,
    }
