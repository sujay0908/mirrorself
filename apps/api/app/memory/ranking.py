"""Ranking policy for retrieved memory candidates.

A deterministic pure function — no DB access, no provider access — so it
can be unit-tested with hand-crafted inputs. The retriever assembles
candidates from the database, this module scores and orders them.

Formula (Sprint 3 baseline):

    score = w_sim  · similarity
          + w_imp  · importance
          + w_conf · confidence
          + w_rec  · recency_decay(now - last_touch, half_life_days)
          - w_stale · stale_penalty(now - last_confirmed_at, stale_days)

Weights (`DEFAULT_RANKING_WEIGHTS`) are tunable at construction time but
default to the values documented in
`docs/architecture/memory-retrieval.md`.

Similarity is cosine similarity in [-1, 1] (normalized to [0, 1] for the
weighted sum by the retriever). All other components are already in
[0, 1] with the exception of the stale penalty, which is in [0, 1] and
subtracted.

The ranking is intentionally transparent and deterministic so a tester
can predict `rank(a) > rank(b)` from the inputs alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class RankingWeights:
    w_sim: float = 1.0
    w_imp: float = 0.4
    w_conf: float = 0.2
    w_rec: float = 0.2
    w_stale: float = 0.3
    recency_half_life_days: float = 30.0
    stale_threshold_days: float = 180.0


DEFAULT_RANKING_WEIGHTS = RankingWeights()


@dataclass(slots=True)
class RankingInputs:
    """The signals needed to score one candidate."""

    memory_id: str
    similarity: float  # cosine in [-1, 1]
    importance: float  # [0, 1]
    confidence: float  # [0, 1]
    user_confirmed: bool
    created_at: datetime
    last_confirmed_at: datetime | None


@dataclass(slots=True)
class RankedCandidate:
    memory_id: str
    score: float
    similarity: float
    components: dict[str, float]


def _as_aware(dt: datetime) -> datetime:
    """SQLite loses tzinfo on roundtrip. Treat naive datetimes as UTC so
    arithmetic with aware `now` works without the TypeError that would
    otherwise bubble out of a hot code path.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _recency_decay(reference: datetime, now: datetime, half_life_days: float) -> float:
    """Exponential decay in [0, 1]. 1.0 at reference, 0.5 after half-life."""
    delta_days = (now - _as_aware(reference)).total_seconds() / 86400.0
    if delta_days <= 0:
        return 1.0
    return math.exp(-math.log(2.0) * delta_days / max(half_life_days, 1e-6))


def _stale_penalty(
    last_confirmed_at: datetime | None,
    now: datetime,
    stale_days: float,
) -> float:
    """0.0 while fresh, ramping linearly to 1.0 at `stale_days` past the
    confirmation. Memories that were never confirmed are treated as fresh
    (penalty 0) — the confirmation gate elsewhere handles that case.
    """
    if last_confirmed_at is None:
        return 0.0
    delta_days = (now - _as_aware(last_confirmed_at)).total_seconds() / 86400.0
    if delta_days <= 0:
        return 0.0
    return min(1.0, delta_days / max(stale_days, 1e-6))


def rank_candidates(
    candidates: list[RankingInputs],
    *,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
    now: datetime | None = None,
) -> list[RankedCandidate]:
    """Score and order candidates by descending score.

    Deterministic: same inputs → same output. Secondary sort key is the
    memory_id so ties are stable without depending on dict ordering.
    """
    now = now or datetime.now(tz=UTC)
    ranked: list[RankedCandidate] = []
    for c in candidates:
        sim_01 = (c.similarity + 1.0) / 2.0  # map [-1, 1] → [0, 1]
        last_touch = c.last_confirmed_at or c.created_at
        recency = _recency_decay(last_touch, now, weights.recency_half_life_days)
        stale = _stale_penalty(c.last_confirmed_at, now, weights.stale_threshold_days)
        components = {
            "similarity_01": sim_01,
            "importance": c.importance,
            "confidence": c.confidence,
            "recency": recency,
            "stale_penalty": stale,
        }
        score = (
            weights.w_sim * sim_01
            + weights.w_imp * c.importance
            + weights.w_conf * c.confidence
            + weights.w_rec * recency
            - weights.w_stale * stale
        )
        ranked.append(
            RankedCandidate(
                memory_id=c.memory_id,
                score=score,
                similarity=c.similarity,
                components=components,
            )
        )
    ranked.sort(key=lambda r: (-r.score, r.memory_id))
    return ranked
