"""OpenAIProvider — second implementation of the provider contract.

Kept deliberately thin and not used in production. It proves the abstraction
holds more than one vendor; it has not been exercised against current OpenAI
models, so treat it as unverified before selecting `LLM_PROVIDER=openai`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.common.errors import APIError
from app.llm.errors import LLMProviderError
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse
from app.observability.logging import get_logger

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    provider_name: ClassVar[str] = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 45.0,
        max_retries: int = 1,
    ) -> None:
        try:
            import openai  # type: ignore[import-not-found,unused-ignore]
        except ImportError as exc:  # pragma: no cover
            raise APIError(
                "openai SDK not installed. Install with `pip install "
                "personal-ai-twin-api[openai]`.",
                code="dependency_missing",
                status_code=500,
            ) from exc
        self._client = openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=max_retries
        )

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
            # The vendor's text is for the operator; it is logged by type only
            # and never forwarded to the caller.
            logger.warning(
                "llm.request_failed",
                provider=self.provider_name,
                error_type=type(exc).__name__,
            )
            raise LLMProviderError("The AI provider could not process this request.") from exc
        choice = resp.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            provider=self.provider_name,
            model=resp.model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else None,
            output_tokens=resp.usage.completion_tokens if resp.usage else None,
            finish_reason=choice.finish_reason,
        )
