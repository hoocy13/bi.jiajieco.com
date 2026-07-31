from __future__ import annotations

from typing import Literal
import re


RagIntent = Literal["knowledge", "metric", "sql", "mixed"]

_SQL_MARKERS = (
    "sql",
    "查询语句",
    "写查询",
    "字段名",
    "表结构",
    "哪张表",
)
_SQL_ANALYSIS_MARKERS = (
    "明细",
    "前10",
    "前 10",
    "top",
    "排行",
    "排名",
    "按品牌",
    "按商品",
    "按货品",
    "按渠道",
    "按仓库",
    "每天",
    "每日",
    "每月",
    "分组",
    "列出",
)
_METRIC_MARKERS = (
    "多少",
    "销售额",
    "销售情况",
    "销售数据",
    "库存量",
    "库存情况",
    "到货量",
    "排名",
    "趋势",
    "同比",
    "环比",
    "本月",
    "本周",
    "今天",
    "昨日",
    "截至",
)
_KNOWLEDGE_MARKERS = (
    "为什么",
    "是什么",
    "什么意思",
    "怎么定义",
    "如何计算",
    "口径",
    "规则",
    "默认",
    "区别",
    "来源",
)


def route_question(question: str) -> RagIntent:
    normalized = question.strip().lower()
    has_sql = requires_sql(question)
    has_knowledge = any(marker in normalized for marker in _KNOWLEDGE_MARKERS)
    has_metric = any(marker in normalized for marker in _METRIC_MARKERS) or (
        "周转" in normalized and not has_knowledge
    )
    if has_sql and has_knowledge:
        return "mixed"
    if has_metric and has_knowledge:
        return "mixed"
    if has_sql:
        return "sql"
    if has_metric:
        return "metric"
    return "knowledge"


def requires_sql(question: str) -> bool:
    normalized = question.strip().lower()
    return any(marker in normalized for marker in (*_SQL_MARKERS, *_SQL_ANALYSIS_MARKERS))


def knowledge_part_of_mixed_question(question: str) -> str:
    clauses = [
        clause.strip()
        for clause in re.split(r"[，,；;。！？!?]+", question)
        if clause.strip()
    ]
    knowledge_clauses = [
        clause
        for clause in clauses
        if any(marker in clause.lower() for marker in _KNOWLEDGE_MARKERS)
    ]
    return "；".join(knowledge_clauses) or question.strip()
