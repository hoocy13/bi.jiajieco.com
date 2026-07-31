from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.rag.db import get_rag_session_factory
from app.rag.embeddings import OpenAICompatibleEmbeddingProvider
from app.rag.ingestion import sync_knowledge_repository
from app.rag.vector_store import QdrantKnowledgeStore


celery_app = Celery(
    "jjc-bi-rag",
    broker=settings.RAG_REDIS_URL or None,
    backend=settings.RAG_CELERY_RESULT_BACKEND or settings.RAG_REDIS_URL or None,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=720,
    task_soft_time_limit=600,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="rag.reindex_knowledge")
def reindex_knowledge_task() -> dict:
    db = get_rag_session_factory()()
    try:
        return sync_knowledge_repository(
            db,
            OpenAICompatibleEmbeddingProvider(),
            QdrantKnowledgeStore(),
        )
    finally:
        db.close()
