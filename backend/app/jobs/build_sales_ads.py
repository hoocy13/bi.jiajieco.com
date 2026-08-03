from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.ads import initialize_ads_schema, require_ads_build_session_factory
from app.db.ods import create_ods_engine
from app.models.ads import (
    AdsPublishBatch,
    AdsSalesDaily,
    AdsSalesDailyBrandChannelProduct,
    AdsSalesDailyBrandChannelScope,
    AdsSalesDailyBrandProduct,
    AdsSalesDailyBrandScope,
    AdsSalesDailyChannelCustomer,
    AdsSalesBrandTurnoverItem,
    AdsSalesBrandTurnoverOrder,
    AdsSalesDailyChannel,
    AdsSalesDailyCityChannel,
    AdsSalesDailyProduct,
    AdsSalesDetailDaily,
    AdsSalesDetailDailyChannel,
    AdsSalesDetailDailyScope,
    AdsSalesOrderDetail,
    AdsSalesOrderDailyFilter,
)
from app.services.sales_sources import (
    ACTIVE_SALES_ORDER_SQL,
    BRAND_EXPRESSION_SQL,
    POSITIVE_SALES_ORDER_COUNT_SQL,
    PRODUCT_TYPE_EXPRESSION_SQL,
    SALES_ORDER_TABLE_SQL,
)


DATASET = "sales_daily"
BRAND_TURNOVER_DEFAULT_WAREHOUSES = (
    "上海仓库新",
    "【商家仓】抖超上海仓",
)
PRODUCT_TYPE_SCOPES_SQL = """
    SELECT 'all' AS product_type_scope
    UNION ALL SELECT 'full_size'
    UNION ALL SELECT 'sample'
    UNION ALL SELECT 'selected'
"""


