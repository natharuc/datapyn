"""Classify Pynia tools and route explore work to fast paths or subagents."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Read-only observation (safe to batch; IDE marshals via ThreadSafeToolExecutor)
READ_ONLY_TOOLS = frozenset({
    "datapyn_snapshot",
    "datapyn_inspect",
    "datapyn_database",
    "datapyn_query",
})

SUBAGENT_TOOL = "datapyn_subagent"
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
    out: List[Dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name", "")
        if name in allowed:
            out.append(tool)
    return out


def should_delegate_to_subagent(user_text: str, *, block_count: int = 0) -> bool:
    """Heuristic: broad discovery questions benefit from parallel explore."""
    text = (user_text or "").lower()
    if block_count > 8 and any(w in text for w in ("all blocks", "every block", "overview", "scan")):
        return True
    if sum(1 for w in ("schema", "tables", "database") if w in text) >= 2:
        return True
    if "compare" in text and block_count > 4:
        return True
    return False


def suggest_explore_tasks(
    user_text: str,
    *,
    connection_name: str = "",
) -> List[Dict[str, str]]:
    """Build tasks[] for datapyn_subagent when the user asks a multi-part explore question."""
    text = (user_text or "").strip()
    tasks: List[Dict[str, str]] = []
    lower = text.lower()
    if connection_name or any(w in lower for w in ("schema", "table", "database", "sql")):
        tasks.append({
            "task_id": "schema",
            "instruction": "datapyn_snapshot action=schema — list tables and key columns.",
        })
    if any(w in lower for w in ("block", "code", "html", "python", "script")):
        tasks.append({
            "task_id": "blocks",
            "instruction": "datapyn_snapshot action=blocks — summarize each block name, language, and purpose.",
        })
    if any(w in lower for w in ("variable", "dataframe", "df ", "data ")):
        tasks.append({
            "task_id": "vars",
            "instruction": "datapyn_snapshot action=variables — list namespace variables and types.",
        })
    return tasks[:3]


def try_parse_single_tool_call(instruction: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Fast path: instruction is clearly one read-only tool (no LLM subagent hop).

    Returns (tool_name, arguments) or None.
    """
    text = (instruction or "").strip()
    if not text:
        return None

    lower = text.lower()
    if lower.startswith("datapyn_"):
        parts = text.split(None, 1)
        name = parts[0].split("(")[0]
        if name in READ_ONLY_TOOLS:
            args: Dict[str, Any] = {}
            if "action=" in lower:
                m = re.search(r"action\s*=\s*(\w+)", lower)
                if m:
                    args["action"] = m.group(1)
            if "block" in lower:
                m = re.search(r"block[_\s]+[`'\"]?([\w-]+)", text, re.I)
                if m:
                    args["kind"] = "block"
                    args["block_name"] = m.group(1)
            if "structure" in lower:
                args.setdefault("kind", "block")
                args["detail"] = "structure"
            return name, args

    if "schema" in lower and "snapshot" in lower:
        return "datapyn_snapshot", {"action": "schema"}
    if re.search(r"\b(list|show)\s+blocks\b", lower):
        return "datapyn_snapshot", {"action": "blocks"}
    if "variables" in lower:
        return "datapyn_snapshot", {"action": "variables"}
    m = re.search(
        r"(?:inspect|read|structure of)\s+(?:block\s+)?[`'\"]?([\w-]+)[`'\"]?",
        text,
        re.I,
    )
    if m:
        args = {"kind": "block", "block_name": m.group(1)}
        if "structure" in lower:
            args["detail"] = "structure"
        elif "result" in lower:
            args["detail"] = "result"
        else:
            args["detail"] = "structure"
        return "datapyn_inspect", args
    return None
