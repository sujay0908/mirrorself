"""Goal-context failure MUST NOT fail chat (Sprint 4).

Mirrors the retrieval-failure isolation test from Sprint 3. We swap the
`goal_service_dep` for a GoalService whose `list_active_for_context` always
raises, and assert that the chat still returns a 201 with
`goals_context.ok=False` on the twin message's metadata.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.deps import goal_service_dep


class _ExplodingGoalService:
    """Stub GoalService whose context path always raises."""

    async def list_active_for_context(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("deliberate boom for isolation test")


@pytest.mark.asyncio
async def test_goal_context_failure_does_not_fail_chat(app_client) -> None:
    app, client, _holder = app_client

    def _override_goal_service() -> _ExplodingGoalService:
        return _ExplodingGoalService()  # type: ignore[return-value]

    app.dependency_overrides[goal_service_dep] = _override_goal_service

    try:
        twin_resp = await client.post("/v1/twin", json={"name": "Aurora"})
        assert twin_resp.status_code == 201

        conv_resp = await client.post("/v1/conversations", json={"title": "x"})
        assert conv_resp.status_code == 201
        conv_id = conv_resp.json()["id"]

        msg_resp = await client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "hi"},
        )
        assert msg_resp.status_code == 201, msg_resp.text
        meta = msg_resp.json()["twin_message"]["metadata_json"]["goals_context"]
        assert meta["ok"] is False
        assert meta["error"] is not None
        assert meta["goals_used"] == 0
    finally:
        app.dependency_overrides.pop(goal_service_dep, None)
