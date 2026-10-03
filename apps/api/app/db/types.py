"""Reusable column types.

Thin re-exports plus a dialect-aware vector column so Sprint 3's semantic
embedding store works on Postgres (via pgvector) and still functions on
SQLite (via JSON) for the test suite.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import JSON, DateTime, Uuid
from sqlalchemy.types import TypeDecorator, TypeEngine

__all__ = ["DateTime", "Uuid", "VectorColumn"]


class VectorColumn(TypeDecorator[list[float]]):
    """A float-vector column.

    On PostgreSQL this uses ``pgvector.Vector(dim)`` so retrieval can rely
    on ``<=>`` / ``<#>`` / ``<->`` operators and ivfflat/hnsw indexes. On
    any other backend (notably SQLite in tests) it falls back to ``JSON``
    so the schema still migrates cleanly and the application code reads
    and writes the same ``list[float]`` values.

    Retrieval queries that need the pgvector operator syntax are
    responsibility of the retriever; this type decorator only standardises
    the storage format.

    Values are always exchanged as Python ``list[float]`` (or ``None``).
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            # Lazy import keeps the test environment free of pgvector when it
            # isn't needed (though it IS a runtime dep via pyproject).
            from pgvector.sqlalchemy import Vector

            return cast(TypeEngine[Any], dialect.type_descriptor(Vector(self.dim)))
        return cast(TypeEngine[Any], dialect.type_descriptor(JSON()))

    def process_bind_param(
        self, value: list[float] | None, dialect: Any
    ) -> list[float] | None:
        return value

    def process_result_value(
        self, value: Any, dialect: Any
    ) -> list[float] | None:
        if value is None:
            return None
        # pgvector returns a numpy-compatible sequence; normalise to list.
        return [float(x) for x in value]
