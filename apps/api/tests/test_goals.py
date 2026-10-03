"""Goal CRUD, ownership, status transitions, and audit events.

Covers phases 1-3 of Sprint 4: the Goal + GoalEvent models, migration-driven
schema, and REST surface. The context-integration tests live in
`test_goal_context.py`.
"""

from __future__ import annotations

import pytest


async def _create_twin(client) -> str:
    resp = await client.post("/v1/twin", json={"name": "Aurora"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_goal_defaults_to_active(client) -> None:
    await _create_twin(client)
    resp = await client.post(
        "/v1/goals",
        json={"title": "Ship Sprint 4", "priority": 2},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Ship Sprint 4"
    assert body["status"] == "active"
    assert body["priority"] == 2
    assert body["description"] is None


@pytest.mark.asyncio
async def test_create_goal_requires_title(client) -> None:
    await _create_twin(client)
    resp = await client.post("/v1/goals", json={"priority": 3})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_goal_without_twin_returns_404(client) -> None:
    resp = await client.post("/v1/goals", json={"title": "No twin"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "twin_not_found"


@pytest.mark.asyncio
async def test_list_goals_newest_updated_first(client) -> None:
    await _create_twin(client)
    r1 = await client.post("/v1/goals", json={"title": "First"})
    r2 = await client.post("/v1/goals", json={"title": "Second"})
    r3 = await client.post("/v1/goals", json={"title": "Third"})
    assert r1.status_code == r2.status_code == r3.status_code == 201

    resp = await client.get("/v1/goals")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()["items"]]
    assert titles == ["Third", "Second", "First"]


@pytest.mark.asyncio
async def test_list_goals_status_filter(client) -> None:
    await _create_twin(client)
    r_active = await client.post("/v1/goals", json={"title": "Active one"})
    r_pause = await client.post("/v1/goals", json={"title": "Paused one"})
    assert r_active.status_code == 201
    assert r_pause.status_code == 201

    pause_id = r_pause.json()["id"]
    await client.patch(f"/v1/goals/{pause_id}", json={"status": "paused"})

    only_active = await client.get("/v1/goals?status=active")
    assert only_active.status_code == 200
    titles = [i["title"] for i in only_active.json()["items"]]
    assert titles == ["Active one"]

    only_paused = await client.get("/v1/goals?status=paused")
    titles = [i["title"] for i in only_paused.json()["items"]]
    assert titles == ["Paused one"]


@pytest.mark.asyncio
async def test_get_goal_returns_full_record(client) -> None:
    await _create_twin(client)
    created = (await client.post("/v1/goals", json={"title": "Pay rent"})).json()
    goal_id = created["id"]

    read = await client.get(f"/v1/goals/{goal_id}")
    assert read.status_code == 200
    body = read.json()
    assert body["id"] == goal_id
    assert body["title"] == "Pay rent"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_get_goal_unknown_id_is_404(client) -> None:
    await _create_twin(client)
    import uuid

    resp = await client.get(f"/v1/goals/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "goal_not_found"


@pytest.mark.asyncio
async def test_patch_goal_edits_title_and_priority(client) -> None:
    await _create_twin(client)
    created = (await client.post("/v1/goals", json={"title": "Old"})).json()
    goal_id = created["id"]

    patched = await client.patch(
        f"/v1/goals/{goal_id}",
        json={"title": "New title", "priority": 1, "description": "The why"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["title"] == "New title"
    assert body["priority"] == 1
    assert body["description"] == "The why"


@pytest.mark.asyncio
async def test_status_transition_active_to_achieved_logs_event(client) -> None:
    await _create_twin(client)
    created = (await client.post("/v1/goals", json={"title": "Climb Rainier"})).json()
    goal_id = created["id"]

    transition = await client.patch(
        f"/v1/goals/{goal_id}",
        json={"status": "achieved", "status_note": "Summited today."},
    )
    assert transition.status_code == 200
    assert transition.json()["status"] == "achieved"

    events = await client.get(f"/v1/goals/{goal_id}/events")
    assert events.status_code == 200
    event_types = [e["event_type"] for e in events.json()["items"]]
    # Chronological: `created` then `status_changed`.
    assert event_types == ["created", "status_changed"]
    status_evt = events.json()["items"][1]
    assert status_evt["from_status"] == "active"
    assert status_evt["to_status"] == "achieved"
    assert status_evt["note"] == "Summited today."


@pytest.mark.asyncio
async def test_illegal_transition_from_achieved_is_rejected(client) -> None:
    await _create_twin(client)
    goal_id = (
        await client.post("/v1/goals", json={"title": "Terminal"})
    ).json()["id"]
    await client.patch(f"/v1/goals/{goal_id}", json={"status": "achieved"})

    attempt = await client.patch(f"/v1/goals/{goal_id}", json={"status": "active"})
    assert attempt.status_code == 409
    assert attempt.json()["error"]["code"] == "invalid_goal_status_transition"


@pytest.mark.asyncio
async def test_pause_then_resume_is_legal(client) -> None:
    await _create_twin(client)
    goal_id = (
        await client.post("/v1/goals", json={"title": "Paused thing"})
    ).json()["id"]
    paused = await client.patch(f"/v1/goals/{goal_id}", json={"status": "paused"})
    assert paused.status_code == 200
    resumed = await client.patch(f"/v1/goals/{goal_id}", json={"status": "active"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"


@pytest.mark.asyncio
async def test_no_op_patch_does_not_emit_updated_event(client) -> None:
    await _create_twin(client)
    goal_id = (
        await client.post("/v1/goals", json={"title": "Same", "priority": 3})
    ).json()["id"]

    patch_same = await client.patch(
        f"/v1/goals/{goal_id}",
        json={"title": "Same", "priority": 3},
    )
    assert patch_same.status_code == 200

    events = (await client.get(f"/v1/goals/{goal_id}/events")).json()["items"]
    assert [e["event_type"] for e in events] == ["created"]


@pytest.mark.asyncio
async def test_cross_user_cannot_access_other_users_goal(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    await _create_twin(client)
    goal_a = (
        await client.post("/v1/goals", json={"title": "Private to A"})
    ).json()
    goal_id = goal_a["id"]

    as_user(user_b)
    # User B has no twin.
    resp = await client.get(f"/v1/goals/{goal_id}")
    assert resp.status_code == 404

    # Even once B has a twin, A's goal is unreachable.
    await _create_twin(client)
    resp2 = await client.get(f"/v1/goals/{goal_id}")
    assert resp2.status_code == 404
    assert resp2.json()["error"]["code"] == "goal_not_found"


@pytest.mark.asyncio
async def test_priority_out_of_range_is_422(client) -> None:
    await _create_twin(client)
    resp = await client.post("/v1/goals", json={"title": "bad", "priority": 9})
    assert resp.status_code == 422
