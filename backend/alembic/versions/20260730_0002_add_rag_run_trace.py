"""add RAG run trace

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_runs",
        sa.Column(
            "trace",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rag_runs", "trace")
