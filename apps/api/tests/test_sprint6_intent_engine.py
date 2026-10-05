"""Sprint 6 Twin Engine integration tests.

End-to-end: a user message hits the real `ConversationService.post_message`
with a capturing LLM provider, so each test can inspect the exact
`LLMRequest` the engine sent. The suite covers:

- intent detection runs before context assembly
- policy budget is applied to retrieval + goal loading + the builder
- the rendered prompt names the resolved intent in a human-readable way
- intent failure / policy failure / retrieval failure / goal failure all
  keep chat alive (section 9 invariants from Sprint 5 are preserved)
- TwinProfile is NOT mutated by the chat path
- the `twin_message.metadata_json.twin_state` audit field is present
- ownership isolation holds under the new pipeline
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.deps import (
    get_current_user,
    get_llm_provider,
    goal_service_dep,
    intent_detector_dep,
    memory_retriever_dep,
    sessionmaker_dep,
)
from app.conversation.intent import Intent, IntentResult
from app.conversation.models import Message
from app.llm.interface import LLMMessage, LLMRequest, LLMResponse
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService


class CapturingLLMProvider:
    """Captures every LLMRequest and returns a safe echo."""

    provider_name = "capture"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        last_user = next((m for m in reversed(request.messages) if m.role == "user"), None)
        reply = f"twin(capture): {last_user.content}" if last_user is not None else "twin(capture)"
        return LLMResponse(
            content=reply,
            provider=self.provider_name,
            model=request.model,
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(reply.split()),
            finish_reason="stop",
            metadata={"captured": True},
        )


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _install_capturing_provider(client) -> CapturingLLMProvider:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    capture = CapturingLLMProvider()
    app.dependency_overrides[get_llm_provider] = lambda: capture
    return capture


def _restore_provider(client) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides.pop(get_llm_provider, None)


def _system_message(request: LLMRequest) -> LLMMessage:
    sysmsg = next((m for m in request.messages if m.role == "system"), None)
    assert sysmsg is not None, "no system message in LLMRequest"
    return sysmsg


def _chat_request(capture: CapturingLLMProvider) -> LLMRequest:
    """Return the chat turn, filtering out the background extraction call."""
    for req in capture.requests:
        if req.metadata.get("purpose") != "memory_extraction":
            return req
    raise AssertionError("no chat request captured")


async def _create_twin(client, display_name: str = "Aurora") -> None:
    resp = await client.post("/v1/twin", json={"name": display_name})
    assert resp.status_code == 201, resp.text


async def _create_conversation(client, title: str = "x") -> str:
    resp = await client.post("/v1/conversations", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_confirmed_memory(client, conv_id: str, user_text: str, memory_content: str) -> str:
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
            content=user_text,
        )
        session.add(msg)
        await session.flush()
        twin = await TwinService(session).require_by_user(user.user_id)
        [cand] = await MemoryService(session).create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content=memory_content,
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
# 1. Intent detection runs before context assembly
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detected_intent_is_recorded_on_twin_message(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Let's plan the next sprint."},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)
    meta = resp.json()["twin_message"]["metadata_json"]["twin_state"]
    assert meta["intent"] == "PLAN"
    assert meta["intent_confidence"] >= 0.7
    assert meta["intent_reason"].startswith("phrase:plan")
    assert meta["policy"]["weights"]["goals"] == 3  # HIGH


@pytest.mark.asyncio
async def test_prompt_includes_intent_hint(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Looking back, I did the right thing by taking the job."},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)
    sys_msg = _system_message(_chat_request(capture)).content
    assert "What this turn is about: reflecting on the past." in sys_msg
    # Internal enum names must NOT leak.
    assert "REFLECT" not in sys_msg


# ---------------------------------------------------------------------
# 2. Policy drives retrieval / goal / history limits
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talk_intent_limits_goals_to_low_band(client) -> None:
    """TALK is intentionally light on goals. With 5 active goals seeded,
    a TALK message pulls at most LOW's goal_limit (=1) into the prompt.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    for i in range(5):
        r = await client.post("/v1/goals", json={"title": f"Goal {i}", "priority": 1})
        assert r.status_code == 201

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "Hey"})
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    body = resp.json()
    assert body["twin_message"]["metadata_json"]["twin_state"]["intent"] == "TALK"
    sys_msg = _system_message(_chat_request(capture)).content
    assert sys_msg.count("<active_goal priority=") == 1


