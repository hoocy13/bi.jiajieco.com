from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import monotonic
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.ods import create_ods_engine
from app.db.sales_profit import (
    initialize_sales_profit_schema,
    require_sales_profit_build_session_factory,
)
from app.models.ads import AdsPublishBatch, AdsSalesProfitDaily
from app.services.sales_sources import (
    ACTIVE_SALES_ORDER_SQL,
    BRAND_EXPRESSION_SQL,
    PRODUCT_TYPE_EXPRESSION_SQL,
    SALES_DETAIL_TABLE_SQL,
)


DATASET = "sales_profit"
MAX_SOURCE_DAYS = 93
SOURCE_CHUNK_DAYS = 7
INSERT_BATCH_ROWS = 1000
DECIMAL_FIELDS = (
    "quantity", "paid_amount", "sale_quantity", "sale_amount",
    "return_quantity", "return_amount",
)
SUMMARY_FIELDS = (*DECIMAL_FIELDS, "source_rows")
# Only customer metadata uses raw headers; the materialized warehouse-patched
# header has no order-date index, and its warehouse patch does not affect these fields.
SALES_CUSTOMER_ORDER_TABLE_SQL = "`ods`.`销售单查询`"

SOURCE_BOUNDS_SQL = f"""
    SELECT `下单时间` AS max_sales_time
    FROM {SALES_DETAIL_TABLE_SQL}
    WHERE `下单时间` IS NOT NULL
    ORDER BY `下单时间` DESC
    LIMIT 1
"""

SOURCE_SUMMARY_SQL = f"""
    SELECT COUNT(*) AS source_rows,
           SUM(COALESCE(`数量`, 0)) AS quantity,
           SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount,
           SUM(CASE WHEN COALESCE(`数量`, 0) > 0 AND COALESCE(`分摊后金额`, 0) >= 0
                    THEN COALESCE(`数量`, 0) ELSE 0 END) AS sale_quantity,
           SUM(CASE WHEN COALESCE(`数量`, 0) > 0 AND COALESCE(`分摊后金额`, 0) >= 0
                    THEN COALESCE(`分摊后金额`, 0) ELSE 0 END) AS sale_amount,
           SUM(CASE WHEN COALESCE(`数量`, 0) < 0 THEN -`数量` ELSE 0 END) AS return_quantity,
           SUM(CASE WHEN COALESCE(`分摊后金额`, 0) < 0 THEN -`分摊后金额` ELSE 0 END) AS return_amount,
           MAX(`updatetime`) AS source_max_updated_at,
           MAX(DATE(`下单时间`)) AS max_sales_date
    FROM {SALES_DETAIL_TABLE_SQL}
    WHERE `下单时间` >= :start_date AND `下单时间` < :end_exclusive
"""

# Deduplicate order headers before joining, so a repeated order cannot multiply revenue.
SOURCE_GROUP_SQL = f"""
    SELECT DATE(l.`下单时间`) AS sales_date,
           ({BRAND_EXPRESSION_SQL}) AS brand,
           COALESCE(NULLIF(TRIM(l.`销售渠道`), ''), '未归类') AS channel,
           COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '') AS customer_code,
           COALESCE(MAX(CASE
               WHEN NULLIF(TRIM(l.`客户编号`), '') IS NULL
                 OR TRIM(l.`客户编号`) = o.customer_code
               THEN o.customer_name END), '') AS customer_name,
           COALESCE(NULLIF(TRIM(l.`货品编号`), ''), '') AS product_code,
           COALESCE(MAX(NULLIF(TRIM(l.`货品名称`), '')), '未命名货品') AS product_name,
           ({PRODUCT_TYPE_EXPRESSION_SQL}) AS product_type,
           SUM(COALESCE(l.`数量`, 0)) AS quantity,
           SUM(COALESCE(l.`分摊后金额`, 0)) AS paid_amount,
           SUM(CASE WHEN COALESCE(l.`数量`, 0) > 0 AND COALESCE(l.`分摊后金额`, 0) >= 0
                    THEN COALESCE(l.`数量`, 0) ELSE 0 END) AS sale_quantity,
           SUM(CASE WHEN COALESCE(l.`数量`, 0) > 0 AND COALESCE(l.`分摊后金额`, 0) >= 0
                    THEN COALESCE(l.`分摊后金额`, 0) ELSE 0 END) AS sale_amount,
           SUM(CASE WHEN COALESCE(l.`数量`, 0) < 0 THEN -l.`数量` ELSE 0 END) AS return_quantity,
           SUM(CASE WHEN COALESCE(l.`分摊后金额`, 0) < 0 THEN -l.`分摊后金额` ELSE 0 END) AS return_amount,
           COUNT(*) AS source_rows
    FROM {SALES_DETAIL_TABLE_SQL} l
    LEFT JOIN (
        SELECT `订单编号`,
               MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
               MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
        FROM {SALES_CUSTOMER_ORDER_TABLE_SQL}
        WHERE `下单时间` >= :start_date AND `下单时间` < :end_exclusive
          AND {ACTIVE_SALES_ORDER_SQL}
        GROUP BY `订单编号`
    ) o ON o.`订单编号` = l.`订单编号`
    WHERE l.`下单时间` >= :start_date AND l.`下单时间` < :end_exclusive
    GROUP BY sales_date, brand, channel,
             COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, ''),
             product_code, product_type
"""


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def decimal_value(value: object) -> Decimal:
    return Decimal(0) if value is None else Decimal(str(value))


