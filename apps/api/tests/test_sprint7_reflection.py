"""Sprint 7 reflection end-to-end tests.

Covers the full flow with the real HTTP surface and a canned
reflection extractor:

- run → candidate list → confirm per kind → apply dispatch is correct
- rejection
- idempotent run (fingerprint dedup)
- cross-user isolation
- founder decision #1: confirming an `insight` does NOT create a Memory
- founder decision #2: `profile_update` payload exposes a legible diff
  and TwinProfile only moves after the user's confirmation
- unconfirmed `profile_update` leaves TwinProfile unchanged
- `memory_dedup` supersession + retrieval filter + reversibility
- cross-twin supersede is rejected
- reflection failure never affects chat
- privacy: no sentinel from input appears in any log event
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import structlog.testing

from app.api.deps import (
    get_current_user,
    reflection_extractor_dep,
    sessionmaker_dep,
)
from app.conversation.models import Message
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.reflection.extractor import ReflectionExtractionResult
from app.reflection.schemas import ReflectionDraft
from app.twin.service import TwinService

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


class _CannedExtractor:
    """Returns a fixed `ReflectionExtractionResult`. Injected via
    `reflection_extractor_dep` override so the LLM is never called.
    """

    def __init__(self, drafts: list[ReflectionDraft], *, error: str | None = None) -> None:
        self._drafts = drafts
        self._error = error
        self.calls = 0

    async def extract(self, **_: Any) -> ReflectionExtractionResult:
        self.calls += 1
        return ReflectionExtractionResult(drafts=list(self._drafts), error=self._error)


class _ExplodingExtractor:
    async def extract(self, **_: Any) -> ReflectionExtractionResult:
        raise RuntimeError("boom")


def _install_extractor(client, extractor: object) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[reflection_extractor_dep] = lambda: extractor


def _restore_extractor(client) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides.pop(reflection_extractor_dep, None)


async def _create_twin(client, name: str = "Aurora") -> str:
    resp = await client.post("/v1/twin", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_conversation(client, title: str = "x") -> str:
    resp = await client.post("/v1/conversations", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_confirmed_memory(client, conv_id: str, text: str, content: str) -> str:
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
                    importance=0.8,
                )
            ],
            source_conversation_id=uuid.UUID(conv_id),
            source_message_id=msg.id,
        )
        candidate_id = cand.id

    confirm = await client.post(f"/v1/memory-candidates/{candidate_id}/confirm")
    assert confirm.status_code == 201, confirm.text
    return confirm.json()["memory"]["id"]


# ---------------------------------------------------------------------
# profile_update
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_update_confirmation_moves_twin_profile(client) -> None:
    """A confirmed `profile_update` reflection applies via
    `TwinService.update` — the same user-authored path PATCH /v1/twin
    uses. Unconfirmed, the profile does not move.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    mem1 = await _seed_confirmed_memory(
        client, conv_id, "I prefer short replies in the morning.", "Morning: concise replies."
    )
    mem2 = await _seed_confirmed_memory(
        client, conv_id, "Also keep breakfast chats short.", "Morning: short conversation."
    )

    before = (await client.get("/v1/twin")).json()
    assert before["profile"]["communication_style_notes"] is None

    draft = ReflectionDraft(
        kind="profile_update",
        payload={
            "kind": "profile_update",
            "field": "communication_style_notes",
            "current_value": None,
            "proposed_value": "Prefers concise replies in the morning.",
            "rationale": "Two memories independently support this.",
        },
        rationale="Two memories independently support this.",
        source_memory_ids=[uuid.UUID(mem1), uuid.UUID(mem2)],
        source_goal_ids=[],
        confidence=0.8,
        importance=0.6,
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
        assert run.json()["candidates_persisted"] == 1
    finally:
        _restore_extractor(client)

    # List pending → candidate is present with the diff visible.
    listed = await client.get("/v1/reflections")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    payload = items[0]["proposed_payload"]
    assert payload["field"] == "communication_style_notes"
    assert payload["current_value"] is None
    assert payload["proposed_value"] == "Prefers concise replies in the morning."
    assert payload["rationale"]
    assert items[0]["source_memory_ids"] == [mem1, mem2]

    # Profile is still unchanged pre-confirmation.
    mid = (await client.get("/v1/twin")).json()
    assert mid["profile"]["communication_style_notes"] is None

    # Confirm → profile actually moves.
    confirm = await client.post(f"/v1/reflections/{items[0]['id']}/confirm")
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["applied"] is True
    assert body["apply_metadata"]["field"] == "communication_style_notes"

    after = (await client.get("/v1/twin")).json()
    assert (
        after["profile"]["communication_style_notes"] == "Prefers concise replies in the morning."
    )


@pytest.mark.asyncio
async def test_profile_update_rejection_leaves_profile_unchanged(client) -> None:
    await _create_twin(client)
    draft = ReflectionDraft(
        kind="profile_update",
        payload={
            "kind": "profile_update",
            "field": "communication_style_notes",
            "current_value": None,
            "proposed_value": "Terse mornings.",
            "rationale": "evidence",
        },
        rationale="evidence",
        source_memory_ids=[],
        source_goal_ids=[],
        confidence=0.6,
        importance=0.4,
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    items = (await client.get("/v1/reflections")).json()["items"]
    reject = await client.post(f"/v1/reflections/{items[0]['id']}/reject")
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"
    assert (await client.get("/v1/twin")).json()["profile"]["communication_style_notes"] is None


@pytest.mark.asyncio
async def test_double_confirm_is_rejected(client) -> None:
    await _create_twin(client)
    draft = ReflectionDraft(
        kind="insight",
        payload={
            "kind": "insight",
            "headline": "noticed",
            "body": "something",
            "rationale": "x",
        },
        rationale="x",
        source_memory_ids=[],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    items = (await client.get("/v1/reflections")).json()["items"]
    rid = items[0]["id"]
    first = await client.post(f"/v1/reflections/{rid}/confirm")
    assert first.status_code == 200
    second = await client.post(f"/v1/reflections/{rid}/confirm")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "reflection_already_resolved"


# ---------------------------------------------------------------------
# insight — founder decision #1
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insight_confirmation_creates_no_memory(client) -> None:
    """Confirming an `insight` reflection must NOT create a Memory
    and must NOT mutate TwinProfile.
    """
    await _create_twin(client)
    await _create_conversation(client)
    before_memories = (await client.get("/v1/memories")).json()["items"]
    before_profile = (await client.get("/v1/twin")).json()

    draft = ReflectionDraft(
        kind="insight",
        payload={
            "kind": "insight",
            "headline": "Prefers evening chats",
            "body": "Six of your last ten conversations started after 7pm.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)

    rid = (await client.get("/v1/reflections")).json()["items"][0]["id"]
    confirm = await client.post(f"/v1/reflections/{rid}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["applied"] is True
    assert confirm.json()["apply_metadata"] == {
        "kind": "insight",
        "acknowledged": True,
    }

    after_memories = (await client.get("/v1/memories")).json()["items"]
    after_profile = (await client.get("/v1/twin")).json()
    assert len(after_memories) == len(before_memories)
    assert after_profile == before_profile
    # Also: no pending memory candidate was created.
    pending = (await client.get("/v1/memory-candidates")).json()["items"]
    assert pending == []


# ---------------------------------------------------------------------
# memory_dedup + supersession
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_dedup_supersession_hides_memory_from_retrieval(client) -> None:
    """A confirmed `memory_dedup` reflection must mark the superseded
    memory, retrieval must exclude it, the memory list must still
    expose it, and un-supersede must restore it.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    mem_a = await _seed_confirmed_memory(
        client, conv_id, "I live in Bengaluru.", "Lives in Bengaluru."
    )
    mem_b = await _seed_confirmed_memory(
        client, conv_id, "I'm based in Bengaluru.", "Based in Bengaluru."
    )

    draft = ReflectionDraft(
        kind="memory_dedup",
        payload={
            "kind": "memory_dedup",
            "superseded_memory_id": mem_a,
            "canonical_memory_id": mem_b,
            "rationale": "Same fact phrased twice.",
        },
        rationale="Same fact phrased twice.",
        source_memory_ids=[uuid.UUID(mem_a), uuid.UUID(mem_b)],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)

    rid = (await client.get("/v1/reflections")).json()["items"][0]["id"]
    confirm = await client.post(f"/v1/reflections/{rid}/confirm")
    assert confirm.status_code == 200

    # The memory list STILL exposes the superseded row.
    listed = (await client.get("/v1/memories")).json()["items"]
    by_id = {m["id"]: m for m in listed}
    assert by_id[mem_a]["superseded_by_memory_id"] == mem_b
    assert by_id[mem_b]["superseded_by_memory_id"] is None

    # Retrieval must now skip the superseded row. Chat picks only mem_b.
    chat = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Looking back, where have I been living?"},
    )
    assert chat.status_code == 201
    memory_ids = chat.json()["twin_message"]["metadata_json"]["retrieval"]["memory_ids"]
    assert mem_a not in memory_ids
    assert mem_b in memory_ids

    # Un-supersede reverses the state.
    rev = await client.post(f"/v1/memories/{mem_a}/unsupersede")
    assert rev.status_code == 200
    assert rev.json()["superseded_by_memory_id"] is None


@pytest.mark.asyncio
async def test_memory_dedup_cross_twin_is_rejected(client, as_user, user_a, user_b) -> None:
    """A `memory_dedup` confirmation whose canonical belongs to a
    different user's twin must fail cleanly without leaking existence.
    """
    as_user(user_a)
    await _create_twin(client, name="A")
    conv_a = await _create_conversation(client)
    mem_a1 = await _seed_confirmed_memory(client, conv_a, "A's text 1.", "A fact 1.")

    as_user(user_b)
    await _create_twin(client, name="B")
    conv_b = await _create_conversation(client)
    mem_b1 = await _seed_confirmed_memory(client, conv_b, "B's text 1.", "B fact 1.")
    # second memory seeded for realism (even though only mem_b1 is used in the
    # dedup payload below); confirms B owns multiple rows when the cross-twin
    # attempt is made.
    await _seed_confirmed_memory(client, conv_b, "B's text 2.", "B fact 2.")

    # B tries to supersede B's own memory, but names A's memory as canonical.
    draft = ReflectionDraft(
        kind="memory_dedup",
        payload={
            "kind": "memory_dedup",
            "superseded_memory_id": mem_b1,
            "canonical_memory_id": mem_a1,  # cross-twin!
            "rationale": "attempt",
        },
        rationale="attempt",
        source_memory_ids=[uuid.UUID(mem_b1)],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)

    rid = (await client.get("/v1/reflections")).json()["items"][0]["id"]
    confirm = await client.post(f"/v1/reflections/{rid}/confirm")
    # The confirm transitions status to confirmed then fails the apply.
    assert confirm.status_code == 500
    assert confirm.json()["error"]["code"] == "reflection_apply_error"
    # mem_b1 is unchanged.
    mem_b1_after = (await client.get(f"/v1/memories/{mem_b1}")).json()
    assert mem_b1_after["superseded_by_memory_id"] is None


# ---------------------------------------------------------------------
# goal_update
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_update_records_goal_event_without_changing_goal(client) -> None:
    await _create_twin(client)
    r = await client.post("/v1/goals", json={"title": "Ship Sprint 7", "priority": 1})
    assert r.status_code == 201
    gid = r.json()["id"]

    draft = ReflectionDraft(
        kind="goal_update",
        payload={
            "kind": "goal_update",
            "goal_id": gid,
            "note": "User mentioned a new blocker today.",
            "rationale": "evidence",
        },
        rationale="evidence",
        source_memory_ids=[],
        source_goal_ids=[uuid.UUID(gid)],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    rid = (await client.get("/v1/reflections")).json()["items"][0]["id"]
    confirm = await client.post(f"/v1/reflections/{rid}/confirm")
    assert confirm.status_code == 200
    # Goal is unchanged.
    goal = (await client.get(f"/v1/goals/{gid}")).json()
    assert goal["title"] == "Ship Sprint 7"
    assert goal["priority"] == 1
    assert goal["status"] == "active"
    # But a GoalEvent of type `updated` was recorded.
    events = (await client.get(f"/v1/goals/{gid}/events")).json()["items"]
    types = [e["event_type"] for e in events]
    assert "updated" in types
    note_evt = next(e for e in events if e["event_type"] == "updated")
    assert note_evt["note"] == "User mentioned a new blocker today."


# ---------------------------------------------------------------------
# Fingerprint dedup
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_run_dedups_by_fingerprint(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    mem_a = await _seed_confirmed_memory(client, conv_id, "something.", "a fact.")

    draft = ReflectionDraft(
        kind="insight",
        payload={
            "kind": "insight",
            "headline": "h",
            "body": "b",
            "rationale": "r",
        },
        rationale="r",
        source_memory_ids=[uuid.UUID(mem_a)],
        source_goal_ids=[],
    )
    extractor = _CannedExtractor([draft])
    _install_extractor(client, extractor)
    try:
        first = await client.post("/v1/reflections/run")
        second = await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    assert first.json()["candidates_persisted"] == 1
    assert second.json()["candidates_persisted"] == 0
    assert second.json()["candidates_deduplicated"] == 1
    assert len((await client.get("/v1/reflections")).json()["items"]) == 1


# ---------------------------------------------------------------------
# Reflection failure never breaks chat
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflection_extractor_failure_does_not_affect_chat(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_extractor(client, _ExplodingExtractor())
    try:
        # A reflection run with an exploding extractor returns a run
        # body with an error tag — not a 500.
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
        assert run.json()["candidates_persisted"] == 0
        assert run.json()["error"] is not None
    finally:
        _restore_extractor(client)
    # Chat is unaffected.
    chat = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hi"})
    assert chat.status_code == 201


# ---------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflections_are_owner_scoped(client, as_user, user_a, user_b) -> None:
    as_user(user_a)
    await _create_twin(client, name="A")
    draft = ReflectionDraft(
        kind="insight",
        payload={"kind": "insight", "headline": "h", "body": "b", "rationale": "r"},
        rationale="r",
        source_memory_ids=[],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    a_items = (await client.get("/v1/reflections")).json()["items"]
    assert len(a_items) == 1
    rid = a_items[0]["id"]

    as_user(user_b)
    await _create_twin(client, name="B")
    # B's listing is empty (owner-scoped).
    b_items = (await client.get("/v1/reflections")).json()["items"]
    assert b_items == []
    # B cannot confirm or reject A's reflection.
    assert (await client.post(f"/v1/reflections/{rid}/confirm")).status_code == 404
    assert (await client.post(f"/v1/reflections/{rid}/reject")).status_code == 404


# ---------------------------------------------------------------------
# Privacy / logging
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflection_run_does_not_leak_sentinel_in_logs(client) -> None:
    """A unique sentinel that would be in the LLM input must not appear
    in any structlog event emitted during a reflection run.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    sentinel = "SPRINT7-NONCE-7f3b2a8c-NEVER-LOG-ME"
    # Seed a memory that contains the sentinel.
    await _seed_confirmed_memory(client, conv_id, "A seed message.", f"Note: {sentinel}")

    draft = ReflectionDraft(
        kind="insight",
        payload={"kind": "insight", "headline": "h", "body": "b", "rationale": "r"},
        rationale="r",
        source_memory_ids=[],
        source_goal_ids=[],
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        with structlog.testing.capture_logs() as events:
            run = await client.post("/v1/reflections/run")
            assert run.status_code == 200
    finally:
        _restore_extractor(client)
    for event in events:
        for value in event.values():
            assert sentinel not in str(value), event


# ---------------------------------------------------------------------
# API shape
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflection_run_requires_twin(client) -> None:
    """Without a Twin the run endpoint returns 404 (twin_not_found),
    not 500.
    """
    _install_extractor(client, _CannedExtractor([]))
    try:
        run = await client.post("/v1/reflections/run")
    finally:
        _restore_extractor(client)
    assert run.status_code == 404
    assert run.json()["error"]["code"] == "twin_not_found"
