"""Unit tests for the Sprint 8 opportunity policy.

The policy is a pure function on `OpportunitySignals`. These tests
pin:

- Decision 1 shape: should_run = meaningful_trigger
                                AND cooldown_expired
                                AND backlog_below_limit.
- Memory-only trigger passes.
- Goal-only trigger passes.
- Cooldown active blocks everything (even when memories alone would
  trigger). A twin that has never run has `seconds_since_last_run =
  None` and bypasses cooldown.
- Backlog cap blocks everything.
- Deterministic: same signals, same `reason` string, byte for byte.
- The default thresholds match the module constants.
"""

from __future__ import annotations

from app.reflection.scheduler import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_PENDING_BACKLOG,
    DEFAULT_MIN_GOAL_EVENTS,
    DEFAULT_MIN_NEW_MEMORIES,
    OpportunityPolicy,
    OpportunitySignals,
)


def _signals(**overrides: object) -> OpportunitySignals:
    defaults: dict[str, object] = {
        "new_confirmed_memories": 0,
        "meaningful_goal_events": 0,
        "pending_backlog": 0,
        "seconds_since_last_run": None,
    }
    defaults.update(overrides)
    return OpportunitySignals(**defaults)  # type: ignore[arg-type]


def test_defaults_match_module_constants() -> None:
    policy = OpportunityPolicy()
    assert policy.min_new_memories == DEFAULT_MIN_NEW_MEMORIES
    assert policy.min_goal_events == DEFAULT_MIN_GOAL_EVENTS
    assert policy.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert policy.max_pending_backlog == DEFAULT_MAX_PENDING_BACKLOG


def test_memory_trigger_only_runs() -> None:
    policy = OpportunityPolicy(min_new_memories=3, min_goal_events=2)
    sig = _signals(new_confirmed_memories=3)
    out = policy.evaluate(sig)
    assert out.should_run is True
    assert out.reason == "run:new_memories"


def test_goal_trigger_only_runs() -> None:
    policy = OpportunityPolicy(min_new_memories=3, min_goal_events=2)
    sig = _signals(meaningful_goal_events=2)
    out = policy.evaluate(sig)
    assert out.should_run is True
    assert out.reason == "run:goal_activity"


def test_either_signal_is_enough_decision_1() -> None:
    """Decision 1: do NOT require both. Either alone is enough."""
    policy = OpportunityPolicy()
    assert policy.evaluate(_signals(new_confirmed_memories=5)).should_run
    assert policy.evaluate(_signals(meaningful_goal_events=5)).should_run


def test_no_meaningful_trigger_skips() -> None:
    policy = OpportunityPolicy()
    out = policy.evaluate(_signals(new_confirmed_memories=0, meaningful_goal_events=0))
    assert out.should_run is False
    assert out.reason == "skip:no_meaningful_trigger"


def test_cooldown_active_blocks_run() -> None:
    policy = OpportunityPolicy(cooldown_seconds=600)
    sig = _signals(new_confirmed_memories=10, seconds_since_last_run=120.0)
    out = policy.evaluate(sig)
    assert out.should_run is False
    assert out.reason == "skip:cooldown_active"


def test_cooldown_bypassed_when_never_ran() -> None:
    """A twin that has never run reflection has `seconds_since_last_run = None`.

    The cooldown clause must NOT falsely treat None as "within window".
    """
    policy = OpportunityPolicy(cooldown_seconds=3600)
    sig = _signals(new_confirmed_memories=5, seconds_since_last_run=None)
    out = policy.evaluate(sig)
    assert out.should_run is True
    assert out.reason == "run:new_memories"


def test_backlog_full_blocks_everything() -> None:
    policy = OpportunityPolicy(max_pending_backlog=3)
    # Even with a strong trigger and no cooldown, a full backlog SKIPs.
    sig = _signals(
        new_confirmed_memories=100,
        meaningful_goal_events=100,
        pending_backlog=3,
        seconds_since_last_run=None,
    )
    out = policy.evaluate(sig)
    assert out.should_run is False
    assert out.reason == "skip:backlog_full"


def test_backlog_edge_case_at_limit() -> None:
    """`>= max_pending_backlog` blocks. One below is fine."""
    policy = OpportunityPolicy(max_pending_backlog=5)
    sig_blocked = _signals(new_confirmed_memories=10, pending_backlog=5)
    sig_ok = _signals(new_confirmed_memories=10, pending_backlog=4)
    assert policy.evaluate(sig_blocked).should_run is False
    assert policy.evaluate(sig_ok).should_run is True


def test_deterministic_reason_string() -> None:
    """Same input → same reason. The reason is a short tag — never
    content."""
    policy = OpportunityPolicy()
    sig = _signals(new_confirmed_memories=5)
    first = policy.evaluate(sig).reason
    second = policy.evaluate(sig).reason
    assert first == second
    assert ":" in first
    assert " " not in first  # reasons are machine tags, no spaces
