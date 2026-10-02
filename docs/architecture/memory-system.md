# Memory System

> **The avatar is the interface; the evolving personal intelligence is the product.**

The memory system is the twin's long-term substrate. It is deliberately
separated from `TwinProfile` — the identity of the twin — so that transient
experiences never silently mutate stable characteristics.

**Sprint 2 status.** The foundation (`memories`, `memory_sources`,
`memory_embeddings`, `memory_candidates`) is implemented and tested. The
response pipeline enqueues candidate extraction as a background task after
every chat turn; candidates persist with `status='pending'` and surface
through `GET /v1/memory-candidates`. Confirming a candidate creates a
`Memory` + `MemorySource` in one transaction; embedding attach is
best-effort and failures never lose the memory. **Retrieval, reflection,
and consolidation remain Sprint 3+.** The vector column stores embeddings
as JSON for now — a Sprint 3 migration swaps the Postgres column for
`pgvector(N)` once the production target dimension is pinned.

---

## Categories

### MVP categories

| Category | What it holds | Example |
|---|---|---|
| `FACT` | Verifiable statements about the user or their world. | "I live in Bengaluru." |
| `PREFERENCE` | Stated likes/dislikes and behavioural preferences. | "I prefer terse replies before coffee." |
| `EXPERIENCE` | Episodic events with time and context. | "Presented the pgvector talk at the meetup on 2026-08-14." |
| `GOAL` | User-declared intentions with a target. | "Ship the MVP by end of Q4." (Goals also live in the `goals` table; the memory row is a durable copy for retrieval.) |

### Roadmap categories (not built in MVP)

| Category | What it holds |
|---|---|
| `BEHAVIOR` | Observed recurring behaviour, inferred from repeated turns. |
| `RELATIONSHIP` | Structured facts about people in the user's life. |
| `EMOTION` | Salient emotional events, distinct from short-term state. |
| `DECISION` | Explicit decisions and their rationale. |
| `REFLECTION` | Twin-generated syntheses across many memories. |

Adding a category is a schema decision: it needs a retrieval strategy, a
scoring rule, and a confirmation policy before it can ship.

---

## The `Memory` row

```
memories
─────────
id                    uuid, pk
user_id               uuid, fk users.id, RLS
twin_id               uuid, fk twins.id
type                  text ∈ {FACT, PREFERENCE, EXPERIENCE, GOAL, ...}
content               text                    -- one to three sentences
source                text ∈ {conversation, user_edit, reflection, import}
source_message_id     uuid, nullable, fk messages.id
confidence            float 0.0-1.0
importance            float 0.0-1.0
sensitive             bool
user_confirmed        bool                    -- false = shown as "unconfirmed"
created_at            timestamptz
updated_at            timestamptz
last_confirmed_at     timestamptz, nullable
last_used_at          timestamptz, nullable   -- updated on retrieval
retrieval_count       int, default 0
metadata              jsonb                   -- freeform, small
deleted_at            timestamptz, nullable   -- hard delete on user request;
                                              -- this column exists only for
                                              -- delete-then-purge workflows
```

Companion table:

```
memory_embeddings
─────────
memory_id             uuid, pk, fk memories.id ON DELETE CASCADE
embedding_model       text                    -- 'openai:text-embedding-3-small'
vector                vector(1536)            -- pgvector
created_at            timestamptz
```

Embeddings live in a separate table so a model swap does not require a
schema migration on `memories`. Multiple `memory_embeddings` rows per
memory are allowed during transitions.