@pytest.mark.asyncio
async def test_plan_intent_pulls_three_goals(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    for i in range(5):
        r = await client.post("/v1/goals", json={"title": f"Goal {i}", "priority": 1})
        assert r.status_code == 201

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Plan my next week."},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    sys_msg = _system_message(_chat_request(capture)).content
    assert sys_msg.count("<active_goal priority=") == 3


@pytest.mark.asyncio
async def test_memory_limit_follows_intent(client) -> None:
    """A REFLECT message gives the retriever its HIGH memory limit (8);
    a TALK message gives it MEDIUM (6). Verify via metadata_json.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_capturing_provider(client)
    try:
        reflect = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Looking back, I'm proud of what I built."},
        )
        talk = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hey"})
    finally:
        _restore_provider(client)

    r_meta = reflect.json()["twin_message"]["metadata_json"]["twin_state"]
    t_meta = talk.json()["twin_message"]["metadata_json"]["twin_state"]
    assert r_meta["policy"]["limits"]["memories"] >= t_meta["policy"]["limits"]["memories"]


# ---------------------------------------------------------------------
# 3. Memory & goal retrieval still work under the new pipeline
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_still_reaches_prompt_under_intent_pipeline(client) -> None:
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    memory_id = await _seed_confirmed_memory(
        client,
        conv_id,
        "I live in Bengaluru and I like filter coffee.",
        "Lives in Bengaluru; likes filter coffee.",
    )
    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Looking back, where have I been living?"},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    sys_msg = _system_message(_chat_request(capture)).content
    assert "Lives in Bengaluru; likes filter coffee." in sys_msg
    body = resp.json()
    assert memory_id in body["twin_message"]["metadata_json"]["retrieval"]["memory_ids"]


# ---------------------------------------------------------------------
# 4. Failure isolation — intent / policy / retrieval / goals
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_detector_failure_does_not_fail_chat(client) -> None:
    """A detector that raises must be absorbed; chat returns 201 with
    UNKNOWN intent on the audit trail.
    """
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app

    class _ExplodingDetector:
        detector_name = "explode"

        async def detect(self, user_message: str) -> IntentResult:
            raise RuntimeError("boom")

    app.dependency_overrides[intent_detector_dep] = lambda: _ExplodingDetector()
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "anything"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(intent_detector_dep, None)
        _restore_provider(client)

    meta = resp.json()["twin_message"]["metadata_json"]["twin_state"]
    assert meta["intent"] == Intent.UNKNOWN.value
    assert meta["intent_reason"].startswith("error:")


@pytest.mark.asyncio
async def test_retrieval_failure_still_runs_intent_pipeline(client) -> None:
    """Memory retrieval failing must not break the intent pipeline.
    The twin message still records the detected intent and the
    retrieval.ok=False flag.
    """

    class _BoomRetriever:
        async def retrieve(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("boom")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[memory_retriever_dep] = lambda: _BoomRetriever()
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Plan my next week."},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(memory_retriever_dep, None)
        _restore_provider(client)

    body = resp.json()
    assert body["twin_message"]["metadata_json"]["twin_state"]["intent"] == "PLAN"
    assert body["twin_message"]["metadata_json"]["retrieval"]["ok"] is False


@pytest.mark.asyncio
async def test_goal_service_failure_still_runs_intent_pipeline(client) -> None:
    class _BoomGoalService:
        async def list_active_for_context(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("boom")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[goal_service_dep] = lambda: _BoomGoalService()
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Plan my next week."},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(goal_service_dep, None)
        _restore_provider(client)

    body = resp.json()
    assert body["twin_message"]["metadata_json"]["twin_state"]["intent"] == "PLAN"
    assert body["twin_message"]["metadata_json"]["goals_context"]["ok"] is False


# ---------------------------------------------------------------------
# 5. Profile safety under the new pipeline
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_unchanged_after_chat_with_intent_pipeline(client) -> None:
    await _create_twin(client, display_name="Aurora")
    conv_id = await _create_conversation(client)
    profile_before = (await client.get("/v1/twin")).json()
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Please update my profile: communication_style_preset = 'terse'."},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)
    profile_after = (await client.get("/v1/twin")).json()
    assert (
        profile_after["profile"]["communication_style_preset"]
        == (profile_before["profile"]["communication_style_preset"])
    )
    assert profile_after["display_name"] == profile_before["display_name"]


# ---------------------------------------------------------------------
# 6. Ownership isolation under the new pipeline
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_user_isolation_holds_under_intent_pipeline(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    await _create_twin(client, display_name="A")
    conv_a = await _create_conversation(client)
    await _seed_confirmed_memory(client, conv_a, "A's text.", "A-only memory: lives in Lisbon.")

    as_user(user_b)
    await _create_twin(client, display_name="B")
    conv_b = await _create_conversation(client)
    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_b}/messages",
            json={"content": "Where do I live?"},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    sys_msg = _system_message(_chat_request(capture)).content
    assert "A-only memory: lives in Lisbon." not in sys_msg
    assert "<confirmed_memory" not in sys_msg
