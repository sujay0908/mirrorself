"""Context policy — intent → concrete context limits (Sprint 6).

Centralises the decision of "how much of each source should the Twin
pull in for this turn?" per intent, so that policy is not scattered
across the service, the retriever, the goal service and the context
builder.

The policy is intentionally expressed in two layers:

1. A coarse `ContextWeight` per source (NONE / LOW / MEDIUM / HIGH)
   because the Sprint-6 brief states weights in those exact bands.
2. A `resolve(weights)` step that turns weights into concrete numeric
   `ContextBudget` fields so the rest of the pipeline can keep its
   existing numeric contracts (ContextBuilder.max_memories, the
   MemoryRetriever `limit`, GoalService.list_active_for_context limit,
   ContextBuilder.max_history_turns).

Design rules enforced here:

- Pure. No I/O, no side effects.
- Deterministic. Same intent → same policy, byte-for-byte.
- Conservative on UNKNOWN. The failure-isolation branches in
  `ConversationService` fall back to UNKNOWN; the UNKNOWN policy must
  still produce a usable, bounded context.
- Must never exceed the HARD CAPS already enforced by lower layers:
    * memories: `MemoryRetriever.MAX_LIMIT` (= 24)
    * active goals: `ConversationService._MAX_ACTIVE_GOALS_IN_CONTEXT` (= 3)
    * history turns: existing `ContextBudget.max_history_turns` default (6)
  A test pins that invariant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from app.conversation.intent import Intent
from app.memory.context import ContextBudget
from app.memory.retrieval import MAX_LIMIT as RETRIEVER_MAX_LIMIT


class ContextWeight(IntEnum):
    """Coarse weight used in the policy table.

    IntEnum so comparisons work naturally (HIGH > MEDIUM > LOW > NONE)
    and so weight values can be dumped straight into
    `metadata_json.policy` on the twin message for the trace layer.
    """

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True, slots=True)
class ContextWeights:
    """Weights per context source. One row per intent in `_WEIGHTS`."""

    memories: ContextWeight
    goals: ContextWeight
    conversation: ContextWeight


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """Concrete, numeric limits derived from a `ContextWeights`.

    This is what the conversation service actually hands to the
    retriever, the goal service and the context builder — not the
    coarse weights. Decoupling the two lets us tune the numeric map
    without touching the per-intent policy table.
    """

    intent: Intent
    weights: ContextWeights
    memory_limit: int
    goal_limit: int
    history_turns: int

    def context_budget(self) -> ContextBudget:
        """Build the `ContextBudget` the ContextBuilder expects.

        The character-level truncation defaults (`max_memory_content_chars`,
        `max_turn_content_chars`, `max_goal_title_chars`,
        `max_goal_description_chars`) are per-item hygiene, independent
        of intent, so we keep the dataclass defaults from the builder.
        """
        return ContextBudget(
            max_memories=self.memory_limit,
            max_history_turns=self.history_turns,
            max_active_goals=self.goal_limit,
        )

    def to_metadata(self) -> dict[str, object]:
        """A JSON-serialisable summary for the twin message's
        `metadata_json.policy` field. IDs and counts only; never user
        content.
        """
        return {
            "intent": self.intent.value,
            "weights": {
                "memories": int(self.weights.memories),
                "goals": int(self.weights.goals),
                "conversation": int(self.weights.conversation),
            },
            "limits": {
                "memories": self.memory_limit,
                "goals": self.goal_limit,
                "history_turns": self.history_turns,
            },
        }


# ---------------------------------------------------------------------
# Intent → weights (Sprint 6 brief, Phase 3)
# ---------------------------------------------------------------------
#
# The brief gives ranges ("medium/high", "low/medium"). We resolve each
# range to a single band so the policy stays deterministic. The choice
# of the specific band inside a range is documented alongside each row.

_WEIGHTS: dict[Intent, ContextWeights] = {
    # THINK: user is working something out. Memories matter (prior
    # related thoughts), goals matter moderately (alignment with
    # ongoing pursuits), conversation matters most (continuity of the
    # current reasoning chain).
    Intent.THINK: ContextWeights(
        memories=ContextWeight.HIGH,
        goals=ContextWeight.MEDIUM,
        conversation=ContextWeight.HIGH,
    ),
    # LEARN: pedagogy. The user is asking the twin to explain or teach,
    # so prior conversation state matters, but personal memories matter
    # less (the lesson doesn't usually hinge on who they are) and goals
    # matter even less.
    Intent.LEARN: ContextWeights(
        memories=ContextWeight.LOW,
        goals=ContextWeight.LOW,
        conversation=ContextWeight.HIGH,
    ),
    # PLAN: strongly goal-anchored. Pull in the active goals, pull in
    # memories about preferences/constraints, keep the full
    # conversation window.
    Intent.PLAN: ContextWeights(
        memories=ContextWeight.MEDIUM,
        goals=ContextWeight.HIGH,
        conversation=ContextWeight.HIGH,
    ),
    # REFLECT: memory is the main input (the twin reads back the
    # user's past), goals contextualise the reflection, conversation
    # keeps the current framing.
    Intent.REFLECT: ContextWeights(
        memories=ContextWeight.HIGH,
        goals=ContextWeight.MEDIUM,
        conversation=ContextWeight.HIGH,
    ),
    # TALK: casual back-and-forth. Keep memory light and goals near
    # zero so a friendly "how are you?" doesn't yank the user's full
    # memory shelf into the prompt.
    Intent.TALK: ContextWeights(
        memories=ContextWeight.MEDIUM,
        goals=ContextWeight.LOW,
        conversation=ContextWeight.HIGH,
    ),
    # TASK: the user wants the twin to produce something. Memories
    # moderate (preferences / tone), goals high (what the task serves),
    # conversation high (the task's current state).
    Intent.TASK: ContextWeights(
        memories=ContextWeight.MEDIUM,
        goals=ContextWeight.HIGH,
        conversation=ContextWeight.HIGH,
    ),
    # UNKNOWN: a conservative default that doesn't surprise anyone.
    # Keeps enough signal around that the chat stays useful if the
    # detector ever misfires.
    Intent.UNKNOWN: ContextWeights(
        memories=ContextWeight.MEDIUM,
        goals=ContextWeight.MEDIUM,
        conversation=ContextWeight.MEDIUM,
    ),
}


# Weight → concrete numeric limit tables. The HIGH caps match the
# Sprint-5 defaults so the "fully loaded" policy equals pre-Sprint-6
# behaviour. The MAX_HIGH values below are also pinned by a test so
# they never grow past the hard caps enforced by MemoryRetriever /
# the ConversationService active-goal cap.

_MEMORY_LIMIT = {
    ContextWeight.NONE: 0,
    ContextWeight.LOW: 3,
    ContextWeight.MEDIUM: 6,
    ContextWeight.HIGH: 8,  # matches ContextBudget.max_memories default
}

_GOAL_LIMIT = {
    ContextWeight.NONE: 0,
    ContextWeight.LOW: 1,
    ContextWeight.MEDIUM: 2,
    ContextWeight.HIGH: 3,  # matches ConversationService hard cap
}

_HISTORY_LIMIT = {
    ContextWeight.NONE: 0,
    ContextWeight.LOW: 2,
    ContextWeight.MEDIUM: 4,
    ContextWeight.HIGH: 6,  # matches ContextBudget.max_history_turns default
}


def policy_for(intent: Intent) -> ContextPolicy:
    """Return the deterministic policy for an intent.

    Unknown intents fall through to `Intent.UNKNOWN`'s row rather than
    raising, so a future enum value a caller forgot to add here still
    produces a usable chat.
    """
    weights = _WEIGHTS.get(intent, _WEIGHTS[Intent.UNKNOWN])
    memory_limit = min(_MEMORY_LIMIT[weights.memories], RETRIEVER_MAX_LIMIT)
    return ContextPolicy(
        intent=intent,
        weights=weights,
        memory_limit=memory_limit,
        goal_limit=_GOAL_LIMIT[weights.goals],
        history_turns=_HISTORY_LIMIT[weights.conversation],
    )
