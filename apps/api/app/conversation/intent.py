"""Intent detection for the Twin Engine (Sprint 6).

Sprint 5 landed the context-aware pipeline:

    user msg → memory retrieval → goal retrieval → context builder
             → prompt renderer → LLM → response

Sprint 6 inserts one step at the front:

    user msg → INTENT DETECTION → context policy → (same pipeline)

This module is the domain-level intent abstraction. It is deliberately
provider-agnostic: the only concrete `IntentDetector` shipped here is a
small, deterministic rule-based matcher so tests, dev loops and CI never
have to call an external model. The abstraction is designed so a future
`LLMBackedIntentDetector` (or any other implementation) can slot in
without touching callers.

Design rules enforced here:

- The detector NEVER raises. On any error — unexpected input shape,
  internal bug, timing out, anything — the public API returns
  `IntentResult(intent=Intent.UNKNOWN, confidence=0.0, reason=...)`.
  Intent-detection failure must never fail a chat turn.
- No side effects. The detector reads a string and returns a value; it
  does not touch the DB, call an LLM provider by default, log user
  content, or mutate anything.
- Deterministic. The rule-based implementation is a pure function. The
  same message yields the same `IntentResult`, so tests can pin exact
  outputs and the audit layer can replay turns.
- The initial rule-based detector is NOT claiming semantic
  understanding. It matches lower-cased phrases and keywords and ranks
  the first match in a documented precedence order. This is explicitly
  a scaffold for Sprint 6 (see `docs/architecture/intent-engine.md`);
  a model-backed detector is a later swap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable


class Intent(StrEnum):
    """Sprint 6 intent vocabulary.

    `StrEnum` (Python 3.11+) so the value serializes directly to JSON
    and shows up as plain text in the twin message's `metadata_json`
    without a special encoder.
    """

    THINK = "THINK"
    LEARN = "LEARN"
    PLAN = "PLAN"
    REFLECT = "REFLECT"
    TALK = "TALK"
    TASK = "TASK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IntentResult:
    """What `IntentDetector.detect` returns.

    `intent`      — the resolved Intent.
    `confidence`  — in [0.0, 1.0]. The rule-based detector uses coarse
                    bands (0.0 for UNKNOWN, 0.4 for a weak default, 0.7
                    for a keyword match, 0.9 for a strong phrase match).
                    These are not probabilities; they are a stable
                    ordering signal for the audit log.
    `reason`      — short machine-readable tag describing WHY the
                    detector returned this intent (e.g. "keyword:plan",
                    "fallback:short_message", "error:unhandled").
                    Never contains user content.
    `metadata`    — opaque bag for extra signals the detector wants to
                    record. Must not contain raw user content.
    """

    intent: Intent
    confidence: float
    reason: str
    metadata: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class IntentDetector(Protocol):
    """The one contract the conversation pipeline depends on.

    Any implementation (rule-based, model-backed, hybrid) must satisfy
    this. The method is async so a future model-backed detector can be
    swapped in without changing callers.
    """

    detector_name: ClassVar[str]

    async def detect(self, user_message: str) -> IntentResult: ...


# ---------------------------------------------------------------------
# Rule-based implementation
# ---------------------------------------------------------------------
#
# Rules are listed in PRECEDENCE ORDER. The first matching rule wins.
# Order matters: "plan my week" matches PLAN before it matches TASK's
# "my" trigger. Each rule is a (intent, confidence, reason, pattern)
# tuple; `pattern` is a compiled case-insensitive regex over the raw
# user message with word boundaries where appropriate.
#
# This is a scaffold, not a classifier. The confidence bands are
# intentional step values so the audit log stays legible.


_WORD_BOUNDARY = r"\b"


def _phrase(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# A rule: (intent, confidence, reason-tag, compiled pattern).
# Keep this list short and well-chosen rather than exhaustive.
_RULES: list[tuple[Intent, float, str, re.Pattern[str]]] = [
    # ---- REFLECT (checked before PLAN so "looking back I planned..." stays reflective)
    (
        Intent.REFLECT,
        0.9,
        "phrase:reflect",
        _phrase(
            r"\b("
            r"looking back"
            r"|in hindsight"
            r"|i realized"
            r"|i realised"
            r"|lesson(s)? learned"
            r"|i regret"
            r"|i'm proud of"
            r"|retrospect(ive)?"
            r"|what did i learn"
            r")\b"
        ),
    ),
    # ---- PLAN
    (
        Intent.PLAN,
        0.9,
        "phrase:plan",
        _phrase(
            r"\b("
            r"let's plan"
            r"|plan (my|the|a|out)"
            r"|prepare for"
            r"|prep(ping)? for"
            r"|roadmap"
            r"|timeline"
            r"|schedule (my|the|a)"
            r"|next steps?"
            r"|game plan"
            r")\b"
        ),
    ),
    (
        Intent.PLAN,
        0.7,
        "keyword:plan",
        _phrase(r"\b(plan|planning|strategy|strategize|strategise)\b"),
    ),
    # ---- LEARN  (what/how/why/explain questions)
    (
        Intent.LEARN,
        0.9,
        "phrase:learn",
        _phrase(
            r"\b("
            r"explain"
            r"|teach me"
            r"|help me understand"
            r"|what is"
            r"|what are"
            r"|how do(es)?"
            r"|how can i"
            r"|what does .+ mean"
            r"|why do(es)?"
            r"|tutorial"
            r")\b"
        ),
    ),
    # ---- TASK (imperative request for the twin to produce or do something)
    (
        Intent.TASK,
        0.9,
        "phrase:task",
        _phrase(
            r"^\s*("
            r"write( me)?"
            r"|draft"
            r"|generate"
            r"|create"
            r"|make"
            r"|build"
            r"|list"
            r"|summari(z|s)e"
            r"|translate"
            r"|rewrite"
            r"|edit"
            r"|fix"
            r"|debug"
            r"|refactor"
            r")\b"
        ),
    ),
    (
        Intent.TASK,
        0.7,
        "keyword:task",
        _phrase(r"\b(todo|to-do|checklist)\b"),
    ),
    # ---- THINK (the user is working something out, wants to be a thinking partner)
    (
        Intent.THINK,
        0.9,
        "phrase:think",
        _phrase(
            r"\b("
            r"i'?m thinking"
            r"|what do you think"
            r"|help me think"
            r"|wondering (if|whether|about)"
            r"|pondering"
            r"|on one hand"
            r"|trade-?offs?"
            r"|should i"
            r")\b"
        ),
    ),
    (
        Intent.THINK,
        0.7,
        "keyword:think",
        _phrase(r"\b(brainstorm|idea(s)?|consider(ing)?)\b"),
    ),
]


# Short conversational openers. If a message is short and matches these
# AND no stronger rule above fires, call it TALK with modest confidence.
_TALK_PHRASES: re.Pattern[str] = _phrase(
    r"^\s*("
    r"hi"
    r"|hello"
    r"|hey"
    r"|yo"
    r"|good (morning|afternoon|evening)"
    r"|how are you"
    r"|what'?s up"
    r"|thanks|thank you|ty"
    r"|lol|haha|lmao"
    r")\b"
)

# A conservative length ceiling for the TALK fallback. Short, casual
# messages that don't match any strong rule are usually conversational;
# long messages that match nothing are more likely something we don't
# yet have a rule for — those go to UNKNOWN so the audit layer can see
# the detector is unsure.
_TALK_MAX_WORDS = 8


class RuleBasedIntentDetector:
    """Deterministic, keyword/phrase-based intent detector.

    EXPLICITLY NOT a classifier. The rules in this file are a scaffold
    so the rest of the pipeline can be built against the
    `IntentDetector` protocol. A later swap to a model-backed detector
    is the point of the abstraction.
    """

    detector_name: ClassVar[str] = "rule-based-v1"

    def detect_sync(self, user_message: str) -> IntentResult:
        """Pure synchronous entry point for tests and in-process use.

        Separate from `detect` so unit tests do not need to run inside
        an asyncio event loop.
        """
        if not isinstance(user_message, str):
            # Defensive: never raise. A non-string input is a caller
            # bug, not a reason to break chat.
            return IntentResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                reason="error:non_string_input",
            )

        stripped = user_message.strip()
        if not stripped:
            return IntentResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                reason="fallback:empty_message",
            )

        for intent, confidence, reason, pattern in _RULES:
            if pattern.search(stripped):
                return IntentResult(
                    intent=intent,
                    confidence=confidence,
                    reason=reason,
                )

        if _TALK_PHRASES.search(stripped) and len(stripped.split()) <= _TALK_MAX_WORDS:
            return IntentResult(
                intent=Intent.TALK,
                confidence=0.7,
                reason="phrase:talk",
            )

        if len(stripped.split()) <= _TALK_MAX_WORDS:
            # Short message with no strong signal — default to TALK with
            # low confidence rather than UNKNOWN, since conversational
            # back-and-forth is the common case.
            return IntentResult(
                intent=Intent.TALK,
                confidence=0.4,
                reason="fallback:short_message",
            )

        return IntentResult(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            reason="fallback:no_rule_matched",
        )

    async def detect(self, user_message: str) -> IntentResult:
        # The rule-based detector is CPU-only and sync. The async
        # signature exists to satisfy the `IntentDetector` protocol so a
        # model-backed implementation can slot in later.
        return self.detect_sync(user_message)


# A singleton default — safe to share because the detector holds no
# mutable state.
DEFAULT_INTENT_DETECTOR: IntentDetector = RuleBasedIntentDetector()


async def detect_intent_safely(detector: IntentDetector, user_message: str) -> IntentResult:
    """Call `detector.detect`; absorb any exception.

    Mirrors the Sprint-3 `_retrieve_safely` pattern used by
    `ConversationService`. Keeps the chat path alive even if a future
    detector regression raises.
    """
    try:
        result = await detector.detect(user_message)
    except Exception as exc:  # pragma: no cover - defensive
        return IntentResult(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            reason=f"error:{type(exc).__name__}",
        )
    # Belt-and-braces: coerce an impl that returns something slightly
    # off-shape into a well-formed UNKNOWN rather than crashing the
    # service.
    if not isinstance(result, IntentResult):  # pragma: no cover
        return IntentResult(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            reason="error:bad_detector_result",
        )
    return result
