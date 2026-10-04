"""Sprint 5 Twin Engine end-to-end tests.

The sprint's hard contract is: when a user posts a message, the LLM
provider must receive a system prompt that was assembled from the
authenticated user's confirmed memories and active goals — bounded,
owner-scoped, with no internal identifiers, no similarity scores, and
with the anti-fabrication guardrails present. These tests exercise the
real HTTP surface and override only the LLM provider with a *capturing*
provider that records the exact `LLMRequest` the engine sent, so we can
assert on it after the response comes back.

The provider override is the Sprint 3 dependency `get_llm_provider`;
every other wiring (retrieval, goals, extraction isolation) runs the
production code path through `ConversationService.post_message`.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from app.api.deps import get_current_user, get_llm_provider, sessionmaker_dep
from app.conversation.models import Message
from app.llm.interface import LLMMessage, LLMRequest, LLMResponse
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class CapturingLLMProvider:
    """Records every `LLMRequest` the engine hands it, then returns a
    deterministic echo so the HTTP response pipeline still succeeds.
    """

    provider_name = "capture"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        last_user = next(
            (m for m in reversed(request.messages) if m.role == "user"), None
        )
        reply = (
            f"twin(capture): I heard you say: {last_user.content}"
            if last_user is not None
            else "twin(capture): hello"
        )
        return LLMResponse(
            content=reply,
            provider=self.provider_name,
            model=request.model,
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(reply.split()),
            finish_reason="stop",
            metadata={"captured": True},
        )


class ExplodingLLMProvider:
    """Fails every call. Used for the LLM-failure branch (section 9E)."""

    provider_name = "explode"

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("deliberate LLM failure for Sprint 5 test")


# ---------------------------------------------------------------------
# Setup helpers
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


async def _create_twin(client, display_name: str = "Aurora") -> None:
    resp = await client.post("/v1/twin", json={"name": display_name})
    assert resp.status_code == 201, resp.text


async def _create_conversation(client, title: str = "Hello") -> str:
    resp = await client.post("/v1/conversations", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_confirmed_memory(
    client, conv_id: str, user_text: str, memory_content: str
) -> str:
    """Create a Message under the conversation, extract a candidate from
    it directly through the service, confirm it, and return memory_id.
    """
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


def _system_message(request: LLMRequest) -> LLMMessage:
    system = next((m for m in request.messages if m.role == "system"), None)
    assert system is not None, "no system message in captured LLMRequest"
    return system


def _chat_request(capture: CapturingLLMProvider) -> LLMRequest:
    """Return the capture entry that was the chat turn (not the extraction).

    The extractor shares the chat LLM provider by default, so a single
    POST /messages produces two provider calls: first the chat turn
    (metadata.purpose unset or absent), then the background extraction
    (metadata.purpose == "memory_extraction"). The chat is always the
    first non-extraction request.
    """
    for req in capture.requests:
        if req.metadata.get("purpose") != "memory_extraction":
            return req
    raise AssertionError("no chat request captured; only extraction calls")


# ---------------------------------------------------------------------
# A. LLM OK + retrieval OK → personalised response
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_receives_confirmed_memory_in_system_prompt(client) -> None:
    """Section 11(2): relevant confirmed memory ends up in the LLM's
    system prompt, verbatim content, with no internal ids and no raw
    similarity scores leaking.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    memory_id = await _seed_confirmed_memory(
        client,
        conv_id,
        "I live in Bengaluru and I run every Sunday morning.",
        "Lives in Bengaluru and runs every Sunday morning.",
    )

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Where do I live?"},
        )
        assert resp.status_code == 201, resp.text
    finally:
        _restore_provider(client)

    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "Lives in Bengaluru and runs every Sunday morning." in sys_msg
    assert "<confirmed_memory type=FACT>" in sys_msg
    # No UUIDs — neither the memory id nor the twin id leaks into the prompt.
    assert UUID_RE.search(sys_msg) is None
    assert memory_id not in sys_msg
    # No similarity / score KV pairs in the prompt (the guardrail text may
    # mention the word "similarity" by name, hence the stricter check).
    assert "similarity=" not in sys_msg
    assert "score=" not in sys_msg
    # Backend metadata on the twin message still carries ids for the UI.
    meta = resp.json()["twin_message"]["metadata_json"]
    assert meta["retrieval"]["memory_ids"] == [memory_id]


