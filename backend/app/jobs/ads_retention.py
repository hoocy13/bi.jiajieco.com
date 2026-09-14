from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.ads import require_ads_build_session_factory, require_ads_session_factory


SALES_DATASET = "sales_daily"
INVENTORY_DATASET = "inventory_overview"
DEFAULT_KEEP_READY = 2
DEFAULT_CHUNK_ROWS = 20_000
DEFAULT_MAX_VERSIONS = 9
DEFAULT_ACTIVE_BUILD_HOURS = 6

SALES_TABLES = (
    "ads_sales_daily",
    "ads_sales_daily_channel",
    "ads_sales_daily_city_channel",
    "ads_sales_detail_daily",
    "ads_sales_detail_daily_channel",
    "ads_sales_daily_product",
    "ads_sales_detail_daily_scope",
    "ads_sales_daily_brand_scope",
    "ads_sales_daily_brand_product",
    "ads_sales_daily_channel_customer",
    "ads_sales_customer_daily",
    "ads_sales_customer_product_daily",
    "ads_sales_customer_quality_daily",
    "ads_sales_daily_brand_channel_scope",
    "ads_sales_daily_brand_channel_product",
    "ads_sales_order_detail",
    "ads_sales_order_daily_filter",
    "ads_sales_brand_turnover_item",
    "ads_sales_brand_turnover_order",
)

INVENTORY_TABLES = (
    "ads_inventory_product_warehouse",
    "ads_inventory_batch_summary",
    "ads_inventory_batch_item",
    "ads_inventory_filter_option",
    "ads_inventory_health_item",
    "ads_inventory_turnover_item",
    "ads_inventory_arrival_item",
)


@dataclass(frozen=True)
class RetentionPlan:
    cutoff_batch_id: int
    keep_sales: tuple[str, ...]
    keep_inventory: tuple[str, ...]
    prune_sales: tuple[str, ...]
    prune_inventory: tuple[str, ...]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _versions(
    db: Session,
    dataset: str,
    *,
    status: str | None = None,
) -> list[tuple[int, str]]:
    status_sql = "AND `status` = :status" if status else ""
    params: dict[str, object] = {"dataset": dataset}
    if status:
        params["status"] = status
    rows = db.execute(
        text(
            f"""
            SELECT `id`, `data_version`
            FROM `ads_publish_batch`
            WHERE `dataset` = :dataset {status_sql}
            ORDER BY COALESCE(`published_at`, `created_at`) DESC, `id` DESC
            """
        ),
        params,
    ).all()
    return [(int(row[0]), str(row[1])) for row in rows]


def physical_versions(db: Session, tables: tuple[str, ...]) -> tuple[str, ...]:
    versions: set[str] = set()
    for table in tables:
        versions.update(
            str(value)
            for value in db.execute(text(f"SELECT DISTINCT `data_version` FROM `{table}`")).scalars()
            if value is not None
        )
    return tuple(sorted(versions))


def build_plan(db: Session, keep_ready: int = DEFAULT_KEEP_READY) -> RetentionPlan:
    if keep_ready < 2:
        raise ValueError("keep_ready must be at least 2")
    cutoff = int(db.execute(text("SELECT COALESCE(MAX(`id`), 0) FROM `ads_publish_batch`")).scalar() or 0)
    ready_sales = _versions(db, SALES_DATASET, status="ready")
    ready_inventory = _versions(db, INVENTORY_DATASET, status="ready")
    if len(ready_sales) < keep_ready or len(ready_inventory) < keep_ready:
        raise RuntimeError("sales and inventory must each have at least two ready batches")
    keep_sales = tuple(version for _, version in ready_sales[:keep_ready])
    keep_inventory = tuple(version for _, version in ready_inventory[:keep_ready])
    all_sales = dict((version, batch_id) for batch_id, version in _versions(db, SALES_DATASET))
    all_inventory = dict((version, batch_id) for batch_id, version in _versions(db, INVENTORY_DATASET))
    physical_sales = physical_versions(db, SALES_TABLES)
    physical_inventory = physical_versions(db, INVENTORY_TABLES)
    unknown_sales = sorted(set(physical_sales) - set(all_sales))
    unknown_inventory = sorted(set(physical_inventory) - set(all_inventory))
    if unknown_sales or unknown_inventory:
        raise RuntimeError(
            "physical ADS versions are missing publish-batch metadata: "
            f"sales={unknown_sales}; inventory={unknown_inventory}"
        )
    return RetentionPlan(
        cutoff_batch_id=cutoff,
        keep_sales=keep_sales,
        keep_inventory=keep_inventory,
        prune_sales=tuple(
            version for version in physical_sales if all_sales[version] <= cutoff and version not in keep_sales
        ),
        prune_inventory=tuple(
            version for version in physical_inventory if all_inventory[version] <= cutoff and version not in keep_inventory
        ),
    )


