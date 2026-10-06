# Reflection Subsystem (Sprint 7)

> **The LLM proposes. The user confirms. Only confirmation can create
> durable changes.**

Sprint 7 adds the Twin's first *reflection* subsystem. The Twin can read
a bounded view of the user's own confirmed memories, active goals and
recent conversation turns, and *propose* observations the user can review
and act on. Nothing in this subsystem mutates `TwinProfile`, writes a
`Memory`, changes a `Goal`, or supersedes a memory **without** an
explicit user confirmation on an owned reflection candidate.

The subsystem is manual: `POST /v1/reflections/run` starts a run, and
the user confirms or rejects each resulting candidate. There is no
cron, no Redis, no scheduled reflection — scheduling lands in a later
sprint.

---

## Pipeline

```
Manual trigger (POST /v1/reflections/run)
    │
    ▼
bounded, owner-scoped input load
   (≤ 24 confirmed memories, ≤ 10 active goals, ≤ 20 recent turns)
    │
    ▼
ReflectionExtractor
   (LLMProvider — same protocol as chat; never raises
    into the request path; strict JSON output)
    │
    ▼
per-kind validated drafts  (profile_update, memory_dedup,
                             goal_update, insight)
    │
    ▼
fingerprint dedup
   (SHA-256 over twin_id, kind, sorted source_memory_ids,
    sorted source_goal_ids — pending candidates only)
    │
    ▼
reflection_candidates (status=pending)
    │
    ▼
user review  ──  POST /v1/reflections/{id}/confirm
             │   POST /v1/reflections/{id}/reject
             ▼
status change COMMITS before apply runs
             ▼
apply dispatcher (reuses existing service boundaries)
   profile_update → TwinService.update(TwinProfilePatch)
   memory_dedup   → MemoryService.supersede(a, b)
   goal_update    → GoalEvent(event_type="updated", note=…)
   insight        → acknowledgement only — no Memory, no profile mutation
```

The pipeline never touches the Sprint 6 chat pipeline. A reflection
failure cannot break conversation; the reflection extractor shares the
chat `LLMProvider` by default via `reflection_extractor_dep`, but the
extractor itself is wrapped so provider or JSON errors return an empty
`ReflectionExtractionResult` with a short, non-sensitive `error`
reason (`provider_error:<Class>`, `parse_error`, `empty_response`).

---

## Approved reflection kinds

Exactly four. Any JSON output from the extractor whose `kind` is not in
this list is dropped silently.

| Kind              | What a confirm does                                                     | What it does NOT do                                                      |
| ----------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `profile_update`  | `TwinService.update(user_id, TwinProfilePatch(**{field: proposed}))`    | Does not touch any other `TwinProfilePatch` field                        |
| `memory_dedup`    | `MemoryService.supersede(twin, superseded_id, canonical_id)`            | Does not delete the superseded memory, its sources, or its embeddings    |
| `goal_update`     | Append `GoalEvent(event_type="updated", note=payload.note)`             | Does not change the goal's title, status, priority, or target_date       |
| `insight`         | Marks the candidate as `confirmed`                                      | Does not create a `Memory`, does not mutate `TwinProfile`                |

Two founder decisions pin the shape of the subsystem:

1. **Insight confirmation is acknowledgement only.** The reflection
   row itself is the record. We explicitly do NOT auto-create a Memory
   from an insight — that would be a double-confirmation UX hiding
   silent identity mutation. If the user wants an insight to become a
   `FACT`, that is a separate explicit action in a later sprint.

2. **Profile-update payload carries the diff.** Every
   `ProfileUpdatePayload` must expose `current_value`, `proposed_value`,
   source memory IDs, rationale and confidence. The mobile Reflections
   screen renders the diff block before the Confirm button is pressed,
   so the user can answer *"why does my Twin think this about me?"*
   before confirming. The payload schema is a Pydantic discriminated
   union; a draft missing any of these fields is dropped silently
   before it is ever stored.

---

## Data model

### `reflection_candidates`

```
id                 UUID PK
user_id            UUID            — owner (indexed)
twin_id            UUID → twins.id ON DELETE CASCADE (indexed)
kind               VARCHAR(32)     CHECK (kind IN (…four values…))
status             VARCHAR(16)     CHECK (status IN ('pending','confirmed','rejected'))
proposed_payload   JSON            — per-kind payload (see schemas)
source_memory_ids  JSON            — explicit provenance for the UI
source_goal_ids    JSON
rationale          TEXT            — human-readable, short
confidence         FLOAT           CHECK (0 ≤ … ≤ 1)
importance         FLOAT           CHECK (0 ≤ … ≤ 1)
fingerprint        VARCHAR(64)     — SHA-256 hex; see dedup below
resolved_at        TIMESTAMPTZ     — set at confirm/reject
apply_error        VARCHAR(255)    — populated when apply fails after confirm
apply_metadata     JSON            — safe metadata returned to the client
created_at         TIMESTAMPTZ
updated_at         TIMESTAMPTZ

INDEX ix_reflection_candidates_twin_status_created (twin_id, status, created_at)
INDEX ix_reflection_candidates_twin_fingerprint    (twin_id, status, fingerprint)
```

