"""Idempotent chat sends and an index for the conversation list.

Two additive changes. No existing column, row or constraint is altered.

1. `messages.client_request_id` (nullable) with a partial unique index on
   `(conversation_id, client_request_id)`. A send that carries an
   Idempotency-Key writes it here; a retry of the same send finds the row
   and returns the original exchange instead of creating a second turn.
   Rows written before this migration, and sends without a key, hold NULL
   and are outside the index.

2. `ix_conversations_twin_updated` on `(twin_id, updated_at)`. The
   conversation list reads one twin's rows, most recently active first;
   this serves it as an index range scan instead of a sort.

Transcript reads (the newest N messages of one conversation) need
`(conversation_id, created_at)` on `messages`. That index has existed since
0001 as `ix_messages_conversation_created`, so nothing is created for it
here; the ORM model now declares it so the model and the schema agree.

Index builds here are plain `CREATE INDEX`, which blocks writes to the table
while it runs. That is the right trade at current table sizes (a build is
milliseconds); a table large enough for it to matter needs
`CREATE INDEX CONCURRENTLY` outside a transaction instead.

`lock_timeout` bounds the wait for the table locks so a deploy fails fast
rather than queueing behind a long transaction and stalling every request
to the table behind it.

Revision ID: 0008_message_idempotency
Revises: 0007_chat_time_learning_ack
Create Date: 2026-11-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_message_idempotency"
down_revision: str | Sequence[str] | None = "0007_chat_time_learning_ack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDEMPOTENCY_INDEX = "uq_messages_conversation_client_request"
_CONVERSATIONS_INDEX = "ix_conversations_twin_updated"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '15s'")

    op.add_column(
        "messages",
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        _IDEMPOTENCY_INDEX,
        "messages",
        ["conversation_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
        sqlite_where=sa.text("client_request_id IS NOT NULL"),
    )
    op.create_index(_CONVERSATIONS_INDEX, "conversations", ["twin_id", "updated_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '15s'")

    op.drop_index(_CONVERSATIONS_INDEX, table_name="conversations")
    op.drop_index(_IDEMPOTENCY_INDEX, table_name="messages")
    # Dropping the column discards the stored request ids. The messages
    # themselves are untouched; only replay-by-key for past sends is lost.
    op.drop_column("messages", "client_request_id")
