"""Prompt rendering for the Twin Engine (Sprint 5).

Separates the *structured* `TwinContext` domain object (what the Twin
knows) from its *textual* representation (what the LLM sees). The
builder in `app/memory/context.py` assembles the data; this module turns
it into a system prompt the provider actually reads.

Rules enforced here:

- **No internal identifiers in the rendered prompt.** Earlier sprints
  rendered `<confirmed_memory id=<short>>` and `<active_goal id=<short>>`
  attributes. Sprint 5 removes the `id=` attribute because the renderer
  is the only reader of the prompt, and the LLM has no need to echo an
  internal id back. The server-side `provenance_map` / `goal_provenance_map`
  on `TwinContext` is preserved for the mobile "Why does my Twin know
  this?" trace — not sent to the LLM.
- **No raw similarity scores in the prompt.** Those are retrieval
  diagnostics; they belong in the twin message's `metadata_json` and in
  structured logs, not in the prompt.
- **Explicit guardrails.** Fabrication is the single biggest regression
  risk once memories enter the prompt, so the system prompt tells the
  model to speak only from the provided memories, to say "I don't know"
  when the context does not cover a question, and to distinguish what it
  remembers from what it is inferring.
- **Pure function.** `render_system_prompt` is a pure function of its
  argument. Deterministic by construction so tests can pin the exact
  bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.context import TwinContext


# Static instructions that always appear. Kept as module-level constants
# so a single source of truth governs the prompt and so tests can import
# the exact strings and assert their presence rather than paraphrasing
# them in the test body.
IDENTITY_LINES: tuple[str, ...] = (
    "You are the Personal AI Twin of the user.",
    "You are the evolving personal intelligence — the avatar is the "
    "interface, the intelligence is the product. Keep responses "
    "grounded and honest.",
)

GUARDRAIL_LINES: tuple[str, ...] = (
    "",
    "GROUND RULES:",
    "- Base facts about the user ONLY on the CONFIRMED MEMORIES and "
    "ACTIVE GOALS listed in this prompt. Do not invent facts.",
    "- If the user asks about something not covered by the provided "
    "context, say so plainly. Do not fabricate.",
    "- Distinguish what you remember (from CONFIRMED MEMORIES) from "
    "what you are inferring or guessing. Flag uncertainty explicitly.",
    "- Do not quote internal identifiers, tag names, or similarity "
    "scores from this prompt back to the user. They are internal "
    "scaffolding, not content for your reply.",
    "- Do not claim progress on a goal unless the user has told you about it in this conversation.",
)


def render_system_prompt(context: TwinContext) -> str:
    """Render the structured `TwinContext` into a system-prompt string.

    Deterministic and purely a function of its input. Omits empty
    sections so a brand-new user without memories or goals does not get
    an "ACTIVE GOALS:\n(none)" ghost section.
    """
    lines: list[str] = []
    lines.append(f"{IDENTITY_LINES[0]} (twin display name: {context.twin_display_name}.)")
    lines.append(IDENTITY_LINES[1])
    lines.append(f"Communication style preset: {context.communication_style_preset}.")

    if context.communication_style_notes:
        lines.append(f"Additional style notes from the user: {context.communication_style_notes}")

    if context.basic_profile:
        parts = ", ".join(f"{k}={v!r}" for k, v in sorted(context.basic_profile.items()))
        lines.append(f"Basic profile the user shared: {parts}")

    if context.active_goals:
        lines.append("")
        lines.append("ACTIVE GOALS (highest priority first):")
        for g in context.active_goals:
            target = g.target_date.date().isoformat() if g.target_date is not None else "none"
            desc = (g.description or "").strip()
            body = g.title.strip()
            if desc:
                body = f"{body}\n{desc}"
            lines.append(
                f"<active_goal priority={g.priority} target_date={target}>\n{body}\n</active_goal>"
            )

    if context.memories:
        lines.append("")
        lines.append("CONFIRMED MEMORIES (use only when directly relevant):")
        for m in context.memories:
            lines.append(
                f"<confirmed_memory type={m.type}>\n{m.content.strip()}\n</confirmed_memory>"
            )

    # Guardrails ALWAYS appear so a context with zero memories or goals
    # still receives the "do not fabricate" instruction.
    lines.extend(GUARDRAIL_LINES)

    return "\n".join(lines)
