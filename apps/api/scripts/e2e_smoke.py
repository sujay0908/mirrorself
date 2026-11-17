"""End-to-end smoke test against a running API.

Three modes, chosen by what credentials are available:

  public    No credentials. Health, readiness, build info, response
            hardening, CORS, and that every protected route refuses
            unauthenticated and malformed requests. Safe against production.

  readonly  One real bearer token (`--token-env NAME`). Everything in
            `public`, plus authenticated reads of that user's own data.
            Writes nothing. Safe against production.

  full      An HS256 dev secret (`--hs-secret-env NAME`). Mints tokens for
            two throwaway users and exercises every write path, ownership
            isolation between the two, idempotency, and failure handling.
            Creates data, so run it against staging or a local database,
            never production. Requires the API to run with APP_ENV=dev and
            the same secret.

Credentials are read from environment variables named on the command line,
never passed as arguments, so they do not land in shell history or in a
process listing. The script prints status codes and timings only: no token,
no response body content beyond error codes.

Exit status is 0 when nothing failed, 1 otherwise.

    python scripts/e2e_smoke.py --base-url https://api.example.com
    python scripts/e2e_smoke.py --base-url http://127.0.0.1:8010 \\
        --hs-secret-env STAGING_JWT_HS_SECRET --mock-llm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    name: str
    outcome: str
    evidence: str
    ms: int = 0


@dataclass
class Report:
    base_url: str
    mode: str
    results: list[Result] = field(default_factory=list)

    def add(self, name: str, ok: bool | None, evidence: str, ms: int = 0) -> bool:
        outcome = SKIP if ok is None else (PASS if ok else FAIL)
        self.results.append(Result(name, outcome, evidence, ms))
        print(f"  {outcome:4}  {name}  [{evidence}]" + (f"  {ms}ms" if ms else ""))
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.outcome == FAIL)

    def summary(self) -> str:
        counts = {o: sum(1 for r in self.results if r.outcome == o) for o in (PASS, FAIL, SKIP)}
        return f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped"


def mint_token(secret: str, *, sub: str | None = None, expires_in: int = 600) -> str:
    import jwt

    return jwt.encode(
        {
            "sub": sub or str(uuid.uuid4()),
            "aud": "authenticated",
            "email": "smoke@example.test",
            "exp": int(time.time()) + expires_in,
        },
        secret,
        algorithm="HS256",
    )


class Api:
    """Thin wrapper that times every call and never raises on HTTP status."""

    def __init__(self, client: httpx.AsyncClient, token: str | None = None) -> None:
        self._client = client
        self._token = token

    async def call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> tuple[httpx.Response, int]:
        merged: dict[str, str] = {}
        if auth and self._token:
            merged["Authorization"] = f"Bearer {self._token}"
        merged.update(headers or {})
        started = time.perf_counter()
        resp = await self._client.request(
            method, path, json=json_body, headers=merged, content=content, params=params
        )
        return resp, int((time.perf_counter() - started) * 1000)


def code_of(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", {}).get("code"))
    except Exception:
        return "?"


def ev(resp: httpx.Response) -> str:
    if resp.status_code >= 400:
        return f"HTTP {resp.status_code} {code_of(resp)}"
    return f"HTTP {resp.status_code}"


# ---------------------------------------------------------------------
# public
# ---------------------------------------------------------------------


async def run_public(report: Report, api: Api, origins: list[str]) -> None:
    print("\n== platform ==")
    resp, ms = await api.call("GET", "/v1/health", auth=False)
    report.add(
        "liveness", resp.status_code == 200 and resp.json() == {"status": "ok"}, ev(resp), ms
    )

    resp, ms = await api.call("GET", "/v1/ready", auth=False)
    body = (
        resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    )
    checks = body.get("checks", {})
    report.add(
        "readiness: database reachable",
        resp.status_code == 200 and checks.get("database") == "ok",
        f"{ev(resp)} db={checks.get('database')} llm={checks.get('llm')} "
        f"db_ms={body.get('database_latency_ms')}",
        ms,
    )

    resp, ms = await api.call("GET", "/v1/system/version", auth=False)
    version = resp.json() if resp.status_code == 200 else {}
    report.add(
        "build info reports the deployed commit",
        resp.status_code == 200 and "commit" in version,
        f"{ev(resp)} env={version.get('env')} commit={str(version.get('commit'))[:12]} "
        f"model={version.get('llm_model')}",
        ms,
    )

    print("\n== response hardening ==")
    resp, _ = await api.call("GET", "/v1/twin", auth=False)
    h = resp.headers
    report.add("request id on every response", len(h.get("x-request-id", "")) >= 8, "X-Request-ID")
    report.add(
        "error envelope carries the same request id",
        resp.status_code == 401
        and resp.json().get("error", {}).get("request_id") == h.get("x-request-id"),
        ev(resp),
    )
    report.add("responses are not cacheable", h.get("cache-control") == "no-store", "Cache-Control")
    report.add("nosniff", h.get("x-content-type-options") == "nosniff", "X-Content-Type-Options")
    report.add("frame embedding denied", h.get("x-frame-options") == "DENY", "X-Frame-Options")
    if report.base_url.startswith("https://"):
        report.add(
            "HSTS",
            "max-age=" in h.get("strict-transport-security", ""),
            "Strict-Transport-Security",
        )

    print("\n== authentication is required ==")
    protected = [
        ("GET", "/v1/twin"),
        ("GET", "/v1/twin/portrait"),
        ("GET", "/v1/twin/evolution"),
        ("GET", "/v1/conversations"),
        ("POST", "/v1/conversations"),
        ("GET", f"/v1/conversations/{uuid.uuid4()}/messages"),
        ("POST", f"/v1/conversations/{uuid.uuid4()}/messages"),
        ("GET", "/v1/memories"),
        ("GET", "/v1/memory-candidates"),
        ("GET", "/v1/goals"),
        ("POST", "/v1/goals"),
        ("GET", "/v1/reflections"),
        ("POST", "/v1/reflections/run"),
    ]
    refused = []
    for method, path in protected:
        resp, _ = await api.call(
            method, path, json_body={} if method == "POST" else None, auth=False
        )
        refused.append(resp.status_code == 401)
    report.add(
        f"all {len(protected)} protected routes refuse a request with no token",
        all(refused),
        f"{sum(refused)}/{len(protected)} returned 401",
    )
    for label, value in (
        ("garbage token", "Bearer not-a-jwt"),
        ("wrong scheme", "Basic dXNlcjpwYXNz"),
        ("bearer with no token", "Bearer"),
        (
            "unsigned token (alg=none)",
            "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0."
            "eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAiLCJhdWQiOiJhdXRoZW50aWNhdGVkIn0.",
        ),
    ):
        resp, _ = await api.call("GET", "/v1/twin", headers={"Authorization": value}, auth=False)
        report.add(f"rejected: {label}", resp.status_code == 401, ev(resp))

    print("\n== limits and routing ==")
    resp, _ = await api.call(
        "POST",
        "/v1/twin",
        content=b"x" * 200_000,
        headers={"Content-Type": "application/json"},
        auth=False,
    )
    report.add("oversized body refused before parsing", resp.status_code == 413, ev(resp))
    resp, _ = await api.call("GET", "/v1/does-not-exist", auth=False)
    report.add(
        "unknown route is a 404 in the standard envelope",
        resp.status_code == 404 and "error" in resp.json(),
        ev(resp),
    )

    if origins:
        print("\n== CORS ==")
    for origin in origins:
        resp, _ = await api.call(
            "OPTIONS",
            "/v1/conversations",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
            },
            auth=False,
        )
        report.add(
            f"preflight allowed for {origin}",
            resp.status_code == 200 and resp.headers.get("access-control-allow-origin") == origin,
            f"HTTP {resp.status_code} allow-origin={resp.headers.get('access-control-allow-origin')}",
        )
    resp, _ = await api.call(
        "OPTIONS",
        "/v1/conversations",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        auth=False,
    )
    report.add(
        "preflight refused for an unknown origin",
        "access-control-allow-origin" not in resp.headers,
        f"HTTP {resp.status_code}",
    )


# ---------------------------------------------------------------------
# readonly
# ---------------------------------------------------------------------


async def run_readonly(report: Report, api: Api) -> None:
    print("\n== authenticated reads (no writes) ==")
    resp, ms = await api.call("GET", "/v1/twin")
    has_twin = resp.status_code == 200
    report.add(
        "token accepted; twin lookup answers",
        resp.status_code in (200, 404) and (has_twin or code_of(resp) == "twin_not_found"),
        ev(resp),
        ms,
    )
    if not has_twin:
        report.add("remaining reads", None, "this account has no twin yet")
        return
    for name, path in (
        ("self-portrait", "/v1/twin/portrait"),
        ("evolution", "/v1/twin/evolution"),
        ("conversations", "/v1/conversations"),
        ("memories", "/v1/memories"),
        ("memory candidates", "/v1/memory-candidates"),
        ("goals", "/v1/goals"),
        ("reflections", "/v1/reflections"),
    ):
        resp, ms = await api.call("GET", path)
        report.add(f"read {name}", resp.status_code == 200, ev(resp), ms)

    resp, _ = await api.call("GET", "/v1/conversations")
    items = resp.json().get("items", []) if resp.status_code == 200 else []
    if items:
        conv = items[0]["id"]
        resp, ms = await api.call("GET", f"/v1/conversations/{conv}/messages", params={"limit": 5})
        report.add("read one transcript page", resp.status_code == 200, ev(resp), ms)
    resp, _ = await api.call("GET", f"/v1/conversations/{uuid.uuid4()}")
    report.add("someone else's conversation id is a 404", resp.status_code == 404, ev(resp))


# ---------------------------------------------------------------------
# full
# ---------------------------------------------------------------------


async def run_full(
    report: Report,
    client: httpx.AsyncClient,
    secret: str,
    *,
    mock_llm: bool,
) -> None:
    a = Api(client, mint_token(secret))
    b = Api(client, mint_token(secret))

    print("\n== token edge cases ==")
    resp, _ = await Api(client, mint_token(secret, expires_in=-60)).call("GET", "/v1/twin")
    report.add("expired token rejected", resp.status_code == 401, ev(resp))
    resp, _ = await Api(client, mint_token("a-different-secret-entirely")).call("GET", "/v1/twin")
    report.add("token signed with another secret rejected", resp.status_code == 401, ev(resp))

    print("\n== twin ==")
    resp, _ = await a.call("GET", "/v1/twin")
    report.add(
        "new user has no twin",
        resp.status_code == 404 and code_of(resp) == "twin_not_found",
        ev(resp),
    )
    resp, ms = await a.call(
        "POST", "/v1/twin", json_body={"name": "Smoke Twin", "communication_style": "warm"}
    )
    twin = resp.json() if resp.status_code == 201 else {}
    report.add("create twin", resp.status_code == 201, ev(resp), ms)
    resp, _ = await a.call("POST", "/v1/twin", json_body={"name": "Second"})
    report.add("second twin is a conflict", resp.status_code == 409, ev(resp))
    creates = await asyncio.gather(
        *[b.call("POST", "/v1/twin", json_body={"name": f"Race {i}"}) for i in range(5)]
    )
    statuses = sorted(r.status_code for r, _ in creates)
    report.add(
        "five simultaneous creates yield exactly one twin",
        statuses.count(201) == 1 and all(s in (201, 409) for s in statuses),
        f"statuses={statuses}",
    )
    resp, ms = await a.call("GET", "/v1/twin")
    report.add(
        "retrieve twin",
        resp.status_code == 200 and resp.json().get("id") == twin.get("id"),
        ev(resp),
        ms,
    )
    resp, _ = await a.call(
        "PATCH",
        "/v1/twin",
        json_body={
            "communication_style_notes": "short sentences",
            "basic_profile": {"city": "Pune"},
        },
    )
    report.add(
        "edit profile",
        resp.status_code == 200 and resp.json()["profile"]["basic_profile"] == {"city": "Pune"},
        ev(resp),
    )
    resp, _ = await a.call("GET", "/v1/twin")
    report.add(
        "profile edit persisted",
        resp.status_code == 200
        and resp.json()["profile"]["communication_style_notes"] == "short sentences",
        ev(resp),
    )
    resp, _ = await a.call("PATCH", "/v1/twin", json_body={"basic_profile": {"x": "y" * 20_000}})
    report.add("oversized profile rejected", resp.status_code == 422, ev(resp))

    print("\n== conversations ==")
    resp, ms = await a.call("POST", "/v1/conversations", json_body={})
    conv = resp.json().get("id") if resp.status_code == 201 else None
    report.add("create conversation", resp.status_code == 201, ev(resp), ms)
    resp, ms = await a.call("GET", "/v1/conversations")
    report.add(
        "conversation is listed",
        resp.status_code == 200 and any(c["id"] == conv for c in resp.json()["items"]),
        ev(resp),
        ms,
    )
    resp, _ = await a.call("GET", f"/v1/conversations/{conv}")
    report.add("retrieve conversation", resp.status_code == 200, ev(resp))
    messages_url = f"/v1/conversations/{conv}/messages"

    print("\n== chat ==")
    key = f"smoke-{uuid.uuid4().hex[:20]}"
    resp, ms = await a.call(
        "POST",
        messages_url,
        json_body={"content": "Hello from the smoke test"},
        headers={"Idempotency-Key": key},
    )
    ai_available = resp.status_code == 201
    if resp.status_code == 503 and code_of(resp) == "llm_provider_not_configured":
        report.add("send message", None, "no LLM provider configured: controlled 503", ms)
    else:
        report.add("send message", ai_available, ev(resp), ms)

    if ai_available:
        first = resp.json()
        report.add(
            "reply is attributed to a provider and model",
            bool(first["twin_message"]["llm_provider"]) and bool(first["twin_message"]["content"]),
            f"provider={first['twin_message']['llm_provider']}",
        )
        resp, ms = await a.call(
            "POST",
            messages_url,
            json_body={"content": "Hello from the smoke test"},
            headers={"Idempotency-Key": key},
        )
        report.add(
            "retry with the same key replays instead of duplicating",
            resp.status_code == 200
            and resp.headers.get("idempotent-replayed") == "true"
            and resp.json()["twin_message"]["id"] == first["twin_message"]["id"],
            f"{ev(resp)} replayed={resp.headers.get('idempotent-replayed')}",
            ms,
        )
        resp, _ = await a.call("GET", messages_url)
        items = resp.json()["items"]
        report.add(
            "exactly one exchange is stored, in order",
            [m["role"] for m in items] == ["user", "twin"],
            f"roles={[m['role'] for m in items]}",
        )
        resp, _ = await a.call("GET", f"/v1/conversations/{conv}")
        report.add(
            "conversation was titled from its first message",
            resp.json().get("title") == "Hello from the smoke test",
            f"title_set={bool(resp.json().get('title'))}",
        )

    resp, _ = await a.call("POST", messages_url, json_body={"content": "   "})
    report.add("blank message rejected", resp.status_code == 422, ev(resp))
    resp, _ = await a.call("POST", messages_url, json_body={"content": "x" * 8001})
    report.add("over-long message rejected", resp.status_code == 422, ev(resp))
    resp, _ = await a.call(
        "POST", messages_url, json_body={"content": "hi"}, headers={"Idempotency-Key": "bad key!"}
    )
    report.add("malformed idempotency key rejected", resp.status_code == 422, ev(resp))

    if mock_llm and ai_available:
        print("\n== failure handling (mock provider directives) ==")
        before = len((await a.call("GET", messages_url))[0].json()["items"])
        fail_key = f"fail-{uuid.uuid4().hex[:20]}"
        resp, _ = await a.call(
            "POST",
            messages_url,
            json_body={"content": "please [[mock:fail]]"},
            headers={"Idempotency-Key": fail_key},
        )
        after = len((await a.call("GET", messages_url))[0].json()["items"])
        report.add(
            "failed model call stores nothing (no orphan message)",
            resp.status_code == 500 and after == before,
            f"{ev(resp)} messages {before}->{after}",
        )
        resp, _ = await a.call(
            "POST",
            messages_url,
            json_body={"content": "second attempt"},
            headers={"Idempotency-Key": fail_key},
        )
        report.add(
            "the same key works once the model is healthy", resp.status_code == 201, ev(resp)
        )

        race_key = f"race-{uuid.uuid4().hex[:20]}"
        before = len((await a.call("GET", messages_url))[0].json()["items"])
        results = await asyncio.gather(
            *[
                a.call(
                    "POST",
                    messages_url,
                    json_body={"content": "double tap [[mock:sleep=1200]]"},
                    headers={"Idempotency-Key": race_key},
                )
                for _ in range(2)
            ]
        )
        after = len((await a.call("GET", messages_url))[0].json()["items"])
        statuses = sorted(r.status_code for r, _ in results)
        report.add(
            "two simultaneous sends with one key create one exchange",
            after - before == 2 and statuses[0] in (200, 201) and 201 in statuses,
            f"statuses={statuses} messages +{after - before}",
        )

        slow_key = f"slow-{uuid.uuid4().hex[:20]}"
        before = after

        async def slow_send() -> tuple[httpx.Response, int]:
            return await a.call(
                "POST",
                messages_url,
                json_body={"content": "slow one [[mock:sleep=6000]]"},
                headers={"Idempotency-Key": slow_key},
            )

        # A model call that outlasts the client's patience, and a retry sent
        # while it is still running. Which of the two reaches the database
        # first depends on connection timing, so the check is on the pair:
        # one is served, the other is told to wait, and neither duplicates.
        original = asyncio.create_task(slow_send())
        await asyncio.sleep(0.8)
        (resp_a, _), (resp_b, _) = await asyncio.gather(original, slow_send())
        pair = sorted((resp_a, resp_b), key=lambda r: r.status_code)
        report.add(
            "a retry while the first is still running gets 409, not a second model call",
            [r.status_code for r in pair] == [201, 409]
            and code_of(pair[1]) == "message_in_progress",
            f"statuses={[r.status_code for r in pair]} "
            f"retry-after={pair[1].headers.get('retry-after')}",
        )
        resp, _ = await slow_send()
        after = len((await a.call("GET", messages_url))[0].json()["items"])
        report.add(
            "once it completes, a later retry replays it",
            resp.status_code == 200
            and resp.headers.get("idempotent-replayed") == "true"
            and after - before == 2,
            f"{ev(resp)} messages +{after - before}",
        )

        resp, _ = await a.call("GET", messages_url, params={"limit": 2})
        page = resp.json()["items"]
        resp, _ = await a.call("GET", messages_url, params={"limit": 2, "before": page[0]["id"]})
        older = resp.json()["items"]
        report.add(
            "transcript pages backwards without overlap",
            len(page) == 2
            and len(older) == 2
            and not {m["id"] for m in page} & {m["id"] for m in older},
            f"page={len(page)} older={len(older)}",
        )

    print("\n== goals ==")
    resp, ms = await a.call(
        "POST", "/v1/goals", json_body={"title": "Ship the smoke test", "priority": 3}
    )
    goal = resp.json().get("id") if resp.status_code == 201 else None
    report.add("create goal", resp.status_code == 201, ev(resp), ms)
    resp, _ = await a.call("GET", "/v1/goals")
    report.add(
        "goal is listed",
        resp.status_code == 200 and any(g["id"] == goal for g in resp.json()["items"]),
        ev(resp),
    )
    resp, _ = await a.call("PATCH", f"/v1/goals/{goal}", json_body={"status": "achieved"})
    report.add(
        "mark goal achieved",
        resp.status_code == 200 and resp.json().get("status") == "achieved",
        ev(resp),
    )
    resp, _ = await a.call("PATCH", f"/v1/goals/{goal}", json_body={"status": "active"})
    report.add("a finished goal cannot be reopened", resp.status_code in (409, 422), ev(resp))
    resp, _ = await a.call("GET", f"/v1/goals/{goal}/events")
    report.add(
        "goal keeps an audit trail",
        resp.status_code == 200 and len(resp.json()["items"]) >= 2,
        f"{ev(resp)} events={len(resp.json().get('items', []))}",
    )
    resp, _ = await a.call("POST", "/v1/goals", json_body={"title": ""})
    report.add("goal without a title rejected", resp.status_code == 422, ev(resp))

    print("\n== memory, reflection, evolution, portrait ==")
    for name, path in (
        ("memories", "/v1/memories"),
        ("memory candidates", "/v1/memory-candidates"),
        ("reflections", "/v1/reflections"),
        ("evolution", "/v1/twin/evolution"),
        ("self-portrait", "/v1/twin/portrait"),
    ):
        resp, ms = await a.call("GET", path)
        report.add(f"read {name}", resp.status_code == 200, ev(resp), ms)
    resp, _ = await a.call("GET", f"/v1/memories/{uuid.uuid4()}")
    report.add("unknown memory is a 404", resp.status_code == 404, ev(resp))
    resp, _ = await a.call("POST", f"/v1/memory-candidates/{uuid.uuid4()}/confirm")
    report.add("unknown candidate is a 404", resp.status_code == 404, ev(resp))

    print("\n== ownership isolation (user B against user A's data) ==")
    for name, method, path, body in (
        ("read A's conversation", "GET", f"/v1/conversations/{conv}", None),
        ("read A's transcript", "GET", messages_url, None),
        ("post into A's conversation", "POST", messages_url, {"content": "intrusion"}),
        ("read A's goal", "GET", f"/v1/goals/{goal}", None),
        ("edit A's goal", "PATCH", f"/v1/goals/{goal}", {"title": "hijacked"}),
        ("read A's goal history", "GET", f"/v1/goals/{goal}/events", None),
    ):
        resp, _ = await b.call(method, path, json_body=body)
        report.add(f"B cannot {name}", resp.status_code == 404, ev(resp))
    resp, _ = await b.call("GET", "/v1/conversations")
    report.add(
        "B's conversation list does not contain A's",
        resp.status_code == 200 and all(c["id"] != conv for c in resp.json()["items"]),
        ev(resp),
    )
    resp, _ = await b.call("GET", "/v1/goals")
    report.add(
        "B's goal list does not contain A's",
        resp.status_code == 200 and all(g["id"] != goal for g in resp.json()["items"]),
        ev(resp),
    )
    resp, _ = await b.call("GET", "/v1/twin")
    report.add(
        "B sees only B's twin",
        resp.status_code == 200 and resp.json().get("id") != twin.get("id"),
        ev(resp),
    )
    resp, _ = await a.call("GET", f"/v1/goals/{goal}")
    report.add(
        "A's goal is unchanged after B's attempts",
        resp.status_code == 200 and resp.json().get("title") == "Ship the smoke test",
        ev(resp),
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token-env", help="env var holding one real bearer token (readonly mode)")
    parser.add_argument("--hs-secret-env", help="env var holding the dev HS256 secret (full mode)")
    parser.add_argument("--mock-llm", action="store_true", help="API runs the mock provider")
    parser.add_argument("--origin", action="append", default=[], help="origin to preflight")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--report", help="write a JSON report to this path")
    parser.add_argument(
        "--allow-remote-writes",
        action="store_true",
        help="permit full mode against a non-local host (staging only, never production)",
    )
    args = parser.parse_args()

    secret = os.environ.get(args.hs_secret_env) if args.hs_secret_env else None
    token = os.environ.get(args.token_env) if args.token_env else None
    if args.hs_secret_env and not secret:
        print(f"{args.hs_secret_env} is not set", file=sys.stderr)
        return 2
    if args.token_env and not token:
        print(f"{args.token_env} is not set", file=sys.stderr)
        return 2
    mode = "full" if secret else ("readonly" if token else "public")
    host = httpx.URL(args.base_url).host
    if mode == "full" and host not in ("127.0.0.1", "localhost") and not args.allow_remote_writes:
        # The write suite creates twins, conversations and goals. Pointing it
        # at anything but a local process has to be a deliberate choice.
        print(
            f"refusing to run the write suite against {host}; "
            "pass --allow-remote-writes if this is a staging service",
            file=sys.stderr,
        )
        return 2

    report = Report(base_url=args.base_url, mode=mode)
    print(f"Smoke test: {args.base_url}  mode={mode}")
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout) as client:
        await run_public(report, Api(client), args.origin)
        if mode == "readonly":
            await run_readonly(report, Api(client, token))
        elif mode == "full":
            assert secret is not None
            await run_full(report, client, secret, mock_llm=args.mock_llm)

    print(f"\n{report.summary()}")
    if args.report:
        write_report(report, args.report)
    return 1 if report.failed else 0


def write_report(report: Report, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "base_url": report.base_url,
                "mode": report.mode,
                "summary": report.summary(),
                "results": [asdict(r) for r in report.results],
            },
            fh,
            indent=2,
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
