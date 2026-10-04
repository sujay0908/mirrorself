"""Runtime provider selection — LLM and Embedding.

Both registries follow the same pattern: a factory function per provider,
cached by name. Factories lazy-import SDKs so `pip install` without extras
still boots the app for mock-only development.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.common.errors import APIError
from app.config import Settings, get_settings
from app.llm.interface import EmbeddingProvider, LLMProvider


class ProviderNotConfiguredError(APIError):
    code = "llm_provider_not_configured"
    status_code = 500


# -------- LLM providers --------

LLMProviderFactory = Callable[[Settings], LLMProvider]


def _make_mock(settings: Settings) -> LLMProvider:
    from app.llm.providers.mock import MockProvider

    return MockProvider()


def _make_anthropic(settings: Settings) -> LLMProvider:
    from app.llm.providers.anthropic import AnthropicProvider

    if not settings.anthropic_api_key:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY is not set but LLM_PROVIDER=anthropic.")
    return AnthropicProvider(api_key=settings.anthropic_api_key)


def _make_openai(settings: Settings) -> LLMProvider:
    from app.llm.providers.openai import OpenAIProvider

    if not settings.openai_api_key:
        raise ProviderNotConfiguredError("OPENAI_API_KEY is not set but LLM_PROVIDER=openai.")
    return OpenAIProvider(api_key=settings.openai_api_key)


def _make_local(settings: Settings) -> LLMProvider:
    from app.llm.providers.local import LocalProvider

    return LocalProvider()


_LLM_FACTORIES: dict[str, LLMProviderFactory] = {
    "mock": _make_mock,
    "anthropic": _make_anthropic,
    "openai": _make_openai,
    "local": _make_local,
}


@lru_cache(maxsize=8)
def _get_llm_provider_cached(name: str) -> LLMProvider:
    settings = get_settings()
    factory = _LLM_FACTORIES.get(name)
    if factory is None:
        raise ProviderNotConfiguredError(f"Unknown LLM provider: {name!r}")
    return factory(settings)


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency: returns the provider selected by `LLM_PROVIDER`."""
    return _get_llm_provider_cached(get_settings().llm_provider)


# -------- Embedding providers --------

EmbeddingProviderFactory = Callable[[Settings], EmbeddingProvider]


def _make_mock_embedding(settings: Settings) -> EmbeddingProvider:
    from app.llm.providers.mock_embedding import MockEmbeddingProvider

    return MockEmbeddingProvider(
        dimensions=settings.embedding_dimensions,
        model=settings.embedding_model,
    )


def _make_openai_embedding(settings: Settings) -> EmbeddingProvider:
    from app.llm.providers.openai_embedding import OpenAIEmbeddingProvider

    if not settings.openai_api_key:
        raise ProviderNotConfiguredError("OPENAI_API_KEY is not set but EMBEDDING_PROVIDER=openai.")
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


_EMBEDDING_FACTORIES: dict[str, EmbeddingProviderFactory] = {
    "mock": _make_mock_embedding,
    "openai": _make_openai_embedding,
}


@lru_cache(maxsize=8)
def _get_embedding_provider_cached(name: str) -> EmbeddingProvider:
    settings = get_settings()
    factory = _EMBEDDING_FACTORIES.get(name)
    if factory is None:
        raise ProviderNotConfiguredError(f"Unknown embedding provider: {name!r}")
    return factory(settings)


def get_embedding_provider() -> EmbeddingProvider:
    """FastAPI dependency: returns the provider selected by
    `EMBEDDING_PROVIDER`.
    """
    return _get_embedding_provider_cached(get_settings().embedding_provider)


def reset_provider_cache() -> None:
    """Test-only: forget cached providers (LLM and embedding)."""
    _get_llm_provider_cached.cache_clear()
    _get_embedding_provider_cached.cache_clear()
