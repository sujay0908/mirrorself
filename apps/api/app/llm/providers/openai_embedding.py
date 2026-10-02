"""OpenAIEmbeddingProvider — OpenAI embeddings via lazy SDK import.

Mirrors the pattern used by `AnthropicProvider` / `OpenAIProvider`:
`import openai` happens inside `__init__` so the SDK is not required for
development or tests when `EMBEDDING_PROVIDER=mock`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.common.errors import APIError
from app.llm.interface import EmbeddingProvider, EmbeddingRequest, EmbeddingResponse


class OpenAIEmbeddingProvider(EmbeddingProvider):
    provider_name: ClassVar[str] = "openai"

    def __init__(self, *, api_key: str, model: str, dimensions: int) -> None:
        try:
            import openai  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise APIError(
                "openai SDK not installed. Install with `pip install "
                "personal-ai-twin-api[openai]`.",
                code="dependency_missing",
                status_code=500,
            ) from exc
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._default_model = model
        self._dimensions = dimensions

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": request.texts,
        }
        # `text-embedding-3-*` accept a dimensions parameter to produce
        # shorter vectors; older models reject it. Pass it when the setting
        # differs from the model's native size.
        if self._dimensions:
            kwargs["dimensions"] = self._dimensions
        try:
            resp = await self._client.embeddings.create(**kwargs)
        except Exception as exc:  # pragma: no cover
            raise APIError(
                f"OpenAI embeddings error: {exc}",
                code="embedding_provider_error",
                status_code=502,
            ) from exc

        vectors = [item.embedding for item in resp.data]
        reported_dim = len(vectors[0]) if vectors else self._dimensions
        return EmbeddingResponse(
            embeddings=vectors,
            model=resp.model,
            provider=self.provider_name,
            dimensions=reported_dim,
        )
