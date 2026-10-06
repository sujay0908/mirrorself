"""Sprint 8 — Evolving Twin Loop.

Three structural additions:

1. `memories.confirmed_at` — immutable timestamp of the moment a
   candidate was confirmed into a durable Memory. The reflection
   opportunity policy counts "new confirmed memories since the last
   successful reflection run" against this column. Backfilled for
   existing rows via `COALESCE(last_confirmed_at, created_at)` where
   `user_confirmed = TRUE`.

2. `twins.last_reflection_run_at` — timestamp of the last successful
   scheduled reflection run. Written inside the same transaction as
   `ReflectionService.create_candidates` so a failed run never
   advances it. NULL for twins that have never run reflection.

3. New tables:
   - `twin_evolution_events` — the record of durable, user-authorized
     changes that took effect. Written only after a successful apply.
     See `docs/architecture/evolving-twin-loop.md`.
   - `intent_telemetry_events` — safe-metadata-only intent telemetry.
     No message content.

Revision ID: 0006_evolving_twin_loop
Revises: 0005_reflection
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_evolving_twin_loop"
down_revision: str | Sequence[str] | None = "0005_reflection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- memories.confirmed_at ----
    op.add_column(
        "memories",
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_memories_confirmed_at",
        "memories",
        ["confirmed_at"],
    )
    # Backfill: for every memory the user already confirmed, we can
    # safely use `last_confirmed_at` (set at candidate_confirm time)
    # or, failing that, `created_at`. Either represents the historical
    # confirmation moment within the fidelity of pre-Sprint-8 data.
    op.execute(
        """
        UPDATE memories
           SET confirmed_at = COALESCE(last_confirmed_at, created_at)
         WHERE user_confirmed = TRUE
           AND confirmed_at IS NULL
        """
    )

    # ---- twins.last_reflection_run_at ----
    op.add_column(
        "twins",
        sa.Column(
            "last_reflection_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ---- twin_evolution_events ----
    op.create_table(
        "twin_evolution_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "reflection_id",
            sa.Uuid(),
            sa.ForeignKey("reflection_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "memory_id",
            sa.Uuid(),
            sa.ForeignKey("memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "goal_id",
            sa.Uuid(),
            sa.ForeignKey("goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("profile_field", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'memory_learned','memory_consolidated','goal_updated',"
            "'profile_confirmed','insight_acknowledged'"
            ")",
            name="twin_evolution_events_type_check",
        ),
    )
    op.create_index(
        "ix_twin_evolution_events_twin_created",
        "twin_evolution_events",
        ["twin_id", "created_at"],
    )

    # ---- intent_telemetry_events ----
    op.create_table(
        "intent_telemetry_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("detector_name", sa.String(length=64), nullable=False),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("message_length_bucket", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="intent_telemetry_confidence_check",
        ),
        sa.CheckConstraint(
            "message_length_bucket IN ('short','medium','long')",
            name="intent_telemetry_bucket_check",
        ),
    )
    op.create_index(
        "ix_intent_telemetry_twin_created",
        "intent_telemetry_events",
        ["twin_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intent_telemetry_twin_created",
        table_name="intent_telemetry_events",
    )
    op.drop_table("intent_telemetry_events")
    op.drop_index(
        "ix_twin_evolution_events_twin_created",
        table_name="twin_evolution_events",
    )
    op.drop_table("twin_evolution_events")
    op.drop_column("twins", "last_reflection_run_at")
    op.drop_index("ix_memories_confirmed_at", table_name="memories")
    op.drop_column("memories", "confirmed_at")
