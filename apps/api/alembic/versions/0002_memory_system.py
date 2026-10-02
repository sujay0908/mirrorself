"""Sprint 2 memory system — memories, memory_sources, memory_embeddings,
memory_candidates.

The embedding vector is stored as JSON for Sprint 2. A later migration
replaces the Postgres column with `pgvector` once Sprint 3 wires retrieval
and the production target dimension is pinned.

Revision ID: 0002_memory_system
Revises: 0001_initial
Create Date: 2026-10-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_memory_system"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False,
                  server_default=sa.text("1.0")),
        sa.Column("importance", sa.Float(), nullable=False,
                  server_default=sa.text("0.5")),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')",
            name="memories_type_check",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="memories_confidence_check",
        ),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="memories_importance_check",
        ),
    )
    op.create_index(
        "ix_memories_twin_created",
        "memories",
        ["twin_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_memories_twin_type",
        "memories",
        ["twin_id", "type"],
    )

    op.create_table(
        "memory_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_metadata", sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source_type IN ('message','user_edit','import')",
            name="memory_sources_type_check",
        ),
    )

    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "memory_id", "embedding_model",
            name="uq_memory_embedding_model",
        ),
        sa.CheckConstraint(
            "embedding_dimensions > 0",
            name="memory_embeddings_dims_check",
        ),
    )

    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False,
                  server_default=sa.text("0.5")),
        sa.Column("importance", sa.Float(), nullable=False,
                  server_default=sa.text("0.5")),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "source_conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column(
            "resulting_memory_id",
            sa.Uuid(),
            sa.ForeignKey("memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')",
            name="memory_candidates_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','rejected','expired')",
            name="memory_candidates_status_check",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="memory_candidates_confidence_check",
        ),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="memory_candidates_importance_check",
        ),
    )
    op.create_index(
        "ix_memory_candidates_twin_status_created",
        "memory_candidates",
        ["twin_id", "status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_candidates_twin_status_created",
        table_name="memory_candidates",
    )
    op.drop_table("memory_candidates")
    op.drop_table("memory_embeddings")
    op.drop_table("memory_sources")
    op.drop_index("ix_memories_twin_type", table_name="memories")
    op.drop_index("ix_memories_twin_created", table_name="memories")
    op.drop_table("memories")
