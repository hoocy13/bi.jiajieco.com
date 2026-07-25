from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import settings


logger = logging.getLogger("uvicorn.error")


@dataclass
class RequestPerformance:
    request_id: str
    method: str
    path: str
    db_query_count: int = 0
    db_duration_ms: float = 0
    slow_query_count: int = 0
    database_query_counts: dict[str, int] = field(default_factory=dict)
    database_duration_ms: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_query(self, database: str, duration_ms: float) -> None:
        with self._lock:
            self.db_query_count += 1
            self.db_duration_ms += duration_ms
            self.database_query_counts[database] = self.database_query_counts.get(database, 0) + 1
            self.database_duration_ms[database] = self.database_duration_ms.get(database, 0) + duration_ms
            if duration_ms >= settings.PERFORMANCE_SLOW_QUERY_MS:
                self.slow_query_count += 1


_request_performance: ContextVar[RequestPerformance | None] = ContextVar(
    "request_performance",
    default=None,
)


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and len(supplied) <= 128 and all(character.isalnum() or character in "-_." for character in supplied):
        return supplied
    return uuid4().hex


def _statement_fingerprint(statement: str) -> str:
    normalized = " ".join(statement.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _record_query(database: str, started_at: float | None, statement: str, failed: bool = False) -> None:
    if started_at is None:
        return

    duration_ms = max(0, (perf_counter() - started_at) * 1000)
    performance = _request_performance.get()
    if performance is None:
        return

    performance.record_query(database, duration_ms)
    if duration_ms >= settings.PERFORMANCE_SLOW_QUERY_MS:
        logger.warning(
            "slow_sql request_id=%s method=%s path=%s database=%s duration_ms=%.1f fingerprint=%s failed=%s",
            performance.request_id,
            performance.method,
            performance.path,
            database,
            duration_ms,
            _statement_fingerprint(statement),
            str(failed).lower(),
        )


def register_engine_performance(engine: Engine | None, database: str) -> None:
    if engine is None or getattr(engine, "_jjc_performance_registered", False):
        return

    setattr(engine, "_jjc_performance_registered", True)

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        context: object,
        _executemany: bool,
    ) -> None:
        setattr(context, "_jjc_query_started_at", perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        context: object,
        _executemany: bool,
    ) -> None:
        _record_query(database, getattr(context, "_jjc_query_started_at", None), statement)

    @event.listens_for(engine, "handle_error")
    def handle_error(exception_context: object) -> None:
        execution_context = getattr(exception_context, "execution_context", None)
        statement = getattr(exception_context, "statement", None) or ""
        started_at = getattr(execution_context, "_jjc_query_started_at", None)
        _record_query(database, started_at, statement, failed=True)


async def performance_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = _request_id(request)
    performance = RequestPerformance(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    token: Token[RequestPerformance | None] = _request_performance.set(performance)
    started_at = perf_counter()

    try:
        response = await call_next(request)
        total_duration_ms = max(0, (perf_counter() - started_at) * 1000)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{total_duration_ms:.1f}"
        response.headers["X-DB-Query-Count"] = str(performance.db_query_count)
        response.headers["X-DB-Time-Ms"] = f"{performance.db_duration_ms:.1f}"
        response.headers["X-DB-Slow-Query-Count"] = str(performance.slow_query_count)
        response.headers["X-ODS-Query-Count"] = str(performance.database_query_counts.get("ods", 0))
        response.headers["X-ODS-Time-Ms"] = f'{performance.database_duration_ms.get("ods", 0):.1f}'
        response.headers["X-ADS-Query-Count"] = str(performance.database_query_counts.get("ads", 0))
        response.headers["X-ADS-Time-Ms"] = f'{performance.database_duration_ms.get("ads", 0):.1f}'
        response.headers["Server-Timing"] = (
            f'app;dur={total_duration_ms:.1f}, '
            f'db;dur={performance.db_duration_ms:.1f};desc="{performance.db_query_count} queries"'
        )

        log = logger.info if settings.PERFORMANCE_LOG_ALL_REQUESTS else logger.warning
        if settings.PERFORMANCE_LOG_ALL_REQUESTS or total_duration_ms >= settings.PERFORMANCE_SLOW_REQUEST_MS:
            log(
                "request_performance request_id=%s method=%s path=%s status=%s "
                "total_ms=%.1f db_ms=%.1f db_queries=%s slow_queries=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                total_duration_ms,
                performance.db_duration_ms,
                performance.db_query_count,
                performance.slow_query_count,
            )
        return response
    finally:
        _request_performance.reset(token)
