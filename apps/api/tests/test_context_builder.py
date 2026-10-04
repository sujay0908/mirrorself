"""ContextBuilder tests.

Pure, no DB, no LLM. Fixtures build minimal `Twin`, `TwinProfile`,
`Message`, and `RetrievedMemory` objects and feed them through the
builder.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.memory.context import ContextBudget, ContextBuilder
from app.memory.retrieval import RetrievedMemory

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def _twin(name: str = "Aurora", style: str = "warm", **basic) -> SimpleNamespace:
    profile = SimpleNamespace(
        communication_style_preset=style,
        communication_style_notes=None,
        basic_profile=basic,
    )
    return SimpleNamespace(
        display_name=name,
        profile=profile,
    )


def _retrieved(
    memory_id: str,
    *,
    content: str,
    mem_type: str = "FACT",
    similarity: float = 0.8,
    score: float = 1.5,
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


def _message(role: str, content: str, when: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        content=content,
        created_at=when or NOW,
    )


def test_builder_includes_profile_fields() -> None:
    twin = _twin(colour="green")
    ctx = ContextBuilder().build(twin, retrieved=[], recent_messages=[])
    sys = ctx.to_system_prompt()
    assert "Aurora" in sys
    assert "warm" in sys
    assert "colour='green'" in sys


def test_builder_includes_memory_content_without_leaking_ids() -> None:
    """Sprint 5: the rendered prompt carries memory content but no identifiers.

    Earlier sprints embedded `id=<short>` as a tag attribute. Sprint 5
    removes that attribute (see `app/conversation/prompt.py`) because
    the LLM has no legitimate use for an internal id; keeping it would
    risk the model echoing it back to the user. The server-side
    `provenance_map` on `TwinContext` still records the short→full
    mapping for the debug/trace layer.
    """
    full_id = "00000000-0000-0000-0000-00000000abcd"
    r = _retrieved(full_id, content="I live in Bengaluru.")
    ctx = ContextBuilder().build(_twin(), retrieved=[r], recent_messages=[])
    sys = ctx.to_system_prompt()
    assert "<confirmed_memory type=FACT>" in sys
    assert "I live in Bengaluru." in sys
    # Neither the full UUID nor its first segment appears in the prompt.
    assert full_id not in sys
    assert "00000000" not in sys
    # The provenance map is still populated for the trace layer.
    assert ctx.provenance_map == {"00000000": full_id}


def test_provenance_map_links_short_to_full() -> None:
    full_id = "11111111-1111-1111-1111-111111111111"
    r = _retrieved(full_id, content="x")
    ctx = ContextBuilder().build(_twin(), retrieved=[r], recent_messages=[])
    assert ctx.provenance_map == {"11111111": full_id}


def test_builder_bounded_memory_count() -> None:
    many = [
        _retrieved(f"00000000-0000-0000-0000-00000000000{i:x}", content=f"m{i}") for i in range(16)
    ]
    budget = ContextBudget(max_memories=3)
    ctx = ContextBuilder(budget).build(_twin(), retrieved=many, recent_messages=[])
    assert len(ctx.memories) == 3


def test_builder_bounded_history_turns() -> None:
    turns = [_message("user" if i % 2 == 0 else "twin", f"t{i}") for i in range(20)]
    budget = ContextBudget(max_history_turns=4)
    ctx = ContextBuilder(budget).build(_twin(), retrieved=[], recent_messages=turns)
    assert len(ctx.recent_turns) == 4
    # Chronological order preserved (last 4 of the 20 turns, oldest first).
    assert [t.content for t in ctx.recent_turns] == ["t16", "t17", "t18", "t19"]


def test_builder_filters_out_system_history() -> None:
    turns = [
        _message("system", "ignored"),
        _message("user", "hi"),
        _message("twin", "hello"),
    ]
    ctx = ContextBuilder().build(_twin(), retrieved=[], recent_messages=turns)
    assert [t.role for t in ctx.recent_turns] == ["user", "twin"]


def test_builder_truncates_long_content() -> None:
    long_content = "x" * 10_000
    r = _retrieved("00000000-0000-0000-0000-000000000001", content=long_content)
    budget = ContextBudget(max_memory_content_chars=100)
    ctx = ContextBuilder(budget).build(_twin(), retrieved=[r], recent_messages=[])
    assert len(ctx.memories[0].content) <= 101  # 100 chars + ellipsis


def test_builder_output_is_deterministic() -> None:
    twin = _twin(colour="green", role="founder")
    r = _retrieved("00000000-0000-0000-0000-000000000001", content="fact")
    turns = [_message("user", "a"), _message("twin", "b")]
    b = ContextBuilder()
    a1 = b.build(twin, retrieved=[r], recent_messages=turns).to_system_prompt()
    a2 = b.build(twin, retrieved=[r], recent_messages=turns).to_system_prompt()
    assert a1 == a2


def test_builder_never_mutates_profile() -> None:
    twin = _twin(colour="green")
    before = (
        twin.profile.communication_style_preset,
        twin.profile.communication_style_notes,
        dict(twin.profile.basic_profile),
    )
    r = _retrieved("00000000-0000-0000-0000-000000000001", content="x")
    ContextBuilder().build(twin, retrieved=[r], recent_messages=[])
    after = (
        twin.profile.communication_style_preset,
        twin.profile.communication_style_notes,
        dict(twin.profile.basic_profile),
    )
    assert before == after


def test_builder_handles_zero_memories() -> None:
    ctx = ContextBuilder().build(_twin(), retrieved=[], recent_messages=[])
    sys = ctx.to_system_prompt()
    # No memory section when there is nothing to show.
    assert "<confirmed_memory" not in sys
