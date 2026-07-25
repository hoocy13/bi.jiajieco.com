from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch


SALES_DATASET = "sales_daily"


class AdsDataUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SalesOverviewDifference:
    path: str
    reason: str


def number(value: object) -> float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def integer(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def date_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def latest_ready_sales_batch(ads_db: Session) -> AdsPublishBatch:
    batch = ads_db.scalars(
        select(AdsPublishBatch)
        .where(
            AdsPublishBatch.dataset == SALES_DATASET,
            AdsPublishBatch.status == "ready",
        )
        .order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc())
        .limit(1)
    ).first()
    if batch is None:
        raise AdsDataUnavailable("No ready sales ADS batch is available")
    return batch


def ensure_batch_covers(
    batch: AdsPublishBatch,
    start_date: date,
    end_date: date,
) -> None:
    if start_date < batch.source_start_date or end_date > batch.source_end_date:
        raise AdsDataUnavailable("Latest sales ADS batch does not cover the requested date range")


def load_sales_overview_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
    }

    daily_rows = ads_db.execute(
        text(
            """
            SELECT
              `sales_date`,
              `orders`,
              `paid_amount`,
              `quantity`
            FROM `ads_sales_daily`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            ORDER BY `sales_date`
            """
        ),
        params,
    ).mappings().all()
    channel_rows = ads_db.execute(
        text(
            """
            SELECT
              `channel`,
              SUM(`orders`) AS orders,
              SUM(`paid_amount`) AS paid_amount,
              SUM(`quantity`) AS quantity
            FROM `ads_sales_daily_channel`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            GROUP BY `channel`
            ORDER BY paid_amount DESC
            LIMIT 10
            """
        ),
        params,
    ).mappings().all()

    paid_amount = sum((number(row["paid_amount"]) for row in daily_rows), 0.0)
    orders = sum((integer(row["orders"]) for row in daily_rows), 0)
    quantity = sum((integer(row["quantity"]) for row in daily_rows), 0)

    return {
        **meta,
        "metrics": {
            "paid_amount": paid_amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": paid_amount / orders if orders else 0,
        },
        "trend": [
            {
                "date": date_text(row["sales_date"]),
                "orders": integer(row["orders"]),
                "paid_amount": number(row["paid_amount"]),
                "quantity": integer(row["quantity"]),
            }
            for row in daily_rows
        ],
        "channels": [
            {
                "channel": row["channel"],
                "orders": channel_orders,
                "paid_amount": channel_paid_amount,
                "quantity": channel_quantity,
                "share": channel_paid_amount / paid_amount * 100 if paid_amount else 0,
                "avg_order_amount": channel_paid_amount / channel_orders if channel_orders else 0,
            }
            for row in channel_rows
            for channel_orders in [integer(row["orders"])]
            for channel_paid_amount in [number(row["paid_amount"])]
            for channel_quantity in [integer(row["quantity"])]
        ],
    }


