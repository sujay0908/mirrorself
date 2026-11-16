"""Error envelope + FastAPI exception handlers.

Every error response follows one shape (see docs/api/api-conventions.md).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.context import current_request_id
from app.observability.logging import get_logger

logger = get_logger(__name__)


class APIError(Exception):
    """Base class for domain errors surfaced as HTTP responses."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "api_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ForbiddenError(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ConflictError(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class RateLimitedError(APIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class ServiceUnavailableError(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def _envelope(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            # The same id is on the X-Request-ID response header and on every
            # log line for this request, so a user-reported id finds its logs.
            "request_id": request_id or current_request_id() or str(uuid.uuid4()),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError) -> JSONResponse:
        # The code, never the message: messages can quote caller input.
        logger.info("api.error", code=exc.code, status=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, details=exc.details),
            headers=exc.headers or None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _default_code_for_status(exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                "validation_error",
                "Request payload failed validation.",
                details={"errors": _safe_validation_errors(exc)},
            ),
        )

    @app.exception_handler(PoolTimeoutError)
    async def _pool_exhausted(request: Request, exc: PoolTimeoutError) -> JSONResponse:
        # Every pooled connection is busy. Shedding the request is correct;
        # the client should back off and retry.
        logger.warning("db.pool_exhausted")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(
                "server_busy",
                "The service is busy right now. Please try again in a moment.",
            ),
            headers={"Retry-After": "2"},
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # A uniqueness or foreign-key race the service layer did not anticipate.
        # Constraint names are schema detail, so only the class is logged.
        logger.warning("db.integrity_error", error_type=type(exc.orig).__name__)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope("conflict", "That change conflicts with existing data."),
        )

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # Connection loss, statement timeout, server restart. hide_parameters
        # on the engine keeps bound values out of the exception text.
        logger.error(
            "db.error",
            error_type=type(exc.orig).__name__ if exc.orig is not None else type(exc).__name__,
            connection_invalidated=exc.connection_invalidated,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(
                "database_unavailable",
                "The service could not reach its database. Please try again shortly.",
            ),
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(TimeoutError)
    async def _timeout(request: Request, exc: TimeoutError) -> JSONResponse:
        # A dependency (most often the database connect) did not answer in time.
        logger.error("api.dependency_timeout")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(
                "dependency_timeout",
                "A dependency did not respond in time. Please try again shortly.",
            ),
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("api.unhandled", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred."),
        )


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Field locations and reasons, without echoing the rejected input.

    Pydantic includes the offending value under `input`; for a chat message
    that is the user's own text, which has no business in an error payload
    that may end up in a client-side log.
    """
    cleaned: list[dict[str, Any]] = []
    for err in exc.errors():
        cleaned.append(
            {
                "type": err.get("type"),
                "loc": list(err.get("loc", ())),
                "msg": err.get("msg"),
            }
        )
    return cleaned


def _default_code_for_status(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
    }.get(status_code, "http_error")
