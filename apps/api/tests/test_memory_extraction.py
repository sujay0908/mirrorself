"""Memory extraction pipeline: conversation → background task → candidates.

The extractor is a pure function that uses an LLMProvider. For tests, we
swap in a `FixtureExtractionProvider` that returns canned JSON. The
MockProvider (echo) is used to prove that non-parseable output yields an
empty extraction.

Also pins two hard invariants:
- NO TwinProfile mutation anywhere on the LLM path.
- Memory extraction failure NEVER fails the chat response.
"""

from __future__ import annotations

import pytest
import structlog
from sqlalchemy import select

from app.api.deps import extraction_llm_provider_dep, get_llm_provider
from app.conversation.models import Message
from app.llm.providers.mock import MockProvider
from app.memory.extractor import MemoryExtractor
from app.memory.models import MemoryCandidate
from app.twin.models import TwinProfile
from tests._helpers import FixtureExtractionProvider

# ---------- Extractor as a pure function ----------


@pytest.mark.asyncio
async def test_extractor_returns_empty_on_trivial_user_message() -> None:
    extractor = MemoryExtractor(MockProvider(), model="mock-echo")
    result = await extractor.extract(
        user_message="hi",
        twin_response="hello there",
        twin_profile=None,
    )
    assert result.drafts == []
    assert result.error is None


@pytest.mark.asyncio
async def test_extractor_returns_empty_when_response_is_not_json() -> None:
    extractor = MemoryExtractor(MockProvider(), model="mock-echo")
    result = await extractor.extract(
        user_message="I was born in 1992 and I live in Bengaluru.",
        twin_response="noted.",
        twin_profile=None,
    )
    assert result.drafts == []


@pytest.mark.asyncio
async def test_extractor_parses_well_formed_json() -> None:
    fixture = FixtureExtractionProvider(
        '{"candidates":[{"type":"FACT","content":"I live in Bengaluru.",'
        '"confidence":0.9,"importance":0.8,"rationale":"stated location"}]}'
    )
    extractor = MemoryExtractor(fixture, model="fixture-model")
    result = await extractor.extract(
        user_message="I just moved to Bengaluru last month.",
        twin_response="congrats on the move",
        twin_profile=None,
    )
    assert len(result.drafts) == 1
    assert result.drafts[0].type == "FACT"
    assert result.drafts[0].content == "I live in Bengaluru."
    assert result.drafts[0].confidence == 0.9
    assert result.error is None


@pytest.mark.asyncio
async def test_extractor_handles_markdown_fenced_json() -> None:
    fixture = FixtureExtractionProvider(
        "```json\n"
        '{"candidates":[{"type":"PREFERENCE","content":"Prefers concise replies.",'
        '"confidence":0.8,"importance":0.6}]}\n'
        "```"
    )
    extractor = MemoryExtractor(fixture, model="fixture-model")
    result = await extractor.extract(
        user_message="Please keep responses short and to the point.",
        twin_response="Will do.",
        twin_profile=None,
    )
    assert len(result.drafts) == 1
    assert result.drafts[0].type == "PREFERENCE"


@pytest.mark.asyncio
async def test_extractor_tolerates_schema_mismatch() -> None:
    fixture = FixtureExtractionProvider('{"wrong_shape": true}')
    extractor = MemoryExtractor(fixture, model="fixture-model")
    result = await extractor.extract(
        user_message="Some substantive user message here.",
        twin_response="Response.",
        twin_profile=None,
    )
    assert result.drafts == []


@pytest.mark.asyncio
async def test_extractor_provider_error_is_captured_not_raised() -> None:
    """Provider failure in extraction returns a labelled result, no raise."""

    class BrokenProvider:
        provider_name = "broken"

        async def generate_response(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("extraction provider boom")

    extractor = MemoryExtractor(BrokenProvider(), model="x")  # type: ignore[arg-type]
    result = await extractor.extract(
        user_message="A substantive user message long enough.",
        twin_response="Twin reply.",
        twin_profile=None,
    )
    assert result.drafts == []
    assert result.error == "provider_error:RuntimeError"


# ---------- Pipeline integration ----------


@pytest.mark.asyncio
async def test_pipeline_persists_candidate_in_background(client, session_factory) -> None:
    """A conversation message with a FixtureExtractionProvider seeded for
    chat (and, by default inheritance, extraction) produces a pending
    candidate.
    """
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    fixture = FixtureExtractionProvider(
        '{"candidates":[{"type":"FACT","content":"I live in Bengaluru.",'
        '"confidence":0.9,"importance":0.8}]}'
    )
    app.dependency_overrides[get_llm_provider] = lambda: fixture

    try:
        await client.post("/v1/twin", json={"name": "Aurora"})
        conv = (await client.post("/v1/conversations", json={"title": "t"})).json()
        posted = await client.post(
            f"/v1/conversations/{conv['id']}/messages",
            json={"content": "I just moved to Bengaluru last month."},
        )
        assert posted.status_code == 201
        candidates = (await client.get("/v1/memory-candidates")).json()["items"]
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    assert len(candidates) == 1
    assert candidates[0]["type"] == "FACT"
    assert candidates[0]["content"] == "I live in Bengaluru."
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["source_message_id"] is not None
    assert candidates[0]["source_conversation_id"] == conv["id"]


@pytest.mark.asyncio
async def test_pipeline_with_mock_provider_produces_no_candidates(client) -> None:
    """MockProvider's echo output never parses as the extraction JSON schema,
    so a chat turn produces zero candidates. This is the safe default.
    """
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={"title": "t"})).json()
    await client.post(
        f"/v1/conversations/{conv['id']}/messages",
        json={"content": "I was born in Mysore and I live in Bengaluru now."},
    )
    candidates = (await client.get("/v1/memory-candidates")).json()["items"]
    assert candidates == []


