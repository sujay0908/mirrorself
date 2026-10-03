# Memory Retrieval

> **The avatar is the interface; the evolving personal intelligence is the product.**

Sprint 3 adds the retrieval half of the memory system. Sprint 2 built
confirmed memories and provenance. Sprint 3 makes the Twin **use** those
memories when it responds — without ever letting retrieval failure break
chat, and without ever letting retrieval mutate the stable `TwinProfile`.

---

## Pipeline

```
User message
    │
    ▼
retrieve relevant confirmed memories ─────── best-effort; failure returns []
    │
    ▼
build TwinContext (profile + memories + recent turns + provenance_map)
    │
    ▼
LLM provider (chat)
    │
    ▼
persist user + twin messages
    │
    ▼
enqueue background extraction (Sprint 2, unchanged)
```

The pipeline is wired in `apps/api/app/conversation/service.py::ConversationService.post_message`. Retrieval is bracketed by `_retrieve_safely` — a double-wrapped try/except so an exception never surfaces as a failed chat response. The resulting `TwinContext` is handed to `apps/api/app/conversation/pipeline.py::run_pipeline`, which turns it into the LLM message sequence.

---

## Storage (D1 + D2 + D3)

### `memory_embeddings` table

Added in migration `0003_memory_retrieval`:

- A new `embedding_vector vector(1536)` **nullable** column (type `pgvector.Vector(1536)` on Postgres, `JSON` on SQLite via `app.db.types.VectorColumn`).
- An IVFFlat index on `embedding_vector` with cosine distance operator class.
- The Sprint 2 `vector JSON` column is **retained** for one release so existing rows remain readable. A follow-up migration will drop it after a dedicated backfill job repopulates `embedding_vector`.

### pgvector enablement (D1-c)

The migration runs `CREATE EXTENSION IF NOT EXISTS vector` at the top of `upgrade()`. If that fails (common on Supabase projects where the extension has not been enabled via Database → Extensions → vector) the migration aborts with a clear message naming the manual SQL. No silent fallback — the migration will not create a half-baked state.

Downgrade drops the index and the vector column, but **does not** drop the extension (other objects may depend on it).

### Dimension pinning (D2-a)

`vector(1536)` matches OpenAI `text-embedding-3-small` native output and the current `.env.example` `EMBEDDING_DIMENSIONS=1536`. Changing the dimension requires a new migration. The constant lives in `app.memory.models.SEMANTIC_EMBEDDING_DIM` for cross-checking from the service layer.

### Mock vector handling (D3-b)

Sprint 2 stored vectors as JSON hashes derived from the mock embedding provider. These are not semantic. The Sprint 3 migration:

- adds the new column as **NULL** for all existing rows (no automatic conversion of mock hashes);
- the memory service writes to `embedding_vector` ONLY when the embedding provider returns a vector matching `SEMANTIC_EMBEDDING_DIM` — other-dimension providers still populate the legacy JSON column so no memory is lost;
- the retriever **skips** rows where `embedding_vector IS NULL`. Those memories are still visible via `GET /v1/memories`, still carry provenance, and will be re-embedded by a Sprint 3.1+ backfill job.

---

## Retrieval service

`apps/api/app/memory/retrieval.py::MemoryRetriever.retrieve(twin, query_text, limit, types)` → `RetrievalResult`.

```python
class RetrievalResult:
    items: list[RetrievedMemory]
    metadata: dict[str, Any]   # duration_ms, memories_considered,
                               # memories_returned, provider, twin_id
    error: str | None          # None on happy path
```

Guardrails:

- **Hard limit cap**: `MAX_LIMIT = 24`. Callers can ask for fewer, never more.
- **Ownership scope**: the retriever only accepts an in-process `Twin` ORM instance. It is impossible to call this API with a Twin resolved from any user other than the authenticated one, because the service layer resolves `Twin` via `TwinService.require_by_user(current_user.user_id)`.
- **Confirmation filter**: `WHERE Memory.user_confirmed IS TRUE`. Pending and rejected candidates are not reachable.
- **Null vector filter**: `WHERE MemoryEmbedding.embedding_vector IS NOT NULL`. See D3-b.
- **Never raises**: every exception path returns `RetrievalResult(error=...)`.

Dialect handling: on Postgres the retriever uses pgvector's `<=>` cosine-distance operator for ANN-friendly ordering, then re-scores with the ranking policy. On SQLite (tests) it loads the candidate rows and computes cosine in Python. The two produce the same ordering so test assertions match production.

---

## Ranking formula

A pure function in `apps/api/app/memory/ranking.py`:

```
score = w_sim  · similarity_01
      + w_imp  · importance
      + w_conf · confidence
      + w_rec  · recency_decay(now − last_touch, half_life=30d)
      − w_stale · stale_penalty(now − last_confirmed_at, threshold=180d)
```

Where:

- `similarity_01 = (cosine_similarity + 1) / 2` — maps cosine from [−1, 1] to [0, 1] for the weighted sum.
- `recency_decay(Δ, h) = exp(−ln 2 · Δ_days / h)` — 1.0 at `now`, 0.5 after one half-life.
- `stale_penalty(Δ, t) = min(1.0, Δ_days / t)` — 0 until the threshold, linear ramp to 1.0; 0 for never-confirmed memories.

Default weights (`DEFAULT_RANKING_WEIGHTS`):

| Weight | Value |
|---|---|
| `w_sim` | 1.0 |
| `w_imp` | 0.4 |
| `w_conf` | 0.2 |
| `w_rec` | 0.2 |
| `w_stale` | 0.3 |
| `recency_half_life_days` | 30.0 |
| `stale_threshold_days` | 180.0 |

