"""Sprint 9 — Twin Self-Portrait tests.

Covers:

- Response shape (profile / memory_summary / active_goals /
  recent_evolution with the Sprint 8 `lead` tag).
- Owner-scoping: another user sees only their own portrait.
- 404 when the authenticated user has no Twin.
- Only confirmed, non-superseded memories appear in top_memories +
  counts_by_type + total_count.
- Rejected memory candidates do not leak into the portrait.
- Pending memory candidates do not leak into the portrait.
- Superseded memories do not appear even though the memory list
  endpoint still exposes them.
- `top_memories` is capped at `TOP_MEMORIES_LIMIT=5`.
- Memory snippets are capped at 240 characters with an ellipsis.
- Unicode content truncates on code-point boundaries without
  splitting a code point.
- Evolution is newest-first and capped at 5.
- `GET /v1/twin/portrait` does not mutate any Twin state.
- GETting the portrait does NOT create an evolution event.
- The portrait path does NOT invoke the LLM provider.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.api.deps import get_current_user, sessionmaker_dep
from app.conversation.models import Message
from app.evolution.models import TwinEvolutionEvent
from app.evolution.service import EvolutionService
from app.memory.models import Memory
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.portrait import (
    MEMORY_SNIPPET_MAX_CHARS,
    TOP_MEMORIES_LIMIT,
)
from app.twin.service import TwinService

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


async def _create_twin(client, name: str = "Aurora") -> str:
    resp = await client.post("/v1/twin", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_conversation(client, title: str = "x") -> str:
    resp = await client.post("/v1/conversations", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_confirmed_memory(
    client,
    conv_id: str,
    text: str,
    content: str,
    *,
    importance: float = 0.5,
) -> str:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=uuid.UUID(conv_id),
            role="user",
            content=text,
        )
        session.add(msg)
        await session.flush()
        twin = await TwinService(session).require_by_user(user.user_id)
        [cand] = await MemoryService(session).create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content=content,
                    confidence=0.9,
                    importance=importance,
                )
            ],
            source_conversation_id=uuid.UUID(conv_id),
            source_message_id=msg.id,
        )
        candidate_id = cand.id
    confirm = await client.post(f"/v1/memory-candidates/{candidate_id}/confirm")
    assert confirm.status_code == 201, confirm.text
    return confirm.json()["memory"]["id"]


async def _seed_pending_candidate(client, conv_id: str, text: str, content: str) -> str:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=uuid.UUID(conv_id),
            role="user",
            content=text,
        )
        session.add(msg)
        await session.flush()
        twin = await TwinService(session).require_by_user(user.user_id)
        [cand] = await MemoryService(session).create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content=content,
                    confidence=0.5,
                    importance=0.5,
                )
            ],
            source_conversation_id=uuid.UUID(conv_id),
            source_message_id=msg.id,
        )
        return str(cand.id)


# ---------------------------------------------------------------
# Shape + owner-scope basics
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_portrait_404_when_no_twin(client) -> None:
    resp = await client.get("/v1/twin/portrait")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_portrait_shape_for_empty_twin(client) -> None:
    await _create_twin(client, name="Aurora")
    resp = await client.get("/v1/twin/portrait")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "profile",
        "memory_summary",
        "active_goals",
        "recent_evolution",
    }
    assert body["profile"]["display_name"] == "Aurora"
    assert body["profile"]["style_preset"] == "neutral"
    assert body["profile"]["style_notes"] is None
    assert body["profile"]["basic_profile"] == {}

    summary = body["memory_summary"]
    assert summary["total_count"] == 0
    # Every known memory type is present with zero count.
    assert set(summary["counts_by_type"].keys()) == {
        "FACT",
        "PREFERENCE",
        "EXPERIENCE",
        "GOAL",
    }
    assert all(v == 0 for v in summary["counts_by_type"].values())
    assert summary["top_memories"] == []

    assert body["active_goals"] == []
    assert body["recent_evolution"] == []


@pytest.mark.asyncio
async def test_portrait_profile_reflects_patch(client) -> None:
    await _create_twin(client)
    patch = await client.patch(
        "/v1/twin",
        json={
            "communication_style_preset": "warm",
            "communication_style_notes": "Short mornings.",
            "basic_profile": {"city": "Lisbon"},
        },
    )
    assert patch.status_code == 200
    portrait = (await client.get("/v1/twin/portrait")).json()
    assert portrait["profile"]["style_preset"] == "warm"
    assert portrait["profile"]["style_notes"] == "Short mornings."
    assert portrait["profile"]["basic_profile"] == {"city": "Lisbon"}


@pytest.mark.asyncio
async def test_portrait_is_owner_scoped(client, as_user, user_a, user_b) -> None:
    """Owner A sees A's portrait; owner B gets a 404 (no Twin of their
    own) and never A's portrait."""
    await _create_twin(client, name="A")
    conv_a = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv_a, "x", "A fact one")
    as_user(user_b)
    resp = await client.get("/v1/twin/portrait")
    assert resp.status_code == 404
    as_user(user_a)
    resp_a = (await client.get("/v1/twin/portrait")).json()
    assert resp_a["memory_summary"]["total_count"] == 1


