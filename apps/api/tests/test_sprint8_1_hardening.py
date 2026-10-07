"""Sprint 8.1 hardening tests.

Covers:

- Advisory-lock key derivation (deterministic, per-twin, namespaced,
  int64-safe).
- `try_acquire_reflection_lock` SQLite branch returns True unconditionally.
- Scheduler synthesizes `skip:locked` when the lock cannot be acquired,
  does NOT call the extractor, and does NOT advance
  `last_reflection_run_at`.
- Chat still succeeds when the scheduler cannot acquire the lock
  (failure isolation preserved from Sprint 8).
- Manual `/v1/reflections/run` returns HTTP 200 + `error="already_running"`
  with zero counts when the lock is already held (shares the lock with
  the scheduler, does not block, does not change response shape).
- Settings refuses to construct when any reflection threshold is below
  the approved floor OR when `reflection_max_pending_backlog` is outside
  [1, 100]. The shipped defaults still construct cleanly.
- `OpportunityPolicy` directly instantiated with sub-floor values is
  clamped UP to the floor (ironclad floor via __post_init__).
- `REFLECTION_CONTEXT_LIMITS` is the single source of truth: both the
  manual endpoint and the scheduler pass identical limits to the loader
  functions.
- Decision 1 branching behavior still passes after the floor is in
  place (regression gate for Sprint 8).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.api.deps import (
    get_current_user,
    reflection_extractor_dep,
)
from app.config import Settings
from app.reflection.extractor import ReflectionExtractionResult
from app.reflection.scheduler import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MIN_GOAL_EVENTS,
    DEFAULT_MIN_NEW_MEMORIES,
    MAX_PENDING_BACKLOG_CEIL,
    MIN_PENDING_BACKLOG_FLOOR,
    REFLECTION_CONTEXT_LIMITS,
    OpportunityPolicy,
    OpportunitySignals,
    ReflectionContextLimits,
    ReflectionScheduler,
    _advisory_lock_key,
    try_acquire_reflection_lock,
)
from app.reflection.service import ReflectionService
from app.twin.service import TwinService

# -------------------------------------------------------------
# Helpers (keep this file independent of other sprints' helpers)
# -------------------------------------------------------------


class _CannedExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, **_: Any) -> ReflectionExtractionResult:
        self.calls += 1
        return ReflectionExtractionResult(drafts=[], error=None)


async def _create_twin(client, name: str = "Aurora") -> str:
    resp = await client.post("/v1/twin", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -------------------------------------------------------------
# Advisory-lock key derivation
# -------------------------------------------------------------


def test_advisory_lock_key_is_deterministic() -> None:
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert _advisory_lock_key(tid) == _advisory_lock_key(tid)


def test_advisory_lock_keys_differ_per_twin() -> None:
    a = _advisory_lock_key(uuid.UUID("11111111-1111-1111-1111-111111111111"))
    b = _advisory_lock_key(uuid.UUID("22222222-2222-2222-2222-222222222222"))
    assert a != b


def test_advisory_lock_key_fits_signed_int64() -> None:
    """Postgres advisory locks take a `bigint` — the key MUST fit the
    signed int64 range or `pg_try_advisory_xact_lock` would overflow.
    """
    for _ in range(100):
        tid = uuid.uuid4()
        key = _advisory_lock_key(tid)
        assert -(1 << 63) <= key <= (1 << 63) - 1


def test_advisory_lock_key_namespace_prefix_affects_key(monkeypatch) -> None:
    """A future scheduler category (e.g. `memory-consolidator:`) would
    use a different prefix. Verify the prefix is actually part of the
    hash input — swapping it changes the key for the same twin.
    """
    import app.reflection.scheduler as sched

    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    original = _advisory_lock_key(tid)
    monkeypatch.setattr(sched, "_ADVISORY_LOCK_NAMESPACE", "memory-consolidator:")
    rotated = _advisory_lock_key(tid)
    assert original != rotated


# -------------------------------------------------------------
# try_acquire_reflection_lock dialect behavior
# -------------------------------------------------------------


@pytest.mark.asyncio
async def test_try_acquire_lock_is_noop_on_sqlite(session_factory) -> None:
    """SQLite deployments are single-process; the helper returns True
    so the full test suite (SQLite-backed) exercises the normal path.
    """
    async with session_factory() as session:
        tid = uuid.uuid4()
        assert await try_acquire_reflection_lock(session, tid) is True
        # Repeat — no state is kept.
        assert await try_acquire_reflection_lock(session, tid) is True


# -------------------------------------------------------------
# Scheduler SKIP when the lock cannot be acquired
# -------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_skipped_locked_does_not_call_extractor(
    client, session_factory, monkeypatch
) -> None:
    await _create_twin(client)

    async def _refuse_lock(_session, _twin_id):  # type: ignore[no-untyped-def]
        return False

    import app.reflection.scheduler as sched

    monkeypatch.setattr(sched, "try_acquire_reflection_lock", _refuse_lock)

    extractor = _CannedExtractor()
    async with session_factory() as session:
        transport = client._transport  # type: ignore[attr-defined]
        app = transport.app
        user_dep = app.dependency_overrides[get_current_user]
        user = (await user_dep()) if callable(user_dep) else user_dep
        twin = await TwinService(session).require_by_user(user.user_id)
        scheduler = ReflectionScheduler(
            session,
            extractor=extractor,  # type: ignore[arg-type]
            reflection_service=ReflectionService(session),
            policy=OpportunityPolicy(),
        )
        result = await scheduler.maybe_run(twin)
        assert result.ran is False
        assert result.opportunity.reason == "skip:locked"
        assert extractor.calls == 0
        await session.refresh(twin)
        assert twin.last_reflection_run_at is None


@pytest.mark.asyncio
async def test_chat_still_succeeds_when_lock_cannot_be_acquired(client, monkeypatch) -> None:
    """Advisory-lock contention must not break chat (failure isolation)."""
    import app.reflection.scheduler as sched

    async def _refuse_lock(_session, _twin_id):  # type: ignore[no-untyped-def]
        return False

    monkeypatch.setattr(sched, "try_acquire_reflection_lock", _refuse_lock)

    await _create_twin(client)
    conv_resp = await client.post("/v1/conversations", json={"title": "x"})
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]
    msg_resp = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hi"})
    assert msg_resp.status_code == 201, msg_resp.text


# -------------------------------------------------------------
# Manual /v1/reflections/run shares the lock
# -------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_run_returns_already_running_when_locked(client, monkeypatch) -> None:
    """When the per-twin advisory lock is already held, POST
    /v1/reflections/run returns HTTP 200 + error='already_running'
    with zero counts. The endpoint contract (ReflectionRunOut shape)
    is unchanged — only the error tag varies.
    """
    import app.api.v1.reflections as refl_api

    async def _refuse_lock(_session, _twin_id):  # type: ignore[no-untyped-def]
        return False

    # The endpoint imported the symbol by name — monkeypatch the one
    # the endpoint actually calls.
    monkeypatch.setattr(refl_api, "try_acquire_reflection_lock", _refuse_lock)

    await _create_twin(client)
    resp = await client.post("/v1/reflections/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] == "already_running"
    assert body["candidates_proposed"] == 0
    assert body["candidates_persisted"] == 0
    assert body["candidates_deduplicated"] == 0


@pytest.mark.asyncio
async def test_manual_run_normal_path_unaffected_when_lock_is_free(
    client,
) -> None:
    """Belt-and-braces regression: with no concurrent run, the manual
    endpoint still works as it did in Sprint 7/8.
    """
    await _create_twin(client)
    # Install a canned extractor so no real LLM call is attempted.
    canned = _CannedExtractor()

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[reflection_extractor_dep] = lambda: canned
    try:
        resp = await client.post("/v1/reflections/run")
    finally:
        app.dependency_overrides.pop(reflection_extractor_dep, None)
    assert resp.status_code == 200
    assert resp.json()["error"] is None
    # Extractor was called exactly once.
    assert canned.calls == 1


# -------------------------------------------------------------
# Safety floor on Settings (schema-time, boot-time)
# -------------------------------------------------------------


def test_settings_rejects_cooldown_below_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(reflection_min_cooldown_seconds=60)


def test_settings_rejects_min_new_memories_below_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(reflection_min_new_memories=1)


def test_settings_rejects_min_goal_events_below_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(reflection_min_goal_events=1)


def test_settings_rejects_backlog_above_ceiling() -> None:
    with pytest.raises(ValidationError):
        Settings(reflection_max_pending_backlog=1000)


def test_settings_rejects_backlog_below_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(reflection_max_pending_backlog=0)


def test_settings_approved_defaults_still_construct() -> None:
    """Shipped defaults must still construct cleanly. If a future
    change moves `ge=` above the shipped default, THIS test fails and
    the misstep is caught before deploy.
    """
    s = Settings()
    assert s.reflection_min_new_memories == DEFAULT_MIN_NEW_MEMORIES
    assert s.reflection_min_goal_events == DEFAULT_MIN_GOAL_EVENTS
    assert s.reflection_min_cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert s.reflection_max_pending_backlog == 10


def test_settings_accepts_more_conservative_overrides() -> None:
    """Raising a threshold (more conservative) is permitted."""
    s = Settings(
        reflection_min_new_memories=5,
        reflection_min_goal_events=3,
        reflection_min_cooldown_seconds=3600,
        reflection_max_pending_backlog=50,
    )
    assert s.reflection_min_new_memories == 5
    assert s.reflection_min_cooldown_seconds == 3600


# -------------------------------------------------------------
# Ironclad floor on direct OpportunityPolicy construction
# -------------------------------------------------------------


def test_opportunity_policy_clamps_sub_floor_values_up() -> None:
    """Direct construction with sub-floor values must be clamped —
    even in tests, even in a worker that constructs the policy
    programmatically bypassing Settings.
    """
    p = OpportunityPolicy(
        min_new_memories=1,
        min_goal_events=1,
        cooldown_seconds=60,
        max_pending_backlog=0,
    )
    assert p.min_new_memories == DEFAULT_MIN_NEW_MEMORIES
    assert p.min_goal_events == DEFAULT_MIN_GOAL_EVENTS
    assert p.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS
    assert p.max_pending_backlog == MIN_PENDING_BACKLOG_FLOOR


def test_opportunity_policy_clamps_backlog_above_ceiling() -> None:
    p = OpportunityPolicy(max_pending_backlog=1000)
    assert p.max_pending_backlog == MAX_PENDING_BACKLOG_CEIL


def test_opportunity_policy_leaves_above_floor_values_untouched() -> None:
    p = OpportunityPolicy(
        min_new_memories=10,
        min_goal_events=5,
        cooldown_seconds=3600,
        max_pending_backlog=20,
    )
    assert p.min_new_memories == 10
    assert p.min_goal_events == 5
    assert p.cooldown_seconds == 3600
    assert p.max_pending_backlog == 20


def test_opportunity_policy_frozen_after_clamp() -> None:
    """`__post_init__` uses `object.__setattr__` because the dataclass
    is frozen. After construction the policy must still refuse normal
    attribute assignment.
    """
    p = OpportunityPolicy()
    # FrozenInstanceError is a dataclass-specific attribute-error. We
    # specifically want to assert the frozen contract rather than
    # swallow any random exception.
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        p.min_new_memories = 999  # type: ignore[misc]


# -------------------------------------------------------------
# Single source of truth: context limits
# -------------------------------------------------------------


def test_reflection_context_limits_values_pinned() -> None:
    """Guard against a silent value drift. If a future contributor
    needs to change these, they must change one dataclass field — not
    a scattered set of module constants.
    """
    assert REFLECTION_CONTEXT_LIMITS.max_memories == 24
    assert REFLECTION_CONTEXT_LIMITS.max_goals == 10
    assert REFLECTION_CONTEXT_LIMITS.max_recent_turns == 20
    assert isinstance(REFLECTION_CONTEXT_LIMITS, ReflectionContextLimits)


def test_old_duplicated_constants_removed_from_endpoint() -> None:
    """Sprint 8.1 removed the per-module duplicates. The endpoint
    module must not reintroduce them under their old names.
    """
    import app.api.v1.reflections as refl_api

    for old in ("_MAX_MEMORIES", "_MAX_GOALS", "_MAX_RECENT_TURNS"):
        assert not hasattr(refl_api, old), (
            f"{old} is a duplicate constant removed in Sprint 8.1 — "
            "use REFLECTION_CONTEXT_LIMITS instead."
        )


def test_old_duplicated_constants_removed_from_scheduler() -> None:
    import app.reflection.scheduler as sched

    for old in (
        "SCHEDULER_MAX_MEMORIES",
        "SCHEDULER_MAX_GOALS",
        "SCHEDULER_MAX_RECENT_TURNS",
    ):
        assert not hasattr(sched, old), (
            f"{old} is a duplicate constant removed in Sprint 8.1 — "
            "use REFLECTION_CONTEXT_LIMITS instead."
        )


@pytest.mark.asyncio
async def test_manual_and_scheduler_paths_use_same_limits(
    client, session_factory, monkeypatch
) -> None:
    """The scheduler and the manual endpoint both call the three
    loaders. This test spies on the loaders at the scheduler module —
    which is where BOTH paths import from — and asserts the recorded
    `limit=` arguments match REFLECTION_CONTEXT_LIMITS exactly.
    """
    import app.reflection.scheduler as sched

    recorded: dict[str, list[int]] = {
        "memories": [],
        "goals": [],
        "turns": [],
    }

    async def _spy_memories(session, twin, *, limit):  # type: ignore[no-untyped-def]
        recorded["memories"].append(limit)
        return []

    async def _spy_goals(session, twin, *, limit):  # type: ignore[no-untyped-def]
        recorded["goals"].append(limit)
        return []

    async def _spy_turns(session, twin, *, limit):  # type: ignore[no-untyped-def]
        recorded["turns"].append(limit)
        return []

    monkeypatch.setattr(sched, "load_recent_memories", _spy_memories)
    monkeypatch.setattr(sched, "load_active_goals", _spy_goals)
    monkeypatch.setattr(sched, "load_recent_turns", _spy_turns)

    # Also patch the names re-imported into reflections.py so the
    # manual endpoint hits the spy too.
    import app.api.v1.reflections as refl_api

    monkeypatch.setattr(refl_api, "_load_recent_memories", _spy_memories)
    monkeypatch.setattr(refl_api, "_load_active_goals", _spy_goals)
    monkeypatch.setattr(refl_api, "_load_recent_turns", _spy_turns)

    await _create_twin(client)
    # Manual path
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[reflection_extractor_dep] = lambda: _CannedExtractor()
    try:
        resp = await client.post("/v1/reflections/run")
    finally:
        app.dependency_overrides.pop(reflection_extractor_dep, None)
    assert resp.status_code == 200

    # Scheduler path — invoke directly (same twin).
    async with session_factory() as session:
        user_dep = app.dependency_overrides[get_current_user]
        user = (await user_dep()) if callable(user_dep) else user_dep
        twin = await TwinService(session).require_by_user(user.user_id)

        # Seed enough signal to pass the policy — override via a
        # directly-constructed policy whose values are at the floor
        # (so the clamp is a no-op). We can short-circuit the policy
        # by stubbing gather_signals.
        async def _canned_signals(_s, _t):  # type: ignore[no-untyped-def]
            return OpportunitySignals(
                new_confirmed_memories=10,
                meaningful_goal_events=0,
                pending_backlog=0,
                seconds_since_last_run=None,
            )

        monkeypatch.setattr(sched, "gather_signals", _canned_signals)
        scheduler = ReflectionScheduler(
            session,
            extractor=_CannedExtractor(),  # type: ignore[arg-type]
            reflection_service=ReflectionService(session),
            policy=OpportunityPolicy(),
        )
        await scheduler.maybe_run(twin)

    # Each loader should have been called at least twice (manual +
    # scheduler) with the shared limit values.
    assert recorded["memories"].count(REFLECTION_CONTEXT_LIMITS.max_memories) >= 2
    assert recorded["goals"].count(REFLECTION_CONTEXT_LIMITS.max_goals) >= 2
    assert recorded["turns"].count(REFLECTION_CONTEXT_LIMITS.max_recent_turns) >= 2
    # And none of the recorded limits are anything other than those three values.
    all_memory_limits = set(recorded["memories"])
    all_goal_limits = set(recorded["goals"])
    all_turn_limits = set(recorded["turns"])
    assert all_memory_limits == {REFLECTION_CONTEXT_LIMITS.max_memories}
    assert all_goal_limits == {REFLECTION_CONTEXT_LIMITS.max_goals}
    assert all_turn_limits == {REFLECTION_CONTEXT_LIMITS.max_recent_turns}


# -------------------------------------------------------------
# Sprint 8 regression gate — Decision 1 branching still correct
# -------------------------------------------------------------


def test_sprint_8_decision_1_shape_still_holds_after_floor() -> None:
    policy = OpportunityPolicy()  # shipped defaults (= floors)
    # Memory alone triggers.
    assert (
        policy.evaluate(
            OpportunitySignals(
                new_confirmed_memories=DEFAULT_MIN_NEW_MEMORIES,
                meaningful_goal_events=0,
                pending_backlog=0,
                seconds_since_last_run=None,
            )
        ).should_run
        is True
    )
    # Goals alone trigger.
    assert (
        policy.evaluate(
            OpportunitySignals(
                new_confirmed_memories=0,
                meaningful_goal_events=DEFAULT_MIN_GOAL_EVENTS,
                pending_backlog=0,
                seconds_since_last_run=None,
            )
        ).should_run
        is True
    )
    # Neither triggers.
    assert (
        policy.evaluate(
            OpportunitySignals(
                new_confirmed_memories=0,
                meaningful_goal_events=0,
                pending_backlog=0,
                seconds_since_last_run=None,
            )
        ).should_run
        is False
    )
    # Backlog full blocks even a strong trigger.
    assert (
        policy.evaluate(
            OpportunitySignals(
                new_confirmed_memories=100,
                meaningful_goal_events=100,
                pending_backlog=10,  # == default max_pending_backlog
                seconds_since_last_run=None,
            )
        ).should_run
        is False
    )
    # Cooldown active blocks a strong trigger.
    assert (
        policy.evaluate(
            OpportunitySignals(
                new_confirmed_memories=100,
                meaningful_goal_events=100,
                pending_backlog=0,
                seconds_since_last_run=10.0,  # well below default cooldown
            )
        ).should_run
        is False
    )
