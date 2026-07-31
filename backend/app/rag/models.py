from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.rag.db import RagBase


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RagKnowledgeBase(TimestampMixin, RagBase):
    __tablename__ = "rag_knowledge_bases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")


class RagDocument(TimestampMixin, RagBase):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "stable_id",
            name="uq_rag_document_stable_id",
        ),
        Index("ix_rag_documents_source_path", "source_path"),
        Index("ix_rag_documents_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_knowledge_bases.id", ondelete="CASCADE")
    )
    stable_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    source_path: Mapped[str] = mapped_column(String(1024))
    allowed_roles: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="active")


class RagDocumentVersion(TimestampMixin, RagBase):
    __tablename__ = "rag_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_rag_document_version"),
        Index("ix_rag_document_versions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagIngestionJob(TimestampMixin, RagBase):
    __tablename__ = "rag_ingestion_jobs"
    __table_args__ = (Index("ix_rag_ingestion_jobs_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_document_versions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagConversation(TimestampMixin, RagBase):
    __tablename__ = "rag_conversations"
    __table_args__ = (
        Index("ix_rag_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(String(32), default="active")


class RagRun(TimestampMixin, RagBase):
    __tablename__ = "rag_runs"
    __table_args__ = (
        Index("ix_rag_runs_status", "status"),
        Index("ix_rag_runs_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[list[dict]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagMessage(RagBase):
    __tablename__ = "rag_messages"
    __table_args__ = (
        Index("ix_rag_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="CASCADE")
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class RagCitation(RagBase):
    __tablename__ = "rag_citations"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_rag_citation_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="CASCADE")
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_document_versions.id", ondelete="SET NULL")
    )
    chunk_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512))
    section_path: Mapped[list[str]] = mapped_column(JSON)
    source_path: Mapped[str] = mapped_column(String(1024))
    quote: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class RagFeedback(RagBase):
    __tablename__ = "rag_feedback"
    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="ck_rag_feedback_rating"),
        UniqueConstraint("run_id", "user_id", name="uq_rag_feedback_run_user"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(Integer)
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