def recent_building_count(db: Session, active_build_hours: int) -> int:
    cutoff = utc_now() - timedelta(hours=active_build_hours)
    return int(
        db.execute(
            text("SELECT COUNT(*) FROM `ads_publish_batch` WHERE `status` = 'building' AND `created_at` >= :cutoff"),
            {"cutoff": cutoff},
        ).scalar()
        or 0
    )


def stale_table_names(db: Session) -> tuple[str, ...]:
    rows = db.execute(
        text(
            """
            SELECT `TABLE_NAME`
            FROM information_schema.TABLES
            WHERE `TABLE_SCHEMA` = DATABASE()
              AND (LOCATE('__compact_', `TABLE_NAME`) > 0
                   OR LOCATE('__old_', `TABLE_NAME`) > 0)
            ORDER BY `TABLE_NAME`
            """
        )
    ).scalars()
    return tuple(str(row) for row in rows)


def table_size_gib(db: Session) -> float:
    value = db.execute(
        text(
            """
            SELECT COALESCE(SUM(`DATA_LENGTH` + `INDEX_LENGTH`), 0) / 1024 / 1024 / 1024
            FROM information_schema.TABLES
            WHERE `TABLE_SCHEMA` = DATABASE()
              AND (`TABLE_NAME` LIKE 'ads_sales_%' OR `TABLE_NAME` LIKE 'ads_inventory_%')
            """
        )
    ).scalar()
    return round(float(value or 0), 2)


def health_payload(
    db: Session,
    *,
    disk_use_percent: float | None,
    strict_retention: bool,
    max_versions: int,
    active_build_hours: int,
) -> tuple[dict[str, object], list[str]]:
    plan = build_plan(db)
    failures: list[str] = []
    warnings: list[str] = []
    active = recent_building_count(db, active_build_hours)
    stale = stale_table_names(db)
    sales_physical_versions = physical_versions(db, SALES_TABLES)
    inventory_physical_versions = physical_versions(db, INVENTORY_TABLES)
    if active:
        failures.append(f"recent building batches={active}")
    if stale:
        failures.append(f"stale compact/old tables={len(stale)}")
    if disk_use_percent is not None:
        if disk_use_percent >= 85:
            failures.append(f"disk usage={disk_use_percent:.1f}%")
        elif disk_use_percent >= 70:
            warnings.append(f"disk usage={disk_use_percent:.1f}%")
    if len(sales_physical_versions) > max_versions or len(inventory_physical_versions) > max_versions:
        warnings.append(
            "physical versions exceed operational window: "
            f"sales={len(sales_physical_versions)}, inventory={len(inventory_physical_versions)}"
        )
    mismatches: list[dict[str, object]] = []
    if strict_retention:
        for table, expected in (
            *((table, set(plan.keep_sales)) for table in SALES_TABLES),
            *((table, set(plan.keep_inventory)) for table in INVENTORY_TABLES),
        ):
            actual = {str(row) for row in db.execute(text(f"SELECT DISTINCT `data_version` FROM `{table}`")).scalars()}
            if actual != expected:
                mismatches.append({"table": table, "versions": len(actual)})
        if mismatches:
            failures.append(f"retention mismatches={len(mismatches)}")
    payload: dict[str, object] = {
        "status": "failed" if failures else ("warning" if warnings else "healthy"),
        "disk_use_percent": disk_use_percent,
        "ads_table_size_gib": table_size_gib(db),
        "cutoff_batch_id": plan.cutoff_batch_id,
        "keep_sales": plan.keep_sales,
        "keep_inventory": plan.keep_inventory,
        "sales_physical_versions": sales_physical_versions,
        "inventory_physical_versions": inventory_physical_versions,
        "prune_sales_versions": len(plan.prune_sales),
        "prune_inventory_versions": len(plan.prune_inventory),
        "recent_building_batches": active,
        "stale_tables": stale,
        "strict_mismatches": mismatches,
        "warnings": warnings,
        "failures": failures,
    }
    return payload, failures


