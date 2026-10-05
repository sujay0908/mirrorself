"""Intent detector unit tests (Sprint 6).

The rule-based detector is a deterministic, provider-independent
scaffold. These tests pin:

- the Sprint-6 vocabulary (THINK / LEARN / PLAN / REFLECT / TALK /
  TASK / UNKNOWN)
- the detector never raises
- repeated detection is byte-for-byte identical
- UNKNOWN is the safe fallback for anything the rules do not match

The rules themselves are not a classifier and tests here do not pretend
otherwise — each case uses a phrase the detector's own rule file
explicitly lists.
"""

from __future__ import annotations

import asyncio

import pytest

from app.conversation.intent import (
    DEFAULT_INTENT_DETECTOR,
    Intent,
    IntentResult,
    RuleBasedIntentDetector,
    detect_intent_safely,
)


def _detect(msg: str) -> IntentResult:
    return RuleBasedIntentDetector().detect_sync(msg)


# ---------------------------------------------------------------------
# Vocabulary coverage — one explicit test per intent
# ---------------------------------------------------------------------


def test_think_detected_on_think_phrase() -> None:
    result = _detect("I'm thinking about leaving my job.")
    assert result.intent is Intent.THINK
    assert result.confidence >= 0.7


def test_learn_detected_on_how_question() -> None:
    result = _detect("How do kubernetes operators work?")
    assert result.intent is Intent.LEARN
    assert result.confidence >= 0.7


def test_plan_detected_on_plan_phrase() -> None:
    result = _detect("Let's plan the next quarter.")
    assert result.intent is Intent.PLAN
    assert result.confidence >= 0.7


def test_reflect_detected_on_hindsight_phrase() -> None:
    result = _detect("Looking back, I think the pivot was the right call.")
    assert result.intent is Intent.REFLECT
    assert result.confidence >= 0.7


def test_talk_detected_on_short_greeting() -> None:
    result = _detect("Hey, how are you?")
    assert result.intent is Intent.TALK
    assert result.confidence >= 0.4


def test_task_detected_on_imperative_verb() -> None:
    result = _detect("Draft a reply to this email.")
    assert result.intent is Intent.TASK
    assert result.confidence >= 0.7


def test_unknown_fallback_on_long_unmatched_message() -> None:
    """A longer message that matches no rule and is above the TALK word
    cap falls through to UNKNOWN with confidence 0.0.
    """
    msg = (
        "The sky is turbulent today and I am looking at the clouds while "
        "I sit by the window watching the day slip by in quiet moments."
    )
    result = _detect(msg)
    assert result.intent is Intent.UNKNOWN
    assert result.confidence == 0.0


# ---------------------------------------------------------------------
# Edge-case / safety
# ---------------------------------------------------------------------


def test_empty_message_returns_unknown() -> None:
    result = _detect("")
    assert result.intent is Intent.UNKNOWN
    assert result.reason.startswith("fallback:")


def test_whitespace_message_returns_unknown() -> None:
    result = _detect("   \n\t  ")
    assert result.intent is Intent.UNKNOWN


def test_non_string_input_returns_unknown_without_raising() -> None:
    """The detector defends against caller bugs. A non-string input
    must not crash the chat path.
    """
    result = RuleBasedIntentDetector().detect_sync(42)  # type: ignore[arg-type]
    assert result.intent is Intent.UNKNOWN
    assert result.reason == "error:non_string_input"


def test_short_unknown_message_falls_back_to_talk() -> None:
    """A short message with no strong signal is routed to TALK with low
    confidence (0.4) rather than UNKNOWN — casual back-and-forth is the
    common case.
    """
    result = _detect("okay sure")
    assert result.intent is Intent.TALK
    assert result.confidence == pytest.approx(0.4)
    assert result.reason == "fallback:short_message"


# ---------------------------------------------------------------------
# Determinism + rule precedence
# ---------------------------------------------------------------------


def test_detection_is_deterministic_across_repeats() -> None:
    msg = "Help me plan my product management interviews."
    first = _detect(msg)
    for _ in range(10):
        again = _detect(msg)
        assert again == first


def test_reflect_wins_over_plan_when_both_phrases_appear() -> None:
    """A reflective framing wins over a planning phrase so that
    "looking back I planned..." reads as REFLECT, not PLAN.
    """
    result = _detect("Looking back, I planned the launch poorly.")
    assert result.intent is Intent.REFLECT


def test_intent_enum_values_match_sprint_6_vocabulary() -> None:
    """Guards against a silent vocabulary drift between the enum and
    the policy / renderer tables.
    """
    assert {i.value for i in Intent} == {
        "THINK",
        "LEARN",
        "PLAN",
        "REFLECT",
        "TALK",
        "TASK",
        "UNKNOWN",
    }


# ---------------------------------------------------------------------
# Async wrapper + failure isolation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_detect_matches_sync_detect() -> None:
    msg = "Teach me what idempotency means."
    sync_result = RuleBasedIntentDetector().detect_sync(msg)
    async_result = await RuleBasedIntentDetector().detect(msg)
    assert async_result == sync_result


@pytest.mark.asyncio
async def test_detect_intent_safely_wraps_detector_exception() -> None:
    """A detector that raises must become a safe UNKNOWN result."""

    class _ExplodingDetector:
        detector_name = "boom"

        async def detect(self, user_message: str) -> IntentResult:
            raise RuntimeError("boom")

    out = await detect_intent_safely(_ExplodingDetector(), "anything")
    assert out.intent is Intent.UNKNOWN
    assert out.confidence == 0.0
    assert out.reason.startswith("error:")


@pytest.mark.asyncio
async def test_default_detector_is_rule_based() -> None:
    """A guard so a future tweak that swaps the default to a
    model-backed detector trips a visible test. If the default is
    legitimately changing, update this test deliberately.
    """
    assert isinstance(DEFAULT_INTENT_DETECTOR, RuleBasedIntentDetector)
    assert DEFAULT_INTENT_DETECTOR.detector_name == "rule-based-v1"


def test_asyncio_run_still_works() -> None:
    """Smoke test that `.detect(...)` is awaitable from a plain
    asyncio.run — ensures the async signature stays correct.
    """
    out = asyncio.run(RuleBasedIntentDetector().detect("let's plan the week"))
    assert out.intent is Intent.PLAN
