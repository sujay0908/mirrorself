#!/usr/bin/env bash
# Idempotent setup: creates venv, installs deps, writes .env, starts postgres+redis.
# Idempotent: safe to re-run.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> MirrorSelf first-time setup"

# 1. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    created .env from .env.example (please fill in ANTHROPIC_API_KEY)"
else
  echo "    .env already exists, leaving it"
fi

# 2. Backend venv
if [ ! -d backend/venv ]; then
  echo "    creating python venv"
  python3 -m venv backend/venv
fi
# shellcheck disable=SC1091
source backend/venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# 3. Storage dirs
mkdir -p backend/storage/{voice_samples,voice_output,face_photos,avatars} backend/logs
echo "    created storage dirs"

# 4. Postgres + Redis
if command -v docker >/dev/null 2>&1; then
  echo "    starting postgres + redis via docker"
  docker compose up -d postgres redis
  echo "    waiting for postgres…"
  for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U mirrorself >/dev/null 2>&1; then break; fi
    sleep 1
  done
else
  echo "    docker not found — please start postgres and redis manually"
fi

# 5. Run migrations
echo "    running alembic migrations"
(cd backend && alembic upgrade head)

# 6. Frontend
if command -v npm >/dev/null 2>&1; then
  echo "    installing frontend deps"
  (cd frontend && npm install)
else
  echo "    npm not found — install Node 20+ to build the frontend"
fi

cat <<EOF

✅ Setup complete. Next:
  1. Edit .env and add your ANTHROPIC_API_KEY
  2. (optional) Pull XTTS-v2 and SadTalker model weights — see README
  3. Start the stack:
       docker compose up --build
     …or run dev mode:
       (cd backend && uvicorn app.main:app --reload)
       (cd frontend && npm run dev)
EOF
