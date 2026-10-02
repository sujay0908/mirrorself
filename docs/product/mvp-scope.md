# MVP Scope

> **The avatar is the interface; the evolving personal intelligence is the product.**

The MVP is the shortest path to a real twin conversation. The measure of success
is not features shipped — it is whether the twin visibly gets to know the user
across sessions.

---

## In scope for MVP (Sprints 1–3)

### Sprint 1 — Backend foundation

- FastAPI service scaffold.
- Health, readiness, and version endpoints.
- Supabase project provisioned (staging + prod).
- Postgres schema for `users`, `twins`, `twin_profiles`, `memories`,
  `memory_embeddings`, `conversations`, `messages`, `goals`, `goal_events`,
  `emotional_states`.
- pgvector extension enabled; ivfflat index on `memory_embeddings.vector`.
- RLS policies on every user-scoped table.
- LLM provider abstraction with a `ClaudeProvider` and a `MockProvider`.
- Structured logging + request tracing.
- Local dev via Docker Compose (Postgres + Redis + API).

### Sprint 2 — Twin Engine v0

- Twin Engine pipeline stages implemented as pure functions:
  intent detection, memory retrieval, goal retrieval, context assembly,
  LLM call, memory candidate extraction, validation, persistence.
- Prompt templates versioned in `packages/prompt-templates/`.
- Conversation and message persistence with idempotent writes.
- Reflection stub: a nightly job that summarises the day's memories into a
  weekly digest (no profile updates yet).
- Golden-transcript tests for extraction behaviour.

### Sprint 3 — Mobile client v0

- Expo React Native app.
- Supabase Auth (email + Apple/Google).
- Chat screen (single conversation).
- Memory drawer: view, edit, delete.
- Goal list: view, add, complete.
- Profile screen: view profile summary, edit communication style toggle.

Total: three sprints, one thin end-to-end product.

---

## Explicitly out of scope for MVP

The following are **not** built in Sprints 1–3. Each has a roadmap slot beyond
MVP, but no code, no scaffold, no half-implementation.

- Voice input, voice output, TTS/STT.
- Visual avatar (2D or 3D), lip sync, expression animation.
- Autonomous agents, planners, or long-running tool loops.
- Tool use / function calling in production paths (a `MockProvider` may
  exercise the shape for tests).
- External integrations: calendar, email, contacts, wearables, health data.
- Multi-user twins, shared twins, or family plans.
- Web application. The MVP is mobile-first; the web client is a Sprint 4+
  concern.
- Local / on-device inference. Claude via cloud API is the MVP path; local
  models are a documented roadmap item.
- Multiple twin personas per user. One user, one twin, for MVP.
- Fine-tuning or embedding retraining.
- Emotional state → profile promotion. Emotional state is captured but does
  not write to profile until the consolidation loop is designed (post-MVP).
- Real-time collaboration or presence.

---

## What "done" looks like at MVP end

A new user signs up, has three conversations across three days, and:

1. The twin correctly recalls three specific facts they mentioned in earlier
   sessions.
2. The twin's tone in session 3 is measurably closer to the user's own tone
   than the default persona (surface metric: sentence length, formality,
   emoji density).
3. The user can open the memory drawer, see those three facts as first-class
   rows, edit one, and delete one, and the twin respects those edits in the
   next turn.
4. All requests are traced end-to-end; ops can point to any twin response and
   show which memories fed the prompt.

That is the bar. No feature ships if it distracts from that.

---

## Sprint 0 (this document set) — checklist

- [x] Product principles written.
- [x] MVP scope written.
- [x] System overview written.
- [x] Twin Engine design written.
- [x] Memory system design written.
- [x] API conventions written.
- [ ] Architecture reviewed and signed off by founder.
- [ ] Open questions in `docs/architecture/system-overview.md` §"Open questions"
      resolved.
- [ ] Decision recorded: monorepo vs polyrepo (recommended: **monorepo**).
- [ ] Decision recorded: initial LLM provider config (recommended:
      **Claude 4.6 Sonnet via Anthropic API**, `MockProvider` for tests).
- [ ] Decision recorded: embedding model (recommended: **OpenAI
      `text-embedding-3-small`** via the same provider abstraction — the
      abstraction supports mixing chat and embedding providers).
- [ ] Decision recorded: hosting for FastAPI (Fly.io, Render, or Railway;
      Supabase already covers DB/auth/storage).
- [ ] Repository initialised on GitHub with these documents, a `LICENSE`, a
      `CODE_OF_CONDUCT.md`, and a `SECURITY.md`.

Sprint 1 begins the day Sprint 0 is signed off.