# ---------------------------------------------------------------
# Memory filtering + top-N + snippet truncation
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_portrait_includes_only_confirmed_non_superseded_memories(
    client, session_factory
) -> None:
    await _create_twin(client)
    conv = await _create_conversation(client)
    # Six confirmed memories with distinct importances.
    ids = []
    for i, imp in enumerate([0.9, 0.8, 0.7, 0.6, 0.5, 0.4]):
        mid = await _seed_confirmed_memory(
            client,
            conv,
            f"msg{i}",
            f"confirmed memory {i}",
            importance=imp,
        )
        ids.append(mid)
    # One pending candidate (unconfirmed).
    pending_id = await _seed_pending_candidate(client, conv, "p", "pending fact")
    # One rejected candidate.
    rejected_id = await _seed_pending_candidate(client, conv, "r", "rejected fact")
    rr = await client.post(f"/v1/memory-candidates/{rejected_id}/reject")
    assert rr.status_code == 200
    # One superseded memory (by another confirmed memory).
    super_src = await _seed_confirmed_memory(
        client, conv, "s1", "superseded source", importance=0.95
    )
    super_dst = await _seed_confirmed_memory(
        client, conv, "s2", "canonical destination", importance=0.95
    )
    async with session_factory() as session:
        row = (
            await session.execute(select(Memory).where(Memory.id == uuid.UUID(super_src)))
        ).scalar_one()
        row.superseded_by_memory_id = uuid.UUID(super_dst)
        await session.commit()

    body = (await client.get("/v1/twin/portrait")).json()
    summary = body["memory_summary"]
    # Confirmed non-superseded only: 6 originals + the canonical
    # destination = 7. (super_src is superseded, pending/rejected are
    # not Memory rows.)
    assert summary["total_count"] == 7
    assert summary["counts_by_type"]["FACT"] == 7
    # top_memories is 5 (TOP_MEMORIES_LIMIT) and ordered by importance.
    assert len(summary["top_memories"]) == TOP_MEMORIES_LIMIT
    importances = [m["importance"] for m in summary["top_memories"]]
    assert importances == sorted(importances, reverse=True)
    # Superseded memory id is not in the top list.
    top_ids = {m["id"] for m in summary["top_memories"]}
    assert super_src not in top_ids
    # Pending/rejected candidate ids are not Memory ids — just sanity:
    # none of our pending/rejected UUIDs appear anywhere.
    all_ids_in_body = {m["id"] for m in summary["top_memories"]}
    assert pending_id not in all_ids_in_body
    assert rejected_id not in all_ids_in_body


@pytest.mark.asyncio
async def test_portrait_snippet_truncates_long_content(client) -> None:
    await _create_twin(client)
    conv = await _create_conversation(client)
    long_content = "x" * 1000
    await _seed_confirmed_memory(client, conv, "m", long_content, importance=0.95)
    body = (await client.get("/v1/twin/portrait")).json()
    [m] = body["memory_summary"]["top_memories"]
    assert len(m["snippet"]) == MEMORY_SNIPPET_MAX_CHARS
    assert m["snippet"].endswith("…")


@pytest.mark.asyncio
async def test_portrait_snippet_is_unicode_safe(client) -> None:
    """A snippet of all-emoji content must truncate at a code-point
    boundary (Python str slicing is code-point-aware) and the length
    must be exactly MEMORY_SNIPPET_MAX_CHARS code points."""
    await _create_twin(client)
    conv = await _create_conversation(client)
    emoji_content = "🧠" * 400
    await _seed_confirmed_memory(client, conv, "m", emoji_content, importance=0.95)
    body = (await client.get("/v1/twin/portrait")).json()
    [m] = body["memory_summary"]["top_memories"]
    # Code-point length (Python len on str counts code points).
    assert len(m["snippet"]) == MEMORY_SNIPPET_MAX_CHARS
    assert m["snippet"].endswith("…")
    # Every character before the ellipsis is a brain emoji.
    assert m["snippet"][:-1] == "🧠" * (MEMORY_SNIPPET_MAX_CHARS - 1)


