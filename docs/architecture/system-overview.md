# System Overview

> **The avatar is the interface; the evolving personal intelligence is the product.**

This document describes the shape of the Personal AI Twin system: repository
layout, technology stack, runtime topology, and the boundaries between
subsystems. The Twin Engine and memory system have their own documents.

---

## Repository organisation — monorepo

**Recommendation: monorepo.**

The system has two runtime surfaces (FastAPI backend, Expo mobile app) that
must share types, prompt templates, and API contracts. A polyrepo forces
version drift between them and duplicates CI. A monorepo keeps types in one
place and lets a schema change land in a single PR that touches both surfaces.

The monorepo is workspaces-based; there is no runtime coupling between
`apps/*`. Each app is deployable independently.

```
personal-ai-twin/
├── apps/
│   ├── api/                     # FastAPI service
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── db/              # SQLAlchemy models, session factory
│   │   │   ├── llm/
│   │   │   │   ├── providers/   # claude.py, openai.py, mock.py, local.py
│   │   │   │   ├── interface.py # LLMProvider protocol
│   │   │   │   └── registry.py  # runtime provider selection
│   │   │   ├── memory/          # extraction, scoring, retrieval, storage
│   │   │   ├── twin/            # engine, stages, context builder
│   │   │   ├── goals/
│   │   │   ├── conversations/
│   │   │   ├── profile/
│   │   │   ├── auth/            # JWT verification against Supabase JWKS
│   │   │   ├── api/             # FastAPI routers
│   │   │   └── observability/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── mobile/                  # Expo / React Native
│       ├── app/                 # Expo Router
│       ├── src/
│       │   ├── api/             # generated client from OpenAPI
│       │   ├── screens/
│       │   ├── components/
│       │   └── state/           # Zustand or Redux Toolkit
│       ├── app.json
│       └── package.json
├── packages/
│   ├── shared-types/            # generated TS + Python types from OpenAPI
│   └── prompt-templates/        # versioned prompt fragments, YAML + tests
├── infra/
│   ├── docker/                  # docker-compose.dev.yml, Dockerfile.api
│   └── supabase/                # schema.sql, policies.sql, seed.sql
├── docs/                        # this documentation set
├── .github/
│   └── workflows/               # test, typecheck, lint, deploy
├── package.json                 # workspace root
├── pnpm-workspace.yaml
└── README.md
```

`pnpm` is the JS package manager (fast, disk-efficient, first-class workspace
support). `uv` (or `pip-tools`) manages Python dependencies for `apps/api`.

---

## Runtime topology

```
                   ┌───────────────────┐
                   │  Expo React       │
                   │  Native (iOS,     │
                   │   Android)        │
                   └─────────┬─────────┘
                             │  HTTPS + JWT
                             ▼
                   ┌───────────────────┐
                   │  FastAPI API      │
                   │  (Fly.io/Render)  │
                   └─┬────┬────┬────┬──┘
                     │    │    │    │
                     ▼    ▼    ▼    ▼
           ┌─────────┐  ┌────┐  ┌──────────┐  ┌──────────────┐
           │Supabase │  │Redis│ │  LLM     │  │  Observ.     │
           │Postgres │  │(BG  │ │ Provider │  │  (OpenTel →  │
           │+pgvector│  │jobs)│ │  API     │  │   Honeycomb) │
           │+Auth    │  │     │ │          │  │              │
           │+Storage │  │     │ │          │  │              │
           └─────────┘  └────┘  └──────────┘  └──────────────┘
```

- **Mobile app** — Expo React Native, distributed via EAS. Talks only to the
  FastAPI service and to Supabase Auth. Never to an LLM provider directly.
- **FastAPI service** — the only path that touches user data at scale. All
  business logic, all LLM calls, all memory writes.
- **Supabase** — Postgres with pgvector, Supabase Auth (JWT issuance, providers),
  Supabase Storage (later, for user-uploaded files that inform memory).
- **Redis** — background job queue (rq or arq) for reflection, embedding
  backfills, and any async work that must not block a chat turn.
- **LLM Provider** — Anthropic (Claude 4.6 Sonnet) via the Anthropic API in
  MVP. Provider is injected via `LLMProvider` interface.
