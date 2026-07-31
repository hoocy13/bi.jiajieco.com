from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _dimension(value: object, fallback: str = "未归类") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def previous_month_end(value: date) -> date:
    return month_start(value) - timedelta(days=1)


def month_sequence(start_date: date, end_date: date) -> list[date]:
    values = []
    cursor = month_start(start_date)
    last = month_start(end_date)
    while cursor <= last:
        values.append(cursor)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return values


def load_brand_inventory_flow_source(
    ods_db: Session,
    *,
    start_date: date,
    end_date: date,
    brand: str,
) -> dict:
    normalized_start = month_start(start_date)
    normalized_end = month_end(end_date)
    opening_snapshot = previous_month_end(normalized_start)
    params = {
        "brand": brand.strip(),
        "start_date": normalized_start,
        "end_exclusive": normalized_end + timedelta(days=1),
        "opening_snapshot": opening_snapshot,
        "ending_snapshot": normalized_end,
    }

    sales_rows = ods_db.execute(
        text(
            """
            SELECT
              DATE_FORMAT(`下单时间`, '%Y-%m') AS month_key,
              COALESCE(NULLIF(TRIM(`发货仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类') AS product_type,
              SUM(COALESCE(`数量`, 0)) AS sales_quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS sales_amount,
              MAX(`updatetime`) AS updated_at
            FROM `销售单明细账`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < :end_exclusive
              AND TRIM(`品牌`) = :brand
            GROUP BY
              DATE_FORMAT(`下单时间`, '%Y-%m'),
              COALESCE(NULLIF(TRIM(`发货仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类')
            """
        ),
        params,
    ).mappings().all()

    inbound_rows = ods_db.execute(
        text(
            """
            SELECT
              DATE_FORMAT(h.`入库时间`, '%Y-%m') AS month_key,
              COALESCE(NULLIF(TRIM(h.`入库仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              SUM(COALESCE(d.`数量`, 0)) AS inbound_quantity,
              SUM(COALESCE(d.`入库成本金额`, 0)) AS inbound_cost,
              MAX(GREATEST(h.`updatetime`, d.`updatetime`)) AS updated_at
            FROM `入库查询明细` d
            JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE h.`入库时间` >= :start_date
              AND h.`入库时间` < :end_exclusive
              AND h.`入库类型编码` = '101'
              AND TRIM(d.`品牌`) = :brand
            GROUP BY
              DATE_FORMAT(h.`入库时间`, '%Y-%m'),
              COALESCE(NULLIF(TRIM(h.`入库仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')
            """
        ),
        params,
    ).mappings().all()

    stock_rows = ods_db.execute(
        text(
            """
            SELECT
              `快照日期` AS snapshot_date,
              COALESCE(NULLIF(TRIM(`仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(`分类`), ''), '未归类') AS product_type,
              SUM(COALESCE(`库存量`, 0)) AS stock_quantity,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
              MAX(`updatetime`) AS updated_at
            FROM `历史库存`
            WHERE `快照日期` BETWEEN :opening_snapshot AND :ending_snapshot
              AND TRIM(`品牌`) = :brand
            GROUP BY
              `快照日期`,
              COALESCE(NULLIF(TRIM(`仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(`分类`), ''), '未归类')
            """
        ),
        params,
    ).mappings().all()

    batch_rows = ods_db.execute(
        text(
            """
            SELECT
              `快照日期` AS snapshot_date,
              `状态` AS status,
              `完成时间` AS completed_at
            FROM `历史库存快照批次`
            WHERE `快照日期` BETWEEN :opening_snapshot AND :ending_snapshot
            ORDER BY `快照日期`
            """
        ),
        params,
    ).mappings().all()

    return {
        "sales": [dict(row) for row in sales_rows],
        "inbound": [dict(row) for row in inbound_rows],
        "stock": [dict(row) for row in stock_rows],
        "batches": [dict(row) for row in batch_rows],
    }


