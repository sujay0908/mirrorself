"""Chat sends are idempotent, ordered, bounded and all-or-nothing."""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest
from sqlalchemy import func, select

from app.api.deps import get_llm_provider
from app.conversation.models import Conversation, Message
from app.conversation.service import ConversationService, MessageInProgressError
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse
from app.twin.models import Twin


class CountingProvider(LLMProvider):
    """Echoes, and remembers every request it was given."""

    provider_name: ClassVar[str] = "counting"

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        last_user = next(m for m in reversed(request.messages) if m.role == "user")
        return LLMResponse(
            content=f"reply to: {last_user.content}",
            provider=self.provider_name,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
        )


class FailingProvider(LLMProvider):
    provider_name: ClassVar[str] = "failing"

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("model call failed")


def _app(client):
    return client._transport.app  # type: ignore[attr-defined]


@pytest.fixture
def provider(client) -> CountingProvider:
    counting = CountingProvider()
    _app(client).dependency_overrides[get_llm_provider] = lambda: counting
    yield counting
    _app(client).dependency_overrides.pop(get_llm_provider, None)


async def _conversation(client, title: str | None = None) -> str:
    await client.post("/v1/twin", json={"name": "Aurora"})
    body = {} if title is None else {"title": title}
    resp = await client.post("/v1/conversations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _message_count(session_factory, conversation_id: str) -> int:
    async with session_factory() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()


# ---------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_with_same_key_returns_the_original_exchange(
    client, provider, session_factory
) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    key = {"Idempotency-Key": "send-0001-abcdef"}

    first = await client.post(url, json={"content": "hello"}, headers=key)
    assert first.status_code == 201
    assert "idempotent-replayed" not in first.headers

    # The client timed out waiting and sends the same message again.
    second = await client.post(url, json={"content": "hello"}, headers=key)
    assert second.status_code == 200
    assert second.headers["idempotent-replayed"] == "true"

    assert second.json()["user_message"]["id"] == first.json()["user_message"]["id"]
    assert second.json()["twin_message"]["id"] == first.json()["twin_message"]["id"]
    assert second.json()["twin_message"]["content"] == "reply to: hello"
    # One model call, one stored exchange.
    assert len(provider.calls) == 1
    assert await _message_count(session_factory, conv) == 2


@pytest.mark.asyncio
async def test_different_keys_are_different_messages(client, provider, session_factory) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    a = await client.post(url, json={"content": "same text"}, headers={"Idempotency-Key": "k" * 8})
    b = await client.post(url, json={"content": "same text"}, headers={"Idempotency-Key": "j" * 8})
    assert a.status_code == b.status_code == 201
    assert a.json()["user_message"]["id"] != b.json()["user_message"]["id"]
    assert len(provider.calls) == 2
    assert await _message_count(session_factory, conv) == 4


@pytest.mark.asyncio
async def test_sends_without_a_key_are_never_deduplicated(
    client, provider, session_factory
) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    await client.post(url, json={"content": "again"})
    await client.post(url, json={"content": "again"})
    assert len(provider.calls) == 2
    assert await _message_count(session_factory, conv) == 4


@pytest.mark.asyncio
async def test_a_key_is_scoped_to_its_conversation(client, provider) -> None:
    first = await _conversation(client)
    second = (await client.post("/v1/conversations", json={})).json()["id"]
    key = {"Idempotency-Key": "shared-key-0001"}
    a = await client.post(f"/v1/conversations/{first}/messages", json={"content": "x"}, headers=key)
    b = await client.post(
        f"/v1/conversations/{second}/messages", json={"content": "x"}, headers=key
    )
    assert a.status_code == b.status_code == 201
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_another_users_key_cannot_replay_my_exchange(
    client, provider, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    conv = await _conversation(client)
    key = {"Idempotency-Key": "private-key-0001"}
    await client.post(f"/v1/conversations/{conv}/messages", json={"content": "secret"}, headers=key)

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "Other"})
    # Guessing the conversation id and the key gets a 404, not the exchange.
    resp = await client.post(
        f"/v1/conversations/{conv}/messages", json={"content": "secret"}, headers=key
    )
    assert resp.status_code == 404
    assert "secret" not in resp.text


@pytest.mark.parametrize("bad_key", ["short", "x" * 65, "has spaces in it", "semi;colon-key"])
@pytest.mark.asyncio
async def test_malformed_keys_are_rejected(client, provider, bad_key: str) -> None:
    conv = await _conversation(client)
    resp = await client.post(
        f"/v1/conversations/{conv}/messages",
        json={"content": "hi"},
        headers={"Idempotency-Key": bad_key},
    )
    assert resp.status_code == 422
    assert provider.calls == []


