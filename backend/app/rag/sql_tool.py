from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.ods import OdsSessionLocal
from app.services.text_to_sql_agent import ask_text_to_sql


class SqlProvider(Protocol):
    def execute(self, question: str) -> dict[str, Any]: ...


class ExistingTextToSqlProvider:
    def __init__(
        self,
        admin_db: Session,
        ods_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.admin_db = admin_db
        self.ods_session_factory = ods_session_factory or OdsSessionLocal
        if self.ods_session_factory is None:
            raise RuntimeError("ODS database is not configured for Text-to-SQL")

    def execute(self, question: str) -> dict[str, Any]:
        with self.ods_session_factory() as ods_db:
            result = ask_text_to_sql(
                db=self.admin_db,
                ods_db=ods_db,
                question=question,
                top_k_tables=5,
                top_k_examples=3,
                max_rows=settings.RAG_SQL_MAX_ROWS,
                max_retries=1,
                include_schema_context=False,
            )
        if result.get("failed"):
            return {
                "tool": "text_to_sql",
                "source": "ods",
                "parameters": {
                    "max_rows": settings.RAG_SQL_MAX_ROWS,
                    "timeout_ms": settings.RAG_SQL_TIMEOUT_MS,
                },
                "data": {
                    "status": "failed",
                    "sql": result.get("sql"),
                    "error": result.get("error"),
                    "attempts": result.get("attempts") or [],
                },
            }
        return {
            "tool": "text_to_sql",
            "source": "ods",
            "parameters": {
                "max_rows": result["max_rows"],
                "timeout_ms": result["timeout_ms"],
            },
            "data": {
                "status": "completed",
                "sql": result["sql"],
                "tables": result["tables"],
                "columns": result["columns"],
                "rows": result["rows"][:20],
                "row_count": result["row_count"],
                "limited": result["limited"],
                "attempts": result["attempts"],
            },
        }


def _display_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def format_sql_answer(result: dict[str, Any]) -> str:
    data = result["data"]
    if data["status"] != "completed":
        return (
            "只读 SQL 未能安全执行。"
            f"原因：{data.get('error') or '生成或校验失败'}"
        )
    rows = data["rows"]
    if not rows:
        return (
            "只读 SQL 已安全执行，但当前条件下没有返回数据。"
            f"\n\n执行 SQL：\n```sql\n{data['sql']}\n```"
        )
    columns = data["columns"]
    preview = rows[:10]
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| "
        + " | ".join(_display_value(row.get(column)) for column in columns)
        + " |"
        for row in preview
    ]
    suffix = (
        f"\n\n共返回 {data['row_count']} 行，以上展示前 {len(preview)} 行。"
        if data["row_count"] > len(preview)
        else f"\n\n共返回 {data['row_count']} 行。"
    )
    return (
        "查询结果：\n\n"
        + "\n".join([header, divider, *body])
        + suffix
        + f"\n\n执行 SQL：\n```sql\n{data['sql']}\n```"
    )
