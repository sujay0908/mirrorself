"""Memory-domain error types."""

from __future__ import annotations

from app.common.errors import ConflictError, NotFoundError


class MemoryNotFoundError(NotFoundError):
    code = "memory_not_found"


class MemoryCandidateNotFoundError(NotFoundError):
    code = "memory_candidate_not_found"


class MemoryCandidateAlreadyResolvedError(ConflictError):
    code = "memory_candidate_already_resolved"
