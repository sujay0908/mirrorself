"""OpenAIProvider — stub for parity.

Not exercised in Sprint 1. Wired here so the provider abstraction is
demonstrated to hold more than one implementation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.common.errors import APIError
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse


class OpenAIProvider(LLMProvider):
    provider_name: ClassVar[str] = "openai"

    def __init__(self, api_key: str) -> None:
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

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop_sequences:
            kwargs["stop"] = request.stop_sequences
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # pragma: no cover
            raise APIError(
                f"OpenAI API error: {exc}",
                code="llm_provider_error",
                status_code=502,
            ) from exc
        choice = resp.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            provider=self.provider_name,
            model=resp.model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else None,
            output_tokens=resp.usage.completion_tokens if resp.usage else None,
            finish_reason=choice.finish_reason,
        )
