# Evolving Twin Loop (Sprint 8)

> **The Twin becomes better at understanding the user over time —
> without silently changing who the user is.**

Sprint 8 closes the loop started by Sprint 7:

```
Conversation
  → Memory
  → Reflection opportunity   ← Sprint 8 adds this stage
  → Reflection candidate
  → USER confirmation
  → Twin evolves             ← Sprint 8 adds the audit trail
  → Better future context
```

Everything added here is a *proposal* until the user confirms it.
`TwinProfile` still only moves through `TwinService.update`; `Memory`
still only becomes durable through `MemoryService.confirm_candidate`;
`memory_dedup` still writes nothing destructive. The Sprint 2-7
invariants are preserved.

---

## Three founder decisions this sprint pins

1. **Trigger clause.** `should_run` is the deterministic conjunction
   ```
   meaningful_trigger AND cooldown_expired AND backlog_below_limit
   ```
   where `meaningful_trigger` is either a memory signal or a goal
   signal — **not both**. See `OpportunityPolicy.evaluate`.
2. **Confirmation time.** "New confirmed memories since the last run"
   is counted against `memories.confirmed_at` — the immutable moment
   a candidate became durable. Not `created_at` (candidate age can
   predate confirmation by days), not `last_confirmed_at` (that
   advances on user edits). See `MemoryService.confirm_candidate`.
3. **Evolution vs. candidate.** A reflection *candidate* is a
   proposal. A `twin_evolution_events` row is only ever written after
   a durable, user-authorized change succeeds. Rejected candidates do
   NOT create evolution rows. The mobile UI phrases pending as
   *"Your Twin noticed…"* and confirmed as *"Your Twin learned…"*
   (with `insight_acknowledged` as the one exception — Sprint 7's
   insight contract says that is acknowledgement, not identity
   mutation, so the UI renders it as *"You acknowledged…"*).

---

## Chat pipeline unchanged in shape; two new enqueues

```
User message
    │
    ▼
intent detection (rule-based, deterministic)       ─── never raises
    │
    ▼
context policy → retrieval → goals → ContextBuilder (Sprint 6)
    │
    ▼
LLM → persist user turn + twin turn                ─── atomic
    │
    ├──► memory extraction task (Sprint 2)         ─── existing
    ├──► intent telemetry task (Sprint 8)          ─── NEW, safe-metadata-only
    └──► reflection scheduler task (Sprint 8)      ─── NEW, policy decides SKIP vs RUN
```

Both new enqueues go through the existing `TaskRunner` protocol
(`FastAPIBackgroundRunner` in production, `ImmediateRunner` in tests).
No Redis. No cron. No scheduled jobs. The scheduler fires on every
chat turn, but the policy is conservative — almost every call returns
SKIP. Chat latency is unaffected because both tasks run AFTER the
response is persisted and returned.

Failure of either task is swallowed and logged. The chat response is
already in the user's hands by the time the task runs; the exception
can never bubble back.

---

## Opportunity policy — the only new decision in the loop

`OpportunityPolicy.evaluate(OpportunitySignals)` is a pure function on
the following signals:

| Signal                          | Where it comes from                                                                                                                              |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `new_confirmed_memories`        | `COUNT(memories WHERE twin_id = … AND user_confirmed AND NOT superseded AND confirmed_at > twin.last_reflection_run_at)`                        |
| `meaningful_goal_events`        | `COUNT(goal_events JOIN goals WHERE twin_id = … AND event_type IN ('status_changed','updated') AND created_at > twin.last_reflection_run_at)` |
| `pending_backlog`               | `COUNT(reflection_candidates WHERE twin_id = … AND status='pending')`                                                                           |
| `seconds_since_last_run`        | `now - twin.last_reflection_run_at` (`None` when the twin has never run)                                                                        |

Policy decision tree, in order:

1. `pending_backlog >= max_pending_backlog` → `skip:backlog_full` (never pile on).
2. `seconds_since_last_run < cooldown_seconds` → `skip:cooldown_active` (cooldown bypassed when the twin has never run).
3. `new_confirmed_memories >= min_new_memories` → `run:new_memories`.
4. `meaningful_goal_events >= min_goal_events` → `run:goal_activity`.
5. Otherwise → `skip:no_meaningful_trigger`.

