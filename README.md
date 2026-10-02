# Personal AI Twin

> **The avatar is the interface; the evolving personal intelligence is the product.**

Personal AI Twin is a per-user digital twin — a persistent, personalised
intelligence that learns who you are over time. It remembers, reflects,
reasons, and eventually acts on your behalf. Voice and visual avatar are
downstream surfaces; the core product is the underlying intelligence:
identity, memory, context, reasoning, emotion, evolution, and (later) agency.

This repository is a monorepo (pnpm for JS, uv for Python).

---

## Status: Sprint 2 complete

Both the Sprint 1 vertical slice and the Sprint 2 memory foundation are in
place.

**Sprint 1** — delivered:
- FastAPI backend (clean layered structure, error envelope, observability,
  Supabase-JWT auth gate).
- Postgres schema for `twins`, `twin_profiles`, `conversations`, `messages`
  (Alembic `0001_initial`).
- Provider-agnostic `LLMProvider` + `MockProvider`, `AnthropicProvider`,
  `OpenAIProvider`, `LocalProvider` stub.
- Twin creation (one per user), profile PATCH, conversation / message
  endpoints.
- Expo React Native app (login → onboarding → home → chat).

**Sprint 2** — delivered:
- Memory domain (`memories`, `memory_sources`, `memory_embeddings`,
  `memory_candidates`) via Alembic `0002_memory_system`.
- `embedding_model` and `embedding_dimensions` are stored per row — no
  hard-coded 1536 anywhere in domain code.
- `EmbeddingProvider` abstraction with `MockEmbeddingProvider`
  (deterministic, offline, dependency-free) and `OpenAIEmbeddingProvider`
  (lazy SDK import, only required for `EMBEDDING_PROVIDER=openai`).
- Memory CRUD (`GET /v1/memories`, `GET /v1/memories/{id}`,
  `PATCH`, `DELETE`). PATCH accepts `content`, `importance`, `metadata`
  only — **never** `user_confirmed`. The only path to a user-confirmed
  memory is confirming a pending candidate.
- Candidate lifecycle (`GET /v1/memory-candidates`,
  `POST .../confirm`, `POST .../reject`).
- Memory extraction runs as a FastAPI background task after each
  conversation turn. It never blocks the chat response, never raises into
  the caller, and never writes to `TwinProfile`.
- Confirmation is a hard guarantee: the Memory + MemorySource transaction
  commits BEFORE any embedding attempt. If the embedding provider fails,
  the memory still exists; the response reports `embedding_attached: false`
  and `embedding_error: "<ExceptionClass>"`.
- 55 backend tests, all passing: 21 Sprint 1 (regression-protected) + 34
  Sprint 2.
- Chat and memory extraction use independent FastAPI dependencies, so an
  extraction-provider failure never fails the chat response. Pinned by
  `test_extraction_failure_does_not_fail_chat`.
- Migrations verified against PostgreSQL 16: forward, downgrade, and
  roundtrip. Caught + fixed a Sprint 1 oversight where the ORM `Message`
  model had `updated_at` but the migration didn't create the column.

Sprint 3 opens retrieval and reflection (not scaffolded yet).

---

## Repository layout

```
personal-ai-twin/
├── README.md · .gitignore · .env.example · package.json · pnpm-workspace.yaml
├── apps/
│   ├── api/                     # FastAPI + SQLAlchemy 2.x async
│   │   ├── app/                 # main.py, config.py, api/, auth/, twin/,
│   │   │                        # conversation/, llm/, db/, observability/,
│   │   │                        # common/
│   │   ├── alembic/versions/    # 0001_initial.py (Sprint 1 schema)
│   │   ├── tests/               # 55 tests, in-memory SQLite
│   │   └── pyproject.toml
│   └── mobile/                  # Expo Router
│       ├── app/                 # (auth)/login, (onboarding)/create-twin,
│       │                        # (main)/home, (main)/chat/[id]
│       └── src/                 # api, auth, state, components
├── packages/
│   ├── shared-types/            # hand-authored TS types (Sprint 2: generated)
│   └── prompt-templates/        # yaml prompt fragments (Sprint 2 wiring)
├── infra/
│   ├── docker/                  # docker-compose.dev.yml, Dockerfile.api
│   └── supabase/                # schema.sql, policies.sql, README.md
├── docs/                        # Sprint 0 architecture + product docs
└── .github/workflows/           # api.yml, mobile.yml, types.yml
```

---

## Local development

### Prerequisites

- Python 3.12 (3.11 works for tests)
- Node 20+ and `pnpm 9`
- Docker + Docker Compose (for Postgres and Redis)
- A Supabase project (optional in dev; `SUPABASE_JWT_HS_SECRET` unlocks the
  HS256 dev shortcut)

### Bootstrap

```bash
# 1. clone
git clone git@github.com:sujay0908/mirrorself.git personal-ai-twin
cd personal-ai-twin

# 2. env
cp .env.example .env    # edit as needed

# 3. JS deps
pnpm install

# 4. Python deps (uv shown here; pip works too)
cd apps/api
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,anthropic]"
```

### Run the backend

```bash
# spin up Postgres + Redis
docker compose -f infra/docker/docker-compose.dev.yml up -d postgres redis

# apply migrations
cd apps/api
alembic upgrade head

# run the API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run the mobile app

```bash
cd apps/mobile
pnpm start        # then choose iOS simulator, Android emulator, or Expo Go
```

### Tests

```bash
# backend
cd apps/api && pytest -q

# mobile (unit-level only in Sprint 1)
cd apps/mobile && pnpm test
```

---

## Environment variables

See `.env.example`. Every setting is sourced from environment variables.
`.env` must NEVER be committed. Provider secrets (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`) only need to be set for the provider named by
`LLM_PROVIDER`.

---

## Design docs

- Sprint 0 architecture and product docs live under `docs/`. Highlights:
  - [`docs/product/product-principles.md`](docs/product/product-principles.md)
  - [`docs/product/mvp-scope.md`](docs/product/mvp-scope.md)
  - [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md)
  - [`docs/architecture/twin-engine.md`](docs/architecture/twin-engine.md)
  - [`docs/architecture/memory-system.md`](docs/architecture/memory-system.md)
  - [`docs/api/api-conventions.md`](docs/api/api-conventions.md)

---

## Sprint 1 → 2 handoff

Sprint 2 lands the memory system. The interfaces, tables, and provider
seams are already shaped for it:

- `EmbeddingProvider` in `apps/api/app/llm/interface.py`.
- The response pipeline in `apps/api/app/conversation/pipeline.py` is a
  single function that the extended engine wraps.
- The migration numbering is stable — the next migration is
  `0002_memory_system.py`.

See `docs/architecture/memory-system.md` for the full schema and lifecycle.
