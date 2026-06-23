"""add supabase auth linkage

Revision ID: 0002_supabase_auth
Revises: 0001_initial
Create Date: 2026-06-22 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_supabase_auth"
down_revision: Union[str, None] = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("supabase_user_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_users_supabase_user_id"), "users", ["supabase_user_id"], unique=True)
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=False)
    op.drop_index(op.f("ix_users_supabase_user_id"), table_name="users")
    op.drop_column("users", "supabase_user_id")
