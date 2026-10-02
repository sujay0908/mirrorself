"""AnthropicProvider — Claude via the Anthropic API.

The `anthropic` SDK is imported lazily so `pip install personal-ai-twin-api`
without the `[anthropic]` extra still works for mock-only setups.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.common.errors import APIError
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse


class AnthropicProvider(LLMProvider):
    provider_name: ClassVar[str] = "anthropic"

    def __init__(self, api_key: str) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise APIError(
                "anthropic SDK not installed. Install with `pip install "
                "personal-ai-twin-api[anthropic]`.",
                code="dependency_missing",
                status_code=500,
            ) from exc
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        system_prompt, chat_messages = _split_system(request)
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": chat_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences

        try:
            resp = await self._client.messages.create(**kwargs)
        except Exception as exc:  # pragma: no cover
            raise APIError(
                f"Anthropic API error: {exc}",
                code="llm_provider_error",
                status_code=502,
            ) from exc

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return LLMResponse(
            content=text,
            provider=self.provider_name,
            model=resp.model,
            input_tokens=resp.usage.input_tokens if resp.usage else None,
            output_tokens=resp.usage.output_tokens if resp.usage else None,
            finish_reason=resp.stop_reason,
        )


def _split_system(request: LLMRequest) -> tuple[str, list[dict[str, str]]]:
    """Anthropic wants `system` as a separate arg, not a message role."""
    system_chunks: list[str] = []
    messages: list[dict[str, str]] = []
    for m in request.messages:
        if m.role == "system":
            system_chunks.append(m.content)
        else:
            messages.append({"role": m.role, "content": m.content})
    return "\n\n".join(system_chunks), messages