def load_sales_product_rank_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    limit: int,
    keyword: str | None = None,
    exact_filtered_orders: int | None = None,
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
    }

    sales_summary_row = ads_db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(`orders`), 0) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `ads_sales_daily`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            """
        ),
        params,
    ).mappings().one()

    product_filter = ""
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        product_filter = "AND `product` LIKE :keyword"

    product_rows = ads_db.execute(
        text(
            f"""
            SELECT
              `product`,
              SUM(`orders`) AS orders,
              SUM(`paid_amount`) AS paid_amount,
              SUM(`quantity`) AS quantity
            FROM `ads_sales_daily_product`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              {product_filter}
            GROUP BY `product`
            """
        ),
        params,
    ).mappings().all()

    if keyword:
        detail_orders = (
            exact_filtered_orders
            if exact_filtered_orders is not None
            else sum((integer(row["orders"]) for row in product_rows), 0)
        )
    else:
        detail_orders = integer(
            ads_db.execute(
                text(
                    """
                    SELECT COALESCE(SUM(`orders`), 0)
                    FROM `ads_sales_detail_daily`
                    WHERE `data_version` = :data_version
                      AND `sales_date` BETWEEN :start_date AND :end_date
                    """
                ),
                params,
            ).scalar()
        )

    rank_paid_amount = sum((number(row["paid_amount"]) for row in product_rows), 0.0)
    rank_quantity = sum((integer(row["quantity"]) for row in product_rows), 0)
    amount_rows = sorted(
        product_rows,
        key=lambda row: (-number(row["paid_amount"]), str(row["product"])),
    )[:limit]
    quantity_rows = sorted(
        product_rows,
        key=lambda row: (
            -integer(row["quantity"]),
            -number(row["paid_amount"]),
            str(row["product"]),
        ),
    )[:limit]

    summary_paid_amount = number(sales_summary_row["paid_amount"])
    summary_orders = integer(sales_summary_row["orders"])
    summary_quantity = integer(sales_summary_row["quantity"])

    def rank_payload(rows: list, share_total: float | int) -> list[dict]:
        return [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": paid_amount,
                "share": paid_amount / share_total * 100 if share_total else 0,
                "avg_unit_price": paid_amount / quantity if quantity else 0,
            }
            for index, row in enumerate(rows)
            for orders in [integer(row["orders"])]
            for quantity in [integer(row["quantity"])]
            for paid_amount in [number(row["paid_amount"])]
        ]

    amount_payload = rank_payload(amount_rows, rank_paid_amount)
    quantity_payload = rank_payload(quantity_rows, rank_quantity)
    for row, source in zip(quantity_payload, quantity_rows, strict=True):
        quantity = integer(source["quantity"])
        row["share"] = quantity / rank_quantity * 100 if rank_quantity else 0

    return {
        **meta,
        "summary": {
            "paid_amount": summary_paid_amount,
            "orders": summary_orders,
            "quantity": summary_quantity,
        },
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": detail_orders,
            "quantity": rank_quantity,
        },
        "rows": amount_payload,
        "quantity_rows": quantity_payload,
    }


def product_type_scope(product_types: list[str]) -> str:
    selected = set(product_types)
    if selected == {"正装"}:
        return "full_size"
    if selected == {"小样"}:
        return "sample"
    if selected == {"正装", "小样"}:
        return "selected"
    return "all"


def load_sales_brand_analysis_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    limit: int,
    product_types: list[str],
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    scope = product_type_scope(product_types)
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
        "product_type_scope": scope,
    }

    detail_summary_row = ads_db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(`orders`), 0) AS orders,
              COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
              COALESCE(SUM(`quantity`), 0) AS quantity
            FROM `ads_sales_detail_daily_scope`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `product_type_scope` = :product_type_scope
            """
        ),
        params,
    ).mappings().one()

    if product_types:
        summary_row = detail_summary_row
    else:
        summary_row = ads_db.execute(
            text(
                """
                SELECT
                  COALESCE(SUM(`orders`), 0) AS orders,
                  COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
                  COALESCE(SUM(`quantity`), 0) AS quantity
                FROM `ads_sales_daily`
                WHERE `data_version` = :data_version
                  AND `sales_date` BETWEEN :start_date AND :end_date
                """
            ),
            params,
        ).mappings().one()

    brand_rows = ads_db.execute(
        text(
            """
            SELECT
              `brand`,
              SUM(`orders`) AS orders,
              SUM(`paid_amount`) AS paid_amount,
              SUM(`quantity`) AS quantity
            FROM `ads_sales_daily_brand_scope`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `product_type_scope` = :product_type_scope
            GROUP BY `brand`
            """
        ),
        params,
    ).mappings().all()

    product_type_filter = ""
    if scope == "full_size":
        product_type_filter = "AND `product_type` = '正装'"
    elif scope == "sample":
        product_type_filter = "AND `product_type` = '小样'"
    elif scope == "selected":
        product_type_filter = "AND `product_type` IN ('正装', '小样')"
    product_count_rows = ads_db.execute(
        text(
            f"""
            SELECT
              `brand`,
              COUNT(DISTINCT `product`) AS product_count
            FROM `ads_sales_daily_brand_product`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              {product_type_filter}
            GROUP BY `brand`
            """
        ),
        params,
    ).mappings().all()
    product_counts = {
        str(row["brand"]): integer(row["product_count"])
        for row in product_count_rows
    }

    rank_paid_amount = number(detail_summary_row["paid_amount"])
    ranked_rows = sorted(
        brand_rows,
        key=lambda row: (-number(row["paid_amount"]), str(row["brand"])),
    )[:limit]
    return {
        **meta,
        "summary": {
            "paid_amount": number(summary_row["paid_amount"]),
            "orders": integer(summary_row["orders"]),
            "quantity": integer(summary_row["quantity"]),
        },
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": integer(detail_summary_row["orders"]),
            "quantity": integer(detail_summary_row["quantity"]),
        },
        "rows": [
            {
                "rank": index + 1,
                "brand": row["brand"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": paid_amount,
                "share": paid_amount / rank_paid_amount * 100 if rank_paid_amount else 0,
                "product_count": product_counts.get(str(row["brand"]), 0),
                "avg_unit_price": paid_amount / quantity if quantity else 0,
            }
            for index, row in enumerate(ranked_rows)
            for orders in [integer(row["orders"])]
            for quantity in [integer(row["quantity"])]
            for paid_amount in [number(row["paid_amount"])]
        ],
    }