@pytest.mark.asyncio
async def test_portrait_snippet_does_not_truncate_short_content(client) -> None:
    await _create_twin(client)
    conv = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv, "m", "a short fact", importance=0.95)
    body = (await client.get("/v1/twin/portrait")).json()
    [m] = body["memory_summary"]["top_memories"]
    assert m["snippet"] == "a short fact"
    assert not m["snippet"].endswith("…")


# ---------------------------------------------------------------
# Evolution newest-first and cap
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_portrait_evolution_newest_first_capped_at_5(client, session_factory) -> None:
    await _create_twin(client)
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    async with session_factory() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        svc = EvolutionService(session)
        # Insert 7 events in order so created_at increments naturally.
        for i in range(7):
            await svc.record(
                twin,
                event_type="memory_learned",
                summary=f"event {i}",
            )
        await session.commit()
    body = (await client.get("/v1/twin/portrait")).json()
    evo = body["recent_evolution"]
    assert len(evo) == 5
    # Newest-first: later-inserted events come first.
    assert [e["summary"] for e in evo] == [
        "event 6",
        "event 5",
        "event 4",
        "event 3",
        "event 2",
    ]
    assert all(e["lead"] == "learned" for e in evo)


@pytest.mark.asyncio
async def test_portrait_evolution_insight_lead_is_acknowledged(client, session_factory) -> None:
    """Sprint 7 Decision #1 preserved: insight confirmation is
    acknowledgement. The portrait uses `lead='acknowledged'` for that
    event type and `lead='learned'` for everything else."""
    await _create_twin(client)
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    async with session_factory() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        svc = EvolutionService(session)
        await svc.record(twin, event_type="insight_acknowledged", summary="i")
        await svc.record(twin, event_type="memory_learned", summary="m")
        await svc.record(twin, event_type="goal_updated", summary="g")
        await svc.record(twin, event_type="profile_confirmed", summary="p")
        await svc.record(twin, event_type="memory_consolidated", summary="c")
        await session.commit()
    body = (await client.get("/v1/twin/portrait")).json()
    leads = {e["event_type"]: e["lead"] for e in body["recent_evolution"]}
    assert leads["insight_acknowledged"] == "acknowledged"
    for et in (
        "memory_learned",
        "goal_updated",
        "profile_confirmed",
        "memory_consolidated",
    ):
        assert leads[et] == "learned", et


# ---------------------------------------------------------------
# GET must not mutate (zero side effects)
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_portrait_get_does_not_create_evolution_event(client, session_factory) -> None:
    await _create_twin(client)
    conv = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv, "m", "a fact")
    async with session_factory() as session:
        before = (await session.execute(select(TwinEvolutionEvent))).scalars().all()
    # Multiple GETs — no new rows.
    for _ in range(3):
        resp = await client.get("/v1/twin/portrait")
        assert resp.status_code == 200
    async with session_factory() as session:
        after = (await session.execute(select(TwinEvolutionEvent))).scalars().all()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_portrait_get_does_not_mutate_profile(client, session_factory) -> None:
    await _create_twin(client)
    before = (await client.get("/v1/twin")).json()
    for _ in range(3):
        assert (await client.get("/v1/twin/portrait")).status_code == 200
    after = (await client.get("/v1/twin")).json()
    assert before["display_name"] == after["display_name"]
    assert before["profile"] == after["profile"]


@pytest.mark.asyncio
async def test_portrait_get_does_not_call_llm(client, monkeypatch) -> None:
    """The portrait is deterministic composition. No LLM is involved.

    We assert this by monkeypatching the provider's `generate_response`
    to raise and verifying that `GET /v1/twin/portrait` still succeeds.
    """
    from app.llm.providers import mock as mock_provider

    async def _explode(self: Any, request: Any) -> Any:
        raise RuntimeError("LLM must not be called by portrait")

    monkeypatch.setattr(mock_provider.MockProvider, "generate_response", _explode)

    await _create_twin(client)
    resp = await client.get("/v1/twin/portrait")
    assert resp.status_code == 200, resp.text
