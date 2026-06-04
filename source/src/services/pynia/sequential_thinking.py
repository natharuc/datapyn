"""
Sequential thinking — visible planning steps for Pynia (all providers).

Copilot streams native reasoning; API providers emit step summaries via agent_progress.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from src.services.pynia.agent_progress import ProgressCallback, emit_progress
from src.services.pynia.agent_status import PHASE_PLANNING, format_tool_display

SEQUENTIAL_THINKING_PROMPT = r"""
## SEQUENTIAL THINKING (mandatory)
Before tools or a long answer, reason in **short visible steps** (like a senior engineer narrating):
1. **Understand** — what the user wants and which focused block matters.
2. **Plan** — 2–4 concrete actions (inspect only if missing context, then edit/run/query).
3. **Execute** — one tool round at a time; do not repeat reads.
4. **Verify** — what changed and what the user should see.

When the runtime exposes reasoning, write step titles as short lines (e.g. "Reviewed `block` structure", "Planned line edits for SUN/GECON signs").
Keep internal reasoning concise; final chat reply stays short and in the user's language.
"""


def round_step_title(round_idx: int, *, planning: bool = False) -> str:
    if planning or round_idx == 0:
        return "Planning next steps"
    if round_idx == 1:
        return "Applying changes"
    return "Refining result"


def summarize_planned_tools(
    prepared: List[Tuple[str, Dict[str, Any], str, bool]],
) -> str:
    lines: List[str] = []
    for name, args, _tc_id, should_execute in prepared:
        if not should_execute:
            continue
        title, detail = format_tool_display(name, args or {})
        line = f"• {title}"
        if detail:
            line += f" — {detail}"
        lines.append(line)
    return "\n".join(lines)


def emit_thinking_step(
    callback: Optional[ProgressCallback],
    *,
    title: str,
    body: str = "",
    step_id: str = "",
) -> None:
    """Push a visible thinking step to the chat UI (via reasoning payload)."""
    text = title.strip()
    if body.strip():
        text = f"{text}\n{body.strip()}"
    emit_progress(
        callback,
        phase_key=PHASE_PLANNING,
        step_id=step_id or "think",
        step_state="active",
        reasoning=text,
        thinking_step=True,
    )


def emit_planned_tools_thinking(
    callback: Optional[ProgressCallback],
    round_idx: int,
    prepared: List[Tuple[str, Dict[str, Any], str, bool]],
) -> None:
    title = round_step_title(round_idx)
    body = summarize_planned_tools(prepared)
    if not body:
        body = "• Respond in chat (no tools needed)"
    emit_thinking_step(
        callback,
        title=title,
        body=body,
        step_id=f"round-{round_idx}",
    )
