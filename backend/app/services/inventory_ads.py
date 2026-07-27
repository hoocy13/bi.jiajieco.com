from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch


INVENTORY_DATASET = "inventory_overview"


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
