# MirrorSelf

> A digital-twin platform: your face, your voice, your personality, in an AI that talks back.

MirrorSelf lets a user upload a face photo, record 30 seconds of voice, and
answer a short personality quiz. From those it builds:

- a **voice clone** (via [XTTS-v2](https://github.com/coqui-ai/TTS))
- a **talking head** (via [SadTalker](https://github.com/OpenTalker/SadTalker))
- a **personality prompt** + **memory** that grows with every conversation

The result is an AI twin you can chat with — typing or speaking — and whose
replies are spoken in your own voice and played back as a lip-synced video.
Make your twin public and you get a shareable link (`/u/yourname`) so friends
can talk to it too.

```
┌──────────┐    HTTPS    ┌────────────┐    HTTP    ┌──────────┐
│ Browser  │ ──────────▶ │ Next.js 14 │ ──────────▶ │ FastAPI  │
└──────────┘             │ (frontend) │             │ (backend)│
                         └────────────┘             └────┬─────┘
                                                         │
                                            ┌────────────┴───────────┐
                                            ▼                        ▼
                                       ┌─────────┐              ┌────────┐
                                       │Postgres │              │ Redis  │
                                       └─────────┘              └────────┘
                                            ▲                        ▲
                                            │                        │
                                  ┌─────────┴────────┐    ┌──────────┴────────┐
                                  │ facts / messages │    │ short-term memory │
                                  └──────────────────┘    └───────────────────┘
```

## Features

- **Onboarding** — face photo + 30s voice sample + 5-question personality quiz
- **Avatar pipeline** — XTTS-v2 voice cloning + SadTalker talking-head generation
- **Chat** — text or voice input, spoken + animated AI replies
- **Memory** — facts are extracted from every conversation (Postgres) and a
  short-term window is held in Redis for prompt context
- **Emotional intelligence** — sentiment + emotion classification adjusts the
  response tone (supportive / challenging / playful / grounding / warm / neutral)
- **Public profiles** — `/u/[username]` for sharing your twin with others

## Tech stack

| Layer    | Tech                                                                                  |
|----------|----------------------------------------------------------------------------------------|
| Frontend | Next.js 14 (App Router) · TypeScript · Tailwind CSS · shadcn/ui · Zustand              |
| Backend  | FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · python-jose                    |
| Data     | PostgreSQL 16 · Redis 7                                                                 |
| AI       | Anthropic Claude (chat, fact extraction, emotion classification)                        |
| Voice    | [XTTS-v2](https://github.com/coqui-ai/TTS) (voice cloning)                              |
| Video    | [SadTalker](https://github.com/OpenTalker/SadTalker) (lip-sync animation)               |
| Infra    | Docker Compose · Cloudflare Tunnel · GitHub Actions                                      |

## Project layout

```
mirrorself/
├── backend/                    # FastAPI service
│   ├── app/
│   │   ├── api/                # auth, onboarding, chat, public, me
│   │   ├── core/               # config, db, redis, security, logging
│   │   ├── models/             # SQLAlchemy ORM (User, Conversation, Message, Fact)
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── services/           # llm, sentiment, memory, voice (XTTS), avatar (SadTalker), chat
│   │   └── main.py             # FastAPI app + lifespan
│   ├── alembic/                # migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # Next.js 14 app
│   ├── src/app/                # routes (App Router)
│   │   ├── api/[...path]/      # catch-all proxy to backend
│   │   ├── login/, register/
│   │   ├── onboarding/         # 4-step wizard
│   │   ├── chat/               # main chat UI
│   │   ├── u/[username]/       # public twin page
│   │   └── settings/
│   ├── src/components/ui/      # shadcn primitives
│   ├── src/lib/                # api client, auth store, utils
│   ├── package.json
│   └── Dockerfile
├── scripts/                    # setup, migrate, make_migration
├── .github/workflows/ci.yml    # GitHub Actions
├── cloudflared/                # Cloudflare Tunnel config
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick start (Docker)

The fastest way to get MirrorSelf running is Docker Compose. It boots
Postgres, Redis, the FastAPI backend, and the Next.js frontend.

```bash
# 1. Clone
git clone https://github.com/your-org/mirrorself.git
cd mirrorself

# 2. Configure
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY (required) and SECRET_KEY (recommended)

# 3. Start
docker compose up --build
```

Then open:

- http://localhost:3000 — frontend
- http://localhost:8000/docs — interactive API docs
- http://localhost:8000/health/ready — readiness probe

> **Note:** XTTS-v2 and SadTalker are not pulled in by default. See
> "Model weights" below. Until they're installed, the voice and avatar
> services fall back to a stub so the rest of the app still works.

## Quick start (dev, no Docker)

Run each service directly for hot-reload development.

### 0. Prereqs

- **Python** 3.11+
- **Node.js** 20+
- **PostgreSQL** 16 running locally
- **Redis** 7 running locally
- **ffmpeg** on `$PATH` (for SadTalker + audio handling)

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Edit .env in repo root with your ANTHROPIC_API_KEY
export $(grep -v '^#' ../.env | xargs)

# Migrate
alembic upgrade head

# Run
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### 3. Model weights

The voice and avatar services lazy-load their models. To enable them:

```bash
# XTTS-v2 (~2 GB)
git clone https://github.com/coqui-ai/TTS.git
# Follow the install instructions, then point XTTS_MODEL_DIR at the
# downloaded checkpoint. (See https://docs.coqui.ai/en/latest/)

# SadTalker (~1.5 GB of checkpoints)
git clone https://github.com/OpenTalker/SadTalker.git
cd SadTalker
bash scripts/download_models.sh   # or follow the README
```

In `.env`, set:

```env
XTTS_MODEL_DIR=/path/to/TTS/models/xtts
SADTALKER_DIR=/path/to/SadTalker
SADTALKER_CHECKPOINTS=/path/to/SadTalker/checkpoints
XTTS_DEVICE=cuda    # or cpu
SADTALKER_DEVICE=cuda
```

> **GPU is strongly recommended.** XTTS-v2 on CPU takes ~10-20× longer
> than on a modern GPU. SadTalker on CPU is essentially unusable.

## Environment variables

See [`.env.example`](.env.example) for the full list. The most important
ones:

| Variable             | Required | Description                                                  |
|----------------------|----------|--------------------------------------------------------------|
| `ANTHROPIC_API_KEY`  | yes      | Anthropic API key for Claude                                 |
| `SECRET_KEY`         | yes      | JWT signing key — generate a long random string for prod     |
| `DATABASE_URL`       | yes      | Async SQLAlchemy URL (`postgresql+asyncpg://…`)              |
| `REDIS_URL`          | yes      | Redis connection string                                      |
| `PUBLIC_BASE_URL`    | yes      | Public origin used when generating share links               |
| `CORS_ORIGINS`       | no       | JSON list of allowed origins (default includes localhost)    |
| `XTTS_DEVICE`        | no       | `cuda` or `cpu`                                              |
| `SADTALKER_DEVICE`   | no       | `cuda` or `cpu`                                              |
| `TUNNEL_TOKEN`       | no       | Cloudflare Tunnel token (only if using the tunnel profile)   |

## API surface

The FastAPI backend is mounted at `/api/v1`. The Next.js catch-all route
forwards browser requests there transparently. Interactive docs at
`/docs` (Swagger) and `/redoc`.

| Method | Path                              | Description                          |
|--------|-----------------------------------|--------------------------------------|
| POST   | `/api/v1/auth/register`           | Create account                       |
| POST   | `/api/v1/auth/login`              | Log in, get JWT                      |
| GET    | `/api/v1/auth/me`                 | Current user                         |
| PATCH  | `/api/v1/me`                      | Update profile / personality         |
| POST   | `/api/v1/onboarding/face`         | Upload face photo (multipart)        |
| POST   | `/api/v1/onboarding/voice`        | Upload voice sample (multipart)      |
| POST   | `/api/v1/onboarding/quiz`         | Submit personality quiz              |
| POST   | `/api/v1/onboarding/generate-avatar` | Trigger SadTalker generation       |
| POST   | `/api/v1/chat`                    | Send a message, get spoken reply     |
| GET    | `/api/v1/me/conversations`        | List past conversations              |
| GET    | `/api/v1/me/facts`                | List memory facts                    |
| GET    | `/api/v1/u/{username}`            | Public profile of a twin             |
| POST   | `/api/v1/u/{username}/chat`       | Talk to a public twin                |

## How it works

### Onboarding

1. User uploads a clear face photo → saved to `storage/face_photos/`.
2. User records a 30s voice sample (WebM via MediaRecorder) → normalized to
   mono 24 kHz WAV and stored under `storage/voice_samples/`. The path is
   referenced as a `voice_id` so XTTS can speak in their voice.
3. User answers a 5-question personality quiz (values, communication style,
   humor, fears, dreams). The answers land in the `personality` JSONB column.
4. On `/onboarding/generate-avatar`, SadTalker is run on the face photo +
   voice sample to produce a `talking.mp4` preview.

### Chat pipeline (`POST /api/v1/chat`)

1. **Sentiment analysis** (VADER baseline, optionally refined by Claude)
   detects the user's emotion and maps it to a response tone.
2. The **system prompt** is built from:
   - the user's personality profile
   - the most relevant facts (last 30 durable facts from Postgres ∪ Redis
     deduped by Jaccard token overlap)
   - tone-specific instructions (supportive / challenging / playful / …)
3. The user's message plus the last 12 turns are sent to **Claude**.
4. In parallel:
   - **XTTS-v2** synthesises the reply in the user's voice → `voice.wav`
   - **Claude** extracts durable facts from the exchange → stored in
     Postgres + cached in Redis
5. If the user has a face photo and the twin is `ready`, **SadTalker**
   generates a `talking.mp4` for the reply.
6. The reply (text + audio + video URLs + extracted facts) is returned.

### Memory

- **Redis** stores the most recent 200 facts as a capped list per user
  (`mirrorself:user:{id}:facts`) and a 40-entry short-term chat window
  (`mirrorself:user:{id}:short_term`).
- **Postgres** persists every fact durably in the `facts` table.
- A fact is added only if it isn't a near-duplicate of an existing one
  (Jaccard ≥ 0.7 over word tokens).

### Public profiles

When a user flips `is_public = true`, anyone can hit
`GET /api/v1/u/{username}` to see their profile and `POST /api/v1/u/{username}/chat`
to talk to their twin. The chat runs in `twin_mode` — the system prompt
identifies the AI as a faithful approximation of the user, not the user
themselves.

## Cloudflare Tunnel (optional)

To expose the app to the public internet without opening ports:

1. Create a tunnel at https://one.dash.cloudflare.com → Zero Trust → Tunnels.
2. Copy the token into `TUNNEL_TOKEN` in `.env`.
3. Add hostnames (e.g. `mirrorself.example.com`, `api.example.com`) and
   point them at the `cloudflared` service.
4. `docker compose --profile tunnel up -d`

See [`cloudflared/README.md`](cloudflared/README.md) for details.

## CI

GitHub Actions runs on every push and PR (`.github/workflows/ci.yml`):

- Backend lint (`ruff`) and tests (`pytest` against a Postgres + Redis
  service in the runner)
- Frontend lint, typecheck, and production build
- Docker images built and pushed to GHCR on `main`

## Development tips

- **Hot reload** for the backend: `uvicorn app.main:app --reload`.
- **Hot reload** for the frontend: `npm run dev` (Next.js handles it).
- **Stub mode**: if XTTS or SadTalker are not installed, the services
  fall back to emitting a stub wav / placeholder so the rest of the app
  stays usable.
- **Fact cleanup**: facts are deduped at insertion time. Use
  `DELETE /api/v1/me/facts/{id}` to forget something specific.
- **Inspect Redis**: `redis-cli LRANGE mirrorself:user:1:facts 0 -1`.

## Production checklist

- [ ] `SECRET_KEY` set to a strong random value
- [ ] `ANTHROPIC_API_KEY` set
- [ ] `CORS_ORIGINS` restricted to your real frontend origin
- [ ] `PUBLIC_BASE_URL` set to your real public URL
- [ ] `XTTS_DEVICE=cuda` and `SADTALKER_DEVICE=cuda` if you have a GPU
- [ ] Postgres backups enabled
- [ ] Redis persistence enabled (`appendonly yes`)
- [ ] Cloudflare Tunnel (or equivalent) in front for TLS + DDoS
- [ ] Rate limiting on `/api/v1/chat` (e.g. Cloudflare WAF rule)

## License

MIT.
