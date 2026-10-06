"""Reflection extractor unit tests (Sprint 7).

The extractor is a pure async function over an injected LLM provider.
These tests pin:
- strict JSON parsing (bad JSON → empty drafts, `parse_error`)
- per-kind payload validation (wrong payload shape → drop that draft)
- "unknown kind" drafts are dropped silently
- provider failure → empty drafts, `provider_error:<ExceptionClass>`
- empty response → `empty_response`
- empty inputs → no LLM call, empty drafts
- happy path: well-formed JSON yields validated drafts
- the LLM call carries `metadata={"purpose": "reflection_extraction"}`
"""

from __future__ import annotations

import json
import uuid
from typing import ClassVar

import pytest

from app.llm.interface import LLMRequest, LLMResponse
from app.reflection.extractor import ReflectionExtractionResult, ReflectionExtractor


class _CannedProvider:
    """Returns a pre-canned LLMResponse for a single call."""

    provider_name: ClassVar[str] = "canned"

    def __init__(self, content: str, *, model: str = "canned-model") -> None:
        self._content = content
        self.calls: list[LLMRequest] = []

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            content=self._content,
            provider=self.provider_name,
            model=request.model,
            finish_reason="stop",
        )


class _ExplodingProvider:
    provider_name: ClassVar[str] = "boom"

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("boom")


def _happy_envelope() -> str:
    """One of each kind, all with valid payload shapes."""
    return json.dumps(
        {
            "candidates": [
                {
                    "kind": "insight",
                    "payload": {
                        "kind": "insight",
                        "headline": "You chat with the Twin before dinner",
                        "body": "In the last 10 turns three were between 6pm and 7pm.",
                        "rationale": "Observed timing on three sources.",
                    },
                    "rationale": "Observed timing on three sources.",
                    "source_memory_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                    "source_goal_ids": [],
                    "confidence": 0.6,
                    "importance": 0.4,
                },
                {
                    "kind": "profile_update",
                    "payload": {
                        "kind": "profile_update",
                        "field": "communication_style_notes",
                        "current_value": None,
                        "proposed_value": "Prefers concise replies in the morning.",
                        "rationale": "Observed over three morning sessions.",
                    },
                    "rationale": "Observed over three morning sessions.",
                    "source_memory_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                    "source_goal_ids": [],
                    "confidence": 0.8,
                    "importance": 0.6,
                },
            ]
        }
    )


@pytest.mark.asyncio
async def test_extractor_happy_path_returns_validated_drafts() -> None:
    provider = _CannedProvider(_happy_envelope())
    out = await ReflectionExtractor(provider, "canned-model").extract(
        memories=[(uuid.uuid4(), "FACT", "lives in Lisbon")],
        goals=[],
        recent_turns=[("user", "hi"), ("twin", "hello")],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.error is None
    assert len(out.drafts) == 2
    assert {d.kind for d in out.drafts} == {"insight", "profile_update"}
    # The provider was called exactly once, with the reflection purpose.
    assert len(provider.calls) == 1
    assert provider.calls[0].metadata.get("purpose") == "reflection_extraction"


@pytest.mark.asyncio
async def test_extractor_parse_error_returns_empty_with_error_tag() -> None:
    provider = _CannedProvider("this is not json at all")
    out = await ReflectionExtractor(provider, "canned-model").extract(
        memories=[(uuid.uuid4(), "FACT", "a fact")],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.drafts == []
    assert out.error == "parse_error"


@pytest.mark.asyncio
async def test_extractor_malformed_payload_is_silently_dropped() -> None:
    """A draft whose payload fails per-kind validation (e.g. memory_dedup
    missing `canonical_memory_id`) is DROPPED from the result; the
    envelope is still a success as long as other drafts are valid.
    """
    envelope = json.dumps(
        {
            "candidates": [
                {
                    "kind": "memory_dedup",
                    # Missing canonical_memory_id → should be dropped.
                    "payload": {
                        "kind": "memory_dedup",
                        "superseded_memory_id": str(uuid.uuid4()),
                        "rationale": "same thing",
                    },
                    "rationale": "same thing",
                    "source_memory_ids": [],
                    "source_goal_ids": [],
                    "confidence": 0.9,
                    "importance": 0.5,
                },
                {
                    "kind": "insight",
                    "payload": {
                        "kind": "insight",
                        "headline": "a thing",
                        "body": "a longer thing",
                        "rationale": "noticed",
                    },
                    "rationale": "noticed",
                    "source_memory_ids": [],
                    "source_goal_ids": [],
                    "confidence": 0.5,
                    "importance": 0.5,
                },
            ]
        }
    )
    out = await ReflectionExtractor(_CannedProvider(envelope), "m").extract(
        memories=[(uuid.uuid4(), "FACT", "a fact")],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.error is None
    assert len(out.drafts) == 1
    assert out.drafts[0].kind == "insight"


@pytest.mark.asyncio
async def test_extractor_unknown_kind_is_silently_dropped() -> None:
    envelope = json.dumps(
        {
            "candidates": [
                {
                    "kind": "mood_update",  # not in REFLECTION_KINDS
                    "payload": {"kind": "mood_update", "mood": "melancholy"},
                    "rationale": "x",
                    "source_memory_ids": [],
                    "source_goal_ids": [],
                    "confidence": 0.5,
                    "importance": 0.5,
                }
            ]
        }
    )
    # Pydantic rejects the kind at ReflectionDraft; the envelope parse
    # becomes a validation failure for the whole envelope, which maps
    # to `parse_error`. Either way the drafts are empty.
    out = await ReflectionExtractor(_CannedProvider(envelope), "m").extract(
        memories=[(uuid.uuid4(), "FACT", "a")],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.drafts == []


@pytest.mark.asyncio
async def test_extractor_absorbs_provider_exception() -> None:
    out = await ReflectionExtractor(_ExplodingProvider(), "m").extract(
        memories=[(uuid.uuid4(), "FACT", "a")],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.drafts == []
    assert out.error == "provider_error:RuntimeError"


@pytest.mark.asyncio
async def test_extractor_handles_empty_response() -> None:
    out = await ReflectionExtractor(_CannedProvider(""), "m").extract(
        memories=[(uuid.uuid4(), "FACT", "a")],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.drafts == []
    assert out.error == "empty_response"


@pytest.mark.asyncio
async def test_extractor_short_circuits_on_empty_inputs() -> None:
    """No memories + no goals + no recent turns → do not call the LLM."""
    provider = _CannedProvider(_happy_envelope())
    out = await ReflectionExtractor(provider, "m").extract(
        memories=[],
        goals=[],
        recent_turns=[],
        profile_style="warm",
        profile_notes=None,
        basic_profile={},
    )
    assert out.drafts == []
    assert out.error is None
    assert provider.calls == []  # no LLM call made


@pytest.mark.asyncio
async def test_extractor_result_matches_dataclass_shape() -> None:
    out = ReflectionExtractionResult()
    assert out.drafts == []
    assert out.error is None
