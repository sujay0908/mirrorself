"""End-to-end Sprint 4 happy-path integration test.

Covers the full new-user → twin → goal → chat → candidate → confirm →
retrieve → context → response → provenance flow in one go. Mirrors Sprint
1's `test_integration.py` style but exercises every Sprint 4 surface.
"""

from __future__ import annotations

import pytest

from app.api.deps import get_current_user, sessionmaker_dep
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService


async def _seed_candidate_from_message(
    client, conv_id: str, text: str
) -> str:
    """Create a user message and a candidate linked to it. Return cand id."""
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()

    from app.conversation.models import Message

    async with sessionmaker() as session:
        import uuid as _uuid

        msg = Message(
            id=_uuid.uuid4(),
            conversation_id=_uuid.UUID(conv_id),
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
                    content="They live in Bengaluru.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
            source_conversation_id=_uuid.UUID(conv_id),
            source_message_id=msg.id,
        )
        return str(cand.id)


@pytest.mark.asyncio
async def test_sprint_4_end_to_end_flow(client) -> None:
    # 1. Create twin.
    twin_resp = await client.post("/v1/twin", json={"name": "Aurora"})
    assert twin_resp.status_code == 201

    # 2. Create an active goal.
    goal_resp = await client.post(
        "/v1/goals",
        json={"title": "Finish Sprint 4", "priority": 1},
    )
    assert goal_resp.status_code == 201
    goal_id = goal_resp.json()["id"]

    # 3. Start a conversation.
    conv_resp = await client.post("/v1/conversations", json={"title": "Hello"})
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]

    # 4. Seed a candidate linked to a message in the conversation.
    candidate_id = await _seed_candidate_from_message(
        client, conv_id, "I live in Bengaluru and I run every Sunday."
    )

    # 5. Confirm the candidate → produces a Memory + source + embedding.
    confirm = await client.post(f"/v1/memory-candidates/{candidate_id}/confirm")
    assert confirm.status_code == 201
    memory_id = confirm.json()["memory"]["id"]

    # 6. Chat — retrieval SHOULD surface the confirmed memory (semantic
    # vector was populated at confirmation time), and the active goal
    # SHOULD appear in the goals_context.
    chat = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Where do I live?"},
    )
    assert chat.status_code == 201, chat.text
    twin_msg = chat.json()["twin_message"]
    meta = twin_msg["metadata_json"]
    assert meta["retrieval"]["ok"] is True
    assert memory_id in meta["retrieval"]["memory_ids"]
    assert meta["goals_context"]["ok"] is True
    assert meta["goals_context"]["goal_ids"] == [goal_id]

    # 7. Provenance surfaces the source message snippet.
    prov = await client.get(f"/v1/memories/{memory_id}/provenance")
    assert prov.status_code == 200
    sources = prov.json()["sources"]
    assert sources
    assert "Bengaluru" in sources[0]["source_snippet"]

    # 8. Move goal to achieved → it drops out of future context.
    done = await client.patch(
        f"/v1/goals/{goal_id}",
        json={"status": "achieved", "status_note": "nailed it"},
    )
    assert done.status_code == 200

    chat2 = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Anything else?"},
    )
    assert chat2.status_code == 201
    goals_meta_2 = chat2.json()["twin_message"]["metadata_json"]["goals_context"]
    assert goals_meta_2["goals_used"] == 0

    # 9. Audit trail now has created + status_changed events.
    events = await client.get(f"/v1/goals/{goal_id}/events")
    types = [e["event_type"] for e in events.json()["items"]]
    assert "created" in types
    assert "status_changed" in types