RLS on both tables: `user_id = auth.uid()` (or the JWT claim used by the
FastAPI service role acting on the user's behalf).

---

## Retrieval

Retrieval is intent-aware (see [`twin-engine.md`](twin-engine.md) §2). The
scoring formula for a candidate memory `m` against a query embedding `q` is:

```
score(m, q) = w_sim  · cos(m.embedding, q)
            + w_imp  · m.importance
            + w_rec  · recency_decay(m.last_used_at)
            + w_conf · m.confidence
            - w_stale · staleness_penalty(m)
```

Sprint 1 weights (tuneable):
`w_sim=1.0, w_imp=0.4, w_rec=0.2, w_conf=0.2, w_stale=0.3`.

`recency_decay(t) = exp(-Δdays / 30)` and `staleness_penalty(m)` triggers
if `now - last_confirmed_at > 180 days` for `PREFERENCE` and `FACT` types.

**Hard cap: 24 memories returned from retrieval per turn.** This is the
single most important guardrail against prompt bloat.

---

## Confirmation loop

Memory writes fall into three lanes:

1. **Auto-persist** — `confidence ≥ 0.7`, not sensitive, not a
   preference-change contradicting an existing high-confidence row.
   Written directly to `memories` with `user_confirmed = false` and
   surfaced in the memory drawer.
2. **Pending confirmation** — sensitive, low-confidence, or contradicting
   a confirmed memory. Stored in `memory_candidates` with `status = pending`.
   The mobile app shows a card: "I noticed X. Should I remember this?".
   The user can confirm, reject, or edit.
3. **Silently dropped** — under confidence floor, or fails the privacy
   filter.

The confirmation UX is a first-class MVP requirement, not a Sprint 4
feature. Without it the user cannot see or steer what the twin knows.

---

## Deduplication and merging

When a candidate is a near-duplicate of an existing memory:

- `cos_sim ≥ 0.92` and same `type` → merge: bump `importance` (bounded),
  update `last_confirmed_at`, keep the older `content` unless the new one
  is materially longer or more specific.
- `cos_sim ∈ [0.85, 0.92)` → link (create a `related` metadata pointer),
  do not merge.

Merging is logged. The mobile app can surface merges in the memory drawer
history.

---

## Contradictions

When a new candidate contradicts an existing high-confidence memory of the
same type (e.g., "I now prefer detailed answers" vs a prior "I prefer
terse replies"):

1. Never overwrite silently.
2. Store the new candidate as `pending` with `status_reason = 'contradicts:<existing_id>'`.
3. Ask the user in the drawer: "You told me before you prefer terse
   replies. Has that changed?"
4. On confirmation, mark the old memory as superseded (`metadata.superseded_by = new_id`,
   `deleted_at = now()`) rather than hard-deleting; keep the row for
   audit until the user asks for a hard delete.

---

## Consolidation and reflection (post-MVP shape)

Sprint 2 ships a **reflection stub** that runs nightly and produces a
weekly digest — a summary memory of type `REFLECTION` (once the roadmap
category is opened) — but does **not** update `TwinProfile`.

The full consolidation loop, post-MVP, is:

1. Group memories by cluster (embedding cluster + type).
2. Detect repeating patterns (a preference stated three times across
   two weeks; a behaviour reflected in twenty messages).
3. Propose a profile update as a `pending` change on `twin_profiles`.
4. Ask the user to confirm before the profile mutates.

This is the mechanism by which learning can eventually shape identity —
gated by user consent every time.

---

## Emotional state, and why it is separate

```
emotional_states
─────────
id                    uuid, pk
user_id               uuid, fk
twin_id               uuid, fk
valence               float -1.0 to 1.0
arousal               float 0.0 to 1.0
dominant_affect       text, nullable
confidence            float
decayed_to            timestamptz            -- rolling window
metadata              jsonb
updated_at            timestamptz
```

`EmotionalState` is a rolling, decaying single row per user. It informs
tone in the current session. It **does not** feed the memory extractor.
It **does not** feed the profile.

The invariant "current state must not automatically become permanent
identity" is enforced by two mechanisms:

1. The extractor has no read access to `emotional_states`.
2. Profile updates only originate from confirmed reflection candidates,
   never from `emotional_states` directly.

---

## Deletion and export

- `DELETE /v1/memories/{id}` performs a hard delete. The row is removed;
  the embedding row cascades.
- `POST /v1/twins/{id}/forget-me` performs a bulk hard delete across
  `memories`, `memory_embeddings`, `memory_candidates`, `messages`,
  `conversations`, `goals`, `goal_events`, `reflections`,
  `emotional_states`, and `twin_profiles`. The `users` and `twins` rows
  remain by default; a follow-up account deletion removes them.
- `GET /v1/twins/{id}/export` returns a JSON archive of all rows above
  scoped to the user. The archive omits embedding vectors by default and
  includes them only if `?include_embeddings=true`.

Both endpoints are authenticated, rate-limited, and logged with sanitized
metadata (no content).

---

## Non-goals for memory in MVP

- No fine-tuning on memories.
- No cross-user memory sharing.
- No proactive memory notifications ("your twin has a new insight").
- No memory-sourced recommendations engine.
- No summarisation of long-term memory into "core beliefs" that mutate
  profile.

These are all reachable from this schema; none of them ship in Sprints 1–3.
