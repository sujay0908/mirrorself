"""/v1/reflections — list, confirm, reject, manual run (Sprint 7).

Manual trigger only. There is no cron, no background queue, no
scheduled reflection in Sprint 7 — a run is a synchronous HTTP call
and the user is told via the response whether it succeeded.

Owner-scope every read/write via `TwinService.require_by_user`.
A wrong-owner reflection id yields 404, not 403, to avoid leaking
existence.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    LLMProviderDep,
    MemoryRetrieverDep,
    MemoryServiceDep,
    ReflectionExtractorDep,
    ReflectionServiceDep,
    SettingsDep,
    TwinServiceDep,
)
from app.conversation.models import Message
from app.memory.models import Memory
from app.reflection.schemas import (
    ReflectionConfirmOut,
    ReflectionListOut,
    ReflectionOut,
    ReflectionRunOut,
    ReflectionStatus,
)
from app.twin.models import Twin

router = APIRouter()

# Reflection input is bounded to keep the LLM call predictable.
# These caps are deliberately smaller than the chat-time ContextBudget
# because reflection is run on demand, not every turn.
_MAX_MEMORIES = 24
_MAX_GOALS = 10
_MAX_RECENT_TURNS = 20

_STATUS_QUERY = Query(default="pending", alias="status")


@router.get("", response_model=ReflectionListOut)
async def list_reflections(
    user: CurrentUser,
    twins: TwinServiceDep,
    reflections: ReflectionServiceDep,
    status_filter: ReflectionStatus | str | None = _STATUS_QUERY,
) -> ReflectionListOut:
    twin = await twins.require_by_user(user.user_id)
    # Allow `?status=all` to mean "no filter".
    filter_value = None if status_filter == "all" else status_filter
    items = await reflections.list_for_twin(twin, status_filter=filter_value)
    return ReflectionListOut(items=[ReflectionOut.model_validate(r) for r in items])


@router.post("/{reflection_id}/confirm", response_model=ReflectionConfirmOut)
async def confirm_reflection(
    reflection_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    reflections: ReflectionServiceDep,
    memories: MemoryServiceDep,
) -> ReflectionConfirmOut:
    twin = await twins.require_by_user(user.user_id)
    candidate, applied, apply_metadata = await reflections.confirm(
        twin,
        reflection_id,
        twin_service=twins,
        memory_service=memories,
    )
    return ReflectionConfirmOut(
        reflection=ReflectionOut.model_validate(candidate),
        applied=applied,
        apply_metadata=apply_metadata,
    )


@router.post("/{reflection_id}/reject", response_model=ReflectionOut)
async def reject_reflection(
    reflection_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    reflections: ReflectionServiceDep,
) -> ReflectionOut:
    twin = await twins.require_by_user(user.user_id)
    candidate = await reflections.reject(twin, reflection_id)
    return ReflectionOut.model_validate(candidate)


@router.post(
    "/run",
    response_model=ReflectionRunOut,
    status_code=status.HTTP_200_OK,
)
async def run_reflection(
    user: CurrentUser,
    twins: TwinServiceDep,
    reflections: ReflectionServiceDep,
    extractor: ReflectionExtractorDep,
    retriever: MemoryRetrieverDep,
    settings: SettingsDep,
    llm: LLMProviderDep,  # noqa: ARG001 — kept so the dependency boots
) -> ReflectionRunOut:
    """Manually trigger a reflection run.

    Synchronous for Sprint 7. The LLM call plus a bounded SQL
    footprint is the only cost. Rate-limiting + scheduled triggers
    are Sprint 8.
    """
    twin = await twins.require_by_user(user.user_id)
    # Pull bounded, owner-scoped input. The service layer always
    # filters by twin_id + user_id so cross-user leakage is
    # impossible here.
    #
    # We only use `MemoryService.list_for_twin`-shaped reads
    # directly to avoid pulling the memory_sources/embeddings graph.
    session = reflections._session
    memory_rows = await _load_recent_memories(session, twin, limit=_MAX_MEMORIES)
    goal_rows = await _load_active_goals(session, twin, limit=_MAX_GOALS)
    turn_rows = await _load_recent_turns(session, twin, limit=_MAX_RECENT_TURNS)

    profile = twin.profile
    try:
        extraction = await extractor.extract(
            memories=memory_rows,
            goals=goal_rows,
            recent_turns=turn_rows,
            profile_style=profile.communication_style_preset,
            profile_notes=profile.communication_style_notes,
            basic_profile=profile.basic_profile or {},
        )
    except Exception as exc:  # pragma: no cover — extractor never raises
        return ReflectionRunOut(
            candidates_proposed=0,
            candidates_persisted=0,
            candidates_deduplicated=0,
            error=f"unhandled:{type(exc).__name__}",
        )

    if extraction.error:
        return ReflectionRunOut(
            candidates_proposed=0,
            candidates_persisted=0,
            candidates_deduplicated=0,
            error=extraction.error,
        )

    created, deduplicated = await reflections.create_candidates(twin, extraction.drafts)
    return ReflectionRunOut(
        candidates_proposed=len(extraction.drafts),
        candidates_persisted=len(created),
        candidates_deduplicated=deduplicated,
    )


# ---------------------------------------------------------------------
# Reflection-run input loaders — bounded, owner-scoped
# ---------------------------------------------------------------------


async def _load_recent_memories(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[uuid.UUID, str, str]]:
    """Load up to `limit` confirmed, non-superseded memories, newest first."""
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


async def _load_active_goals(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[uuid.UUID, str, str | None, int, str]]:
    """Load up to `limit` active goals, highest-priority first."""
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


async def _load_recent_turns(
    session: AsyncSession, twin: Twin, *, limit: int
) -> list[tuple[str, str]]:
    """Load up to `limit` recent user/twin messages across any
    conversation owned by this twin, newest first.
    """
    from app.conversation.models import Conversation

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
    # Return in chronological order (oldest → newest) so the extractor
    # reads it the natural way.
    return [(m.role, m.content) for m in reversed(rows)]
