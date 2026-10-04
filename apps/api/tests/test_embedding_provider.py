"""EmbeddingProvider — MockEmbeddingProvider + registry."""

from __future__ import annotations

import pytest

from app.config import get_settings, reset_settings_cache
from app.llm.interface import EmbeddingProvider, EmbeddingRequest
from app.llm.providers.mock_embedding import MockEmbeddingProvider
from app.llm.registry import get_embedding_provider, reset_provider_cache


@pytest.mark.asyncio
async def test_mock_embedding_is_deterministic() -> None:
    provider = MockEmbeddingProvider(dimensions=16, model="mock-embed-1")
    r1 = await provider.embed(EmbeddingRequest(texts=["hello"], model="mock-embed-1"))
    r2 = await provider.embed(EmbeddingRequest(texts=["hello"], model="mock-embed-1"))
    assert r1.embeddings == r2.embeddings


@pytest.mark.asyncio
async def test_mock_embedding_differs_across_inputs() -> None:
    provider = MockEmbeddingProvider(dimensions=16, model="mock-embed-1")
    r = await provider.embed(EmbeddingRequest(texts=["one", "two"], model="mock-embed-1"))
    assert r.embeddings[0] != r.embeddings[1]


@pytest.mark.asyncio
async def test_mock_embedding_dimensions_match_config() -> None:
    provider = MockEmbeddingProvider(dimensions=64, model="mock-embed-1")
    r = await provider.embed(EmbeddingRequest(texts=["abc"], model="mock-embed-1"))
    assert r.dimensions == 64
    assert len(r.embeddings[0]) == 64


@pytest.mark.asyncio
async def test_mock_embedding_values_in_range() -> None:
    provider = MockEmbeddingProvider(dimensions=32, model="mock-embed-1")
    r = await provider.embed(EmbeddingRequest(texts=["x"], model="mock-embed-1"))
    vec = r.embeddings[0]
    assert all(-1.0 <= v <= 1.0 for v in vec)


@pytest.mark.asyncio
async def test_mock_embedding_odd_dimensions() -> None:
    """Non-multiple-of-8 dimensions still produce exactly N floats."""
    provider = MockEmbeddingProvider(dimensions=17, model="mock-embed-1")
    r = await provider.embed(EmbeddingRequest(texts=["x"], model="mock-embed-1"))
    assert len(r.embeddings[0]) == 17


def test_registry_returns_mock_embedding() -> None:
    reset_settings_cache()
    reset_provider_cache()
    provider = get_embedding_provider()
    assert isinstance(provider, EmbeddingProvider)
    assert provider.provider_name == "mock"


def test_mock_embedding_provider_satisfies_protocol() -> None:
    assert isinstance(
        MockEmbeddingProvider(dimensions=8, model="x"),
        EmbeddingProvider,
    )


def test_configured_dimensions_round_trip() -> None:
    reset_settings_cache()
    settings = get_settings()
    # Default value from `.env.example` is 1536.
    assert settings.embedding_dimensions == 1536