RLS policy (`infra/supabase/policies.sql`):
```sql
CREATE POLICY reflection_candidates_owner ON reflection_candidates
    FOR ALL
    USING (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()))
    WITH CHECK (twin_id IN (SELECT id FROM twins WHERE user_id = auth.uid()));
```

### `memories.superseded_by_memory_id`

A nullable self-FK (`ON DELETE SET NULL`) added by the same migration.

- Confirmed `memory_dedup` reflections set this pointer; **nothing is
  deleted.** The row stays, its sources stay, its embeddings stay.
- Retrieval (`MemoryRetriever._pg_candidates` and
  `_portable_candidates`) filters by `superseded_by_memory_id IS NULL`
  so chat context never includes a superseded row.
- The normal `GET /v1/memories` list still returns superseded rows so
  the user can see the status in the mobile UI, open the canonical
  memory, or un-supersede.
- `POST /v1/memories/{id}/unsupersede` clears the pointer. The
  retrieval filter picks the memory up again on the next chat turn.
- `MemoryService.supersede` enforces cross-twin safety: both IDs are
  resolved through `self.get(twin, …)`, which checks ownership before
  issuing the UPDATE. A cross-twin attempt raises
  `MemoryNotFoundError` and the reflection ends up with status
  `confirmed` and `apply_error` populated; the two memories stay
  untouched.
- The column lives inside the existing `memories_owner` RLS policy —
  it is a column, not a new table — so cross-user visibility and
  cross-user supersede attempts are both rejected at the database
  layer. Verified by `infra/supabase/tests/reflection_rls_smoke.sql`.

---

## Confirmation + apply contract

The `confirm` and `reject` endpoints each take `(twin, reflection_id)`
and run through `ReflectionService._require_owned_candidate`, which
filters by **id + twin_id + user_id**. A reflection owned by another
user returns 404 (not 403) to avoid leaking existence.

### Status change commits BEFORE apply runs

```python
candidate.status = "confirmed"
candidate.resolved_at = now()
await self._session.commit()        # ← commit #1

try:
    applied, apply_metadata = await self._apply(…)
    candidate.apply_metadata = apply_metadata
except ReflectionApplyError as exc:
    candidate.apply_error = str(exc)
    applied, apply_metadata = False, {}
await self._session.commit()        # ← commit #2
```

This is deliberate. If apply failed and the status were still
`pending`, the next `confirm` would re-run apply — a double-apply bug
on retries. By committing the status change first:

- A second `confirm` request on the same id raises
  `ReflectionAlreadyResolvedError` → **HTTP 409**.
- A failed apply (e.g. cross-twin dedup, deleted goal) is reported in
  `apply_error`; the candidate stays `confirmed` and is NOT retried.
- The `apply_metadata` returned to the client is populated on success
  and empty on apply failure.

The apply dispatcher never writes to the database directly — every
mutation goes through `TwinService.update` / `MemoryService.supersede`
/ the existing `GoalEvent` write path. The LLM-never-mutates-profile
invariant from Sprint 1 is preserved exactly.

### What a confirm returns

```json
{
  "reflection": { … full ReflectionOut … },
  "applied": true,
  "apply_metadata": {
    "kind": "profile_update",
    "field": "communication_style_notes",
    "twin_id": "…"
  }
}
```

---

## Deduplication

Reflection runs are safe to repeat. Each draft produces a deterministic
fingerprint:

```
fingerprint = sha256(
    twin_id || "\n" ||
    kind || "\n" ||
    "\n".join(sorted(str(x) for x in source_memory_ids)) || "\n" ||
    "\n".join(sorted(str(x) for x in source_goal_ids))
).hexdigest()
```

Before inserting new candidates, the service loads the set of
pending-candidate fingerprints for this twin in one query, then skips
any draft whose fingerprint is already pending (either in the DB or in
the same batch). The `candidates_deduplicated` counter in the
`ReflectionRunOut` response makes this visible to the client.

This is deliberately *not* semantic deduplication. If the extractor
emits two drafts that cite the same memories but say slightly different
things, they fingerprint identically and only the first survives — the
cost of a stray duplicate is small, and a semantic dedup pass would
itself need confirmation infrastructure.

---

## Observability

Structured events (structlog), IDs and counts only:

