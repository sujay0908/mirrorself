"""Reusable column types.

Currently a thin re-export layer — the `Uuid` and `DateTime` types provided
by SQLAlchemy 2.x are sufficient for the Sprint 1 schema. This file exists
so that when future migrations need `TSVECTOR`, `JSONB`-specific behaviour,
or `pgvector` types, there is one canonical import site to touch.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Uuid

__all__ = ["DateTime", "Uuid"]