@pytest.mark.asyncio
async def test_the_key_is_not_exposed_in_responses(client, provider) -> None:
    conv = await _conversation(client)
    key = "internal-handle-0001"
    resp = await client.post(
        f"/v1/conversations/{conv}/messages",
        json={"content": "hi"},
        headers={"Idempotency-Key": key},
    )
    assert key not in resp.text
    listed = await client.get(f"/v1/conversations/{conv}/messages")
    assert key not in listed.text


@pytest.mark.asyncio
async def test_a_key_still_in_flight_is_refused_not_duplicated(
    client, provider, session_factory
) -> None:
    """Two requests with one key at the same moment: the second must not run
    a second model call. The first request's user turn exists but has no
    stored reply yet, which is what "in flight" looks like to the second."""
    conv = await _conversation(client)
    key = "in-flight-key-0001"
    async with session_factory() as s:
        s.add(
            Message(
                conversation_id=uuid.UUID(conv),
                role="user",
                content="hello",
                client_request_id=key,
                metadata_json={"reply_message_id": str(uuid.uuid4())},
            )
        )
        await s.commit()

    resp = await client.post(
        f"/v1/conversations/{conv}/messages",
        json={"content": "hello"},
        headers={"Idempotency-Key": key},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "message_in_progress"
    assert resp.headers["retry-after"] == "3"
    assert provider.calls == []
    assert await _message_count(session_factory, conv) == 1


@pytest.mark.asyncio
async def test_losing_the_insert_race_leaves_the_session_usable(session_factory) -> None:
    """The uniqueness violation is absorbed inside a savepoint, so the
    request's transaction and the objects already loaded in it survive."""
    key = "race-key-00000001"
    async with session_factory() as s:
        twin = Twin(user_id=uuid.uuid4(), display_name="Aurora")
        s.add(twin)
        await s.flush()
        conv = Conversation(twin_id=twin.id)
        s.add(conv)
        await s.flush()
        s.add(
            Message(
                conversation_id=conv.id,
                role="user",
                content="first",
                client_request_id=key,
                metadata_json={"reply_message_id": str(uuid.uuid4())},
            )
        )
        await s.commit()

        service = ConversationService(s, CountingProvider())
        duplicate = Message(
            conversation_id=conv.id, role="user", content="first", client_request_id=key
        )
        with pytest.raises(MessageInProgressError):
            await service._insert_user_message(conv, duplicate, key)
        # Still usable: a plain read in the same session works.
        assert (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 1
        assert conv.twin_id == twin.id


# ---------------------------------------------------------------------
# All-or-nothing
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_model_call_stores_nothing(client, session_factory) -> None:
    conv = await _conversation(client)
    _app(client).dependency_overrides[get_llm_provider] = lambda: FailingProvider()
    try:
        resp = await client.post(
            f"/v1/conversations/{conv}/messages",
            json={"content": "will fail"},
            headers={"Idempotency-Key": "failing-send-0001"},
        )
    finally:
        _app(client).dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 500
    assert "model call failed" not in resp.text
    # No orphan user turn, so the client can simply send again.
    assert await _message_count(session_factory, conv) == 0


@pytest.mark.asyncio
async def test_a_retry_after_failure_succeeds_with_the_same_key(client, session_factory) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    key = {"Idempotency-Key": "retry-after-fail-01"}
    app = _app(client)

    app.dependency_overrides[get_llm_provider] = lambda: FailingProvider()
    assert (await client.post(url, json={"content": "hi"}, headers=key)).status_code == 500

    working = CountingProvider()
    app.dependency_overrides[get_llm_provider] = lambda: working
    try:
        resp = await client.post(url, json={"content": "hi"}, headers=key)
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 201
    assert len(working.calls) == 1
    assert await _message_count(session_factory, conv) == 2


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["   ", "\n\n", "\t"])
@pytest.mark.asyncio
async def test_blank_messages_are_rejected(client, provider, blank: str) -> None:
    conv = await _conversation(client)
    resp = await client.post(f"/v1/conversations/{conv}/messages", json={"content": blank})
    assert resp.status_code == 422
    assert provider.calls == []


@pytest.mark.asyncio
async def test_surrounding_whitespace_is_trimmed(client, provider) -> None:
    conv = await _conversation(client)
    resp = await client.post(f"/v1/conversations/{conv}/messages", json={"content": "  hello  \n"})
    assert resp.json()["user_message"]["content"] == "hello"


# ---------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_order_is_stable_under_rapid_turns(client, provider) -> None:
    """Twenty turns sent as fast as the loop allows. On a coarse clock
    several land on one timestamp; the transcript must still read in the
    order it happened."""
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    for i in range(20):
        assert (await client.post(url, json={"content": f"m{i}"})).status_code == 201

    items = (await client.get(url)).json()["items"]
    expected: list[str] = []
    for i in range(20):
        expected += [f"m{i}", f"reply to: m{i}"]
    assert [m["content"] for m in items] == expected
    stamps = [m["created_at"] for m in items]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


# ---------------------------------------------------------------------
# Bounded reads
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_model_only_sees_a_bounded_window_of_history(client, provider) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    for i in range(15):
        await client.post(url, json={"content": f"turn {i}"})

    last = provider.calls[-1]
    turns = [m for m in last.messages if m.role != "system"]
    # The newest user message plus at most the policy's history window,
    # not all 28 earlier messages.
    assert len(turns) <= 7
    assert turns[-1].content == "turn 14"
    assert "turn 0" not in [m.content for m in turns]


@pytest.mark.asyncio
async def test_messages_can_be_paged_backwards(client, provider) -> None:
    conv = await _conversation(client)
    url = f"/v1/conversations/{conv}/messages"
    for i in range(5):
        await client.post(url, json={"content": f"m{i}"})

    newest = (await client.get(url, params={"limit": 4})).json()["items"]
    assert [m["content"] for m in newest] == ["m3", "reply to: m3", "m4", "reply to: m4"]

    older = (await client.get(url, params={"limit": 4, "before": newest[0]["id"]})).json()["items"]
    assert [m["content"] for m in older] == ["m1", "reply to: m1", "m2", "reply to: m2"]


@pytest.mark.asyncio
async def test_a_cursor_from_another_conversation_matches_nothing(client, provider) -> None:
    conv = await _conversation(client)
    other = (await client.post("/v1/conversations", json={})).json()["id"]
    sent = await client.post(f"/v1/conversations/{other}/messages", json={"content": "x"})
    await client.post(f"/v1/conversations/{conv}/messages", json={"content": "y"})

    foreign_cursor = sent.json()["user_message"]["id"]
    resp = await client.get(f"/v1/conversations/{conv}/messages", params={"before": foreign_cursor})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.parametrize("limit", [0, 501, -1])
@pytest.mark.asyncio
async def test_message_limit_is_bounded(client, provider, limit: int) -> None:
    conv = await _conversation(client)
    resp = await client.get(f"/v1/conversations/{conv}/messages", params={"limit": limit})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_conversations_can_be_paged(client, provider) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    ids = [
        (await client.post("/v1/conversations", json={"title": f"c{i}"})).json()["id"]
        for i in range(5)
    ]
    first = (await client.get("/v1/conversations", params={"limit": 2})).json()["items"]
    rest = (await client.get("/v1/conversations", params={"limit": 10, "offset": 2})).json()[
        "items"
    ]
    assert len(first) == 2 and len(rest) == 3
    assert {c["id"] for c in first} | {c["id"] for c in rest} == set(ids)
    assert (await client.get("/v1/conversations", params={"limit": 201})).status_code == 422


# ---------------------------------------------------------------------
# List freshness and titles
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_most_recently_used_conversation_is_listed_first(client, provider) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    old = (await client.post("/v1/conversations", json={"title": "old"})).json()["id"]
    new = (await client.post("/v1/conversations", json={"title": "new"})).json()["id"]

    # Talking in the older conversation brings it back to the top.
    await client.post(f"/v1/conversations/{old}/messages", json={"content": "still here"})
    listed = (await client.get("/v1/conversations")).json()["items"]
    assert [c["id"] for c in listed] == [old, new]


@pytest.mark.asyncio
async def test_an_untitled_conversation_is_named_by_its_first_message(client, provider) -> None:
    conv = await _conversation(client)
    await client.post(
        f"/v1/conversations/{conv}/messages",
        json={"content": "Planning my move to Bengaluru next spring\nsecond line"},
    )
    assert (await client.get(f"/v1/conversations/{conv}")).json()["title"] == (
        "Planning my move to Bengaluru next spring"
    )
    # Later messages do not rename it.
    await client.post(f"/v1/conversations/{conv}/messages", json={"content": "Something else"})
    assert (await client.get(f"/v1/conversations/{conv}")).json()["title"] == (
        "Planning my move to Bengaluru next spring"
    )


@pytest.mark.asyncio
async def test_long_first_messages_make_short_titles(client, provider) -> None:
    conv = await _conversation(client)
    await client.post(f"/v1/conversations/{conv}/messages", json={"content": "word " * 100})
    title = (await client.get(f"/v1/conversations/{conv}")).json()["title"]
    assert len(title) <= 60
    assert title.endswith("…")


@pytest.mark.asyncio
async def test_a_title_the_user_chose_is_kept(client, provider) -> None:
    conv = await _conversation(client, title="My own title")
    await client.post(f"/v1/conversations/{conv}/messages", json={"content": "hello there"})
    assert (await client.get(f"/v1/conversations/{conv}")).json()["title"] == "My own title"
