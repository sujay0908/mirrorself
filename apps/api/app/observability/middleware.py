"""Request-scoped middleware: request ids, access logs, response hardening,
body-size and per-IP limits.

Written as plain ASGI rather than `BaseHTTPMiddleware` so background tasks and
context variables behave exactly as they do without it.

Nothing here reads or logs a request or response body.
"""

from __future__ import annotations

import json
import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.errors import APIError
from app.common.ratelimit import get_rate_limiter, retry_after_header
from app.config import Settings, get_settings
from app.observability.context import request_id_var
from app.observability.logging import get_logger

logger = get_logger(__name__)

# An inbound id is only reused when it is short and boring; anything else is
# replaced, so a caller cannot inject arbitrary text into log lines.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")

# Liveness and readiness probes arrive every few seconds from the platform.
# They are never rate limited and are logged at debug to keep them out of the
# way of real traffic.
_PROBE_PATHS = frozenset({"/v1/health", "/v1/ready"})

# Swagger UI and ReDoc load their assets from a CDN, so the locked-down
# content security policy used for JSON responses cannot apply to them.
_DOCS_PATHS = frozenset({"/v1/docs", "/v1/redoc"})


class PayloadTooLargeError(APIError):
    status_code = 413
    code = "payload_too_large"


def client_ip(scope: Scope) -> str:
    """Best available client address.

    The service is only reachable through the platform's edge, which sets
    CF-Connecting-IP itself and overwrites any value a caller supplies.
    X-Forwarded-For is a fallback for other hosts and local runs; its first
    entry is caller-controlled there, which is acceptable for a limiter whose
    job is to slow down unauthenticated floods rather than to authorise.
    """
    headers = Headers(scope=scope)
    for name in ("cf-connecting-ip", "true-client-ip"):
        value = headers.get(name)
        if value:
            return value.strip()
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = Headers(scope=scope)
        inbound = headers.get("x-request-id", "")
        request_id = inbound if _REQUEST_ID_RE.match(inbound) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        path: str = scope.get("path", "")
        method: str = scope.get("method", "")
        started = time.perf_counter()
        status_holder = {"status": 500}
        hardened = settings.app_env in ("staging", "prod")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                out.setdefault("X-Content-Type-Options", "nosniff")
                out.setdefault("X-Frame-Options", "DENY")
                out.setdefault("Referrer-Policy", "no-referrer")
                # Every response body here is one person's private data.
                out.setdefault("Cache-Control", "no-store")
                if path not in _DOCS_PATHS:
                    out.setdefault(
                        "Content-Security-Policy",
                        "default-src 'none'; frame-ancestors 'none'",
                    )
                if hardened:
                    out.setdefault(
                        "Strict-Transport-Security",
                        "max-age=31536000; includeSubDomains",
                    )
            await send(message)

        try:
            rejection = self._reject_early(scope, headers, settings, path, method)
            if rejection is not None:
                await self._send_error(send_wrapper, *rejection, request_id=request_id)
                return
            limited_receive = _limit_body(receive, settings.max_request_body_bytes)
            await self.app(scope, limited_receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log = logger.debug if path in _PROBE_PATHS else logger.info
            log(
                "http.request",
                method=method,
                path=path,
                status=status_holder["status"],
                duration_ms=duration_ms,
            )
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(token)

    def _reject_early(
        self,
        scope: Scope,
        headers: Headers,
        settings: Settings,
        path: str,
        method: str,
    ) -> tuple[int, str, str, dict[str, str]] | None:
        """Cheap checks that run before routing, auth or any database work."""
        declared = headers.get("content-length")
        if (
            declared is not None
            and declared.isdigit()
            and int(declared) > settings.max_request_body_bytes
        ):
            return (
                413,
                "payload_too_large",
                f"Request body is larger than {settings.max_request_body_bytes} bytes.",
                {},
            )

        if not settings.rate_limit_active or method == "OPTIONS" or path in _PROBE_PATHS:
            return None
        wait = get_rate_limiter().check(
            f"ip:{client_ip(scope)}", per_minute=settings.rate_limit_ip_per_minute
        )
        if wait > 0:
            return (
                429,
                "rate_limited",
                "Too many requests. Slow down and try again shortly.",
                {"Retry-After": retry_after_header(wait)},
            )
        return None

    @staticmethod
    async def _send_error(
        send: Send,
        status: int,
        code: str,
        message: str,
        extra_headers: dict[str, str],
        *,
        request_id: str,
    ) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": {},
                    "request_id": request_id,
                }
            }
        ).encode()
        raw_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        raw_headers.extend((k.lower().encode(), v.encode()) for k, v in extra_headers.items())
        await send({"type": "http.response.start", "status": status, "headers": raw_headers})
        await send({"type": "http.response.body", "body": body})


def _limit_body(receive: Receive, limit: int) -> Receive:
    """Enforce the size limit on bodies sent without a Content-Length."""
    seen = 0

    async def limited() -> Message:
        nonlocal seen
        message = await receive()
        if message["type"] == "http.request":
            seen += len(message.get("body", b""))
            if seen > limit:
                raise PayloadTooLargeError(f"Request body is larger than {limit} bytes.")
        return message

    return limited
