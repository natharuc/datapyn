"""Guards for Pynia agent tool loops — prevent stalls and duplicate work."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from src.services.pynia.subagents.classifier import (
    READ_ONLY_TOOLS,
    SUBAGENT_TOOL,
    is_mutating_tool,
    is_read_only_tool,
    is_subagent_tool,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_MUTATING_PER_ROUND = 2
MAX_READ_ONLY_PER_ROUND = 5
MAX_SUBAGENTS_PER_ROUND = 3

MAX_TOOL_RESULT_CHARS = 6_000
DUPLICATE_RESULT_MSG = (
    "DUPLICATE (skipped): identical tool call already ran this turn. "
    "Use the previous tool result in context. Do not repeat this call."
)
TOO_MANY_TOOLS_MSG = (
    "SKIPPED: too many {kind} tools in one step (max {max}). "
    "Use datapyn_subagent for parallel explore, or fewer calls per step."
)

# Re-export for agent loops
__all__ = [
    "READ_ONLY_TOOLS",
    "MAX_TOOL_ROUNDS",
    "MAX_MUTATING_PER_ROUND",
    "MAX_READ_ONLY_PER_ROUND",
    "MAX_SUBAGENTS_PER_ROUND",
    "prepare_tool_calls",
    "skipped_tool_message",
    "tool_call_key",
    "truncate_tool_result",
    "format_registry_result",
    "was_duplicate_skip",
]


def tool_call_key(name: str, args: Dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args or {}, sort_keys=True, default=str)}"


def prepare_tool_calls(
    parsed_calls: List[Tuple[str, Dict[str, Any], str]],
    *,
    seen_keys: set[str],
    max_mutating: int = MAX_MUTATING_PER_ROUND,
    max_read_only: int = MAX_READ_ONLY_PER_ROUND,
    max_subagents: int = MAX_SUBAGENTS_PER_ROUND,
) -> List[Tuple[str, Dict[str, Any], str, bool]]:
    """
    Normalize a round of tool calls.

    Returns list of (name, args, tool_call_id, should_execute).
    When should_execute is False, the caller must still emit a tool result.
    """
    prepared: List[Tuple[str, Dict[str, Any], str, bool]] = []
    mutating_this_round = 0
    read_only_this_round = 0
    subagents_this_round = 0

    for name, args, tc_id in parsed_calls:
        key = tool_call_key(name, args or {})
        if key in seen_keys:
            prepared.append((name, args, tc_id, False))
            continue

        if is_subagent_tool(name):
            if subagents_this_round >= max_subagents:
                prepared.append((name, args, tc_id, False))
                continue
            subagents_this_round += 1
        elif is_mutating_tool(name):
            if mutating_this_round >= max_mutating:
                prepared.append((name, args, tc_id, False))
                continue
            mutating_this_round += 1
        elif is_read_only_tool(name):
            if read_only_this_round >= max_read_only:
                prepared.append((name, args, tc_id, False))
                continue
            read_only_this_round += 1
        else:
            if mutating_this_round >= max_mutating:
                prepared.append((name, args, tc_id, False))
                continue
            mutating_this_round += 1

        seen_keys.add(key)
        prepared.append((name, args, tc_id, True))

    return prepared


def was_duplicate_skip(name: str, args: Dict[str, Any], seen_keys: set[str]) -> bool:
    """True when this call was skipped because an identical call already ran."""
    return tool_call_key(name, args or {}) in seen_keys


def skipped_tool_message(name: str, args: Dict[str, Any], seen_keys: set[str]) -> str:
    key = tool_call_key(name, args or {})
    if key in seen_keys:
        return DUPLICATE_RESULT_MSG
    if is_subagent_tool(name):
        kind = "subagent"
        max_n = MAX_SUBAGENTS_PER_ROUND
    elif is_read_only_tool(name):
        kind = "read-only"
        max_n = MAX_READ_ONLY_PER_ROUND
    else:
        kind = "mutating"
        max_n = MAX_MUTATING_PER_ROUND
    return TOO_MANY_TOOLS_MSG.format(kind=kind, max=max_n)


def truncate_tool_result(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    if not text or len(text) <= max_chars:
        return text or ""
    tail = (
        f"\n\n[Truncated to {max_chars} chars for speed. "
        "Use datapyn_inspect with detail=structure or around= for large blocks.]"
    )
    return text[: max_chars - len(tail)] + tail


def format_registry_result(result: Dict[str, Any]) -> str:
    if "error" in result:
        return f"Error: {result['error']}"
    parts = []
    for item in result.get("content", []):
        parts.append(item.get("text", str(item)))
    return truncate_tool_result("\n".join(parts))
