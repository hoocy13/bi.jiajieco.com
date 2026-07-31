from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.rag.embeddings import embedding_is_configured


CheckFunction = Callable[[], None]


def _component_status(configured: bool, check: CheckFunction) -> dict[str, Any]:
    if not configured:
        return {
            "configured": False,
            "status": "disabled",
            "latency_ms": None,
        }

    started_at = monotonic()
    try:
        check()
    except Exception as exc:
        return {
            "configured": True,
            "status": "unavailable",
            "latency_ms": round((monotonic() - started_at) * 1000, 2),
            "error": type(exc).__name__,
        }
    return {
        "configured": True,
        "status": "available",
        "latency_ms": round((monotonic() - started_at) * 1000, 2),
    }


def _check_postgresql() -> None:
    engine = create_engine(
        settings.RAG_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        connect_args={"connect_timeout": settings.RAG_CONNECT_TIMEOUT_SECONDS},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _check_redis() -> None:
    client = Redis.from_url(
        settings.RAG_REDIS_URL,
        socket_connect_timeout=settings.RAG_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=settings.RAG_CONNECT_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


def _check_qdrant() -> None:
    client = QdrantClient(
        url=settings.RAG_QDRANT_URL,
        api_key=settings.RAG_QDRANT_API_KEY or None,
        timeout=settings.RAG_CONNECT_TIMEOUT_SECONDS,
    )
    try:
        client.get_collections()
    finally:
        client.close()


def rag_infrastructure_health() -> dict[str, Any]:
    components = {
        "postgresql": _component_status(bool(settings.RAG_DATABASE_URL), _check_postgresql),
        "redis": _component_status(bool(settings.RAG_REDIS_URL), _check_redis),
        "qdrant": _component_status(bool(settings.RAG_QDRANT_URL), _check_qdrant),
    }
    embedding_configured = embedding_is_configured()
    ready = (
        settings.RAG_ENABLED
        and embedding_configured
        and all(component["status"] == "available" for component in components.values())
    )
    return {
        "enabled": settings.RAG_ENABLED,
        "ready": ready,
        "embedding_configured": embedding_configured,
        "components": components,
    }
