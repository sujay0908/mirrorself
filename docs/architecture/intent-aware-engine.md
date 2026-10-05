# Intent-Aware Twin Engine (Sprint 6)

> **The avatar is the interface; the evolving personal intelligence is the product.**

Sprint 6 puts a single new stage at the front of the Sprint-3/4/5
conversation pipeline: *intent detection*. The Twin now decides what
kind of turn it is handling before it decides how much context to
assemble. Memory retrieval, goal retrieval, context building, prompt
rendering, failure isolation and the mobile contract are unchanged
from Sprint 5 — they are each tuned by one small, deterministic policy
object derived from the detected intent.

---

## Pipeline

```
User message
    │
    ▼
intent detection (rule-based, deterministic)
    │
    ▼
context policy (intent → weights → numeric limits)
    │
    ▼
retrieval (bounded by policy.memory_limit)        ─── never raises
    │
    ▼
active-goal loading (bounded by policy.goal_limit) ─── never raises
    │
    ▼
ContextBuilder.build(twin, memories, history, goals, budget)
    │
    ▼
LLM provider  (same `LLMProvider` protocol as before)
    │
    ▼
persist response + enqueue background extraction
```

The sprint changes exactly three insertion points — the two calls at
the top (intent + policy) and the fact that the retriever and goal
service now take a per-turn `limit` instead of relying on hard-coded
defaults. Everything downstream — the LLM provider, the memory
candidate pipeline, the mobile API contract, authentication, migrations
— is untouched.

---

## Vocabulary

| Intent | Meaning |
|---|---|
| `THINK` | The user is weighing something — "trade-offs", "should I…", "wondering if…" |
| `LEARN` | The user is asking the Twin to explain, teach, or answer a how/what/why question |
| `PLAN` | Planning or preparing — "plan my week", "roadmap", "prep for X" |
| `REFLECT` | Looking back — "in hindsight", "I realized", "lessons learned" |
| `TALK` | Casual back-and-forth — greetings, acknowledgements, short banter |
| `TASK` | Imperative — "write", "draft", "summarise", "translate", "refactor" |
| `UNKNOWN` | The detector could not confidently resolve any of the above |

The enum lives in `app/conversation/intent.py` and is `StrEnum` so the
value serialises directly to JSON for the audit trail.

---

## Intent detection

`app/conversation/intent.py`:

- `IntentResult(intent, confidence, reason, metadata)` is what the
  detector returns. `confidence` is a coarse band (0.0 / 0.4 / 0.7 /
  0.9) — not a probability, a stable ordering signal for the audit
  log. `reason` is a short machine-readable tag such as `"phrase:plan"`
  or `"fallback:empty_message"` and never carries user content.
- `IntentDetector` is a `Protocol`. The only concrete shipped
  implementation is `RuleBasedIntentDetector` — a deterministic,
  pure, regex-based matcher explicitly documented as a scaffold, not
  a classifier. A later LLM-backed detector can slot in without
  touching callers.
- `detect_intent_safely(detector, message)` wraps the call in a
  belt-and-braces try/except. The chat path uses it; a buggy future
  detector cannot fail a chat turn.
- The rule-based detector:
  - never raises
  - is a pure function (no I/O, no DB, no provider calls, no logging
    of user content)
  - gives the same message the same result every time
  - falls through to `TALK` for short unmatched messages and to
    `UNKNOWN` for longer unmatched messages, so the audit layer can
    see when the detector is uncertain
- Explicitly **not** a semantic understanding system. The precedence
  of rules (REFLECT before PLAN; verb-anchored TASK before keyword
  THINK) is documented in-file.

---

## Context policy

`app/conversation/policy.py`:

- `ContextWeight` enum: `NONE / LOW / MEDIUM / HIGH` (IntEnum so
  values dump straight into `metadata_json.policy.weights`).
- `ContextWeights` holds coarse per-source weights (memories / goals /
  conversation).
