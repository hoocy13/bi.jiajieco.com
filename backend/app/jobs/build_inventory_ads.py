from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.ads import initialize_ads_schema, require_ads_build_session_factory
from app.db.ods import create_ods_engine
from app.models.ads import (
    AdsInventoryBatchSummary,
    AdsInventoryBatchItem,
    AdsInventoryArrivalItem,
    AdsInventoryFilterOption,
    AdsInventoryHealthItem,
    AdsInventoryProductWarehouse,
    AdsInventoryTurnoverItem,
    AdsPublishBatch,
)
from app.services.inventory_ads import INVENTORY_DATASET


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def decimal_value(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def new_data_version(snapshot_date: date) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"inventory-{snapshot_date.isoformat()}-{timestamp}-{uuid4().hex[:8]}"


def resolve_snapshot_date(ods_db: Session) -> date:
    values = [
        ods_db.execute(text("SELECT MAX(`updatetime`) FROM `分仓库查询`")).scalar(),
        ods_db.execute(text("SELECT MAX(`updatetime`) FROM `批次货品库存查询`")).scalar(),
    ]
    latest = max((value for value in values if value is not None), default=None)
    if latest is None:
        raise RuntimeError("Inventory source contains no update timestamp")
    if isinstance(latest, datetime):
        return latest.date()
    if isinstance(latest, date):
        return latest
    return date.fromisoformat(str(latest)[:10])


def load_product_warehouse_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              COALESCE(NULLIF(s.`仓库`, ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类') AS product_type,
              s.`货品编号` AS product_code,
              COUNT(*) AS records,
              SUM(COALESCE(s.`库存数量`, 0)) AS stock_quantity,
              SUM(COALESCE(s.`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(s.`库存金额`, 0)) AS stock_amount,
              MAX(COALESCE(limits.`库存下限`, 0)) AS stock_min,
              MAX(COALESCE(limits.`库存上限`, 0)) AS stock_max,
              MAX(s.`updatetime`) AS updated_at
            FROM `分仓库查询` s
            LEFT JOIN (
              SELECT
                `货品编号`,
                MAX(COALESCE(`库存下限`, 0)) AS `库存下限`,
                MAX(COALESCE(`库存上限`, 0)) AS `库存上限`
              FROM `总库存查询`
              GROUP BY `货品编号`
            ) limits ON limits.`货品编号` = s.`货品编号`
            WHERE NULLIF(TRIM(s.`货品编号`), '') IS NOT NULL
            GROUP BY
              COALESCE(NULLIF(s.`仓库`, ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类'),
              s.`货品编号`
            ORDER BY warehouse, product_type, product_code
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_batch_summary_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类') AS product_type,
              COUNT(*) AS batch_records,
              SUM(
                CASE
                  WHEN COALESCE(`剩余有效天数`, 999999) BETWEEN 0 AND 30 THEN 1
                  ELSE 0
                END
              ) AS expiring_batch_count,
              MAX(`updatetime`) AS updated_at
            FROM `批次货品库存查询`
            GROUP BY
              COALESCE(NULLIF(`仓库`, ''), '未归类'),
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类')
            ORDER BY warehouse, product_type
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_filter_option_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT 'warehouse' AS option_type, warehouse AS option_value
            FROM (
              SELECT COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse FROM `分仓库查询`
              UNION
              SELECT COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse FROM `批次货品库存查询`
            ) warehouses
            UNION ALL
            SELECT 'product_type', product_type
            FROM (
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `分仓库查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `总库存查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`货品分类`), '') AS product_type FROM `批次货品库存查询`
            ) product_types
            WHERE product_type IS NOT NULL
            UNION ALL
            SELECT 'brand', brand
            FROM (
              SELECT DISTINCT NULLIF(TRIM(`品牌`), '') AS brand FROM `分仓库查询`
              UNION
              SELECT DISTINCT NULLIF(TRIM(`品牌`), '') AS brand FROM `dwd`.`销售单明细账_品牌补全`
            ) brands
            WHERE brand IS NOT NULL AND brand <> '未归类'
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_health_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              inventory_items.*,
              CASE
                WHEN available_stock < 0 THEN 'negative'
                WHEN COALESCE(NULLIF(barcode, ''), '') = '' THEN 'missing_barcode'
                WHEN stock > 0 AND available_stock <= 0 THEN 'out_of_stock'
                WHEN stock > 0 AND sales90 <= 0 THEN 'no_sales'
                WHEN sales30 > 0 AND available_stock / (sales30 / 30) < 14 THEN 'shortage'
                WHEN sales90 > 0 AND stock / (sales90 / 90) > 180 THEN 'overstock'
                ELSE 'healthy'
              END AS issue_type,
              CASE
                WHEN sales30 > 0 THEN ROUND(available_stock / (sales30 / 30), 1)
                ELSE NULL
              END AS available_days
            FROM (
              SELECT
                `货品编号` AS product_code,
                MAX(`条码`) AS barcode,
                COALESCE(NULLIF(MAX(`货品名称`), ''), '未命名商品') AS product,
                COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
                COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
                COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
                SUM(COALESCE(`库存数量`, 0)) AS stock,
                SUM(COALESCE(`可用库存`, 0)) AS available_stock,
                SUM(COALESCE(`近30天销量`, 0)) AS sales30,
                SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
                SUM(COALESCE(`库存金额`, 0)) AS stock_amount
              FROM `分仓库查询` s
              GROUP BY
                `货品编号`,
                COALESCE(NULLIF(`品牌`, ''), '未归类'),
                COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
                COALESCE(NULLIF(`仓库`, ''), '未归类')
            ) inventory_items
            ORDER BY
              CASE issue_type
                WHEN 'negative' THEN 1
                WHEN 'out_of_stock' THEN 2
                WHEN 'shortage' THEN 3
                WHEN 'missing_barcode' THEN 4
                WHEN 'no_sales' THEN 5
                WHEN 'overstock' THEN 6
                ELSE 7
              END,
              stock_amount DESC,
              available_stock DESC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_batch_item_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              `货品编号` AS product_code,
              `条码` AS barcode,
              `货品名称` AS product,
              COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(`货品分类`), ''), '未归类') AS product_type,
              `批次` AS batch,
              `生产日期` AS production_date,
              `到期日期` AS expiry_date,
              COALESCE(`库存数量`, 0) AS stock,
              COALESCE(`可用库存`, 0) AS available_stock,
              `updatetime` AS updated_at
            FROM `批次货品库存查询`
            WHERE COALESCE(`可用库存`, 0) > 0
            ORDER BY warehouse, product_code, expiry_date, production_date, batch
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_turnover_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              `货品编号` AS product_code,
              MAX(`条码`) AS barcode,
              `货品名称` AS product,
              COALESCE(NULLIF(`品牌`, ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
              SUM(COALESCE(`库存数量`, 0)) AS stock,
              SUM(COALESCE(`可用库存`, 0)) AS available_stock,
              SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
              SUM(COALESCE(`近30天销量`, 0)) AS sales30,
              SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
              MAX(`updatetime`) AS updated_at
            FROM `分仓库查询` s
            WHERE COALESCE(`库存数量`, 0) > 0
            GROUP BY
              `货品编号`,
              `货品名称`,
              COALESCE(NULLIF(`品牌`, ''), '未归类'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未归类'),
              COALESCE(NULLIF(`仓库`, ''), '未归类')
            ORDER BY
              product_code,
              product,
              brand,
              product_type,
              warehouse
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def load_arrival_rows(ods_db: Session) -> list[dict]:
    rows = ods_db.execute(
        text(
            """
            SELECT
              h.`入库时间` AS receipt_time,
              DATE(h.`入库时间`) AS receipt_date,
              YEAR(h.`入库时间`) AS receipt_year,
              h.`docId` AS doc_id,
              d.`recId` AS rec_id,
              h.`入库单号` AS receipt_number,
              h.`入库类型` AS receipt_type,
              COALESCE(NULLIF(TRIM(h.`入库仓库`), ''), '未设置') AS warehouse,
              h.`入库仓库` AS warehouse_raw,
              h.`往来单位` AS supplier,
              h.`红冲状态` AS reversal_status,
              d.`货品编号` AS product_code,
              d.`货品名称` AS product,
              d.`品牌` AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              d.`货品分类` AS product_type_raw,
              COALESCE(d.`数量`, 0) AS quantity,
              COALESCE(d.`入库成本单价`, 0) AS unit_cost,
              COALESCE(d.`入库成本金额`, 0) AS cost_amount,
              d.`批次` AS batch,
              d.`生产日期` AS production_date,
              d.`到期日期` AS expiry_date,
              GREATEST(
                COALESCE(h.`updatetime`, h.`入库时间`),
                COALESCE(d.`updatetime`, h.`入库时间`)
              ) AS updated_at
            FROM `入库查询明细` d
            INNER JOIN `入库查询` h ON h.`docId` = d.`docId`
            WHERE h.`入库时间` IS NOT NULL
            ORDER BY
              h.`入库时间`,
              h.`入库单号`,
              d.`recId`
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def source_summary(
    product_rows: list[dict],
    batch_rows: list[dict],
) -> dict:
    return {
        "warehouse_records": sum(int(row["records"] or 0) for row in product_rows),
        "stock_quantity": sum(decimal_value(row["stock_quantity"]) for row in product_rows),
        "available_stock": sum(decimal_value(row["available_stock"]) for row in product_rows),
        "stock_amount": sum(decimal_value(row["stock_amount"]) for row in product_rows),
        "batch_records": sum(int(row["batch_records"] or 0) for row in batch_rows),
        "expiring_batch_count": sum(
            int(row["expiring_batch_count"] or 0) for row in batch_rows
        ),
    }


def ads_summary(ads_db: Session, data_version: str) -> dict:
    product = ads_db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(`records`), 0) AS warehouse_records,
              COALESCE(SUM(`stock_quantity`), 0) AS stock_quantity,
              COALESCE(SUM(`available_stock`), 0) AS available_stock,
              COALESCE(SUM(`stock_amount`), 0) AS stock_amount
            FROM `ads_inventory_product_warehouse`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    batch = ads_db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(`batch_records`), 0) AS batch_records,
              COALESCE(SUM(`expiring_batch_count`), 0) AS expiring_batch_count
            FROM `ads_inventory_batch_summary`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return {
        "warehouse_records": int(product["warehouse_records"] or 0),
        "stock_quantity": decimal_value(product["stock_quantity"]),
        "available_stock": decimal_value(product["available_stock"]),
        "stock_amount": decimal_value(product["stock_amount"]),
        "batch_records": int(batch["batch_records"] or 0),
        "expiring_batch_count": int(batch["expiring_batch_count"] or 0),
    }


def health_summary(rows: list[dict]) -> dict:
    counts = {
        "item_count": len(rows),
        "negative_count": 0,
        "missing_barcode_count": 0,
        "out_of_stock_count": 0,
        "no_sales_count": 0,
        "shortage_count": 0,
        "overstock_count": 0,
        "healthy_count": 0,
    }
    for row in rows:
        key = f"{row['issue_type']}_count"
        if key in counts:
            counts[key] += 1
    return counts


def ads_health_summary(ads_db: Session, data_version: str) -> dict:
    row = ads_db.execute(
        text(
            """
            SELECT
              COUNT(*) AS item_count,
              SUM(`issue_type` = 'negative') AS negative_count,
              SUM(`issue_type` = 'missing_barcode') AS missing_barcode_count,
              SUM(`issue_type` = 'out_of_stock') AS out_of_stock_count,
              SUM(`issue_type` = 'no_sales') AS no_sales_count,
              SUM(`issue_type` = 'shortage') AS shortage_count,
              SUM(`issue_type` = 'overstock') AS overstock_count,
              SUM(`issue_type` = 'healthy') AS healthy_count
            FROM `ads_inventory_health_item`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return {key: int(value or 0) for key, value in row.items()}


def batch_item_summary(rows: list[dict]) -> dict:
    return {
        "batch_count": len(rows),
        "stock": sum(decimal_value(row["stock"]) for row in rows),
        "available_stock": sum(
            decimal_value(row["available_stock"]) for row in rows
        ),
    }


def ads_batch_item_summary(ads_db: Session, data_version: str) -> dict:
    row = ads_db.execute(
        text(
            """
            SELECT
              COUNT(*) AS batch_count,
              COALESCE(SUM(`stock`), 0) AS stock,
              COALESCE(SUM(`available_stock`), 0) AS available_stock
            FROM `ads_inventory_batch_item`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return {
        "batch_count": int(row["batch_count"] or 0),
        "stock": decimal_value(row["stock"]),
        "available_stock": decimal_value(row["available_stock"]),
    }


def turnover_summary(rows: list[dict]) -> dict:
    return {
        "item_count": len(rows),
        "stock": sum(decimal_value(row["stock"]) for row in rows),
        "available_stock": sum(
            decimal_value(row["available_stock"]) for row in rows
        ),
        "stock_amount": sum(
            decimal_value(row["stock_amount"]) for row in rows
        ),
        "sales30": sum(decimal_value(row["sales30"]) for row in rows),
        "sales90": sum(decimal_value(row["sales90"]) for row in rows),
    }


def ads_turnover_summary(ads_db: Session, data_version: str) -> dict:
    row = ads_db.execute(
        text(
            """
            SELECT
              COUNT(*) AS item_count,
              COALESCE(SUM(`stock`), 0) AS stock,
              COALESCE(SUM(`available_stock`), 0) AS available_stock,
              COALESCE(SUM(`stock_amount`), 0) AS stock_amount,
              COALESCE(SUM(`sales30`), 0) AS sales30,
              COALESCE(SUM(`sales90`), 0) AS sales90
            FROM `ads_inventory_turnover_item`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return {
        "item_count": int(row["item_count"] or 0),
        "stock": decimal_value(row["stock"]),
        "available_stock": decimal_value(row["available_stock"]),
        "stock_amount": decimal_value(row["stock_amount"]),
        "sales30": decimal_value(row["sales30"]),
        "sales90": decimal_value(row["sales90"]),
    }


def arrival_summary(rows: list[dict]) -> dict:
    return {
        "item_count": len(rows),
        "document_count": len(
            {str(row["doc_id"]) for row in rows if row["doc_id"]}
        ),
        "net_quantity": sum(decimal_value(row["quantity"]) for row in rows),
        "net_cost_amount": sum(
            decimal_value(row["cost_amount"]) for row in rows
        ),
    }


def ads_arrival_summary(ads_db: Session, data_version: str) -> dict:
    row = ads_db.execute(
        text(
            """
            SELECT
              COUNT(*) AS item_count,
              COUNT(DISTINCT `doc_id`) AS document_count,
              COALESCE(SUM(`quantity`), 0) AS net_quantity,
              COALESCE(SUM(`cost_amount`), 0) AS net_cost_amount
            FROM `ads_inventory_arrival_item`
            WHERE `data_version` = :data_version
            """
        ),
        {"data_version": data_version},
    ).mappings().one()
    return {
        "item_count": int(row["item_count"] or 0),
        "document_count": int(row["document_count"] or 0),
        "net_quantity": decimal_value(row["net_quantity"]),
        "net_cost_amount": decimal_value(row["net_cost_amount"]),
    }


def reconciliation_payload(source: dict, ads: dict) -> dict:
    fields = (
        "warehouse_records",
        "stock_quantity",
        "available_stock",
        "stock_amount",
        "batch_records",
        "expiring_batch_count",
    )
    matches = {field: source[field] == ads[field] for field in fields}
    return {
        "passed": all(matches.values()),
        "matches": matches,
        "source": {key: str(value) for key, value in source.items()},
        "ads": {key: str(value) for key, value in ads.items()},
    }


def build_inventory_ads(data_version: str | None = None) -> dict:
    if not settings.ODS_DATABASE_URL:
        raise RuntimeError("ODS_DATABASE_URL is not configured")
    ads_session_factory = require_ads_build_session_factory()
    ods_engine = create_ods_engine(
        settings.ODS_DATABASE_URL,
        read_timeout=settings.ODS_BUILD_READ_TIMEOUT_SECONDS,
    )
    ods_db = Session(bind=ods_engine)
    try:
        snapshot_date = resolve_snapshot_date(ods_db)
        version = data_version or new_data_version(snapshot_date)
        with ads_session_factory() as ads_db:
            batch = AdsPublishBatch(
                data_version=version,
                dataset=INVENTORY_DATASET,
                status="building",
                source_start_date=snapshot_date,
                source_end_date=snapshot_date,
                created_at=utc_now(),
            )
            ads_db.add(batch)
            ads_db.commit()
            batch_id = batch.id
            try:
                product_rows = load_product_warehouse_rows(ods_db)
                batch_rows = load_batch_summary_rows(ods_db)
                option_rows = load_filter_option_rows(ods_db)
                health_rows = load_health_rows(ods_db)
                batch_item_rows = load_batch_item_rows(ods_db)
                turnover_rows = load_turnover_rows(ods_db)
                arrival_rows = load_arrival_rows(ods_db)
                arrival_options = {
                    ("arrival_year", str(row["receipt_year"]))
                    for row in arrival_rows
                }
                arrival_options.update(
                    {
                        ("arrival_brand", str(row["brand"]).strip())
                        for row in arrival_rows
                        if row["brand"] and str(row["brand"]).strip()
                    }
                )
                arrival_options.update(
                    {
                        ("arrival_product_type", str(row["product_type"]))
                        for row in arrival_rows
                    }
                )
                arrival_options.update(
                    {
                        ("arrival_warehouse", str(row["warehouse"]))
                        for row in arrival_rows
                    }
                )
                option_rows.extend(
                    {
                        "option_type": option_type,
                        "option_value": option_value,
                    }
                    for option_type, option_value in sorted(arrival_options)
                )
                if (
                    not product_rows
                    or not batch_rows
                    or not option_rows
                    or not health_rows
                    or not batch_item_rows
                    or not turnover_rows
                    or not arrival_rows
                ):
                    raise RuntimeError("No inventory rows found")

                ads_db.execute(
                    insert(AdsInventoryProductWarehouse),
                    [
                        {
                            "data_version": version,
                            "warehouse": str(row["warehouse"]),
                            "product_type": str(row["product_type"]),
                            "product_code": str(row["product_code"]),
                            "records": int(row["records"] or 0),
                            "stock_quantity": decimal_value(row["stock_quantity"]),
                            "available_stock": decimal_value(row["available_stock"]),
                            "stock_amount": decimal_value(row["stock_amount"]),
                            "stock_min": decimal_value(row["stock_min"]),
                            "stock_max": decimal_value(row["stock_max"]),
                            "updated_at": row["updated_at"],
                        }
                        for row in product_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryBatchSummary),
                    [
                        {
                            "data_version": version,
                            "warehouse": str(row["warehouse"]),
                            "product_type": str(row["product_type"]),
                            "batch_records": int(row["batch_records"] or 0),
                            "expiring_batch_count": int(row["expiring_batch_count"] or 0),
                            "updated_at": row["updated_at"],
                        }
                        for row in batch_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryFilterOption),
                    [
                        {
                            "data_version": version,
                            "option_type": str(row["option_type"]),
                            "option_value": str(row["option_value"]),
                        }
                        for row in option_rows
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryHealthItem),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "product_code": str(row["product_code"] or "-").strip() or "-",
                            "barcode": str(row["barcode"] or "-").strip() or "-",
                            "product": str(row["product"]),
                            "brand": str(row["brand"]),
                            "product_type": str(row["product_type"]),
                            "warehouse": str(row["warehouse"]),
                            "stock": decimal_value(row["stock"]),
                            "available_stock": decimal_value(row["available_stock"]),
                            "sales30": decimal_value(row["sales30"]),
                            "sales90": decimal_value(row["sales90"]),
                            "stock_amount": decimal_value(row["stock_amount"]),
                            "available_days": (
                                decimal_value(row["available_days"])
                                if row["available_days"] is not None
                                else None
                            ),
                            "issue_type": str(row["issue_type"]),
                        }
                        for index, row in enumerate(health_rows, start=1)
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryBatchItem),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "warehouse": str(row["warehouse"]),
                            "product_code": row["product_code"],
                            "barcode": row["barcode"],
                            "product": row["product"],
                            "brand": str(row["brand"]),
                            "product_type": str(row["product_type"]),
                            "batch": row["batch"],
                            "production_date": row["production_date"],
                            "expiry_date": row["expiry_date"],
                            "stock": decimal_value(row["stock"]),
                            "available_stock": decimal_value(row["available_stock"]),
                            "updated_at": row["updated_at"],
                        }
                        for index, row in enumerate(batch_item_rows, start=1)
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryTurnoverItem),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "product_code": row["product_code"],
                            "barcode": row["barcode"],
                            "product": row["product"],
                            "brand": str(row["brand"]),
                            "product_type": str(row["product_type"]),
                            "warehouse": str(row["warehouse"]),
                            "stock": decimal_value(row["stock"]),
                            "available_stock": decimal_value(row["available_stock"]),
                            "stock_amount": decimal_value(row["stock_amount"]),
                            "sales30": decimal_value(row["sales30"]),
                            "sales90": decimal_value(row["sales90"]),
                            "updated_at": row["updated_at"],
                        }
                        for index, row in enumerate(turnover_rows, start=1)
                    ],
                )
                ads_db.execute(
                    insert(AdsInventoryArrivalItem),
                    [
                        {
                            "data_version": version,
                            "item_id": index,
                            "receipt_time": row["receipt_time"],
                            "receipt_date": row["receipt_date"],
                            "receipt_year": int(row["receipt_year"]),
                            "doc_id": str(row["doc_id"]),
                            "rec_id": str(row["rec_id"]),
                            "receipt_number": row["receipt_number"],
                            "receipt_type": row["receipt_type"],
                            "warehouse": str(row["warehouse"]),
                            "warehouse_raw": row["warehouse_raw"],
                            "supplier": row["supplier"],
                            "reversal_status": row["reversal_status"],
                            "product_code": row["product_code"],
                            "product": row["product"],
                            "brand": row["brand"],
                            "product_type": str(row["product_type"]),
                            "product_type_raw": row["product_type_raw"],
                            "quantity": decimal_value(row["quantity"]),
                            "unit_cost": decimal_value(row["unit_cost"]),
                            "cost_amount": decimal_value(row["cost_amount"]),
                            "batch": row["batch"],
                            "production_date": row["production_date"],
                            "expiry_date": row["expiry_date"],
                            "updated_at": row["updated_at"],
                        }
                        for index, row in enumerate(arrival_rows, start=1)
                    ],
                )

                source = source_summary(product_rows, batch_rows)
                ads = ads_summary(ads_db, version)
                reconciliation = reconciliation_payload(source, ads)
                source_health = health_summary(health_rows)
                ads_health = ads_health_summary(ads_db, version)
                health_matches = source_health == ads_health
                reconciliation["health"] = {
                    "matches": health_matches,
                    "source": source_health,
                    "ads": ads_health,
                }
                source_batch_items = batch_item_summary(batch_item_rows)
                ads_batch_items = ads_batch_item_summary(ads_db, version)
                batch_item_matches = {
                    field: source_batch_items[field] == ads_batch_items[field]
                    for field in source_batch_items
                }
                batch_items_match = all(batch_item_matches.values())
                reconciliation["batch_expiry"] = {
                    "matches": batch_items_match,
                    "field_matches": batch_item_matches,
                    "source": {
                        field: str(value) for field, value in source_batch_items.items()
                    },
                    "ads": {
                        field: str(value) for field, value in ads_batch_items.items()
                    },
                }
                source_turnover = turnover_summary(turnover_rows)
                ads_turnover = ads_turnover_summary(ads_db, version)
                turnover_field_matches = {
                    field: source_turnover[field] == ads_turnover[field]
                    for field in source_turnover
                }
                turnover_matches = all(turnover_field_matches.values())
                reconciliation["product_turnover"] = {
                    "matches": turnover_matches,
                    "field_matches": turnover_field_matches,
                    "source": {
                        field: str(value) for field, value in source_turnover.items()
                    },
                    "ads": {
                        field: str(value) for field, value in ads_turnover.items()
                    },
                }
                source_arrivals = arrival_summary(arrival_rows)
                ads_arrivals = ads_arrival_summary(ads_db, version)
                arrival_field_matches = {
                    field: source_arrivals[field] == ads_arrivals[field]
                    for field in source_arrivals
                }
                arrival_matches = all(arrival_field_matches.values())
                reconciliation["brand_monthly_arrivals"] = {
                    "matches": arrival_matches,
                    "field_matches": arrival_field_matches,
                    "source": {
                        field: str(value) for field, value in source_arrivals.items()
                    },
                    "ads": {
                        field: str(value) for field, value in ads_arrivals.items()
                    },
                }
                reconciliation["passed"] = (
                    reconciliation["passed"]
                    and health_matches
                    and batch_items_match
                    and turnover_matches
                    and arrival_matches
                )
                if not reconciliation["passed"]:
                    failed_sections = [
                        section
                        for section, passed in (
                            ("overview", all(reconciliation["matches"].values())),
                            ("health", health_matches),
                            ("batch_expiry", batch_items_match),
                            ("product_turnover", turnover_matches),
                            ("brand_monthly_arrivals", arrival_matches),
                        )
                        if not passed
                    ]
                    raise RuntimeError(
                        "Inventory ADS reconciliation failed: "
                        + ",".join(failed_sections)
                        + (
                            " fields="
                            + ",".join(
                                field
                                for field, matched in batch_item_matches.items()
                                if not matched
                            )
                            if not batch_items_match
                            else ""
                        )
                    )

                finished_at = utc_now()
                published = ads_db.get(AdsPublishBatch, batch_id)
                if published is None:
                    raise RuntimeError("Inventory ADS publish batch disappeared")
                published.status = "ready"
                published.daily_row_count = len(product_rows)
                published.channel_row_count = len(batch_rows)
                published.reconciliation = reconciliation
                published.finished_at = finished_at
                published.published_at = finished_at
                ads_db.commit()
                return {
                    "data_version": version,
                    "status": "ready",
                    "snapshot_date": snapshot_date.isoformat(),
                    "product_warehouse_rows": len(product_rows),
                    "batch_summary_rows": len(batch_rows),
                    "filter_option_rows": len(option_rows),
                    "health_item_rows": len(health_rows),
                    "batch_item_rows": len(batch_item_rows),
                    "turnover_item_rows": len(turnover_rows),
                    "arrival_item_rows": len(arrival_rows),
                    "reconciliation": reconciliation,
                }
            except Exception as exc:
                ads_db.rollback()
                failed = ads_db.get(AdsPublishBatch, batch_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error_code = type(exc).__name__
                    failed.finished_at = utc_now()
                    ads_db.commit()
                raise
    finally:
        ods_db.close()
        ods_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build versioned inventory ADS tables")
    parser.add_argument("--data-version", help="Optional immutable data version")
    parser.add_argument("--initialize-only", action="store_true")
    args = parser.parse_args()
    if args.initialize_only:
        initialize_ads_schema()
        print("ADS schema initialized")
        return
    result = build_inventory_ads(data_version=args.data_version)
    print(
        "inventory ADS published "
        f"version={result['data_version']} "
        f"snapshot={result['snapshot_date']} "
        f"product_warehouse_rows={result['product_warehouse_rows']} "
        f"batch_summary_rows={result['batch_summary_rows']} "
        f"filter_option_rows={result['filter_option_rows']} "
        f"health_item_rows={result['health_item_rows']} "
        f"batch_item_rows={result['batch_item_rows']} "
        f"turnover_item_rows={result['turnover_item_rows']} "
        f"arrival_item_rows={result['arrival_item_rows']}"
    )


if __name__ == "__main__":
    main()
