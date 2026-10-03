"""TwinContext + context builder.

The context builder is a token-budget-aware pure function (no I/O) that
turns:

- the Twin's stable profile
- the (ranked) retrieved memories
- the recent conversation history

into a `TwinContext` object which the pipeline turns into the LLM message
sequence. It is unit-testable without ever calling an LLM.

Design rules enforced here:

- `TwinProfile` is READ-ONLY in this module. There is no code path that
  writes to the profile — reinforced by test
  `test_context_builder_never_mutates_profile`.
- Memory content inside the prompt is wrapped in `<confirmed_memory>` tags
  with a short attribution header `id=<short>` so the model (and audit
  logs) can tell what came from memory and what was conversational.
- Hard bounds: at most ``max_memories`` memory items, at most
  ``max_history_turns`` conversation turns. Both default to small numbers.
- Deterministic ordering: memories by descending retrieval score, with
  memory_id as a stable tiebreaker (already done by the ranker);
  conversation turns in chronological order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.memory.retrieval import RetrievedMemory

if TYPE_CHECKING:
    from app.conversation.models import Message
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
    recent_turns: list[ContextTurn] = field(default_factory=list)
    # provenance_map: short_id → full memory_id. Not sent to the LLM.
    # Used by the trace/debug layer to answer "why does my Twin know this?"
    provenance_map: dict[str, str] = field(default_factory=dict)

    def to_system_prompt(self) -> str:
        """Deterministic, structured system prompt for the LLM."""
        lines: list[str] = [
            f"You are the Personal AI Twin of the user "
            f"(twin display name: {self.twin_display_name}).",
            "You are the evolving personal intelligence — the avatar is the "
            "interface, the intelligence is the product. Keep responses "
            "grounded and honest.",
            f"Communication style preset: {self.communication_style_preset}.",
        ]
        if self.communication_style_notes:
            lines.append(
                f"Additional style notes from the user: "
                f"{self.communication_style_notes}"
            )
        if self.basic_profile:
            parts = ", ".join(
                f"{k}={v!r}" for k, v in sorted(self.basic_profile.items())
            )
            lines.append(f"Basic profile the user shared: {parts}")

        if self.memories:
            lines.append("")
            lines.append(
                "Use the following CONFIRMED MEMORIES about the user only "
                "when they are directly relevant to the message. Do not "
                "assume a memory is relevant just because it was retrieved. "
                "If a memory is used, you may say what you remember, but do "
                "not quote internal identifiers."
            )
            for m in self.memories:
                lines.append(
                    f"<confirmed_memory id={m.short_id} type={m.type}>"
                    f"\n{m.content.strip()}\n"
                    f"</confirmed_memory>"
                )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_memories: int = 8
    max_history_turns: int = 6
    max_memory_content_chars: int = 500
    max_turn_content_chars: int = 1500


_DEFAULT_BUDGET = ContextBudget()


class ContextBuilder:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self._budget = budget or _DEFAULT_BUDGET

    def build(
        self,
        twin: Twin,
        retrieved: list[RetrievedMemory],
        recent_messages: list[Message],
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
            recent_turns=turns,
            provenance_map=provenance,
        )
