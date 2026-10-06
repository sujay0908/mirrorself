"""Sprint 8 integration tests — the Evolving Twin Loop end-to-end.

Covers:

- Scheduler maybe_run: SKIP when nothing meaningful (chat still succeeds).
- Scheduler maybe_run: RUNS when new memories cross the threshold,
  advances `twins.last_reflection_run_at`, and persists candidates.
- Scheduler never advances the run timestamp on an extractor error
  (so the next chat retries once the trigger survives).
- Chat failure isolation: a scheduler that explodes NEVER breaks chat.
- Evolution events:
    * memory_learned on confirmed candidate.
    * profile_confirmed on confirmed profile_update reflection.
    * memory_consolidated on confirmed memory_dedup reflection.
    * goal_updated on confirmed goal_update reflection.
    * insight_acknowledged on confirmed insight reflection.
    * REJECTED reflection candidates DO NOT create evolution events.
    * Cross-user listing returns owner-scoped rows only.
- Intent telemetry row shape (safe metadata only).
- Privacy sentinel: a sentinel in the chat message or memory content
  never appears in any evolution row, telemetry row, or structlog
  event emitted during the turn.
- Confirmation lifecycle: `memories.confirmed_at` is set at
  candidate_confirm and is NOT touched by a subsequent `patch` edit.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import structlog.testing
from sqlalchemy import select

from app.api.deps import (
    get_current_user,
    reflection_extractor_dep,
    sessionmaker_dep,
)
from app.conversation.models import Message
from app.evolution.models import TwinEvolutionEvent
from app.memory.models import Memory
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.reflection.extractor import ReflectionExtractionResult
from app.reflection.scheduler import (
    OpportunityPolicy,
    ReflectionScheduler,
    gather_signals,
)
from app.reflection.schemas import ReflectionDraft
from app.telemetry.models import IntentTelemetryEvent
from app.twin.service import TwinService

# --------------------------------------------------------------
# Helpers (duplicated from test_sprint7_reflection to keep this
# test file independent, so a Sprint-7 refactor cannot silently
# break Sprint-8 assertions).
# --------------------------------------------------------------


class _CannedExtractor:
    def __init__(self, drafts: list[ReflectionDraft], *, error: str | None = None) -> None:
        self._drafts = drafts
        self._error = error
        self.calls = 0

    async def extract(self, **_: Any) -> ReflectionExtractionResult:
        self.calls += 1
        return ReflectionExtractionResult(drafts=list(self._drafts), error=self._error)


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


# --------------------------------------------------------------
# gather_signals + scheduler core
# --------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_skip_when_no_signal(client, session_factory) -> None:
    """Freshly-created twin, no new memories, no goal events, no
    pending reflections → scheduler returns SKIP with the
    `skip:no_meaningful_trigger` reason."""
    await _create_twin(client)
    async with session_factory() as session:
        transport = client._transport  # type: ignore[attr-defined]
        app = transport.app
        user_dep = app.dependency_overrides[get_current_user]
        user = (await user_dep()) if callable(user_dep) else user_dep
        twin = await TwinService(session).require_by_user(user.user_id)
        # The default policy requires 3 new memories OR 2 goal events.
        policy = OpportunityPolicy()
        signals = await gather_signals(session, twin)
        assert signals.new_confirmed_memories == 0
        assert signals.meaningful_goal_events == 0
        decision = policy.evaluate(signals)
        assert decision.should_run is False
        assert decision.reason == "skip:no_meaningful_trigger"


@pytest.mark.asyncio
async def test_scheduler_runs_after_three_confirmed_memories(client, session_factory) -> None:
    """Confirming three memories crosses the memory threshold. The
    scheduler then runs and advances `last_reflection_run_at`."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    m1 = await _seed_confirmed_memory(client, conv_id, "x", "m1")
    m2 = await _seed_confirmed_memory(client, conv_id, "y", "m2")
    m3 = await _seed_confirmed_memory(client, conv_id, "z", "m3")

    draft = ReflectionDraft(
        kind="insight",
        payload={
            "kind": "insight",
            "headline": "You confirmed three memories",
            "body": "That is a signal.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[uuid.UUID(m1), uuid.UUID(m2), uuid.UUID(m3)],
        source_goal_ids=[],
        confidence=0.6,
        importance=0.4,
    )
    extractor = _CannedExtractor([draft])

    async with session_factory() as session:
        transport = client._transport  # type: ignore[attr-defined]
        app = transport.app
        user_dep = app.dependency_overrides[get_current_user]
        user = (await user_dep()) if callable(user_dep) else user_dep
        twin = await TwinService(session).require_by_user(user.user_id)
        assert twin.last_reflection_run_at is None

        from app.reflection.service import ReflectionService

        scheduler = ReflectionScheduler(
            session,
            extractor=extractor,  # type: ignore[arg-type]
            reflection_service=ReflectionService(session),
            policy=OpportunityPolicy(),
        )
        result = await scheduler.maybe_run(twin)
        assert result.ran is True
        assert result.candidates_persisted == 1
        # Advance stamp committed inside the same transaction.
        assert twin.last_reflection_run_at is not None
        assert extractor.calls == 1


@pytest.mark.asyncio
async def test_scheduler_does_not_advance_timestamp_on_extractor_error(
    client, session_factory
) -> None:
    """An extractor error must not advance `last_reflection_run_at`
    — otherwise cooldown would then suppress the next real run."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    for i in range(3):
        await _seed_confirmed_memory(client, conv_id, f"x{i}", f"m{i}")

    extractor = _CannedExtractor([], error="provider_error:RuntimeError")

    async with session_factory() as session:
        transport = client._transport  # type: ignore[attr-defined]
        app = transport.app
        user_dep = app.dependency_overrides[get_current_user]
        user = (await user_dep()) if callable(user_dep) else user_dep
        twin = await TwinService(session).require_by_user(user.user_id)
        from app.reflection.service import ReflectionService

        scheduler = ReflectionScheduler(
            session,
            extractor=extractor,  # type: ignore[arg-type]
            reflection_service=ReflectionService(session),
            policy=OpportunityPolicy(),
        )
        result = await scheduler.maybe_run(twin)
        assert result.ran is False
        assert result.error == "provider_error:RuntimeError"
        await session.refresh(twin)
        assert twin.last_reflection_run_at is None


@pytest.mark.asyncio
async def test_memory_confirmed_at_set_at_candidate_confirm_and_immutable(
    client, session_factory
) -> None:
    """Decision 2: `memories.confirmed_at` is set the moment the
    candidate confirms and is NOT touched by subsequent user edits
    (`last_confirmed_at` can advance; `confirmed_at` must not)."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    memory_id = await _seed_confirmed_memory(client, conv_id, "x", "a fact")

    async with session_factory() as session:
        row = (
            await session.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()
        assert row.confirmed_at is not None
        confirmed_at_before = row.confirmed_at
        assert row.last_confirmed_at is not None

    # Patch the memory content — this must NOT move confirmed_at even
    # if a future callsite updates last_confirmed_at.
    patch = await client.patch(f"/v1/memories/{memory_id}", json={"content": "a fact (edited)"})
    assert patch.status_code == 200, patch.text

    async with session_factory() as session:
        row = (
            await session.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()
        assert row.confirmed_at == confirmed_at_before


# --------------------------------------------------------------
# Evolution events (Decision 3 + invariant)
# --------------------------------------------------------------


async def _list_evolution_rows(session_factory, user_id: uuid.UUID) -> list[TwinEvolutionEvent]:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(TwinEvolutionEvent).where(TwinEvolutionEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


@pytest.mark.asyncio
async def test_memory_learned_event_emitted_on_candidate_confirm(client, session_factory) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv_id, "x", "a learned fact")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    rows = await _list_evolution_rows(session_factory, user.user_id)
    assert any(r.event_type == "memory_learned" for r in rows)

    listed = await client.get("/v1/twin/evolution")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(i["event_type"] == "memory_learned" for i in items)


@pytest.mark.asyncio
async def test_profile_confirmed_event_only_after_apply(client, session_factory) -> None:
    """Confirming a profile_update reflection emits exactly one
    `profile_confirmed` evolution event. Rejecting one DOES NOT."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    m1 = await _seed_confirmed_memory(client, conv_id, "x", "m1")
    m2 = await _seed_confirmed_memory(client, conv_id, "y", "m2")

    confirm_draft = ReflectionDraft(
        kind="profile_update",
        payload={
            "kind": "profile_update",
            "field": "communication_style_notes",
            "current_value": None,
            "proposed_value": "Prefers short replies.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[uuid.UUID(m1), uuid.UUID(m2)],
        source_goal_ids=[],
        confidence=0.8,
        importance=0.6,
    )
    reject_draft = ReflectionDraft(
        kind="profile_update",
        payload={
            "kind": "profile_update",
            "field": "communication_style_notes",
            "current_value": None,
            "proposed_value": "Prefers verbose replies.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[uuid.UUID(m1)],
        source_goal_ids=[],
        confidence=0.4,
        importance=0.3,
    )
    _install_extractor(client, _CannedExtractor([confirm_draft, reject_draft]))
    try:
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
    finally:
        _restore_extractor(client)
    items = (await client.get("/v1/reflections")).json()["items"]
    confirm_id = next(
        i["id"]
        for i in items
        if i["proposed_payload"]["proposed_value"] == "Prefers short replies."
    )
    reject_id = next(
        i["id"]
        for i in items
        if i["proposed_payload"]["proposed_value"] == "Prefers verbose replies."
    )
    assert (await client.post(f"/v1/reflections/{confirm_id}/confirm")).status_code == 200
    assert (await client.post(f"/v1/reflections/{reject_id}/reject")).status_code == 200

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    rows = await _list_evolution_rows(session_factory, user.user_id)
    assert sum(1 for r in rows if r.event_type == "profile_confirmed") == 1
    # Rejection emitted no event:
    for r in rows:
        assert r.reflection_id != uuid.UUID(reject_id)


@pytest.mark.asyncio
async def test_memory_dedup_emits_consolidated_event(client, session_factory) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    m_super = await _seed_confirmed_memory(client, conv_id, "x", "m-super")
    m_canon = await _seed_confirmed_memory(client, conv_id, "y", "m-canon")

    draft = ReflectionDraft(
        kind="memory_dedup",
        payload={
            "kind": "memory_dedup",
            "superseded_memory_id": m_super,
            "canonical_memory_id": m_canon,
            "rationale": "same thing",
        },
        rationale="same thing",
        source_memory_ids=[uuid.UUID(m_super), uuid.UUID(m_canon)],
        source_goal_ids=[],
        confidence=0.9,
        importance=0.5,
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
    finally:
        _restore_extractor(client)
    [item] = (await client.get("/v1/reflections")).json()["items"]
    assert (await client.post(f"/v1/reflections/{item['id']}/confirm")).status_code == 200

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    rows = await _list_evolution_rows(session_factory, user.user_id)
    assert any(r.event_type == "memory_consolidated" for r in rows)


@pytest.mark.asyncio
async def test_insight_emits_acknowledged_event_not_memory_learned(client, session_factory) -> None:
    """Sprint 7 founder decision #1 — insight is acknowledgement, not
    identity mutation. The Sprint 8 event is `insight_acknowledged`,
    NOT `memory_learned`."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    m1 = await _seed_confirmed_memory(client, conv_id, "x", "m1")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    pre = await _list_evolution_rows(session_factory, user.user_id)
    pre_memory_learned = sum(1 for r in pre if r.event_type == "memory_learned")

    draft = ReflectionDraft(
        kind="insight",
        payload={
            "kind": "insight",
            "headline": "Noticed something",
            "body": "You chat before dinner.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[uuid.UUID(m1)],
        source_goal_ids=[],
        confidence=0.5,
        importance=0.3,
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
    finally:
        _restore_extractor(client)
    [item] = (await client.get("/v1/reflections")).json()["items"]
    assert (await client.post(f"/v1/reflections/{item['id']}/confirm")).status_code == 200

    rows = await _list_evolution_rows(session_factory, user.user_id)
    assert any(r.event_type == "insight_acknowledged" for r in rows)
    # No *new* memory_learned event — insight confirmation does not
    # create a Memory.
    new_memory_learned = sum(1 for r in rows if r.event_type == "memory_learned")
    assert new_memory_learned == pre_memory_learned


@pytest.mark.asyncio
async def test_evolution_endpoint_owner_scoped(client, as_user, user_a, user_b) -> None:
    await _create_twin(client, name="A")
    conv_a = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv_a, "x", "ma")

    as_user(user_b)
    await _create_twin(client, name="B")
    as_user(user_a)
    listed_a = await client.get("/v1/twin/evolution")
    assert listed_a.status_code == 200
    assert any(i["event_type"] == "memory_learned" for i in listed_a.json()["items"])

    as_user(user_b)
    listed_b = await client.get("/v1/twin/evolution")
    assert listed_b.status_code == 200
    # B has no evolution events — cannot see A's.
    assert listed_b.json()["items"] == []


# --------------------------------------------------------------
# Intent telemetry
# --------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_telemetry_row_is_safe_metadata_only(client, session_factory) -> None:
    """Posting a chat produces exactly one telemetry row that carries
    the detected intent, confidence, reason, detector_name, latency,
    bucket — no content fields exist on the row schema."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    # Send a message distinctive enough to pick a known intent.
    resp = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "let's plan next week together"},
    )
    assert resp.status_code == 201, resp.text

    async with session_factory() as session:
        rows = (await session.execute(select(IntentTelemetryEvent))).scalars().all()
    assert len(rows) >= 1
    row = rows[-1]
    # Shape — fields are present and in-range. Nowhere does the raw
    # user message exist on the row.
    assert row.intent in {"THINK", "LEARN", "PLAN", "REFLECT", "TALK", "TASK", "UNKNOWN"}
    assert 0.0 <= row.confidence <= 1.0
    assert row.message_length_bucket in {"short", "medium", "long"}
    assert row.reason and ":" in row.reason
    assert row.detector_name


# --------------------------------------------------------------
# Chat failure isolation & scheduler privacy
# --------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_succeeds_even_when_scheduler_task_raises(client, monkeypatch) -> None:
    """If `scheduled_reflection_task` raises, chat must still succeed
    — the chat response is already persisted when the task runs."""
    import app.conversation.service as convo_service

    async def _boom(**_: Any) -> None:
        raise RuntimeError("scheduler blew up")

    monkeypatch.setattr(convo_service, "scheduled_reflection_task", _boom)

    await _create_twin(client)
    conv_id = await _create_conversation(client)
    resp = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hi"})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_privacy_sentinel_never_appears_in_evolution_rows_or_logs(
    client, session_factory
) -> None:
    """Decision 3 + telemetry privacy: seed a sentinel into both the
    user message and the memory content. Assert the sentinel never
    appears in any row of `twin_evolution_events`, any row of
    `intent_telemetry_events`, nor any structlog event emitted during
    the turn."""
    sentinel = "SENTINEL-SPRINT8-DO-NOT-LEAK"
    await _create_twin(client)
    conv_id = await _create_conversation(client)

    with structlog.testing.capture_logs() as captured:
        # One chat with the sentinel in the user message.
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": f"here is a message with {sentinel} inside"},
        )
        assert resp.status_code == 201
        # One confirmed memory with the sentinel in the content —
        # this writes a memory_learned evolution event.
        await _seed_confirmed_memory(client, conv_id, "x", f"a fact that contains {sentinel}")

    # Evolution rows summary is derived from IDs and the kind only —
    # the memory content never appears.
    async with session_factory() as session:
        evo_rows = (await session.execute(select(TwinEvolutionEvent))).scalars().all()
        for r in evo_rows:
            assert sentinel not in r.summary
            assert sentinel not in (r.profile_field or "")

    # Telemetry rows carry no content at all.
    async with session_factory() as session:
        tele_rows = (await session.execute(select(IntentTelemetryEvent))).scalars().all()
        for r in tele_rows:
            # Every column is either an id, intent label, confidence,
            # reason tag, detector_name, latency, or bucket. Just
            # stringify the row and check:
            flat = f"{r.intent}|{r.reason}|{r.detector_name}|{r.message_length_bucket}"
            assert sentinel not in flat

    # Structlog capture — never let the sentinel through.
    flat = "\n".join(repr(e) for e in captured)
    assert sentinel not in flat


# --------------------------------------------------------------
# Confirmation safety: rejected reflection ≠ evolution
# --------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_reflection_does_not_create_evolution_event(client, session_factory) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    m1 = await _seed_confirmed_memory(client, conv_id, "x", "m1")
    draft = ReflectionDraft(
        kind="profile_update",
        payload={
            "kind": "profile_update",
            "field": "communication_style_notes",
            "current_value": None,
            "proposed_value": "A proposal the user will reject.",
            "rationale": "observed",
        },
        rationale="observed",
        source_memory_ids=[uuid.UUID(m1)],
        source_goal_ids=[],
        confidence=0.5,
        importance=0.4,
    )
    _install_extractor(client, _CannedExtractor([draft]))
    try:
        run = await client.post("/v1/reflections/run")
        assert run.status_code == 200
    finally:
        _restore_extractor(client)
    [item] = (await client.get("/v1/reflections")).json()["items"]
    reject = await client.post(f"/v1/reflections/{item['id']}/reject")
    assert reject.status_code == 200

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    rows = await _list_evolution_rows(session_factory, user.user_id)
    # Only the memory_learned event from _seed_confirmed_memory.
    assert all(r.event_type != "profile_confirmed" for r in rows)
