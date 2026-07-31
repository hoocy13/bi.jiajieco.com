from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Iterable

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.core.config import settings
from app.services.schema_linker import load_metadata


DEFAULT_ALLOWED_TABLES = frozenset(
    {
        "ods.销售单明细账",
        "dwd.销售单查询_进口超市上海仓补全",
        "ods.总库存查询",
        "ods.分仓库查询",
        "ods.批次货品库存查询",
        "ods.渠道列表",
    }
)
_BLOCKED_FUNCTIONS = frozenset(
    {
        "benchmark",
        "get_lock",
        "is_free_lock",
        "is_used_lock",
        "load_file",
        "master_pos_wait",
        "release_lock",
        "sleep",
        "sys_exec",
        "sys_eval",
    }
)
_VARIABLE_RE = re.compile(r"(?<![\w])@@?[A-Za-z_]")


@dataclass(frozen=True)
class SafeSql:
    sql: str
    tables: tuple[str, ...]
    max_rows: int
    limit_rewritten: bool


class SqlSafetyError(ValueError):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(dict.fromkeys(errors))
        super().__init__("；".join(self.errors))


def _qualified_table(table: exp.Table) -> str:
    return f"{table.db}.{table.name}"


@lru_cache(maxsize=1)
def _allowed_column_names() -> frozenset[str]:
    return frozenset(
        str(column.get("name", "")).casefold()
        for table in load_metadata().get("tables", [])
        for column in table.get("columns", [])
        if column.get("name")
    )


def inspect_sql(
    sql: str,
    *,
    allowed_tables: Iterable[str] = DEFAULT_ALLOWED_TABLES,
    max_joins: int | None = None,
) -> tuple[exp.Query | None, list[str], tuple[str, ...]]:
    errors: list[str] = []
    try:
        statements = [item for item in parse(sql, read="mysql") if item is not None]
    except ParseError:
        return None, ["SQL 语法无法解析。"], ()
    if len(statements) != 1:
        return None, ["SQL 只能包含一条语句。"], ()

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        errors.append("SQL 只允许 SELECT 或 WITH 查询。")
    if list(statement.find_all(exp.Into)):
        errors.append("SQL 禁止 SELECT INTO。")
    if list(statement.find_all(exp.Lock)):
        errors.append("SQL 禁止 FOR UPDATE 或共享锁。")
    if _VARIABLE_RE.search(sql):
        errors.append("SQL 禁止访问或设置数据库会话变量。")
    unsafe_stars = [
        star
        for star in statement.find_all(exp.Star)
        if not isinstance(star.parent, exp.Count)
    ]
    if unsafe_stars:
        errors.append("SQL 禁止 SELECT *，必须显式选择已审核字段。")

    blocked_functions = sorted(
        {
            function.name.lower()
            for function in statement.find_all(exp.Func)
            if function.name and function.name.lower() in _BLOCKED_FUNCTIONS
        }
    )
    if blocked_functions:
        errors.append(
            "SQL 包含禁止函数：" + ", ".join(blocked_functions)
        )

    join_limit = max_joins if max_joins is not None else settings.RAG_SQL_MAX_JOINS
    if len(list(statement.find_all(exp.Join))) > join_limit:
        errors.append(f"SQL 关联表数量不能超过 {join_limit} 个。")

    cte_names = {
        cte.alias_or_name.casefold()
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }
    allowed = {item.casefold() for item in allowed_tables}
    tables: list[str] = []
    for table in statement.find_all(exp.Table):
        if not table.db and table.name.casefold() in cte_names:
            continue
        if table.catalog:
            errors.append("SQL 禁止跨 catalog 查询。")
            continue
        if not table.db:
            errors.append(f"表 {table.name} 必须带 ods 或 dwd schema 前缀。")
            continue
        qualified = _qualified_table(table)
        tables.append(qualified)
        if qualified.casefold() not in allowed:
            errors.append(f"表 {qualified} 不在只读白名单中。")
    if not tables:
        errors.append("SQL 必须查询至少一张白名单业务表。")

    allowed_columns = _allowed_column_names()
    projection_aliases = {
        alias.alias.casefold()
        for alias in statement.find_all(exp.Alias)
        if alias.alias
    }
    unknown_columns = sorted(
        {
            column.name
            for column in statement.find_all(exp.Column)
            if column.name
            and column.name.casefold() not in allowed_columns
            and column.name.casefold() not in projection_aliases
        }
    )
    if unknown_columns:
        errors.append(
            "SQL 包含未审核字段：" + "、".join(unknown_columns)
        )

    return (
        statement if isinstance(statement, exp.Query) else None,
        list(dict.fromkeys(errors)),
        tuple(dict.fromkeys(tables)),
    )


def validate_sql(
    sql: str,
    *,
    allowed_tables: Iterable[str] = DEFAULT_ALLOWED_TABLES,
    max_joins: int | None = None,
) -> list[str]:
    _, errors, _ = inspect_sql(
        sql,
        allowed_tables=allowed_tables,
        max_joins=max_joins,
    )
    return errors


def prepare_safe_sql(
    sql: str,
    max_rows: int,
    *,
    allowed_tables: Iterable[str] = DEFAULT_ALLOWED_TABLES,
    max_joins: int | None = None,
) -> SafeSql:
    effective_max_rows = max(1, min(max_rows, settings.RAG_SQL_MAX_ROWS))
    statement, errors, tables = inspect_sql(
        sql,
        allowed_tables=allowed_tables,
        max_joins=max_joins,
    )
    if errors or statement is None:
        raise SqlSafetyError(errors or ["SQL 未通过安全检查。"])

    limit_rewritten = False
    limit = statement.args.get("limit")
    current_limit: int | None = None
    if limit is not None:
        expression = limit.args.get("expression")
        if isinstance(expression, exp.Literal) and expression.is_int:
            current_limit = int(expression.this)
    if current_limit is None or current_limit > effective_max_rows:
        statement.set(
            "limit",
            exp.Limit(expression=exp.Literal.number(effective_max_rows)),
        )
        limit_rewritten = True

    return SafeSql(
        sql=statement.sql(dialect="mysql", identify=True) + ";",
        tables=tables,
        max_rows=effective_max_rows,
        limit_rewritten=limit_rewritten,
    )
