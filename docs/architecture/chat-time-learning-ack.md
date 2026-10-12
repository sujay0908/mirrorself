# Chat-time Learning Acknowledgement (Sprint 10)

> **When the Twin has learned something the user confirmed, the next
> reply quietly says so — once, deterministically, and without ever
> failing the chat.**

Sprint 8 recorded durable, user-authorized Twin changes as
`twin_evolution_events`. Sprint 9 showed them in the Self-Portrait.
Sprint 10 surfaces the *new* ones inline in chat as a small "learning"
chip on the twin reply, then marks them acknowledged so they are never
shown again.

Nothing here is a new mutation path. The chip is a read over
`twin_evolution_events` plus an advance of a per-twin cursor. No LLM
decides what was learned; the events were already written by the
Sprint 7/8 confirm-and-apply paths. All Sprint 2–9 invariants hold.

---

## The surfacing contract

- A twin reply carries `metadata_json.learning` when there are confirmed
  evolution events the user has not seen yet; otherwise the field is
  `null`. The mobile client already reads `metadata_json`, so no API
  schema field was added.
- "Not seen yet" = `twin_evolution_events.seq` strictly greater than
  `twins.last_acknowledged_evolution_seq`. The reply surfaces the oldest
  such events first (by `seq`), at most `ACK_SURFACE_LIMIT` per turn, and
  advances the cursor to the max seq it surfaced. A backlog drains over
  successive turns.
