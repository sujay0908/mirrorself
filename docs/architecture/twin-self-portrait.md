# Twin Self-Portrait (Sprint 9)

> **The Twin's existing knowledge, made visible and controllable —
> without ever asking an LLM to narrate it.**

Sprint 9 adds one user-facing surface and one supporting endpoint:

```
GET /v1/twin/portrait
    → deterministic composition of profile + confirmed memories +
      active goals + recent evolution events, owner-scoped by the
      authenticated user.

PATCH /v1/twin
    → unchanged. Sprint 9 adds a mobile Profile Edit screen that
      calls this existing endpoint.
```

No new persistence. No new migration. No new background task. No new
LLM call. No new reflection path. No new autonomous behavior. The
portrait is a trust surface — accuracy is more important than
cleverness, so it never generates narrative.

---

## 1. Purpose

The retrieval, ranking, context-injection, reflection, and evolution
subsystems built in Sprints 2–8.1 already personalize every chat turn.
What they do not do, until Sprint 9, is show the user — in one place —
what their Twin thinks it knows about them. The Self-Portrait screen
closes that perceptual gap:

- **How I speak to you** — style preset, style notes, basic profile.
- **What I remember about you** — total confirmed-memory count, counts
  by type, top-5 memories by importance with a bounded snippet.
- **What you're working on** — up to 5 active goals via the Sprint 4
  active-goal query.
- **What I've noticed recently** — the newest 5 Sprint-8 evolution
  events, each tagged with its Sprint-8 user-facing "lead"
  (*learned* for durable change, *acknowledged* for insight).

The screen is paired with a direct mid-session Profile Edit so the
user can refine `communication_style_preset`,
`communication_style_notes`, and `basic_profile` at any time — through
the existing `TwinService.update` path, not a new mutation route.

---

## 2. Deterministic composition

```
PortraitComposer.compose(twin) →
    TwinPortrait(
        profile         : TwinProfile fields (read from the ORM instance)
        memory_summary  : total_count + counts_by_type + top_memories
        active_goals    : GoalService.list_active_for_context(twin, 5)
        recent_evolution: EvolutionService.list_for_twin(twin, 5)
    )
```

- Pure read-aggregator. No LLM call. No row written.
- Memory queries filter by `(twin.id, twin.user_id, user_confirmed=TRUE,
  superseded_by_memory_id IS NULL)` — the exact filter the chat-time
  retriever uses, so a memory that appears in the portrait is the
  same memory that appears in chat context.
- Memory snippets are truncated at 240 characters (`str` slicing is
  code-point aware, so Unicode never splits a code point). An
  ellipsis is appended when the original overflowed.
- `active_goals` delegates to `GoalService.list_active_for_context`;
  no duplicate SQL.
- `recent_evolution` delegates to `EvolutionService.list_for_twin`;
  no duplicate SQL. The `lead` tag is derived server-side from
  `event_type` (`insight_acknowledged → "acknowledged"`; everything
  else → `"learned"`), so the mobile UI never diverges from the
  Sprint-7/8 semantic.

The composer and the Pydantic response schemas live in
`apps/api/app/twin/portrait.py` and `apps/api/app/twin/schemas.py`
respectively. The endpoint lives on the existing twin router.

---

## 3. Data sources

| Section          | Service                                   | Filter                                                                 |
| ---------------- | ----------------------------------------- | ---------------------------------------------------------------------- |
| profile          | `TwinService.require_by_user`             | authenticated user                                                     |
| memory_summary   | direct SQL over `memories` (3 queries)    | twin_id + user_id + user_confirmed + superseded_by_memory_id IS NULL   |
| active_goals     | `GoalService.list_active_for_context`     | twin_id + status='active'                                              |
| recent_evolution | `EvolutionService.list_for_twin`          | twin_id + user_id                                                      |

Memory summary issues three bounded queries (COUNT, GROUP BY type,
ORDER BY importance LIMIT 5). The ORDER BY breaks ties on `id ASC`
for deterministic output.

