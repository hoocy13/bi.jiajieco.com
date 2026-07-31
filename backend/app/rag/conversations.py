from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.rag.embeddings import EmbeddingProvider
from app.rag.llm import ChatModel
from app.rag.metric_tools import MetricProvider
from app.rag.sql_tool import SqlProvider
from app.rag.models import (
    RagCitation,
    RagConversation,
    RagDocumentVersion,
    RagMessage,
    RagRun,
)
from app.rag.permissions import rag_role_for_user
from app.rag.vector_store import QdrantKnowledgeStore
from app.rag.workflow import build_knowledge_graph


class ConversationNotFoundError(LookupError):
    pass


def get_user_conversation(
    db: Session,
    conversation_id: UUID,
    user_id: int,
) -> RagConversation:
    conversation = db.scalar(
        select(RagConversation).where(
            RagConversation.id == conversation_id,
            RagConversation.user_id == user_id,
            RagConversation.status == "active",
        )
    )
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


def create_conversation(
    db: Session,
    user: User,
    title: str | None = None,
) -> RagConversation:
    conversation = RagConversation(
        user_id=user.id,
        username=user.username,
        title=(title or "新会话").strip()[:255] or "新会话",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def execute_run(
    db: Session,
    conversation: RagConversation,
    user: User,
    question: str,
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantKnowledgeStore,
    chat_model: ChatModel,
    metric_provider: MetricProvider | None = None,
    sql_provider: SqlProvider | None = None,
) -> RagRun:
    normalized_question = " ".join(question.strip().split())
    run = RagRun(
        conversation_id=conversation.id,
        user_id=user.id,
        question=normalized_question,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    run_id = run.id
    db.add(
        RagMessage(
            conversation_id=conversation.id,
            run_id=run.id,
            role="user",
            content=normalized_question,
        )
    )
    if conversation.title == "新会话":
        conversation.title = normalized_question[:30]
    conversation.updated_at = datetime.now(UTC)
    db.commit()

    try:
        graph = build_knowledge_graph(
            db,
            embedding_provider,
            vector_store,
            chat_model,
            metric_provider,
            sql_provider,
        )
        result: dict[str, Any] = graph.invoke(
            {
                "question": normalized_question,
                "roles": [rag_role_for_user(user)],
                "warnings": [],
            }
        )
        run.intent = result["intent"]
        run.trace = [
            {
                "node": "route_intent",
                "intent": result["intent"],
            },
            {
                "node": "retrieve_knowledge",
                "result_count": len(result.get("evidence") or []),
            },
            *[
                {
                    "node": "metric_tool",
                    "tool": item["tool"],
                    "source": item["source"],
                    "parameters": item["parameters"],
                    "result": item["data"],
                }
                for item in (result.get("tool_results") or [])
            ],
            {
                "node": "compose_answer",
                "warnings": result.get("warnings") or [],
            },
        ]
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        db.add(
            RagMessage(
                conversation_id=conversation.id,
                run_id=run.id,
                role="assistant",
                content=result["answer"],
            )
        )
        evidence = result.get("evidence") or []
        referenced_ordinals = {
            int(value)
            for value in re.findall(r"\[(\d+)\]", result["answer"])
            if 1 <= int(value) <= len(evidence)
        }
        for ordinal, item in enumerate(evidence, start=1):
            if ordinal not in referenced_ordinals:
                continue
            version_id = item.get("document_version_id")
            db.add(
                RagCitation(
                    run_id=run.id,
                    document_version_id=UUID(version_id) if version_id else None,
                    chunk_id=item.get("chunk_id"),
                    title=item.get("title") or "未命名知识",
                    section_path=item.get("section_path") or [],
                    source_path=item.get("source_path") or "",
                    quote=(item.get("content") or "")[:1000] or None,
                    ordinal=ordinal,
                )
            )
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        failed_run = db.get(RagRun, run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.error_code = type(exc).__name__
            failed_run.error_message = str(exc)[:2000]
            failed_run.finished_at = datetime.now(UTC)
            db.commit()
        raise


def citation_payload(db: Session, citation: RagCitation) -> dict:
    version = (
        db.get(RagDocumentVersion, citation.document_version_id)
        if citation.document_version_id
        else None
    )
    return {
        "ordinal": citation.ordinal,
        "title": citation.title,
        "section_path": citation.section_path,
        "source_path": citation.source_path,
        "quote": citation.quote,
        "document_version": version.version if version else None,
        "document_version_id": (
            str(citation.document_version_id)
            if citation.document_version_id
            else None
        ),
        "chunk_id": citation.chunk_id,
    }
