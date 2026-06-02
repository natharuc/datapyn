"""Guards for Pynia agent tool loops — prevent stalls and duplicate work."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
MAX_TOOLS_PER_ROUND = 3
MAX_TOOL_RESULT_CHARS = 6_000
DUPLICATE_RESULT_MSG = (
    "DUPLICATE (skipped): identical tool call already ran this turn. "
    "Use the previous tool result in context. Do not repeat this call."
)
TOO_MANY_TOOLS_MSG = (
    "SKIPPED: too many parallel tools in one step (max {max}). "
    "Call fewer tools per step — observe once, then edit or answer."
)


def tool_call_key(name: str, args: Dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args or {}, sort_keys=True, default=str)}"


def prepare_tool_calls(
    parsed_calls: List[Tuple[str, Dict[str, Any], str]],
    *,
    seen_keys: set[str],
    max_per_round: int = MAX_TOOLS_PER_ROUND,
) -> List[Tuple[str, Dict[str, Any], str, bool]]:
    """
    Normalize a round of tool calls.

    Returns list of (name, args, tool_call_id, should_execute).
    When should_execute is False, the caller must still emit a tool result with DUPLICATE_RESULT_MSG.
    """
    prepared: List[Tuple[str, Dict[str, Any], str, bool]] = []
    executed_this_round = 0

    for name, args, tc_id in parsed_calls:
        key = tool_call_key(name, args or {})
        if key in seen_keys:
            prepared.append((name, args, tc_id, False))
            continue
        if executed_this_round >= max_per_round:
            prepared.append((name, args, tc_id, False))
            continue
        seen_keys.add(key)
        executed_this_round += 1
        prepared.append((name, args, tc_id, True))

    return prepared


def skipped_tool_message(name: str, args: Dict[str, Any], seen_keys: set[str]) -> str:
    key = tool_call_key(name, args or {})
    if key in seen_keys:
        return DUPLICATE_RESULT_MSG
    return TOO_MANY_TOOLS_MSG.format(max=MAX_TOOLS_PER_ROUND)


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