---

## 4. API

New endpoint:

```
GET /v1/twin/portrait
Response: TwinPortraitOut
```

Response shape:
```json
{
  "profile": {
    "display_name": "Aurora",
    "style_preset": "warm",
    "style_notes": "Short replies in the morning.",
    "basic_profile": { "city": "Lisbon" }
  },
  "memory_summary": {
    "total_count": 3,
    "counts_by_type": {
      "FACT": 2, "PREFERENCE": 1, "EXPERIENCE": 0, "GOAL": 0
    },
    "top_memories": [
      { "id": "...", "type": "FACT", "importance": 0.9,
        "snippet": "Lives in Lisbon." }
    ]
  },
  "active_goals": [
    { "id": "...", "title": "Ship Sprint 9",
      "description": null, "priority": 2, "target_date": null }
  ],
  "recent_evolution": [
    { "id": "...", "event_type": "profile_confirmed",
      "summary": "profile.communication_style_notes updated",
      "created_at": "2026-10-08T00:00:00Z", "lead": "learned" }
  ]
}
```

HTTP 404 when the authenticated user has no Twin. Owner-scoped at the
endpoint boundary (`TwinServiceDep.require_by_user(user.user_id)`),
reinforced by the service-level filters and by the existing memories
RLS.

Existing endpoints are unchanged. The mid-session profile edit is
served by the existing `PATCH /v1/twin` without modification.

---

## 5. Mobile surfaces

| File                                              | Purpose                              |
| ------------------------------------------------- | ------------------------------------ |
| `apps/mobile/app/(main)/portrait/index.tsx`       | Portrait screen                      |
| `apps/mobile/app/(main)/profile/index.tsx`        | Profile edit screen (PATCH /v1/twin) |
| `apps/mobile/src/lib/profileForm.ts`              | Pure helpers for the edit form       |
| `apps/mobile/app/(main)/home.tsx`                 | New "Self-portrait" tile             |
| `apps/mobile/src/api/types.ts`                    | `TwinPortrait` + sub-types           |
| `apps/mobile/src/api/client.ts`                   | `api.getTwinPortrait`                |

Portrait copy preserves Sprint 7/8 conventions:
- Confirmed durable changes carry the lead "Your Twin learned …".
- Insight confirmations carry the lead "You acknowledged …" (Sprint 7
  founder decision #1: insight is acknowledgement, not identity
  mutation).

Error, loading, and empty states follow the pattern already in
Reflections, Memories, Evolution.

---

## 6. Privacy considerations

- Memory snippets are capped at 240 characters server-side. Longer
  content is truncated at a Python code-point boundary (`str` slicing
  is code-point-aware) and an ellipsis is appended.
- The endpoint's one structured log event (`twin.portrait.returned`)
  carries twin_id + counts + latency only. No memory content, no goal
  description, no profile value, no evolution summary.
- Rejected memory candidates have no `memories` row and therefore
  cannot leak into the portrait. Pending candidates also have no
  `memories` row — the same guarantee.
- Superseded memories are explicitly excluded by
  `superseded_by_memory_id IS NULL`. The portrait only exposes the
  Twin's *active* knowledge.
- Owner scoping is enforced at every service boundary the composer
  calls. The existing RLS policies on `memories`, `goals`, and
  `twin_evolution_events` remain the second line of defence.
- GETting the portrait is side-effect-free. It does NOT create an
  evolution event ("GET observed the portrait" would be a surveillance
  record and is explicitly out of scope).

---

## 7. Profile mutation path

Mid-session edits call the existing `PATCH /v1/twin` endpoint, which
is served by `TwinService.update(user_id, TwinProfilePatch)` — the
exact same path a Sprint-1 user-authored edit would take, and the
exact same path a confirmed Sprint-7 `profile_update` reflection
takes.

