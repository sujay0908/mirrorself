"""Prompt renderer tests (Sprint 5).

The renderer is a pure function of a `TwinContext`. These tests pin the
specific guarantees Sprint 5 adds on top of the Sprint 3+4 context
builder: no internal identifiers in the prompt, no raw similarity
scores in the prompt, and the explicit anti-fabrication guardrail
block.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.conversation.prompt import (
    GUARDRAIL_LINES,
    IDENTITY_LINES,
    render_system_prompt,
)
from app.memory.context import ContextBuilder
from app.memory.retrieval import RetrievedMemory

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _twin(name: str = "Aurora", style: str = "warm", **basic) -> SimpleNamespace:
    profile = SimpleNamespace(
        communication_style_preset=style,
        communication_style_notes=None,
        basic_profile=basic,
    )
    return SimpleNamespace(display_name=name, profile=profile)


def _retrieved(
    memory_id: str,
    *,
    content: str,
    mem_type: str = "FACT",
    similarity: float = 0.823456,
    score: float = 1.47,
) -> RetrievedMemory:
    memory = SimpleNamespace(
        id=uuid.UUID(memory_id),
        type=mem_type,
        content=content,
    )
    return RetrievedMemory(
        memory=memory,
        sources=[],
        similarity=similarity,
        score=score,
        ranking_components={},
    )


def _goal(
    short_hex: str,
    *,
    title: str,
    description: str | None = None,
    priority: int = 3,
    target_date: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(f"{short_hex}-0000-0000-0000-000000000000"),
        title=title,
        description=description,
        priority=priority,
        target_date=target_date,
    )


# ----------------------------------------------------------------------
# Shape and determinism
# ----------------------------------------------------------------------


def test_renderer_output_is_deterministic() -> None:
    twin = _twin(colour="green")
    r = _retrieved("00000000-0000-0000-0000-00000000abcd", content="x")
    g = _goal("cccccccc", title="Goal c", priority=2)
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[], active_goals=[g])
    assert render_system_prompt(ctx) == render_system_prompt(ctx)


def test_renderer_always_emits_identity_and_guardrails() -> None:
    twin = _twin()
    ctx = ContextBuilder().build(twin, retrieved=[], recent_messages=[])
    out = render_system_prompt(ctx)
    for line in IDENTITY_LINES:
        assert line.split(" (twin")[0] in out  # identity line start
    for guardrail in GUARDRAIL_LINES:
        if guardrail:  # skip the blank separator line
            assert guardrail in out


def test_renderer_omits_section_headers_when_empty() -> None:
    """No memories + no goals → the ACTIVE GOALS and CONFIRMED MEMORIES
    section HEADERS are absent. The guardrail block, which does name
    those sections, still appears.
    """
    twin = _twin()
    ctx = ContextBuilder().build(twin, retrieved=[], recent_messages=[])
    out = render_system_prompt(ctx)
    assert "ACTIVE GOALS (highest priority first):" not in out
    assert "CONFIRMED MEMORIES (use only when directly relevant):" not in out
    assert "<active_goal" not in out
    assert "<confirmed_memory" not in out
    assert "GROUND RULES:" in out


# ----------------------------------------------------------------------
# Guarantee: no internal identifiers in the rendered prompt
# ----------------------------------------------------------------------


def test_renderer_never_leaks_full_uuid() -> None:
    twin = _twin()
    r = _retrieved("deadbeef-dead-beef-dead-beefdeadbeef", content="I love filter coffee.")
    g = _goal(
        "feedfeed",
        title="Finish the memoir",
        priority=1,
        target_date=datetime(2026, 12, 31, tzinfo=UTC),
    )
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[], active_goals=[g])
    out = render_system_prompt(ctx)
    # No full UUID.
    assert UUID_RE.search(out) is None
    # No `id=` attribute at all on either tag.
    assert "id=" not in out
    # Content is still present.
    assert "I love filter coffee." in out
    assert "Finish the memoir" in out


def test_renderer_does_not_leak_short_id_segments() -> None:
    twin = _twin()
    r = _retrieved("abcdef01-0000-0000-0000-000000000000", content="A fact.")
    g = _goal("fedcba98", title="A goal", priority=4)
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[], active_goals=[g])
    out = render_system_prompt(ctx)
    assert "abcdef01" not in out
    assert "fedcba98" not in out


# ----------------------------------------------------------------------
# Guarantee: no raw similarity scores in the rendered prompt
# ----------------------------------------------------------------------


def test_renderer_never_leaks_similarity_or_score() -> None:
    """No retrieval diagnostics (numeric similarity, numeric score,
    "similarity:" or "score:" KV pairs) surface in the prompt. The
    guardrail block does mention the word "similarity" by name as part
    of a don't-echo instruction, so this test checks for the leakage
    shape, not for the word in isolation.
    """
    twin = _twin()
    r = _retrieved(
        "00000000-0000-0000-0000-000000000001",
        content="A thing",
        similarity=0.823456,
        score=1.4712345,
    )
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[])
    out = render_system_prompt(ctx)
    assert "0.823456" not in out
    assert "0.823" not in out
    assert "1.4712345" not in out
    assert "1.47" not in out
    assert "similarity=" not in out
    assert "score=" not in out
    assert "similarity:" not in out.lower()
    assert "score:" not in out.lower()


# ----------------------------------------------------------------------
# Guarantee: anti-fabrication guardrail wording is present verbatim
# ----------------------------------------------------------------------


def test_renderer_contains_anti_fabrication_wording() -> None:
    twin = _twin()
    ctx = ContextBuilder().build(twin, retrieved=[], recent_messages=[])
    out = render_system_prompt(ctx)
    assert "Do not invent facts." in out
    assert "Do not fabricate." in out
    # The uncertainty rule.
    assert "inferring or guessing" in out
    # The "don't echo tags/ids" rule the LLM instruction depends on.
    assert "internal identifiers" in out


# ----------------------------------------------------------------------
# Section layout — goals before memories, each with its header
# ----------------------------------------------------------------------


def test_renderer_section_order_is_goals_then_memories() -> None:
    twin = _twin()
    r = _retrieved("00000000-0000-0000-0000-000000000002", content="A memory")
    g = _goal("00000001", title="A goal", priority=1)
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[], active_goals=[g])
    out = render_system_prompt(ctx)
    goals_pos = out.index("ACTIVE GOALS")
    memories_pos = out.index("CONFIRMED MEMORIES")
    guardrails_pos = out.index("GROUND RULES:")
    assert goals_pos < memories_pos < guardrails_pos


def test_renderer_renders_target_date_or_none() -> None:
    twin = _twin()
    g_dated = _goal(
        "00000001",
        title="Dated",
        priority=1,
        target_date=datetime(2027, 1, 15, tzinfo=UTC),
    )
    g_undated = _goal("00000002", title="Undated", priority=1)
    ctx = ContextBuilder().build(
        twin,
        retrieved=[],
        recent_messages=[],
        active_goals=[g_dated, g_undated],
    )
    out = render_system_prompt(ctx)
    assert "target_date=2027-01-15" in out
    assert "target_date=none" in out


# ----------------------------------------------------------------------
# TwinContext.to_system_prompt still delegates to the renderer
# ----------------------------------------------------------------------


def test_context_to_system_prompt_matches_renderer() -> None:
    twin = _twin(colour="indigo")
    r = _retrieved("00000000-0000-0000-0000-000000000003", content="hello")
    g = _goal("00000003", title="A goal")
    ctx = ContextBuilder().build(twin, retrieved=[r], recent_messages=[], active_goals=[g])
    assert ctx.to_system_prompt() == render_system_prompt(ctx)