- `ContextPolicy` resolves those weights to numeric limits the rest of
  the pipeline already understands: `memory_limit`, `goal_limit`,
  `history_turns`, plus a `context_budget()` projection into the
  Sprint-5 `ContextBudget` dataclass.
- `policy_for(intent)` is a pure deterministic lookup. An unknown
  intent falls through to `Intent.UNKNOWN`'s row rather than raising.

The Sprint-6 brief's qualitative weights map to the shipped table:

| Intent | memories | goals | conversation | memory_limit | goal_limit | history_turns |
|---|---|---|---|---:|---:|---:|
| THINK | HIGH | MEDIUM | HIGH | 8 | 2 | 6 |
| LEARN | LOW | LOW | HIGH | 3 | 1 | 6 |
| PLAN | MEDIUM | HIGH | HIGH | 6 | 3 | 6 |
| REFLECT | HIGH | MEDIUM | HIGH | 8 | 2 | 6 |
| TALK | MEDIUM | LOW | HIGH | 6 | 1 | 6 |
| TASK | MEDIUM | HIGH | HIGH | 6 | 3 | 6 |
| UNKNOWN | MEDIUM | MEDIUM | MEDIUM | 6 | 2 | 4 |

Three hard caps the table respects (asserted by
`test_context_policy.py`):

- `memory_limit  ≤ MemoryRetriever.MAX_LIMIT (24)`
- `goal_limit    ≤ ConversationService._MAX_ACTIVE_GOALS_IN_CONTEXT (3)`
- `history_turns ≤ ContextBudget().max_history_turns (6)`

---

## TwinState — the Sprint-6 boundary

`app/conversation/state.py` adds the smallest `TwinState` abstraction
needed for Sprint 6. The dataclass carries the detected intent + the
resolved policy forward from `ConversationService.post_message` into
the pipeline and into `metadata_json.twin_state`. It is explicitly:

- **ephemeral**: lives for the duration of one chat turn and is NOT
  persisted anywhere;
- **not emotional state**: nothing here claims to represent mood or
  affect, and the file's docstring says so verbatim;
- **not a memory**: nothing here feeds the memory candidate
  pipeline;
- **not profile mutation**: `TwinProfile` is untouched by this module
  and by every code path reading `TwinState`.

A future emotional-state subsystem, if the product ever introduces
one, will live in its own module with its own persistence and
confirmation policy; this file is explicitly not that place.

---

## Prompt integration

`app/conversation/prompt.py::render_system_prompt(context, twin_state)`:

- When a `TwinState` is passed in, a single line is added after the
  identity block: `What this turn is about: <plain-english label>.`
- The label is a human-readable description such as
  "reflecting on the past" or "casual conversation". The raw enum
  (`REFLECT`, `TALK`) is never rendered, so the LLM cannot echo an
  internal token back to the user.
- The confidence number and the detector's `reason` tag are also
  never rendered — they live in the audit trail only.

`TwinContext.to_system_prompt(twin_state)` accepts the optional
argument and forwards to the renderer. The dataclass stays as pure
data; rendering remains a separate pure function per the Sprint-5
contract.

---

## Failure isolation

Every failure branch is covered by an explicit test in
`test_sprint6_intent_engine.py` and preserves the Sprint-5 invariants:

| Failure | Outcome |
|---|---|
| Intent detector raises | Chat returns 201. `twin_state.intent == "UNKNOWN"`, `intent_reason` starts with `error:`. Policy for UNKNOWN is applied; the rest of the pipeline runs as normal. |
| `policy_for` raises | Policy falls back to `policy_for(Intent.UNKNOWN)`. Chat returns 201. |
| Memory retrieval raises | Chat returns 201. `retrieval.ok=False`. The intent and policy are still recorded on the message. |
| Goal service raises | Chat returns 201. `goals_context.ok=False`. The intent and policy are still recorded. |
| LLM provider raises | Returns 500 via the registered exception handler. No partial twin message is persisted. (Unchanged from Sprint 5.) |

A `limit` of 0 produced by the policy — which no row currently uses
but which is reachable if the weights are tuned down — short-circuits
retrieval and goal loading to empty results instead of calling the
providers at all.

