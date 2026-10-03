# Goals + Memory UX (Sprint 4)

> **The avatar is the interface; the evolving personal intelligence is the product.**

Sprint 4 adds first-class *goals* and surfaces *memory* to the user. The
Twin is no longer only a retrieval target — it carries forward what the
user is deliberately pursuing and shows the user, in their own device,
what it remembers and why.

Four product surfaces land in this sprint:

1. Memory Candidates — the Twin's proposed memories, approved/rejected.
2. Memories — the user's confirmed memory list, filtered by type.
3. Memory Detail — the content, inline edit, delete, and provenance
   ("Why does my Twin know this?").
4. Goals — list, create, detail with status transitions, and an
   append-only audit event trail.

Plus one in-chat affordance: tap-to-reveal citations under each twin
reply, showing the memories used and goals considered.

---

## Founder decisions carried into code

| Key | Decision |
|-----|----------|
| DF1 | New `Goal` entity (id, twin_id, title, description, target_date, priority, status, status_changed_at, metadata, timestamps) with status enum `{active, achieved, abandoned, paused}`. Append-only `GoalEvent`. No parent/child, no recurring. |
| DF2 | Keep the existing `GOAL` memory type AND the new Goal entity simultaneously. No silent conversion. |
| DF3 | No automatic memory deduplication in Sprint 4. |
| DF4 | `GET /v1/memories/{id}/provenance` returns source rows + a bounded (≤240 char) sanitized message snippet. Owner-scoped. |
| DF5 | In-chat citations are tap-to-reveal under each twin reply. |
| DF6 | Four mobile surfaces as listed above. |
| DF7 | Only `active` goals reach the TwinContext; `paused/achieved/abandoned` are excluded. |
| DF8 | At most 3 active goals per request, ordered by priority (1 highest) then recency, rendered under a separate `<active_goal>` tag. |

---

## Backend

### Models

`app/goal/models.py`:

- `Goal` — `twin_id` FK with `CASCADE`, `user_id` denormalised for RLS,
  `priority int CHECK 1..5`, `status varchar CHECK IN
  ('active','achieved','abandoned','paused')`, `status_changed_at`
  timestamp for the context tiebreaker.
- `GoalEvent` — append-only audit trail: `event_type` in
  `(created, updated, status_changed)`, with `from_status` /
  `to_status` populated only on status changes.
- Index `ix_goals_twin_status (twin_id, status)` so the active-goal
  context query scales with the twin's goal count.

### Migration `0004_goals`

Creates both tables with the CHECK constraints and the composite index.
`downgrade()` drops them cleanly. Verified against PostgreSQL 16 +
pgvector 0.6.0:

```
alembic upgrade head  → 0001 → 0002 → 0003 → 0004 ✔
alembic downgrade -1  → removes goal_events, goals ✔
alembic upgrade head  → re-adds them ✔
```

### Service layer policy

`app/goal/service.py::GoalService` enforces:

- **Ownership scope** on every read AND write. `_require_owned_goal`
  filters by `goal_id AND twin_id AND user_id`.
- **Status-transition policy** (service-level, not DB CHECK):

```
active     → achieved | abandoned | paused
paused     → active   | achieved  | abandoned
achieved   → (terminal)
abandoned  → (terminal)
```

  Any other transition raises `InvalidGoalStatusTransitionError` → HTTP
  409 `invalid_goal_status_transition`.

- **Audit events** are appended through `session.add(GoalEvent(...))`
  rather than `goal.events.append(...)` on the write paths that follow a
  fresh flush, to avoid async lazy-load of the collection.

- **Context ordering** (DF8): `list_active_for_context` returns
  `WHERE status = 'active' ORDER BY priority ASC, updated_at DESC, id ASC
  LIMIT 3`. Deterministic tiebreak on `id` makes the context
  reproducible across test runs.

### Context integration

`ConversationService.post_message` now calls `_load_active_goals_safely`
after retrieval. The method mirrors `_retrieve_safely`:

- Never raises. Exceptions become `(goals=[], ok=False, error="...")`
  and chat continues without goal context.
- Emits `goals.context.failed` with ids only on failure; never user
  content.

`ContextBuilder.build` accepts an `active_goals: list[Goal] | None`
parameter and renders each as a separate `<active_goal id=<short>
priority=<n> target_date=<date|none>>…</active_goal>` block. Memories
remain under `<confirmed_memory>` — a deliberate separation so the LLM
never confuses a filed fact with a pursued goal.

The twin message's `metadata_json` grows a `goals_context`
sibling to `retrieval`:

```json
{
  "retrieval":      { "ok": true, "memory_ids": [...] },
  "goals_context":  { "ok": true, "goal_ids": [...] }
}
```

