"""Sprint 7 reflection — reflection_candidates + memories.superseded_by_memory_id.

Reflection candidates are user-confirmable proposals the Twin's
reflection extractor emits after reading the user's confirmed memories,
active goals and recent conversation turns. See
`docs/architecture/reflection.md` for the design.

This migration also adds a nullable `superseded_by_memory_id` column
to `memories` so confirmed `memory_dedup` reflections can mark a
memory as superseded without ever deleting its content, embeddings or
provenance. Retrieval filters by `superseded_by_memory_id IS NULL`;
the memory list endpoint continues to expose superseded rows so the
user can un-supersede.

No backfill is required: every existing memory row stays as-is with a
NULL supersession pointer.

Revision ID: 0005_reflection
Revises: 0004_goals
Create Date: 2026-10-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_reflection"
down_revision: str | Sequence[str] | None = "0004_goals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column(
            "superseded_by_memory_id",
            sa.Uuid(),
            sa.ForeignKey("memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_memories_superseded_by_memory_id",
        "memories",
        ["superseded_by_memory_id"],
    )

    op.create_table(
        "reflection_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "proposed_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "source_memory_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "source_goal_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "importance",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_error", sa.String(length=255), nullable=True),
        sa.Column(
            "apply_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('profile_update','memory_dedup','goal_update','insight')",
            name="reflection_candidates_kind_check",
        ),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','rejected')",
            name="reflection_candidates_status_check",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="reflection_candidates_confidence_check",
        ),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="reflection_candidates_importance_check",
        ),
    )
    op.create_index(
        "ix_reflection_candidates_twin_status_created",
        "reflection_candidates",
        ["twin_id", "status", "created_at"],
    )
    op.create_index(
        "ix_reflection_candidates_twin_fingerprint",
        "reflection_candidates",
        ["twin_id", "status", "fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reflection_candidates_twin_fingerprint",
        table_name="reflection_candidates",
    )
    op.drop_index(
        "ix_reflection_candidates_twin_status_created",
        table_name="reflection_candidates",
    )
    op.drop_table("reflection_candidates")

    op.drop_index(
        "ix_memories_superseded_by_memory_id", table_name="memories"
    )
    op.drop_column("memories", "superseded_by_memory_id")
