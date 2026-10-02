# Product & Engineering Principles

> **The avatar is the interface; the evolving personal intelligence is the product.**

These principles are load-bearing. Any pull request that violates one requires an
explicit, written exception in the PR description and sign-off from the architect.

---

## 1. Model-agnostic AI architecture

No module outside `apps/api/llm/providers/` may import a vendor SDK. Every LLM
interaction goes through the `LLMProvider` interface (`complete`, `embed`, `stream`).
Providers are selected at runtime from configuration. Prompts, temperature, token
budgets, and safety settings are provider-neutral parameters.

*Why:* the model market changes monthly. Local and edge models are on the DT 4.0
roadmap (Gap G3 in Sujay's survey). Being provider-agnostic is the difference
between a two-hour swap and a two-week rewrite.

## 2. Privacy-first design

The twin holds intimate data. Treat it that way.

- All user data is scoped by `user_id` and enforced by Postgres row-level security.
- Export ("give me everything you know about me") and delete ("forget me") are
  first-class API endpoints, not afterthoughts.
- Server-side logs never contain raw memory content — only IDs and structured
  metadata.
- Embedding vectors are treated as personal data.

## 3. User control over memory

Every stored memory is:

- **Visible** — the user can see the full list, filtered and searchable.
- **Editable** — content and importance can be changed.
- **Revocable** — a delete is a hard delete, not a soft flag.
- **Attributed** — the source (message ID, timestamp) is retained.
- **Confirmable** — sensitive or high-impact memories require explicit user confirmation
  before they influence future turns.

## 4. Explicit separation of profile and memory

`TwinProfile` is *who the user is* at a stable, months-scale level:
values, communication style, long-standing preferences, relationships.

`Memory` is *what happened, what was said, what was decided*: episodic facts,
short-term preferences, in-flight experiences.

The two tables have different write paths, different retention rules, and different
retrieval strategies. A memory can propose a profile update; the profile never
silently mutates from a single memory.

## 5. Current state must not automatically become permanent identity

`EmotionalState` is a rolling, decaying vector of near-term affect. It informs
tone and empathy in the current session. It **cannot** write to `TwinProfile`
or `PersonalityTrait` without a confirmed, repeated pattern surfaced by
reflection (see `docs/architecture/memory-system.md`, "Consolidation loop").

A user who has a bad Tuesday is not permanently anxious.

## 6. Relevant-memory retrieval rather than full-memory injection

The prompt for a single turn contains:

- The profile summary (bounded, ~500 tokens).
- The top-k retrieved memories for this turn (k tuned per intent, default 8).
- Active goals (bounded, filtered by relevance).
- Rolling emotional state (compact).
- The last N conversation turns.

Never the full memory store. Never every goal. Never the raw embedding table.

## 7. Modular architecture

The Twin Engine is a directed graph of stages, each with a typed input and typed
output. A stage can be swapped, mocked, or removed. Stages do not import from each
other; they communicate through the `TwinContext` object.

## 8. Testability

- Every stage is unit-tested with fixtures.
- The LLM provider has a `MockProvider` that returns fixture responses keyed by
  prompt hash.
- Integration tests run against a disposable Postgres + pgvector container.
- Golden-transcript tests pin the memory-extraction behaviour on canonical
  conversations.

## 9. Observability

Every request is traced. For each Twin Engine call we record:

- Retrieved memory IDs and their similarity scores.
- Prompt hash and provider/model.
- Latency per stage.
- Token counts in and out.
- Extracted memory candidates and their fate (persisted, rejected, deferred).

Traces are queryable per user (with privacy tier applied) and per session.

## 10. Security by default

- Postgres RLS on every user-scoped table.
- Service-role keys stay server-side; never in the mobile bundle.
- Secrets in a vault; never in `.env` files committed to the repo.
- Rate limits per user, per IP, and per endpoint.
- All API calls authenticated by Supabase-issued JWTs; no anonymous writes.

## 11. No speculative features

The MVP does **not** include: voice, avatar generation, autonomous agents,
tool use, external integrations (calendar, email, health), or multi-modal input
beyond text. Each of these has a roadmap slot; none has code in Sprint 1.

## 12. Build the smallest working system first

The smallest working twin is:

> A user signs in, chats with their twin, and the twin remembers what matters
> between sessions.

That is the Sprint 1–3 target. Everything else is scope creep until that works.

---

## Product-level principles (for context)

- **The user is the source of truth.** When the twin's belief and the user's
  statement disagree, the user wins by default; the previous belief is retained
  as historical, not deleted, unless the user asks.
- **The twin does not pretend to be a therapist, doctor, or lawyer.** It can
  discuss feelings, health topics, and legal topics, but it names its limits and
  points to professionals when appropriate.
- **The twin is honest about what it does not know.** "I don't have that on
  file" is preferable to a plausible fabrication.
- **The twin's tone follows the user, not a persona.** Communication style is
  learned; it is not a fixed brand voice.
