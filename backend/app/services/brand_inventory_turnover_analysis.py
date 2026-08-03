from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sales_sources import is_online_sales_channel


PRODUCT_TYPES = ("正装", "小样")


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _dimension(value: object, fallback: str = "未归类") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def _month_sequence(start_date: date, end_date: date) -> list[date]:
    values: list[date] = []
    cursor = _month_start(start_date)
    last = _month_start(end_date)
    while cursor <= last:
        values.append(cursor)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return values


def _snapshot_sequence(start_date: date, end_date: date) -> list[date]:
    opening = _month_start(start_date) - timedelta(days=1)
    return [opening, *[_month_end(month) for month in _month_sequence(start_date, end_date)]]


def load_brand_inventory_turnover_source(
    ods_db: Session,
    *,
    start_date: date,
    end_date: date,
    brand: str,
    ads_db: Session | None = None,
    sales_data_version: str | None = None,
) -> dict:
    normalized_start = _month_start(start_date)
    normalized_end = _month_end(end_date)
    params = {
        "brand": brand.strip(),
        "start_date": normalized_start,
        "end_exclusive": normalized_end + timedelta(days=1),
        "opening_snapshot": normalized_start - timedelta(days=1),
        "ending_snapshot": normalized_end,
    }

    channel_sales_rows = []
    channel_sales_scope = "warehouse"
    if ads_db is not None and sales_data_version:
        channel_sales_scope = "all"
        ads_params = {
            "data_version": sales_data_version,
            "brand": brand.strip(),
            "start_date": normalized_start,
            "end_date": normalized_end,
        }
        sales_rows = ads_db.execute(
            text(
                """
                SELECT
                  DATE_FORMAT(`sales_date`, '%Y-%m') AS month_key,
                  `warehouse`,
                  `product_type`,
                  COALESCE(`product_code`, '') AS product_code,
                  COALESCE(`product`, '未命名商品') AS product_name,
                  SUM(`quantity`) AS sales_quantity,
                  SUM(`paid_amount`) AS sales_amount,
                  MAX(`sales_date`) AS last_sale_date
                FROM `ads_sales_brand_turnover_item`
                WHERE `data_version` = :data_version
                  AND `sales_date` BETWEEN :start_date AND :end_date
                  AND `brand` = :brand
                  AND `product_type` IN ('正装', '小样')
                GROUP BY
                  DATE_FORMAT(`sales_date`, '%Y-%m'),
                  `warehouse`, `product_type`,
                  COALESCE(`product_code`, ''),
                  COALESCE(`product`, '未命名商品')
                """
            ),
            ads_params,
        ).mappings().all()
        raw_channel_rows = ads_db.execute(
            text(
                """
                SELECT
                  `channel` AS channel_name,
                  SUM(`quantity`) AS sales_quantity,
                  SUM(`paid_amount`) AS sales_amount
                FROM `ads_sales_daily_brand_channel_scope`
                WHERE `data_version` = :data_version
                  AND `sales_date` BETWEEN :start_date AND :end_date
                  AND `brand` = :brand
                  AND `product_type_scope` = 'selected'
                GROUP BY `channel`
                """
            ),
            ads_params,
        ).mappings().all()
        channel_names = [str(row["channel_name"]) for row in raw_channel_rows]
        channel_lookup = {}
        if channel_names:
            channel_params = {f"channel_{index}": value for index, value in enumerate(channel_names)}
            placeholders = ", ".join(f":channel_{index}" for index in range(len(channel_names)))
            channel_rows = ods_db.execute(
                text(
                    f"""
                    SELECT
                      `渠道名称` AS channel_name,
                      MAX(`分类`) AS channel_category,
                      MAX(`线上平台`) AS channel_platform,
                      MAX(`默认仓库`) AS channel_default_warehouse
                    FROM `渠道列表`
                    WHERE `渠道名称` IN ({placeholders})
                    GROUP BY `渠道名称`
                    """
                ),
                channel_params,
            ).mappings().all()
            channel_lookup = {row["channel_name"]: dict(row) for row in channel_rows}
        channel_sales_rows = [
            {**dict(row), **channel_lookup.get(row["channel_name"], {})}
            for row in raw_channel_rows
        ]
    else:
        sales_rows = ods_db.execute(
            text(
                """
            SELECT
              DATE_FORMAT(s.`下单时间`, '%Y-%m') AS month_key,
              COALESCE(NULLIF(TRIM(s.`发货仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(TRIM(s.`货品编号`), ''), '') AS product_code,
              COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品') AS product_name,
              COALESCE(NULLIF(TRIM(s.`销售渠道`), ''), '未归类') AS channel_name,
              COALESCE(NULLIF(TRIM(c.category), ''), '未分类') AS channel_category,
              COALESCE(NULLIF(TRIM(c.platform), ''), '未设置') AS channel_platform,
              COALESCE(NULLIF(TRIM(c.default_warehouse), ''), '') AS channel_default_warehouse,
              SUM(COALESCE(s.`数量`, 0)) AS sales_quantity,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS sales_amount,
              MAX(s.`下单时间`) AS last_sale_date,
              MAX(s.`updatetime`) AS updated_at
            FROM `dwd`.`销售单明细账_品牌补全` s
            LEFT JOIN (
              SELECT
                `渠道名称` AS channel_name,
                MAX(`分类`) AS category,
                MAX(`线上平台`) AS platform,
                MAX(`默认仓库`) AS default_warehouse
              FROM `渠道列表`
              WHERE NULLIF(TRIM(`渠道名称`), '') IS NOT NULL
              GROUP BY `渠道名称`
            ) c ON c.channel_name = COALESCE(NULLIF(TRIM(s.`销售渠道`), ''), '未归类')
            WHERE s.`下单时间` >= :start_date
              AND s.`下单时间` < :end_exclusive
              AND TRIM(s.`品牌`) = :brand
              AND COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') IN ('正装', '小样')
            GROUP BY
              DATE_FORMAT(s.`下单时间`, '%Y-%m'),
              COALESCE(NULLIF(TRIM(s.`发货仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品编号`), ''), ''),
              COALESCE(NULLIF(TRIM(s.`货品名称`), ''), '未命名商品'),
              COALESCE(NULLIF(TRIM(s.`销售渠道`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(c.category), ''), '未分类'),
              COALESCE(NULLIF(TRIM(c.platform), ''), '未设置'),
              COALESCE(NULLIF(TRIM(c.default_warehouse), ''), '')
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
              COALESCE(NULLIF(TRIM(`货品编号`), ''), '') AS product_code,
              COALESCE(NULLIF(TRIM(`货品名称`), ''), '未命名商品') AS product_name,
              SUM(COALESCE(`库存量`, 0)) AS stock_quantity,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
              MAX(`updatetime`) AS updated_at
            FROM `历史库存`
            WHERE `快照日期` BETWEEN :opening_snapshot AND :ending_snapshot
              AND TRIM(`品牌`) = :brand
              AND COALESCE(NULLIF(TRIM(`分类`), ''), '未归类') IN ('正装', '小样')
            GROUP BY
              `快照日期`,
              COALESCE(NULLIF(TRIM(`仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(`分类`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(`货品编号`), ''), ''),
              COALESCE(NULLIF(TRIM(`货品名称`), ''), '未命名商品')
            """
        ),
        params,
    ).mappings().all()

    batch_rows = ods_db.execute(
        text(
            """
            SELECT `快照日期` AS snapshot_date, `状态` AS status, `完成时间` AS completed_at
            FROM `历史库存快照批次`
            WHERE `快照日期` BETWEEN :opening_snapshot AND :ending_snapshot
            ORDER BY `快照日期`
            """
        ),
        params,
    ).mappings().all()

    return {
        "sales": [dict(row) for row in sales_rows],
        "channel_sales": channel_sales_rows,
        "channel_sales_scope": channel_sales_scope,
        "stock": [dict(row) for row in stock_rows],
        "batches": [dict(row) for row in batch_rows],
    }