The weights are frozen by `test_default_weights_frozen` — changing them is intentional and requires a doc update.

Determinism: identical inputs produce identical output. Tie-break is the memory_id string so dict ordering never affects results.

---

## Context builder

`apps/api/app/memory/context.py::ContextBuilder` → `TwinContext`.

The context is deterministic and token-budgeted via `ContextBudget`:

| Section | Default budget |
|---|---|
| `max_memories` | 8 |
| `max_history_turns` | 6 |
| `max_memory_content_chars` | 500 |
| `max_turn_content_chars` | 1500 |

Each retrieved memory is injected into the system prompt as:

```
<confirmed_memory id=<short> type=<FACT|PREFERENCE|EXPERIENCE|GOAL>>
<content>
</confirmed_memory>
```

- `<short>` is the first UUID segment (8 hex chars). The LLM never sees the full memory UUID. The `TwinContext.provenance_map` holds the short → full mapping for debugging and "why does my Twin know this?" answers; it is not sent to the LLM.
- Conversation history is appended in chronological order, bounded, with `system` turns excluded.
- `TwinProfile` is read-only in this module. The invariant is unit-tested (`test_builder_never_mutates_profile`).

---

## Chat integration

In `ConversationService.post_message`:

1. Persist the user message.
2. `_retrieve_safely(twin, user_content)` → `RetrievalResult` (never raises).
3. `ContextBuilder.build(twin, retrieved, history)` → `TwinContext`.
4. `run_pipeline(context, user_content, provider)` → `LLMResponse`.
5. Persist twin message with `metadata_json.retrieval = { ok, error, memories_returned, memory_ids }` — the audit trail for what the LLM saw this turn.
6. Enqueue Sprint 2 extraction task (unchanged).

Failure cases, all exercised by `test_retrieval_failure_does_not_fail_chat`:

- Embedding provider raises → `RetrievalResult(error="embedding_provider_error:...")`, chat continues with empty memories.
- DB query raises → `RetrievalResult(error="query_error:...")`, chat continues with empty memories.
- Retriever itself raises unexpectedly → service-level try/except catches, logs with IDs only, chat continues with empty memories.

---

## Provenance

Preserved end-to-end:

1. Sprint 2 confirmation creates a `MemorySource` row referencing the originating conversation and message. Not changed.
2. Retrieval loads sources via `selectinload(Memory.sources)` so each `RetrievedMemory` carries the originals.
3. The context builder keeps a `provenance_map: {short_id: memory_id}` so an operator can trace any `<confirmed_memory id=X>` block back to the DB row — which, through `MemorySource`, points to the originating conversation and message.
4. The twin message's `metadata_json.retrieval.memory_ids` records which memories were used at request time.

Together: given a twin reply, we can enumerate the memories it saw and, for each memory, the message that produced it.

---

## Observability

Structured events emitted (never user content):

| Event | Fields |
|---|---|
| `memory.retrieval.ok` | duration_ms, memories_considered, memories_returned, limit, types, twin_id, provider |
| `memory.retrieval.failed` | reason, twin_id, conversation_id, metadata |
| `memory.retrieval.skipped` | reason, twin_id, conversation_id |
| `memory.retrieval.unhandled` | error (exception class), twin_id, conversation_id |
| `conversation.message.persisted` | ... retrieval_ok, memories_used (added in Sprint 3) |

Safety guard in test `test_retrieval_failure_does_not_fail_chat`: a unique nonce injected into the user message is asserted absent from every emitted event.

---

## Security / ownership

Covered by:

- `test_cross_user_and_cross_twin_isolation` — User B cannot retrieve User A's memories.
- Service-layer `TwinService.require_by_user(auth.user_id)` resolution — the retriever never receives a Twin from another user.
- RLS policies (`infra/supabase/policies.sql`) scope `memories` and `memory_embeddings` by `twin_id ∈ (twins owned by auth.uid())`. The RLS is a second line of defence; the Python service enforces ownership first.

---

## Limitations (acknowledged, deferred)

1. **No backfill job yet.** Sprint 2 mock rows and any provider-failure rows have `embedding_vector = NULL` and are skipped by retrieval. A Sprint 3.1 CLI/endpoint re-embeds them on demand.
2. **IVFFlat lists = 100.** Fine for small corpora; tune up as the corpus grows (Postgres advice: ~√N).
3. **No HNSW index.** IVFFlat is simpler and sufficient for Sprint 3; HNSW is a later optimisation.
4. **No deduplication yet.** Two confirmations of near-identical content yield two memories. See Sprint 3.1.
5. **No cross-twin search.** By design.
6. **No streaming retrieval UI.** Beyond Sprint 3 scope.
7. **No LLM-side citations.** The prompt uses `<confirmed_memory>` tags; whether the model attributes which memory it used is up to the LLM.

---

## Future improvements

- Dedicated backfill endpoint / job to populate `embedding_vector` for legacy rows (Sprint 3.1).
- Switch to HNSW index once corpus exceeds ~100k rows.
- Introduce an `EXTRACTION_LLM_PROVIDER` separate from `LLM_PROVIDER` for cost tuning (Sprint 3.1).
- Deduplication at candidate confirmation: cosine-similarity match against existing memories above threshold → merge with provenance.
- Memory drawer in the mobile app (Sprint 3.1).
- Reflection loop that proposes profile updates (Sprint 4).
