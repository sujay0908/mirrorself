"""Reflection-domain error types."""

from __future__ import annotations

from app.common.errors import APIError, ConflictError, NotFoundError


class ReflectionNotFoundError(NotFoundError):
    code = "reflection_not_found"


class ReflectionAlreadyResolvedError(ConflictError):
    code = "reflection_already_resolved"


class ReflectionApplyError(APIError):
    """Raised when applying a confirmed reflection fails.

    The candidate itself stays `status='confirmed'` with
    `apply_error` populated so the user can see what went wrong and a
    later retry endpoint (Sprint 8+) has somewhere to look.
    """

    status_code = 500
    code = "reflection_apply_error"


class InvalidReflectionPayloadError(APIError):
    """Raised when a draft fails payload validation. Never bubbles up
    to the chat path; the extractor returns an empty result on error.
    """

    status_code = 400
    code = "invalid_reflection_payload"
