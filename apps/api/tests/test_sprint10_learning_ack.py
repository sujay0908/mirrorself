"""Sprint 10 — chat-time learning acknowledgement (SQLite integration).

These exercise the deterministic surfacing/cursor logic end-to-end
through the chat endpoint on the in-memory SQLite harness:

- A confirmed evolution event surfaces as a `learning` block on the next
  twin reply, exactly once; the cursor advances with the message.
- No events / already-acknowledged → no `learning` block.
- Ordering by `seq`, batch cap, and the backlog draining over turns.
- `insight_acknowledged` carries the "acknowledged" lead.
- Owner scoping: one user never sees another's evolution.
- Privacy: no raw user/message content leaks into the `learning` block.
- Failure isolation: an ack-lookup error never fails the chat.

The per-twin advisory-lock serialization, seq==commit ordering under
concurrent out-of-order commits, and the migration boundary require a
real PostgreSQL backend and live in test_sprint10_pg.py.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.evolution.acknowledgement import ACK_SURFACE_LIMIT
from app.evolution.service import EvolutionService
from app.twin.service import TwinService


async def _create_twin(client, name: str = "Aurora") -> str:
    resp = await client.post("/v1/twin", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_conversation(client, title: str = "c") -> str:
    resp = await client.post("/v1/conversations", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post(client, conv_id: str, content: str) -> dict[str, Any]:
    resp = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": content},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_event(
    session_factory: async_sessionmaker,
    user: AuthenticatedUser,
    *,
    event_type: str,
    summary: str,
    profile_field: str | None = None,
) -> int:
    """Record one evolution event for the user's twin. Returns its seq."""
    async with session_factory() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        row = await EvolutionService(session).record(
            twin,
            event_type=event_type,
            summary=summary,
            profile_field=profile_field,
        )
        await session.commit()
        return row.seq


def _learning(twin_message: dict[str, Any]) -> dict[str, Any] | None:
    return twin_message["metadata_json"]["learning"]


def test_migration_locks_twins_before_events() -> None:
    """Static guard for the audit deadlock fix: migration 0007 must take
    ACCESS EXCLUSIVE on `twins` BEFORE `twin_evolution_events`, matching
    the twins→events lock order every owner-scoped request uses. Reverting
    to events-first reintroduces the reproduced deadlock, so this fails.

    Runs in CI (no PostgreSQL needed); the dynamic proof is in
    test_sprint10_pg.py::test_corrected_lock_order_no_deadlock.
    """
    migration = (
        pathlib.Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0007_chat_time_learning_ack.py"
    )
    locks = re.findall(
        r"LOCK TABLE (\w+) IN ACCESS EXCLUSIVE MODE",
        migration.read_text(),
    )
    assert "twins" in locks and "twin_evolution_events" in locks, locks
    assert locks.index("twins") < locks.index("twin_evolution_events"), (
        f"migration lock order must be twins before twin_evolution_events; got {locks!r}"
    )


async def test_confirmed_event_surfaces_once_and_advances_cursor(
    client, session_factory, user_a
):
    await _create_twin(client)
    conv = await _create_conversation(client)
    seq = await _seed_event(
        session_factory,
        user_a,
        event_type="memory_learned",
        summary="FACT memory learned via confirmed candidate",
    )

    first = await _post(client, conv, "hello")
    learning = _learning(first["twin_message"])
    assert learning is not None
    assert learning["count"] == 1
    assert learning["acknowledged_up_to_seq"] == seq
    assert learning["has_learned"] is True
    assert learning["has_acknowledged"] is False
    item = learning["items"][0]
    assert item["event_type"] == "memory_learned"
    assert item["lead"] == "learned"
    assert item["seq"] == seq
    assert "learned" in item["summary"]

    # Second turn: nothing new → no chip, cursor stayed advanced.
    second = await _post(client, conv, "again")
    assert _learning(second["twin_message"]) is None

    async with session_factory() as session:
        twin = await TwinService(session).require_by_user(user_a.user_id)
        assert twin.last_acknowledged_evolution_seq == seq


async def test_no_events_means_no_learning_block(client, session_factory, user_a):
    await _create_twin(client)
    conv = await _create_conversation(client)
    reply = await _post(client, conv, "hi")
    assert _learning(reply["twin_message"]) is None


