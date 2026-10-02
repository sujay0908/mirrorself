# Twin Engine

> **The avatar is the interface; the evolving personal intelligence is the product.**

The Twin Engine is the request pipeline that turns a user message into a
personalised twin response, and turns that response into durable learning.
It is a directed graph of stages, each with a typed input, a typed output,
and no shared state beyond the `TwinContext` object passed through.

---

## Pipeline

```
User Message
    │
    ▼
┌──────────────────────┐
│ 1. Intent detection  │  short LLM call or classifier
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 2. Memory retrieval  │  pgvector kNN + metadata filters
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 3. Goal retrieval    │  active goals, filtered by intent
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 4. Current context   │  emotional state, session history,
│                      │  time-of-day, device signals
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 5. Twin context      │  assemble Profile + Memories + Goals +
│    builder           │  Emotional + Recent turns into a bounded
│                      │  prompt.
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 6. LLM provider      │  call `LLMProvider.complete(...)`
└──────────┬───────────┘
           ▼
      Twin Response  ──►  streamed to user
           │
           ▼
┌──────────────────────┐
│ 7. Memory candidate  │  post-response extraction
│    extraction        │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 8. Validation +      │  score, dedupe, safety, sensitivity
│    scoring           │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 9. Persistence /     │  either persist, or queue for user
│    confirmation      │  confirmation.
└──────────────────────┘
```

---

## Stage contracts

Each stage is a pure function against a growing `TwinContext`. Stages do
not import from each other. They read from and write to well-defined
fields on the context.

### 1. Intent detection

```python
def detect_intent(msg: UserMessage) -> Intent: ...
```

Buckets the message into a coarse intent: `chit_chat`, `information_recall`,
`goal_update`, `decision_help`, `reflection`, `preference_change`,
`sensitive_topic`, `unknown`. The intent tunes retrieval `k`, prompt
template, and memory extraction thresholds.

**Sprint 1 implementation:** a small LLM call with a fixed JSON schema.
**Later:** distilled classifier for latency.

### 2. Memory retrieval

```python
def retrieve_memories(intent: Intent, msg: UserMessage, user_id: UUID) -> list[Memory]: ...
```

- Embed the user message using `EmbeddingProvider.embed(msg.text)`.
- Query `memory_embeddings` with cosine similarity, filtered by `user_id`
  and by memory type according to intent.
- Take top-`k` (default 8; `information_recall` → 12; `chit_chat` → 4).
- Re-rank by `importance × recency_decay × similarity`.
- Attach source `message_id` and timestamp for citation.

**Guardrail:** never return more than 24 memories from this stage, no
matter what the intent is. This is the mechanism that prevents whole-store
injection.

### 3. Goal retrieval

```python
def retrieve_goals(intent: Intent, user_id: UUID) -> list[Goal]: ...
```

- Active goals only, sorted by `updated_at` desc.
- Filter by tags if the intent implies a domain.
- Cap at 5 goals in the prompt.
- Attach the most recent `GoalEvent` per goal for freshness.

### 4. Current context

```python
def build_current_context(user_id: UUID, session: Session) -> CurrentContext: ...
```

- Load latest `EmotionalState` (single row, decayed).
- Load the last N conversation messages (default 6).
- Load time-of-day and, if the client sent it, timezone.
- **No profile promotion happens here.** Emotional state is read-only for
  this stage.

### 5. Twin context builder

```python
def build_twin_context(
    profile: TwinProfile,
    memories: list[Memory],
    goals: list[Goal],
    current: CurrentContext,
    intent: Intent,
) -> TwinContext: ...
```

Assembles the final structured context object with strict token budgets:

| Section | Token budget (Sprint 1) | Notes |
|---|---|---|
| Profile summary | 500 | Rendered from the `TwinProfile` row. |
| Personality traits | 200 | Compact bullet list. |
| Retrieved memories | 1500 | Prioritised by score. |
| Active goals | 300 | Title + latest event. |
| Emotional state | 100 | One sentence. |
| Recent turns | 1500 | Last 6 messages. |
| System instructions | 800 | From `packages/prompt-templates/`. |

Overflow is dropped in order of ascending score. The builder logs which
items were dropped and why.

