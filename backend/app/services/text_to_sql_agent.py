from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.model_client import chat_completion
from app.services.schema_linker import link_schema
from app.services.sql_generator import build_repair_prompt, extract_sql, generate_sql, validate_readonly_sql
from app.services.sql_safety import prepare_safe_sql


import re


_TRANSIENT_DB_ERROR_RE = re.compile(
    r"timed out|can't connect|lost connection|connection reset|server has gone away",
    re.IGNORECASE,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def ensure_limit(sql: str, max_rows: int) -> str:
    return prepare_safe_sql(sql, max_rows).sql


def execute_readonly_sql(
    ods_db: Session,
    sql: str,
    max_rows: int,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    safe = prepare_safe_sql(sql, max_rows)
    effective_timeout = max(
        1000,
        min(timeout_ms or settings.RAG_SQL_TIMEOUT_MS, settings.RAG_SQL_TIMEOUT_MS),
    )
    try:
        if ods_db.bind is not None and ods_db.bind.dialect.name == "mysql":
            ods_db.execute(text("SET TRANSACTION READ ONLY"))
            ods_db.execute(
                text(f"SET SESSION MAX_EXECUTION_TIME={effective_timeout}")
            )
        rows = ods_db.execute(text(safe.sql)).mappings().all()
        result_rows = [
            {key: _json_value(value) for key, value in row.items()}
            for row in rows[: safe.max_rows]
        ]
        columns = list(result_rows[0].keys()) if result_rows else []
        return {
            "sql": safe.sql,
            "tables": list(safe.tables),
            "columns": columns,
            "rows": result_rows,
            "row_count": len(result_rows),
            "limited": safe.limit_rewritten,
            "max_rows": safe.max_rows,
            "timeout_ms": effective_timeout,
        }
    finally:
        ods_db.rollback()


def _repair_sql(
    db: Session,
    schema_context: dict[str, Any],
    failed_sql: str,
    error_message: str,
) -> str:
    raw_output = chat_completion(
        db,
        build_repair_prompt(schema_context, failed_sql, error_message),
        max_tokens=1200,
    )
    return extract_sql(raw_output)


def _should_retry_same_sql(error_message: str) -> bool:
    return bool(_TRANSIENT_DB_ERROR_RE.search(error_message))


def ask_text_to_sql(
    db: Session,
    ods_db: Session,
    question: str,
    top_k_tables: int = 5,
    top_k_examples: int = 3,
    max_rows: int = 200,
    max_retries: int = 2,
    include_schema_context: bool = False,
) -> dict[str, Any]:
    generated = generate_sql(db, question, top_k_tables=top_k_tables, top_k_examples=top_k_examples)
    schema_context = generated["schema_context"]
    attempts: list[dict[str, Any]] = []
    sql = generated["sql"]

    for attempt_index in range(max_retries + 1):
        safety_errors = validate_readonly_sql(sql)
        if safety_errors:
            error_message = "；".join(safety_errors)
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "sql": sql,
                    "success": False,
                    "stage": "safety",
                    "error": error_message,
                }
            )
        else:
            try:
                execution = execute_readonly_sql(ods_db, sql, max_rows)
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "sql": execution["sql"],
                        "success": True,
                        "stage": "execute",
                        "row_count": execution["row_count"],
                    }
                )
                result = {
                    "question": question.strip(),
                    "sql": execution["sql"],
                    "tables": execution["tables"],
                    "columns": execution["columns"],
                    "rows": execution["rows"],
                    "row_count": execution["row_count"],
                    "limited": execution["limited"],
                    "max_rows": execution["max_rows"],
                    "timeout_ms": execution["timeout_ms"],
                    "attempts": attempts,
                }
                if include_schema_context:
                    result["schema_context"] = schema_context
                return result
            except (SQLAlchemyError, ValueError) as exc:
                error_message = str(exc)
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "sql": sql,
                        "success": False,
                        "stage": "execute",
                        "error": error_message[:2000],
                    }
                )

        if attempt_index >= max_retries:
            break
        if _should_retry_same_sql(attempts[-1]["error"]):
            continue
        repaired_sql = _repair_sql(db, schema_context, sql, attempts[-1]["error"])
        if validate_readonly_sql(repaired_sql):
            attempts.append(
                {
                    "attempt": f"{attempt_index + 1}.repair",
                    "sql": repaired_sql,
                    "success": False,
                    "stage": "repair",
                    "error": "模型修复结果未通过安全检查，继续使用上一条 SQL 重试。",
                }
            )
            continue
        sql = repaired_sql

    return {
        "question": question.strip(),
        "sql": sql,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "limited": False,
        "max_rows": max_rows,
        "attempts": attempts,
        "failed": True,
        "error": attempts[-1]["error"] if attempts else "SQL 生成失败",
        "schema_context": schema_context if include_schema_context else None,
    }
