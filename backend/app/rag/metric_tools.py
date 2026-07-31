from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re
from typing import Any, Protocol

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.routers.inventory import inventory_brand_turnover
from app.api.routers.sales import sales_overview
from app.core.config import settings
from app.db.ods import OdsSessionLocal


class MetricProvider(Protocol):
    def execute(self, question: str) -> dict[str, Any]: ...


class UnsupportedMetricError(ValueError):
    pass


@dataclass(frozen=True)
class MetricQuery:
    tool: str
    range_key: str = "last_30"
    start_date: date | None = None
    end_date: date | None = None
    year: int | None = None
    quarter: int | None = None
    brand: str = ""
    min_stock: int = 100
    warehouses: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ("正装", "小样")


def _extract_brand(question: str) -> str:
    quoted = re.search(r"[“\"]([^”\"]{1,30})[”\"]", question)
    if quoted:
        return quoted.group(1).strip()
    after_brand = re.search(
        r"品牌(?:为|是|：|:)?\s*([\u4e00-\u9fffA-Za-z0-9·&\-]{1,30})",
        question,
    )
    if after_brand:
        value = re.split(r"(?:的)?(?:周转|库存|情况|数据)", after_brand.group(1))[0]
        return value.strip()
    before_brand = re.search(
        r"([\u4e00-\u9fffA-Za-z0-9·&\-]{1,30})品牌(?:的)?(?:周转|库存)",
        question,
    )
    if before_brand:
        value = before_brand.group(1)
        for prefix in ("查询", "查看", "分析", "请查", "请看", "帮我看"):
            if value.startswith(prefix):
                value = value[len(prefix) :]
        return value.strip()
    return ""


def parse_metric_query(question: str) -> MetricQuery:
    normalized = " ".join(question.strip().split())
    if "周转" not in normalized:
        if not any(
            marker in normalized
            for marker in ("销售", "订单", "客单价")
        ):
            raise UnsupportedMetricError(
                "当前只支持销售概览和品牌周转指标"
            )
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", normalized)
        if len(dates) >= 2:
            return MetricQuery(
                tool="sales_overview",
                range_key="custom",
                start_date=date.fromisoformat(dates[0]),
                end_date=date.fromisoformat(dates[1]),
            )
        if "本月" in normalized:
            range_key = "this_month"
        elif "本年" in normalized or "今年" in normalized:
            range_key = "this_year"
        else:
            range_key = "last_30"
        return MetricQuery(tool="sales_overview", range_key=range_key)

    period = re.search(
        r"(\d{4})\s*年?\s*[Qq第]?\s*([1-4])\s*(?:季度?)?",
        normalized,
    )
    min_stock_match = re.search(
        r"(?:库存|可用库存)(?:不少于|大于等于|至少)\s*(\d+)",
        normalized,
    )
    mentions_full_size = "正装" in normalized
    mentions_sample = "小样" in normalized
    product_types = (
        ("正装", "小样")
        if mentions_full_size == mentions_sample
        else (("正装",) if mentions_full_size else ("小样",))
    )
    return MetricQuery(
        tool="brand_turnover",
        year=int(period.group(1)) if period else None,
        quarter=int(period.group(2)) if period else None,
        brand=_extract_brand(normalized),
        min_stock=int(min_stock_match.group(1)) if min_stock_match else 100,
        product_types=product_types,
    )


def _set_read_only(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "mysql":
        db.execute(text("SET TRANSACTION READ ONLY"))


def _metric_parameters(query: MetricQuery) -> dict:
    values = asdict(query)
    values["start_date"] = query.start_date.isoformat() if query.start_date else None
    values["end_date"] = query.end_date.isoformat() if query.end_date else None
    values["warehouses"] = list(query.warehouses)
    values["product_types"] = list(query.product_types)
    return values


class ExistingBiMetricProvider:
    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.session_factory = session_factory or OdsSessionLocal
        if self.session_factory is None:
            raise RuntimeError("ODS database is not configured for RAG metric tools")

    def execute(self, question: str) -> dict[str, Any]:
        query = parse_metric_query(question)
        response = Response()
        with self.session_factory() as db:
            _set_read_only(db)
            if query.tool == "sales_overview":
                payload = sales_overview(
                    response=response,
                    range=query.range_key,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    current_user=None,
                    db=db,
                )["data"]
                compact_data = {
                    "as_of": payload["as_of"],
                    "period": payload["period"],
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                    "metrics": payload["metrics"],
                    "channels": payload["channels"][:5],
                }
            else:
                payload = inventory_brand_turnover(
                    response=response,
                    year=query.year,
                    quarter=query.quarter,
                    keyword=query.brand,
                    min_stock=query.min_stock,
                    warehouse=list(query.warehouses) or None,
                    product_type=list(query.product_types),
                    page=1,
                    page_size=50,
                    current_user=None,
                    db=db,
                )["data"]
                compact_data = {
                    "period": payload["period"],
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                    "snapshot_at": payload["snapshot_at"],
                    "basis": payload["basis"],
                    "summary": payload["summary"],
                    "rows": payload["chart_rows"][:5],
                }
        return {
            "tool": query.tool,
            "source": response.headers.get("X-BI-Response-Source", settings.BI_QUERY_SOURCE),
            "parameters": _metric_parameters(query),
            "data": compact_data,
        }


def format_metric_answer(result: dict[str, Any]) -> str:
    data = result["data"]
    if result["tool"] == "sales_overview":
        metrics = data["metrics"]
        return (
            f"{data['start_date']} 至 {data['end_date']}："
            f"销售额 {float(metrics['paid_amount']):,.2f} 元，"
            f"订单数 {int(metrics['orders']):,} 单，"
            f"销售数量 {int(metrics['quantity']):,} 件，"
            f"平均客单价 {float(metrics['avg_order_amount']):,.2f} 元。"
            f"数据截至 {data['as_of']}，来源为 {result['source'].upper()} 只读查询。"
        )

    summary = data["summary"]
    parameters = result["parameters"]
    brand = parameters.get("brand")
    rows = data.get("rows") or []
    if brand and rows:
        row = next((item for item in rows if item["brand"] == brand), rows[0])
        turnover = (
            f"{float(row['turnover_days']):,.1f} 天"
            if row["turnover_days"] is not None
            else "无法计算"
        )
        return (
            f"{data['period']}，品牌“{row['brand']}”可用库存 "
            f"{float(row['available_stock']):,.0f} 件，净销售数量 "
            f"{float(row['net_sales_quantity']):,.0f} 件，估算周转天数为 "
            f"{turnover}，状态为“{row['status']}”。库存快照日期为 "
            f"{data['snapshot_at'] or '未知'}，来源为 {result['source'].upper()} 只读查询。"
        )
    turnover = (
        f"{float(summary['turnover_days']):,.1f} 天"
        if summary["turnover_days"] is not None
        else "无法计算"
    )
    return (
        f"{data['period']} 在当前筛选下共有 {int(summary['brand_count']):,} 个品牌，"
        f"可用库存 {float(summary['available_stock']):,.0f} 件，净销售数量 "
        f"{float(summary['net_sales_quantity']):,.0f} 件，整体估算周转天数为 "
        f"{turnover}，需关注品牌 {int(summary['attention_brands']):,} 个。"
        f"库存快照日期为 {data['snapshot_at'] or '未知'}，"
        f"来源为 {result['source'].upper()} 只读查询。"
    )
