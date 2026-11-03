#!/bin/sh
# Production entrypoint: apply migrations, then serve.
#
# This lives in a file rather than in an inline `dockerCommand` because a
# command containing quotes, `&&` and `$PORT` has to survive the hosting
# platform's own parsing before a shell ever sees it. Render re-parsed the
# previous inline `sh -c "..."` and handed the whole line to a shell as a
# single word, which exited 127 with a misleading message:
#
#   sh: 1: alembic upgrade head && exec uvicorn ... --port 10000: not found
#
# Note what that named: the ENTIRE command line, not `alembic`. A missing
# binary reports `sh: 1: alembic: not found`. Alembic was never missing - it
# is a runtime dependency in pyproject.toml and is installed in the image.
#
# Invoked as a single path with no quoting, so it cannot be mis-parsed again.

set -e

# alembic.ini is resolved relative to the working directory, so anchor to this
# script's own directory instead of trusting the caller's cwd.
cd "$(dirname "$0")"

# `python -m alembic` rather than the `alembic` console script: it does not
# depend on the entry-point shim being on PATH for the runtime user.
python -m alembic upgrade head

# `exec` so uvicorn replaces the shell and receives SIGTERM directly, which is
# what lets the platform stop the container cleanly.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