def resolve_source_range(
    latest_date: date,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[date, date]:
    resolved_end = end_date or latest_date
    resolved_start = start_date or resolved_end - timedelta(days=MAX_SOURCE_DAYS - 1)
    if resolved_end > latest_date:
        raise ValueError("End date exceeds the latest sales source date")
    if resolved_start > resolved_end:
        raise ValueError("Start date must not follow end date")
    if (resolved_end - resolved_start).days + 1 > MAX_SOURCE_DAYS:
        raise ValueError(f"Sales-profit builds are limited to {MAX_SOURCE_DAYS} days")
    return resolved_start, resolved_end


def normalize_summary(mapping: dict) -> dict:
    result = {field: decimal_value(mapping.get(field)) for field in DECIMAL_FIELDS}
    result["source_rows"] = int(mapping.get("source_rows") or 0)
    return result


def source_chunks(start_date: date, end_date: date) -> Iterable[dict]:
    cursor = start_date
    final_exclusive = end_date + timedelta(days=1)
    while cursor < final_exclusive:
        chunk_end = min(cursor + timedelta(days=SOURCE_CHUNK_DAYS), final_exclusive)
        yield {"start_date": cursor, "end_exclusive": chunk_end}
        cursor = chunk_end


def load_source_summary(ods_db: Session, start_date: date, end_date: date) -> dict:
    summary = normalize_summary({})
    summary["source_max_updated_at"] = None
    summary["max_sales_date"] = None
    for params in source_chunks(start_date, end_date):
        row = dict(ods_db.execute(text(SOURCE_SUMMARY_SQL), params).mappings().one())
        for field in DECIMAL_FIELDS:
            summary[field] += decimal_value(row.get(field))
        summary["source_rows"] += int(row.get("source_rows") or 0)
        for field in ("source_max_updated_at", "max_sales_date"):
            value = row.get(field)
            if value is not None and (summary[field] is None or value > summary[field]):
                summary[field] = value
    return summary


def iter_source_profit_rows(ods_db: Session, start_date: date, end_date: date) -> Iterable[dict]:
    for params in source_chunks(start_date, end_date):
        print(f"[sales-profit-ads] stage=source-chunk start={params['start_date']} end_exclusive={params['end_exclusive']}", flush=True)
        result = ods_db.execute(text(SOURCE_GROUP_SQL).execution_options(
            stream_results=True, yield_per=INSERT_BATCH_ROWS,
        ), params)
        try:
            yield from result.mappings()
        finally:
            result.close()


def reconciliation_payload(source: dict, grouped: dict, persisted: dict) -> dict:
    def comparable(summary: dict) -> dict:
        return {
            field: (int(summary[field]) if field == "source_rows" else str(summary[field]))
            for field in SUMMARY_FIELDS
        }

    source = normalize_summary(source)
    grouped = normalize_summary(grouped)
    persisted = normalize_summary(persisted)
    mismatches = [
        field for field in SUMMARY_FIELDS
        if source[field] != grouped[field] or source[field] != persisted[field]
    ]
    return {
        "passed": not mismatches,
        "mismatches": mismatches,
        "source": comparable(source),
        "grouped": comparable(grouped),
        "ads": comparable(persisted),
    }


def load_persisted_summary(ads_db: Session, version: str) -> dict:
    if ads_db.get_bind().dialect.name == "sqlite":
        summary = normalize_summary({})
        fields = [getattr(AdsSalesProfitDaily, field) for field in SUMMARY_FIELDS]
        rows = ads_db.execute(select(*fields).where(
            AdsSalesProfitDaily.data_version == version,
        ).execution_options(yield_per=INSERT_BATCH_ROWS)).mappings()
        for row in rows:
            for field in DECIMAL_FIELDS:
                summary[field] += row[field]
            summary["source_rows"] += row["source_rows"]
        return summary
    fields = [func.sum(getattr(AdsSalesProfitDaily, field)).label(field) for field in SUMMARY_FIELDS]
    return dict(ads_db.execute(select(*fields).where(
        AdsSalesProfitDaily.data_version == version,
    )).mappings().one())


def publish_profit_rows(
    ads_db: Session,
    rows: Iterable[dict],
    source_summary: dict,
    start_date: date,
    end_date: date,
    *,
    data_version: str | None = None,
) -> dict:
    version = data_version or f"profit-{end_date.isoformat()}-{uuid4().hex[:20]}"
    if len(version) > 64 or not version:
        raise ValueError("Data version must contain between 1 and 64 characters")
    if ads_db.execute(select(AdsPublishBatch.id).where(
        AdsPublishBatch.data_version == version,
    )).first() is not None:
        raise ValueError("Data version is immutable and already exists")
    batch = AdsPublishBatch(
        data_version=version,
        dataset=DATASET,
        status="building",
        source_start_date=start_date,
        source_end_date=end_date,
        created_at=utc_now(),
    )
    ads_db.add(batch)
    ads_db.commit()
    batch_id = batch.id
    started = monotonic()
    grouped = normalize_summary({})
    row_count = 0
    pending: list[dict] = []
    try:
        for raw in rows:
            row = dict(raw)
            row_count += 1
            for field in DECIMAL_FIELDS:
                row[field] = decimal_value(row.get(field))
                grouped[field] += row[field]
            row["source_rows"] = int(row.get("source_rows") or 0)
            grouped["source_rows"] += row["source_rows"]
            row["data_version"] = version
            row["item_id"] = row_count
            for field in ("customer_code", "customer_name", "product_code"):
                row[field] = str(row.get(field) or "")
            pending.append(row)
            if len(pending) >= INSERT_BATCH_ROWS:
                ads_db.execute(insert(AdsSalesProfitDaily), pending)
                ads_db.commit()
                pending.clear()
        if pending:
            ads_db.execute(insert(AdsSalesProfitDaily), pending)
            ads_db.commit()
        persisted = load_persisted_summary(ads_db, version)
        reconciliation = reconciliation_payload(source_summary, grouped, persisted)
        for key in ("source_max_updated_at", "max_sales_date"):
            value = source_summary.get(key)
            reconciliation[key] = value.isoformat() if hasattr(value, "isoformat") else value
        reconciliation["scope"] = "bounded_93_days"
        reconciliation["grain"] = "date_brand_channel_customer_product_type"
        batch = ads_db.get(AdsPublishBatch, batch_id)
        if batch is None:
            raise RuntimeError("Sales-profit batch disappeared")
        batch.reconciliation = reconciliation
        if not reconciliation["passed"]:
            raise RuntimeError("Sales-profit source reconciliation failed")
        finished = utc_now()
        batch.status = "ready"
        batch.daily_row_count = row_count
        batch.finished_at = finished
        batch.published_at = finished
        ads_db.commit()
        print(f"[sales-profit-ads] stage=ready rows={row_count} elapsed={monotonic() - started:.1f}s", flush=True)
        return {
            "data_version": version,
            "status": "ready",
            "source_start_date": start_date.isoformat(),
            "source_end_date": end_date.isoformat(),
            "daily_row_count": row_count,
            "reconciliation": reconciliation,
        }
    except Exception as exc:
        ads_db.rollback()
        failed = ads_db.get(AdsPublishBatch, batch_id)
        if failed is not None:
            if "reconciliation" in locals():
                failed.reconciliation = reconciliation
            failed.status = "failed"
            failed.error_code = type(exc).__name__
            failed.finished_at = utc_now()
            ads_db.commit()
        raise


def prune_old_profit_versions(ads_db: Session, keep_ready: int = 2) -> dict[str, int]:
    if keep_ready < 2:
        raise ValueError("Keep at least two ready sales-profit versions")
    batches = ads_db.execute(select(AdsPublishBatch).where(
        AdsPublishBatch.dataset == DATASET,
        AdsPublishBatch.status == "ready",
    ).order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc())).scalars().all()
    removed: dict[str, int] = {}
    for batch in batches[keep_ready:]:
        count = 0
        while True:
            ids = list(ads_db.execute(select(AdsSalesProfitDaily.item_id).where(
                AdsSalesProfitDaily.data_version == batch.data_version,
            ).order_by(AdsSalesProfitDaily.item_id).limit(INSERT_BATCH_ROWS)).scalars())
            if not ids:
                break
            result = ads_db.execute(delete(AdsSalesProfitDaily).where(
                AdsSalesProfitDaily.data_version == batch.data_version,
                AdsSalesProfitDaily.item_id.in_(ids),
            ))
            count += max(int(result.rowcount or 0), 0)
            ads_db.commit()
        batch.status = "retired"
        ads_db.commit()
        removed[batch.data_version] = count
    return removed


