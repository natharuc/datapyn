"""Guards for Pynia agent tool loops — prevent stalls and duplicate work."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.services.pynia.subagents.classifier import (
    READ_ONLY_TOOLS,
    SUBAGENT_TOOL,
    is_mutating_tool,
    is_read_only_tool,
    is_subagent_tool,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4
# Rounds 0-2 offer tools; the last round forces a chat answer. Three rounds
# give the model read → act → verify/recover (2 was too tight to fix a failed
# run or retry a safety-refused edit).
FORCE_ANSWER_AFTER_ROUND = 3
MAX_MUTATING_PER_ROUND = 2
MAX_READ_ONLY_PER_ROUND = 4
MAX_SUBAGENTS_PER_ROUND = 3
MAX_INSPECTS_PER_BLOCK = 2
# SDK (Copilot) per-turn budget. Reads and mutations have SEPARATE lanes:
# with a single shared cap, mapping a large block burned the whole budget on
# reads and the model reached the edit phase with nothing left — it then
# narrated edits that never ran.
MAX_SDK_READ_TOOLS_PER_TURN = 10
MAX_SDK_MUTATING_TOOLS_PER_TURN = 8
# Legacy combined cap (kept for back-compat imports; no longer the gate).
MAX_SDK_TOOLS_PER_TURN = MAX_SDK_READ_TOOLS_PER_TURN + MAX_SDK_MUTATING_TOOLS_PER_TURN

MAX_TOOL_RESULT_CHARS = 6_000
DUPLICATE_RESULT_MSG = (
    "DUPLICATE (skipped): identical tool call already ran this turn. "
    "Use the previous tool result in context. Do not repeat this call."
)
TOO_MANY_TOOLS_MSG = (
    "SKIPPED: too many {kind} tools in one step (max {max}). "
    "Batch fewer calls per step and reuse results already in context."
)
BLOCK_INSPECT_LIMIT_MSG = (
    "SKIPPED: `{block}` was already inspected twice this turn. "
    "Use focused_block_detail and earlier tool results — do not re-read the same block."
)
READ_BUDGET_EXHAUSTED_MSG = (
    "SKIPPED (read budget reached): no more reads this turn. "
    "You can still EDIT and RUN — apply the change now with datapyn_edit / "
    "datapyn_run using what you already fetched, or tell the user what is missing."
)
MUTATION_NOT_APPLIED_MSG = (
    "NOT APPLIED: mutation budget reached — the block was NOT modified by this call. "
    "Do not tell the user this change was made. List exactly which edits are still "
    "pending so they can ask you to continue."
)

# Re-export for agent loops
__all__ = [
    "READ_ONLY_TOOLS",
    "MAX_TOOL_ROUNDS",
    "FORCE_ANSWER_AFTER_ROUND",
    "MAX_MUTATING_PER_ROUND",
    "MAX_READ_ONLY_PER_ROUND",
    "MAX_SUBAGENTS_PER_ROUND",
    "MAX_SDK_TOOLS_PER_TURN",
    "MAX_SDK_READ_TOOLS_PER_TURN",
    "MAX_SDK_MUTATING_TOOLS_PER_TURN",
    "READ_BUDGET_EXHAUSTED_MSG",
    "MUTATION_NOT_APPLIED_MSG",
    "evaluate_sdk_budget",
    "prepare_tool_calls",
    "evaluate_tool_call",
    "skipped_tool_message",
    "tool_call_key",
    "truncate_tool_result",
    "format_registry_result",
    "was_duplicate_skip",
    "should_offer_tools",
    "invalidate_block_reads",
]

# Tools whose execution changes block content — afterwards the model may
# legitimately need to re-read what it just changed.
_BLOCK_MUTATING_TOOLS = frozenset({"datapyn_edit", "datapyn_run"})


def tool_call_key(name: str, args: Dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args or {}, sort_keys=True, default=str)}"


def inspect_block_name(args: Dict[str, Any]) -> str:
    """Block name for datapyn_inspect kind=block (empty when not a block read)."""
    if not args:
        return ""
    kind = args.get("kind")
    if kind not in (None, "", "block"):
        return ""
    return str(args.get("block_name") or "").strip()


def _inspect_targets_section(args: Dict[str, Any]) -> bool:
    """True when an inspect reads a *specific section* (anchor or line range).

    Section reads target different parts of a large block, so they should not
    count toward the per-block re-read limit — identical repeats are already
    caught by the duplicate (seen_keys) guard.
    """
    if not args:
        return False
    return bool(
        str(args.get("around") or "").strip()
        or args.get("start_line") is not None
        or args.get("end_line") is not None
    )


def prepare_tool_calls(
    parsed_calls: List[Tuple[str, Dict[str, Any], str]],
    *,
    seen_keys: set[str],
    block_inspect_counts: Optional[Dict[str, int]] = None,
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
    block_counts = block_inspect_counts if block_inspect_counts is not None else {}

    for name, args, tc_id in parsed_calls:
        key = tool_call_key(name, args or {})
        if key in seen_keys:
            prepared.append((name, args, tc_id, False))
            continue

        block_name = inspect_block_name(args or {})
        # Section reads (around=/line range) target distinct parts of a large
        # block and are exempt from the per-block limit (still deduped above).
        counts_against_block = bool(block_name) and not _inspect_targets_section(args or {})
        if counts_against_block:
            if block_counts.get(block_name, 0) >= MAX_INSPECTS_PER_BLOCK:
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
        if counts_against_block:
            block_counts[block_name] = block_counts.get(block_name, 0) + 1
        prepared.append((name, args, tc_id, True))

    return prepared


def should_offer_tools(round_idx: int, *, max_rounds: int = MAX_TOOL_ROUNDS) -> bool:
    """After FORCE_ANSWER_AFTER_ROUND tool rounds, stop offering tools to the model."""
    if round_idx >= FORCE_ANSWER_AFTER_ROUND:
        return False
    return round_idx < max_rounds


def evaluate_sdk_budget(
    name: str,
    *,
    read_executions: int,
    mutating_executions: int,
) -> Tuple[bool, str]:
    """Per-turn SDK budget with separate read/mutation lanes.

    Reads exhausting their lane must never block edits — that failure mode
    made the agent map a block all turn and then "apply" edits that were
    silently skipped.
    """
    if is_mutating_tool(name):
        if mutating_executions >= MAX_SDK_MUTATING_TOOLS_PER_TURN:
            return False, MUTATION_NOT_APPLIED_MSG
        return True, ""
    if read_executions >= MAX_SDK_READ_TOOLS_PER_TURN:
        return False, READ_BUDGET_EXHAUSTED_MSG
    return True, ""


def evaluate_tool_call(
    name: str,
    args: Dict[str, Any],
    *,
    seen_keys: set[str],
    block_inspect_counts: Dict[str, int],
) -> Tuple[bool, str]:
    """Return (should_execute, skip_message). Used by the Copilot SDK tool handler."""
    prepared = prepare_tool_calls(
        [(name, args or {}, "guard")],
        seen_keys=seen_keys,
        block_inspect_counts=block_inspect_counts,
    )
    if prepared and prepared[0][3]:
        return True, ""
    return False, skipped_tool_message(name, args or {}, seen_keys, block_inspect_counts)


def was_duplicate_skip(name: str, args: Dict[str, Any], seen_keys: set[str]) -> bool:
    """True when this call was skipped because an identical call already ran."""
    return tool_call_key(name, args or {}) in seen_keys


def invalidate_block_reads(
    name: str,
    args: Dict[str, Any],
    *,
    seen_keys: set[str],
    block_inspect_counts: Optional[Dict[str, int]] = None,
) -> None:
    """After an edit/run mutates a block, drop read-dedupe state for it.

    Without this, inspecting a block right after editing it returns
    "DUPLICATE (skipped)" pointing at the stale pre-edit content.
    """
    if name not in _BLOCK_MUTATING_TOOLS:
        return
    block = str((args or {}).get("block_name") or "").strip()
    if block_inspect_counts is not None:
        if block:
            block_inspect_counts.pop(block, None)
        else:
            block_inspect_counts.clear()
    token = f'"block_name": {json.dumps(block)}' if block else ""
    for key in list(seen_keys):
        if not key.startswith("datapyn_inspect:"):
            continue
        # When the mutated block is unknown (focused-block default), allow all
        # inspects again; otherwise clear reads of that block plus unnamed
        # reads (which resolve to the focused block and may be the same one).
        if not block or token in key or '"block_name"' not in key:
            seen_keys.discard(key)


def skipped_tool_message(
    name: str,
    args: Dict[str, Any],
    seen_keys: set[str],
    block_inspect_counts: Optional[Dict[str, int]] = None,
) -> str:
    key = tool_call_key(name, args or {})
    if key in seen_keys:
        return DUPLICATE_RESULT_MSG
    block_name = inspect_block_name(args or {})
    if (
        block_name
        and not _inspect_targets_section(args or {})
        and block_inspect_counts is not None
        and block_inspect_counts.get(block_name, 0) >= MAX_INSPECTS_PER_BLOCK
    ):
        return BLOCK_INSPECT_LIMIT_MSG.format(block=block_name)
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