- The chip distinguishes **learned** (a durable change took effect) from
  **acknowledged** (an `insight_acknowledged` event — Sprint 7 founder
  decision #1: acknowledgement, not identity mutation). The lead is
  computed server-side so the UI never diverges from what the apply
  dispatcher recorded.
- `summary` on each item is the same IDs-and-safe-metadata string the
  event was written with (capped at 255 chars, enforced at write time).
  No raw message, memory, goal, or profile content ever enters the chip.

## Why `seq`, not `(created_at, id)`

`created_at` is `transaction_timestamp()`, fixed at the writer's BEGIN,
not at commit. Under concurrent, out-of-order commits a writer can hold
an *earlier* `created_at` yet become visible *after* a later one, which
would let the cursor step over it and skip it forever. `seq` is drawn
from a dedicated sequence (`twin_evolution_events_seq`) at INSERT time
inside a per-twin advisory lock, so **commit order equals seq order per
twin** and "surface each event exactly once" holds. See
`EvolutionService.record` and `app/evolution/locks.py`.

## Atomicity, isolation, lock order

- The cursor advance and the twin-message INSERT commit in the **same
  transaction** (`ConversationService.post_message`), so "the user saw
  the chip" and "the cursor advanced" are atomically equivalent.
- The surface read runs inside a `SAVEPOINT` (`session.begin_nested()`).
  Any failure there (including a `lock_timeout` while a migration holds
  `ACCESS EXCLUSIVE`) rolls back only the read; the outer chat
  transaction stays usable and still persists the reply. **The
  acknowledgement never fails the chat.**
- The per-twin evolution advisory lock is acquired inside that SAVEPOINT
  and, on success, promoted to the outer transaction when the SAVEPOINT
  is released — so it is held through the cursor advance and commit,
  serializing concurrent chats for the same twin. (Empirically: an
  advisory lock taken in a SAVEPOINT survives `RELEASE SAVEPOINT` and is
  released by `ROLLBACK TO SAVEPOINT`.)
- **Stale-cursor defense (exactly-once).** The lock serializes *execution*
  but the twin was loaded — and its `last_acknowledged_evolution_seq`
  read — before the lock was held. A second chat that waited on the lock
  while the first advanced and committed the cursor would otherwise still
  see its own stale in-memory `0` and re-surface the same events. So,
  immediately after acquiring the lock, the ack re-reads the cursor
  (`session.refresh(twin, attribute_names=["last_acknowledged_evolution_seq"])`,
  READ COMMITTED) before the surface query. This is what makes
  concurrent chats surface a given event **exactly once**; it is verified
  by `test_sprint10_pg.py::test_concurrent_chats_surface_event_once`.
- **Global lock order: `twins` → `twin_evolution_events`.** Every
  owner-scoped request loads its twin first (`require_by_user`, a plain
  `SELECT` = AccessShare on `twins`, held for the whole request) and only
  then reads/writes `twin_evolution_events` (always via `EvolutionService`
  with the twin already loaded; there is no `FOR UPDATE`/`LOCK` on `twins`
  anywhere, and no path touches the event table before the twin). The
  write paths never hold a `twins` **row** lock while inserting an event
  (reflection `profile_update` commits its `twins` write in a separate
  transaction before the event write; `MemoryService.confirm_candidate`
  never writes `twins`) — but they, like the ack path, do hold `twins`
  AccessShare. Migration 0007 therefore must take its locks in this same
  order (see below).
- The advisory lock uses a dedicated `twin-evolution:` namespace,
  **not** the Sprint 8.1 `reflection-scheduler:` key (which is held
  across the reflection LLM call). A chat ack therefore never blocks on
  a reflection LLM call.

On SQLite (the test harness) the advisory lock and the Postgres sequence
are no-ops / replaced by `MAX(seq)+1`; SQLite deployments are
single-writer by construction.

---

## Migration 0007

`0007_chat_time_learning_ack` adds `twin_evolution_events.seq` and
`twins.last_acknowledged_evolution_seq`, with `SET LOCAL lock_timeout`/
`statement_timeout` as inner guards. It takes `ACCESS EXCLUSIVE` on
**`twins` first, then `twin_evolution_events`** — matching the global
reader order above — then backfills every existing event's `seq` in
`(created_at, id)` order under those locks, pins each twin's cursor to
its own `MAX(seq)` (event-less twins stay at `0`), and advances the
sequence so the next `nextval()` is strictly greater than the largest
backfilled value.

**Lock-order deadlock avoidance.** An earlier revision locked
`twin_evolution_events` first and `twins` later (via `ADD COLUMN`). That
is the *opposite* of the global reader order, and it deadlocks with any
concurrent chat/confirm request: the request holds `twins` AccessShare
and waits for `twin_evolution_events`, while the migration holds
`twin_evolution_events` and waits for `twins`. This cycle was reproduced
against a live cluster. Locking `twins` first removes it entirely —
because every app transaction is twins-before-events, a twins-first
migration never closes a cycle (whoever holds `twins` forces the other
to wait before it can touch the event table). Guarded by a static test
(`test_sprint10_learning_ack.py::test_migration_locks_twins_before_events`)
and a dynamic two-connection test
(`test_sprint10_pg.py::test_corrected_lock_order_no_deadlock`, which
replays the migration's lock order *as written in the file* and fails if
it regresses to events-first).

**Migration-boundary guarantee.** Because the backfill runs under
`ACCESS EXCLUSIVE`, every pre-Sprint-10 event is captured in `[1, N]`,
each twin's cursor sits at its own ceiling, and any post-migration
INSERT — including one whose writer transaction began before the
migration and commits after it — draws `seq > N`. So no pre-Sprint-10
event is ever surfaced as "learning", and no post-migration event is
skipped. Verified by
`tests/test_sprint10_pg.py::test_migration_backfills_seq_and_cursor_and_boundary`.

Rollback (`downgrade`) drops both columns, the unique constraint, the
`(twin_id, seq)` index, and the sequence. It is a pure structural
reversal; it does not reconstruct any acknowledgement state (there is no
durable state beyond the cursor column it removes). The downgrade and a
re-upgrade round-trip are verified by
`test_sprint10_pg.py::test_migration_downgrade_removes_sprint10_objects`.

The migration runs on PostgreSQL only. The test suite builds its schema
from the ORM models, never from Alembic, so this migration is never
invoked against SQLite (it raises clearly if it ever is).

---

## Deployment / rollout

**What is implemented in this repo** and works against the actual
deployment target (a Supabase PostgreSQL reached over a service-role
connection; no Kubernetes, no migration-role provisioning, no control
over cluster roles):

1. The migration's inner `lock_timeout` (15s) and `statement_timeout`
   (120s). If an unexpected lock holder is present the migration fails
   fast and the schema is untouched (it runs in one transaction), rather
   than blocking the cluster. Re-run after the holder clears.
2. `ACCESS EXCLUSIVE` + backfill, which gives the migration-boundary
   guarantee above without any external coordination.
3. **Twins-first lock order**, which makes the migration deadlock-free
   against concurrent chat/confirm requests (see "Lock-order deadlock
   avoidance" above) — the migration may *wait* for an in-flight request,
   but the two can no longer form a cycle. This holds even if traffic is
   not quiesced.
4. An **optional, read-only** preflight check,
   `apps/api/scripts/sprint10_migration_preflight.sql`, that an operator
   can run against the target database just before the migration to see
   whether any other client backend holds an open transaction or a
   prepared transaction exists. It is advisory: it reports, it does not
   fence.

**What is intentionally NOT implemented here.** The design review
(Corrections 14–17) specified a strict connection fence — drain app
workers, `REVOKE CONNECT` / role-level `NOLOGIN` on a dedicated
`twin_migrator` role, a privilege gate, and running Alembic on a fenced
connection. None of that is provisioned in this repository, and the
production target does not grant this project the cluster-role control
(`ALTER DATABASE`, `pg_signal_backend`, `CREATEROLE`, a superuser
allowlist) those steps require. Implementing them here would be
inventing infrastructure that does not exist. They remain **operational
guidance** for an environment that can support them; the migration's
inner guards + the optional preflight are the robust, in-repo subset.

Recommended rollout for the current environment: a quiet window is still
preferred (it minimizes the migration's wait on in-flight AccessShare
locks), but is no longer required for *correctness* — the twins-first
lock order removes the deadlock the audit reproduced. Run the preflight
first and investigate any rows it reports; rely on the inner
`lock_timeout` as the backstop.

## Test coverage & CI

The `postgres`-marked tests in `tests/test_sprint10_pg.py` run in CI:
`.github/workflows/api.yml` provisions a `pgvector/pgvector:pg16`
service (the image ships the `vector` extension the Alembic chain needs)
and sets `PAT_TEST_PG_DSN`, so they no longer skip. They cover
advisory-lock seq==commit ordering, the out-of-order-commit scenario,
the migration boundary, the lock-order deadlock regression (both a
static file-order guard and a dynamic two-connection replay),
concurrent-chat exactly-once surfacing, and the downgrade round-trip.
Locally they run against any PostgreSQL named by `PAT_TEST_PG_DSN` (unix
socket or TCP); without it they skip and the SQLite suite still runs.

---

## Files

- `apps/api/alembic/versions/0007_chat_time_learning_ack.py` — migration.
- `apps/api/app/evolution/models.py` — `seq` column + `(twin_id, seq)` index.
- `apps/api/app/twin/models.py` — `last_acknowledged_evolution_seq`.
- `apps/api/app/evolution/service.py` — `record()` seq assignment +
  `unacknowledged_for_twin()`.
- `apps/api/app/evolution/locks.py` — per-twin `twin-evolution:` advisory lock.
- `apps/api/app/evolution/acknowledgement.py` — deterministic chip composer.
- `apps/api/app/conversation/service.py` — `_acknowledge_learning_safely`
  (advisory lock + post-lock cursor refresh + SAVEPOINT-isolated read).
- `apps/mobile/src/lib/learning.ts`, `src/components/MessageBubble.tsx`,
  `src/api/types.ts` — the chip.
- `.github/workflows/api.yml` — Postgres service + `PAT_TEST_PG_DSN`.
- `apps/api/scripts/sprint10_migration_preflight.sql` — optional preflight.
- Tests: `tests/test_sprint10_learning_ack.py` (SQLite, incl. the static
  lock-order guard), `tests/test_sprint10_pg.py` (PostgreSQL-only),
  `apps/mobile/__tests__/learning.test.ts`.