- **Observability** — OpenTelemetry SDK inside FastAPI, exporting to an
  OTel-compatible backend (Honeycomb, Grafana Tempo, or SigNoz). Logs to
  stdout, aggregated by the platform.

---

## Technology decisions

| Concern | Choice | Notes |
|---|---|---|
| Backend language | Python 3.12 | Aligns with Sujay's existing stack. |
| Backend framework | FastAPI | Async, typed, OpenAPI-native. |
| ORM | SQLAlchemy 2.x (async) | Or SQLModel wrapping it. |
| Migrations | Alembic | **Not created in Sprint 0.** |
| Database | Postgres 15+ via Supabase | pgvector for embeddings. |
| Vector search | pgvector, ivfflat | Upgrade to hnsw when row count justifies. |
| Auth | Supabase Auth | FastAPI verifies JWTs against JWKS. |
| Storage | Supabase Storage | User-uploaded artefacts (post-MVP). |
| Background jobs | Redis + arq | Small, async-native. |
| Frontend | Expo React Native + Expo Router | Mobile first. |
| State (mobile) | Zustand | Small, ergonomic. |
| API contract | OpenAPI 3.1 from FastAPI | Generates TS client and Python types. |
| LLM (chat) | Claude 4.6 Sonnet | Behind `LLMProvider` interface. |
| LLM (embeddings) | OpenAI `text-embedding-3-small` | 1536 dims. Behind `EmbeddingProvider`. |
| Prompt storage | YAML in `packages/prompt-templates/` | Versioned, hashed, tested. |
| Package manager (JS) | pnpm | Workspaces. |
| Package manager (Py) | uv | Fast, lockfile-first. |
| CI | GitHub Actions | Test, typecheck, lint per app. |
| Deployment (API) | Fly.io (recommended) | Region near Supabase. |
| Deployment (mobile) | EAS Build + TestFlight/Play Internal | |
| Observability | OpenTelemetry + Honeycomb | Trace every LLM call. |
| Error tracking | Sentry (both API and mobile) | |
| Secrets | Supabase Vault (server) + Expo secure store (mobile) | No `.env` in the repo. |

Every LLM-touching row in this table is behind an interface. A future
provider (OpenAI, Ollama, llama.cpp, MLX on-device) can be added without
touching business logic.

---

## Data flow (chat turn, high level)

1. Mobile app sends `POST /v1/conversations/{id}/messages` with the user
   message and JWT.
2. FastAPI verifies the JWT, resolves the `user_id`, loads the twin.
3. `TwinEngine.run(user_message, twin_context)` executes the pipeline
   (see [`twin-engine.md`](twin-engine.md)).
4. The response is streamed back to the mobile app.
5. A background task extracts memory candidates, scores them, and either
   persists them, defers them for user confirmation, or drops them.

---

## Environments

- **dev** — Docker Compose on a laptop. Supabase local dev instance optional.
- **staging** — a small Fly.io app + a separate Supabase project.
- **prod** — a scaled Fly.io app + a separate Supabase project.

Environment selection is exclusively via environment variables. No environment
name is baked into code.

---

## Open questions (must be closed before Sprint 1)

1. **Hosting for FastAPI:** Fly.io, Render, or Railway? Recommendation:
   Fly.io for region control and lifecycle simplicity.
2. **Embedding provider commitment:** OpenAI vs Voyage vs Cohere. OpenAI is
   cheapest and well-understood; Voyage has stronger benchmarks on retrieval.
   Recommendation: OpenAI `text-embedding-3-small` for MVP, revisit after
   1000 memories.
3. **Mobile-first vs web-first:** memory says React Native + Expo. Confirmed.
   Web is post-MVP.
4. **Consolidation loop timing:** nightly, weekly, or event-driven? The
   memory doc proposes nightly with weekly digests. Decision needed before
   Sprint 2.
5. **Deletion semantics:** hard delete vs anonymised retention for
   ML/analytics. Recommendation: hard delete on user request, no analytics
   retention.
6. **Privacy tier for observability:** does the trace store memory IDs only,
   or also similarity scores and content hashes? Recommendation: IDs and
   scores yes; content hashes no.
7. **Rate limiting strategy:** per user, per IP, or both? Recommendation: both,
   with user limits stricter than IP.
