"""Context policy unit tests (Sprint 6).

The policy table is the one place where "which context sources matter
for which intent" is encoded. These tests pin:

- every intent in the Sprint-6 vocabulary maps to a weights row
- the Sprint-6 brief's qualitative weights (HIGH / MEDIUM / LOW) are
  reflected in the table
- resolved numeric limits respect the Sprint-3/4 hard caps:
    * memory_limit  ≤ MemoryRetriever.MAX_LIMIT (24)
    * goal_limit    ≤ ConversationService._MAX_ACTIVE_GOALS_IN_CONTEXT (3)
    * history_turns ≤ ContextBudget.max_history_turns default (6)
- UNKNOWN produces a bounded, usable "conservative default" policy
- the policy is deterministic and side-effect free
- `policy_for` never raises for a known intent
"""

from __future__ import annotations

from app.conversation.intent import Intent
from app.conversation.policy import (
    ContextWeight,
    ContextWeights,
    policy_for,
)
from app.conversation.service import ConversationService
from app.memory.context import ContextBudget
from app.memory.retrieval import MAX_LIMIT as RETRIEVER_MAX_LIMIT

# ---------------------------------------------------------------------
# Coverage: every intent has a row
# ---------------------------------------------------------------------


def test_every_intent_has_a_policy() -> None:
    for intent in Intent:
        policy = policy_for(intent)
        assert policy.intent is intent
        assert isinstance(policy.weights, ContextWeights)


# ---------------------------------------------------------------------
# Per-intent qualitative weights match the Sprint-6 brief
# ---------------------------------------------------------------------


def test_think_weights() -> None:
    w = policy_for(Intent.THINK).weights
    assert w.memories >= ContextWeight.MEDIUM
    assert w.goals == ContextWeight.MEDIUM
    assert w.conversation == ContextWeight.HIGH


def test_learn_weights_low_memory_low_goals_high_conversation() -> None:
    w = policy_for(Intent.LEARN).weights
    assert w.memories <= ContextWeight.MEDIUM
    assert w.goals <= ContextWeight.MEDIUM
    assert w.conversation == ContextWeight.HIGH


def test_plan_weights_high_goals_high_conversation() -> None:
    w = policy_for(Intent.PLAN).weights
    assert w.goals == ContextWeight.HIGH
    assert w.conversation == ContextWeight.HIGH
    assert w.memories >= ContextWeight.MEDIUM


def test_reflect_weights_high_memory_high_conversation() -> None:
    w = policy_for(Intent.REFLECT).weights
    assert w.memories == ContextWeight.HIGH
    assert w.goals >= ContextWeight.LOW
    assert w.conversation == ContextWeight.HIGH


def test_talk_weights_low_goals() -> None:
    """TALK: casual back-and-forth. Goals should be LOW so a friendly
    "how are you?" doesn't pull the user's whole goal shelf into the
    prompt.
    """
    w = policy_for(Intent.TALK).weights
    assert w.goals == ContextWeight.LOW
    assert w.conversation == ContextWeight.HIGH


def test_task_weights_high_goals() -> None:
    w = policy_for(Intent.TASK).weights
    assert w.goals >= ContextWeight.MEDIUM
    assert w.conversation == ContextWeight.HIGH


def test_unknown_weights_are_conservative_default() -> None:
    w = policy_for(Intent.UNKNOWN).weights
    # Not NONE on any axis — UNKNOWN must still produce a usable chat.
    assert w.memories > ContextWeight.NONE
    assert w.goals > ContextWeight.NONE
    assert w.conversation > ContextWeight.NONE


# ---------------------------------------------------------------------
# Hard-cap guarantees
# ---------------------------------------------------------------------


def test_memory_limit_never_exceeds_retriever_max() -> None:
    for intent in Intent:
        assert policy_for(intent).memory_limit <= RETRIEVER_MAX_LIMIT


def test_goal_limit_never_exceeds_three() -> None:
    """The service-level cap `_MAX_ACTIVE_GOALS_IN_CONTEXT` must stay
    an upper bound.
    """
    for intent in Intent:
        assert policy_for(intent).goal_limit <= ConversationService._MAX_ACTIVE_GOALS_IN_CONTEXT


def test_history_turns_never_exceeds_builder_default() -> None:
    default = ContextBudget().max_history_turns
    for intent in Intent:
        assert policy_for(intent).history_turns <= default


def test_all_limits_are_non_negative() -> None:
    for intent in Intent:
        p = policy_for(intent)
        assert p.memory_limit >= 0
        assert p.goal_limit >= 0
        assert p.history_turns >= 0


# ---------------------------------------------------------------------
# ContextBudget projection + metadata shape
# ---------------------------------------------------------------------


def test_context_budget_projection_matches_policy() -> None:
    for intent in Intent:
        p = policy_for(intent)
        budget = p.context_budget()
        assert budget.max_memories == p.memory_limit
        assert budget.max_active_goals == p.goal_limit
        assert budget.max_history_turns == p.history_turns


def test_metadata_round_trip_is_json_safe() -> None:
    """`policy.to_metadata()` is written straight into
    `twin_message.metadata_json`. It must only contain JSON-safe
    scalars/arrays — never a dataclass, never a UUID.
    """
    import json

    for intent in Intent:
        meta = policy_for(intent).to_metadata()
        # Round-trip via json dumps to prove it is pure JSON.
        dumped = json.dumps(meta)
        assert json.loads(dumped) == meta
        # Core shape pin.
        assert meta["intent"] == intent.value
        assert set(meta["weights"].keys()) == {"memories", "goals", "conversation"}
        assert set(meta["limits"].keys()) == {"memories", "goals", "history_turns"}


# ---------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------


def test_policy_is_deterministic_across_calls() -> None:
    first = {i: policy_for(i) for i in Intent}
    for _ in range(5):
        again = {i: policy_for(i) for i in Intent}
        assert again == first
