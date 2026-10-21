from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ok
from app.core.config import settings
from app.services.decision_summary import remember, summary_state
from app.services.decision_sales import load_sales_evidence
from app.services.sales_sources import SALES_ORDER_TABLE_SQL


router = APIRouter(prefix="/ai", tags=["ai"])
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = Lock()


def _warehouses(values: list[str] | None) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values or [] if value.strip()}))


def _warehouse_sql(values: tuple[str, ...]) -> tuple[str, dict]:
    if not values:
        return "", {}
    params = {f"warehouse_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f":{key}" for key in params)
    return f"AND COALESCE(NULLIF(`仓库`, ''), '未归类') IN ({placeholders})", params


def _get_cache(key: tuple) -> dict | None:
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            return deepcopy(cached[1])
        if cached:
            _cache.pop(key, None)
    return None


def _set_cache(key: tuple, data: dict) -> None:
    with _cache_lock:
        _cache[key] = (monotonic() + 300, deepcopy(data))
        expired = [item for item, cached in _cache.items() if cached[0] <= monotonic()]
        for item in expired:
            _cache.pop(item, None)
        while len(_cache) > 32:
            _cache.pop(next(iter(_cache)))


def _number(value: object) -> float:
    if value is None:
        return 0
    return float(value)


@router.get("/inventory-decisions")
def inventory_decisions(
    warehouse: list[str] | None = Query(None),
    refresh: bool = Query(False),
    current_user: User = Depends(get_current_user),
    ods_db: Session = Depends(get_ods_db),
    db: Session = Depends(get_db),
) -> dict:
    warehouses = _warehouses(warehouse)
    cache_key = ("inventory-decisions-v5", warehouses, settings.BI_QUERY_SOURCE)
    if not refresh:
        cached = _get_cache(cache_key)
        if cached is not None:
            return ok(cached)

    warehouse_sql, params = _warehouse_sql(warehouses)
    rows = ods_db.execute(
        text(
            f"""
            SELECT *
            FROM (
              SELECT
                `货品编号` AS product_code,
                MAX(`货品名称`) AS product,
                MAX(COALESCE(NULLIF(`品牌`, ''), '未归类')) AS brand,
                MAX(`条码`) AS barcode,
                COALESCE(NULLIF(`仓库`, ''), '未归类') AS warehouse,
                SUM(COALESCE(`库存数量`, 0)) AS stock,
                SUM(COALESCE(`可用库存`, 0)) AS available_stock,
                SUM(COALESCE(`近30天销量`, 0)) AS sales30,
                SUM(COALESCE(`近90天销量(库存公式)`, 0)) AS sales90,
                SUM(COALESCE(`库存金额`, 0)) AS stock_amount,
                CASE
                  WHEN SUM(COALESCE(`可用库存`, 0)) < 0 THEN 'negative'
                  WHEN SUM(COALESCE(`库存数量`, 0)) > 0 AND SUM(COALESCE(`可用库存`, 0)) <= 0 THEN 'out_of_stock'
                  WHEN SUM(COALESCE(`库存数量`, 0)) > 0 AND SUM(COALESCE(`近90天销量(库存公式)`, 0)) <= 0 THEN 'no_sales'
                  WHEN SUM(COALESCE(`近30天销量`, 0)) > 0
                    AND SUM(COALESCE(`可用库存`, 0)) / (SUM(COALESCE(`近30天销量`, 0)) / 30) < 14 THEN 'shortage'
                  WHEN SUM(COALESCE(`近90天销量(库存公式)`, 0)) > 0
                    AND SUM(COALESCE(`库存数量`, 0)) / (SUM(COALESCE(`近90天销量(库存公式)`, 0)) / 90) > 180 THEN 'overstock'
                  ELSE 'healthy'
                END AS issue_type
              FROM `分仓库查询`
              WHERE 1 = 1 {warehouse_sql}
              GROUP BY `货品编号`, COALESCE(NULLIF(`仓库`, ''), '未归类')
            ) inventory_items
            WHERE issue_type <> 'healthy'
            ORDER BY
              FIELD(issue_type, 'negative', 'out_of_stock', 'shortage', 'no_sales', 'overstock'),
              stock_amount DESC,
              available_stock DESC
            LIMIT 20
            """
        ),
        params,
    ).mappings().all()
    expiry = ods_db.execute(
        text(
            f"""
            SELECT
              SUM(CASE WHEN `到期日期` < CURDATE() THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS expired_stock,
              SUM(CASE WHEN `到期日期` BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 6 MONTH)
                THEN COALESCE(`可用库存`, 0) ELSE 0 END) AS expiring_stock
            FROM `批次货品库存查询`
            WHERE COALESCE(`可用库存`, 0) > 0 {warehouse_sql}
            """
        ),
        params,
    ).mappings().one()
    if settings.BI_QUERY_SOURCE == 'ads':
        sales_evidence = load_sales_evidence()
    else:
        sales_evidence = _legacy_sales_evidence(ods_db)
    sales_evidence['scope'] = '全部销售；仓库筛选仅作用于库存'

    labels = {
        "negative": ("紧急", "负库存", "检查库存同步、占用和出库回传"),
        "out_of_stock": ("高", "可用库存为零", "检查锁定库存并评估补货"),
        "shortage": ("高", "缺货风险", "结合在途库存制定补货或调拨"),
        "no_sales": ("中", "90天无销量", "停止补货并评估促销清理"),
        "overstock": ("中", "超储风险", "降低采购并评估跨仓调拨"),
    }
    decisions = []
    for index, row in enumerate(rows):
        priority, issue, action = labels.get(row["issue_type"], ("中", "库存异常", "人工复核"))
        available_days = None
        if float(row["sales30"] or 0) > 0:
            available_days = round(float(row["available_stock"] or 0) / (float(row["sales30"]) / 30), 1)
        decisions.append(
            {
                "id": f"{row['issue_type']}-{row['warehouse']}-{row['product_code']}",
                "rank": index + 1,
                "priority": priority,
                "issue_type": row["issue_type"],
                "issue": issue,
                "product_code": str(row["product_code"] or "-"),
                "product": str(row["product"] or "未命名商品"),
                "brand": str(row["brand"] or "未归类"),
                "barcode": str(row["barcode"] or "-"),
                "warehouse": str(row["warehouse"] or "未归类"),
                "stock": float(row["stock"] or 0),
                "available_stock": float(row["available_stock"] or 0),
                "sales30": float(row["sales30"] or 0),
                "sales90": float(row["sales90"] or 0),
                "stock_amount": float(row["stock_amount"] or 0),
                "available_days": available_days,
                "suggested_action": action,
            }
        )

    evidence = {
        "warehouses": list(warehouses),
        "sales": sales_evidence,
        "inventory": {
            "decision_count": len(decisions),
            "expired_stock": float(expiry["expired_stock"] or 0),
            "expiring_stock": float(expiry["expiring_stock"] or 0),
            "top_decisions": decisions[:12],
        },
    }
    evidence_id = remember(evidence)
    data = {
        "warehouses_selected": list(warehouses),
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "evidence_id": evidence_id,
        "sales": sales_evidence,
        "ai_status": "idle",
        "ai_summary": "",
        "metrics": {
            "decision_count": len(decisions),
            "urgent_count": sum(item["priority"] == "紧急" for item in decisions),
            "high_count": sum(item["priority"] == "高" for item in decisions),
            "expired_stock": evidence["inventory"]["expired_stock"],
            "expiring_stock": evidence["inventory"]["expiring_stock"],
        },
        "decisions": decisions,
    }
    _set_cache(cache_key, data)
    return ok(data)


@router.get("/inventory-decisions/summary")
def get_decision_summary(evidence_id: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
                         warehouse: list[str] | None = Query(None),
                         current_user: User = Depends(get_current_user)):
    return ok(summary_state(evidence_id, _warehouses(warehouse)))


@router.post("/inventory-decisions/summary")
def start_decision_summary(evidence_id: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
                           warehouse: list[str] | None = Query(None),
                           refresh: bool = Query(False),
                           current_user: User = Depends(get_current_user)):
    return ok(summary_state(evidence_id, _warehouses(warehouse), start=True, refresh=refresh))


def _legacy_sales_evidence(ods_db):
    sales_anchor = ods_db.execute(
        text(
            f"SELECT MAX(`下单时间`) FROM {SALES_ORDER_TABLE_SQL} "
            "WHERE COALESCE(`订单状态`, '') NOT LIKE '%取消%'"
        )
    ).scalar()
    sales_evidence = {
        "period": "近30天",
        "start_date": None,
        "end_date": None,
        "current": {"paid_amount": 0, "orders": 0, "quantity": 0, "avg_order_amount": 0},
        "previous": {"paid_amount": 0, "orders": 0, "quantity": 0, "avg_order_amount": 0},
        "change": {"paid_amount_rate": None, "orders_rate": None, "quantity_rate": None},
        "top_channels": [],
    }
    if sales_anchor is not None:
        sales_end = sales_anchor.date() if isinstance(sales_anchor, datetime) else sales_anchor
        sales_start = sales_end - timedelta(days=29)
        previous_end = sales_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=29)

        sales_params = {
            "sales_start": sales_start,
            "sales_end": sales_end,
            "previous_start": previous_start,
            "previous_end": previous_end,
        }
        sales_summary = ods_db.execute(
            text(
                f"""
                SELECT
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM {SALES_ORDER_TABLE_SQL}
                WHERE `下单时间` >= :sales_start
                  AND `下单时间` < DATE_ADD(:sales_end, INTERVAL 1 DAY)
                  AND COALESCE(`订单状态`, '') NOT LIKE '%取消%'
                """
            ),
            sales_params,
        ).mappings().one()
        previous_summary = ods_db.execute(
            text(
                f"""
                SELECT
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM {SALES_ORDER_TABLE_SQL}
                WHERE `下单时间` >= :previous_start
                  AND `下单时间` < DATE_ADD(:previous_end, INTERVAL 1 DAY)
                  AND COALESCE(`订单状态`, '') NOT LIKE '%取消%'
                """
            ),
            sales_params,
        ).mappings().one()
        top_channels = ods_db.execute(
            text(
                f"""
                SELECT
                  COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM {SALES_ORDER_TABLE_SQL}
                WHERE `下单时间` >= :sales_start
                  AND `下单时间` < DATE_ADD(:sales_end, INTERVAL 1 DAY)
                  AND COALESCE(`订单状态`, '') NOT LIKE '%取消%'
                GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
                ORDER BY paid_amount DESC
                LIMIT 8
                """
            ),
            sales_params,
        ).mappings().all()

        current_paid_amount = _number(sales_summary["paid_amount"])
        current_orders = int(sales_summary["orders"] or 0)
        current_quantity = _number(sales_summary["quantity"])
        previous_paid_amount = _number(previous_summary["paid_amount"])
        previous_orders = int(previous_summary["orders"] or 0)
        previous_quantity = _number(previous_summary["quantity"])

        def change_rate(current: float, previous: float) -> float | None:
            if previous == 0:
                return None
            return round((current - previous) / previous * 100, 2)

        sales_evidence = {
            "period": "近30天",
            "start_date": sales_start.isoformat(),
            "end_date": sales_end.isoformat(),
            "current": {
                "paid_amount": round(current_paid_amount, 2),
                "orders": current_orders,
                "quantity": round(current_quantity, 2),
                "avg_order_amount": round(current_paid_amount / current_orders, 2) if current_orders else 0,
            },
            "previous": {
                "start_date": previous_start.isoformat(),
                "end_date": previous_end.isoformat(),
                "paid_amount": round(previous_paid_amount, 2),
                "orders": previous_orders,
                "quantity": round(previous_quantity, 2),
                "avg_order_amount": round(previous_paid_amount / previous_orders, 2) if previous_orders else 0,
            },
            "change": {
                "paid_amount_rate": change_rate(current_paid_amount, previous_paid_amount),
                "orders_rate": change_rate(current_orders, previous_orders),
                "quantity_rate": change_rate(current_quantity, previous_quantity),
            },
            "top_channels": [
                {
                    "channel": str(row["channel"] or "未归类"),
                    "paid_amount": round(_number(row["paid_amount"]), 2),
                    "orders": int(row["orders"] or 0),
                    "quantity": round(_number(row["quantity"]), 2),
                }
                for row in top_channels
            ],
        }

    return sales_evidence