def _numbers_equal(left: object, right: object, tolerance: float = 0.01) -> bool:
    return abs(number(left) - number(right)) <= tolerance


def compare_sales_overviews(ods_data: dict, ads_data: dict) -> list[SalesOverviewDifference]:
    differences: list[SalesOverviewDifference] = []

    for field in ("as_of", "start_date", "end_date", "range"):
        if ods_data.get(field) != ads_data.get(field):
            differences.append(SalesOverviewDifference(path=field, reason="value_mismatch"))

    for field in ("orders", "quantity"):
        if integer(ods_data["metrics"].get(field)) != integer(ads_data["metrics"].get(field)):
            differences.append(SalesOverviewDifference(path=f"metrics.{field}", reason="value_mismatch"))
    if not _numbers_equal(
        ods_data["metrics"].get("paid_amount"),
        ads_data["metrics"].get("paid_amount"),
    ):
        differences.append(SalesOverviewDifference(path="metrics.paid_amount", reason="value_mismatch"))

    ods_trend = {row["date"]: row for row in ods_data.get("trend", [])}
    ads_trend = {row["date"]: row for row in ads_data.get("trend", [])}
    if set(ods_trend) != set(ads_trend):
        differences.append(SalesOverviewDifference(path="trend.dates", reason="keys_mismatch"))
    for day in sorted(set(ods_trend) & set(ads_trend)):
        for field in ("orders", "quantity"):
            if integer(ods_trend[day].get(field)) != integer(ads_trend[day].get(field)):
                differences.append(
                    SalesOverviewDifference(path=f"trend.{day}.{field}", reason="value_mismatch")
                )
        if not _numbers_equal(
            ods_trend[day].get("paid_amount"),
            ads_trend[day].get("paid_amount"),
        ):
            differences.append(
                SalesOverviewDifference(path=f"trend.{day}.paid_amount", reason="value_mismatch")
            )

    ods_channels = {str(row["channel"]): row for row in ods_data.get("channels", [])}
    ads_channels = {str(row["channel"]): row for row in ads_data.get("channels", [])}
    if set(ods_channels) != set(ads_channels):
        differences.append(SalesOverviewDifference(path="channels.names", reason="keys_mismatch"))
    for channel in sorted(set(ods_channels) & set(ads_channels)):
        for field in ("orders", "quantity"):
            if integer(ods_channels[channel].get(field)) != integer(ads_channels[channel].get(field)):
                differences.append(
                    SalesOverviewDifference(
                        path=f"channels.{field}",
                        reason="value_mismatch",
                    )
                )
        if not _numbers_equal(
            ods_channels[channel].get("paid_amount"),
            ads_channels[channel].get("paid_amount"),
        ):
            differences.append(
                SalesOverviewDifference(
                    path="channels.paid_amount",
                    reason="value_mismatch",
                )
            )

    return differences
