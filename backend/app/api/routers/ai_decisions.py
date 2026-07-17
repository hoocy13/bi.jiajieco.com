import json
from copy import deepcopy
from datetime import datetime, timedelta
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
from app.services.model_client import chat_completion


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
    cache_key = ("inventory-decisions-v3", warehouses)
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
    sales_anchor = ods_db.execute(
        text("SELECT MAX(`下单时间`) FROM `销售单查询` WHERE COALESCE(`订单状态`, '') NOT LIKE '%取消%'")
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
                """
                SELECT
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM `销售单查询`
                WHERE `下单时间` >= :sales_start
                  AND `下单时间` < DATE_ADD(:sales_end, INTERVAL 1 DAY)
                  AND COALESCE(`订单状态`, '') NOT LIKE '%取消%'
                """
            ),
            sales_params,
        ).mappings().one()
        previous_summary = ods_db.execute(
            text(
                """
                SELECT
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM `销售单查询`
                WHERE `下单时间` >= :previous_start
                  AND `下单时间` < DATE_ADD(:previous_end, INTERVAL 1 DAY)
                  AND COALESCE(`订单状态`, '') NOT LIKE '%取消%'
                """
            ),
            sales_params,
        ).mappings().one()
        top_channels = ods_db.execute(
            text(
                """
                SELECT
                  COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
                  SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
                  COUNT(DISTINCT CASE WHEN COALESCE(`货品数量`, 0) > 0 THEN `订单编号` END) AS orders,
                  SUM(COALESCE(`货品数量`, 0)) AS quantity
                FROM `销售单查询`
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
    ai_summary = ""
    ai_status = "ready"
    try:
        ai_summary = chat_completion(
            db,
            [
                {
                    "role": "system",
                    "content": """
你是销售与库存运营策略助手。只能依据用户提供的 JSON 数据判断，不得编造不存在的销售额、订单数、库存、渠道或商品信息。

请输出一份清晰、有条理的经营建议，格式固定为：
一、总体判断：先给结论，再说明影响。要直接指出当前最重要的问题、机会或风险。
二、销售侧：围绕近30天销售额、订单数、销量、客单价、环比变化、TOP渠道表现给出判断。说明哪些渠道值得继续投入，哪些渠道需要复核或调整。
三、库存侧：围绕缺货、负库存、可用库存为零、90天无销量、超储、临期/过期给出判断。说明库存是否能支撑当前销售，以及哪些问题需要优先处理。
四、销售库存联动动作：把销售表现和库存动作连起来，给出可执行建议，例如补货、停止补货、调拨、清货、渠道投放、数据复核。

要求：
- 用中文。
- 不要刻意减少字数，内容要完整，但表达要清楚。
- 每一段先说结论，再说原因或动作。
- 分点输出，每点尽量只表达一个判断，避免长句堆叠。
- 不要使用 Markdown 表格。
- 不要泛泛而谈；建议尽量带上具体指标、渠道、仓库或商品问题。
- 数据不足时，明确说明缺少什么，不要猜测。
""".strip(),
                },
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
            ],
            max_tokens=2000,
        )
    except Exception as exc:
        ai_status = "unavailable"
        ai_summary = f"模型暂不可用，已保留规则决策。原因：{exc}"

    data = {
        "warehouses_selected": list(warehouses),
        "generated_at": datetime.now().isoformat(),
        "ai_status": ai_status,
        "ai_summary": ai_summary,
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
