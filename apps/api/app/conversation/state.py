"""TwinState — Sprint-6 boundary for *current-turn* twin state.

A `TwinState` captures the ephemeral state a single chat turn runs
under: the detected intent, the resolved context policy, and nothing
else for now. It is deliberately NOT persisted and NOT connected to the
database.

Why this file exists at all:

The Sprint-6 brief asks whether a safe `TwinState` abstraction already
exists in the codebase and, if not, to introduce "only the minimal
domain abstraction needed for Sprint 6" without creating a permanent
emotional-memory system. The pre-existing codebase has no such
abstraction, so this file adds the smallest useful one — a plain
in-memory dataclass that carries intent+policy forward from
`ConversationService.post_message` into the context builder and the
prompt renderer. The audit layer serializes it into
`twin_message.metadata_json.twin_state`.

Hard invariants that this file reinforces:

- `TwinState` is session-local. It lives for the duration of one chat
  turn and is NOT written to any table.
- `TwinState` does NOT touch `TwinProfile`. The LLM-never-mutates-profile
  invariant from earlier sprints remains intact.
- `TwinState` is NOT a memory. Nothing from here feeds the memory
  candidate / confirmation pipeline.
- `TwinState` is NOT emotional state. If an emotional-state subsystem
  is ever introduced it will live in its own module with its own
  policy around persistence and confirmation; this file is explicitly
  not that place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.conversation.intent import IntentResult
from app.conversation.policy import ContextPolicy


@dataclass(frozen=True, slots=True)
class TwinState:
    """Ephemeral per-turn state.

    The fields here are what the Sprint-6 pipeline needs to carry
    between intent detection, context policy and prompt rendering.
    Anything beyond this requires an explicit design decision — do not
    tack additional fields on here without one.
    """

    intent_result: IntentResult
    policy: ContextPolicy
    # `extras` is reserved for diagnostic entries the pipeline wants to
    # surface via `twin_message.metadata_json` without changing this
    # dataclass. Must never carry raw user content.
    extras: dict[str, object] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        """JSON-serialisable summary for the twin message's
        `metadata_json.twin_state` field. IDs and counts only; never
        user content.
        """
        return {
            "intent": self.intent_result.intent.value,
            "intent_confidence": self.intent_result.confidence,
            "intent_reason": self.intent_result.reason,
            "policy": self.policy.to_metadata(),
        }
