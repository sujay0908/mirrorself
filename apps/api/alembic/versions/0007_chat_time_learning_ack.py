"""Sprint 10 — Chat-time Learning Acknowledgement.

Two structural additions that give the chat path a deterministic,
exactly-once way to surface confirmed Twin-evolution events as a
"learning" chip on the next reply:

1. `twin_evolution_events.seq` — a monotonic, gap-tolerant ordering key
   drawn from a dedicated Postgres sequence at INSERT time (see
   `EvolutionService.record`). It replaces the `(created_at, id)`
   composite cursor that an earlier design used: `created_at` is
   `transaction_timestamp()` (set at the writer's BEGIN, not at commit),
   so it is not a reliable ordering key under concurrent, out-of-order
   commits. A sequence value is drawn at INSERT; paired with a per-twin
   advisory lock in `record()` (so commit order matches draw order per
   twin), `seq` gives a stable "surface each event exactly once" cursor.

2. `twins.last_acknowledged_evolution_seq` — the high-water mark of the
   last evolution event surfaced to the user in chat. `0` means nothing
   acknowledged yet; every real event has `seq >= 1`, so a fresh twin
   surfaces all of its post-creation events. The chat ack path advances
   this inside the SAME transaction that persists the twin message, so
   "the user saw the chip" and "the cursor advanced" are atomic.

Migration-boundary guarantee
----------------------------
The `seq` column is added and backfilled under `ACCESS EXCLUSIVE` on
`twin_evolution_events`. That lock drains any in-flight writer (it must
commit or roll back before the ALTER proceeds) and blocks new INSERTs
until this migration commits. Every pre-existing event therefore gets a
`seq` in `[1, N]`, each twin's cursor is pinned to its own `MAX(seq)`,
and any post-migration INSERT draws `seq > N` from the sequence — so no
pre-Sprint-10 event is ever surfaced and no post-migration event is
skipped, even one whose writer transaction began before the migration
and commits after it.

`lock_timeout`/`statement_timeout` are set LOCAL to this migration's
transaction as defense-in-depth: if an unexpected lock holder is present
the migration fails fast and cleanly (and the schema is untouched,
because it runs in one transaction) instead of blocking the cluster.

Revision ID: 0007_chat_time_learning_ack
Revises: 0006_evolving_twin_loop
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_chat_time_learning_ack"
down_revision: str | Sequence[str] | None = "0006_evolving_twin_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEQ_NAME = "twin_evolution_events_seq"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # The test harness builds its schema from the ORM models via
        # Base.metadata.create_all (see tests/conftest.py), never from
        # Alembic. This migration therefore only ever runs against
        # Postgres in dev/prod. Guard so a stray non-Postgres invocation
        # is a clear no-op rather than a confusing syntax error.
        raise RuntimeError(
            "0007_chat_time_learning_ack targets PostgreSQL only; "
            f"got dialect {bind.dialect.name!r}."
        )

    # Defense-in-depth: bound how long we will wait for locks / run.
    op.execute("SET LOCAL lock_timeout = '15s'")
    op.execute("SET LOCAL statement_timeout = '120s'")

    # Lock ORDER matters. Every owner-scoped request in the app loads its
    # twin first (TwinService.require_by_user → AccessShare on `twins`)
    # and only then reads/writes `twin_evolution_events` (always via
    # EvolutionService, with the twin already loaded — there is no code
    # path that touches `twin_evolution_events` before `twins`, and no
    # FOR UPDATE / LOCK on `twins` anywhere). So the global lock order is
    # twins → twin_evolution_events. This migration MUST acquire its
    # ACCESS EXCLUSIVE locks in that SAME order, or it deadlocks with any
    # concurrent chat / confirm request: a request holding AccessShare on
    # `twins` and waiting for `twin_evolution_events` would wait on us
    # while we (holding `twin_evolution_events`) waited on its `twins`
    # lock. Taking `twins` FIRST removes that cycle entirely.
    op.execute("LOCK TABLE twins IN ACCESS EXCLUSIVE MODE")

    # Then drain in-flight event writers and block new INSERTs for the
    # duration of this transaction, so the backfill observes exactly the
    # pre-Sprint-10 universe and every later INSERT draws a strictly
    # greater seq.
    op.execute("LOCK TABLE twin_evolution_events IN ACCESS EXCLUSIVE MODE")

    # Dedicated sequence owned by the seq column.
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {_SEQ_NAME} AS BIGINT START 1")

    # Add the column nullable, backfill, then enforce NOT NULL.
    op.add_column(
        "twin_evolution_events",
        sa.Column("seq", sa.BigInteger(), nullable=True),
    )
    # Deterministic historical order: oldest first by (created_at, id).
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   row_number() OVER (ORDER BY created_at, id) AS rn
            FROM twin_evolution_events
        )
        UPDATE twin_evolution_events e
           SET seq = ordered.rn
          FROM ordered
         WHERE ordered.id = e.id
        """
    )
    # Advance the sequence so the next nextval() is strictly greater than
    # every backfilled value (N+1 for N existing rows, 1 for an empty
    # table). is_called=false → the given value is what nextval() returns.
    op.execute(
        f"""
        SELECT setval(
            '{_SEQ_NAME}',
            (SELECT COALESCE(MAX(seq), 0) FROM twin_evolution_events) + 1,
            false
        )
        """
    )
    op.execute("ALTER SEQUENCE " + _SEQ_NAME + " OWNED BY twin_evolution_events.seq")
    op.alter_column("twin_evolution_events", "seq", nullable=False)
    op.create_unique_constraint(
        "uq_twin_evolution_events_seq",
        "twin_evolution_events",
        ["seq"],
    )
    op.create_index(
        "ix_twin_evolution_events_twin_seq",
        "twin_evolution_events",
        ["twin_id", "seq"],
    )

    # twins.last_acknowledged_evolution_seq — 0 = nothing acknowledged.
    op.add_column(
        "twins",
        sa.Column(
            "last_acknowledged_evolution_seq",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Pin each twin's cursor to the ceiling of its own pre-existing
    # events, so historical events are never re-surfaced as "learning".
    op.execute(
        """
        UPDATE twins t
           SET last_acknowledged_evolution_seq = sub.max_seq
          FROM (
                SELECT twin_id, MAX(seq) AS max_seq
                  FROM twin_evolution_events
              GROUP BY twin_id
          ) AS sub
         WHERE sub.twin_id = t.id
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "0007_chat_time_learning_ack targets PostgreSQL only; "
            f"got dialect {bind.dialect.name!r}."
        )
    op.drop_column("twins", "last_acknowledged_evolution_seq")
    op.drop_index(
        "ix_twin_evolution_events_twin_seq",
        table_name="twin_evolution_events",
    )
    op.drop_constraint(
        "uq_twin_evolution_events_seq",
        "twin_evolution_events",
        type_="unique",
    )
    # Dropping the column drops the sequence too (OWNED BY), but be
    # explicit so a re-run after a partial failure is clean.
    op.drop_column("twin_evolution_events", "seq")
    op.execute(f"DROP SEQUENCE IF EXISTS {_SEQ_NAME}")
