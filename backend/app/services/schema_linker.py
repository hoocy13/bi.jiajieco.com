from __future__ import annotations

import re
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_CANCEL_STATUS_FILTER = "订单状态 not in ('已取消', '已取消-被合并', '已取消-被拆分')"


@dataclass(frozen=True)
class ScoredItem:
    score: int
    data: dict[str, Any]
    reasons: tuple[str, ...]


def _metadata_path() -> Path:
    env_path = os.getenv("TEXT_TO_SQL_METADATA_PATH")
    candidates = [
        Path(env_path) if env_path else None,
        Path(__file__).resolve().parents[1] / "resources" / "text-to-sql-ods-sales-metadata.yaml",
        Path(__file__).resolve().parents[3] / "docs" / "text-to-sql-ods-sales-metadata.yaml",
        Path.cwd() / "docs" / "text-to-sql-ods-sales-metadata.yaml",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    checked = ", ".join(str(candidate) for candidate in candidates if candidate)
    raise FileNotFoundError(f"Text-to-SQL metadata file not found. Checked: {checked}")


@lru_cache(maxsize=1)
def load_metadata() -> dict[str, Any]:
    with _metadata_path().open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_as_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_as_text(item) for item in value.values())
    return str(value)


def _tokens(text: str) -> set[str]:
    tokens = {token.lower() for token in _TOKEN_RE.findall(text or "")}
    chars = {char for char in text if "\u4e00" <= char <= "\u9fff"}
    return tokens | chars


def _contains(text: str, keyword: str) -> bool:
    return bool(keyword) and keyword.lower() in text.lower()


def _compact(text: str) -> str:
    return re.sub(r"\W+", "", text or "", flags=re.UNICODE).lower()