Nothing in Sprint 9 adds a new mutation path. Nothing in Sprint 9
lets the LLM mutate `TwinProfile`. The Sprint 1/7/8 invariant is
preserved:

```
LLM → ReflectionCandidate → user confirm → TwinService.update → DB
User (mobile edit) → PATCH /v1/twin → TwinService.update → DB
```

The profile edit screen enforces `communication_style_notes` ≤ 500
characters on the client as a usability guard (the backend already
caps at 2000). `basic_profile` values are coerced to strings on the
client (Sprint 9 brief) until the backend tightens that shape.

---

## 8. What the Self-Portrait does NOT do

- **No LLM call.** Pinned by `test_portrait_get_does_not_call_llm` —
  the test monkeypatches `MockProvider.generate_response` to raise and
  verifies the portrait endpoint still returns 200.
- **No narrative generation.** The portrait is deterministic
  composition. A memory snippet is the memory's own content,
  truncated to a known length. The summary is derived from stored
  IDs + the kind-of-change only.
- **No new persistence.** Zero new tables, zero schema changes.
- **No new migration.** The alembic head stays at `0006_evolving_twin_loop`.
- **No new mutation path.** The profile edit screen calls the
  existing `PATCH /v1/twin`.
- **No background task.** The portrait is composed synchronously in
  the request's own session.
- **No autonomous behavior.** No cron, no Redis, no scheduled refresh,
  no proactive push.
- **No evolution event on GET.** Observing the portrait never emits a
  `twin_evolution_events` row. Pinned by
  `test_portrait_get_does_not_create_evolution_event`.
- **No insight → Memory auto-promotion.** Sprint 7 Decision #1
  remains the contract.

---

## 9. Architectural invariants preserved

| Invariant                                                              | How Sprint 9 preserves it                                              |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| LLM never directly mutates `TwinProfile`                               | Portrait does not call the LLM at all; profile edit goes through `TwinService.update` which is the user-authored path. |
| Reflection requires explicit user confirmation                         | Portrait is read-only; it never proposes or applies a reflection.      |
| Memory confirmation remains explicit                                   | Portrait only shows `user_confirmed=TRUE` rows; rejected and pending candidates are structurally invisible. |
| Memory supersession remains reversible                                 | Portrait excludes `superseded_by_memory_id IS NOT NULL` rows but the memory list keeps them for un-supersede. |
| Rejected reflections create no evolution event                         | Portrait does not touch the reflection path.                           |
| Chat failure isolation                                                 | Portrait is a GET on its own session; it cannot affect chat.           |
| Owner scoping                                                          | Enforced at `TwinService.require_by_user` + at every service query the composer calls. |
| RLS unchanged                                                          | No new tables, no new policies.                                        |
| No raw personal content in logs/telemetry                              | Only IDs + counts + latency logged by the endpoint.                     |
| No Redis / cron / scheduled autonomy                                   | None introduced.                                                       |

---

## 10. Where this lives in the repo

| Concern                             | Path                                               |
| ----------------------------------- | -------------------------------------------------- |
| Composer                            | `apps/api/app/twin/portrait.py`                    |
| Pydantic response schemas           | `apps/api/app/twin/schemas.py`                     |
| HTTP endpoint                       | `apps/api/app/api/v1/twin.py` (`GET /portrait`)    |
| Tests                               | `apps/api/tests/test_portrait.py`                  |
| Mobile types                        | `apps/mobile/src/api/types.ts`                     |
| Mobile client                       | `apps/mobile/src/api/client.ts`                    |
| Mobile portrait screen              | `apps/mobile/app/(main)/portrait/index.tsx`        |
| Mobile profile edit screen          | `apps/mobile/app/(main)/profile/index.tsx`         |
| Mobile profile form helpers         | `apps/mobile/src/lib/profileForm.ts`               |
| Mobile home tile                    | `apps/mobile/app/(main)/home.tsx`                  |
| Mobile tests                        | `apps/mobile/__tests__/profile-form.test.ts`, `api-types.test.ts` |
