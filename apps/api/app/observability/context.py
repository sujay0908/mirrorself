"""Per-request context shared by logging and error responses."""

from __future__ import annotations

from contextvars import ContextVar

# The id of the request being handled, or None outside a request (startup,
# background work that outlives its request).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()