The `goal_update` event path writes a `GoalEvent(event_type='updated')`,
which **does** show up as a meaningful goal event in step 4. We
accept this intentionally — a user-confirmed reflection on a goal is
exactly the kind of signal that should earn the next reflection
opportunity.

Defaults (overridable via `Settings`, each tunable without redeploy):

| Setting                              | Default |
| ------------------------------------ | ------- |
| `reflection_min_new_memories`        | 3       |
| `reflection_min_goal_events`         | 2       |
| `reflection_min_cooldown_seconds`    | 1800    |
| `reflection_max_pending_backlog`     | 10      |

**No LLM is involved in the decision.** The policy is deterministic,
testable, and pure. `test_opportunity_policy.py` pins every branch.

---

## Memory lifecycle — the new `confirmed_at` column

`memories.confirmed_at` is **immutable after first set**:

| Column                | When it's set                                                   | Can it change later?                        |
| --------------------- | --------------------------------------------------------------- | ------------------------------------------- |
| `created_at`          | Row insert at `MemoryService.confirm_candidate`                 | No                                          |
| `confirmed_at`        | Row insert at `MemoryService.confirm_candidate`                 | **No** — guarded by code + test             |
| `last_confirmed_at`   | Row insert at `MemoryService.confirm_candidate`                 | Yes — may advance on a future reconfirmation|

The Sprint 8 migration backfills existing rows via
`COALESCE(last_confirmed_at, created_at)` for `user_confirmed = TRUE`.
A memory that was superseded by a `memory_dedup` reflection keeps its
`confirmed_at`; an un-supersede does not touch it either. The
opportunity policy's "new memories since last run" is accurate even
when a candidate created days earlier is confirmed today — because
`confirmed_at` is the *confirmation* moment, not the candidate's
`created_at`.

---

## Twin evolution events — the audit trail

```
twin_evolution_events
├── id (uuid)
├── user_id, twin_id (CASCADE from twins)
├── event_type ∈ (
│       memory_learned,
│       memory_consolidated,
│       goal_updated,
│       profile_confirmed,
│       insight_acknowledged      ← Sprint 7 insight = acknowledgement
│   )
├── reflection_id?  → reflection_candidates (SET NULL on delete)
├── memory_id?      → memories                (SET NULL on delete)
├── goal_id?        → goals                   (SET NULL on delete)
├── profile_field?  (string, only for profile_confirmed)
├── summary         (string ≤ 255 — IDs + kind of change only, NO content)
└── created_at
```

Writers:

- `MemoryService.confirm_candidate` → `memory_learned` **inside the
  same transaction** as the memory and source rows. A failed commit
  rolls back both together.
- `ReflectionService._record_evolution_for` → `memory_consolidated`,
  `goal_updated`, `profile_confirmed`, `insight_acknowledged`, called
  **only after** the per-kind apply succeeded. A failed apply writes
  `apply_error` and NEVER emits an evolution event.
- `ReflectionService.reject` → **nothing** (Decision 3).

Reader:
- `GET /v1/twin/evolution?limit=N` → newest-first, owner-scoped,
  N ≤ 100.

RLS: `twin_evolution_events_owner` policy follows the memories
pattern (direct `twin_id` ownership).

---

## Intent telemetry — safe-metadata-only

The Sprint 6 `RuleBasedIntentDetector` stays live and unchanged.
Sprint 8 adds *telemetry* so a later sprint can evaluate detector
accuracy without replaying user content.

```
intent_telemetry_events
├── id, user_id, twin_id
├── intent                   (StrEnum value, e.g. "PLAN")
├── confidence               (0..1)
├── reason                   (short tag — "phrase:plan", "fallback:short_message", …)
├── detector_name            (e.g. "rule-based-v1")
├── latency_ms
├── message_length_bucket    ∈ (short, medium, long)
└── created_at
```

**No content fields.** No `message_id`. No FK that would let a reader
reconstruct the words. The length bucket is computed in the request
scope so the raw text never reaches the background task:

```
ConversationService.post_message
    (len(content.strip()) → bucket in {short, medium, long})
    enqueue(record_intent_telemetry_task, bucket=…)   ← no `content` arg
```