@dataclass(frozen=True)
class SalesSummary:
    orders: int
    paid_amount: Decimal
    quantity: Decimal


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def decimal_value(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def summary_from_mapping(row: dict) -> SalesSummary:
    return SalesSummary(
        orders=int(row.get("orders") or 0),
        paid_amount=decimal_value(row.get("paid_amount")),
        quantity=decimal_value(row.get("quantity")),
    )


def summaries_match(left: SalesSummary, right: SalesSummary) -> bool:
    return (
        left.orders == right.orders
        and left.paid_amount == right.paid_amount
        and left.quantity == right.quantity
    )


def new_data_version(source_end_date: date) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"sales-{source_end_date.isoformat()}-{timestamp}-{uuid4().hex[:8]}"


def resolve_source_range(
    ods_db: Session,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date cannot be later than end_date")
        return start_date, end_date

    row = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(MIN(`下单时间`)) AS start_date,
              DATE(MAX(`下单时间`)) AS end_date
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE {ACTIVE_SALES_ORDER_SQL}
            """
        )
    ).mappings().one()
    source_start = row["start_date"]
    source_end = row["end_date"]
    if source_start is None or source_end is None:
        raise RuntimeError("Sales source contains no active orders")

    resolved_start = start_date or source_start
    resolved_end = end_date or source_end
    if resolved_start > resolved_end:
        raise ValueError("start_date cannot be later than end_date")
    return resolved_start, resolved_end


def load_source_summary(ods_db: Session, start_date: date, end_date: date) -> SalesSummary:
    row = ods_db.execute(
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
        {"start_date": start_date, "end_date": end_date},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_daily_rows(ods_db: Session, start_date: date, end_date: date) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS sales_date,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY DATE(`下单时间`)
            ORDER BY sales_date
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_channel_rows(ods_db: Session, start_date: date, end_date: date) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS sales_date,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY
              DATE(`下单时间`),
              COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY sales_date, channel
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_city_channel_rows(ods_db: Session, start_date: date, end_date: date) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS sales_date,
              COALESCE(NULLIF(`市`, ''), '未填写') AS city,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY
              DATE(`下单时间`),
              COALESCE(NULLIF(`市`, ''), '未填写'),
              COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY sales_date, city, channel
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_detail_source_summary(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> SalesSummary:
    row = ods_db.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_detail_daily_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              DATE(`下单时间`) AS sales_date,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY DATE(`下单时间`)
            ORDER BY sales_date
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_detail_channel_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              DATE(`下单时间`) AS sales_date,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(`下单时间`),
              COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY sales_date, channel
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_product_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              DATE(`下单时间`) AS sales_date,
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(`下单时间`),
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY sales_date, product
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_detail_scope_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(d.`下单时间`) AS sales_date,
              scopes.product_type_scope,
              COUNT(DISTINCT d.`订单编号`) AS orders,
              SUM(COALESCE(d.`数量`, 0)) AS quantity,
              SUM(COALESCE(d.`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全` d
            JOIN ({PRODUCT_TYPE_SCOPES_SQL}) scopes
              ON scopes.product_type_scope = 'all'
              OR (
                scopes.product_type_scope = 'full_size'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} = '正装'
              )
              OR (
                scopes.product_type_scope = 'sample'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} = '小样'
              )
              OR (
                scopes.product_type_scope = 'selected'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} IN ('正装', '小样')
              )
            WHERE d.`下单时间` >= :start_date
              AND d.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY DATE(d.`下单时间`), scopes.product_type_scope
            ORDER BY sales_date, scopes.product_type_scope
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_brand_scope_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(d.`下单时间`) AS sales_date,
              scopes.product_type_scope,
              {BRAND_EXPRESSION_SQL} AS brand,
              COUNT(DISTINCT d.`订单编号`) AS orders,
              SUM(COALESCE(d.`数量`, 0)) AS quantity,
              SUM(COALESCE(d.`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全` d
            JOIN ({PRODUCT_TYPE_SCOPES_SQL}) scopes
              ON scopes.product_type_scope = 'all'
              OR (
                scopes.product_type_scope = 'full_size'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} = '正装'
              )
              OR (
                scopes.product_type_scope = 'sample'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} = '小样'
              )
              OR (
                scopes.product_type_scope = 'selected'
                AND {PRODUCT_TYPE_EXPRESSION_SQL} IN ('正装', '小样')
              )
            WHERE d.`下单时间` >= :start_date
              AND d.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(d.`下单时间`),
              scopes.product_type_scope,
              {BRAND_EXPRESSION_SQL}
            ORDER BY sales_date, scopes.product_type_scope, brand
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_brand_product_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS sales_date,
              {BRAND_EXPRESSION_SQL} AS brand,
              {PRODUCT_TYPE_EXPRESSION_SQL} AS product_type,
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(`下单时间`),
              {BRAND_EXPRESSION_SQL},
              {PRODUCT_TYPE_EXPRESSION_SQL},
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY sales_date, brand, product_type, product
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def month_ranges(start_date: date, end_date: date):
    cursor = start_date
    while cursor <= end_date:
        next_month = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        yield cursor, min(end_date, next_month - timedelta(days=1))
        cursor = next_month


def load_channel_customer_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    result: list[dict] = []
    for slice_start, slice_end in month_ranges(start_date, end_date):
        rows = ods_db.execute(
            text(
                f"""
                SELECT
                  DATE(l.`下单时间`) AS sales_date,
                  COALESCE(NULLIF(l.`销售渠道`, ''), '未归类') AS channel,
                  COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置') AS customer_code,
                  COALESCE(o.customer_name, '未命名客户') AS customer_name,
                  COUNT(DISTINCT l.`订单编号`) AS orders,
                  SUM(COALESCE(l.`数量`, 0)) AS quantity,
                  SUM(COALESCE(l.`分摊后金额`, 0)) AS paid_amount
                FROM `dwd`.`销售单明细账_品牌补全` l
                LEFT JOIN (
                  SELECT
                    `订单编号`,
                    MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
                    MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
                  FROM {SALES_ORDER_TABLE_SQL}
                  WHERE `下单时间` >= :start_date
                    AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
                    AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN (
                      SELECT `渠道名称`
                      FROM `渠道列表`
                      WHERE NULLIF(TRIM(`线上平台`), '') IS NULL
                    )
                  GROUP BY `订单编号`
                ) o ON o.`订单编号` = l.`订单编号`
                WHERE l.`下单时间` >= :start_date
                  AND l.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
                  AND COALESCE(NULLIF(l.`销售渠道`, ''), '未归类') IN (
                    SELECT `渠道名称`
                    FROM `渠道列表`
                    WHERE NULLIF(TRIM(`线上平台`), '') IS NULL
                  )
                GROUP BY
                  DATE(l.`下单时间`),
                  COALESCE(NULLIF(l.`销售渠道`, ''), '未归类'),
                  COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置'),
                  COALESCE(o.customer_name, '未命名客户')
                """
            ),
            {"start_date": slice_start, "end_date": slice_end},
        ).mappings().all()
        result.extend(dict(row) for row in rows)
    return result


def load_offline_customer_source_summary(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> SalesSummary:
    row = ods_db.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN (
                SELECT `渠道名称`
                FROM `渠道列表`
                WHERE NULLIF(TRIM(`线上平台`), '') IS NULL
              )
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_brand_channel_scope_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(d.`下单时间`) AS sales_date,
              {BRAND_EXPRESSION_SQL} AS brand,
              COALESCE(NULLIF(d.`销售渠道`, ''), '未归类') AS channel,
              scopes.product_type_scope,
              COUNT(*) AS detail_rows,
              COUNT(DISTINCT d.`订单编号`) AS orders,
              SUM(COALESCE(d.`数量`, 0)) AS quantity,
              SUM(COALESCE(d.`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全` d
            JOIN ({PRODUCT_TYPE_SCOPES_SQL}) scopes
              ON scopes.product_type_scope = 'all'
              OR (scopes.product_type_scope = 'full_size' AND {PRODUCT_TYPE_EXPRESSION_SQL} = '正装')
              OR (scopes.product_type_scope = 'sample' AND {PRODUCT_TYPE_EXPRESSION_SQL} = '小样')
              OR (scopes.product_type_scope = 'selected' AND {PRODUCT_TYPE_EXPRESSION_SQL} IN ('正装', '小样'))
            WHERE d.`下单时间` >= :start_date
              AND d.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(d.`下单时间`),
              {BRAND_EXPRESSION_SQL},
              COALESCE(NULLIF(d.`销售渠道`, ''), '未归类'),
              scopes.product_type_scope
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def load_brand_channel_product_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = ods_db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS sales_date,
              {BRAND_EXPRESSION_SQL} AS brand,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              {PRODUCT_TYPE_EXPRESSION_SQL} AS product_type,
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(`下单时间`),
              {BRAND_EXPRESSION_SQL},
              COALESCE(NULLIF(`销售渠道`, ''), '未归类'),
              {PRODUCT_TYPE_EXPRESSION_SQL},
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(row) for row in rows]


def insert_order_detail_rows_streaming(
    ods_db: Session,
    ads_db: Session,
    data_version: str,
    start_date: date,
    end_date: date,
    chunk_size: int = 5000,
) -> int:
    result = ods_db.execute(
        text(
            f"""
            SELECT
              `下单时间` AS sales_time,
              `订单编号` AS order_number,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              COALESCE(NULLIF(`订单状态`, ''), '未知') AS status,
              COALESCE(NULLIF(`结算状态`, ''), '未知') AS settlement_status,
              COALESCE(NULLIF(`货品摘要`, ''), '未命名商品') AS product,
              COALESCE(`货品数量`, 0) AS quantity,
              COALESCE(`应收合计`, 0) AS receivable_amount,
              COALESCE(`实付金额`, 0) AS paid_amount,
              COALESCE(NULLIF(`市`, ''), '-') AS city
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            ORDER BY `下单时间`, `订单编号`
            """
        ),
        {"start_date": start_date, "end_date": end_date},
        execution_options={"stream_results": True},
    ).mappings()
    item_id = 0
    while True:
        chunk = result.fetchmany(chunk_size)
        if not chunk:
            break
        payload = []
        for row in chunk:
            item_id += 1
            sales_time = row["sales_time"]
            payload.append(
                {
                    "data_version": data_version,
                    "item_id": item_id,
                    "sales_date": sales_time.date(),
                    "sales_time": sales_time,
                    "order_number": str(row["order_number"] or ""),
                    "channel": str(row["channel"]),
                    "status": str(row["status"]),
                    "settlement_status": str(row["settlement_status"]),
                    "product": str(row["product"]),
                    "quantity": decimal_value(row["quantity"]),
                    "receivable_amount": decimal_value(row["receivable_amount"]),
                    "paid_amount": decimal_value(row["paid_amount"]),
                    "city": str(row["city"]),
                }
            )
        ads_db.execute(insert(AdsSalesOrderDetail), payload)
        if item_id % 50000 == 0:
            ads_db.commit()
    ads_db.commit()
    return item_id


def ads_can_read_sales_source_directly() -> bool:
    if not settings.ADS_BUILD_DATABASE_URL:
        return False
    ods_url = make_url(settings.ODS_DATABASE_URL)
    ads_url = make_url(settings.ADS_BUILD_DATABASE_URL)
    return (
        ods_url.get_backend_name() == "mysql"
        and ads_url.get_backend_name() == "mysql"
        and ods_url.host == ads_url.host
        and (ods_url.port or 3306) == (ads_url.port or 3306)
    )


def insert_order_detail_rows_server_side(
    ads_db: Session,
    data_version: str,
    start_date: date,
    end_date: date,
) -> int:
    item_offset = 0
    for slice_start, slice_end in month_ranges(start_date, end_date):
        result = ads_db.execute(
            text(
                f"""
                INSERT INTO `ads_sales_order_detail` (
                  `data_version`, `item_id`, `sales_date`, `sales_time`,
                  `order_number`, `channel`, `status`, `settlement_status`,
                  `product`, `quantity`, `receivable_amount`, `paid_amount`, `city`
                )
                SELECT
                  :data_version,
                  :item_offset + ROW_NUMBER() OVER (
                    ORDER BY `下单时间`, `订单编号`
                  ) AS item_id,
                  DATE(`下单时间`) AS sales_date,
                  `下单时间` AS sales_time,
                  COALESCE(`订单编号`, '') AS order_number,
                  COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
                  COALESCE(NULLIF(`订单状态`, ''), '未知') AS status,
                  COALESCE(NULLIF(`结算状态`, ''), '未知') AS settlement_status,
                  COALESCE(NULLIF(`货品摘要`, ''), '未命名商品') AS product,
                  COALESCE(`货品数量`, 0) AS quantity,
                  COALESCE(`应收合计`, 0) AS receivable_amount,
                  COALESCE(`实付金额`, 0) AS paid_amount,
                  COALESCE(NULLIF(`市`, ''), '-') AS city
                FROM {SALES_ORDER_TABLE_SQL}
                WHERE `下单时间` >= :start_date
                  AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
                  AND {ACTIVE_SALES_ORDER_SQL}
                """
            ),
            {
                "data_version": data_version,
                "item_offset": item_offset,
                "start_date": slice_start,
                "end_date": slice_end,
            },
        )
        inserted = int(result.rowcount or 0)
        if inserted < 0:
            inserted = int(
                ads_db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM `ads_sales_order_detail`
                        WHERE `data_version` = :data_version
                        """
                    ),
                    {"data_version": data_version},
                ).scalar()
                or 0
            ) - item_offset
        item_offset += inserted
        ads_db.commit()
    return item_offset


