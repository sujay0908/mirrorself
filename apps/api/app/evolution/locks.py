"""Per-twin advisory lock for evolution-event writes and chat-time
acknowledgement (Sprint 10).

Why a *dedicated* namespace, not the Sprint 8.1 reflection-scheduler
key: the reflection scheduler holds its advisory lock across the LLM
extraction call (see `app.reflection.scheduler`). If evolution writes
and the chat ack path reused that key with a BLOCKING acquire, a chat
turn could stall for the full duration of a concurrent reflection LLM
call for the same twin. This namespace is disjoint, so the only thing a
`twin-evolution:` holder waits on is another `twin-evolution:` holder —
i.e. another short, DB-only evolution write or ack for the same twin.

What it guarantees: for one twin, evolution-event writes (and the chat
ack read+advance) run one at a time. Because `record()` draws its `seq`
from the sequence while holding this lock and the lock releases at the
transaction's commit, the commit order of evolution events for a twin
matches their `seq` order — which is what makes "surface each event
exactly once" hold under concurrent, out-of-order commits.

On non-PostgreSQL dialects (SQLite in the test harness) these are
no-ops: SQLite deployments are single-writer by construction, so there
is nothing to serialize, and `seq` is assigned MAX(seq)+1 instead.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.logging import get_logger

logger = get_logger(__name__)

_EVOLUTION_LOCK_NAMESPACE: str = "twin-evolution:"


def evolution_advisory_lock_key(twin_id: uuid.UUID) -> int:
    """Deterministic signed 64-bit advisory-lock key for one twin.

    Same construction as the reflection scheduler's key (SHA-256 over a
    namespaced input, first 8 bytes as a signed int64 so it fits a
    Postgres `bigint`), but under the disjoint `twin-evolution:`
    namespace so the two mechanisms never collide.
    """
    digest = hashlib.sha256((_EVOLUTION_LOCK_NAMESPACE + str(twin_id)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def acquire_twin_evolution_lock(session: AsyncSession, twin_id: uuid.UUID) -> None:
    """Acquire the per-twin evolution advisory lock (BLOCKING).

    - PostgreSQL: `pg_advisory_xact_lock(:key)` — waits until the lock
      is free, then holds it until the current transaction commits or
      rolls back. Reentrant within a transaction (hold count bumps), so
      a caller that already holds it does not deadlock with itself.
    - Other dialects: no-op.

    The caller MUST already have an open transaction (any prior read or
    write started one; AsyncSession autobegins on first use).
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    key = evolution_advisory_lock_key(twin_id)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=key))
