from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("BI_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
BACKEND_ROOT = Path(os.environ.get("BI_BACKEND_ROOT", PROJECT_ROOT / "backend"))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

from sqlalchemy import text

from app.db.ads import AdsSessionLocal
from app.db.ods import OdsSessionLocal
from app.services.inventory_ads import latest_ready_inventory_batch
from app.services.sales_ads import latest_ready_sales_batch
from app.services.sales_sources import is_online_sales_channel


parser = argparse.ArgumentParser(description="提取经营月报的本月、上月和去年同期数据。")
parser.add_argument("--month", default="2026-08", help="报告月份，格式 YYYY-MM。")
args = parser.parse_args()


def month_range(value: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{value}-01")
    end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    return start, end


report_start, report_end = month_range(args.month)
previous_end = report_start - timedelta(days=1)
previous_start = previous_end.replace(day=1)
year_ago_start = report_start.replace(year=report_start.year - 1)
year_ago_end = date(
    year_ago_start.year,
    year_ago_start.month,
    calendar.monthrange(year_ago_start.year, year_ago_start.month)[1],
)

PERIODS = (
    ("去年同期", year_ago_start, year_ago_end),
    ("上月", previous_start, previous_end),
    ("本月", report_start, report_end),
)


def serializable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(type(value).__name__)


ads = AdsSessionLocal()
ods = OdsSessionLocal()
try:
    sales_batch = latest_ready_sales_batch(ads)
    inventory_batch = latest_ready_inventory_batch(ads)
    output = {
        "sales_batch": {
            "id": sales_batch.id,
            "data_version": sales_batch.data_version,
            "source_start_date": sales_batch.source_start_date,
            "source_end_date": sales_batch.source_end_date,
            "status": sales_batch.status,
        },
        "inventory_batch": {
            "id": inventory_batch.id,
            "data_version": inventory_batch.data_version,
            "source_start_date": inventory_batch.source_start_date,
            "source_end_date": inventory_batch.source_end_date,
            "status": inventory_batch.status,
            "arrival_reconciliation": (inventory_batch.reconciliation or {}).get("brand_monthly_arrivals", {}),
        },
        "periods": [],
    }

    dimension_rows = ods.execute(text("""
        SELECT
          `渠道名称` AS channel_name,
          COALESCE(NULLIF(`分类`, ''), '未分类') AS category,
          COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform
        FROM `渠道列表`
        WHERE NULLIF(`渠道名称`, '') IS NOT NULL
    """)).mappings().all()
    dimensions = {str(row["channel_name"]): dict(row) for row in dimension_rows}

    for label, start_date, end_date in PERIODS:
        params = {
            "sales_version": sales_batch.data_version,
            "inventory_version": inventory_batch.data_version,
            "start_date": start_date,
            "end_date": end_date,
        }
        summary = dict(ads.execute(text("""
            SELECT COUNT(*) AS day_rows,
                   MIN(`sales_date`) AS min_date,
                   MAX(`sales_date`) AS max_date,
                   SUM(`paid_amount`) AS paid_amount,
                   SUM(`orders`) AS orders,
                   SUM(`quantity`) AS quantity
            FROM `ads_sales_daily`
            WHERE `data_version` = :sales_version
              AND `sales_date` BETWEEN :start_date AND :end_date
        """), params).mappings().one())

        scope_rows = [dict(row) for row in ads.execute(text("""
            SELECT `product_type_scope`,
                   COUNT(DISTINCT `sales_date`) AS day_rows,
                   SUM(`paid_amount`) AS paid_amount,
                   SUM(`orders`) AS orders,
                   SUM(`quantity`) AS quantity
            FROM `ads_sales_detail_daily_scope`
            WHERE `data_version` = :sales_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `product_type_scope` IN ('full_size', 'sample', 'selected', 'all')
            GROUP BY `product_type_scope`
            ORDER BY `product_type_scope`
        """), params).mappings().all()]

        channel_rows = ads.execute(text("""
            SELECT `channel`, SUM(`paid_amount`) AS paid_amount,
                   SUM(`orders`) AS orders, SUM(`quantity`) AS quantity
            FROM `ads_sales_daily_channel`
            WHERE `data_version` = :sales_version
              AND `sales_date` BETWEEN :start_date AND :end_date
            GROUP BY `channel`
        """), params).mappings().all()
        channel_summary = {
            "online": {"paid_amount": Decimal("0"), "orders": 0, "quantity": Decimal("0"), "channels": 0},
            "offline": {"paid_amount": Decimal("0"), "orders": 0, "quantity": Decimal("0"), "channels": 0},
            "unmatched_channels": 0,
        }
        for row in channel_rows:
            name = str(row["channel"])
            dimension = dimensions.get(name)
            if dimension:
                online = is_online_sales_channel(dimension["category"], dimension["platform"], name)
            else:
                online = is_online_sales_channel("未匹配渠道", "未设置", name)
                channel_summary["unmatched_channels"] += 1
            target = channel_summary["online" if online else "offline"]
            target["paid_amount"] += row["paid_amount"] or 0
            target["orders"] += int(row["orders"] or 0)
            target["quantity"] += row["quantity"] or 0
            target["channels"] += 1

        customer_row = dict(ads.execute(text("""
            SELECT COUNT(*) AS customers,
                   SUM(CASE WHEN customer_orders >= 2 THEN 1 ELSE 0 END) AS repeat_customers,
                   SUM(customer_orders) AS orders,
                   SUM(paid_amount) AS paid_amount,
                   SUM(quantity) AS quantity
            FROM (
              SELECT `customer_code`, SUM(`orders`) AS customer_orders,
                     SUM(`paid_amount`) AS paid_amount, SUM(`quantity`) AS quantity
              FROM `ads_sales_customer_daily`
              WHERE `data_version` = :sales_version
                AND `sales_date` BETWEEN :start_date AND :end_date
                AND `brand` = '__all__'
              GROUP BY `customer_code`
            ) customer_period
        """), params).mappings().one())
        quality_row = dict(ads.execute(text("""
            SELECT SUM(`orders`) AS orders,
                   SUM(`identified_orders`) AS identified_orders,
                   SUM(`paid_amount`) AS paid_amount,
                   SUM(`identified_amount`) AS identified_amount
            FROM `ads_sales_customer_quality_daily`
            WHERE `data_version` = :sales_version
              AND `sales_date` BETWEEN :start_date AND :end_date
              AND `brand` = '__all__'
        """), params).mappings().one())

        arrival_row = dict(ads.execute(text("""
            SELECT SUM(`quantity`) AS net_quantity,
                   COUNT(DISTINCT `doc_id`) AS document_count,
                   COUNT(DISTINCT NULLIF(`brand`, '')) AS brand_count,
                   MAX(`updated_at`) AS updated_at
            FROM `ads_inventory_arrival_item`
            WHERE `data_version` = :inventory_version
              AND `receipt_date` BETWEEN :start_date AND :end_date
        """), params).mappings().one())

        snapshot_row = dict(ods.execute(text("""
            SELECT b.`快照日期` AS snapshot_date,
                   MAX(b.`完成时间`) AS completed_at,
                   COUNT(h.`货品编号`) AS detail_rows,
                   SUM(COALESCE(h.`库存量`, 0)) AS stock_quantity,
                   SUM(COALESCE(h.`库存金额`, 0)) AS stock_amount
            FROM `历史库存快照批次` b
            LEFT JOIN `历史库存` h ON h.`快照日期` = b.`快照日期`
            WHERE b.`快照日期` = :end_date
              AND UPPER(COALESCE(b.`状态`, '')) = 'SUCCESS'
            GROUP BY b.`快照日期`
        """), params).mappings().one())

        output["periods"].append({
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
            "summary": summary,
            "product_scopes": scope_rows,
            "channel_summary": channel_summary,
            "customer_summary": customer_row,
            "customer_quality": quality_row,
            "arrivals": arrival_row,
            "inventory_snapshot": snapshot_row,
        })

    output["daily"] = [dict(row) for row in ads.execute(text("""
        SELECT `sales_date`, `paid_amount`, `orders`, `quantity`
        FROM `ads_sales_daily`
        WHERE `data_version` = :sales_version
          AND `sales_date` BETWEEN :start_date AND :end_date
        ORDER BY `sales_date`
    """), {
        "sales_version": sales_batch.data_version,
        "start_date": report_start,
        "end_date": report_end,
    }).mappings().all()]
    output["brands"] = [dict(row) for row in ads.execute(text("""
        SELECT `brand`, SUM(`paid_amount`) AS paid_amount,
               SUM(`orders`) AS orders, SUM(`quantity`) AS quantity
        FROM `ads_sales_daily_brand_scope`
        WHERE `data_version` = :sales_version
          AND `product_type_scope` = 'all'
          AND `sales_date` BETWEEN :start_date AND :end_date
        GROUP BY `brand`
        ORDER BY `paid_amount` DESC
    """), {
        "sales_version": sales_batch.data_version,
        "start_date": report_start,
        "end_date": report_end,
    }).mappings().all()]

    print(json.dumps(output, ensure_ascii=False, default=serializable))
finally:
    ads.close()
    ods.close()
