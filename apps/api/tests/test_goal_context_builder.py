"""Goal integration in the ContextBuilder (Sprint 4).

Pure tests — no DB, no HTTP. These assert the invariants from DF7 + DF8:

- Active goals appear under a SEPARATE `<active_goal>` tag (never
  confused with `<confirmed_memory>`).
- The builder caps `active_goals` to `ContextBudget.max_active_goals` (3
  by default). It does NOT re-order; the service is responsible for
  passing them in the (priority, recency) order it decided on.
- Long titles and descriptions are truncated to the budget's limits.
- The builder never mutates the goals it receives.
- The `goal_provenance_map` records short-id → full-id for debugging.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.memory.context import ContextBudget, ContextBuilder

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def _twin(name: str = "Aurora") -> SimpleNamespace:
    profile = SimpleNamespace(
        communication_style_preset="neutral",
        communication_style_notes=None,
        basic_profile={},
    )
    return SimpleNamespace(display_name=name, profile=profile)


def _goal(
    short: str,
    *,
    title: str = "Ship Sprint 4",
    description: str | None = None,
    priority: int = 3,
    target_date: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(f"{short}-0000-0000-0000-000000000000"),
        title=title,
        description=description,
        priority=priority,
        target_date=target_date,
    )


def test_active_goals_render_in_separate_tag() -> None:
    g = _goal("aaaaaaaa", title="Ship Sprint 4", priority=1)
    ctx = ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    prompt = ctx.to_system_prompt()
    assert "<active_goal id=aaaaaaaa priority=1" in prompt
    assert "Ship Sprint 4" in prompt
    # Memory tag must NOT be used for goals.
    assert "<confirmed_memory" not in prompt


def test_builder_caps_active_goals_at_budget() -> None:
    goals = [_goal(f"{i:08x}", title=f"Goal {i}") for i in range(10)]
    budget = ContextBudget(max_active_goals=3)
    ctx = ContextBuilder(budget).build(
        _twin(), retrieved=[], recent_messages=[], active_goals=goals
    )
    assert len(ctx.active_goals) == 3
    # The slice preserves input order (service orders by priority then
    # recency; the builder does not re-sort).
    assert [g.title for g in ctx.active_goals] == ["Goal 0", "Goal 1", "Goal 2"]


def test_builder_omits_active_goals_section_when_empty() -> None:
    ctx = ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[]
    )
    prompt = ctx.to_system_prompt()
    assert "<active_goal" not in prompt
    assert "CURRENTLY ACTIVE GOALS" not in prompt


def test_builder_renders_target_date_when_present() -> None:
    due = datetime(2026, 12, 31, tzinfo=UTC)
    g = _goal("bbbbbbbb", title="Taxes", target_date=due)
    ctx = ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    assert "target_date=2026-12-31" in ctx.to_system_prompt()


def test_builder_renders_target_date_none_when_missing() -> None:
    g = _goal("cccccccc", title="Open-ended")
    ctx = ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    assert "target_date=none" in ctx.to_system_prompt()


def test_builder_truncates_long_goal_title() -> None:
    g = _goal("dddddddd", title="x" * 10_000)
    budget = ContextBudget(max_goal_title_chars=50)
    ctx = ContextBuilder(budget).build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    assert len(ctx.active_goals[0].title) <= 51  # 50 chars + ellipsis


def test_builder_truncates_long_goal_description() -> None:
    g = _goal("eeeeeeee", title="t", description="y" * 10_000)
    budget = ContextBudget(max_goal_description_chars=80)
    ctx = ContextBuilder(budget).build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    desc = ctx.active_goals[0].description
    assert desc is not None
    assert len(desc) <= 81


def test_goal_provenance_map_links_short_to_full() -> None:
    g = _goal("ffffffff", title="Goal")
    ctx = ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    assert ctx.goal_provenance_map == {
        "ffffffff": "ffffffff-0000-0000-0000-000000000000"
    }


def test_builder_never_mutates_goal() -> None:
    g = _goal("12345678", title="original", description="original desc", priority=2)
    before = (g.title, g.description, g.priority, g.target_date)
    ContextBuilder().build(
        _twin(), retrieved=[], recent_messages=[], active_goals=[g]
    )
    after = (g.title, g.description, g.priority, g.target_date)
    assert before == after


def test_builder_output_is_deterministic_with_goals() -> None:
    goals = [_goal(f"{i:08x}", title=f"G{i}") for i in range(2)]
    b = ContextBuilder()
    a1 = b.build(
        _twin(), retrieved=[], recent_messages=[], active_goals=goals
    ).to_system_prompt()
    a2 = b.build(
        _twin(), retrieved=[], recent_messages=[], active_goals=goals
    ).to_system_prompt()
    assert a1 == a2
