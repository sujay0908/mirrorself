"""Twin-domain error types."""

from __future__ import annotations

from app.common.errors import ConflictError, NotFoundError


class TwinAlreadyExistsError(ConflictError):
    code = "twin_already_exists"


class TwinNotFoundError(NotFoundError):
    code = "twin_not_found"
