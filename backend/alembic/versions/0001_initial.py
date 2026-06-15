"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("is_public", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("is_onboarded", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("face_photo_path", sa.String(512), nullable=True),
        sa.Column("voice_sample_path", sa.String(512), nullable=True),
        sa.Column("voice_id", sa.String(128), nullable=True, index=True),
        sa.Column("avatar_video_path", sa.String(512), nullable=True),
        sa.Column("twin_status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("personality", postgresql.JSONB, nullable=True),
        sa.Column("conversation_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("is_public", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("detected_emotion", sa.String(32), nullable=True),
        sa.Column("response_tone", sa.String(32), nullable=True),
        sa.Column("audio_path", sa.String(512), nullable=True),
        sa.Column("video_path", sa.String(512), nullable=True),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "facts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, server_default="0.7", nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_facts_user_id", "facts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_facts_user_id", table_name="facts")
    op.drop_table("facts")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("users")
