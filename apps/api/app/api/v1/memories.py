"""/v1/memories and /v1/memory-candidates endpoints.

Two routers (`memories_router` and `candidates_router`) are mounted at
different prefixes so URL shapes match docs/api/api-conventions.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, MemoryServiceDep, TwinServiceDep
from app.memory.schemas import (
    MemoryCandidateConfirmOut,
    MemoryCandidateListOut,
    MemoryCandidateOut,
    MemoryListOut,
    MemoryOut,
    MemoryPatch,
    MemoryProvenanceOut,
    MemoryProvenanceSourceOut,
)

memories_router = APIRouter()
candidates_router = APIRouter()


# ---------- Memories ----------


@memories_router.get("", response_model=MemoryListOut)
async def list_memories(
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
    type: str | None = Query(default=None, pattern="^(FACT|PREFERENCE|EXPERIENCE|GOAL)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> MemoryListOut:
    twin = await twins.require_by_user(user.user_id)
    items = await memories.list_for_twin(twin, type=type, limit=limit)
    return MemoryListOut(items=[MemoryOut.model_validate(m) for m in items])


@memories_router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory(
    memory_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> MemoryOut:
    twin = await twins.require_by_user(user.user_id)
    memory = await memories.get(twin, memory_id)
    return MemoryOut.model_validate(memory)


@memories_router.patch("/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: uuid.UUID,
    payload: MemoryPatch,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> MemoryOut:
    """Edit an already-confirmed memory.

    Deliberately does NOT accept `user_confirmed`. Flipping that flag on an
    existing memory is not a supported operation; the only mechanism that
    produces a user-confirmed memory is confirming a candidate.
    """
    twin = await twins.require_by_user(user.user_id)
    memory = await memories.patch(twin, memory_id, payload)
    return MemoryOut.model_validate(memory)


@memories_router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> None:
    twin = await twins.require_by_user(user.user_id)
    await memories.delete(twin, memory_id)


@memories_router.get("/{memory_id}/provenance", response_model=MemoryProvenanceOut)
async def get_memory_provenance(
    memory_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> MemoryProvenanceOut:
    """Answer "why does my Twin know this?" (Sprint 4).

    Returns each source row for the memory, including a bounded
    (≤240 char) sanitized snippet of the originating message content.
    The full message remains reachable via `/v1/conversations/{id}/messages`.
    Owner-scoped: a wrong-owner memory id yields 404, not 403, to avoid
    leaking existence.
    """
    twin = await twins.require_by_user(user.user_id)
    memory, source_rows = await memories.get_provenance(twin, memory_id)
    return MemoryProvenanceOut(
        memory_id=memory.id,
        sources=[
            MemoryProvenanceSourceOut(
                source_id=src.id,
                source_type=src.source_type,
                source_message_id=src.source_message_id,
                source_conversation_id=src.source_conversation_id,
                created_at=src.created_at,
                source_snippet=snippet,
                source_snippet_truncated=truncated,
            )
            for src, snippet, truncated in source_rows
        ],
    )


# ---------- Memory candidates ----------


@candidates_router.get("", response_model=MemoryCandidateListOut)
async def list_candidates(
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
    status: str | None = Query(
        default="pending",
        pattern="^(pending|confirmed|rejected|expired|all)$",
    ),
) -> MemoryCandidateListOut:
    twin = await twins.require_by_user(user.user_id)
    status_filter = None if status == "all" else status
    items = await memories.list_candidates(twin, status=status_filter)
    return MemoryCandidateListOut(
        items=[MemoryCandidateOut.model_validate(c) for c in items]
    )


@candidates_router.post(
    "/{candidate_id}/confirm",
    response_model=MemoryCandidateConfirmOut,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_candidate(
    candidate_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> MemoryCandidateConfirmOut:
    twin = await twins.require_by_user(user.user_id)
    candidate, memory, embedding_attached, embedding_error = (
        await memories.confirm_candidate(twin, candidate_id)
    )
    return MemoryCandidateConfirmOut(
        candidate=MemoryCandidateOut.model_validate(candidate),
        memory=MemoryOut.model_validate(memory),
        embedding_attached=embedding_attached,
        embedding_error=embedding_error,
    )


@candidates_router.post("/{candidate_id}/reject", response_model=MemoryCandidateOut)
async def reject_candidate(
    candidate_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    memories: MemoryServiceDep,
) -> MemoryCandidateOut:
    twin = await twins.require_by_user(user.user_id)
    candidate = await memories.reject_candidate(twin, candidate_id)
    return MemoryCandidateOut.model_validate(candidate)
