"""Ranking is a pure function — exercised with hand-built inputs here.

Covers: determinism, tie-break stability, similarity dominance, importance
weighting, recency decay, stale penalty.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.memory.ranking import (
    DEFAULT_RANKING_WEIGHTS,
    RankingInputs,
    RankingWeights,
    rank_candidates,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def _mk(
    memory_id: str = "m1",
    *,
    similarity: float = 0.9,
    importance: float = 0.5,
    confidence: float = 0.9,
    user_confirmed: bool = True,
    created_at: datetime | None = None,
    last_confirmed_at: datetime | None = None,
) -> RankingInputs:
    return RankingInputs(
        memory_id=memory_id,
        similarity=similarity,
        importance=importance,
        confidence=confidence,
        user_confirmed=user_confirmed,
        created_at=created_at or NOW,
        last_confirmed_at=last_confirmed_at or NOW,
    )


def test_higher_similarity_ranks_higher() -> None:
    low = _mk("low", similarity=0.1)
    high = _mk("high", similarity=0.9)
    ranked = rank_candidates([low, high], now=NOW)
    assert [r.memory_id for r in ranked] == ["high", "low"]


def test_higher_importance_breaks_similarity_tie() -> None:
    a = _mk("a", similarity=0.5, importance=0.1)
    b = _mk("b", similarity=0.5, importance=0.9)
    ranked = rank_candidates([a, b], now=NOW)
    assert ranked[0].memory_id == "b"


def test_recency_decay_reduces_score() -> None:
    fresh = _mk("fresh", similarity=0.5, last_confirmed_at=NOW)
    stale = _mk(
        "stale",
        similarity=0.5,
        importance=0.5,
        last_confirmed_at=NOW - timedelta(days=90),
    )
    ranked = rank_candidates([fresh, stale], now=NOW)
    assert ranked[0].memory_id == "fresh"
    assert ranked[0].score > ranked[1].score


def test_stale_penalty_applies_only_past_threshold() -> None:
    thirty_days_old = _mk(
        "mid",
        similarity=0.5,
        last_confirmed_at=NOW - timedelta(days=30),
    )
    two_years_old = _mk(
        "old",
        similarity=0.5,
        last_confirmed_at=NOW - timedelta(days=720),
    )
    ranked = rank_candidates([thirty_days_old, two_years_old], now=NOW)
    # Both get similarity + importance + confidence credit; the older one
    # takes an additional stale-penalty hit AND a bigger recency decay.
    assert ranked[0].memory_id == "mid"


def test_ranking_is_deterministic_across_runs() -> None:
    inputs = [
        _mk("a", similarity=0.3),
        _mk("b", similarity=0.3),
        _mk("c", similarity=0.7),
    ]
    r1 = [r.memory_id for r in rank_candidates(inputs, now=NOW)]
    r2 = [r.memory_id for r in rank_candidates(inputs, now=NOW)]
    assert r1 == r2
    # Tie-break (a vs b with identical score) is alphabetical by memory_id.
    assert r1 == ["c", "a", "b"]


def test_components_expose_each_signal() -> None:
    ranked = rank_candidates([_mk("x", similarity=0.6, importance=0.8)], now=NOW)
    comps = ranked[0].components
    for key in (
        "similarity_01",
        "importance",
        "confidence",
        "recency",
        "stale_penalty",
    ):
        assert key in comps


def test_custom_weights_change_ranking() -> None:
    # With default weights (w_sim=1.0, w_imp=0.4), a bigger similarity gap
    # than importance gap lets similarity dominate. 0.9 vs 0.1 in sim is
    # a (0.5*(0.9-0.1))=0.4 effective swing; 0.1 vs 0.9 in importance is a
    # 0.4*0.8=0.32 effective swing. So `a` wins by default.
    a = _mk("a", similarity=0.9, importance=0.1)
    b = _mk("b", similarity=0.1, importance=0.9)
    default = [r.memory_id for r in rank_candidates([a, b], now=NOW)]
    assert default[0] == "a"
    # Flip the weights so importance dominates (and zero out confounds).
    importance_dominant = RankingWeights(
        w_sim=0.1,
        w_imp=1.0,
        w_conf=0.0,
        w_rec=0.0,
        w_stale=0.0,
    )
    flipped = [r.memory_id for r in rank_candidates([a, b], weights=importance_dominant, now=NOW)]
    assert flipped[0] == "b"


def test_default_weights_frozen() -> None:
    # Freeze guard: changes to the published default weighting are
    # intentional and need a doc update + a changelog note.
    w = DEFAULT_RANKING_WEIGHTS
    assert (w.w_sim, w.w_imp, w.w_conf, w.w_rec, w.w_stale) == (
        1.0,
        0.4,
        0.2,
        0.2,
        0.3,
    )
    assert (w.recency_half_life_days, w.stale_threshold_days) == (30.0, 180.0)
