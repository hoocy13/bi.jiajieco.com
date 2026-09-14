from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, pstdev

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sales_ads import (
    AdsDataUnavailable,
    ensure_batch_covers,
    latest_ready_sales_batch,
    number,
)


def _change_rate(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def analyze_sales_workspace(
    daily_rows: list[dict],
    previous_rows: list[dict],
    brand_rows: list[dict],
) -> dict:
    """Turn sales facts into one stable analysis result for callers and tests."""
    total = sum(number(row.get("paid_amount")) for row in daily_rows)
    previous_total = sum(number(row.get("paid_amount")) for row in previous_rows)
    values = [number(row.get("paid_amount")) for row in daily_rows]
    baseline = mean(values) if values else 0
    deviation = pstdev(values) if len(values) > 1 else 0
    anomaly_floor = baseline * 0.25

    anomalies = []
    for row in daily_rows:
        value = number(row.get("paid_amount"))
        delta = value - baseline
        if deviation and abs(delta) >= 2 * deviation and abs(delta) >= anomaly_floor:
            anomalies.append(
                {
                    "date": str(row["sales_date"]),
                    "paid_amount": value,
                    "baseline": baseline,
                    "deviation_rate": delta / baseline * 100 if baseline else None,
                    "direction": "up" if delta > 0 else "down",
                }
            )
    anomalies.sort(key=lambda item: abs(item["deviation_rate"] or 0), reverse=True)

    ranked_brands = sorted(
        (
            {"brand": str(row.get("brand") or "未归类"), "paid_amount": number(row.get("paid_amount"))}
            for row in brand_rows
        ),
        key=lambda item: (-item["paid_amount"], item["brand"]),
    )[:10]
    for index, item in enumerate(ranked_brands, 1):
        item.update(rank=index, share=item["paid_amount"] / total * 100 if total else 0)

    return {
        "summary": {
            "paid_amount": total,
            "previous_paid_amount": previous_total,
            "change_rate": _change_rate(total, previous_total),
            "daily_average": baseline,
            "anomaly_count": len(anomalies),
        },
        "trend": [
            {"date": str(row["sales_date"]), "paid_amount": number(row.get("paid_amount"))}
            for row in daily_rows
        ],
        "brands": ranked_brands,
        "anomalies": anomalies[:8],
    }


def load_sales_workspace(ads_db: Session, period_days: int = 90) -> dict:
    batch = latest_ready_sales_batch(ads_db)
    end_date = batch.source_end_date
    start_date = end_date - timedelta(days=period_days - 1)
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    ensure_batch_covers(batch, previous_start, end_date)
    params = {
        "data_version": batch.data_version,
        "start_date": start_date,
        "end_date": end_date,
        "previous_start": previous_start,
        "previous_end": previous_end,
    }
    daily_rows = ads_db.execute(text("""
        SELECT `sales_date`, `paid_amount` FROM `ads_sales_daily`
        WHERE `data_version` = :data_version AND `sales_date` BETWEEN :start_date AND :end_date
        ORDER BY `sales_date`
    """), params).mappings().all()
    previous_rows = ads_db.execute(text("""
        SELECT `sales_date`, `paid_amount` FROM `ads_sales_daily`
        WHERE `data_version` = :data_version AND `sales_date` BETWEEN :previous_start AND :previous_end
        ORDER BY `sales_date`
    """), params).mappings().all()
    brand_rows = ads_db.execute(text("""
        SELECT `brand`, SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_daily_brand_scope`
        WHERE `data_version` = :data_version
          AND `sales_date` BETWEEN :start_date AND :end_date
          AND `product_type_scope` = 'all'
        GROUP BY `brand`
    """), params).mappings().all()
    result = analyze_sales_workspace(list(daily_rows), list(previous_rows), list(brand_rows))
    return {
        "metric": "paid_amount",
        "method": "trend",
        "dimension": "brand",
        "period": "last_90",
        "period_label": "近90天",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "previous_start_date": previous_start.isoformat(),
        "previous_end_date": previous_end.isoformat(),
        "as_of": end_date.isoformat(),
        **result,
    }

