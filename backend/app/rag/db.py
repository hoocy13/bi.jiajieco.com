from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class RagBase(DeclarativeBase):
    pass


@lru_cache
def get_rag_engine() -> Engine:
    if not settings.RAG_DATABASE_URL:
        raise RuntimeError("RAG_DATABASE_URL is not configured")
    return create_engine(
        settings.RAG_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
    )


@lru_cache
def get_rag_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=get_rag_engine(),
    )


def get_rag_db() -> Generator[Session, None, None]:
    db = get_rag_session_factory()()
    try:
        yield db
    finally:
        db.close()