@pytest.mark.asyncio
async def test_profile_unchanged_after_extraction(client, session_factory) -> None:
    """CRITICAL: no LLM path (chat or extraction) may mutate TwinProfile."""
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    fixture = FixtureExtractionProvider(
        '{"candidates":[{"type":"FACT","content":"test fact","confidence":0.9,"importance":0.8}]}'
    )
    app.dependency_overrides[get_llm_provider] = lambda: fixture

    await client.post(
        "/v1/twin",
        json={
            "name": "Aurora",
            "communication_style": "warm",
            "basic_profile": {"colour": "blue"},
        },
    )

    async with session_factory() as s:
        profile = (await s.execute(select(TwinProfile))).scalar_one()
        before = (
            profile.id,
            profile.communication_style_preset,
            profile.communication_style_notes,
            dict(profile.basic_profile),
            profile.updated_at,
        )

    try:
        conv = (await client.post("/v1/conversations", json={})).json()
        for turn in range(3):
            await client.post(
                f"/v1/conversations/{conv['id']}/messages",
                json={"content": f"user turn number {turn} with substantive content"},
            )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    async with session_factory() as s:
        profile = (await s.execute(select(TwinProfile))).scalar_one()
        after = (
            profile.id,
            profile.communication_style_preset,
            profile.communication_style_notes,
            dict(profile.basic_profile),
            profile.updated_at,
        )

    assert before == after


@pytest.mark.asyncio
async def test_extraction_failure_does_not_fail_chat(client, session_factory) -> None:
    """ARCHITECTURAL INVARIANT (Sprint 2 close-out):

    Chat and extraction use independent FastAPI deps so the extraction
    provider can fail without failing the chat response. The chat uses the
    default `MockProvider` (echo) and succeeds; the extraction provider is
    overridden to raise.

    Requirements proved:
    - POST /v1/conversations/{id}/messages returns 201.
    - user message + twin message exist.
    - no partial memory_candidate exists.
    - extraction failure is observable through structured telemetry.
    - no user message content appears in any emitted log event.
    """
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app

    class BrokenExtractionProvider:
        provider_name = "broken-extract"

        async def generate_response(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("extraction provider intentionally failing for test")

    # A phrase unlikely to appear in any system log line, used to prove the
    # user's message content never leaks into telemetry.
    secret_user_phrase = "quokka-paradox-7391-ultraviolet"

    app.dependency_overrides[extraction_llm_provider_dep] = lambda: BrokenExtractionProvider()

    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={"title": "t"})).json()

    try:
        with structlog.testing.capture_logs() as captured:
            resp = await client.post(
                f"/v1/conversations/{conv['id']}/messages",
                json={"content": f"I just moved to {secret_user_phrase} last month."},
            )
    finally:
        app.dependency_overrides.pop(extraction_llm_provider_dep, None)

    # 1. Chat succeeds.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == (f"I just moved to {secret_user_phrase} last month.")
    assert body["twin_message"]["role"] == "twin"
    assert body["twin_message"]["content"].startswith("twin(mock):")

    # 2. Messages persisted (user + twin, exactly two rows).
    async with session_factory() as s:
        msgs = (await s.execute(select(Message))).scalars().all()
        assert len(msgs) == 2
        assert sorted(m.role for m in msgs) == ["twin", "user"]

        # 3. No partial candidate persisted.
        candidates = (await s.execute(select(MemoryCandidate))).scalars().all()
        assert candidates == []

    # 4. Extraction failure is observable through structlog telemetry.
    failure_events = [e for e in captured if e.get("event") == "memory.extraction.failed"]
    assert failure_events, f"Expected memory.extraction.failed event. Captured: {captured!r}"
    ev = failure_events[0]
    assert ev["reason"] == "provider_error:RuntimeError"
    assert ev["conversation_id"] == str(conv["id"])
    assert "user_message_id" in ev
    assert "twin_message_id" in ev
    assert ev["log_level"] in {"warning", "error"}

    # 5. SAFETY: user message content must NOT appear in any emitted event.
    for e in captured:
        for value in e.values():
            if isinstance(value, str):
                assert secret_user_phrase not in value, (
                    f"User message content leaked into log event: {e!r}"
                )
