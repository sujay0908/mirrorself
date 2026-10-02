"""MockEmbeddingProvider — deterministic, dependency-free, offline.

Given a text and model, derives a vector of `dimensions` floats from the
SHA-256 of `"{model}:{text}"`. The same input always produces the same
vector. Values are in [-1, 1] with uniform distribution good enough for
unit tests; this is NOT a semantic embedding.
"""

from __future__ import annotations

import hashlib
import struct
from typing import ClassVar

from app.llm.interface import EmbeddingProvider, EmbeddingRequest, EmbeddingResponse


class MockEmbeddingProvider(EmbeddingProvider):
    provider_name: ClassVar[str] = "mock"

    def __init__(self, *, dimensions: int, model: str) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions
        self._default_model = model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        vectors = [self._hash_vector(text, request.model) for text in request.texts]
        return EmbeddingResponse(
            embeddings=vectors,
            model=request.model,
            provider=self.provider_name,
            dimensions=self._dimensions,
        )

    def _hash_vector(self, text: str, model: str) -> list[float]:
        """Deterministic pseudo-embedding.

        Produces `self._dimensions` floats from a growing SHA-256 chain so
        the output length is independent of the input. Each 4-byte chunk is
        unpacked as an unsigned int and mapped to [-1, 1].
        """
        out: list[float] = []
        counter = 0
        seed = f"{model}:{text}".encode()
        while len(out) < self._dimensions:
            h = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            # 8 x 4-byte chunks per digest.
            for i in range(0, 32, 4):
                if len(out) >= self._dimensions:
                    break
                (chunk,) = struct.unpack(">I", h[i : i + 4])
                out.append((chunk / 0xFFFFFFFF) * 2.0 - 1.0)
            counter += 1
        return out
