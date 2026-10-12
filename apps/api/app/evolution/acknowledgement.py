"""Deterministic composition of the chat-time learning acknowledgement
(Sprint 10).

Pure functions over already-loaded `TwinEvolutionEvent` rows. No I/O, no
LLM, no new persistence. The chat path calls `compose_learning` with the
owner-scoped slice of unacknowledged events and drops the result into the
twin message's `metadata_json["learning"]`, which the mobile client
already surfaces via the generic `metadata_json` passthrough.

Privacy: every field here is derived from IDs, the event type, the seq,
and the event's `summary` — and `summary` is itself an IDs-and-safe-
metadata-only string capped at 255 chars and enforced at write time by
`EvolutionService.record`. No raw message, memory, goal, or profile
content passes through this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.evolution.models import TwinEvolutionEvent

# How many unacknowledged events a single reply will surface at most.
# Bounded so a long backlog does not produce an unwieldy chip; the rest
# surface on subsequent turns as the cursor advances.
ACK_SURFACE_LIMIT: int = 5


def evolution_lead(event_type: str) -> str:
    """Map an evolution event type to the user-facing distinction.

    `insight_acknowledged` is acknowledgement, not identity mutation
    (Sprint 7 founder decision #1) → "acknowledged". Everything else is
    a durable change that took effect → "learned". The lead is computed
    server-side so the mobile header never diverges from what the apply
    dispatcher actually recorded.
    """
    if event_type == "insight_acknowledged":
        return "acknowledged"
    return "learned"


def compose_learning(events: Sequence[TwinEvolutionEvent]) -> dict[str, Any] | None:
    """Build the `learning` metadata block from unacknowledged events.

    Returns `None` when there is nothing to surface, so the caller can
    store `metadata_json["learning"] = None` (or omit it) without the
    mobile client rendering an empty chip.

    `events` MUST already be ordered by `seq` ascending (the surface
    query does this). `acknowledged_up_to_seq` is the max seq in the
    slice — the value the caller writes back to the twin cursor.
    """
    if not events:
        return None
    items = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "lead": evolution_lead(e.event_type),
            "summary": e.summary,
            "seq": e.seq,
        }
        for e in events
    ]
    return {
        "count": len(items),
        "acknowledged_up_to_seq": max(e.seq for e in events),
        "has_learned": any(it["lead"] == "learned" for it in items),
        "has_acknowledged": any(it["lead"] == "acknowledged" for it in items),
        "items": items,
    }