Both subobjects are now exposed through `MessageOut.metadata_json`, so
the mobile app can render tap-to-reveal citations.

### Memory provenance

`GET /v1/memories/{id}/provenance` is backed by
`MemoryService.get_provenance`:

- Resolves the memory under the authenticated user's twin or returns
  404 (never 403 — don't leak existence).
- For each `MemorySource`, joins to `messages` through `conversations`
  under THIS twin only (belt-and-braces: the memory ownership check is
  authoritative, this layer still refuses to peek into another twin's
  conversation even if a bug surfaced one).
- If the source isn't a message or the message no longer exists, the
  snippet is `null`.
- Otherwise the snippet is the message content, truncated to
  `PROVENANCE_SNIPPET_MAX_CHARS = 240` with a trailing ellipsis and
  `source_snippet_truncated: true`.

### Observability

Structured events (never user content):

| Event | Fields |
|---|---|
| `goal.created` | twin_id, goal_id, priority |
| `goal.status_changed` | twin_id, goal_id, from_status, to_status |
| `goals.context.failed` | twin_id, conversation_id, error |
| `goals.context.skipped` | twin_id, conversation_id, reason |
| `conversation.message.persisted` | …, goals_ok, goals_used (new in Sprint 4) |

---

## Mobile

Four Expo-Router screens, all under `apps/mobile/app/(main)/`:

- `candidates/index.tsx` — pending memory candidates with
  Keep / Reject.
- `memories/index.tsx` — list with type filter and `Review` affordance
  linking to candidates.
- `memories/[id].tsx` — view, edit, delete, and the "Why does my Twin
  know this?" provenance panel with per-source snippet + "Open
  conversation" link.
- `goals/index.tsx`, `goals/new.tsx`, `goals/[id].tsx` — list,
  minimal create form, and detail with inline edit + legal-only status
  transition buttons.

The chat `MessageBubble` renders tap-to-reveal citations below each
twin reply when retrieval or goals_context returned ids. The predicate
is extracted to `src/lib/citations.ts::citationsFromMessage` so it is
unit-testable without a React Native renderer.

The home screen gains quick-link tiles for Goals, Memories and Review.

### Mobile types

`src/api/types.ts` grows:

- `Memory`, `MemorySource`, `MemoryCandidate`, `MemoryPatch`,
  `MemoryProvenance[Source]`
- `Goal`, `GoalCreateIn`, `GoalUpdateIn`, `GoalEvent`, `GoalStatus`,
  `GoalEventType`
- `Message.metadata_json: MessageMetadata` with `retrieval` +
  `goals_context` sub-objects

`src/api/client.ts` adds the matching endpoint wrappers.

---

## Tests

Backend (119 pytest tests total; 37 new in Sprint 4):

| File | Count |
|---|---|
| `test_goals.py` | 14 |
| `test_goal_context_builder.py` | 10 |
| `test_goal_context_integration.py` | 5 |
| `test_goal_context_failure_isolation.py` | 1 |
| `test_memory_provenance.py` | 6 |
| `test_sprint4_integration.py` | 1 |

Mobile (10 jest tests total; 9 new in Sprint 4):

| File | Count |
|---|---|
| `__tests__/api-types.test.ts` | 2 (compile-time + api shape) |
| `__tests__/citations.test.ts` | 8 |

Quality gates:

- `pytest`: 119/119 passing.
- `ruff check app tests alembic`: clean.
- `mypy app`: clean.
- `pnpm --filter @pat/mobile typecheck`: clean.
- `pnpm --filter @pat/mobile test`: 10/10 passing.
- Alembic migration upgrade/downgrade/upgrade: verified on PG 16 +
  pgvector 0.6.0.

---

## Limitations (acknowledged, deferred)

1. **No automatic memory dedup** (DF3). Confirming two near-identical
   candidates still yields two memories.
2. **No `GOAL` memory → Goal entity migration** (DF2). The two live
   side by side; the user can promote by hand later.
3. **Goal context is a HARD CAP of 3**. Multi-goal strategies get
   deferred to Sprint 5+.
4. **No notifications when the Twin proposes a memory.** The user has
   to open the Candidates screen to see pending items.
5. **No goal reminders** or target-date surfacing in chat.
6. **No analytics on which memories/goals the user keeps vs. rejects.**
7. **Mobile tests are logic-only.** A full RN-renderer test harness is
   deferred; the pure helpers in `src/lib/citations.ts` are covered.

## Future improvements

- Dedup proposal at candidate confirmation (Sprint 5).
- Goal reminders by target_date (Sprint 5).
- Promote a `GOAL` memory → Goal entity in one tap (Sprint 5).
- Full RN-renderer tests for the four mobile surfaces (Sprint 5).
- Rich conversation reference link under provenance snippet (jumps to
  the exact message, not just the conversation).