async def test_insight_event_has_acknowledged_lead(client, session_factory, user_a):
    await _create_twin(client)
    conv = await _create_conversation(client)
    await _seed_event(
        session_factory,
        user_a,
        event_type="insight_acknowledged",
        summary="insight acknowledged (no memory or profile change)",
    )
    reply = await _post(client, conv, "hi")
    learning = _learning(reply["twin_message"])
    assert learning is not None
    assert learning["has_acknowledged"] is True
    assert learning["has_learned"] is False
    assert learning["items"][0]["lead"] == "acknowledged"


async def test_ordering_and_batch_cap_drains_over_turns(client, session_factory, user_a):
    await _create_twin(client)
    conv = await _create_conversation(client)
    total = ACK_SURFACE_LIMIT + 2
    seqs = []
    for i in range(total):
        seqs.append(
            await _seed_event(
                session_factory,
                user_a,
                event_type="memory_learned",
                summary=f"memory {i} learned",
            )
        )
    assert seqs == sorted(seqs)  # monotonic seq assignment

    first = await _post(client, conv, "turn1")
    l1 = _learning(first["twin_message"])
    assert l1 is not None
    assert l1["count"] == ACK_SURFACE_LIMIT
    # Oldest-first, seq ascending.
    assert [it["seq"] for it in l1["items"]] == seqs[:ACK_SURFACE_LIMIT]
    assert l1["acknowledged_up_to_seq"] == seqs[ACK_SURFACE_LIMIT - 1]

    second = await _post(client, conv, "turn2")
    l2 = _learning(second["twin_message"])
    assert l2 is not None
    assert [it["seq"] for it in l2["items"]] == seqs[ACK_SURFACE_LIMIT:]

    third = await _post(client, conv, "turn3")
    assert _learning(third["twin_message"]) is None


async def test_owner_scoping(client, session_factory, as_user, user_a, user_b):
    # user_a has a twin + an evolution event.
    await _create_twin(client, "A-twin")
    await _seed_event(
        session_factory,
        user_a,
        event_type="memory_learned",
        summary="A private learning",
    )
    # Switch to user_b: their own twin + conversation, no events.
    as_user(user_b)
    await _create_twin(client, "B-twin")
    conv_b = await _create_conversation(client)
    reply = await _post(client, conv_b, "hi from B")
    # B must not see A's evolution.
    assert _learning(reply["twin_message"]) is None

    # Direct service check: B's unacknowledged slice is empty.
    async with session_factory() as session:
        twin_b = await TwinService(session).require_by_user(user_b.user_id)
        rows = await EvolutionService(session).unacknowledged_for_twin(twin_b, limit=50)
        assert list(rows) == []


async def test_privacy_no_raw_message_content_in_learning(client, session_factory, user_a):
    await _create_twin(client)
    conv = await _create_conversation(client)
    await _seed_event(
        session_factory,
        user_a,
        event_type="goal_updated",
        summary="goal note appended via confirmed reflection",
    )
    sentinel = "SENTINEL-" + uuid.uuid4().hex
    reply = await _post(client, conv, f"please remember {sentinel}")
    learning = _learning(reply["twin_message"])
    assert learning is not None
    import json as _json

    blob = _json.dumps(learning)
    assert sentinel not in blob
    # Only the safe, fixed key set is present per item.
    assert set(learning["items"][0].keys()) == {"id", "event_type", "lead", "summary", "seq"}


async def test_ack_lookup_failure_never_breaks_chat(
    client, session_factory, user_a, monkeypatch
):
    await _create_twin(client)
    conv = await _create_conversation(client)
    await _seed_event(
        session_factory,
        user_a,
        event_type="memory_learned",
        summary="will not be read",
    )

    async def _boom(self, twin, *, limit):  # noqa: ANN001
        raise RuntimeError("simulated lookup failure")

    monkeypatch.setattr(EvolutionService, "unacknowledged_for_twin", _boom)

    reply = await _post(client, conv, "hi")
    # Chat still succeeds; no chip surfaced.
    assert _learning(reply["twin_message"]) is None
    assert reply["twin_message"]["content"]  # a real reply came back

    # Cursor did NOT advance (the SAVEPOINT rolled the read back).
    async with session_factory() as session:
        twin = await TwinService(session).require_by_user(user_a.user_id)
        assert twin.last_acknowledged_evolution_seq == 0
