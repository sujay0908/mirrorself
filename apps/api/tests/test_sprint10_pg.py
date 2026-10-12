"""Sprint 10 — PostgreSQL-only guarantees.

SQLite cannot exercise these, so they are gated behind the `postgres`
marker and skipped unless `PAT_TEST_PG_DSN` (a postgresql+asyncpg:// DSN)
is set. Each test provisions its own throwaway database so runs do not
interfere.

Covered:

1. The per-twin evolution advisory lock makes `seq` order equal commit
   order per twin — i.e. the "writer draws seq=41 but commits after a
   writer that drew seq=42" reordering that would permanently skip an
   event CANNOT occur. Uses two independent engines (NullPool) so the
   two writers own distinct backend connections and genuinely race on
   the row/advisory lock.
2. Writers for DIFFERENT twins do not block each other (the lock is
   per-twin, not global).
3. The 0007 migration, run over a seeded 0006 schema, backfills `seq`
   for every pre-existing event, pins each twin's cursor to its own
   MAX(seq), leaves event-less twins at 0, and advances the sequence so
   the next INSERT draws a strictly greater seq (the migration-boundary
   guarantee).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import pathlib
import re
import subprocess
import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Import every model so SQLAlchemy can configure the Twin mapper's
# relationships (Conversation, Goal, …) when we query Twin below.
from app.conversation import models as _conv_models  # noqa: F401
from app.conversation.service import ConversationService
from app.evolution.models import TwinEvolutionEvent
from app.evolution.service import EvolutionService
from app.goal import models as _goal_models  # noqa: F401
from app.memory import models as _mem_models  # noqa: F401
from app.reflection import models as _refl_models  # noqa: F401
from app.telemetry import models as _telemetry_models  # noqa: F401
from app.twin.models import Twin, TwinProfile

_BASE_DSN = os.environ.get("PAT_TEST_PG_DSN")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(_BASE_DSN is None, reason="PAT_TEST_PG_DSN not set"),
]

_SEQ_NAME = "twin_evolution_events_seq"


def _conn_kwargs(*, database: str = "postgres") -> dict[str, object]:
    """asyncpg connection kwargs for a database on the configured server.

    Handles both DSN shapes:
      * unix socket — host/port in the query string
        (postgresql+asyncpg://user@/db?host=/sock/dir&port=5432), used by
        the local test cluster;
      * TCP — host/port/password in the netloc
        (postgresql+asyncpg://user:pw@host:5432/db), used by the CI
        Postgres service.
    """
    assert _BASE_DSN is not None
    parts = urlsplit(_BASE_DSN)
    q = parse_qs(parts.query)
    host = q.get("host", [None])[0] or parts.hostname
    port = int(q.get("port", [str(parts.port or 5432)])[0])
    user = parts.username or "postgres"
    kwargs: dict[str, object] = {
        "host": host,
        "port": port,
        "user": user,
        "database": database,
    }
    if parts.password:
        kwargs["password"] = parts.password
    return kwargs


def _url_for(dbname: str) -> str:
    """SQLAlchemy asyncpg URL for a specific database, preserving the DSN shape."""
    assert _BASE_DSN is not None
    parts = urlsplit(_BASE_DSN)
    q = parse_qs(parts.query)
    user = parts.username or "postgres"
    if q.get("host"):  # unix-socket form
        host = q["host"][0]
        port = q.get("port", ["5432"])[0]
        return f"postgresql+asyncpg://{user}@/{dbname}?host={host}&port={port}"
    # TCP form
    auth = user + (f":{parts.password}" if parts.password else "")
    host = parts.hostname or "localhost"
    port = parts.port or 5432
    return f"postgresql+asyncpg://{auth}@{host}:{port}/{dbname}"


async def _admin(sql: str) -> None:
    import asyncpg  # local import so a missing driver skips cleanly elsewhere

    conn = await asyncpg.connect(**_conn_kwargs())
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def fresh_db() -> AsyncIterator[str]:
    """Create a throwaway database; yield its SQLAlchemy URL; drop it."""
    name = "pat_s10_" + uuid.uuid4().hex[:12]
    await _admin(f'CREATE DATABASE "{name}"')
    try:
        yield _url_for(name)
    finally:
        # Terminate stragglers, then drop.
        await _admin(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
        )
        await _admin(f'DROP DATABASE IF EXISTS "{name}"')


def _alembic(url: str, revision: str, *, direction: str = "upgrade") -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env.setdefault("APP_ENV", "test")
    env.setdefault("LLM_PROVIDER", "mock")
    env.setdefault("LLM_MODEL", "mock-echo")
    proc = subprocess.run(
        ["python3", "-m", "alembic", direction, revision],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"alembic {direction} {revision} failed:\n{proc.stdout}\n{proc.stderr}"
    )


async def _seed_twin(url: str, *, name: str = "Aurora") -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one twin (+ profile). Returns (twin_id, user_id)."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as s:
            user_id = uuid.uuid4()
            twin = Twin(id=uuid.uuid4(), user_id=user_id, display_name=name)
            s.add(twin)
            await s.flush()
            s.add(TwinProfile(twin_id=twin.id, communication_style_preset="neutral"))
            await s.commit()
            return twin.id, user_id
    finally:
        await engine.dispose()


async def test_advisory_lock_makes_seq_order_equal_commit_order(fresh_db):
    """The seq=41/seq=42 out-of-order-commit reordering cannot happen.

    Writer A draws its seq and holds the per-twin advisory lock without
    committing. Writer B (separate connection, same twin) must BLOCK at
    the lock — it cannot draw a seq until A commits. So the writer that
    draws the lower seq is always the one that commits first.
    """
    url = fresh_db
    _alembic(url, "head")
    twin_id, user_id = await _seed_twin(url)

    engine_a = create_async_engine(url, poolclass=NullPool)
    engine_b = create_async_engine(url, poolclass=NullPool)
    try:
        sm_a = async_sessionmaker(engine_a, expire_on_commit=False)
        sm_b = async_sessionmaker(engine_b, expire_on_commit=False)

        session_a = sm_a()
        session_b = sm_b()
        try:
            twin_a = (
                await session_a.execute(select(Twin).where(Twin.id == twin_id))
            ).scalar_one()
            twin_b = (
                await session_b.execute(select(Twin).where(Twin.id == twin_id))
            ).scalar_one()

            # A draws seq + holds the advisory lock (no commit yet).
            row_a = await EvolutionService(session_a).record(
                twin_a, event_type="memory_learned", summary="A"
            )
            seq_a = row_a.seq

            # B tries to record the same twin → must block on the lock.
            b_task = asyncio.create_task(
                EvolutionService(session_b).record(
                    twin_b, event_type="memory_learned", summary="B"
                )
            )
            await asyncio.sleep(0.5)
            assert not b_task.done(), "writer B should be blocked on the per-twin advisory lock"

            # The sequence has only advanced to seq_a — B has not drawn.
            probe_engine = create_async_engine(url, poolclass=NullPool)
            try:
                async with probe_engine.connect() as probe:
                    last = (
                        await probe.execute(text(f"SELECT last_value FROM {_SEQ_NAME}"))
                    ).scalar_one()
            finally:
                await probe_engine.dispose()
            assert last == seq_a

            # Commit A → releases the lock; B unblocks and draws a higher seq.
            await session_a.commit()
            row_b = await asyncio.wait_for(b_task, timeout=5.0)
            await session_b.commit()

            assert row_b.seq > seq_a
            assert row_b.seq == seq_a + 1  # B drew immediately after A, in order
        finally:
            await session_a.close()
            await session_b.close()
    finally:
        await engine_a.dispose()
        await engine_b.dispose()

    # A reader never sees the higher seq without the lower one: both are
    # committed, ordered.
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as c:
            seqs = list(
                (
                    await c.execute(
                        select(TwinEvolutionEvent.seq)
                        .where(TwinEvolutionEvent.twin_id == twin_id)
                        .order_by(TwinEvolutionEvent.seq)
                    )
                ).scalars()
            )
        assert seqs == sorted(seqs)
        assert len(seqs) == 2
    finally:
        await engine.dispose()


async def test_different_twins_do_not_block(fresh_db):
    url = fresh_db
    _alembic(url, "head")
    twin1, _ = await _seed_twin(url, name="T1")
    twin2, _ = await _seed_twin(url, name="T2")

    engine_a = create_async_engine(url, poolclass=NullPool)
    engine_b = create_async_engine(url, poolclass=NullPool)
    try:
        sm_a = async_sessionmaker(engine_a, expire_on_commit=False)
        sm_b = async_sessionmaker(engine_b, expire_on_commit=False)
        async with sm_a() as sa, sm_b() as sb:
            t1 = (await sa.execute(select(Twin).where(Twin.id == twin1))).scalar_one()
            t2 = (await sb.execute(select(Twin).where(Twin.id == twin2))).scalar_one()
            # A holds twin1's lock without committing.
            await EvolutionService(sa).record(t1, event_type="memory_learned", summary="t1")
            # B records twin2 — different lock key → must NOT block.
            row2 = await asyncio.wait_for(
                EvolutionService(sb).record(t2, event_type="memory_learned", summary="t2"),
                timeout=3.0,
            )
            await sb.commit()
            await sa.commit()
            assert row2.seq >= 1
    finally:
        await engine_a.dispose()
        await engine_b.dispose()




async def test_migration_backfills_seq_and_cursor_and_boundary(fresh_db):
    url = fresh_db
    # Bring the schema to the pre-Sprint-10 head.
    _alembic(url, "0006_evolving_twin_loop")

    # Seed two twins; twin1 gets 3 events, twin2 gets 0.
    import asyncpg

    kw = _conn_kwargs()
    dbname = urlsplit(url).path.lstrip("/")
    kw["database"] = dbname
    conn = await asyncpg.connect(**kw)
    try:
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        t1, t2 = uuid.uuid4(), uuid.uuid4()
        for tid, uid, nm in ((t1, u1, "T1"), (t2, u2, "T2")):
            await conn.execute(
                "INSERT INTO twins (id, user_id, display_name, created_at, updated_at) "
                "VALUES ($1,$2,$3, now(), now())",
                tid,
                uid,
                nm,
            )
        ev_ids = [uuid.uuid4() for _ in range(3)]
        for i, eid in enumerate(ev_ids):
            await conn.execute(
                "INSERT INTO twin_evolution_events "
                "(id, user_id, twin_id, event_type, summary, created_at) "
                "VALUES ($1,$2,$3,'memory_learned',$4, now() + ($5 || ' seconds')::interval)",
                eid,
                u1,
                t1,
                f"e{i}",
                str(i),
            )
    finally:
        await conn.close()

    # Apply the Sprint 10 migration.
    _alembic(url, "0007_chat_time_learning_ack")

    conn = await asyncpg.connect(**kw)
    try:
        # Every pre-existing event has a seq in 1..N, ordered by created_at.
        rows = await conn.fetch(
            "SELECT seq FROM twin_evolution_events WHERE twin_id = $1 ORDER BY created_at",
            t1,
        )
        seqs = [r["seq"] for r in rows]
        assert seqs == [1, 2, 3], seqs

        # twin1's cursor pinned to its MAX(seq); twin2 (no events) stays 0.
        c1 = await conn.fetchval(
            "SELECT last_acknowledged_evolution_seq FROM twins WHERE id = $1", t1
        )
        c2 = await conn.fetchval(
            "SELECT last_acknowledged_evolution_seq FROM twins WHERE id = $1", t2
        )
        assert c1 == 3
        assert c2 == 0

        # Boundary: the next sequence draw is strictly greater than N=3,
        # so any post-migration INSERT surfaces (seq > cursor) and no
        # pre-existing event is ever re-surfaced.
        nxt = await conn.fetchval(f"SELECT nextval('{_SEQ_NAME}')")
        assert nxt == 4
    finally:
        await conn.close()


# --------------------------------------------------------------------
# Sprint 10 audit remediation: migration lock-order regression,
# concurrent-chat exactly-once, and downgrade round-trip.
# --------------------------------------------------------------------



def _migration_lock_order() -> list[str]:
    """Extract the ACCESS EXCLUSIVE lock targets, in source order, from the
    0007 migration. Ties the dynamic lock-order test below to the actual
    migration file: if the fix is reverted (events locked first), the
    replay reproduces the deadlock and the test fails."""
    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0007_chat_time_learning_ack.py"
    )
    src = path.read_text()
    return re.findall(
        r"LOCK TABLE (\w+) IN ACCESS EXCLUSIVE MODE",
        src,
    )


async def test_corrected_lock_order_no_deadlock(fresh_db):
    """The migration's lock order (as written in the file) must not
    deadlock with an in-flight chat/confirm request.

    Reader order is always twins → twin_evolution_events (every request
    loads its twin, AccessShare, before touching the event table). We
    replay the migration's two ACCESS EXCLUSIVE locks IN FILE ORDER as
    the migration ("mig") against a chat-like reader ("chat":
    AccessShare twins → AccessShare events), in the exact interleaving
    that deadlocked under the old (events-first) order, and assert no
    deadlock now that twins is locked first.
    """
    url = fresh_db
    _alembic(url, "head")
    twin_id, _ = await _seed_twin(url)

    lock_order = _migration_lock_order()
    assert lock_order[:2] == ["twins", "twin_evolution_events"], (
        f"migration lock order regressed: {lock_order!r} — twins must be locked first"
    )

    import asyncpg

    kw = _conn_kwargs()
    kw["database"] = urlsplit(url).path.lstrip("/")

    # Interleaving A: mig acquires its first lock, then chat tries to read.
    mig = await asyncpg.connect(**kw)
    chat = await asyncpg.connect(**kw)
    try:
        await mig.execute("BEGIN")
        await mig.execute(f"LOCK TABLE {lock_order[0]} IN ACCESS EXCLUSIVE MODE")
        await chat.execute("BEGIN")
        # chat loads its twin (AccessShare twins). If lock_order[0] ==
        # 'twins' this blocks until mig commits — which is fine (no cycle).
        chat_twin = asyncio.create_task(chat.fetch("SELECT * FROM twins WHERE id=$1", twin_id))
        await asyncio.sleep(0.3)
        # mig acquires its second lock and finishes.
        await mig.execute(f"LOCK TABLE {lock_order[1]} IN ACCESS EXCLUSIVE MODE")
        await mig.execute("COMMIT")
        # chat now proceeds through both reads without deadlock.
        await asyncio.wait_for(chat_twin, timeout=5.0)
        await chat.fetch("SELECT * FROM twin_evolution_events WHERE twin_id=$1", twin_id)
        await chat.execute("COMMIT")
    finally:
        for c in (mig, chat):
            with contextlib.suppress(Exception):
                await c.execute("ROLLBACK")
            await c.close()

    # Interleaving B: chat holds twins AccessShare first, then mig runs fully.
    mig = await asyncpg.connect(**kw)
    chat = await asyncpg.connect(**kw)
    try:
        await chat.execute("BEGIN")
        await chat.fetch("SELECT * FROM twins WHERE id=$1", twin_id)  # AccessShare twins
        await mig.execute("BEGIN")
        # mig wants twins ACCESS EXCLUSIVE → blocks on chat; must NOT deadlock.
        mig_task = asyncio.create_task(
            _run_locks(mig, [f"LOCK TABLE {t} IN ACCESS EXCLUSIVE MODE" for t in lock_order])
        )
        await asyncio.sleep(0.3)
        assert not mig_task.done()  # blocked on chat's twins AccessShare
        # chat reads the event table (mig holds neither lock yet) then commits.
        await chat.fetch("SELECT * FROM twin_evolution_events WHERE twin_id=$1", twin_id)
        await chat.execute("COMMIT")
        await asyncio.wait_for(mig_task, timeout=5.0)
        await mig.execute("COMMIT")
    finally:
        for c in (mig, chat):
            with contextlib.suppress(Exception):
                await c.execute("ROLLBACK")
            await c.close()


async def _run_locks(conn, statements: list[str]) -> None:
    for s in statements:
        await conn.execute(s)


class _StubProvider:
    """Minimal LLMProvider stand-in; the ack path never calls it."""

    name = "stub"


async def test_concurrent_chats_surface_event_once(fresh_db):
    """Two concurrent chat acknowledgements for the same twin must surface
    a given evolution event EXACTLY once (no double-surface), and the
    cursor must end advanced to that event's seq."""
    url = fresh_db
    _alembic(url, "head")
    twin_id, user_id = await _seed_twin(url)

    # Seed exactly one unacknowledged evolution event.
    seed_engine = create_async_engine(url, poolclass=NullPool)
    try:
        sm = async_sessionmaker(seed_engine, expire_on_commit=False)
        async with sm() as s:
            twin = (await s.execute(select(Twin).where(Twin.id == twin_id))).scalar_one()
            row = await EvolutionService(s).record(
                twin, event_type="memory_learned", summary="learned once"
            )
            await s.commit()
            event_seq = row.seq
    finally:
        await seed_engine.dispose()

    async def ack_flow(engine):
        smf = async_sessionmaker(engine, expire_on_commit=False)
        async with smf() as s:
            twin = (await s.execute(select(Twin).where(Twin.id == twin_id))).scalar_one()
            svc = ConversationService(
                s, _StubProvider(), evolution_service=EvolutionService(s)
            )
            learning = await svc._acknowledge_learning_safely(
                twin=twin, conversation_id=uuid.uuid4()
            )
            await s.commit()
            return learning

    engine_a = create_async_engine(url, poolclass=NullPool)
    engine_b = create_async_engine(url, poolclass=NullPool)
    try:
        results = await asyncio.gather(ack_flow(engine_a), ack_flow(engine_b))
    finally:
        await engine_a.dispose()
        await engine_b.dispose()

    surfaced = [r for r in results if r is not None]
    assert len(surfaced) == 1, f"event surfaced {len(surfaced)} times, expected exactly once"
    assert surfaced[0]["count"] == 1
    assert surfaced[0]["acknowledged_up_to_seq"] == event_seq

    # Cursor advanced exactly to the event's seq; a third read surfaces nothing.
    check_engine = create_async_engine(url, poolclass=NullPool)
    try:
        smc = async_sessionmaker(check_engine, expire_on_commit=False)
        async with smc() as s:
            twin = (await s.execute(select(Twin).where(Twin.id == twin_id))).scalar_one()
            assert twin.last_acknowledged_evolution_seq == event_seq
            remaining = await EvolutionService(s).unacknowledged_for_twin(twin, limit=50)
            assert list(remaining) == []
    finally:
        await check_engine.dispose()


async def test_migration_downgrade_removes_sprint10_objects(fresh_db):
    """0007 downgrade cleanly removes the seq column, cursor column, and
    sequence, and a re-upgrade round-trips."""
    url = fresh_db
    _alembic(url, "head")
    _alembic(url, "0006_evolving_twin_loop", direction="downgrade")

    import asyncpg

    kw = _conn_kwargs()
    kw["database"] = urlsplit(url).path.lstrip("/")
    conn = await asyncpg.connect(**kw)
    try:
        seq_col = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='twin_evolution_events' AND column_name='seq'"
        )
        cursor_col = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='twins' AND column_name='last_acknowledged_evolution_seq'"
        )
        seq_obj = await conn.fetchval(
            "SELECT 1 FROM pg_class WHERE relkind='S' AND relname=$1", _SEQ_NAME
        )
        assert seq_col is None, "seq column should be gone after downgrade"
        assert cursor_col is None, "cursor column should be gone after downgrade"
        assert seq_obj is None, "sequence should be dropped after downgrade"
        # The 0006-era table itself must still exist.
        tee = await conn.fetchval(
            "SELECT 1 FROM information_schema.tables WHERE table_name='twin_evolution_events'"
        )
        assert tee == 1
    finally:
        await conn.close()

    # Round-trip: re-upgrade succeeds and restores the seq column.
    _alembic(url, "head")
    conn = await asyncpg.connect(**kw)
    try:
        seq_col = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='twin_evolution_events' AND column_name='seq'"
        )
        assert seq_col == 1
    finally:
        await conn.close()
