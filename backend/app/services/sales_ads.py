from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch
from app.services.sales_sources import is_online_sales_channel


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


def date_value(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


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


def load_dashboard_overview_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    city_coords: dict[str, list[float]],
) -> dict:
    as_of = batch.source_end_date
    start_date = as_of - timedelta(days=29)
    trend_start = as_of - timedelta(days=6)
    ensure_batch_covers(batch, start_date, as_of)
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "trend_start": trend_start,
        "end_date": as_of,
    }
    daily_rows = ads_db.execute(
        text(
            """
            SELECT `sales_date`, `orders`, `paid_amount`, `quantity`
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
            SELECT `channel`, SUM(`paid_amount`) AS paid_amount
            FROM `ads_sales_daily_channel`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            GROUP BY `channel`
            ORDER BY paid_amount DESC
            LIMIT 6
            """
        ),
        params,
    ).mappings().all()
    city_channel_rows = ads_db.execute(
        text(
            """
            SELECT `city`, `channel`, SUM(`paid_amount`) AS paid_amount
            FROM `ads_sales_daily_city_channel`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            GROUP BY `city`, `channel`
            ORDER BY paid_amount DESC
            LIMIT 120
            """
        ),
        params,
    ).mappings().all()

    trend_by_day = {
        date_value(row["sales_date"]): {
            "sales": number(row["paid_amount"]),
            "orders": integer(row["orders"]),
        }
        for row in daily_rows
        if date_value(row["sales_date"]) >= trend_start
    }
    paid_amount = sum(number(row["paid_amount"]) for row in daily_rows)
    quantity = sum(number(row["quantity"]) for row in daily_rows)
    city_groups: dict[str, list[dict]] = {}
    for row in city_channel_rows:
        city = str(row["city"]).strip()
        if city not in city_coords:
            continue
        city_groups.setdefault(city, []).append(
            {"name": row["channel"], "value": round(number(row["paid_amount"]), 2)}
        )

    map_pies = []
    for city, segments in city_groups.items():
        positive_segments = [segment for segment in segments if segment["value"] > 0]
        total = sum(segment["value"] for segment in positive_segments)
        if total <= 0:
            continue
        top_segments = sorted(
            positive_segments,
            key=lambda segment: segment["value"],
            reverse=True,
        )[:3]
        other_value = total - sum(segment["value"] for segment in top_segments)
        if other_value > 0:
            top_segments.append({"name": "其他", "value": round(other_value, 2)})
        map_pies.append(
            {
                "name": city,
                "coord": city_coords[city],
                "total": round(total, 2),
                "segments": top_segments,
            }
        )
    map_pies.sort(key=lambda item: item["total"], reverse=True)
    days = [trend_start + timedelta(days=offset) for offset in range(7)]
    return {
        "as_of": as_of.isoformat(),
        "period": "近30天",
        "cards": [
            {
                "label": "近30天销售额",
                "value": f"{paid_amount / 1_000_000:,.2f}",
                "unit": "百万",
                "trend": f"截至 {as_of.isoformat()}",
            },
            {
                "label": "近30天销售",
                "value": f"{quantity / 1_000_000:,.2f}",
                "unit": "百万",
                "trend": "净销售数量",
            },
        ],
        "trend": {
            "days": [day.strftime("%m-%d") for day in days],
            "sales": [trend_by_day.get(day, {"sales": 0})["sales"] for day in days],
            "orders": [trend_by_day.get(day, {"orders": 0})["orders"] for day in days],
        },
        "channels": [
            {"name": row["channel"], "value": round(number(row["paid_amount"]), 2)}
            for row in channel_rows
        ],
        "map_pies": map_pies[:8],
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


def load_sales_channel_analysis_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    dimension_rows: list[dict],
    filter_option_rows: list[dict],
    include_unmatched: bool,
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    fact_rows = ads_db.execute(
        text(
            """
            SELECT
              `sales_date`,
              `channel`,
              `orders`,
              `paid_amount`,
              `quantity`
            FROM `ads_sales_detail_daily_channel`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            ORDER BY `sales_date`, `channel`
            """
        ),
        {
            "data_version": batch.data_version,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).mappings().all()

    selected_channel_names = {str(row["channel_name"]) for row in dimension_rows}
    all_channel_names = {str(row["channel_name"]) for row in filter_option_rows}
    selected_facts = [
        row
        for row in fact_rows
        if (
            str(row["channel"]) in selected_channel_names
            if str(row["channel"]) in all_channel_names
            else include_unmatched
        )
    ]

    trend_by_month: dict[str, dict] = {}
    facts_by_channel: dict[str, dict] = {}
    for row in selected_facts:
        sales_date = row["sales_date"]
        month = (
            f"{sales_date.year:04d}-{sales_date.month:02d}-01"
            if isinstance(sales_date, date)
            else f"{str(sales_date)[:7]}-01"
        )
        channel = str(row["channel"])
        month_item = trend_by_month.setdefault(
            month,
            {"month": month, "orders": 0, "paid_amount": 0.0, "quantity": 0},
        )
        channel_item = facts_by_channel.setdefault(
            channel,
            {"channel": channel, "orders": 0, "paid_amount": 0.0, "quantity": 0},
        )
        for item in (month_item, channel_item):
            item["orders"] += integer(row["orders"])
            item["paid_amount"] += number(row["paid_amount"])
            item["quantity"] += integer(row["quantity"])

    trend = [trend_by_month[key] for key in sorted(trend_by_month)]
    summary = {
        "orders": sum(row["orders"] for row in trend),
        "paid_amount": sum(row["paid_amount"] for row in trend),
        "quantity": sum(row["quantity"] for row in trend),
    }
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
            "is_online": is_online_sales_channel(
                row["category"],
                row["platform"],
                row["channel_name"],
            ),
            "matched": True,
        }
        for row in dimension_rows
        for fact in [facts_by_channel.get(str(row["channel_name"]), {})]
        for orders in [integer(fact.get("orders"))]
        for paid_amount in [number(fact.get("paid_amount"))]
        for quantity in [integer(fact.get("quantity"))]
    ]

    channel_types = sorted({str(row["channel_type"]) for row in filter_option_rows})
    platforms = sorted(
        {
            str(row["platform"])
            for row in filter_option_rows
            if str(row["platform"]) != "未设置"
        }
    )
    unmatched_rows = sorted(
        (
            row
            for name, row in facts_by_channel.items()
            if name not in all_channel_names
        ),
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
            "orders": integer(row["orders"]),
            "paid_amount": paid_amount,
            "quantity": integer(row["quantity"]),
            "share": paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
            "avg_order_amount": paid_amount / integer(row["orders"]) if integer(row["orders"]) else 0,
            "is_online": is_online_sales_channel("未匹配渠道", "未设置", row["channel"]),
            "matched": False,
        }
        for row in unmatched_rows
        for paid_amount in [number(row["paid_amount"])]
    )
    channel_rows.sort(key=lambda row: row["paid_amount"], reverse=True)

    def summarize_channels(field: str, include_unset: bool = True) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in channel_rows:
            key = str(row[field])
            if not include_unset and key == "未设置":
                continue
            item = grouped.setdefault(
                key,
                {
                    field: key,
                    "channels": 0,
                    "active_channels": 0,
                    "orders": 0,
                    "paid_amount": 0.0,
                    "quantity": 0,
                },
            )
            item["channels"] += 1
            item["active_channels"] += 1 if row["orders"] > 0 else 0
            item["orders"] += row["orders"]
            item["paid_amount"] += row["paid_amount"]
            item["quantity"] += row["quantity"]
        return sorted(grouped.values(), key=lambda row: row["paid_amount"], reverse=True)

    type_summary = summarize_channels("channel_type")
    platform_summary = summarize_channels("platform", include_unset=False)[:12]
    return {
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
                "channels": integer(row["channels"]),
                "active_channels": integer(row["active_channels"]),
                "orders": integer(row["orders"]),
                "paid_amount": number(row["paid_amount"]),
                "quantity": integer(row["quantity"]),
                "share": number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in type_summary
        ],
        "platform_summary": [
            {
                "platform": row["platform"],
                "channels": integer(row["channels"]),
                "active_channels": integer(row["active_channels"]),
                "orders": integer(row["orders"]),
                "paid_amount": number(row["paid_amount"]),
                "quantity": integer(row["quantity"]),
                "share": number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in platform_summary
        ],
        "rows": channel_rows,
        "unmatched_channels": [
            {
                "channel": row["channel"],
                "orders": integer(row["orders"]),
                "paid_amount": number(row["paid_amount"]),
                "quantity": integer(row["quantity"]),
                "share": number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in unmatched_rows
        ],
        "filter_options": {
            "channel_types": channel_types,
            "platforms": platforms,
        },
    }


def load_sales_detail_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    page: int,
    page_size: int,
    keyword: str | None,
    channel: str | None,
    status: str | None,
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    params: dict = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
        "end_exclusive": end_date + timedelta(days=1),
    }
    detail_filters = [
        "`data_version` = :data_version",
        "`sales_time` >= :start_date",
        "`sales_time` < :end_exclusive",
    ]
    if keyword and keyword.strip():
        params["keyword"] = f"%{keyword.strip()}%"
        detail_filters.append("(`order_number` LIKE :keyword OR `product` LIKE :keyword)")
    if channel:
        params["channel"] = channel
        detail_filters.append("`channel` = :channel")
    if status:
        params["status"] = status
        detail_filters.append("`status` = :status")
    detail_where_sql = " AND ".join(detail_filters)

    if keyword and keyword.strip():
        summary = ads_db.execute(
            text(
                f"""
                SELECT
                  COUNT(DISTINCT CASE WHEN `quantity` > 0 THEN `order_number` END) AS orders,
                  COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
                  COALESCE(SUM(`quantity`), 0) AS quantity,
                  COUNT(*) AS total
                FROM `ads_sales_order_detail`
                WHERE {detail_where_sql}
                """
            ),
            params,
        ).mappings().one()
    else:
        aggregate_filters = [
            "`data_version` = :data_version",
            "`sales_date` BETWEEN :start_date AND :end_date",
        ]
        if channel:
            aggregate_filters.append("`channel` = :channel")
        if status:
            aggregate_filters.append("`status` = :status")
        aggregate_where_sql = " AND ".join(aggregate_filters)
        filter_summary = ads_db.execute(
            text(
                f"""
                SELECT
                  COALESCE(SUM(`orders`), 0) AS orders,
                  COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
                  COALESCE(SUM(`quantity`), 0) AS quantity,
                  COALESCE(SUM(`detail_rows`), 0) AS total
                FROM `ads_sales_order_daily_filter`
                WHERE {aggregate_where_sql}
                """
            ),
            params,
        ).mappings().one()
        summary = filter_summary
        if status is None:
            exact_table = (
                "ads_sales_daily_channel" if channel else "ads_sales_daily"
            )
            channel_filter = "AND `channel` = :channel" if channel else ""
            exact_summary = ads_db.execute(
                text(
                    f"""
                    SELECT
                      COALESCE(SUM(`orders`), 0) AS orders,
                      COALESCE(SUM(`paid_amount`), 0) AS paid_amount,
                      COALESCE(SUM(`quantity`), 0) AS quantity
                    FROM `{exact_table}`
                    WHERE `data_version` = :data_version
                      AND `sales_date` BETWEEN :start_date AND :end_date
                      {channel_filter}
                    """
                ),
                params,
            ).mappings().one()
            summary = {**dict(filter_summary), **dict(exact_summary)}

    rows = ads_db.execute(
        text(
            f"""
            SELECT
              `sales_date`, `order_number`, `channel`, `status`,
              `settlement_status`, `product`, `quantity`,
              `receivable_amount`, `paid_amount`, `city`
            FROM `ads_sales_order_detail`
            WHERE {detail_where_sql}
            ORDER BY `sales_time` DESC, `order_number` DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return {
        **meta,
        "summary": {
            "paid_amount": number(summary["paid_amount"]),
            "orders": integer(summary["orders"]),
            "quantity": integer(summary["quantity"]),
        },
        "rows": [
            {
                "date": date_text(row["sales_date"]),
                "order_no": row["order_number"],
                "channel": row["channel"],
                "status": row["status"],
                "settlement_status": row["settlement_status"],
                "product": row["product"],
                "quantity": integer(row["quantity"]),
                "receivable_amount": number(row["receivable_amount"]),
                "paid_amount": number(row["paid_amount"]),
                "city": row["city"],
            }
            for row in rows
        ],
        "total": integer(summary["total"]),
        "page": page,
        "page_size": page_size,
    }


def load_sales_channel_customer_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    channel_name: str,
    owner: str,
    keyword: str | None,
    page: int,
    page_size: int,
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    params: dict = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
        "channel": channel_name.strip(),
    }
    customer_filter = ""
    if keyword and keyword.strip():
        params["keyword"] = f"%{keyword.strip()}%"
        customer_filter = (
            "WHERE customer_code LIKE :keyword OR customer_name LIKE :keyword"
        )
    grouped_sql = """
        SELECT
          `customer_code`, `customer_name`,
          SUM(`orders`) AS orders,
          SUM(`quantity`) AS quantity,
          SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_daily_channel_customer`
        WHERE `data_version` = :data_version
          AND `sales_date` BETWEEN :start_date AND :end_date
          AND `channel` = :channel
        GROUP BY `customer_code`, `customer_name`
    """
    summary = ads_db.execute(
        text(
            f"""
            SELECT COUNT(*) AS customers, COALESCE(SUM(orders), 0) AS orders,
                   COALESCE(SUM(quantity), 0) AS quantity,
                   COALESCE(SUM(paid_amount), 0) AS paid_amount
            FROM ({grouped_sql}) customer_sales
            {customer_filter}
            """
        ),
        params,
    ).mappings().one()
    rows = ads_db.execute(
        text(
            f"""
            SELECT * FROM ({grouped_sql}) customer_sales
            {customer_filter}
            ORDER BY paid_amount DESC, quantity DESC, customer_code
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    total_paid = number(summary["paid_amount"])
    return {
        **meta,
        "channel_name": channel_name.strip(),
        "owner": owner or "-",
        "summary": {
            "customers": integer(summary["customers"]),
            "orders": integer(summary["orders"]),
            "quantity": integer(summary["quantity"]),
            "paid_amount": total_paid,
        },
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": integer(summary["customers"]),
        },
        "rows": [
            {
                "customer_code": row["customer_code"],
                "customer_name": row["customer_name"],
                "orders": orders,
                "quantity": integer(row["quantity"]),
                "paid_amount": paid,
                "share": paid / total_paid * 100 if total_paid else 0,
                "avg_order_amount": paid / orders if orders else 0,
            }
            for row in rows
            for orders in [integer(row["orders"])]
            for paid in [number(row["paid_amount"])]
        ],
    }


def load_sales_brand_channel_from_ads(
    ads_db: Session,
    batch: AdsPublishBatch,
    meta: dict,
    brand: str,
    product_types: list[str],
    channel_types: list[str],
    channel_names: list[str],
    dimension_rows: list[dict],
) -> dict:
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    ensure_batch_covers(batch, start_date, end_date)
    scope = product_type_scope(product_types)
    dimensions = {str(row["channel_name"]): row for row in dimension_rows}
    selected_names = {
        name
        for name, row in dimensions.items()
        if (not channel_types or str(row["channel_type"]) in channel_types)
        and (not channel_names or name in channel_names)
    }
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
        "brand": brand.strip(),
        "scope": scope,
    }
    facts = ads_db.execute(
        text(
            """
            SELECT `sales_date`, `channel`, `detail_rows`, `orders`, `quantity`, `paid_amount`
            FROM `ads_sales_daily_brand_channel_scope`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `brand` = :brand
              AND `product_type_scope` = :scope
            """
        ),
        params,
    ).mappings().all()
    selected_facts = [
        row
        for row in facts
        if (
            str(row["channel"]) in selected_names
            if str(row["channel"]) in dimensions
            else not channel_types and not channel_names
        )
    ]
    by_day: dict[str, dict] = {}
    by_channel: dict[str, dict] = {}
    for row in selected_facts:
        day = date_text(row["sales_date"])
        channel = str(row["channel"])
        for target, key in ((by_day, day), (by_channel, channel)):
            item = target.setdefault(
                key,
                {"orders": 0, "quantity": 0, "paid_amount": 0.0, "detail_rows": 0},
            )
            item["orders"] += integer(row["orders"])
            item["quantity"] += integer(row["quantity"])
            item["paid_amount"] += number(row["paid_amount"])
            item["detail_rows"] += integer(row["detail_rows"])

    if not channel_types and not channel_names:
        exact_rows = ads_db.execute(
            text(
                """
                SELECT `sales_date`, `orders`
                FROM `ads_sales_daily_brand_scope`
                WHERE `data_version` = :data_version
                  AND `sales_date` BETWEEN :start_date AND :end_date
                  AND `brand` = :brand
                  AND `product_type_scope` = :scope
                """
            ),
            params,
        ).mappings().all()
        for row in exact_rows:
            day = date_text(row["sales_date"])
            if day in by_day:
                by_day[day]["orders"] = integer(row["orders"])
    paid_amount = sum(item["paid_amount"] for item in by_day.values())
    orders = sum(item["orders"] for item in by_day.values())
    quantity = sum(item["quantity"] for item in by_day.values())

    product_conditions: list[str] = []
    product_params = dict(params)
    if scope == "full_size":
        product_conditions.append("`product_type` = :single_product_type")
        product_params["single_product_type"] = "正装"
    elif scope == "sample":
        product_conditions.append("`product_type` = :single_product_type")
        product_params["single_product_type"] = "小样"
    elif scope == "selected":
        product_conditions.append("`product_type` IN :selected_product_types")
        product_params["selected_product_types"] = ("正装", "小样")
    if channel_types or channel_names:
        product_conditions.append("`channel` IN :selected_channels")
        product_params["selected_channels"] = tuple(selected_names)
    product_filter = "".join(
        f"\n              AND {condition}" for condition in product_conditions
    )
    product_query = text(
        f"""
            SELECT `product`,
                   SUM(`orders`) AS `orders`,
                   SUM(`quantity`) AS `quantity`,
                   SUM(`paid_amount`) AS `paid_amount`
            FROM `ads_sales_daily_brand_channel_product`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `brand` = :brand
              {product_filter}
            GROUP BY `product`
            ORDER BY `paid_amount` DESC
            LIMIT 20
        """
    )
    salesperson_query = text(
        f"""
            SELECT `channel`, `product_type`,
                   SUM(`quantity`) AS `quantity`,
                   SUM(`paid_amount`) AS `paid_amount`
            FROM `ads_sales_daily_brand_channel_product`
            WHERE `data_version` = :data_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `brand` = :brand
              {product_filter}
              AND `product_type` IN :salesperson_product_types
            GROUP BY `channel`, `product_type`
        """
    )
    if "selected_product_types" in product_params:
        product_query = product_query.bindparams(
            bindparam("selected_product_types", expanding=True)
        )
        salesperson_query = salesperson_query.bindparams(
            bindparam("selected_product_types", expanding=True)
        )
    if "selected_channels" in product_params:
        product_query = product_query.bindparams(
            bindparam("selected_channels", expanding=True)
        )
        salesperson_query = salesperson_query.bindparams(
            bindparam("selected_channels", expanding=True)
        )
    product_rows = ads_db.execute(product_query, product_params).mappings().all()
    salesperson_params = {
        **product_params,
        "salesperson_product_types": ("正装", "小样"),
    }
    salesperson_rows_by_channel = ads_db.execute(
        salesperson_query.bindparams(
            bindparam("salesperson_product_types", expanding=True)
        ),
        salesperson_params,
    ).mappings().all()
    salesperson_totals: dict[str, dict] = {}
    for row in salesperson_rows_by_channel:
        channel = str(row["channel"])
        if channel in dimensions:
            owner = str(dimensions[channel]["owner"])
        else:
            owner = "-"
        sales = salesperson_totals.setdefault(
            owner,
            {
                "salesperson": owner,
                "regular_quantity": 0,
                "regular_paid_amount": 0.0,
                "sample_quantity": 0,
                "sample_paid_amount": 0.0,
            },
        )
        prefix = "regular" if row["product_type"] == "正装" else "sample"
        sales[f"{prefix}_quantity"] += integer(row["quantity"])
        sales[f"{prefix}_paid_amount"] += number(row["paid_amount"])

    channel_data = []
    for name in sorted(selected_names):
        row = dimensions[name]
        fact = by_channel.get(
            name, {"orders": 0, "quantity": 0, "paid_amount": 0.0, "detail_rows": 0}
        )
        row_orders = fact["orders"]
        row_quantity = fact["quantity"]
        row_paid = fact["paid_amount"]
        channel_data.append(
            {
                **row,
                "detail_rows": fact["detail_rows"],
                "orders": row_orders,
                "quantity": row_quantity,
                "paid_amount": row_paid,
                "share": row_paid / paid_amount * 100 if paid_amount else 0,
                "avg_order_amount": row_paid / row_orders if row_orders else 0,
                "avg_unit_price": row_paid / row_quantity if row_quantity else 0,
                "is_online": is_online_sales_channel(
                    row["channel_type"], row["platform"], name
                ),
                "matched": True,
            }
        )
    unmatched = [
        {
            "channel": name,
            "orders": fact["orders"],
            "quantity": fact["quantity"],
            "paid_amount": fact["paid_amount"],
        }
        for name, fact in by_channel.items()
        if name not in dimensions
    ]
    for item in unmatched:
        channel_data.append(
            {
                "channel_code": None,
                "channel_name": item["channel"],
                "channel_type": "未匹配渠道",
                "source_channel_type": "未匹配渠道",
                "platform": "未设置",
                "owner": "-",
                "detail_rows": 0,
                **{key: item[key] for key in ("orders", "quantity", "paid_amount")},
                "share": item["paid_amount"] / paid_amount * 100 if paid_amount else 0,
                "avg_order_amount": item["paid_amount"] / item["orders"] if item["orders"] else 0,
                "avg_unit_price": item["paid_amount"] / item["quantity"] if item["quantity"] else 0,
                "is_online": is_online_sales_channel("未匹配渠道", "未设置", item["channel"]),
                "matched": False,
            }
        )
    channel_data.sort(key=lambda row: row["paid_amount"], reverse=True)

    def dimension_summary(key: str, online_only: bool = False) -> list[dict]:
        groups: dict[str, dict] = {}
        candidates = [
            row
            for row in channel_data
            if row["matched"] and (not online_only or row["platform"] != "未设置")
        ]
        for row in candidates:
            label = str(row[key])
            group = groups.setdefault(
                label,
                {"channels": 0, "active_channels": 0, "orders": 0, "quantity": 0, "paid_amount": 0.0},
            )
            group["channels"] += 1
            group["active_channels"] += int(row["orders"] > 0)
            for metric in ("orders", "quantity", "paid_amount"):
                group[metric] += row[metric]
        return sorted(
            [
                {
                    key: label,
                    **group,
                    "share": group["paid_amount"] / paid_amount * 100 if paid_amount else 0,
                    "avg_order_amount": group["paid_amount"] / group["orders"] if group["orders"] else 0,
                }
                for label, group in groups.items()
            ],
            key=lambda row: row["paid_amount"],
            reverse=True,
        )

    online = [row for row in channel_data if row["is_online"]]
    offline = [row for row in channel_data if not row["is_online"]]
    salesperson_rows = []
    for item in salesperson_totals.values():
        item["total_quantity"] = item["regular_quantity"] + item["sample_quantity"]
        item["total_paid_amount"] = item["regular_paid_amount"] + item["sample_paid_amount"]
        salesperson_rows.append(item)
    salesperson_rows.sort(key=lambda row: row["total_paid_amount"], reverse=True)
    return {
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
                "date": day,
                "orders": by_day[day]["orders"],
                "quantity": by_day[day]["quantity"],
                "paid_amount": by_day[day]["paid_amount"],
            }
            for day in sorted(by_day)
        ],
        "channel_types": dimension_summary("channel_type"),
        "platforms": dimension_summary("platform", online_only=True)[:12],
        "channels": channel_data,
        "sales_contribution": {
            "online": {
                "paid_amount": sum(row["paid_amount"] for row in online),
                "quantity": sum(row["quantity"] for row in online),
            },
            "offline": {
                "paid_amount": sum(row["paid_amount"] for row in offline),
                "quantity": sum(row["quantity"] for row in offline),
            },
            "paid_amount_difference": 0,
            "quantity_difference": 0,
        },
        "salesperson_product_types": salesperson_rows,
        "products": [
            {
                "rank": index,
                "product": str(row["product"]),
                "orders": integer(row["orders"]),
                "quantity": integer(row["quantity"]),
                "paid_amount": number(row["paid_amount"]),
                "share": (
                    number(row["paid_amount"]) / paid_amount * 100
                    if paid_amount
                    else 0
                ),
                "avg_unit_price": (
                    number(row["paid_amount"]) / integer(row["quantity"])
                    if integer(row["quantity"])
                    else 0
                ),
            }
            for index, row in enumerate(product_rows, start=1)
        ],
        "unmatched_channels": unmatched,
        "filter_options": {
            "channel_types": sorted({str(row["channel_type"]) for row in dimension_rows}),
            "channel_names": sorted(dimensions),
        },
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