def _turnover_values(
    sales_quantity: Decimal,
    average_inventory: Decimal,
    period_days: int,
) -> tuple[float | None, float | None]:
    if average_inventory <= 0:
        return None, None
    turnover_rate = sales_quantity / average_inventory
    if turnover_rate <= 0:
        return float(turnover_rate), None
    return float(turnover_rate), float(Decimal(period_days) / turnover_rate)


def build_brand_inventory_turnover_analysis(
    source: dict,
    *,
    start_date: date,
    end_date: date,
    brand: str,
    warehouses: tuple[str, ...] = (),
    product_types: tuple[str, ...] = PRODUCT_TYPES,
    ranking_limit: int = 10,
) -> dict:
    normalized_start = _month_start(start_date)
    normalized_end = _month_end(end_date)
    months = _month_sequence(normalized_start, normalized_end)
    expected_snapshots = _snapshot_sequence(normalized_start, normalized_end)
    warehouse_filter = set(warehouses)
    product_type_filter = set(product_types)

    def included(row: dict) -> bool:
        warehouse = _dimension(row.get("warehouse"))
        product_type = _dimension(row.get("product_type"))
        return (
            (not warehouse_filter or warehouse in warehouse_filter)
            and (not product_type_filter or product_type in product_type_filter)
        )

    completed_dates = {
        row["snapshot_date"]
        for row in source.get("batches", [])
        if row.get("status") == "SUCCESS" and row.get("snapshot_date") in expected_snapshots
    }
    dates_with_stock = {
        row["snapshot_date"]
        for row in source.get("stock", [])
        if included(row) and row.get("snapshot_date") in expected_snapshots
    }
    valid_snapshots = [
        snapshot_date
        for snapshot_date in expected_snapshots
        if snapshot_date in completed_dates or snapshot_date in dates_with_stock
    ]
    if not valid_snapshots:
        valid_snapshots = expected_snapshots

    products: dict[str, dict] = {}
    channel_sales = {
        "线上": {"sales_quantity": Decimal(0), "sales_amount": Decimal(0), "channels": set()},
        "线下": {"sales_quantity": Decimal(0), "sales_amount": Decimal(0), "channels": set()},
    }
    source_updates = []

    def product_bucket(row: dict) -> dict:
        product_code = str(row.get("product_code") or "").strip()
        product_name = _dimension(row.get("product_name"), "未命名商品")
        key = product_code or f"name:{product_name}"
        return products.setdefault(
            key,
            {
                "product_code": product_code,
                "product_name": product_name,
                "product_type": _dimension(row.get("product_type")),
                "sales_quantity": Decimal(0),
                "sales_amount": Decimal(0),
                "last_sale_date": None,
                "sales_by_month": {},
                "stock_by_date": {},
            },
        )

    for row in source.get("sales", []):
        if not included(row):
            continue
        bucket = product_bucket(row)
        quantity = _decimal(row.get("sales_quantity"))
        amount = _decimal(row.get("sales_amount"))
        bucket["sales_quantity"] += quantity
        bucket["sales_amount"] += amount
        month_key = str(row.get("month_key"))
        bucket["sales_by_month"][month_key] = (
            bucket["sales_by_month"].get(month_key, Decimal(0)) + quantity
        )
        last_sale_date = row.get("last_sale_date")
        if last_sale_date and (
            bucket["last_sale_date"] is None or last_sale_date > bucket["last_sale_date"]
        ):
            bucket["last_sale_date"] = last_sale_date
        if row.get("channel_name"):
            channel_kind = (
                "线上"
                if is_online_sales_channel(
                    row.get("channel_category"),
                    row.get("channel_platform"),
                    row.get("channel_name"),
                )
                else "线下"
            )
            channel_sales[channel_kind]["sales_quantity"] += quantity
            channel_sales[channel_kind]["sales_amount"] += amount
            channel_sales[channel_kind]["channels"].add(_dimension(row.get("channel_name")))
        if row.get("updated_at"):
            source_updates.append(row["updated_at"])

    if not warehouse_filter or source.get("channel_sales_scope") != "all":
        for row in source.get("channel_sales", []):
            channel_kind = (
                "线上"
                if is_online_sales_channel(
                    row.get("channel_category"),
                    row.get("channel_platform"),
                    row.get("channel_name"),
                )
                else "线下"
            )
            channel_sales[channel_kind]["sales_quantity"] += _decimal(row.get("sales_quantity"))
            channel_sales[channel_kind]["sales_amount"] += _decimal(row.get("sales_amount"))
            channel_sales[channel_kind]["channels"].add(_dimension(row.get("channel_name")))

    for row in source.get("stock", []):
        if not included(row):
            continue
        bucket = product_bucket(row)
        snapshot_date = row.get("snapshot_date")
        stock_bucket = bucket["stock_by_date"].setdefault(
            snapshot_date,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        stock_bucket["quantity"] += _decimal(row.get("stock_quantity"))
        stock_bucket["amount"] += _decimal(row.get("stock_amount"))
        if row.get("updated_at"):
            source_updates.append(row["updated_at"])

    period_days = (normalized_end - normalized_start).days + 1
    product_rows = []
    for bucket in products.values():
        stock_quantities = [
            bucket["stock_by_date"].get(value, {}).get("quantity", Decimal(0))
            for value in valid_snapshots
        ]
        stock_amounts = [
            bucket["stock_by_date"].get(value, {}).get("amount", Decimal(0))
            for value in valid_snapshots
        ]
        average_inventory = sum(stock_quantities, Decimal(0)) / Decimal(len(valid_snapshots))
        average_inventory_amount = sum(stock_amounts, Decimal(0)) / Decimal(len(valid_snapshots))
        ending = bucket["stock_by_date"].get(
            normalized_end,
            {"quantity": Decimal(0), "amount": Decimal(0)},
        )
        turnover_rate, turnover_days = _turnover_values(
            bucket["sales_quantity"], average_inventory, period_days
        )
        if bucket["sales_quantity"] <= 0 and ending["quantity"] > 0:
            status = "无销售"
        elif turnover_days is None:
            status = "暂不可算"
        elif turnover_days > 180:
            status = "滞销"
        elif turnover_days > 90:
            status = "偏慢"
        else:
            status = "正常"
        product_rows.append(
            {
                "product_code": bucket["product_code"],
                "product_name": bucket["product_name"],
                "product_type": bucket["product_type"],
                "sales_quantity": float(bucket["sales_quantity"]),
                "sales_amount": float(bucket["sales_amount"]),
                "average_inventory": float(average_inventory),
                "average_inventory_amount": float(average_inventory_amount),
                "ending_inventory": float(ending["quantity"]),
                "ending_inventory_amount": float(ending["amount"]),
                "turnover_rate": round(turnover_rate, 4) if turnover_rate is not None else None,
                "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
                "last_sale_date": (
                    bucket["last_sale_date"].date().isoformat()
                    if hasattr(bucket["last_sale_date"], "date")
                    else bucket["last_sale_date"].isoformat()
                    if bucket["last_sale_date"]
                    else None
                ),
                "status": status,
            }
        )

    def aggregate(rows: list[dict]) -> dict:
        sales_quantity = sum(_decimal(row["sales_quantity"]) for row in rows)
        sales_amount = sum(_decimal(row["sales_amount"]) for row in rows)
        average_inventory = sum(_decimal(row["average_inventory"]) for row in rows)
        ending_inventory = sum(_decimal(row["ending_inventory"]) for row in rows)
        ending_amount = sum(_decimal(row["ending_inventory_amount"]) for row in rows)
        turnover_rate, turnover_days = _turnover_values(
            sales_quantity, average_inventory, period_days
        )
        return {
            "sales_quantity": float(sales_quantity),
            "sales_amount": float(sales_amount),
            "average_inventory": float(average_inventory),
            "ending_inventory": float(ending_inventory),
            "ending_inventory_amount": float(ending_amount),
            "turnover_rate": round(turnover_rate, 4) if turnover_rate is not None else None,
            "turnover_days": round(turnover_days, 1) if turnover_days is not None else None,
        }

    category_summary = []
    for product_type in PRODUCT_TYPES:
        if product_type_filter and product_type not in product_type_filter:
            continue
        category_summary.append(
            {
                "product_type": product_type,
                **aggregate([row for row in product_rows if row["product_type"] == product_type]),
            }
        )

    waterline = []
    for month in months:
        snapshot_date = _month_end(month)
        month_key = month.strftime("%Y-%m")
        row = {"month": month_key, "snapshot_date": snapshot_date.isoformat()}
        for product_type, field in (("正装", "full_size_inventory"), ("小样", "sample_inventory")):
            row[field] = float(
                sum(
                    (
                        bucket["stock_by_date"].get(snapshot_date, {}).get("quantity", Decimal(0))
                        for bucket in products.values()
                        if bucket["product_type"] == product_type
                    ),
                    Decimal(0),
                )
            )
        row["total_inventory"] = row["full_size_inventory"] + row["sample_inventory"]
        row["sales_quantity"] = float(
            sum(
                (bucket["sales_by_month"].get(month_key, Decimal(0)) for bucket in products.values()),
                Decimal(0),
            )
        )
        waterline.append(row)

    slow_products = sorted(
        [row for row in product_rows if row["ending_inventory"] > 0],
        key=lambda row: (
            0 if row["sales_quantity"] <= 0 else 1,
            -(row["turnover_days"] if row["turnover_days"] is not None else 10**9),
            -row["ending_inventory_amount"],
        ),
    )[:ranking_limit]
    hot_products = sorted(
        [row for row in product_rows if row["sales_quantity"] > 0],
        key=lambda row: (-row["sales_quantity"], -row["sales_amount"]),
    )[:ranking_limit]
    detail_rows = sorted(
        product_rows,
        key=lambda row: (-row["ending_inventory_amount"], -row["sales_quantity"]),
    )

    overall = aggregate(product_rows)
    total_channel_quantity = sum(
        (bucket["sales_quantity"] for bucket in channel_sales.values()), Decimal(0)
    )
    total_channel_amount = sum(
        (bucket["sales_amount"] for bucket in channel_sales.values()), Decimal(0)
    )
    channel_mix = [
        {
            "channel_kind": channel_kind,
            "sales_quantity": float(bucket["sales_quantity"]),
            "sales_amount": float(bucket["sales_amount"]),
            "quantity_share": float(
                bucket["sales_quantity"] / total_channel_quantity * Decimal(100)
                if total_channel_quantity
                else Decimal(0)
            ),
            "amount_share": float(
                bucket["sales_amount"] / total_channel_amount * Decimal(100)
                if total_channel_amount
                else Decimal(0)
            ),
            "channel_count": len(bucket["channels"]),
        }
        for channel_kind, bucket in channel_sales.items()
    ]
    completed_updates = [
        row["completed_at"]
        for row in source.get("batches", [])
        if row.get("status") == "SUCCESS" and row.get("completed_at")
    ]

    return {
        "brand": brand,
        "start_date": normalized_start.isoformat(),
        "end_date": normalized_end.isoformat(),
        "period": f"{normalized_start.strftime('%Y年%m月')}—{normalized_end.strftime('%Y年%m月')}",
        "period_days": period_days,
        "summary": overall,
        "category_summary": category_summary,
        "waterline": waterline,
        "channel_mix": channel_mix,
        "channel_turnover": {
            "available": False,
            "reason": "销售渠道与库存仓库没有唯一归属关系；当前仅展示线上、线下销售贡献，不将共享库存重复计算为渠道周转。",
        },
        "slow_products": slow_products,
        "hot_products": hot_products,
        "details": detail_rows,
        "freshness": {
            "snapshot_count": len(valid_snapshots),
            "snapshot_expected": len(expected_snapshots),
            "snapshot_complete": set(expected_snapshots).issubset(completed_dates),
            "snapshot_updated_at": max(completed_updates).isoformat() if completed_updates else None,
            "source_updated_at": max(source_updates).isoformat() if source_updates else None,
        },
        "metric_notes": {
            "average_inventory": "使用期初及所选期间各月末的库存数量计算平均值，某月未出现的商品按0库存计。",
            "turnover": "数量周转次数 = 净销售数量 ÷ 月末平均库存数量；周转天数 = 期间天数 ÷ 周转次数。",
            "ranking": "滞销优先展示有期末库存但无销售的商品，再按周转天数和库存金额排序；热销按净销售数量排序。",
        },
    }
