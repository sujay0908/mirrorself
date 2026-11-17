# Performance and load testing

## Method

`apps/api/scripts/load_test.py` runs a closed-loop test: each virtual user is
its own account with its own Twin and conversation and loops through a
realistic mix with 0.2–1.0 s of think time between actions:

| Action | Share |
|---|---|
| Open the app (`GET /v1/twin`) | 40% |
| Conversation list | 25% |
| Open a transcript (50 messages) | 20% |
| Send a message (idempotency key, model call) | 10% |
| Self-portrait | 5% |

Stages: 10, 25, 50, 100 and 250 concurrent users, 30 s each.

**Environment.** Production was not load-tested. The tested stack was the
current API code running locally against the Neon **staging** branch (same
region, plan and compute limits as production, its own role and database),
with the mock model delaying each reply by 1.5 s so a send holds its database
connection the way a real model call does. Rate limiting was off so the test
measures capacity rather than the limiter.

**Caveat that dominates the absolute numbers.** The test machine is about
270 ms from the database per round trip (measured). A read endpoint makes
4–5 round trips (connection check, begin, query, end), so ~1.3 s of a 1.3 s
`GET /v1/twin` here is network. In production the API (Render, Oregon) is
about one cross-country hop from the database (Neon, Ohio). The absolute
latencies below are therefore much worse than production's; what transfers is
the **shape**: where the system saturates, and how it fails.

## Results

### Connection pool 15 (the previous default)

| Users | Req/s | Errors | p50 | p95 | Send p50 |
|---|---|---|---|---|---|
| 10 | 2.3 | 0% | 1.8 s | 10.5 s | 10.4 s |
| 25 | 4.8 | 0% | 3.6 s | 9.3 s | 11.4 s |
| 50 | 4.2 | **8.9%** (503) | 8.1 s | 15.4 s | 14.9 s |
| 100 | 6.9 | **40.4%** (503) | 10.9 s | 16.9 s | 16.7 s |
| 250 | 13.2 | **65.1%** (503) | 11.4 s | 17.4 s | 16.8 s |

### Connection pool 50 (new default: 20 + 30 overflow)

| Users | Req/s | Errors | p50 | p95 | Send p50 |
|---|---|---|---|---|---|
| 10 | 2.5 | 0% | 1.8 s | 10.9 s | 10.8 s |
| 50 | 11.5 | **0%** | 1.9 s | 10.6 s | 10.9 s |
| 100 | 12.7 | 0.56% | 4.9 s | 12.6 s | 12.5 s |
| 250 | 16.4 | 17.2% (503) | 11.1 s | 17.1 s | 17.0 s |

(p95 "all" includes sends, which carry the model's 1.5 s plus ~20 database
round trips.)

### What held under every stage

- **Zero timeouts and zero 500s.** Every error was a fast `503 server_busy`
  with `Retry-After`, raised when no connection freed up within 10 s. The
  service sheds load instead of hanging or crashing.
- Memory: the API process peaked at ~143 MB at 250 users (Render free
  instances have 512 MB).
- No duplicated messages: every send carried an idempotency key.

### Production measurements (read-only, 2026-11-17)

Production was not load-tested with accounts or writes. Two read-only
measurements were taken after the deploy:

| Measurement | Result |
|---|---|
| `/v1/ready` database check from Render (Oregon) to Neon (Ohio), warm | **~348 ms** (first call 1.2 s while the compute woke). That is ~4–5 cross-country round trips, so every authenticated read in production spends roughly 350–450 ms waiting on the network to the database. |
| `/v1/health` (no database), 5 / 20 / 50 concurrent for 15 s each | 19 / 76 / **189 req/s**, p50 252 ms at every level (the test client's own distance to Oregon), no errors. The free instance's request handling is not the bottleneck at these levels. |

## Findings

1. **The connection pool was the first limit.** Raising it from 15 to 50 took
   50 users from 9% errors to none and multiplied throughput 2.7×. The new
   default is 20 + 30.
2. **Each chat send holds a database connection for the whole model call.**
   That makes concurrent sends ≤ pool size. With a 5 s model call and 50
   connections, one instance tops out around 10 sends/s if nothing else ran.
   The fix, when needed: release the connection during the model call (read
   context, commit, call the model, then write both turns in a new
   transaction). It changes the in-flight duplicate handling, so it is
   deliberately not part of this release.
3. **The API and the database are in different regions.** Render Oregon →
   Neon Ohio adds a cross-country round trip to every query; a read makes 4–5
   of them. Moving the API to Render's **Ohio** region (same AWS region as the
   database) removes most of every request's latency. Render regions cannot be
   changed in place, so this means creating the service anew in Ohio and
   moving the domain — an owner decision.
4. **Cold starts.** The free Render instance sleeps after ~15 minutes idle;
   the first request afterwards took **43 s** (measured). The Neon compute
   also suspends when idle and takes a few seconds to wake. The web app now
   allows 90 s for a chat send so a cold start does not fail the first
   message, and reads show a retry option.
5. **Per-instance rate limits.** Limits live in process memory, correct for
   one instance. Running several instances requires moving them to Redis.

## Capacity estimates

Concurrent users are people with a request in flight or thinking between
actions in one session, not registered or daily users. Rule of thumb for a
chat product: concurrent ≈ 5–10% of daily actives at peak, daily actives ≈
20–40% of registered.

| Registered | Daily active | Peak concurrent | Infrastructure | Basis |
|---|---|---|---|---|
| 1,000 | 200–400 | 10–40 | Current single instance, but **paid** Render (no sleep) | Tested: 50 concurrent at 0% errors on this code with the larger pool, even with the slow network path. |
| 5,000 | 1–2k | 50–200 | Render Standard (or larger) **in Ohio**, Neon autoscaling to 2 CU, connection release during model calls | 100 concurrent was 0.6% errors with the slow path; co-location removes most per-request time. **Estimate, not tested at this level in production.** |
| 10,000 | 2–4k | 100–400 | 2–3 instances behind Render's load balancer, Redis-backed rate limits, Neon pooler or larger compute, model rate-limit tier raised | **Estimate.** Requires the Redis limiter and a re-test. |

Model-provider rate limits are a separate ceiling: at 10 sends per minute
per active chatter, 400 concurrent chatters is ~67 model requests/s. Check the
organization's Claude rate-limit tier before that scale.

## Re-running

```bash
# Terminal 1: the API against the staging branch, mock model with latency
APP_ENV=dev LLM_PROVIDER=mock MOCK_LLM_LATENCY_MS=1500 RATE_LIMIT_ENABLED=false \
SUPABASE_JWT_HS_SECRET=<staging-only secret> DATABASE_URL=<staging url> \
  uvicorn app.main:app --port 8010
# Terminal 2
python scripts/load_test.py --base-url http://127.0.0.1:8010 \
  --hs-secret-env STAGING_JWT_HS_SECRET --stages 10,25,50,100,250 --duration 30
```

For production-representative numbers, run the same script from a machine in
the API's region (or deploy a staging service next to the database).