def _delete_version(db: Session, table: str, version: str, chunk_rows: int) -> int:
    deleted = 0
    while True:
        result = db.execute(
            text(f"DELETE FROM `{table}` WHERE `data_version` = :version LIMIT {chunk_rows}"),
            {"version": version},
        )
        count = max(int(result.rowcount or 0), 0)
        db.commit()
        deleted += count
        if count < chunk_rows:
            return deleted


def apply_retention(db: Session, plan: RetentionPlan, chunk_rows: int, active_build_hours: int) -> dict[str, object]:
    if chunk_rows < 1_000 or chunk_rows > 200_000:
        raise ValueError("chunk_rows must be between 1000 and 200000")
    if recent_building_count(db, active_build_hours):
        raise RuntimeError("a recent ADS build is still marked building")
    # Planning and the active-build guard issue SELECTs, so SQLAlchemy has
    # already autobegun a transaction. MySQL only permits sql_log_bin changes
    # outside a transaction; close the read-only transaction first.
    db.rollback()
    db.execute(text("SET SESSION sql_log_bin = 0"))
    sql_log_bin = db.execute(text("SELECT @@session.sql_log_bin")).scalar()
    if sql_log_bin is None or int(sql_log_bin) != 0:
        raise RuntimeError("failed to disable binlog for retention session")
    deleted: dict[str, int] = {}
    for tables, versions in (
        (SALES_TABLES, plan.prune_sales),
        (INVENTORY_TABLES, plan.prune_inventory),
    ):
        for table in tables:
            table_deleted = 0
            for version in versions:
                current = int(db.execute(text("SELECT COALESCE(MAX(`id`), 0) FROM `ads_publish_batch`")).scalar() or 0)
                if current != plan.cutoff_batch_id:
                    raise RuntimeError(f"ADS batch changed during retention: {plan.cutoff_batch_id} -> {current}")
                if recent_building_count(db, active_build_hours):
                    raise RuntimeError("a new ADS build started during retention")
                table_deleted += _delete_version(db, table, version, chunk_rows)
            deleted[table] = table_deleted
            print(json.dumps({"event": "table_pruned", "table": table, "rows": table_deleted}), flush=True)
    payload, failures = health_payload(
        db,
        disk_use_percent=None,
        strict_retention=True,
        max_versions=DEFAULT_MAX_VERSIONS,
        active_build_hours=active_build_hours,
    )
    if failures:
        raise RuntimeError("retention verification failed: " + "; ".join(failures))
    return {
        "cutoff_batch_id": plan.cutoff_batch_id,
        "keep_sales": plan.keep_sales,
        "keep_inventory": plan.keep_inventory,
        "deleted_rows": sum(deleted.values()),
        "tables": deleted,
    }


def plan_payload(db: Session, keep_ready: int) -> dict[str, object]:
    plan = build_plan(db, keep_ready)
    return {
        "mode": "dry-run",
        "cutoff_batch_id": plan.cutoff_batch_id,
        "keep_sales": plan.keep_sales,
        "keep_inventory": plan.keep_inventory,
        "prune_sales_versions": len(plan.prune_sales),
        "prune_inventory_versions": len(plan.prune_inventory),
        "sales_tables": len(SALES_TABLES),
        "inventory_tables": len(INVENTORY_TABLES),
        "ads_table_size_gib": table_size_gib(db),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADS ready版本健康检查与历史版本维护")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--health", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--strict-retention", action="store_true")
    parser.add_argument("--keep-ready", type=int, default=DEFAULT_KEEP_READY)
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS)
    parser.add_argument("--max-versions", type=int, default=DEFAULT_MAX_VERSIONS)
    parser.add_argument("--active-build-hours", type=int, default=DEFAULT_ACTIVE_BUILD_HOURS)
    parser.add_argument("--disk-use-percent", type=float)
    return parser.parse_args(list(argv) if argv is not None else None)


def main() -> None:
    args = parse_args()
    factory = require_ads_build_session_factory() if args.apply else require_ads_session_factory()
    with factory() as db:
        if args.health:
            payload, failures = health_payload(
                db,
                disk_use_percent=args.disk_use_percent,
                strict_retention=args.strict_retention,
                max_versions=args.max_versions,
                active_build_hours=args.active_build_hours,
            )
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            if failures:
                raise SystemExit(2)
        elif args.dry_run:
            print(json.dumps(plan_payload(db, args.keep_ready), ensure_ascii=False), flush=True)
        else:
            plan = build_plan(db, args.keep_ready)
            result = apply_retention(db, plan, args.chunk_rows, args.active_build_hours)
            print(json.dumps({"mode": "apply", **result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
