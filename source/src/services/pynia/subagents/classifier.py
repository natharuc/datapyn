"""Classify Pynia tools for parallel explore vs main-thread mutation."""

from __future__ import annotations

from typing import Any, Dict, List

# Read-only observation (safe to batch; IDE marshals via ThreadSafeToolExecutor)
READ_ONLY_TOOLS = frozenset({
    "datapyn_snapshot",
    "datapyn_inspect",
    "datapyn_database",
    "datapyn_query",
})

# Subagent spawn — handled by orchestrator, not the legacy registry
SUBAGENT_TOOL = "datapyn_subagent"

# Tools explore subagents may call (read-only only)
EXPLORE_SUBAGENT_TOOLS = READ_ONLY_TOOLS

MUTATING_TOOLS = frozenset({
    "datapyn_edit",
    "datapyn_run",
    "datapyn_blocks",
    "datapyn_chart",
    "datapyn_notify",
})


def is_read_only_tool(name: str) -> bool:
    return name in READ_ONLY_TOOLS


def is_mutating_tool(name: str) -> bool:
    return name in MUTATING_TOOLS


def is_subagent_tool(name: str) -> bool:
    return name == SUBAGENT_TOOL


def filter_openai_tools(
    tools: List[Dict[str, Any]],
    allowed: frozenset[str],
) -> List[Dict[str, Any]]:
    """Keep only tools whose function name is in *allowed*."""
    out: List[Dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name", "")
        if name in allowed:
            out.append(tool)
    return out
