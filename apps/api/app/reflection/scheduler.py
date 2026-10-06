"""Reflection scheduler + opportunity policy (Sprint 8).

The scheduler fires as a background task AFTER every completed chat
turn. The opportunity policy decides whether this is a worthwhile
moment to actually run reflection. The policy is deterministic,
testable, and conservative — it prefers to SKIP.

Decision 1 (founder):

    should_run = meaningful_trigger
                 AND cooldown_expired
                 AND pending_backlog_below_limit

    meaningful_trigger =
          new_confirmed_memories >= REFLECTION_MIN_NEW_MEMORIES
       OR meaningful_goal_events >= REFLECTION_MIN_GOAL_EVENTS

Decision 2 (founder):

    "new confirmed memories since the last successful reflection run"
    uses `memories.confirmed_at`, the IMMUTABLE moment the memory went
    from candidate to durable. Not `memories.created_at` (which is the
    same today, but the Memory lifecycle does not promise that forever)
    and not `last_confirmed_at` (which can advance on edits).

The scheduler NEVER raises into the chat path. The chat response is
already persisted when this task runs, and any exception is swallowed
with a logged `reflection.schedule.failed`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.goal.models import GoalEvent
from app.memory.models import Memory
from app.observability.logging import get_logger
from app.reflection.extractor import ReflectionExtractor
from app.reflection.service import ReflectionService
from app.twin.models import Twin

logger = get_logger(__name__)


# Default thresholds. The Settings object below can override each one;
# tests pin the defaults so a future tweak is a visible change.
DEFAULT_MIN_NEW_MEMORIES: int = 3
DEFAULT_MIN_GOAL_EVENTS: int = 2
DEFAULT_COOLDOWN_SECONDS: int = 1800
DEFAULT_MAX_PENDING_BACKLOG: int = 10


@dataclass(frozen=True, slots=True)
class OpportunitySignals:
    """Raw inputs the policy consults. Pure data, no I/O."""

    new_confirmed_memories: int
    meaningful_goal_events: int
    pending_backlog: int
    seconds_since_last_run: float | None  # None if the twin has never run


@dataclass(frozen=True, slots=True)
class ReflectionOpportunity:
    """What the policy decided."""

    should_run: bool
    reason: str  # short machine tag — never user content
    signals: OpportunitySignals


@dataclass(frozen=True, slots=True)
class OpportunityPolicy:
    """Deterministic opportunity-detection policy."""

    min_new_memories: int = DEFAULT_MIN_NEW_MEMORIES
    min_goal_events: int = DEFAULT_MIN_GOAL_EVENTS
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    max_pending_backlog: int = DEFAULT_MAX_PENDING_BACKLOG

    @classmethod
    def from_settings(cls, settings: Settings) -> OpportunityPolicy:
        """Build a policy from runtime settings.

        Each setting is optional on `Settings`; if not present we fall
        back to the module default. We read via `getattr` so an older
        settings instance (e.g. in a Sprint-7 config fixture) still
        boots.
        """
        return cls(
            min_new_memories=int(
                getattr(settings, "reflection_min_new_memories", DEFAULT_MIN_NEW_MEMORIES)
            ),
            min_goal_events=int(
                getattr(settings, "reflection_min_goal_events", DEFAULT_MIN_GOAL_EVENTS)
            ),
            cooldown_seconds=int(
                getattr(settings, "reflection_min_cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
            ),
            max_pending_backlog=int(
                getattr(
                    settings,
                    "reflection_max_pending_backlog",
                    DEFAULT_MAX_PENDING_BACKLOG,
                )
            ),
        )

    def evaluate(self, signals: OpportunitySignals) -> ReflectionOpportunity:
        if signals.pending_backlog >= self.max_pending_backlog:
            return ReflectionOpportunity(
                should_run=False,
                reason="skip:backlog_full",
                signals=signals,
            )
        if (
            signals.seconds_since_last_run is not None
            and signals.seconds_since_last_run < self.cooldown_seconds
        ):
            return ReflectionOpportunity(
                should_run=False,
                reason="skip:cooldown_active",
                signals=signals,
            )
        meaningful = (
            signals.new_confirmed_memories >= self.min_new_memories
            or signals.meaningful_goal_events >= self.min_goal_events
        )
        if not meaningful:
            return ReflectionOpportunity(
                should_run=False,
                reason="skip:no_meaningful_trigger",
                signals=signals,
            )
        if signals.new_confirmed_memories >= self.min_new_memories:
            trigger = "run:new_memories"
        else:
            trigger = "run:goal_activity"
        return ReflectionOpportunity(
            should_run=True,
            reason=trigger,
            signals=signals,
        )


@dataclass(frozen=True, slots=True)
class ScheduleRunResult:
    """What `ReflectionScheduler.maybe_run` returns."""

    ran: bool
    opportunity: ReflectionOpportunity
    candidates_proposed: int = 0
    candidates_persisted: int = 0
    candidates_deduplicated: int = 0
    error: str | None = None


# --------------------------------------------------------------------
# Shared loaders (used by both the HTTP endpoint and the scheduler)
# --------------------------------------------------------------------
#
# These are the same bounded, owner-scoped loaders the Sprint-7
# `/v1/reflections/run` endpoint used inline. Lifted here so the
# scheduler can reuse them without the endpoint having to import the
# scheduler. The endpoint is updated to call these.


SCHEDULER_MAX_MEMORIES: int = 24
SCHEDULER_MAX_GOALS: int = 10
SCHEDULER_MAX_RECENT_TURNS: int = 20


async def load_recent_memories(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[uuid.UUID, str, str]]:
    stmt = (
        select(Memory)
        .where(
            Memory.twin_id == twin.id,
            Memory.user_id == twin.user_id,
            Memory.user_confirmed.is_(True),
            Memory.superseded_by_memory_id.is_(None),
        )
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [(m.id, m.type, m.content) for m in rows]


async def load_active_goals(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[uuid.UUID, str, str | None, int, str]]:
    from app.goal.models import Goal

    stmt = (
        select(Goal)
        .where(
            Goal.twin_id == twin.id,
            Goal.user_id == twin.user_id,
            Goal.status == "active",
        )
        .order_by(Goal.priority.asc(), Goal.updated_at.desc(), Goal.id.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [(g.id, g.title, g.description, g.priority, g.status) for g in rows]


async def load_recent_turns(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[str, str]]:
    from app.conversation.models import Conversation, Message

    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.twin_id == twin.id,
            Message.role.in_(("user", "twin")),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [(m.role, m.content) for m in reversed(rows)]


# --------------------------------------------------------------------
# Signal gathering + scheduler
# --------------------------------------------------------------------


async def gather_signals(session: AsyncSession, twin: Twin) -> OpportunitySignals:
    """Count the signals the policy needs. Owner-scoped by `twin`."""
    # Reference time for memory and goal activity: the twin's last
    # successful reflection run. If NULL (first run ever), count
    # everything that currently exists for the twin.
    last_run = twin.last_reflection_run_at

    mem_stmt = (
        select(func.count())
        .select_from(Memory)
        .where(
            Memory.twin_id == twin.id,
            Memory.user_id == twin.user_id,
            Memory.user_confirmed.is_(True),
            Memory.superseded_by_memory_id.is_(None),
            Memory.confirmed_at.is_not(None),
        )
    )
    if last_run is not None:
        mem_stmt = mem_stmt.where(Memory.confirmed_at > last_run)
    new_memories = int((await session.execute(mem_stmt)).scalar_one())

    # Meaningful goal activity: status_changed OR updated. `created`
    # would also count the GoalEvent emitted the moment a goal is first
    # created, which is noisy — skip it.
    from app.goal.models import Goal

    goal_stmt = (
        select(func.count())
        .select_from(GoalEvent)
        .join(Goal, Goal.id == GoalEvent.goal_id)
        .where(
            Goal.twin_id == twin.id,
            Goal.user_id == twin.user_id,
            GoalEvent.event_type.in_(("status_changed", "updated")),
        )
    )
    if last_run is not None:
        goal_stmt = goal_stmt.where(GoalEvent.created_at > last_run)
    goal_events = int((await session.execute(goal_stmt)).scalar_one())

    from app.reflection.models import ReflectionCandidate

    backlog_stmt = (
        select(func.count())
        .select_from(ReflectionCandidate)
        .where(
            ReflectionCandidate.twin_id == twin.id,
            ReflectionCandidate.user_id == twin.user_id,
            ReflectionCandidate.status == "pending",
        )
    )
    backlog = int((await session.execute(backlog_stmt)).scalar_one())

    seconds_since: float | None
    if last_run is None:
        seconds_since = None
    else:
        now = datetime.now(tz=UTC)
        delta = now - _as_aware(last_run)
        seconds_since = max(0.0, delta.total_seconds())
    return OpportunitySignals(
        new_confirmed_memories=new_memories,
        meaningful_goal_events=goal_events,
        pending_backlog=backlog,
        seconds_since_last_run=seconds_since,
    )


def _as_aware(dt: datetime) -> datetime:
    """Return `dt` with a tzinfo attached. SQLite round-trips the
    column as naive on some platforms; treat naive as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class ReflectionScheduler:
    """Orchestration layer between the chat pipeline and ReflectionService.

    Infrastructure-independent: takes the dependencies it needs by
    constructor arg. No Redis, no cron, no scheduled jobs. Callable
    from a background `TaskRunner` task or directly from tests.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        extractor: ReflectionExtractor,
        reflection_service: ReflectionService,
        policy: OpportunityPolicy,
    ) -> None:
        self._session = session
        self._extractor = extractor
        self._reflection_service = reflection_service
        self._policy = policy

    async def maybe_run(self, twin: Twin) -> ScheduleRunResult:
        signals = await gather_signals(self._session, twin)
        opportunity = self._policy.evaluate(signals)
        if not opportunity.should_run:
            logger.info(
                "reflection.opportunity.skipped",
                twin_id=str(twin.id),
                reason=opportunity.reason,
                new_memories=signals.new_confirmed_memories,
                goal_events=signals.meaningful_goal_events,
                pending_backlog=signals.pending_backlog,
                seconds_since_last_run=signals.seconds_since_last_run,
            )
            return ScheduleRunResult(ran=False, opportunity=opportunity)

        logger.info(
            "reflection.opportunity.detected",
            twin_id=str(twin.id),
            reason=opportunity.reason,
            new_memories=signals.new_confirmed_memories,
            goal_events=signals.meaningful_goal_events,
            pending_backlog=signals.pending_backlog,
            seconds_since_last_run=signals.seconds_since_last_run,
        )
        logger.info("reflection.schedule.started", twin_id=str(twin.id))

        memory_rows = await load_recent_memories(self._session, twin, limit=SCHEDULER_MAX_MEMORIES)
        goal_rows = await load_active_goals(self._session, twin, limit=SCHEDULER_MAX_GOALS)
        turn_rows = await load_recent_turns(self._session, twin, limit=SCHEDULER_MAX_RECENT_TURNS)
        profile = twin.profile
        extraction = await self._extractor.extract(
            memories=memory_rows,
            goals=goal_rows,
            recent_turns=turn_rows,
            profile_style=profile.communication_style_preset,
            profile_notes=profile.communication_style_notes,
            basic_profile=profile.basic_profile or {},
        )
        if extraction.error:
            logger.warning(
                "reflection.schedule.failed",
                twin_id=str(twin.id),
                error=extraction.error,
            )
            # Do NOT advance `last_reflection_run_at` on an error — the
            # next chat can re-attempt once the cooldown window applies
            # to a successful run only.
            return ScheduleRunResult(
                ran=False,
                opportunity=opportunity,
                error=extraction.error,
            )

        created, deduplicated = await self._reflection_service.create_candidates(
            twin, extraction.drafts
        )
        # Advance the last-run timestamp inside the same transaction
        # so a crash between the create and the stamp either rolls both
        # back together or commits both together.
        twin.last_reflection_run_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(twin)
        logger.info(
            "reflection.schedule.completed",
            twin_id=str(twin.id),
            candidates_proposed=len(extraction.drafts),
            candidates_persisted=len(created),
            candidates_deduplicated=deduplicated,
        )
        return ScheduleRunResult(
            ran=True,
            opportunity=opportunity,
            candidates_proposed=len(extraction.drafts),
            candidates_persisted=len(created),
            candidates_deduplicated=deduplicated,
        )