def build_brand_inventory_flow(
    source: dict,
    *,
    start_date: date,
    end_date: date,
    brand: str,
    warehouses: tuple[str, ...] = (),
    product_types: tuple[str, ...] = (),
) -> dict:
    normalized_start = month_start(start_date)
    normalized_end = month_end(end_date)
    warehouse_filter = set(warehouses)
    product_type_filter = set(product_types)

    def included(row: dict) -> bool:
        warehouse = _dimension(row.get("warehouse"))
        product_type = _dimension(row.get("product_type"))
        return (
            (not warehouse_filter or warehouse in warehouse_filter)
            and (not product_type_filter or product_type in product_type_filter)
        )

    warehouse_options = sorted(
        {
            _dimension(row.get("warehouse"))
            for collection in ("sales", "inbound", "stock")
            for row in source.get(collection, [])
        }
    )
    sales_by_month: dict[str, dict[str, Decimal]] = {}
    inbound_by_month: dict[str, dict[str, Decimal]] = {}
    stock_by_date: dict[date, dict[str, Decimal]] = {}
    source_updates = []

    for row in source.get("sales", []):
        if not included(row):
            continue
        month_key = str(row["month_key"])
        bucket = sales_by_month.setdefault(
            month_key,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        bucket["quantity"] += _decimal(row.get("sales_quantity"))
        bucket["amount"] += _decimal(row.get("sales_amount"))
        if row.get("updated_at"):
            source_updates.append(row["updated_at"])

    for row in source.get("inbound", []):
        if not included(row):
            continue
        month_key = str(row["month_key"])
        bucket = inbound_by_month.setdefault(
            month_key,
            {"quantity": Decimal(0), "cost": Decimal(0)},
        )
        bucket["quantity"] += _decimal(row.get("inbound_quantity"))
        bucket["cost"] += _decimal(row.get("inbound_cost"))
        if row.get("updated_at"):
            source_updates.append(row["updated_at"])

    for row in source.get("stock", []):
        if not included(row):
            continue
        snapshot_date = row["snapshot_date"]
        bucket = stock_by_date.setdefault(
            snapshot_date,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        bucket["quantity"] += _decimal(row.get("stock_quantity"))
        bucket["amount"] += _decimal(row.get("stock_amount"))
        if row.get("updated_at"):
            source_updates.append(row["updated_at"])

    months = []
    for month in month_sequence(normalized_start, normalized_end):
        month_key = month.strftime("%Y-%m")
        opening_date = previous_month_end(month)
        ending_date = month_end(month)
        opening = stock_by_date.get(
            opening_date,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        ending = stock_by_date.get(
            ending_date,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        inbound = inbound_by_month.get(
            month_key,
            {"quantity": Decimal(0), "cost": Decimal(0)},
        )
        sales = sales_by_month.get(
            month_key,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        available_quantity = opening["quantity"] + inbound["quantity"]
        sell_through_rate = (
            sales["quantity"] / available_quantity * Decimal(100)
            if available_quantity > 0
            else Decimal(0)
        )
        months.append(
            {
                "month": month_key,
                "opening_quantity": float(opening["quantity"]),
                "inbound_quantity": float(inbound["quantity"]),
                "sales_quantity": float(sales["quantity"]),
                "ending_quantity": float(ending["quantity"]),
                "sell_through_rate": float(sell_through_rate),
                "inbound_cost": float(inbound["cost"]),
                "sales_amount": float(sales["amount"]),
                "ending_stock_amount": float(ending["amount"]),
            }
        )

    first = months[0]
    last = months[-1]
    total_inbound = sum(_decimal(row["inbound_quantity"]) for row in months)
    total_sales = sum(_decimal(row["sales_quantity"]) for row in months)
    available = _decimal(first["opening_quantity"]) + total_inbound
    batches = source.get("batches", [])
    completed_batches = [row for row in batches if row.get("status") == "SUCCESS"]
    batch_updates = [
        row["completed_at"] for row in completed_batches if row.get("completed_at")
    ]
    expected_snapshots = len(months) + 1

    return {
        "brand": brand,
        "start_date": normalized_start.isoformat(),
        "end_date": normalized_end.isoformat(),
        "opening_snapshot_date": previous_month_end(normalized_start).isoformat(),
        "ending_snapshot_date": normalized_end.isoformat(),
        "period": (
            f"{normalized_start.strftime('%Y年%m月')}—"
            f"{normalized_end.strftime('%Y年%m月')}"
        ),
        "summary": {
            "opening_quantity": first["opening_quantity"],
            "inbound_quantity": float(total_inbound),
            "sales_quantity": float(total_sales),
            "ending_quantity": last["ending_quantity"],
            "sell_through_rate": float(
                total_sales / available * Decimal(100)
                if available > 0
                else Decimal(0)
            ),
            "inbound_cost": sum(row["inbound_cost"] for row in months),
            "sales_amount": sum(row["sales_amount"] for row in months),
            "ending_stock_amount": last["ending_stock_amount"],
        },
        "months": months,
        "filter_options": {"warehouses": warehouse_options},
        "freshness": {
            "snapshot_batches": len(completed_batches),
            "snapshot_expected": expected_snapshots,
            "snapshot_complete": len(completed_batches) == expected_snapshots,
            "snapshot_updated_at": max(batch_updates).isoformat() if batch_updates else None,
            "source_updated_at": (
                max(source_updates).isoformat() if source_updates else None
            ),
        },
        "metric_notes": {
            "inbound": "采购入库（入库类型编码 101），红冲和负数计入净额。",
            "sales": "销售单明细账按下单时间统计，退货或负数记录计入净销量。",
            "stock": "期初取所选起始月的上月末快照，期末取所选结束月的月末快照。",
        },
    }
