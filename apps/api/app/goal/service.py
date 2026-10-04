"""Goal domain service.

Ownership model:

- Every public method takes the authenticated user's `Twin` ORM instance
  (resolved upstream from the JWT). The service never accepts a bare
  `twin_id` or `user_id` from a request body. This makes it structurally
  impossible to read or mutate another user's goal from the API layer.
- The individual-goal lookup `_require_owned_goal` always filters by both
  `twin_id` AND `user_id` as a belt-and-braces check against a Twin ORM
  instance that somehow escaped scope.

Status transitions:

- The initial status is always `active`.
- Legal transitions are:
    active     -> achieved | abandoned | paused
    paused     -> active   | achieved  | abandoned
    achieved   -> (terminal; no transitions)
    abandoned  -> (terminal; no transitions)
- Any other transition raises `InvalidGoalStatusTransitionError`. Terminal
  states are terminal by policy, not by DB.

Append-only event log:

- `created`, `updated` and `status_changed` events are appended to
  `goal_events`. No code path deletes rows from that table.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.goal.errors import (
    GoalNotFoundError,
    InvalidGoalStatusTransitionError,
)
from app.goal.models import Goal, GoalEvent
from app.goal.schemas import GoalCreateIn, GoalUpdateIn
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


# Service-layer policy, deliberately not a DB CHECK so Sprint 5+ can evolve
# transitions without a migration.
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"achieved", "abandoned", "paused"}),
    "paused": frozenset({"active", "achieved", "abandoned"}),
    # Terminal states.
    "achieved": frozenset(),
    "abandoned": frozenset(),
}


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    async def list_for_twin(
        self,
        twin: Twin,
        *,
        status: str | None = None,
    ) -> Sequence[Goal]:
        """List goals owned by this twin, newest-updated first.

        If `status` is provided it is applied as an equality filter. Order:
        updated_at DESC, id ASC for a deterministic tiebreak.
        """
        stmt = (
            select(Goal)
            .where(Goal.twin_id == twin.id, Goal.user_id == twin.user_id)
            .order_by(Goal.updated_at.desc(), Goal.id.asc())
        )
        if status is not None:
            stmt = stmt.where(Goal.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_active_for_context(self, twin: Twin, *, limit: int) -> Sequence[Goal]:
        """Deterministic ordering for TwinContext (DF8).

        Order: priority ASC (1 is highest), then updated_at DESC, then id ASC.
        The `id` tiebreaker makes test assertions stable.
        """
        if limit <= 0:
            return []
        stmt = (
            select(Goal)
            .where(
                Goal.twin_id == twin.id,
                Goal.user_id == twin.user_id,
                Goal.status == "active",
            )
            .order_by(
                Goal.priority.asc(),
                Goal.updated_at.desc(),
                Goal.id.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, twin: Twin, goal_id: uuid.UUID) -> Goal:
        """Return a goal owned by this twin or raise GoalNotFoundError."""
        return await self._require_owned_goal(twin, goal_id)

    async def list_events(self, twin: Twin, goal_id: uuid.UUID) -> Sequence[GoalEvent]:
        # Resolve the goal first so a wrong-owner / unknown id yields 404
        # rather than an empty list.
        await self._require_owned_goal(twin, goal_id)
        stmt = (
            select(GoalEvent)
            .where(GoalEvent.goal_id == goal_id)
            .order_by(GoalEvent.created_at.asc(), GoalEvent.id.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------

    async def create(self, twin: Twin, payload: GoalCreateIn) -> Goal:
        goal = Goal(
            user_id=twin.user_id,
            twin_id=twin.id,
            title=payload.title,
            description=payload.description,
            target_date=_as_aware(payload.target_date),
            priority=payload.priority,
            status="active",
        )
        self._session.add(goal)
        await self._session.flush()
        # Add the audit event through the session directly (not via
        # `goal.events.append`) so this code path never triggers a lazy load
        # of the brand-new goal's events collection — on an async session
        # that would raise MissingGreenlet.
        self._session.add(
            GoalEvent(
                goal_id=goal.id,
                event_type="created",
                from_status=None,
                to_status="active",
                note=None,
            )
        )
        await self._session.commit()
        await self._session.refresh(goal)
        logger.info(
            "goal.created",
            twin_id=str(twin.id),
            goal_id=str(goal.id),
            priority=goal.priority,
        )
        return goal

    async def update(
        self,
        twin: Twin,
        goal_id: uuid.UUID,
        patch: GoalUpdateIn,
    ) -> Goal:
        goal = await self._require_owned_goal(twin, goal_id)

        # Capture whether anything actually changed so we don't emit a
        # misleading `updated` event when the PATCH body was a no-op.
        content_changed = False
        if patch.title is not None and patch.title != goal.title:
            goal.title = patch.title
            content_changed = True
        if patch.description is not None and patch.description != goal.description:
            goal.description = patch.description
            content_changed = True
        if patch.target_date is not None:
            new_td = _as_aware(patch.target_date)
            if new_td != goal.target_date:
                goal.target_date = new_td
                content_changed = True
        if patch.priority is not None and patch.priority != goal.priority:
            goal.priority = patch.priority
            content_changed = True

        if content_changed:
            goal.events.append(
                GoalEvent(
                    goal_id=goal.id,
                    event_type="updated",
                    from_status=None,
                    to_status=None,
                    note=None,
                )
            )

        # Status change is handled separately so it emits a `status_changed`
        # event rather than piggy-backing on `updated`.
        if patch.status is not None and patch.status != goal.status:
            self._assert_legal_transition(goal.status, patch.status)
            old_status = goal.status
            goal.status = patch.status
            goal.status_changed_at = datetime.now(tz=UTC)
            goal.events.append(
                GoalEvent(
                    goal_id=goal.id,
                    event_type="status_changed",
                    from_status=old_status,
                    to_status=patch.status,
                    note=patch.status_note,
                )
            )
            logger.info(
                "goal.status_changed",
                twin_id=str(twin.id),
                goal_id=str(goal.id),
                from_status=old_status,
                to_status=patch.status,
            )

        await self._session.commit()
        await self._session.refresh(goal)
        return goal

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_owned_goal(self, twin: Twin, goal_id: uuid.UUID) -> Goal:
        stmt = (
            select(Goal)
            .where(
                Goal.id == goal_id,
                Goal.twin_id == twin.id,
                Goal.user_id == twin.user_id,
            )
            .options(selectinload(Goal.events))
        )
        goal = (await self._session.execute(stmt)).scalar_one_or_none()
        if goal is None:
            raise GoalNotFoundError(
                "Goal not found.",
                details={"goal_id": str(goal_id)},
            )
        return goal

    @staticmethod
    def _assert_legal_transition(from_status: str, to_status: str) -> None:
        allowed = _LEGAL_TRANSITIONS.get(from_status, frozenset())
        if to_status not in allowed:
            raise InvalidGoalStatusTransitionError(
                "Illegal status transition.",
                details={"from": from_status, "to": to_status},
            )