### 6. LLM provider

```python
class LLMProvider(Protocol):
    async def complete(self, prompt: Prompt, options: CompletionOptions) -> Completion: ...
    async def stream(self, prompt: Prompt, options: CompletionOptions) -> AsyncIterator[str]: ...

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[Vector]: ...
```

- One registry, one entry point.
- `ClaudeProvider`, `OpenAIProvider`, `LocalProvider` (post-MVP), and
  `MockProvider` all implement these.
- No provider-specific parameters leak into stages. Provider-specific tuning
  lives in the provider module.

### 7. Memory candidate extraction

Runs **after** the response is returned to the user, on a background task.

```python
def extract_candidates(turn: ConversationTurn) -> list[MemoryCandidate]: ...
```

Uses a structured-output LLM call with a strict JSON schema:

```json
{
  "candidates": [
    {
      "type": "FACT|PREFERENCE|EXPERIENCE|GOAL",
      "content": "...",
      "confidence": 0.0-1.0,
      "importance": 0.0-1.0,
      "user_confirmation_required": true|false,
      "source_message_id": "...",
      "sensitive": true|false,
      "rationale": "..."
    }
  ]
}
```

Candidates come with a `rationale` for observability but the rationale is
not persisted with the memory row.

### 8. Validation and scoring

Every candidate passes through:

- **Deduplication:** kNN against existing memories of the same type;
  similarity > 0.92 → merge (update `last_confirmed_at`, incrementally
  raise `importance`).
- **Safety filter:** the privacy rules from `product-principles.md` §2 are
  applied here — payment card numbers, government IDs, and health inferences
  the user did not state are dropped.
- **Sensitivity flag:** anything the extractor flagged as sensitive, or
  anything under the "never store without confirmation" list, is diverted
  to a **pending memory queue** rather than persisted.
- **Confidence gate:** candidates below `confidence < 0.5` are dropped
  silently; those in `[0.5, 0.7)` are stored with `user_confirmed = false`
  and surfaced in the memory drawer as "unconfirmed".

### 9. Persistence

- Persisted rows go into `memories` and `memory_embeddings` in the same
  transaction.
- Pending confirmations are stored in a `memory_candidates` table with a
  `status ∈ {pending, confirmed, rejected, expired}` column.
- The mobile app polls (or subscribes to) pending candidates and shows the
  user "I noticed X — want me to remember this?" cards.

---

## `TwinContext` object

The single struct threaded through every stage:

```python
@dataclass
class TwinContext:
    user_id: UUID
    twin_id: UUID
    session_id: UUID
    incoming_message: UserMessage

    intent: Intent | None = None
    profile: TwinProfile | None = None
    memories: list[Memory] = field(default_factory=list)
    goals: list[Goal] = field(default_factory=list)
    current: CurrentContext | None = None

    prompt: Prompt | None = None
    completion: Completion | None = None

    trace: TraceRecorder = field(default_factory=TraceRecorder)
```

Every stage mutates only its own field and calls `trace.stage(name, meta)`.
The trace record is what powers observability (§9 of principles).

---

## Failure modes and fallbacks

| Stage | Failure | Fallback |
|---|---|---|
| Intent | LLM error / timeout | Default to `unknown`; use conservative retrieval. |
| Memory retrieval | pgvector error | Return an empty list; log; degrade tone gracefully. |
| Goal retrieval | DB error | Return empty; degrade. |
| LLM provider | Provider outage | Try next provider in registry; if none, return a graceful "I'm having trouble reaching my mind right now." |
| Extraction | LLM error | Silently skip persistence for this turn; do not fail the user response. |
| Persistence | DB error | Enqueue for retry; log. Never fail the user response. |

The user's chat turn must succeed even if learning fails. Learning failing
is a background problem; conversation failing is a product problem.

---

## Latency budget (Sprint 1 target)

- Intent detection: ≤ 250 ms (or skipped via classifier post-MVP).
- Memory retrieval: ≤ 100 ms (pgvector).
- Goal + current context: ≤ 50 ms.
- LLM streaming first token: ≤ 1.5 s.
- End-of-response extraction: async, up to 5 s off the critical path.

Time to first token is what the user feels. Everything else can be async.
