"""Closed-loop load test with a realistic MirrorSelf request mix.

Each virtual user is its own account with its own Twin and conversation, and
repeatedly does what a person using the app does: open the app (Twin), look
at the conversation list, open a transcript, and now and then send a message
or open the self-portrait.

Needs an API running in dev mode with an HS256 secret (it mints its own
tokens) and, for the chat share of the mix, the mock model with
`MOCK_LLM_LATENCY_MS` set so a send holds its connection as long as a real
model call would. It creates accounts, so it refuses to run against anything
but a local process unless told otherwise. Never point it at production.

    python scripts/load_test.py --base-url http://127.0.0.1:8010 \\
        --hs-secret-env STAGING_JWT_HS_SECRET --stages 10,25,50,100 --duration 30

Reports per stage: requests/s, latency percentiles per endpoint, error rate
broken down by status, and timeouts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import httpx
import jwt

MIX: list[tuple[str, float]] = [
    ("twin", 0.40),
    ("conversations", 0.25),
    ("messages", 0.20),
    ("send", 0.10),
    ("portrait", 0.05),
]
THINK_SECONDS = (0.2, 1.0)


@dataclass
class User:
    token: str
    conversation_id: str


@dataclass
class Stage:
    users: int
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    statuses: Counter[str] = field(default_factory=Counter)
    timeouts: int = 0
    other_errors: int = 0
    started: float = 0.0
    ended: float = 0.0

    @property
    def total(self) -> int:
        return sum(self.statuses.values()) + self.timeouts + self.other_errors

    @property
    def failures(self) -> int:
        bad = sum(n for code, n in self.statuses.items() if not code.startswith(("2",)))
        return bad + self.timeouts + self.other_errors


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1))))
    return ordered[k]


def token(secret: str) -> str:
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "exp": int(time.time()) + 7200,
        },
        secret,
        algorithm="HS256",
    )


async def make_user(client: httpx.AsyncClient, secret: str, i: int) -> User:
    t = token(secret)
    headers = {"Authorization": f"Bearer {t}"}
    r = await client.post("/v1/twin", json={"name": f"Load {i}"}, headers=headers)
    r.raise_for_status()
    r = await client.post("/v1/conversations", json={"title": f"load {i}"}, headers=headers)
    r.raise_for_status()
    return User(token=t, conversation_id=r.json()["id"])


async def ensure_users(client: httpx.AsyncClient, secret: str, users: list[User], n: int) -> None:
    sem = asyncio.Semaphore(20)

    async def one(i: int) -> User:
        async with sem:
            return await make_user(client, secret, i)

    if len(users) < n:
        users.extend(await asyncio.gather(*[one(i) for i in range(len(users), n)]))


async def act(client: httpx.AsyncClient, user: User, stage: Stage, rng: random.Random) -> None:
    kind = rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX])[0]
    headers = {"Authorization": f"Bearer {user.token}"}
    conv = user.conversation_id
    started = time.perf_counter()
    try:
        if kind == "twin":
            r = await client.get("/v1/twin", headers=headers)
        elif kind == "conversations":
            r = await client.get("/v1/conversations", headers=headers)
        elif kind == "messages":
            r = await client.get(
                f"/v1/conversations/{conv}/messages", params={"limit": 50}, headers=headers
            )
        elif kind == "portrait":
            r = await client.get("/v1/twin/portrait", headers=headers)
        else:
            r = await client.post(
                f"/v1/conversations/{conv}/messages",
                json={"content": f"load message {rng.random():.6f}"},
                headers={**headers, "Idempotency-Key": f"ld-{uuid.uuid4().hex[:24]}"},
            )
    except httpx.TimeoutException:
        stage.timeouts += 1
        return
    except httpx.HTTPError:
        stage.other_errors += 1
        return
    elapsed = (time.perf_counter() - started) * 1000
    stage.statuses[str(r.status_code)] += 1
    if r.status_code < 400:
        stage.latencies[kind].append(elapsed)
        stage.latencies["all"].append(elapsed)


async def run_stage(
    client: httpx.AsyncClient, users: list[User], n: int, duration: float, seed: int
) -> Stage:
    stage = Stage(users=n)
    deadline = time.perf_counter() + duration

    async def vu(user: User, idx: int) -> None:
        rng = random.Random(seed * 1000 + idx)
        # Stagger the start so the stage ramps rather than stampedes.
        await asyncio.sleep(rng.uniform(0, 2))
        while time.perf_counter() < deadline:
            await act(client, user, stage, rng)
            await asyncio.sleep(rng.uniform(*THINK_SECONDS))

    stage.started = time.perf_counter()
    await asyncio.gather(*[vu(users[i], i) for i in range(n)])
    stage.ended = time.perf_counter()
    return stage


def summarise(stage: Stage) -> dict[str, object]:
    elapsed = stage.ended - stage.started
    per_kind = {}
    for kind, values in stage.latencies.items():
        per_kind[kind] = {
            "n": len(values),
            "p50": round(pct(values, 50)),
            "p95": round(pct(values, 95)),
            "p99": round(pct(values, 99)),
            "mean": round(statistics.fmean(values)) if values else None,
        }
    return {
        "users": stage.users,
        "seconds": round(elapsed, 1),
        "requests": stage.total,
        "rps": round(stage.total / elapsed, 1) if elapsed else 0,
        "error_rate_pct": round(100 * stage.failures / stage.total, 2) if stage.total else 0,
        "statuses": dict(stage.statuses),
        "timeouts": stage.timeouts,
        "other_errors": stage.other_errors,
        "latency_ms": per_kind,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--hs-secret-env", required=True)
    parser.add_argument("--stages", default="10,25,50,100")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", help="write results as JSON to this path")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    host = httpx.URL(args.base_url).host
    if host not in ("127.0.0.1", "localhost") and not args.allow_remote:
        print(f"refusing to load-test {host}; this creates accounts", file=sys.stderr)
        return 2
    secret = os.environ.get(args.hs_secret_env)
    if not secret:
        print(f"{args.hs_secret_env} is not set", file=sys.stderr)
        return 2

    stages = [int(s) for s in args.stages.split(",") if s.strip()]
    limits = httpx.Limits(max_connections=max(stages) + 20, max_keepalive_connections=max(stages))
    results = []
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout, limits=limits
    ) as client:
        users: list[User] = []
        for i, n in enumerate(stages):
            await ensure_users(client, secret, users, n)
            print(f"\n== {n} concurrent users, {args.duration:.0f}s ==", flush=True)
            summary = summarise(await run_stage(client, users, n, args.duration, seed=i))
            results.append(summary)
            lat = summary["latency_ms"]
            assert isinstance(lat, dict)
            overall = lat.get("all", {})
            print(
                f"  {summary['rps']} req/s  errors {summary['error_rate_pct']}%  "
                f"timeouts {summary['timeouts']}  statuses {summary['statuses']}"
            )
            print(
                f"  all: p50 {overall.get('p50')}ms  p95 {overall.get('p95')}ms  "
                f"p99 {overall.get('p99')}ms"
            )
            for kind in ("twin", "conversations", "messages", "send", "portrait"):
                if kind in lat:
                    k = lat[kind]
                    print(
                        f"  {kind:13} n={k['n']:5}  p50 {k['p50']:6}ms  "
                        f"p95 {k['p95']:6}ms  p99 {k['p99']:6}ms"
                    )
            # Let the pool and the database settle between stages.
            await asyncio.sleep(5)

    if args.report:
        write_report(args.report, results)
    return 0


def write_report(path: str, results: list[dict[str, object]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
