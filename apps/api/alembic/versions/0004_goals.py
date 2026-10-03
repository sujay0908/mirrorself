"""Sprint 4 goals — goals + goal_events.

Goals belong to a Twin (and transitively to a user). GoalEvent rows are an
append-only audit log for the goal lifecycle.

Status transition policy lives in `app.goal.service.GoalService`, not in the
DB. The CHECK constraint just enforces that `status` is one of the four
MVP values.

Revision ID: 0004_goals
Revises: 0003_memory_retrieval
Create Date: 2026-10-03
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_goals"
down_revision: str | Sequence[str] | None = "0003_memory_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "twin_id",
            sa.Uuid(),
            sa.ForeignKey("twins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata_json",
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
            "status IN ('active','achieved','abandoned','paused')",
            name="goals_status_check",
        ),
        sa.CheckConstraint(
            "priority >= 1 AND priority <= 5",
            name="goals_priority_check",
        ),
    )
    op.create_index("ix_goals_twin_status", "goals", ["twin_id", "status"])

    op.create_table(
        "goal_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "goal_id",
            sa.Uuid(),
            sa.ForeignKey("goals.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "event_type IN ('created','updated','status_changed')",
            name="goal_events_type_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("goal_events")
    op.drop_index("ix_goals_twin_status", table_name="goals")
    op.drop_table("goals")
