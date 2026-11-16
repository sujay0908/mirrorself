"""AnthropicProvider request shape and error mapping.

No network and no API key: the SDK client is replaced with a recorder. The
SDK's own exception classes are used, so the mapping is tested against the
real hierarchy rather than a guess at it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from app.llm.errors import (  # noqa: E402
    LLMMisconfiguredError,
    LLMProviderError,
    LLMRateLimitedError,
    LLMRefusedError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.interface import LLMMessage, LLMRequest  # noqa: E402
from app.llm.providers.anthropic import AnthropicProvider  # noqa: E402


def _response(
    text: str = "hello",
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5-5",
    content: list[Any] | None = None,
    category: str | None = None,
) -> SimpleNamespace:
    blocks = content
    if blocks is None:
        blocks = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        model=model,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


class _Recorder:
    """Stands in for `AsyncAnthropic`. Records every call it receives."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.messages = SimpleNamespace(create=self._plain)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta))

    async def _next(self, kind: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((kind, kwargs))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def _plain(self, **kwargs: Any) -> Any:
        return await self._next("plain", kwargs)

    async def _beta(self, **kwargs: Any) -> Any:
        return await self._next("beta", kwargs)


def _provider(outcomes: list[Any], **options: Any) -> tuple[AnthropicProvider, _Recorder]:
    provider = AnthropicProvider(api_key="test-key-not-real", **options)
    recorder = _Recorder(outcomes)
    provider._client = recorder  # type: ignore[assignment]
    return provider, recorder


def _request(model: str = "claude-haiku-5-5", **overrides: Any) -> LLMRequest:
    base: dict[str, Any] = {
        "messages": [
            LLMMessage(role="system", content="You are Aurora."),
            LLMMessage(role="user", content="Hi"),
        ],
        "model": model,
    }
    base.update(overrides)
    return LLMRequest(**base)


def _status_error(cls: type, status: int, *, headers: dict[str, str] | None = None) -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(
        status,
        request=request,
        headers=headers or {},
        json={"type": "error", "error": {"type": "x", "message": "provider detail text"}},
    )
    return cls("provider detail text", response=response, body=response.json())


# ---------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_sampling_parameters_are_sent() -> None:
    """Current models and the current API version reject `temperature`, and
    the SDK no longer accepts the argument. Sending it failed every chat."""
    provider, recorder = _provider([_response()])
    await provider.generate_response(_request(temperature=0.0))
    _, kwargs = recorder.calls[0]
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in kwargs


@pytest.mark.asyncio
async def test_request_is_accepted_by_the_real_sdk_signature() -> None:
    """The keyword arguments the provider builds must bind to the installed
    SDK's `messages.create`. A stale argument is a TypeError on every call."""
    import inspect

    provider, recorder = _provider([_response()], effort="low")
    await provider.generate_response(_request(stop_sequences=["END"]))
    _, kwargs = recorder.calls[0]
    real = anthropic.AsyncAnthropic(api_key="test-key-not-real")
    inspect.signature(real.messages.create).bind(**kwargs)


@pytest.mark.asyncio
async def test_system_prompt_is_separated_from_the_turns() -> None:
    provider, recorder = _provider([_response()])
    await provider.generate_response(_request())
    _, kwargs = recorder.calls[0]
    assert kwargs["system"] == "You are Aurora."
    assert kwargs["messages"] == [{"role": "user", "content": "Hi"}]


@pytest.mark.asyncio
async def test_history_that_opens_on_a_twin_reply_is_trimmed() -> None:
    # A bounded window over a real conversation can start on an assistant
    # turn; the API requires the first turn to be the user's.
    provider, recorder = _provider([_response()])
    await provider.generate_response(
        _request(
            messages=[
                LLMMessage(role="system", content="sys"),
                LLMMessage(role="assistant", content="earlier reply"),
                LLMMessage(role="user", content="follow-up"),
                LLMMessage(role="assistant", content="answer"),
                LLMMessage(role="user", content="latest"),
            ]
        )
    )
    _, kwargs = recorder.calls[0]
    assert [m["role"] for m in kwargs["messages"]] == ["user", "assistant", "user"]


@pytest.mark.asyncio
async def test_output_ceiling_leaves_room_for_thinking() -> None:
    # The memory extractor asks for 1024 tokens of answer. On a model that
    # thinks first, 1024 total would be spent before the answer began.
    provider, recorder = _provider([_response()], max_tokens=16000)
    await provider.generate_response(_request(max_tokens=1024))
    assert recorder.calls[0][1]["max_tokens"] == 16000


@pytest.mark.asyncio
async def test_effort_is_only_sent_when_configured() -> None:
    provider, recorder = _provider([_response()])
    await provider.generate_response(_request())
    assert "output_config" not in recorder.calls[0][1]

    provider, recorder = _provider([_response()], effort="low")
    await provider.generate_response(_request())
    assert recorder.calls[0][1]["output_config"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_usage_and_serving_model_are_reported() -> None:
    provider, _ = _provider([_response("hi there", model="claude-sonnet-5-5")])
    out = await provider.generate_response(_request("claude-sonnet-5-5"))
    assert out.content == "hi there"
    assert out.provider == "anthropic"
    assert out.model == "claude-sonnet-5-5"
    assert (out.input_tokens, out.output_tokens) == (11, 7)


@pytest.mark.asyncio
async def test_thinking_blocks_are_not_treated_as_the_answer() -> None:
    provider, _ = _provider(
        [
            _response(
                content=[
                    SimpleNamespace(type="thinking", thinking=""),
                    SimpleNamespace(type="text", text="the answer"),
                ]
            )
        ]
    )
    out = await provider.generate_response(_request())
    assert out.content == "the answer"


# ---------------------------------------------------------------------
# Refusal handling and the server-side fallback
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_is_requested_on_models_that_support_it() -> None:
    provider, recorder = _provider([_response()])
    await provider.generate_response(_request("claude-sonnet-5-5"))
    kind, kwargs = recorder.calls[0]
    assert kind == "beta"
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]


@pytest.mark.asyncio
async def test_fallback_is_not_sent_to_models_that_reject_it() -> None:
    provider, recorder = _provider([_response()])
    await provider.generate_response(_request("claude-haiku-5-5"))
    kind, kwargs = recorder.calls[0]
    assert kind == "plain"
    assert "fallbacks" not in kwargs


@pytest.mark.asyncio
async def test_fallback_can_be_switched_off() -> None:
    provider, recorder = _provider([_response()], refusal_fallback=False)
    await provider.generate_response(_request("claude-sonnet-5-5"))
    assert recorder.calls[0][0] == "plain"


@pytest.mark.asyncio
async def test_a_rejected_fallback_option_does_not_take_chat_down() -> None:
    rejection = _status_error(anthropic.BadRequestError, 400)
    rejection.message = (
        "Unexpected value(s) `server-side-fallback-2026-07-01` for the `anthropic-beta` header."
    )
    provider, recorder = _provider([rejection, _response("still works"), _response("again")])

    out = await provider.generate_response(_request("claude-sonnet-5-5"))
    assert out.content == "still works"
    assert [kind for kind, _ in recorder.calls] == ["beta", "plain"]

    # It stops asking for the rest of the process's life.
    await provider.generate_response(_request("claude-sonnet-5-5"))
    assert recorder.calls[-1][0] == "plain"


@pytest.mark.asyncio
async def test_a_decline_is_a_controlled_error_not_an_empty_reply() -> None:
    provider, _ = _provider(
        [_response(content=[], stop_reason="refusal", category="general_harms")]
    )
    with pytest.raises(LLMRefusedError) as excinfo:
        await provider.generate_response(_request())
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "llm_refused"
    assert excinfo.value.details == {"category": "general_harms"}


@pytest.mark.asyncio
async def test_a_decline_without_details_is_still_handled() -> None:
    provider, _ = _provider([_response(content=[], stop_reason="refusal")])
    with pytest.raises(LLMRefusedError) as excinfo:
        await provider.generate_response(_request())
    assert excinfo.value.details == {"category": None}


@pytest.mark.asyncio
async def test_an_empty_reply_is_an_error_not_a_blank_message() -> None:
    provider, _ = _provider([_response("   ", stop_reason="max_tokens")])
    with pytest.raises(LLMProviderError) as excinfo:
        await provider.generate_response(_request())
    assert excinfo.value.code == "llm_empty_response"
    assert excinfo.value.status_code == 502


# ---------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sdk_error", "expected", "status", "code"),
    [
        (
            lambda: _status_error(anthropic.AuthenticationError, 401),
            LLMMisconfiguredError,
            503,
            "llm_provider_misconfigured",
        ),
        (
            lambda: _status_error(anthropic.PermissionDeniedError, 403),
            LLMMisconfiguredError,
            503,
            "llm_provider_misconfigured",
        ),
        (
            lambda: _status_error(anthropic.NotFoundError, 404),
            LLMMisconfiguredError,
            503,
            "llm_provider_misconfigured",
        ),
        (
            lambda: _status_error(anthropic.RateLimitError, 429, headers={"retry-after": "17"}),
            LLMRateLimitedError,
            429,
            "llm_rate_limited",
        ),
        (
            lambda: anthropic.APITimeoutError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            LLMTimeoutError,
            504,
            "llm_timeout",
        ),
        (
            lambda: anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            LLMUnavailableError,
            503,
            "llm_unavailable",
        ),
        (
            lambda: _status_error(anthropic.InternalServerError, 500),
            LLMUnavailableError,
            503,
            "llm_unavailable",
        ),
        (
            lambda: _status_error(anthropic.OverloadedError, 529),
            LLMUnavailableError,
            503,
            "llm_unavailable",
        ),
        (
            lambda: _status_error(anthropic.BadRequestError, 400),
            LLMProviderError,
            502,
            "llm_request_rejected",
        ),
    ],
)
@pytest.mark.asyncio
async def test_sdk_errors_map_to_controlled_api_errors(
    sdk_error: Any, expected: type, status: int, code: str
) -> None:
    provider, _ = _provider([sdk_error()])
    with pytest.raises(expected) as excinfo:
        await provider.generate_response(_request())
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code
    # The provider's own wording is for the key's operator, not the user.
    assert "provider detail text" not in excinfo.value.message


@pytest.mark.asyncio
async def test_rate_limit_passes_the_providers_retry_after_through() -> None:
    provider, _ = _provider(
        [_status_error(anthropic.RateLimitError, 429, headers={"retry-after": "17"})]
    )
    with pytest.raises(LLMRateLimitedError) as excinfo:
        await provider.generate_response(_request())
    assert excinfo.value.headers == {"Retry-After": "17"}


def test_client_is_built_with_a_deadline_and_bounded_retries() -> None:
    # The SDK default is a ten-minute timeout, far longer than a chat UI
    # can sensibly wait.
    provider = AnthropicProvider(api_key="test-key-not-real", timeout_seconds=12.5, max_retries=1)
    assert provider._client.max_retries == 1
    timeout = provider._client.timeout
    assert getattr(timeout, "read", timeout) == 12.5