The `test_privacy_sentinel_never_appears_in_evolution_rows_or_logs`
test seeds a sentinel into both the chat message and the memory
content, confirms the entire turn, and asserts the sentinel is absent
from every evolution row, every telemetry row, and every structlog
event emitted during the turn.

---

## Architectural invariants preserved

| Invariant                                                              | How Sprint 8 preserves it                                                                 |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| LLM → `TwinProfile` is NEVER direct                                   | `_apply` still dispatches to `TwinService.update`; scheduler NEVER writes profile data.    |
| User confirmation is required for every durable mutation               | Scheduler only *proposes* candidates; apply still gates on `confirm`.                      |
| Memory supersession is non-destructive and reversible                  | Unchanged. `confirmed_at` is kept intact across supersede / un-supersede.                 |
| Chat failure isolation                                                 | Scheduler + telemetry run AFTER the chat response is persisted; exceptions are swallowed. |
| Cross-user / cross-twin access is impossible                           | Every new service checks owner scope; new RLS policies on both tables.                    |
| Rejected reflection ≠ Twin evolution                                   | `_record_evolution_for` runs only on `applied=True`; reject writes nothing.                |
| Logs contain IDs/counts/safe metadata only                             | Nine new structlog events (listed below), each with IDs + a short tag.                    |

---

## Observability — nine new structured events

- `reflection.opportunity.detected` / `.skipped` — one of these fires on every chat turn.
- `reflection.schedule.started` / `.completed` / `.failed`
- `twin.evolution.created`
- `intent.detected`
- `intent.telemetry.failed`
- `reflection.candidate.proposed` (already existed, now also fires from the scheduler path).

All carry twin ID, counts, and (where applicable) a short reason tag.
Never user content.

---

## Non-goals (deferred past Sprint 8)

- LLM-backed intent detection — still rule-based.
- Scheduled reflection via cron / Redis / arq — still manual-trigger + chat-time scheduler only.
- Autonomous profile mutation — never.
- Emotional state / mood tracking — still out.
- `/v1/me/story` / Twin narrative — still out.
- Multi-turn reflection reasoning — still out.
- OpenAPI → `shared-types/generated.ts` — still out.
- Insight → Memory auto-promotion — still out (Sprint 7 Decision #1 preserved).

---

## Where this lives in the repo

| Concern                            | Path                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------ |
| Opportunity policy + scheduler     | `apps/api/app/reflection/scheduler.py`                                   |
| Scheduler background task          | `apps/api/app/reflection/tasks.py`                                       |
| Evolution ORM / service / schemas  | `apps/api/app/evolution/`                                                |
| Evolution endpoint                 | `apps/api/app/api/v1/evolution.py`                                       |
| Intent telemetry ORM / service     | `apps/api/app/telemetry/models.py`, `app/telemetry/service.py`           |
| Intent telemetry background task   | `apps/api/app/telemetry/tasks.py`                                        |
| Memory `confirmed_at` + evolution hook | `apps/api/app/memory/models.py`, `app/memory/service.py`             |
| Twin `last_reflection_run_at`      | `apps/api/app/twin/models.py`                                            |
| Reflection apply → evolution       | `apps/api/app/reflection/service.py` (`_record_evolution_for`)           |
| Chat enqueue of scheduler + telemetry | `apps/api/app/conversation/service.py`                                |
| Config                             | `apps/api/app/config.py`                                                 |
| Migration                          | `apps/api/alembic/versions/0006_evolving_twin_loop.py`                   |
| Schema mirror                      | `infra/supabase/schema.sql`                                              |
| RLS policies                       | `infra/supabase/policies.sql`                                            |
| RLS smoke                          | `infra/supabase/tests/evolving_twin_loop_rls_smoke.sql`                  |
| Policy unit tests                  | `apps/api/tests/test_opportunity_policy.py`                              |
| Integration tests                  | `apps/api/tests/test_sprint8_evolving_twin_loop.py`                      |
| Mobile types + client              | `apps/mobile/src/api/types.ts`, `src/api/client.ts`                      |
| Mobile evolution screen            | `apps/mobile/app/(main)/evolution/index.tsx`                             |
| Mobile home tile                   | `apps/mobile/app/(main)/home.tsx`                                        |
