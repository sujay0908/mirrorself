"""AnthropicProvider — Claude via the Anthropic API.

The `anthropic` SDK is imported lazily so `pip install personal-ai-twin-api`
without the `[anthropic]` extra still works for mock-only setups.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.common.errors import APIError
from app.llm.errors import (
    LLMMisconfiguredError,
    LLMProviderError,
    LLMRateLimitedError,
    LLMRefusedError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse
from app.observability.logging import get_logger

logger = get_logger(__name__)

_REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Models on which a safety-classifier decline can be retried server-side on
# another model. Anything else is sent without the option, because models
# outside this set reject it.
_REFUSAL_FALLBACK_MODELS: tuple[str, ...] = (
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
)


class AnthropicProvider(LLMProvider):
    provider_name: ClassVar[str] = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 45.0,
        max_retries: int = 1,
        max_tokens: int = 16000,
        effort: str | None = None,
        refusal_fallback: bool = True,
    ) -> None:
        try:
            import anthropic  # type: ignore[import-not-found,unused-ignore]
        except ImportError as exc:  # pragma: no cover
            raise APIError(
                "anthropic SDK not installed. Install with `pip install "
                "personal-ai-twin-api[anthropic]`.",
                code="dependency_missing",
                status_code=500,
            ) from exc
        self._sdk = anthropic
        # The SDK retries timeouts, 429s and 5xx itself with backoff, so the
        # longest a call can take is about timeout * (max_retries + 1).
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._max_tokens = max_tokens
        self._effort = effort
        self._refusal_fallback = refusal_fallback

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        system_prompt, chat_messages = _split_system(request)
        # No sampling parameters: current models and the current API version
        # reject `temperature`/`top_p`/`top_k`, and the SDK no longer accepts
        # them. `LLMRequest.temperature` remains for providers that take it.
        kwargs: dict[str, Any] = {
            "model": request.model,
            # The caller's figure is the visible answer it wants. Current
            # models think before answering and that thinking is drawn from
            # the same allowance, so a small ceiling truncates the reply.
            "max_tokens": max(request.max_tokens, self._max_tokens),
            "messages": chat_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences
        if self._effort:
            kwargs["output_config"] = {"effort": self._effort}

        resp = await self._create(kwargs)

        # A decline is a successful HTTP response; it has to be checked before
        # the content is read, which is empty or partial in that case.
        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None)
            logger.info("llm.refused", provider=self.provider_name, category=category)
            raise LLMRefusedError(
                "The AI model declined to respond to this message.",
                details={"category": category},
            )

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            logger.warning(
                "llm.empty_response",
                provider=self.provider_name,
                stop_reason=resp.stop_reason,
            )
            raise LLMProviderError(
                "The AI model returned an empty reply. Please try again.",
                code="llm_empty_response",
            )
        return LLMResponse(
            content=text,
            provider=self.provider_name,
            model=resp.model,
            input_tokens=resp.usage.input_tokens if resp.usage else None,
            output_tokens=resp.usage.output_tokens if resp.usage else None,
            finish_reason=resp.stop_reason,
        )

    async def _create(self, kwargs: dict[str, Any]) -> Any:
        sdk = self._sdk
        with_fallback = self._refusal_fallback and kwargs["model"].startswith(
            _REFUSAL_FALLBACK_MODELS
        )
        try:
            if with_fallback:
                return await self._client.beta.messages.create(
                    betas=[_REFUSAL_FALLBACK_BETA],
                    fallbacks="default",
                    **kwargs,
                )
            return await self._client.messages.create(**kwargs)
        except sdk.BadRequestError as exc:
            if with_fallback and _rejects_fallback_option(exc):
                # The opt-in itself was refused (not enabled for this
                # organisation). Chat matters more than the fallback: stop
                # asking for it and send the plain request.
                self._refusal_fallback = False
                logger.warning("llm.refusal_fallback_disabled", provider=self.provider_name)
                try:
                    return await self._client.messages.create(**kwargs)
                except sdk.APIError as retry_exc:
                    raise self._translate(retry_exc) from retry_exc
            raise self._translate(exc) from exc
        except sdk.APIError as exc:
            raise self._translate(exc) from exc

    def _translate(self, exc: Any) -> APIError:
        """Map an SDK error onto the API's own error types.

        The provider's message is logged and not forwarded: it is written for
        the operator of the API key, and the user can act on none of it.
        """
        sdk = self._sdk
        status = getattr(exc, "status_code", None)
        logger.warning(
            "llm.request_failed",
            provider=self.provider_name,
            error_type=type(exc).__name__,
            status=status,
            provider_request_id=getattr(exc, "request_id", None),
        )
        if isinstance(exc, sdk.AuthenticationError | sdk.PermissionDeniedError):
            return LLMMisconfiguredError(
                "The AI provider rejected this service's credentials. "
                "The operator needs to check the configured API key."
            )
        if isinstance(exc, sdk.NotFoundError):
            return LLMMisconfiguredError(
                "The configured AI model is not available. "
                "The operator needs to check the configured model."
            )
        if isinstance(exc, sdk.RateLimitError):
            retry_after = exc.response.headers.get("retry-after", "30")
            return LLMRateLimitedError(
                "The AI provider is rate limiting requests. Please try again shortly.",
                headers={"Retry-After": retry_after},
            )
        if isinstance(exc, sdk.APITimeoutError):
            return LLMTimeoutError("The AI model took too long to respond. Please try again.")
        if isinstance(exc, sdk.APIConnectionError):
            return LLMUnavailableError(
                "The AI provider could not be reached. Please try again shortly."
            )
        if isinstance(exc, sdk.APIStatusError) and exc.status_code >= 500:
            return LLMUnavailableError(
                "The AI provider is temporarily unavailable. Please try again shortly.",
                headers={"Retry-After": "10"},
            )
        return LLMProviderError(
            "The AI provider could not process this request.",
            code="llm_request_rejected",
        )


def _rejects_fallback_option(exc: Any) -> bool:
    message = str(getattr(exc, "message", "")).lower()
    return "anthropic-beta" in message or "fallbacks" in message


def _split_system(request: LLMRequest) -> tuple[str, list[dict[str, str]]]:
    """Anthropic wants `system` as a separate arg, not a message role.

    The conversation must open with a user turn. History is a bounded window
    over the real conversation, so it can begin on a twin reply; those leading
    assistant turns are dropped rather than sent and rejected.
    """
    system_chunks: list[str] = []
    messages: list[dict[str, str]] = []
    for m in request.messages:
        if m.role == "system":
            system_chunks.append(m.content)
        elif m.role == "assistant" and not messages:
            continue
        else:
            messages.append({"role": m.role, "content": m.content})
    return "\n\n".join(system_chunks), messages