def build_sales_profit_ads(
    start_date: date | None = None,
    end_date: date | None = None,
    data_version: str | None = None,
) -> dict:
    if not settings.ODS_DATABASE_URL:
        raise RuntimeError("ODS_DATABASE_URL is not configured")
    initialize_sales_profit_schema()
    ods_engine = create_ods_engine(settings.ODS_DATABASE_URL, settings.ODS_BUILD_READ_TIMEOUT_SECONDS)
    factory = require_sales_profit_build_session_factory()
    try:
        with Session(ods_engine.execution_options(isolation_level="REPEATABLE READ")) as ods_db:
            ods_db.execute(text("SET TRANSACTION READ ONLY"))
            latest = ods_db.execute(text(SOURCE_BOUNDS_SQL)).scalar_one_or_none()
            if latest is None:
                raise RuntimeError("Sales source has no dated records")
            latest_date = latest.date() if isinstance(latest, datetime) else date.fromisoformat(str(latest)[:10])
            resolved_start, resolved_end = resolve_source_range(latest_date, start_date, end_date)
            print(f"[sales-profit-ads] stage=source-summary range={resolved_start}..{resolved_end}", flush=True)
            summary = load_source_summary(ods_db, resolved_start, resolved_end)
            print("[sales-profit-ads] stage=source-grouped", flush=True)
            rows = iter_source_profit_rows(ods_db, resolved_start, resolved_end)
            with factory() as ads_db:
                return publish_profit_rows(
                    ads_db, rows, summary, resolved_start, resolved_end,
                    data_version=data_version,
                )
    finally:
        ods_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the isolated 93-day sales-profit ADS dataset")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--data-version")
    parser.add_argument("--initialize-only", action="store_true")
    parser.add_argument("--prune", action="store_true", help="After publishing, retire only this dataset's older ready versions; retain two")
    args = parser.parse_args()
    if args.initialize_only:
        initialize_sales_profit_schema()
        print("Sales-profit ADS schema initialized")
        return
    result = build_sales_profit_ads(args.start_date, args.end_date, args.data_version)
    if args.prune:
        with require_sales_profit_build_session_factory()() as ads_db:
            removed = prune_old_profit_versions(ads_db)
        print(f"[sales-profit-ads] stage=pruned versions={len(removed)}", flush=True)
    print(f"Sales-profit ADS published version={result['data_version']} rows={result['daily_row_count']}")


if __name__ == "__main__":
    main()
