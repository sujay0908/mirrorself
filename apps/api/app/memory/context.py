"""TwinContext + context builder.

The context builder is a token-budget-aware pure function (no I/O) that
turns:

- the Twin's stable profile
- the (ranked) retrieved memories
- the recent conversation history
- the Twin's active goals (Sprint 4, DF7+DF8)

into a `TwinContext` object which the pipeline turns into the LLM message
sequence. It is unit-testable without ever calling an LLM.

Design rules enforced here:

- `TwinProfile` is READ-ONLY in this module. There is no code path that
  writes to the profile — reinforced by test
  `test_context_builder_never_mutates_profile`.
- Memory content inside the prompt is wrapped in `<confirmed_memory>` tags
  with a short attribution header `id=<short>` so the model (and audit
  logs) can tell what came from memory and what was conversational.
- Active goals are a SEPARATE channel. They are passed in pre-ordered (by
  priority then recency) and rendered under their own `<active_goal>` tags
  so the model never confuses an aspirational commitment with a filed fact.
  Only `active` goals ever reach the prompt (DF7).
- Hard bounds: at most ``max_memories`` memory items, ``max_active_goals``
  goals, ``max_history_turns`` conversation turns.
- Deterministic ordering: memories by descending retrieval score, with
  memory_id as a stable tiebreaker (already done by the ranker); goals
  as provided (service layer orders them); conversation turns in
  chronological order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from app.memory.retrieval import RetrievedMemory

if TYPE_CHECKING:
    from app.conversation.models import Message
    from app.goal.models import Goal
    from app.twin.models import Twin


# Short-ID helper: don't leak full UUIDs into the LLM prompt.
def _short_id(uuid_str: str) -> str:
    return uuid_str.split("-")[0]


@dataclass(slots=True)
class ContextMemoryEntry:
    short_id: str
    memory_id: str
    type: str
    content: str
    score: float
    similarity: float


@dataclass(slots=True)
class ContextGoalEntry:
    short_id: str
    goal_id: str
    title: str
    description: str | None
    priority: int
    target_date: datetime | None


@dataclass(slots=True)
class ContextTurn:
    role: str  # "user" | "twin"
    content: str


@dataclass(slots=True)
class TwinContext:
    twin_display_name: str
    communication_style_preset: str
    communication_style_notes: str | None
    basic_profile: dict[str, object]
    memories: list[ContextMemoryEntry] = field(default_factory=list)
    active_goals: list[ContextGoalEntry] = field(default_factory=list)
    recent_turns: list[ContextTurn] = field(default_factory=list)
    # provenance_map: short_id → full memory_id. Not sent to the LLM.
    # Used by the trace/debug layer to answer "why does my Twin know this?"
    provenance_map: dict[str, str] = field(default_factory=dict)
    # goal_provenance_map: short_id → full goal_id. Not sent to the LLM.
    goal_provenance_map: dict[str, str] = field(default_factory=dict)

    def to_system_prompt(self) -> str:
        """Render the context as a system prompt string.

        Sprint 5 moved the actual rendering into
        `app.conversation.prompt.render_system_prompt` so the structured
        context object stays separate from the string it eventually
        becomes. This method is kept as a thin adapter so the pipeline,
        tests, and any other callers that already invoke it do not need
        to change. The renderer is deterministic and pure; see the
        module docstring on `app.conversation.prompt` for the rules it
        enforces (no internal ids, no similarity scores, explicit
        anti-fabrication guardrails).
        """
        # Local import keeps the import graph acyclic: `prompt.py` only
        # type-imports `TwinContext`.
        from app.conversation.prompt import render_system_prompt

        return render_system_prompt(self)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_memories: int = 8
    max_history_turns: int = 6
    max_memory_content_chars: int = 500
    max_turn_content_chars: int = 1500
    # DF8: at most 3 active goals carried into the prompt. Service layer
    # orders them so this is a straight slice.
    max_active_goals: int = 3
    max_goal_title_chars: int = 200
    max_goal_description_chars: int = 500


_DEFAULT_BUDGET = ContextBudget()


class ContextBuilder:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self._budget = budget or _DEFAULT_BUDGET

    def build(
        self,
        twin: Twin,
        retrieved: list[RetrievedMemory],
        recent_messages: list[Message],
        active_goals: list[Goal] | None = None,
    ) -> TwinContext:
        memories: list[ContextMemoryEntry] = []
        provenance: dict[str, str] = {}
        for retrieved_memory in retrieved[: self._budget.max_memories]:
            full_id = str(retrieved_memory.memory.id)
            short = _short_id(full_id)
            content = retrieved_memory.memory.content
            if len(content) > self._budget.max_memory_content_chars:
                content = content[: self._budget.max_memory_content_chars] + "…"
            memories.append(
                ContextMemoryEntry(
                    short_id=short,
                    memory_id=full_id,
                    type=retrieved_memory.memory.type,
                    content=content,
                    score=retrieved_memory.score,
                    similarity=retrieved_memory.similarity,
                )
            )
            provenance[short] = full_id

        # Active goals (DF7+DF8). The caller is responsible for the order and
        # the status filter; the builder enforces the hard cap and the per-
        # field truncation. An empty list is the common path — no retrieval
        # ever gates chat on goals.
        goal_entries: list[ContextGoalEntry] = []
        goal_provenance: dict[str, str] = {}
        for goal in (active_goals or [])[: self._budget.max_active_goals]:
            full_id = str(goal.id)
            short = _short_id(full_id)
            title = goal.title
            if len(title) > self._budget.max_goal_title_chars:
                title = title[: self._budget.max_goal_title_chars] + "…"
            description = goal.description
            if (
                description is not None
                and len(description) > self._budget.max_goal_description_chars
            ):
                description = (
                    description[: self._budget.max_goal_description_chars] + "…"
                )
            goal_entries.append(
                ContextGoalEntry(
                    short_id=short,
                    goal_id=full_id,
                    title=title,
                    description=description,
                    priority=goal.priority,
                    target_date=goal.target_date,
                )
            )
            goal_provenance[short] = full_id

        # Recent turns in chronological order, bounded, excluding system
        # messages which are already synthesised by the system prompt.
        bounded_messages = [
            m for m in recent_messages if m.role in ("user", "twin")
        ][-self._budget.max_history_turns :]
        turns: list[ContextTurn] = []
        for m in bounded_messages:
            content = m.content
            if len(content) > self._budget.max_turn_content_chars:
                content = content[: self._budget.max_turn_content_chars] + "…"
            turns.append(ContextTurn(role=m.role, content=content))

        profile = twin.profile
        return TwinContext(
            twin_display_name=twin.display_name,
            communication_style_preset=profile.communication_style_preset,
            communication_style_notes=profile.communication_style_notes,
            basic_profile=dict(profile.basic_profile or {}),
            memories=memories,
            active_goals=goal_entries,
            recent_turns=turns,
            provenance_map=provenance,
            goal_provenance_map=goal_provenance,
        )
