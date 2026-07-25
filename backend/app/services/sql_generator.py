from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.model_client import chat_completion
from app.services.schema_linker import link_schema


_SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_DANGEROUS_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke|call|exec|execute|load|outfile|infile|sleep|benchmark)\b",
    re.IGNORECASE,
)


def _slim_table(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": table.get("name"),
        "physical_table": table.get("physical_table"),
        "description": table.get("description"),
        "grain": table.get("grain"),
        "columns": [
            {
                "name": column.get("name"),
                "type": column.get("type"),
                "description": column.get("description"),
                "aliases": column.get("aliases", []),
            }
            for column in table.get("columns", [])
        ],
    }


def _slim_metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": metric.get("name"),
        "aliases": metric.get("aliases", []),
        "description": metric.get("description"),
        "formula": metric.get("formula"),
        "filters": metric.get("filters", []),
        "default_time_field": metric.get("default_time_field"),
    }


def _slim_example(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": example.get("question"),
        "sql": example.get("sql"),
    }


def _build_prompt(schema_context: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "question": schema_context["question"],
        "intents": schema_context.get("intents", []),
        "tables": [_slim_table(table) for table in schema_context.get("tables", [])],
        "metrics": [_slim_metric(metric) for metric in schema_context.get("metrics", [])],
        "business_terms": schema_context.get("business_terms", []),
        "relationships": schema_context.get("relationships", []),
        "examples": [_slim_example(example) for example in schema_context.get("examples", [])],
        "guardrails": schema_context.get("guardrails", []),
    }
    system = """你是企业 BI Text-to-SQL 助手，只负责生成 MySQL 8.0 的只读 SQL。

必须遵守：
1. 只输出一个 SELECT 查询，不要解释，不要 Markdown。
2. 只能使用提供的表、字段、指标和关系。
3. 中文表名、中文字段名必须用反引号。
4. 表名必须带 schema 前缀，例如 ods.`销售单明细账`。
5. 默认销售额使用 ods.`销售单明细账`.`分摊后金额`。
6. 售后退货、售后发货进入销售指标，不要默认过滤。
7. 订单头“销售单查询”使用 dwd.`销售单查询_进口超市上海仓补全`，不要使用 ods 原始订单头表。
8. 不确定时优先生成保守、可执行的聚合 SQL。
"""
    user = "请基于以下剪枝后的语义上下文生成 SQL：\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_repair_prompt(
    schema_context: dict[str, Any],
    failed_sql: str,
    error_message: str,
) -> list[dict[str, str]]:
    payload = {
        "question": schema_context["question"],
        "tables": [_slim_table(table) for table in schema_context.get("tables", [])],
        "metrics": [_slim_metric(metric) for metric in schema_context.get("metrics", [])],
        "relationships": schema_context.get("relationships", []),
        "examples": [_slim_example(example) for example in schema_context.get("examples", [])],
        "failed_sql": failed_sql,
        "error_message": error_message[:2000],
        "guardrails": schema_context.get("guardrails", []),
    }
    system = """你是 MySQL SQL 修复助手。请根据原问题、可用 schema、失败 SQL 和错误信息修复查询。

必须遵守：
1. 只输出一个修复后的 SELECT 查询，不要解释，不要 Markdown。
2. 只能使用提供的表、字段、指标和关系。
3. 中文表名、中文字段名必须用反引号。
4. 表名必须带 schema 前缀，例如 ods.`销售单明细账`。
5. 不要使用写入、DDL、存储过程、临时表或多语句。
6. 订单头“销售单查询”使用 dwd.`销售单查询_进口超市上海仓补全`。
"""
    user = "请修复以下 SQL：\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def extract_sql(model_output: str) -> str:
    text = model_output.strip()
    block = _SQL_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()
    text = text.strip().rstrip(";").strip()
    return text + ";"


def validate_readonly_sql(sql: str) -> list[str]:
    errors: list[str] = []
    compact = sql.strip()
    lowered = compact.lower()
    if not lowered.startswith("select"):
        errors.append("SQL 必须以 SELECT 开头。")
    if ";" in compact.rstrip(";"):
        errors.append("SQL 只能包含一条语句。")
    if _DANGEROUS_RE.search(compact):
        errors.append("SQL 包含非只读或高风险关键字。")
    if "ods." not in compact and "dwd." not in compact:
        errors.append("SQL 表名必须带 ods 或 dwd schema 前缀。")
    return errors


def generate_sql(db: Session, question: str, top_k_tables: int = 5, top_k_examples: int = 3) -> dict[str, Any]:
    schema_context = link_schema(question, top_k_tables=top_k_tables, top_k_examples=top_k_examples)
    messages = _build_prompt(schema_context)
    raw_output = chat_completion(db, messages, max_tokens=1200)
    sql = extract_sql(raw_output)
    safety_errors = validate_readonly_sql(sql)
    return {
        "question": question.strip(),
        "sql": sql,
        "safety_passed": not safety_errors,
        "safety_errors": safety_errors,
        "raw_output": raw_output,
        "schema_context": schema_context,
    }