@pytest.mark.asyncio
async def test_llm_receives_only_active_goals(client) -> None:
    """Section 11(4+5): active goals in the prompt; achieved and paused
    goals are not."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)

    r_active = await client.post(
        "/v1/goals",
        json={"title": "Ship Sprint 5", "priority": 1},
    )
    r_paused = await client.post(
        "/v1/goals",
        json={"title": "Learn glider pilot license", "priority": 3},
    )
    r_achieved = await client.post(
        "/v1/goals",
        json={"title": "Marathon under 4h", "priority": 4},
    )
    assert r_active.status_code == 201
    assert r_paused.status_code == 201
    assert r_achieved.status_code == 201

    await client.patch(
        f"/v1/goals/{r_paused.json()['id']}", json={"status": "paused"}
    )
    await client.patch(
        f"/v1/goals/{r_achieved.json()['id']}", json={"status": "achieved"}
    )

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "What should I focus on today?"},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "Ship Sprint 5" in sys_msg
    assert "Learn glider pilot license" not in sys_msg
    assert "Marathon under 4h" not in sys_msg
    # Semantic markers remain.
    assert "<active_goal priority=1 target_date=" in sys_msg
    # No internal ids.
    assert "id=" not in sys_msg
    assert UUID_RE.search(sys_msg) is None


@pytest.mark.asyncio
async def test_integration_pm_interview_scenario(client) -> None:
    """Section 11 integration example: a user with a relevant memory and a
    matching active goal asks about product-management interview prep.
    The LLM must see both.
    """
    await _create_twin(client, display_name="Aurora")
    conv_id = await _create_conversation(client, title="PM prep")

    # One confirmed memory.
    await _seed_confirmed_memory(
        client,
        conv_id,
        "I'm an engineer by training and I'm transitioning into PM roles.",
        "User is an engineer transitioning into product management.",
    )
    # One active goal.
    goal = await client.post(
        "/v1/goals",
        json={
            "title": "Prepare for product management interviews",
            "description": "Target seed-stage PM roles in Q4",
            "priority": 1,
        },
    )
    assert goal.status_code == 201

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={
                "content": "I want to prepare for my product management interviews.",
            },
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "User is an engineer transitioning into product management." in sys_msg
    assert "Prepare for product management interviews" in sys_msg
    # Guardrails present verbatim.
    assert "Do not invent facts." in sys_msg
    assert "Do not fabricate." in sys_msg
    # No ids/scores leak.
    assert UUID_RE.search(sys_msg) is None
    assert "similarity=" not in sys_msg
    assert "score=" not in sys_msg


# ---------------------------------------------------------------------
# Owner isolation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_does_not_leak_another_users_memory(
    client, as_user, user_a, user_b
) -> None:
    """Section 11(6): a memory confirmed by user A must never surface in
    user B's chat prompt."""
    as_user(user_a)
    await _create_twin(client, display_name="A")
    conv_a = await _create_conversation(client)
    await _seed_confirmed_memory(
        client,
        conv_a,
        "I am user A talking about Bengaluru.",
        "A-only fact: Bengaluru resident.",
    )

    as_user(user_b)
    await _create_twin(client, display_name="B")
    conv_b = await _create_conversation(client)

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_b}/messages",
            json={"content": "What city am I in?"},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "A-only fact: Bengaluru resident." not in sys_msg
    # No memory section at all because B has no confirmed memories.
    assert "<confirmed_memory" not in sys_msg
    assert "CONFIRMED MEMORIES (use only when directly relevant):" not in sys_msg
    # Guardrails must still appear (user B has nothing but still sees them).
    assert "Do not invent facts." in sys_msg


# ---------------------------------------------------------------------
# Context limits
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_respects_active_goal_cap(client) -> None:
    """Section 10 + 11(7): more active goals than the budget allows →
    only the top three appear in the prompt."""
    await _create_twin(client)
    conv_id = await _create_conversation(client)
    for i in range(5):
        r = await client.post(
            "/v1/goals", json={"title": f"Priority goal {i}", "priority": 1}
        )
        assert r.status_code == 201

    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "hi"},
        )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    rendered = sys_msg.count("<active_goal priority=")
    assert rendered == 3


