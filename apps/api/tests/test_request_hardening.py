"""Request ids, response hardening, body limits, rate limits, readiness.

These are the cross-cutting protections every request passes through. None
of them may read or log a request body, and none may get in the way of the
platform's health probes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.api.deps import sessionmaker_dep
from app.common.ratelimit import TokenBucketLimiter, retry_after_header
from app.config import get_settings
from app.db.session import engine_kwargs

# ---------------------------------------------------------------------
# Request ids
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id(client) -> None:
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert len(resp.headers["x-request-id"]) >= 8


@pytest.mark.asyncio
async def test_a_well_formed_inbound_request_id_is_kept(client) -> None:
    resp = await client.get("/v1/health", headers={"X-Request-ID": "client-trace-0001"})
    assert resp.headers["x-request-id"] == "client-trace-0001"


@pytest.mark.asyncio
async def test_a_hostile_inbound_request_id_is_replaced(client) -> None:
    # Anything that is not a short plain identifier could smuggle text into a
    # log line, so it is discarded rather than echoed.
    hostile = 'x" level=error event="forged'
    resp = await client.get("/v1/health", headers={"X-Request-ID": hostile})
    assert resp.headers["x-request-id"] != hostile
    assert '"' not in resp.headers["x-request-id"]


@pytest.mark.asyncio
async def test_error_envelope_request_id_matches_the_header(client) -> None:
    # No twin yet -> a 404 from the domain layer.
    resp = await client.get("/v1/twin")
    assert resp.status_code == 404
    assert resp.json()["error"]["request_id"] == resp.headers["x-request-id"]


# ---------------------------------------------------------------------
# Response hardening
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_responses_are_not_cacheable_and_not_sniffable(client) -> None:
    resp = await client.get("/v1/twin")
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in resp.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_hsts_is_sent_in_production_only(client, settings_env) -> None:
    resp = await client.get("/v1/health")
    assert "strict-transport-security" not in resp.headers

    settings_env(APP_ENV="prod")
    resp = await client.get("/v1/health")
    assert "max-age=31536000" in resp.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_docs_page_is_not_given_the_locked_down_csp(client) -> None:
    # Swagger UI loads its assets from a CDN; the JSON-only policy would
    # leave it a blank page.
    resp = await client.get("/v1/docs")
    assert resp.status_code == 200
    assert "content-security-policy" not in resp.headers


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_the_rejected_input(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={})).json()
    secret_text = "x" * 8001
    resp = await client.post(
        f"/v1/conversations/{conv['id']}/messages", json={"content": secret_text}
    )
    assert resp.status_code == 422
    assert secret_text not in resp.text
    errors = resp.json()["error"]["details"]["errors"]
    assert errors and errors[0]["loc"][-1] == "content"


# ---------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_allows_the_headers_the_client_sends(client) -> None:
    origin = get_settings().cors_origins_list[0]
    resp = await client.options(
        "/v1/conversations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    allowed = resp.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "idempotency-key"):
        assert header in allowed


@pytest.mark.asyncio
async def test_unknown_origin_gets_no_cors_grant(client) -> None:
    resp = await client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_browser_can_read_request_id_and_retry_after(client) -> None:
    origin = get_settings().cors_origins_list[0]
    resp = await client.get("/v1/health", headers={"Origin": origin})
    exposed = resp.headers["access-control-expose-headers"].lower()
    assert "x-request-id" in exposed
    assert "retry-after" in exposed


# ---------------------------------------------------------------------
# Body size limit
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_body_is_rejected_before_it_is_parsed(client) -> None:
    limit = get_settings().max_request_body_bytes
    resp = await client.post(
        "/v1/twin",
        content=b"{" + b" " * (limit + 10) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_oversized_body_rejection_still_carries_cors_headers(client) -> None:
    # Without CORS headers a browser reports this as a network failure and the
    # user never learns the real reason.
    origin = get_settings().cors_origins_list[0]
    limit = get_settings().max_request_body_bytes
    resp = await client.post(
        "/v1/twin",
        content=b"x" * (limit + 1),
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    assert resp.status_code == 413
    assert resp.headers["access-control-allow-origin"] == origin


# ---------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------


def test_bucket_allows_a_burst_then_refuses() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0])
    assert all(limiter.check("k", per_minute=5) == 0.0 for _ in range(5))
    wait = limiter.check("k", per_minute=5)
    assert wait == pytest.approx(12.0)  # one token every 60/5 seconds


def test_bucket_refills_over_time() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.check("k", per_minute=5)
    assert limiter.check("k", per_minute=5) > 0
    now[0] += 12.0
    assert limiter.check("k", per_minute=5) == 0.0


def test_buckets_are_independent_per_key() -> None:
    limiter = TokenBucketLimiter(clock=lambda: 0.0)
    for _ in range(3):
        limiter.check("a", per_minute=3)
    assert limiter.check("a", per_minute=3) > 0
    assert limiter.check("b", per_minute=3) == 0.0


def test_bucket_memory_is_bounded() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0], max_keys=100)
    for i in range(500):
        now[0] += 1.0
        limiter.check(f"key-{i}", per_minute=10)
    assert len(limiter) <= 121  # the idle window plus the insert that triggered pruning


def test_retry_after_is_whole_seconds_and_never_zero() -> None:
    assert retry_after_header(0.01) == "1"
    assert retry_after_header(2.2) == "3"


# ---------------------------------------------------------------------
# Rate limits end to end
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiting_is_off_in_the_test_environment_by_default(client) -> None:
    for _ in range(40):
        assert (await client.get("/v1/twin")).status_code == 404


@pytest.mark.asyncio
async def test_per_user_limit_returns_429_with_retry_after(client, settings_env) -> None:
    settings_env(RATE_LIMIT_ENABLED="true", RATE_LIMIT_DEFAULT_PER_MINUTE="3")
    statuses = [(await client.get("/v1/twin")).status_code for _ in range(4)]
    assert statuses == [404, 404, 404, 429]

    resp = await client.get("/v1/twin")
    assert resp.status_code == 429
    body = resp.json()["error"]
    assert body["code"] == "rate_limited"
    assert int(resp.headers["retry-after"]) >= 1
    assert body["details"]["scope"] == "default"


@pytest.mark.asyncio
async def test_one_users_limit_does_not_affect_another(
    client, settings_env, as_user, user_a, user_b
) -> None:
    settings_env(RATE_LIMIT_ENABLED="true", RATE_LIMIT_DEFAULT_PER_MINUTE="2")
    as_user(user_a)
    for _ in range(2):
        await client.get("/v1/twin")
    assert (await client.get("/v1/twin")).status_code == 429

    as_user(user_b)
    assert (await client.get("/v1/twin")).status_code == 404


@pytest.mark.asyncio
async def test_chat_has_its_own_tighter_limit(client, settings_env) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={})).json()
    settings_env(
        RATE_LIMIT_ENABLED="true",
        RATE_LIMIT_DEFAULT_PER_MINUTE="100",
        RATE_LIMIT_CHAT_PER_MINUTE="2",
    )
    url = f"/v1/conversations/{conv['id']}/messages"
    assert (await client.post(url, json={"content": "one"})).status_code == 201
    assert (await client.post(url, json={"content": "two"})).status_code == 201
    limited = await client.post(url, json={"content": "three"})
    assert limited.status_code == 429
    assert limited.json()["error"]["details"]["scope"] == "chat"
    # Reading the transcript is not a model call and is still allowed.
    msgs = await client.get(url)
    assert msgs.status_code == 200
    assert len(msgs.json()["items"]) == 4


@pytest.mark.asyncio
async def test_per_ip_limit_applies_before_authentication(client, settings_env) -> None:
    settings_env(RATE_LIMIT_ENABLED="true", RATE_LIMIT_IP_PER_MINUTE="3")
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    for _ in range(3):
        assert (await client.get("/v1/system/version", headers=headers)).status_code == 200
    limited = await client.get("/v1/system/version", headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    # A different address has its own budget.
    other = await client.get("/v1/system/version", headers={"CF-Connecting-IP": "203.0.113.10"})
    assert other.status_code == 200


@pytest.mark.asyncio
async def test_health_probes_are_never_rate_limited(client, settings_env) -> None:
    settings_env(RATE_LIMIT_ENABLED="true", RATE_LIMIT_IP_PER_MINUTE="2")
    headers = {"CF-Connecting-IP": "203.0.113.50"}
    for _ in range(20):
        assert (await client.get("/v1/health", headers=headers)).status_code == 200


# ---------------------------------------------------------------------
# Readiness and build info
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ready_reports_database_and_llm(client) -> None:
    resp = await client.get("/v1/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "llm": "configured"}
    assert isinstance(body["database_latency_ms"], int)


@pytest.mark.asyncio
async def test_ready_is_503_when_the_database_is_unreachable(app_client) -> None:
    app, client, _holder = app_client

    class _DeadSession:
        async def __aenter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        async def __aexit__(self, *exc: object) -> None:
            return None

    app.dependency_overrides[sessionmaker_dep] = lambda: lambda: _DeadSession()
    resp = await client.get("/v1/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] == "unavailable"
    # Liveness is unaffected: the process itself is fine.
    assert (await client.get("/v1/health")).status_code == 200


@pytest.mark.asyncio
async def test_version_reports_the_deployed_commit(client, settings_env) -> None:
    commit = uuid.uuid4().hex
    settings_env(RENDER_GIT_COMMIT=commit)
    assert (await client.get("/v1/system/version")).json()["commit"] == commit


# ---------------------------------------------------------------------
# Connection pool policy
# ---------------------------------------------------------------------


def test_postgres_engine_checks_connections_and_hides_parameters() -> None:
    settings = get_settings()
    kwargs = engine_kwargs("postgresql+asyncpg://u:p@db.example.com/app", settings)
    # A serverless database drops idle connections; pre-ping is what turns
    # that into a transparent reconnect instead of a failed request.
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == settings.db_pool_recycle_seconds
    assert kwargs["pool_size"] == settings.db_pool_size
    # Bound parameters are chat messages; they must never reach an error log.
    assert kwargs["hide_parameters"] is True
    connect_args = kwargs["connect_args"]
    assert isinstance(connect_args, dict)
    assert connect_args["command_timeout"] == settings.db_command_timeout_seconds
    assert connect_args["timeout"] == settings.db_connect_timeout_seconds


def test_sqlite_engine_gets_no_pool_arguments() -> None:
    kwargs = engine_kwargs("sqlite+aiosqlite:///:memory:", get_settings())
    assert "pool_size" not in kwargs
    assert kwargs["hide_parameters"] is True
