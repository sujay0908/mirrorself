"""End-to-end goal → TwinContext integration tests (Sprint 4).

Covers DF7+DF8 using the real HTTP surface + real `ConversationService` +
real `GoalService`. The LLM provider is the mock. Assertions focus on what
the twin message's `metadata_json.goals_context` records, and on the
service-layer ordering being applied before the context builder caps.
"""

from __future__ import annotations

import pytest


async def _create_twin_and_conversation(client) -> str:
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = await client.post(
        "/v1/conversations",
        json={"title": "Hello"},
    )
    assert conv.status_code == 201, conv.text
    return conv.json()["id"]


async def _create_goal(client, **payload) -> str:
    resp = await client.post("/v1/goals", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_message(client, conv_id: str, text: str) -> dict:
    resp = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": text},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_only_active_goals_reach_context(client) -> None:
    conv_id = await _create_twin_and_conversation(client)

    active_id = await _create_goal(client, title="Active", priority=2)
    paused_id = await _create_goal(client, title="Paused", priority=2)
    achieved_id = await _create_goal(client, title="Done", priority=2)
    abandoned_id = await _create_goal(client, title="Dropped", priority=2)

    await client.patch(f"/v1/goals/{paused_id}", json={"status": "paused"})
    await client.patch(f"/v1/goals/{achieved_id}", json={"status": "achieved"})
    await client.patch(f"/v1/goals/{abandoned_id}", json={"status": "abandoned"})

    body = await _post_message(client, conv_id, "Hi there")
    goals_meta = body["twin_message"]["metadata_json"]["goals_context"]
    assert goals_meta["ok"] is True
    assert goals_meta["goals_used"] == 1
    assert goals_meta["goal_ids"] == [active_id]


@pytest.mark.asyncio
async def test_active_goals_capped_at_three(client) -> None:
    conv_id = await _create_twin_and_conversation(client)

    for i in range(5):
        await _create_goal(client, title=f"Goal {i}", priority=3)

    body = await _post_message(client, conv_id, "What should I focus on?")
    goals_meta = body["twin_message"]["metadata_json"]["goals_context"]
    assert goals_meta["goals_used"] == 3


@pytest.mark.asyncio
async def test_goals_ordered_by_priority_then_recency(client) -> None:
    conv_id = await _create_twin_and_conversation(client)

    low = await _create_goal(client, title="low", priority=5)
    high_old = await _create_goal(client, title="high-old", priority=1)
    mid = await _create_goal(client, title="mid", priority=3)
    high_new = await _create_goal(client, title="high-new", priority=1)

    body = await _post_message(client, conv_id, "What is top?")
    ids_in_order = body["twin_message"]["metadata_json"]["goals_context"]["goal_ids"]
    # Priority asc wins first; among same priority newest-updated wins.
    assert ids_in_order == [high_new, high_old, mid]
    assert low not in ids_in_order


@pytest.mark.asyncio
async def test_zero_active_goals_still_succeeds(client) -> None:
    conv_id = await _create_twin_and_conversation(client)
    body = await _post_message(client, conv_id, "Hello")
    goals_meta = body["twin_message"]["metadata_json"]["goals_context"]
    assert goals_meta["ok"] is True
    assert goals_meta["goals_used"] == 0
    assert goals_meta["goal_ids"] == []


@pytest.mark.asyncio
async def test_other_users_goals_never_reach_context(client, as_user, user_a, user_b) -> None:
    as_user(user_a)
    await client.post("/v1/twin", json={"name": "A"})
    for i in range(3):
        await _create_goal(client, title=f"A-{i}", priority=1)

    as_user(user_b)
    conv_id = await _create_twin_and_conversation(client)
    body = await _post_message(client, conv_id, "hi")
    assert body["twin_message"]["metadata_json"]["goals_context"]["goals_used"] == 0
