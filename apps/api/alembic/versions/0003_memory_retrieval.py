"""Sprint 3 memory retrieval — pgvector column on memory_embeddings.

Design (Sprint 3 decision D3-b):

- Keep the Sprint 2 legacy ``vector`` JSON column in place for one release
  so existing rows remain readable.
- Add a NEW nullable ``embedding_vector`` column typed ``vector(1536)``.
- Build an IVFFlat cosine-distance index on the new column.
- Semantic retrieval queries operate ONLY on the new column.
  Rows with ``embedding_vector IS NULL`` (legacy Sprint 2 mock-vector rows
  and any provider-failure rows) are skipped by the retriever but still
  usable via listing endpoints and still carry provenance.
- A future backfill job can populate ``embedding_vector`` for existing
  rows via the configured EmbeddingProvider; this migration does NOT
  attempt to convert the Sprint 2 mock hash vectors.

Extension enablement (decision D1-c):

The migration attempts ``CREATE EXTENSION IF NOT EXISTS vector`` at the
top of ``upgrade()``. If the operator's role lacks permission (common on
Supabase projects where the extension has not been enabled from the
dashboard), the migration aborts with a clear message describing the
one-line manual command. No silent fallback — if pgvector cannot be
provisioned the vector column cannot be created and the Sprint 3 feature
cannot run.

Revision ID: 0003_memory_retrieval
Revises: 0002_memory_system
Create Date: 2026-10-03
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, ProgrammingError

from alembic import op

revision: str = "0003_memory_retrieval"
down_revision: str | Sequence[str] | None = "0002_memory_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1536

MANUAL_FALLBACK_SQL = (
    "CREATE EXTENSION IF NOT EXISTS vector;  -- run as a role with CREATE "
    "privilege on the database (Supabase: Database → Extensions → vector)."
)


def _ensure_pgvector_extension() -> None:
    """Try to enable pgvector; raise with a helpful message on failure."""
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except (ProgrammingError, DBAPIError) as exc:
        raise RuntimeError(
            "Could not CREATE EXTENSION vector. Enable it once as a "
            "superuser-equivalent role, then re-run `alembic upgrade head`. "
            f"Manual command: {MANUAL_FALLBACK_SQL}"
        ) from exc


def upgrade() -> None:
    _ensure_pgvector_extension()

    # Import inside the function so Alembic autogenerate doesn't need
    # pgvector loaded when the migration file is merely imported.
    from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]

    op.add_column(
        "memory_embeddings",
        sa.Column("embedding_vector", Vector(EMBED_DIM), nullable=True),
    )

    # IVFFlat cosine index. `lists=100` is a conservative default for small
    # tables; tune up as the corpus grows (Postgres doc: ~sqrt(N)).
    op.execute(
        "CREATE INDEX ix_memory_embeddings_vector "
        "ON memory_embeddings "
        "USING ivfflat (embedding_vector vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_embeddings_vector")
    op.drop_column("memory_embeddings", "embedding_vector")
    # Deliberately do NOT drop the vector extension — other objects in the
    # database may depend on it. The operator removes it manually when safe.