---

## Observability

Structured events emitted (IDs and counts only; never user content):

| Event | Fields |
|---|---|
| `intent.detection.unknown` | reason, twin_id, conversation_id |
| `intent.detection.unhandled` | error, twin_id, conversation_id |
| `intent.policy.unhandled` | error, twin_id, conversation_id |
| `memory.retrieval.skipped` | reason (`policy_memory_zero` is new) |
| `goals.context.skipped` | reason (`policy_goals_zero` is new) |
| `conversation.message.persisted` | …Sprint-5 fields… plus `intent`, `intent_confidence`, `intent_reason`, `memory_limit`, `goal_limit`, `history_turns` |

`metadata_json.twin_state` on each twin message carries the audit
trail:

```json
{
  "intent": "PLAN",
  "intent_confidence": 0.9,
  "intent_reason": "phrase:plan",
  "policy": {
    "intent": "PLAN",
    "weights": {"memories": 2, "goals": 3, "conversation": 3},
    "limits":  {"memories": 6, "goals": 3, "history_turns": 6}
  }
}
```

---

## Tests

49 new tests. Full suite is **184 passed**.

| File | Count | Purpose |
|---|---:|---|
| `test_intent_detector.py` | 21 | Vocabulary coverage, edge cases, determinism, rule precedence, async wrapper, failure isolation, default-detector guard |
| `test_context_policy.py` | 15 | Every intent has a row, qualitative weights match the brief, hard caps respected, budget projection, JSON-safe metadata, determinism |
| `test_sprint6_intent_engine.py` | 13 | Intent → prompt label, policy → retrieval/goal/history limits, memory still reaches prompt, failure isolation for intent / retrieval / goals, profile safety, cross-user isolation |

Three Sprint-4/5 cap-at-3 tests had their user message changed to
PLAN-triggering phrasing so the invariant they always enforced (goals
capped at 3 per prompt) continues to hold under the new policy. No
test was weakened to obtain green CI.

---

## What is intentionally NOT implemented (Sprint 6)

- **Semantic / LLM-backed intent detection.** The shipped detector is
  deterministic regex. The `IntentDetector` protocol is the insertion
  point for a later model-backed implementation.
- **Emotional state.** `TwinState` is not that; see the file's
  docstring.
- **Reflection candidates / goal candidates.** The pre-Sprint-5 audit
  flagged these as Sprint 6+ candidates; Sprint 6 keeps its scope tight.
- **Multi-intent / mixed-intent handling.** Each turn resolves to one
  intent; a confident short message with multiple phrasings uses rule
  precedence rather than returning a list.
- **A user-facing intent surface.** Mobile is unchanged. The intent is
  an audit field, not a product affordance.
- **Any new provider contract.** `LLMProvider` and `EmbeddingProvider`
  are untouched.

---

## File map

New:
- `apps/api/app/conversation/intent.py`
- `apps/api/app/conversation/policy.py`
- `apps/api/app/conversation/state.py`
- `apps/api/tests/test_intent_detector.py`
- `apps/api/tests/test_context_policy.py`
- `apps/api/tests/test_sprint6_intent_engine.py`
- `docs/architecture/intent-aware-engine.md` (this document)

Modified:
- `apps/api/app/api/deps.py` — wire `intent_detector_dep` into
  `conversation_service_dep`
- `apps/api/app/conversation/service.py` — call intent + policy before
  retrieval + goals; thread `limit` through; add `twin_state` to the
  twin message's `metadata_json`; log the new audit fields
- `apps/api/app/conversation/pipeline.py` — accept optional
  `TwinState`
- `apps/api/app/conversation/prompt.py` — render the human-readable
  intent hint
- `apps/api/app/memory/context.py` — `to_system_prompt(twin_state)`
  pass-through; `ContextBuilder.build(budget=...)` per-call override
- `apps/api/tests/test_goal_context_integration.py` + two others —
  swap to PLAN-triggering phrasing to keep the cap-at-3 invariant
  verifiable under the new policy