| Event                              | Where                                        | Fields                                                     |
| ---------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `reflection.run.ok`                | `ReflectionService.create_candidates`        | `twin_id`, `proposed`, `persisted`, `deduplicated`         |
| `reflection.run.failed`            | `/v1/reflections/run` dispatcher             | `twin_id`, `error`                                         |
| `reflection.extractor.empty`       | `ReflectionExtractor.extract`                | `twin_id`                                                  |
| `reflection.extractor.failed`      | `ReflectionExtractor.extract`                | `twin_id`, `error` (short, non-sensitive)                  |
| `reflection.candidate.proposed`    | `ReflectionService.create_candidates`        | `twin_id`, `candidate_id`, `kind`                          |
| `reflection.candidate.confirmed`   | `ReflectionService.confirm`                  | `twin_id`, `candidate_id`, `kind`                          |
| `reflection.candidate.rejected`    | `ReflectionService.reject`                   | `twin_id`, `candidate_id`, `kind`                          |
| `reflection.apply.ok`              | `ReflectionService._apply`                   | `twin_id`, `candidate_id`, `kind`                          |
| `reflection.apply.failed`          | `ReflectionService._apply`                   | `twin_id`, `candidate_id`, `kind`, `error`                 |

The extractor itself logs nothing. The service layer never logs raw
memory content, raw goal content, raw user messages, proposed profile
text, or any secret. A privacy regression test
(`test_reflection_run_does_not_leak_sentinel_in_logs`) seeds a sentinel
string into memory content and asserts the sentinel never appears in
any captured structlog event emitted during the run.

---

## Architectural invariants preserved

| Invariant                                                              | How Sprint 7 preserves it                                                                 |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `TwinProfile` ≠ `Memory` ≠ `TwinState`                                 | Reflection candidates are a fourth, orthogonal concept — proposals, not state.            |
| LLM never directly mutates durable user state                          | `_apply` dispatches to existing services; the LLM never gets a DB handle.                  |
| User confirmation is required for every durable mutation               | `status = 'pending'` is the only state the extractor can produce; apply gates on confirm. |
| Memory provenance remains explicit                                     | `source_memory_ids` on every candidate; `MemoryService.supersede` leaves sources intact.  |
| Supersession is non-destructive                                        | `superseded_by_memory_id` is a pointer, not a delete; `/unsupersede` is the inverse.      |
| Reflection failure never breaks chat                                   | The extractor swallows all exceptions; the chat pipeline never calls it.                  |
| Cross-user / cross-twin access is impossible                           | `_require_owned_candidate` + `MemoryService.supersede` ownership checks + RLS policy.     |

---

## What Sprint 7 explicitly does NOT do

Deferred to a later sprint — see `SPRINT 7 IMPLEMENTATION
AUTHORIZATION`'s OUT OF SCOPE list for the full statement:

- No cron, no Redis/arq, no scheduled reflection runs. `POST
  /v1/reflections/run` is the only trigger.
- No automatic promotion of `insight` to `FACT` memory.
- No LLM-backed intent detection (Sprint 6 kept its rule-based
  detector).
- No emotional state, no mood tracking.
- No multi-turn reflection reasoning, no multi-intent handling.
- No `/v1/me/story`, no twin narrative, no export/delete-me compliance
  surface.
- No shared-types regeneration — the mobile package has its own hand
  type for `Reflection` until the OpenAPI → `generated.ts` pipeline
  lands.

---

## Where this lives in the repo

| Concern                        | Path                                                          |
| ------------------------------ | ------------------------------------------------------------- |
| ORM models                     | `apps/api/app/reflection/models.py`                           |
| Pydantic schemas (union)       | `apps/api/app/reflection/schemas.py`                          |
| Extractor (LLM wrapper)        | `apps/api/app/reflection/extractor.py`                        |
| Service + apply dispatcher     | `apps/api/app/reflection/service.py`                          |
| Errors                         | `apps/api/app/reflection/errors.py`                           |
| FastAPI endpoints              | `apps/api/app/api/v1/reflections.py`                          |
| Dependencies                   | `apps/api/app/api/deps.py` (`reflection_service_dep`, …)      |
| Memory supersession helpers    | `apps/api/app/memory/service.py` (`supersede`, `unsupersede`) |
| Retrieval filter               | `apps/api/app/memory/retrieval.py`                            |
| Un-supersede endpoint          | `apps/api/app/api/v1/memories.py`                             |
| Migration                      | `apps/api/alembic/versions/0005_reflection.py`                |
| Schema mirror                  | `infra/supabase/schema.sql`                                   |
| RLS policy                     | `infra/supabase/policies.sql`                                 |
| RLS smoke test                 | `infra/supabase/tests/reflection_rls_smoke.sql`               |
| Unit tests (extractor)         | `apps/api/tests/test_reflection_extractor.py`                 |
| Integration tests              | `apps/api/tests/test_sprint7_reflection.py`                   |
| Mobile types                   | `apps/mobile/src/api/types.ts`                                |
| Mobile client                  | `apps/mobile/src/api/client.ts`                               |
| Mobile reflections list        | `apps/mobile/app/(main)/reflections/index.tsx`                |
| Mobile supersede UI            | `apps/mobile/app/(main)/memories/[id].tsx`                    |
| Mobile list supersede badge    | `apps/mobile/app/(main)/memories/index.tsx`                   |
| Home entry point               | `apps/mobile/app/(main)/home.tsx`                             |
