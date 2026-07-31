"""create RAG control-plane tables

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rag_knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("allowed_roles", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["rag_knowledge_bases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "stable_id",
            name="uq_rag_document_stable_id",
        ),
    )
    op.create_index("ix_rag_documents_source_path", "rag_documents", ["source_path"])
    op.create_index("ix_rag_documents_status", "rag_documents", ["status"])

    op.create_table(
        "rag_document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["rag_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version",
            name="uq_rag_document_version",
        ),
    )
    op.create_index(
        "ix_rag_document_versions_status",
        "rag_document_versions",
        ["status"],
    )

    op.create_table(
        "rag_ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["rag_document_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_ingestion_jobs_status", "rag_ingestion_jobs", ["status"])

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="新会话"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_conversations_user_updated",
        "rag_conversations",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "rag_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["rag_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_runs_status", "rag_runs", ["status"])
    op.create_index(
        "ix_rag_runs_conversation_created",
        "rag_runs",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "rag_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["rag_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["rag_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_messages_conversation_created",
        "rag_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "rag_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["rag_document_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["rag_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_rag_citation_ordinal"),
    )

    op.create_table(
        "rag_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_rag_feedback_rating"),
        sa.ForeignKeyConstraint(["run_id"], ["rag_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "user_id", name="uq_rag_feedback_run_user"),
    )


def downgrade() -> None:
    op.drop_table("rag_feedback")
    op.drop_table("rag_citations")
    op.drop_index("ix_rag_messages_conversation_created", table_name="rag_messages")
    op.drop_table("rag_messages")
    op.drop_index("ix_rag_runs_conversation_created", table_name="rag_runs")
    op.drop_index("ix_rag_runs_status", table_name="rag_runs")
    op.drop_table("rag_runs")
    op.drop_index("ix_rag_conversations_user_updated", table_name="rag_conversations")
    op.drop_table("rag_conversations")
    op.drop_index("ix_rag_ingestion_jobs_status", table_name="rag_ingestion_jobs")
    op.drop_table("rag_ingestion_jobs")
    op.drop_index("ix_rag_document_versions_status", table_name="rag_document_versions")
    op.drop_table("rag_document_versions")
    op.drop_index("ix_rag_documents_status", table_name="rag_documents")
    op.drop_index("ix_rag_documents_source_path", table_name="rag_documents")
    op.drop_table("rag_documents")
    op.drop_table("rag_knowledge_bases")
