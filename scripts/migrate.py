#!/usr/bin/env python
"""Run database migrations via Alembic. Idempotent wrapper that loads .env."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# Load .env if present (very small parser — no dependency)
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

cmd = ["alembic", "upgrade", "head"] if len(sys.argv) == 1 else sys.argv[1:]
print(f"==> Running: {' '.join(cmd)} (cwd={BACKEND})")
result = subprocess.run(cmd, cwd=BACKEND)
sys.exit(result.returncode)