def insert_order_detail_rows(
    ods_db: Session,
    ads_db: Session,
    data_version: str,
    start_date: date,
    end_date: date,
) -> int:
    if ads_can_read_sales_source_directly():
        return insert_order_detail_rows_server_side(
            ads_db,
            data_version,
            start_date,
            end_date,
        )
    return insert_order_detail_rows_streaming(
        ods_db,
        ads_db,
        data_version,
        start_date,
        end_date,
    )


def insert_order_daily_filter_rows(
    ads_db: Session,
    data_version: str,
) -> int:
    result = ads_db.execute(
        text(
            """
            INSERT INTO `ads_sales_order_daily_filter` (
              `data_version`, `sales_date`, `channel`, `status`,
              `detail_rows`, `orders`, `paid_amount`, `quantity`
            )
            SELECT
              `data_version`, `sales_date`, `channel`, `status`,
              COUNT(*) AS detail_rows,
              COUNT(DISTINCT CASE WHEN `quantity` > 0 THEN `order_number` END) AS orders,
              SUM(`paid_amount`) AS paid_amount,
              SUM(`quantity`) AS quantity
            FROM `ads_sales_order_detail`
            WHERE `data_version` = :data_version
            GROUP BY `data_version`, `sales_date`, `channel`, `status`
            """
        ),
        {"data_version": data_version},
    )
    row_count = int(result.rowcount or 0)
    ads_db.commit()
    return row_count


