"""LLM provider abstraction — MockProvider and registry."""

from __future__ import annotations

import pytest

from app.llm.interface import LLMMessage, LLMProvider, LLMRequest
from app.llm.providers.mock import MockProvider
from app.llm.registry import get_llm_provider, reset_provider_cache


@pytest.mark.asyncio
async def test_mock_provider_echoes_last_user_message() -> None:
    provider = MockProvider()
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content="You are a twin."),
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
            LLMMessage(role="user", content="what's up?"),
        ],
        model="mock-echo",
    )
    resp = await provider.generate_response(request)
    assert resp.provider == "mock"
    assert resp.model == "mock-echo"
    assert resp.content == "twin(mock): I heard you say: what's up?"
    assert resp.input_tokens is not None
    assert resp.output_tokens is not None


@pytest.mark.asyncio
async def test_mock_provider_handles_no_user_message() -> None:
    provider = MockProvider()
    resp = await provider.generate_response(
        LLMRequest(
            messages=[LLMMessage(role="system", content="hi")], model="mock-echo"
        )
    )
    assert "no user message" in resp.content


def test_registry_returns_mock_when_configured() -> None:
    reset_provider_cache()
    provider = get_llm_provider()
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "mock"


def test_mock_provider_satisfies_protocol() -> None:
    # Runtime-checkable Protocol assertion — this is the "no vendor SDK import
    # in domain code" rule made testable.
    assert isinstance(MockProvider(), LLMProvider)
