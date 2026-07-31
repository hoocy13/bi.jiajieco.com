from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embeddings import EmbeddingProvider
from app.rag.models import RagKnowledgeBase
from app.rag.vector_store import QdrantKnowledgeStore


def search_knowledge(
    db: Session,
    question: str,
    roles: list[str],
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantKnowledgeStore,
    *,
    limit: int | None = None,
) -> list[dict]:
    knowledge_base = db.scalar(
        select(RagKnowledgeBase).where(
            RagKnowledgeBase.name == settings.RAG_KNOWLEDGE_BASE_NAME,
            RagKnowledgeBase.status == "active",
        )
    )
    if knowledge_base is None:
        return []
    vector = embedding_provider.embed_query(question.strip())
    return vector_store.search(
        vector,
        knowledge_base_id=knowledge_base.id,
        roles=roles,
        limit=limit or settings.RAG_SEARCH_TOP_K,
    )