def load_brand_turnover_product_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = []
    cursor = start_date
    while cursor <= end_date:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        slice_end = min(end_date, next_month - timedelta(days=1))
        slice_rows = ods_db.execute(
            text(
            """
            SELECT
              DATE(d.`下单时间`) AS sales_date,
              COALESCE(NULLIF(TRIM(d.`发货仓库`), ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              CONCAT(
                COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类'),
                '|',
                COALESCE(
                  NULLIF(TRIM(d.`货品编号`), ''),
                  CONCAT(
                    'NAME:',
                    COALESCE(NULLIF(TRIM(d.`货品名称`), ''), '未命名商品')
                  )
                )
              ) AS product_key,
              MAX(d.`货品编号`) AS product_code,
              MAX(d.`货品名称`) AS product,
              SUM(COALESCE(d.`数量`, 0)) AS quantity,
              SUM(COALESCE(d.`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全` d
            WHERE d.`下单时间` >= :start_date
              AND d.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            GROUP BY
              DATE(d.`下单时间`),
              COALESCE(NULLIF(TRIM(d.`发货仓库`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类'),
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类'),
              CONCAT(
                COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类'),
                '|',
                COALESCE(
                  NULLIF(TRIM(d.`货品编号`), ''),
                  CONCAT(
                    'NAME:',
                    COALESCE(NULLIF(TRIM(d.`货品名称`), ''), '未命名商品')
                  )
                )
              )
            """
            ),
            {"start_date": cursor, "end_date": slice_end},
        ).mappings().all()
        rows.extend(dict(row) for row in slice_rows)
        cursor = next_month
    return rows


def load_brand_turnover_order_rows(
    ods_db: Session,
    start_date: date,
    end_date: date,
) -> list[dict]:
    rows = []
    scope_specs = (
        ("__all__", "", ""),
        (
            "__default__",
            "AND COALESCE(NULLIF(TRIM(d.`发货仓库`), ''), '未归类') "
            "IN (:default_warehouse_0, :default_warehouse_1)",
            "",
        ),
        (
            None,
            "",
            ", COALESCE(NULLIF(TRIM(d.`发货仓库`), ''), '未归类')",
        ),
    )
    for warehouse_scope, warehouse_filter, warehouse_group in scope_specs:
        warehouse_expression = (
            "COALESCE(NULLIF(TRIM(d.`发货仓库`), ''), '未归类')"
            if warehouse_scope is None
            else f"'{warehouse_scope}'"
        )
        slice_rows = ods_db.execute(
            text(
            f"""
            SELECT
              DATE(d.`下单时间`) AS sales_date,
              NULL AS order_number,
              {warehouse_expression} AS warehouse,
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类') AS brand,
              scopes.product_type_scope AS product_type,
              COUNT(DISTINCT d.`订单编号`) AS orders
            FROM `dwd`.`销售单明细账_品牌补全` d
            JOIN ({PRODUCT_TYPE_SCOPES_SQL}) scopes
              ON scopes.product_type_scope = 'all'
              OR (
                scopes.product_type_scope = 'full_size'
                AND COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') = '正装'
              )
              OR (
                scopes.product_type_scope = 'sample'
                AND COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') = '小样'
              )
              OR (
                scopes.product_type_scope = 'selected'
                AND COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')
                    IN ('正装', '小样')
              )
            WHERE d.`下单时间` >= :start_date
              AND d.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              {warehouse_filter}
            GROUP BY
              DATE(d.`下单时间`),
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类'),
              scopes.product_type_scope
              {warehouse_group}
            """
            ),
            {
                "start_date": start_date,
                "end_date": end_date,
                "default_warehouse_0": BRAND_TURNOVER_DEFAULT_WAREHOUSES[0],
                "default_warehouse_1": BRAND_TURNOVER_DEFAULT_WAREHOUSES[1],
            },
        ).mappings().all()
        rows.extend(dict(row) for row in slice_rows)
    return rows


