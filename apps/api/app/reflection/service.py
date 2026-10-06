"""ReflectionService — persist, confirm, reject reflection candidates.

Ownership model:

- Every public method takes the authenticated user's `Twin` ORM
  instance. The service never accepts a bare `twin_id` or `user_id`
  from a request body. Cross-user access via a guessed ID is
  impossible from the API layer.
- The individual-candidate lookup `_require_owned_candidate` filters
  by `id` + `twin_id` + `user_id` as belt-and-braces.

Apply dispatcher:

- `profile_update`  → `TwinService.update(user_id, TwinProfilePatch)`
  (the user-authored path; the LLM proposes, the service writes).
- `memory_dedup`    → `MemoryService.supersede(twin, …)` (non-destructive).
- `goal_update`     → records a `GoalEvent` on the referenced goal
  (non-destructive; no change to title / status / priority).
- `insight`         → acknowledged only; NO Memory row is created,
  NO TwinProfile field is written (founder decision #1).

Durability guarantees:

- Confirm transitions `pending → confirmed` under a single transaction
  BEFORE the per-kind apply runs. The apply then runs in a fresh unit
  of work via the same session; if it fails, the candidate stays
  `status='confirmed'` with `apply_error` populated, and the user is
  told the apply did not complete. The candidate is NEVER re-opened to
  `pending` (double-apply prevention).
- Reject transitions `pending → rejected` and never writes anywhere
  else.

Deduplication:

- `create_candidates` filters drafts whose fingerprint already has a
  pending row on the same twin. Fingerprint =
  `sha256(twin_id, kind, sorted(source_memory_ids), sorted(source_goal_ids))`.
  Deterministic by construction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.service import EvolutionService
from app.goal.models import Goal, GoalEvent
from app.memory.service import MemoryService
from app.observability.logging import get_logger
from app.reflection.errors import (
    ReflectionAlreadyResolvedError,
    ReflectionApplyError,
    ReflectionNotFoundError,
)
from app.reflection.models import REFLECTION_KINDS, ReflectionCandidate
from app.reflection.schemas import (
    GoalUpdatePayload,
    InsightPayload,
    MemoryDedupPayload,
    ProfileUpdatePayload,
    ReflectionDraft,
)
from app.twin.models import Twin
from app.twin.schemas import TwinProfilePatch
from app.twin.service import TwinService

logger = get_logger(__name__)


def _candidate_fingerprint(
    *,
    twin_id: uuid.UUID,
    kind: str,
    source_memory_ids: list[str],
    source_goal_ids: list[str],
) -> str:
    """Deterministic SHA-256 over the input tuple.

    Sorted lists so the order the extractor emits does not change the
    fingerprint. Stable across runs so a repeated `/v1/reflections/run`
    does not surface the same proposal twice.
    """
    payload = {
        "twin_id": str(twin_id),
        "kind": kind,
        "memories": sorted(source_memory_ids),
        "goals": sorted(source_goal_ids),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ReflectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def list_for_twin(
        self,
        twin: Twin,
        *,
        status_filter: str | None = "pending",
    ) -> Sequence[ReflectionCandidate]:
        stmt = (
            select(ReflectionCandidate)
            .where(
                ReflectionCandidate.twin_id == twin.id,
                ReflectionCandidate.user_id == twin.user_id,
            )
            .order_by(
                ReflectionCandidate.created_at.desc(),
                ReflectionCandidate.id.asc(),
            )
        )
        if status_filter is not None:
            stmt = stmt.where(ReflectionCandidate.status == status_filter)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, twin: Twin, reflection_id: uuid.UUID) -> ReflectionCandidate:
        return await self._require_owned_candidate(twin, reflection_id)

    # ------------------------------------------------------------------
    # Create (idempotent on fingerprint)
    # ------------------------------------------------------------------

    async def create_candidates(
        self,
        twin: Twin,
        drafts: Sequence[ReflectionDraft],
    ) -> tuple[list[ReflectionCandidate], int]:
        """Persist drafts as `pending` candidates, deduplicating by
        fingerprint against the twin's existing pending backlog.

        Returns `(created_rows, deduplicated_count)`.
        """
        if not drafts:
            return [], 0

        # Load the current set of pending fingerprints for this twin
        # ONCE so we don't do N queries for N drafts.
        existing_stmt = select(ReflectionCandidate.fingerprint).where(
            ReflectionCandidate.twin_id == twin.id,
            ReflectionCandidate.status == "pending",
            ReflectionCandidate.fingerprint.is_not(None),
        )
        existing_fingerprints = set((await self._session.execute(existing_stmt)).scalars())

        created: list[ReflectionCandidate] = []
        deduplicated = 0
        seen_in_batch: set[str] = set()
        for draft in drafts:
            source_memory_ids = [str(x) for x in draft.source_memory_ids]
            source_goal_ids = [str(x) for x in draft.source_goal_ids]
            fp = _candidate_fingerprint(
                twin_id=twin.id,
                kind=draft.kind,
                source_memory_ids=source_memory_ids,
                source_goal_ids=source_goal_ids,
            )
            if fp in existing_fingerprints or fp in seen_in_batch:
                deduplicated += 1
                continue
            seen_in_batch.add(fp)
            row = ReflectionCandidate(
                user_id=twin.user_id,
                twin_id=twin.id,
                kind=draft.kind,
                status="pending",
                proposed_payload=draft.payload,
                source_memory_ids=source_memory_ids,
                source_goal_ids=source_goal_ids,
                rationale=draft.rationale,
                confidence=draft.confidence,
                importance=draft.importance,
                fingerprint=fp,
            )
            self._session.add(row)
            created.append(row)
        await self._session.flush()
        await self._session.commit()
        for row in created:
            await self._session.refresh(row)
        logger.info(
            "reflection.candidate.proposed",
            twin_id=str(twin.id),
            created=len(created),
            deduplicated=deduplicated,
        )
        return created, deduplicated

    # ------------------------------------------------------------------
    # Confirm / reject (status transitions)
    # ------------------------------------------------------------------

    async def confirm(
        self,
        twin: Twin,
        reflection_id: uuid.UUID,
        *,
        twin_service: TwinService,
        memory_service: MemoryService,
        evolution_service: EvolutionService | None = None,
    ) -> tuple[ReflectionCandidate, bool, dict[str, Any]]:
        """Transition pending → confirmed and run the per-kind apply.

        The status change is committed BEFORE the apply runs so a
        duplicate confirmation request can never run the apply twice.
        If the apply itself fails, the candidate stays `confirmed`
        with `apply_error` populated AND no evolution event is written
        (Decision 3: only confirmed-and-applied is evolution).

        `evolution_service` is optional so Sprint 7 call sites that
        construct a confirm pipeline without the Sprint 8 writer still
        work; the HTTP endpoint always passes one.
        """
        candidate = await self._require_owned_candidate(twin, reflection_id)
        if candidate.status != "pending":
            raise ReflectionAlreadyResolvedError(
                f"Reflection is already {candidate.status!r}.",
                details={
                    "reflection_id": str(candidate.id),
                    "status": candidate.status,
                },
            )

        now = datetime.now(tz=UTC)
        candidate.status = "confirmed"
        candidate.resolved_at = now
        await self._session.commit()
        await self._session.refresh(candidate)

        logger.info(
            "reflection.candidate.confirmed",
            reflection_id=str(candidate.id),
            kind=candidate.kind,
            twin_id=str(twin.id),
        )

        try:
            applied, apply_metadata = await self._apply(
                twin,
                candidate,
                twin_service=twin_service,
                memory_service=memory_service,
            )
        except Exception as exc:
            candidate.apply_error = f"{type(exc).__name__}:{str(exc)[:200]}"
            await self._session.commit()
            await self._session.refresh(candidate)
            logger.warning(
                "reflection.apply.failed",
                reflection_id=str(candidate.id),
                kind=candidate.kind,
                twin_id=str(twin.id),
                error=type(exc).__name__,
            )
            raise ReflectionApplyError(
                "Reflection confirmed but apply failed.",
                details={
                    "reflection_id": str(candidate.id),
                    "error": type(exc).__name__,
                },
            ) from exc

        candidate.apply_metadata = apply_metadata
        await self._session.commit()
        await self._session.refresh(candidate)
        logger.info(
            "reflection.apply.ok",
            reflection_id=str(candidate.id),
            kind=candidate.kind,
            twin_id=str(twin.id),
        )

        # Sprint 8 (Decision 3 + "ReflectionCandidate != EvolutionEvent"):
        # evolution is written ONLY after a successful apply. A reject,
        # a failed apply, or a pending candidate NEVER produces one.
        if evolution_service is not None and applied:
            await self._record_evolution_for(
                twin,
                candidate=candidate,
                apply_metadata=apply_metadata,
                evolution_service=evolution_service,
            )
            await self._session.commit()
        return candidate, applied, apply_metadata

    async def _record_evolution_for(
        self,
        twin: Twin,
        *,
        candidate: ReflectionCandidate,
        apply_metadata: dict[str, Any],
        evolution_service: EvolutionService,
    ) -> None:
        """Translate a successfully-applied candidate into one evolution row.

        Summaries are composed from IDs + the kind-of-change only — never
        from stored content. The Sprint 7 insight contract says insight
        confirmation is acknowledgement, not identity mutation: this
        branch writes a distinct `insight_acknowledged` event type and
        the mobile UI treats it as "You acknowledged…" rather than
        "Your Twin learned…".
        """
        kind = candidate.kind
        if kind == "profile_update":
            field = str(apply_metadata.get("field") or "")
            await evolution_service.record(
                twin,
                event_type="profile_confirmed",
                summary=(
                    f"profile.{field} updated via confirmed reflection"
                    if field
                    else "profile updated via confirmed reflection"
                ),
                reflection_id=candidate.id,
                profile_field=field or None,
            )
            return
        if kind == "memory_dedup":
            superseded_id = apply_metadata.get("superseded_memory_id")
            await evolution_service.record(
                twin,
                event_type="memory_consolidated",
                summary="two memories consolidated via confirmed dedup",
                reflection_id=candidate.id,
                memory_id=(uuid.UUID(superseded_id) if isinstance(superseded_id, str) else None),
            )
            return
        if kind == "goal_update":
            goal_id = apply_metadata.get("goal_id")
            await evolution_service.record(
                twin,
                event_type="goal_updated",
                summary="goal note appended via confirmed reflection",
                reflection_id=candidate.id,
                goal_id=(uuid.UUID(goal_id) if isinstance(goal_id, str) else None),
            )
            return
        if kind == "insight":
            await evolution_service.record(
                twin,
                event_type="insight_acknowledged",
                summary="insight acknowledged (no memory or profile change)",
                reflection_id=candidate.id,
            )
            return

    async def reject(self, twin: Twin, reflection_id: uuid.UUID) -> ReflectionCandidate:
        candidate = await self._require_owned_candidate(twin, reflection_id)
        if candidate.status != "pending":
            raise ReflectionAlreadyResolvedError(
                f"Reflection is already {candidate.status!r}.",
                details={
                    "reflection_id": str(candidate.id),
                    "status": candidate.status,
                },
            )
        candidate.status = "rejected"
        candidate.resolved_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(candidate)
        logger.info(
            "reflection.candidate.rejected",
            reflection_id=str(candidate.id),
            kind=candidate.kind,
            twin_id=str(twin.id),
        )
        return candidate

    # ------------------------------------------------------------------
    # Apply dispatcher
    # ------------------------------------------------------------------

    async def _apply(
        self,
        twin: Twin,
        candidate: ReflectionCandidate,
        *,
        twin_service: TwinService,
        memory_service: MemoryService,
    ) -> tuple[bool, dict[str, Any]]:
        """Dispatch per-kind apply. Returns (applied, apply_metadata).

        Each branch returns an IDs-only metadata dict so the audit
        trail can show what changed without copying content.
        """
        kind = candidate.kind
        payload_raw = candidate.proposed_payload

        if kind == "profile_update":
            profile_payload = ProfileUpdatePayload.model_validate(payload_raw)
            # Build a TwinProfilePatch with ONLY the single field being
            # proposed. Reusing the user-authored update path keeps the
            # LLM-never-mutates-profile invariant intact: the write
            # runs through TwinService.update exactly as a PATCH /v1/twin
            # from the user would.
            patch_kwargs: dict[str, Any] = {
                profile_payload.field: profile_payload.proposed_value,
            }
            await twin_service.update(twin.user_id, TwinProfilePatch(**patch_kwargs))
            return True, {
                "kind": "profile_update",
                "field": profile_payload.field,
                "twin_id": str(twin.id),
            }

        if kind == "memory_dedup":
            dedup_payload = MemoryDedupPayload.model_validate(payload_raw)
            superseded = await memory_service.supersede(
                twin,
                dedup_payload.superseded_memory_id,
                dedup_payload.canonical_memory_id,
            )
            return True, {
                "kind": "memory_dedup",
                "superseded_memory_id": str(superseded.id),
                "canonical_memory_id": str(dedup_payload.canonical_memory_id),
            }

        if kind == "goal_update":
            goal_payload = GoalUpdatePayload.model_validate(payload_raw)
            # Non-destructive: write a GoalEvent of type `updated`
            # with the proposed note. Does NOT change title, status
            # or priority — the user acts on the note separately
            # from the goal detail screen if they want to.
            goal_id = goal_payload.goal_id
            goal = (
                await self._session.execute(
                    select(Goal).where(
                        Goal.id == goal_id,
                        Goal.twin_id == twin.id,
                        Goal.user_id == twin.user_id,
                    )
                )
            ).scalar_one_or_none()
            if goal is None:
                raise ReflectionApplyError(
                    "Goal not found or not yours.",
                    details={"goal_id": str(goal_id)},
                )
            event = GoalEvent(
                goal_id=goal.id,
                event_type="updated",
                from_status=None,
                to_status=None,
                note=goal_payload.note,
            )
            self._session.add(event)
            await self._session.flush()
            return True, {
                "kind": "goal_update",
                "goal_id": str(goal.id),
                "goal_event_id": str(event.id),
            }

        if kind == "insight":
            # Founder decision #1: confirming an insight is the
            # acknowledgement — nothing durable is created. No
            # Memory row, no TwinProfile mutation. The reflection row
            # itself is the record.
            InsightPayload.model_validate(payload_raw)
            return True, {"kind": "insight", "acknowledged": True}

        # Defence-in-depth: an unknown kind should have been caught by
        # the CHECK constraint on the way in. If somehow it got past
        # that, we fail the apply cleanly.
        raise ReflectionApplyError(
            f"Unsupported reflection kind: {kind!r}",
            details={"kind": kind},
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_owned_candidate(
        self, twin: Twin, reflection_id: uuid.UUID
    ) -> ReflectionCandidate:
        stmt = select(ReflectionCandidate).where(
            ReflectionCandidate.id == reflection_id,
            ReflectionCandidate.twin_id == twin.id,
            ReflectionCandidate.user_id == twin.user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ReflectionNotFoundError(
                "Reflection not found.",
                details={"reflection_id": str(reflection_id)},
            )
        return row


# Re-export so callers import the kind set from one place.
__all__ = ["ReflectionService", "REFLECTION_KINDS", "_candidate_fingerprint"]
