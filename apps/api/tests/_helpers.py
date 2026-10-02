"""Test-only helpers (not test functions themselves)."""

from __future__ import annotations

from typing import ClassVar

from app.llm.interface import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    LLMProvider,
    LLMRequest,
    LLMResponse,
)


class FixtureExtractionProvider(LLMProvider):
    """LLMProvider that returns a canned response — used to simulate the
    extraction LLM call deterministically.
    """

    provider_name: ClassVar[str] = "fixture-extract"

    def __init__(self, response_content: str, model: str = "fixture-model") -> None:
        self._content = response_content
        self._model = model
        self.calls: list[LLMRequest] = []

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            content=self._content,
            provider=self.provider_name,
            model=self._model,
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
        )


class FailingEmbeddingProvider(EmbeddingProvider):
    """EmbeddingProvider that always raises — proves the confirm endpoint
    survives embedding failures without losing the Memory.
    """

    provider_name: ClassVar[str] = "failing"
    _default_model = "failing-embed"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise RuntimeError("embedding provider intentionally failing for test")