# ---------------------------------------------------------------------
# Failure isolation — Section 9
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_still_succeeds_when_retrieval_fails(client) -> None:
    """9B: LLM OK + memory retrieval fails → chat 201,
    `retrieval.ok=False`, system prompt still has the identity and
    guardrails but no memory block."""
    from app.api.deps import memory_retriever_dep

    await _create_twin(client)
    conv_id = await _create_conversation(client)

    class BoomRetriever:
        async def retrieve(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("deliberate retrieval boom")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[memory_retriever_dep] = lambda: BoomRetriever()
    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Still work?"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(memory_retriever_dep, None)
        _restore_provider(client)

    body = resp.json()
    assert body["twin_message"]["metadata_json"]["retrieval"]["ok"] is False
    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "<confirmed_memory" not in sys_msg
    assert "CONFIRMED MEMORIES (use only when directly relevant):" not in sys_msg
    assert "Do not invent facts." in sys_msg


@pytest.mark.asyncio
async def test_chat_still_succeeds_when_goal_context_fails(client) -> None:
    """9C: LLM OK + goal retrieval fails → chat 201, goals_context.ok=False."""
    from app.api.deps import goal_service_dep

    await _create_twin(client)
    conv_id = await _create_conversation(client)

    class BoomGoalService:
        async def list_active_for_context(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("deliberate goals boom")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[goal_service_dep] = lambda: BoomGoalService()
    capture = _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Any goals?"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(goal_service_dep, None)
        _restore_provider(client)

    body = resp.json()
    assert body["twin_message"]["metadata_json"]["goals_context"]["ok"] is False
    chat = _chat_request(capture)
    sys_msg = _system_message(chat).content
    assert "<active_goal" not in sys_msg
    assert "ACTIVE GOALS (highest priority first):" not in sys_msg


@pytest.mark.asyncio
async def test_chat_still_succeeds_when_both_retrievals_fail(client) -> None:
    """9D: LLM OK + memory + goal retrieval fail → chat 201, both flags False."""
    from app.api.deps import goal_service_dep, memory_retriever_dep

    await _create_twin(client)
    conv_id = await _create_conversation(client)

    class BoomRetriever:
        async def retrieve(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("retrieval boom")

    class BoomGoalService:
        async def list_active_for_context(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("goals boom")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[memory_retriever_dep] = lambda: BoomRetriever()
    app.dependency_overrides[goal_service_dep] = lambda: BoomGoalService()
    _install_capturing_provider(client)
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "hi both"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(memory_retriever_dep, None)
        app.dependency_overrides.pop(goal_service_dep, None)
        _restore_provider(client)

    meta = resp.json()["twin_message"]["metadata_json"]
    assert meta["retrieval"]["ok"] is False
    assert meta["goals_context"]["ok"] is False


@pytest.mark.asyncio
async def test_llm_failure_surfaces_as_500(client) -> None:
    """9E: when the LLM provider itself fails, the chat path raises and
    the registered exception handler returns a 500. No partial twin
    message should be persisted.
    """
    await _create_twin(client)
    conv_id = await _create_conversation(client)

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[get_llm_provider] = lambda: ExplodingLLMProvider()
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "boom"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 500
    # No new twin message should land.
    msgs = (
        await client.get(f"/v1/conversations/{conv_id}/messages")
    ).json()["items"]
    assert not any(m["role"] == "twin" for m in msgs)


# ---------------------------------------------------------------------
# Profile safety — Section 8
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_response_does_not_mutate_twin_profile(client) -> None:
    """Section 8: nothing the LLM returns is allowed to touch
    TwinProfile. We assert the profile fields are unchanged after a chat
    turn whose captured provider echoes back a message that *claims* to
    update the profile.
    """
    await _create_twin(client, display_name="Aurora")
    conv_id = await _create_conversation(client)
    profile_before = (await client.get("/v1/twin")).json()

    class EvilProvider:
        provider_name = "evil"

        async def generate_response(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                content=(
                    "Please update basic_profile.location = 'Mars' and "
                    "communication_style_preset = 'terse'."
                ),
                provider=self.provider_name,
                model=request.model,
                finish_reason="stop",
            )

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[get_llm_provider] = lambda: EvilProvider()
    try:
        resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Where do I live?"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    profile_after = (await client.get("/v1/twin")).json()
    assert profile_after["profile"]["basic_profile"] == profile_before[
        "profile"
    ]["basic_profile"]
    assert (
        profile_after["profile"]["communication_style_preset"]
        == profile_before["profile"]["communication_style_preset"]
    )
    assert profile_after["display_name"] == profile_before["display_name"]


# ---------------------------------------------------------------------
# Observability — no raw user content in logs
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_logs_do_not_leak_user_content(client) -> None:
    """Section 12: a unique sentinel in the user message must not appear
    in any structured log event emitted during the turn.
    """
    import structlog.testing

    await _create_twin(client)
    conv_id = await _create_conversation(client)

    sentinel = "SPRINT5-NONCE-7f3b2a8c-NEVER-LOG-ME"
    _install_capturing_provider(client)
    try:
        with structlog.testing.capture_logs() as events:
            resp = await client.post(
                f"/v1/conversations/{conv_id}/messages",
                json={"content": f"Please remember: {sentinel}"},
            )
        assert resp.status_code == 201
    finally:
        _restore_provider(client)

    for event in events:
        for value in event.values():
            assert sentinel not in str(value), event