def brand_turnover_summary(
    product_rows: list[dict],
    order_rows: list[dict],
) -> SalesSummary:
    return SalesSummary(
        orders=sum(
            int(row["orders"] or 0)
            for row in order_rows
            if row["warehouse"] == "__all__"
            and row["product_type"] == "all"
        ),
        paid_amount=sum(
            (decimal_value(row["paid_amount"]) for row in product_rows),
            start=Decimal(0),
        ),
        quantity=sum(
            (decimal_value(row["quantity"]) for row in product_rows),
            start=Decimal(0),
        ),
    )


def load_ads_summary(ads_db: Session, data_version: str) -> SalesSummary:
    row = ads_db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(`orders`), 0) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `ads_sales_daily`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_ads_brand_turnover_summary(
    ads_db: Session,
    data_version: str,
) -> SalesSummary:
    row = ads_db.execute(
        text(
            """
            SELECT
              (
                SELECT COALESCE(SUM(o.`orders`), 0)
                FROM `ads_sales_brand_turnover_order` o
                WHERE o.`data_version` = :data_version
                  AND o.`warehouse` = '__all__'
                  AND o.`product_type` = 'all'
              ) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `ads_sales_brand_turnover_item`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_ads_channel_summary(ads_db: Session, data_version: str) -> SalesSummary:
    row = ads_db.execute(
        text(
            """
            SELECT
              0 AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `ads_sales_daily_channel`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_ads_table_summary(
    ads_db: Session,
    table_name: str,
    data_version: str,
) -> SalesSummary:
    if table_name not in {
        "ads_sales_detail_daily",
        "ads_sales_daily_product",
        "ads_sales_detail_daily_channel",
        "ads_sales_daily_city_channel",
        "ads_sales_daily_channel_customer",
        "ads_sales_daily_brand_channel_product",
        "ads_sales_order_daily_filter",
    }:
        raise ValueError("Unsupported ADS summary table")
    row = ads_db.execute(
        text(
            f"""
            SELECT
              COALESCE(SUM(`orders`), 0) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `{table_name}`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def load_ads_brand_summary(
    ads_db: Session,
    table_name: str,
    data_version: str,
) -> SalesSummary:
    if table_name == "ads_sales_detail_daily_scope":
        scope_filter = "AND `product_type_scope` = 'all'"
    elif table_name == "ads_sales_daily_brand_scope":
        scope_filter = "AND `product_type_scope` = 'all'"
    elif table_name == "ads_sales_daily_brand_product":
        scope_filter = ""
    elif table_name == "ads_sales_daily_brand_channel_scope":
        scope_filter = "AND `product_type_scope` = 'all'"
    else:
        raise ValueError("Unsupported brand ADS summary table")
    row = ads_db.execute(
        text(
            f"""
            SELECT
              COALESCE(SUM(`orders`), 0) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `{table_name}`
            WHERE `data_version` = :data_version
              {scope_filter}
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return summary_from_mapping(dict(row))


def reconciliation_payload(
    source: SalesSummary,
    daily: SalesSummary,
    channel: SalesSummary,
    detail_source: SalesSummary | None = None,
    detail_daily: SalesSummary | None = None,
    product: SalesSummary | None = None,
) -> dict:
    daily_matches = summaries_match(source, daily)
    channel_matches = (
        source.paid_amount == channel.paid_amount
        and source.quantity == channel.quantity
    )
    payload = {
        "passed": daily_matches and channel_matches,
        "daily_matches": daily_matches,
        "channel_amount_quantity_matches": channel_matches,
        "source": {
            "orders": source.orders,
            "paid_amount": str(source.paid_amount),
            "quantity": str(source.quantity),
        },
        "daily": {
            "orders": daily.orders,
            "paid_amount": str(daily.paid_amount),
            "quantity": str(daily.quantity),
        },
        "channel": {
            "paid_amount": str(channel.paid_amount),
            "quantity": str(channel.quantity),
        },
    }
    if detail_source is None or detail_daily is None or product is None:
        return payload

    detail_daily_matches = summaries_match(detail_source, detail_daily)
    product_amount_quantity_matches = (
        detail_source.paid_amount == product.paid_amount
        and detail_source.quantity == product.quantity
    )
    payload["passed"] = (
        payload["passed"]
        and detail_daily_matches
        and product_amount_quantity_matches
    )
    payload["product_rank"] = {
        "detail_daily_matches": detail_daily_matches,
        "product_amount_quantity_matches": product_amount_quantity_matches,
        "source": {
            "orders": detail_source.orders,
            "paid_amount": str(detail_source.paid_amount),
            "quantity": str(detail_source.quantity),
        },
        "detail_daily": {
            "orders": detail_daily.orders,
            "paid_amount": str(detail_daily.paid_amount),
            "quantity": str(detail_daily.quantity),
        },
        "product": {
            "paid_amount": str(product.paid_amount),
            "quantity": str(product.quantity),
        },
    }
    return payload


def build_sales_ads(
    start_date: date | None = None,
    end_date: date | None = None,
    data_version: str | None = None,
) -> dict:
    if not settings.ODS_DATABASE_URL:
        raise RuntimeError("ODS_DATABASE_URL is not configured")

    initialize_ads_schema()
    ads_session_factory = require_ads_build_session_factory()
    ods_build_engine = create_ods_engine(
        settings.ODS_DATABASE_URL,
        read_timeout=settings.ODS_BUILD_READ_TIMEOUT_SECONDS,
    )
    ods_db = Session(bind=ods_build_engine)

    try:
        resolved_start, resolved_end = resolve_source_range(ods_db, start_date, end_date)
        version = data_version or new_data_version(resolved_end)

        with ads_session_factory() as ads_db:
            batch = AdsPublishBatch(
                data_version=version,
                dataset=DATASET,
                status="building",
                source_start_date=resolved_start,
                source_end_date=resolved_end,
                created_at=utc_now(),
            )
            ads_db.add(batch)
            ads_db.commit()
            batch_id = batch.id

            try:
                source_summary = load_source_summary(ods_db, resolved_start, resolved_end)
                daily_rows = load_daily_rows(ods_db, resolved_start, resolved_end)
                channel_rows = load_channel_rows(ods_db, resolved_start, resolved_end)
                city_channel_rows = load_city_channel_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                detail_source_summary = load_detail_source_summary(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                detail_daily_rows = load_detail_daily_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                detail_channel_rows = load_detail_channel_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                product_rows = load_product_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                detail_scope_rows = load_detail_scope_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_scope_rows = load_brand_scope_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_product_rows = load_brand_product_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                channel_customer_rows = load_channel_customer_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                offline_customer_source_summary = load_offline_customer_source_summary(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_channel_scope_rows = load_brand_channel_scope_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_channel_product_rows = load_brand_channel_product_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_turnover_product_rows = load_brand_turnover_product_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )
                brand_turnover_order_rows = load_brand_turnover_order_rows(
                    ods_db,
                    resolved_start,
                    resolved_end,
                )

                if (
                    not daily_rows
                    or not detail_daily_rows
                    or not city_channel_rows
                    or not detail_channel_rows
                    or not product_rows
                    or not detail_scope_rows
                    or not brand_scope_rows
                    or not brand_product_rows
                    or not channel_customer_rows
                    or not brand_channel_scope_rows
                    or not brand_channel_product_rows
                    or not brand_turnover_product_rows
                    or not brand_turnover_order_rows
                ):
                    raise RuntimeError("No sales rows found for the requested range")

                ads_db.execute(
                    insert(AdsSalesDaily),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in daily_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyChannel),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "channel": str(row["channel"] or "未归类"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in channel_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyCityChannel),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "city": str(row["city"] or "未填写"),
                            "channel": str(row["channel"] or "未归类"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in city_channel_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDetailDaily),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in detail_daily_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDetailDailyChannel),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "channel": str(row["channel"] or "未归类"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in detail_channel_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyProduct),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "product": str(row["product"] or "未命名商品"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in product_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDetailDailyScope),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "product_type_scope": str(row["product_type_scope"]),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in detail_scope_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyBrandScope),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "product_type_scope": str(row["product_type_scope"]),
                            "brand": str(row["brand"] or "未识别品牌"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in brand_scope_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyBrandProduct),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "brand": str(row["brand"] or "未识别品牌"),
                            "product_type": str(row["product_type"] or "未分类"),
                            "product": str(row["product"] or "未命名商品"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in brand_product_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyChannelCustomer),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "channel": str(row["channel"]),
                            "customer_code": str(row["customer_code"]),
                            "customer_name": str(row["customer_name"]),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in channel_customer_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyBrandChannelScope),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "brand": str(row["brand"] or "未识别品牌"),
                            "channel": str(row["channel"] or "未归类"),
                            "product_type_scope": str(row["product_type_scope"]),
                            "detail_rows": int(row["detail_rows"] or 0),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in brand_channel_scope_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesDailyBrandChannelProduct),
                    [
                        {
                            "data_version": version,
                            "sales_date": row["sales_date"],
                            "brand": str(row["brand"] or "未识别品牌"),
                            "channel": str(row["channel"] or "未归类"),
                            "product_type": str(row["product_type"] or "未分类"),
                            "product": str(row["product"] or "未命名商品"),
                            "orders": int(row["orders"] or 0),
                            "paid_amount": decimal_value(row["paid_amount"]),
                            "quantity": decimal_value(row["quantity"]),
                        }
                        for row in brand_channel_product_rows
                    ],
                )
                order_detail_row_count = insert_order_detail_rows(
                    ods_db,
                    ads_db,
                    version,
                    resolved_start,
                    resolved_end,
                )
                order_daily_filter_row_count = insert_order_daily_filter_rows(
                    ads_db,
                    version,
                )
                ads_db.execute(
                    insert(AdsSalesBrandTurnoverItem),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "sales_date": row["sales_date"],
                            "order_number": None,
                            "warehouse": str(row["warehouse"]),
                            "brand": str(row["brand"]),
                            "product_type": str(row["product_type"]),
                            "product_key": str(row["product_key"]),
                            "product_code": row["product_code"],
                            "product": row["product"],
                            "quantity": decimal_value(row["quantity"]),
                            "paid_amount": decimal_value(row["paid_amount"]),
                        }
                        for index, row in enumerate(
                            brand_turnover_product_rows,
                            start=1,
                        )
                    ],
                )
                ads_db.execute(
                    insert(AdsSalesBrandTurnoverOrder),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "sales_date": row["sales_date"],
                            "order_number": row["order_number"],
                            "warehouse": str(row["warehouse"]),
                            "brand": str(row["brand"]),
                            "product_type": str(row["product_type"]),
                            "orders": int(row["orders"] or 0),
                        }
                        for index, row in enumerate(
                            brand_turnover_order_rows,
                            start=1,
                        )
                    ],
                )

                daily_summary = load_ads_summary(ads_db, version)
                channel_summary = load_ads_channel_summary(ads_db, version)
                detail_daily_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_detail_daily",
                    version,
                )
                product_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_daily_product",
                    version,
                )
                reconciliation = reconciliation_payload(
                    source_summary,
                    daily_summary,
                    channel_summary,
                    detail_source_summary,
                    detail_daily_summary,
                    product_summary,
                )
                detail_scope_summary = load_ads_brand_summary(
                    ads_db,
                    "ads_sales_detail_daily_scope",
                    version,
                )
                brand_scope_summary = load_ads_brand_summary(
                    ads_db,
                    "ads_sales_daily_brand_scope",
                    version,
                )
                brand_product_summary = load_ads_brand_summary(
                    ads_db,
                    "ads_sales_daily_brand_product",
                    version,
                )
                source_brand_turnover_summary = brand_turnover_summary(
                    brand_turnover_product_rows,
                    brand_turnover_order_rows,
                )
                ads_brand_turnover_summary = load_ads_brand_turnover_summary(
                    ads_db,
                    version,
                )
                brand_turnover_matches = summaries_match(
                    source_brand_turnover_summary,
                    ads_brand_turnover_summary,
                )
                detail_channel_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_detail_daily_channel",
                    version,
                )
                city_channel_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_daily_city_channel",
                    version,
                )
                detail_scope_matches = summaries_match(
                    detail_source_summary,
                    detail_scope_summary,
                )
                brand_scope_amount_quantity_matches = (
                    detail_source_summary.paid_amount == brand_scope_summary.paid_amount
                    and detail_source_summary.quantity == brand_scope_summary.quantity
                )
                brand_product_amount_quantity_matches = (
                    detail_source_summary.paid_amount == brand_product_summary.paid_amount
                    and detail_source_summary.quantity == brand_product_summary.quantity
                )
                detail_channel_amount_quantity_matches = (
                    detail_source_summary.paid_amount == detail_channel_summary.paid_amount
                    and detail_source_summary.quantity == detail_channel_summary.quantity
                )
                city_channel_amount_quantity_matches = (
                    source_summary.paid_amount == city_channel_summary.paid_amount
                    and source_summary.quantity == city_channel_summary.quantity
                )
                customer_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_daily_channel_customer",
                    version,
                )
                brand_channel_scope_summary = load_ads_brand_summary(
                    ads_db,
                    "ads_sales_daily_brand_channel_scope",
                    version,
                )
                brand_channel_product_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_daily_brand_channel_product",
                    version,
                )
                order_detail_row = ads_db.execute(
                    text(
                        """
                        SELECT
                          COUNT(DISTINCT CASE WHEN `quantity` > 0 THEN `order_number` END) AS orders,
                          COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
                          COALESCE(SUM(`quantity`), 0) AS quantity
                        FROM `ads_sales_order_detail`
                        WHERE `data_version` = :data_version
                        """
                    ),
                    {"data_version": version},
                ).mappings().one()
                order_detail_summary = summary_from_mapping(dict(order_detail_row))
                order_detail_matches = summaries_match(source_summary, order_detail_summary)
                order_filter_summary = load_ads_table_summary(
                    ads_db,
                    "ads_sales_order_daily_filter",
                    version,
                )
                order_filter_row_total = int(
                    ads_db.execute(
                        text(
                            """
                            SELECT COALESCE(SUM(`detail_rows`), 0)
                            FROM `ads_sales_order_daily_filter`
                            WHERE `data_version` = :data_version
                            """
                        ),
                        {"data_version": version},
                    ).scalar()
                    or 0
                )
                order_filter_matches = (
                    source_summary.paid_amount == order_filter_summary.paid_amount
                    and source_summary.quantity == order_filter_summary.quantity
                    and order_detail_row_count == order_filter_row_total
                )
                customer_amount_quantity_matches = summaries_match(
                    offline_customer_source_summary,
                    customer_summary,
                )
                brand_channel_scope_matches = (
                    detail_source_summary.paid_amount
                    == brand_channel_scope_summary.paid_amount
                    and detail_source_summary.quantity
                    == brand_channel_scope_summary.quantity
                )
                brand_channel_product_amount_quantity_matches = (
                    detail_source_summary.paid_amount
                    == brand_channel_product_summary.paid_amount
                    and detail_source_summary.quantity
                    == brand_channel_product_summary.quantity
                )
                reconciliation["brand_analysis"] = {
                    "detail_scope_matches": detail_scope_matches,
                    "brand_scope_amount_quantity_matches": brand_scope_amount_quantity_matches,
                    "brand_product_amount_quantity_matches": brand_product_amount_quantity_matches,
                }
                reconciliation["brand_turnover"] = {
                    "matches": brand_turnover_matches,
                    "scope_mode": "compact_v1",
                    "source": {
                        "orders": source_brand_turnover_summary.orders,
                        "paid_amount": str(
                            source_brand_turnover_summary.paid_amount
                        ),
                        "quantity": str(source_brand_turnover_summary.quantity),
                    },
                    "ads": {
                        "orders": ads_brand_turnover_summary.orders,
                        "paid_amount": str(ads_brand_turnover_summary.paid_amount),
                        "quantity": str(ads_brand_turnover_summary.quantity),
                    },
                }
                reconciliation["channel_analysis"] = {
                    "detail_channel_amount_quantity_matches": detail_channel_amount_quantity_matches,
                }
                reconciliation["dashboard"] = {
                    "city_channel_amount_quantity_matches": city_channel_amount_quantity_matches,
                }
                reconciliation["remaining_slow_endpoints"] = {
                    "order_detail_matches": order_detail_matches,
                    "order_filter_matches": order_filter_matches,
                    "customer_amount_quantity_matches": customer_amount_quantity_matches,
                    "brand_channel_scope_matches": brand_channel_scope_matches,
                    "brand_channel_product_amount_quantity_matches": brand_channel_product_amount_quantity_matches,
                }
                reconciliation["passed"] = (
                    reconciliation["passed"]
                    and detail_scope_matches
                    and brand_scope_amount_quantity_matches
                    and brand_product_amount_quantity_matches
                    and brand_turnover_matches
                    and detail_channel_amount_quantity_matches
                    and city_channel_amount_quantity_matches
                    and order_detail_matches
                    and order_filter_matches
                    and customer_amount_quantity_matches
                    and brand_channel_scope_matches
                    and brand_channel_product_amount_quantity_matches
                )
                if not reconciliation["passed"]:
                    raise RuntimeError("ADS reconciliation failed")

                finished_at = utc_now()
                batch = ads_db.get(AdsPublishBatch, batch_id)
                if batch is None:
                    raise RuntimeError("ADS publish batch disappeared during build")
                batch.status = "ready"
                batch.daily_row_count = len(daily_rows)
                batch.channel_row_count = len(channel_rows)
                batch.reconciliation = reconciliation
                batch.finished_at = finished_at
                batch.published_at = finished_at
                ads_db.commit()
                return {
                    "data_version": version,
                    "status": "ready",
                    "source_start_date": resolved_start.isoformat(),
                    "source_end_date": resolved_end.isoformat(),
                    "daily_row_count": len(daily_rows),
                    "channel_row_count": len(channel_rows),
                    "city_channel_row_count": len(city_channel_rows),
                    "detail_daily_row_count": len(detail_daily_rows),
                    "detail_channel_row_count": len(detail_channel_rows),
                    "product_row_count": len(product_rows),
                    "detail_scope_row_count": len(detail_scope_rows),
                    "brand_scope_row_count": len(brand_scope_rows),
                    "brand_product_row_count": len(brand_product_rows),
                    "order_detail_row_count": order_detail_row_count,
                    "order_daily_filter_row_count": order_daily_filter_row_count,
                    "channel_customer_row_count": len(channel_customer_rows),
                    "brand_channel_scope_row_count": len(brand_channel_scope_rows),
                    "brand_channel_product_row_count": len(brand_channel_product_rows),
                    "brand_turnover_product_row_count": len(
                        brand_turnover_product_rows
                    ),
                    "brand_turnover_order_row_count": len(
                        brand_turnover_order_rows
                    ),
                    "reconciliation": reconciliation,
                }
            except Exception as exc:
                ads_db.rollback()
                failed_batch = ads_db.get(AdsPublishBatch, batch_id)
                if failed_batch is not None:
                    failed_batch.status = "failed"
                    failed_batch.error_code = type(exc).__name__
                    failed_batch.finished_at = utc_now()
                    ads_db.commit()
                raise
    finally:
        ods_db.close()
        ods_build_engine.dispose()


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build versioned sales ADS summary tables")
    parser.add_argument("--start-date", help="Inclusive source start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", help="Inclusive source end date in YYYY-MM-DD format")
    parser.add_argument("--data-version", help="Optional caller-provided immutable data version")
    parser.add_argument(
        "--initialize-only",
        action="store_true",
        help="Create ADS tables without reading ODS or publishing data",
    )
    args = parser.parse_args()

    if args.initialize_only:
        initialize_ads_schema()
        print("ADS schema initialized")
        return

    result = build_sales_ads(
        start_date=parse_date(args.start_date),
        end_date=parse_date(args.end_date),
        data_version=args.data_version,
    )
    print(
        "sales ADS published "
        f"version={result['data_version']} "
        f"range={result['source_start_date']}..{result['source_end_date']} "
        f"daily_rows={result['daily_row_count']} "
        f"channel_rows={result['channel_row_count']} "
        f"detail_daily_rows={result['detail_daily_row_count']} "
        f"detail_channel_rows={result['detail_channel_row_count']} "
        f"product_rows={result['product_row_count']} "
        f"detail_scope_rows={result['detail_scope_row_count']} "
        f"brand_scope_rows={result['brand_scope_row_count']} "
        f"brand_product_rows={result['brand_product_row_count']} "
        f"order_detail_rows={result['order_detail_row_count']} "
        f"order_daily_filter_rows={result['order_daily_filter_row_count']} "
        f"channel_customer_rows={result['channel_customer_row_count']} "
        f"brand_channel_scope_rows={result['brand_channel_scope_row_count']} "
        f"brand_channel_product_rows={result['brand_channel_product_row_count']} "
        f"brand_turnover_product_rows={result['brand_turnover_product_row_count']} "
        f"brand_turnover_order_rows={result['brand_turnover_order_row_count']}"
    )


if __name__ == "__main__":
    main()