def _score_text(question: str, question_tokens: set[str], payload: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    name = _as_text(payload.get("name") or payload.get("term") or payload.get("question"))
    aliases = payload.get("aliases") or []
    description = _as_text(payload.get("description"))

    if _contains(question, name):
        score += 40
        reasons.append(f"命中名称：{name}")
    elif name and (_compact(question) in _compact(name) or _compact(name) in _compact(question)):
        score += 32
        reasons.append(f"近似命中名称：{name}")

    for alias in aliases:
        alias_text = _as_text(alias)
        if _contains(question, alias_text):
            score += 35
            reasons.append(f"命中别名：{alias_text}")

    text_tokens = _tokens(" ".join([name, _as_text(aliases), description]))
    overlap = sorted(question_tokens & text_tokens)
    if overlap:
        overlap_score = min(len(overlap) * 3, 24)
        score += overlap_score
        reasons.append("词面相关：" + "、".join(overlap[:8]))

    return score, reasons


def _infer_intents(question: str) -> list[str]:
    intents: list[str] = []
    checks = [
        ("销售分析", ("销售", "成交", "金额", "GMV", "gmv", "销量", "毛利", "订单")),
        ("商品分析", ("商品", "货品", "SKU", "sku", "品牌", "品类", "排行", "排名")),
        ("渠道分析", ("渠道", "店铺", "平台", "线上")),
        ("库存分析", ("库存", "可用库存", "仓库", "周转", "滞销", "缺货", "在途")),
        ("效期分析", ("效期", "到期", "过期", "批次", "保质期", "剩余有效")),
        ("时间趋势", ("每天", "每日", "每月", "月份", "趋势", "环比", "同比", "近", "今年", "上月", "昨天")),
    ]
    for intent, keywords in checks:
        if any(keyword in question for keyword in keywords):
            intents.append(intent)
    return intents or ["通用查询"]


def _rank_metrics(metadata: dict[str, Any], question: str, question_tokens: set[str]) -> list[ScoredItem]:
    scored: list[ScoredItem] = []
    for metric in metadata.get("metrics", []):
        score, reasons = _score_text(question, question_tokens, metric)
        formula = _as_text(metric.get("formula"))
        if any(keyword in question for keyword in ("销售", "成交", "金额", "GMV", "gmv")) and metric.get("name") == "销售额":
            score += 35
            reasons.append("默认销售额口径")
        if any(keyword in question for keyword in ("销量", "件数", "数量")) and "数量" in formula:
            score += 25
            reasons.append("问题需要数量类指标")
        if "毛利" in question and "毛利" in metric.get("name", ""):
            score += 35
            reasons.append("问题需要毛利指标")
        if "库存" in question and "库存" in metric.get("name", ""):
            score += 35
            reasons.append("问题需要库存指标")
        if any(keyword in question for keyword in ("销售", "销量", "毛利", "成交")) and "库存" not in question and "库存" in metric.get("name", ""):
            score -= 40
            reasons.append("纯销售问题降低库存指标优先级")
        if score > 0:
            scored.append(ScoredItem(score, metric, tuple(reasons)))
    return sorted(scored, key=lambda item: item.score, reverse=True)


def _rank_terms(metadata: dict[str, Any], question: str, question_tokens: set[str]) -> list[ScoredItem]:
    scored: list[ScoredItem] = []
    for term in metadata.get("business_terms", []):
        score, reasons = _score_text(question, question_tokens, term)
        if score > 0:
            scored.append(ScoredItem(score, term, tuple(reasons)))
    return sorted(scored, key=lambda item: item.score, reverse=True)


def _table_metric_bonus(table_name: str, metrics: list[ScoredItem]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for item in metrics:
        formula_text = _as_text(item.data.get("formula"))
        time_field_text = _as_text(item.data.get("default_time_field"))
        if table_name in formula_text or table_name in time_field_text:
            score += 30
            reasons.append(f"承载指标：{item.data.get('name')}")
    return score, reasons


def _rank_tables(
    metadata: dict[str, Any],
    question: str,
    question_tokens: set[str],
    metrics: list[ScoredItem],
) -> list[ScoredItem]:
    scored: list[ScoredItem] = []
    for table in metadata.get("tables", []):
        score, reasons = _score_text(question, question_tokens, table)
        metric_score, metric_reasons = _table_metric_bonus(table.get("name", ""), metrics)
        score += metric_score
        reasons.extend(metric_reasons)

        column_hits = []
        for column in table.get("columns", []):
            column_score, column_reasons = _score_text(question, question_tokens, column)
            if column_score > 0:
                score += min(column_score, 28)
                column_hits.append(column.get("name"))
        if column_hits:
            reasons.append("命中字段：" + "、".join(column_hits[:8]))

        name = table.get("name", "")
        if any(keyword in question for keyword in ("销售", "销量", "毛利", "品牌", "品类", "商品", "货品")) and name == "销售单明细账":
            score += 35
            reasons.append("明细账适合销售、商品、品牌、品类分析")
        if any(keyword in question for keyword in ("订单", "实付", "订单状态")) and name == "销售单查询":
            score += 30
            reasons.append("订单头适合订单状态与实付金额分析")
        if any(keyword in question for keyword in ("库存", "可用库存", "滞销")) and name in {"总库存查询", "分仓库查询"}:
            score += 35
            reasons.append("库存类问题优先召回库存表")
        if any(keyword in question for keyword in ("批次", "效期", "到期", "保质期", "剩余有效")) and name == "批次货品库存查询":
            score += 120
            reasons.append("效期/批次问题优先召回批次库存")
        if any(keyword in question for keyword in ("效期", "到期", "保质期", "剩余有效")) and name != "批次货品库存查询":
            score -= 45
            reasons.append("效期问题降低非批次表优先级")
        if any(keyword in question for keyword in ("销售", "销量", "毛利", "成交")) and "库存" not in question and name in {"总库存查询", "分仓库查询", "批次货品库存查询"}:
            score -= 55
            reasons.append("纯销售问题降低库存表优先级")

        if score > 0:
            scored.append(ScoredItem(score, table, tuple(reasons)))
    return sorted(scored, key=lambda item: item.score, reverse=True)


def _rank_columns(question: str, question_tokens: set[str], tables: list[ScoredItem], metrics: list[ScoredItem]) -> list[dict[str, Any]]:
    metric_text = " ".join(_as_text(metric.data) for metric in metrics)
    columns: list[ScoredItem] = []
    for table_item in tables:
        table = table_item.data
        table_name = table.get("name", "")
        for column in table.get("columns", []):
            score, reasons = _score_text(question, question_tokens, column)
            column_ref = f"{table_name}.{column.get('name')}"
            if column_ref in metric_text or column.get("name") in metric_text:
                score += 22
                reasons.append("指标公式相关字段")
            if score > 0:
                payload = dict(column)
                payload["table"] = table_name
                payload["ref"] = column_ref
                columns.append(ScoredItem(score, payload, tuple(reasons)))
    ranked = sorted(columns, key=lambda item: item.score, reverse=True)
    return [_serialize(item) for item in ranked[:24]]


def _rank_examples(metadata: dict[str, Any], question: str, question_tokens: set[str]) -> list[ScoredItem]:
    scored: list[ScoredItem] = []
    for example in metadata.get("query_examples", []):
        score, reasons = _score_text(question, question_tokens, example)
        sql = _as_text(example.get("sql"))
        if "销售单明细账" in sql and any(keyword in question for keyword in ("销售", "销量", "品牌", "商品", "货品")):
            score += 20
            reasons.append("示例使用销售明细账")
        if "总库存查询" in sql and "库存" in question:
            score += 20
            reasons.append("示例使用库存表")
        if "批次货品库存查询" in sql and any(keyword in question for keyword in ("效期", "到期", "保质期", "剩余有效")):
            score += 60
            reasons.append("示例使用批次效期表")
        if score > 0:
            scored.append(ScoredItem(score, example, tuple(reasons)))
    return sorted(scored, key=lambda item: item.score, reverse=True)


def _required_joins(tables: list[ScoredItem], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    selected = {item.data.get("name") for item in tables}
    joins = []
    for rel in metadata.get("relationships", []):
        left = _as_text(rel.get("from")).split(".")[0]
        right = _as_text(rel.get("to")).split(".")[0]
        if left in selected and right in selected:
            joins.append(rel)
    return joins


def _serialize(item: ScoredItem) -> dict[str, Any]:
    data = dict(item.data)
    data["score"] = item.score
    data["reasons"] = list(dict.fromkeys(item.reasons))
    return data


def link_schema(question: str, top_k_tables: int = 5, top_k_examples: int = 3) -> dict[str, Any]:
    clean_question = question.strip()
    metadata = load_metadata()
    question_tokens = _tokens(clean_question)

    metrics = _rank_metrics(metadata, clean_question, question_tokens)
    terms = _rank_terms(metadata, clean_question, question_tokens)
    tables = _rank_tables(metadata, clean_question, question_tokens, metrics)
    selected_tables = tables[:top_k_tables]
    examples = _rank_examples(metadata, clean_question, question_tokens)

    guardrails = [
        "仅生成 SELECT 查询。",
        "默认销售额使用 ods.`销售单明细账`.`分摊后金额`。",
        "售后退货、售后发货进入销售指标。",
        f"涉及订单头有效订单时使用过滤：{_CANCEL_STATUS_FILTER}。",
        "所有中文表名和字段名在 MySQL 中必须使用反引号。",
    ]

    return {
        "question": clean_question,
        "domain": metadata.get("domain"),
        "intents": _infer_intents(clean_question),
        "tables": [_serialize(item) for item in selected_tables],
        "columns": _rank_columns(clean_question, question_tokens, selected_tables, metrics[:5]),
        "metrics": [_serialize(item) for item in metrics[:8]],
        "business_terms": [_serialize(item) for item in terms[:8]],
        "relationships": _required_joins(selected_tables, metadata),
        "examples": [_serialize(item) for item in examples[:top_k_examples]],
        "guardrails": guardrails,
    }
