#!/usr/bin/env bash
# Generate a fresh revision in backend/alembic/versions/
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"
source ../backend/venv/bin/activate 2>/dev/null || true
alembic revision --autogenerate -m "${1:-schema change}"
