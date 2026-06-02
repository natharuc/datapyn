"""Human-readable agent progress labels for the Pynia chat UI."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def format_tool_display(tool_name: str, arguments: Dict[str, Any] | None) -> Tuple[str, str]:
    """
    Return (title, detail) for chat UI — block-aware, not raw MCP names.

    Title strings are English defaults; the panel may localize via i18n keys.
    """
    args = arguments or {}
    name = tool_name or ""

    if name == "datapyn_inspect":
        kind = (args.get("kind") or "block").lower()
        if kind == "block":
            block = args.get("block_name") or (f"#{args['block_index']}" if args.get("block_index") is not None else "focused block")
            detail = (args.get("detail") or "structure").lower()
            if args.get("around"):
                return f"Reading block `{block}`", f"lines around {args.get('around')}"
            return f"Inspecting `{block}`", f"detail={detail}"
        if kind == "variable":
            return "Inspecting variable", str(args.get("variable_name") or "")
        if kind == "reference":
            return "Resolving reference", str(args.get("reference") or "")
        if kind == "selection":
            return "Reading editor selection", ""
        return "Inspecting", kind

    if name == "datapyn_snapshot":
        action = (args.get("action") or "context").lower()
        labels = {
            "context": ("Reading tab context", ""),
            "blocks": ("Listing blocks", ""),
            "schema": ("Loading database schema", ""),
            "variables": ("Reading variables", ""),
            "full": ("Reading workspace snapshot", ""),
        }
        return labels.get(action, (f"Snapshot: {action}", ""))

    if name == "datapyn_query":
        lang = (args.get("language") or "sql").upper()
        code = (args.get("code") or "").strip().replace("\n", " ")
        preview = code[:72] + ("…" if len(code) > 72 else "")
        return f"Running silent {lang}", preview

    if name == "datapyn_database":
        op = (args.get("operation") or "list").lower()
        if op == "schema":
            return "Loading schema", ""
        if op == "tables":
            return "Listing tables", str(args.get("connection_name") or "")
        if op == "sample":
            return "Sampling table", str(args.get("table_name") or "")
        if op == "describe":
            return "Describing table", str(args.get("table_name") or "")
        return f"Database: {op}", ""

    if name == "datapyn_edit":
        op = (args.get("operation") or "replace").lower()
        block = args.get("block_name") or "focused block"
        return f"Editing `{block}`", f"operation={op}"

    if name == "datapyn_run":
        mode = (args.get("mode") or "block").lower()
        if mode == "write":
            return "Writing and running code", ""
        if mode == "all":
            return "Running all blocks", ""
        block = args.get("block_name") or "focused block"
        return f"Running `{block}`", ""

    if name == "datapyn_blocks":
        op = (args.get("operation") or "create").lower()
        return f"Blocks: {op}", str(args.get("title") or args.get("block_name") or "")

    if name == "datapyn_chart":
        return f"Chart: {args.get('operation', 'list')}", ""

    if name == "datapyn_notify":
        return "Notifying you", str(args.get("message") or "")[:80]

    if name == "datapyn_subagent":
        instr = str(args.get("instruction") or args.get("task") or "").strip()
        tasks = args.get("tasks")
        if isinstance(tasks, list) and len(tasks) > 1:
            return f"Parallel explore ({len(tasks)} agents)", ""
        if instr:
            return "Explore subagent", instr[:80] + ("…" if len(instr) > 80 else "")
        return "Explore subagent", ""

    # Legacy MCP names (Copilot path)
    legacy = {
        "get_context": ("Reading context", ""),
        "list_blocks": ("Listing blocks", ""),
        "get_block_code": ("Reading block code", ""),
        "edit_block": ("Editing block", ""),
        "execute_block": ("Running block", ""),
        "run_silent_query": ("Running query", ""),
    }
    if name in legacy:
        return legacy[name]

    return name.replace("datapyn_", "").replace("_", " ").title(), _arg_preview(args)


def _arg_preview(args: Dict[str, Any]) -> str:
    parts = []
    for key, val in list(args.items())[:3]:
        if key == "thought":
            continue
        s = str(val)
        parts.append(f"{key}={s[:40]}{'…' if len(s) > 40 else ''}")
    return ", ".join(parts)


# Progress phase keys — mapped to S.pynia.* in the chat panel
PHASE_PLANNING = "activity_planning"
PHASE_ANALYZING = "activity_analyzing"
PHASE_SYNTHESIZING = "activity_synthesizing"
PHASE_WAITING_MODEL = "activity_waiting_model"
PHASE_TOOL_DONE = "activity_tool_done"
