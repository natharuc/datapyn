"""Tab + tool context injected into every ACP prompt."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from src.services.pynia.tools.definitions import pynia_tool_definitions

logger = logging.getLogger(__name__)

_MAX_BLOCK_PREVIEW = 800
_MAX_CONTEXT_CHARS = 24_000

_TOOL_BLURB = (
    "You are Pynia, the in-IDE agent for DataPyn (a desktop SQL/Python IDE). "
    "You are already running INSIDE DataPyn — not a remote app, not a website. "
    "There is no DataPyn HTTP API and no localhost server to probe. "
    "ALWAYS use DataPyn MCP tools (`datapyn_*` on server `datapyn`) to create, edit, "
    "run blocks, query data, and read context — never bash, curl, files, or menus. "
    "Never curl localhost / 127.0.0.1. "
    "CURRENT TAB JSON is a snapshot hint only; still call tools to mutate the IDE "
    "(create/edit/run) or when you need fresher detail. "
    "If a tool errors, read the error text and retry with corrected args — "
    "that is not a server connection failure. Only treat the MCP as dead if the "
    "message says Transport closed. "
    "Never answer with a numbered menu of options (graph vs block vs visualization). "
    "Only ask when a required value is truly missing or the action is destructive."
)


def _tools_block() -> str:
    lines = [
        "TOOLS (call these datapyn_* MCP tools on server datapyn — they run in this DataPyn window):",
        "- datapyn_snapshot: read tab/blocks/schema/variables (action=context|blocks|schema|full).",
        "- datapyn_inspect: inspect a target — kind=block detail=code|result|structure "
        "(default detail for blocks is result/grid; use detail=code for editor source).",
        "- datapyn_blocks: operation=create|focus|tab — create a new SQL/Python block or switch focus.",
        "- datapyn_edit: operation=replace|lines|selection|rename|delete|language — change editor content.",
        "- datapyn_run: mode=block|write|all — execute; mode=write creates/updates then runs.",
        "- datapyn_query: silent SQL/Python on THIS tab's live session "
        "(do not connect first if is_connected is true).",
    ]
    for spec in pynia_tool_definitions():
        name = spec.get("name") or ""
        desc = (spec.get("description") or "").split(". ")[0].strip()
        if name and name not in {
            "datapyn_snapshot",
            "datapyn_inspect",
            "datapyn_query",
            "datapyn_edit",
            "datapyn_run",
            "datapyn_blocks",
        }:
            lines.append(f"- {name}: {desc}")
    lines.append(
        "If is_connected is true in CURRENT TAB JSON, do NOT call datapyn_database "
        "operation=connect or open. Use datapyn_query. "
        "Do not fire several datapyn_database describe calls in parallel if the snapshot "
        "already has the connection. One tool at a time unless they are independent."
    )
    return "\n".join(lines)

_CHART_RE = re.compile(
    r"gr[aá]fico|grafico|\bchart\b|\bplot\b|\bgraph\b|visualiza",
    re.IGNORECASE,
)
_QUERY_RE = re.compile(
    r"\bquer(?:y|ie)s?\b|\bsql\b|\bselect\b|\bconsulta\b",
    re.IGNORECASE,
)
_WRITE_RE = re.compile(
    r"escrev|write|mont[ae]|cria[r]?\b|faz(?:er)?\b|gera[r]?\b",
    re.IGNORECASE,
)
_EDIT_RE = re.compile(
    r"\bedit|\baltera|\bmuda|\bcorri[gj]|\bfix\b|\breplace\b",
    re.IGNORECASE,
)
_RUN_RE = re.compile(
    r"\broda|\bexecut|\brun\b|\bf5\b",
    re.IGNORECASE,
)


def action_directive(user_text: str, context: Optional[dict[str, Any]] = None) -> str:
    """One-line order for this turn so the agent does not offer a menu."""
    text = user_text or ""
    ctx = context or {}
    result = (ctx.get("execution_state") or {}).get("active_result") or {}
    columns = result.get("columns") or []
    col_hint = f" Columns: {', '.join(str(c) for c in columns[:16])}." if columns else ""
    if _CHART_RE.search(text):
        return (
            "THIS TURN: call datapyn_chart operation=create now."
            f"{col_hint} Infer type/x_column/y_columns. Do not ask. Do not list options."
        )
    if _QUERY_RE.search(text) and _WRITE_RE.search(text):
        return (
            "THIS TURN: write the SQL into the editor with datapyn_run mode=write "
            "(or datapyn_blocks operation=create then datapyn_edit). "
            "Do not ask. Do not only explain."
        )
    if _WRITE_RE.search(text) and re.search(r"\bblock\b|bloco", text, re.IGNORECASE):
        return (
            "THIS TURN: call datapyn_blocks operation=create (and datapyn_edit/datapyn_run as needed). "
            "Do not only paste code in chat."
        )
    if _EDIT_RE.search(text):
        return (
            "THIS TURN: call datapyn_edit on the focused block and apply the change. Do not ask."
        )
    if _RUN_RE.search(text):
        return "THIS TURN: call datapyn_run. Do not ask the user to press F5."
    return (
        "THIS TURN: call the matching datapyn_* tool. "
        "Do not present a numbered menu. Do not ask graph vs block vs visualization."
    )


def _context_headline(ctx: dict[str, Any]) -> str:
    bits: list[str] = []
    if ctx.get("tab_name"):
        bits.append(f"tab={ctx['tab_name']}")
    if ctx.get("is_connected"):
        name = ctx.get("connection_name") or "database"
        db = ctx.get("database") or ""
        bits.append(f"connected={name}" + (f" db={db}" if db else ""))
    else:
        bits.append("not connected")
    result = (ctx.get("execution_state") or {}).get("active_result") or {}
    cols = result.get("columns") or []
    if cols:
        bits.append("grid_columns=" + ", ".join(str(c) for c in cols[:20]))
        if result.get("rows") is not None:
            bits.append(f"rows={result.get('rows')}")
    focus = ctx.get("focused_block")
    if focus:
        bits.append(f"focused_block={focus}")
    variables = ctx.get("variables") or {}
    if variables:
        names = ", ".join(str(k) for k in list(variables)[:12])
        bits.append(f"variables={names}")
    if not bits:
        return "Current tab snapshot is attached as JSON."
    line = "Current tab: " + "; ".join(bits)
    if ctx.get("is_connected"):
        line += ". Do NOT call datapyn_database operation=connect or open."
    return line


def _agent_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """Short recoverable snapshot — not the full tool catalog."""
    exec_state = ctx.get("execution_state") or {}
    result = exec_state.get("active_result") or {}
    blocks = []
    for item in ctx.get("blocks") or []:
        preview = str(item.get("code_preview") or "")[:400]
        blocks.append(
            {
                "name": item.get("name"),
                "language": item.get("language"),
                "focused": bool(item.get("focused")),
                "lines": item.get("lines"),
                "preview": preview,
            }
        )
    snap: dict[str, Any] = {
        "tab_id": ctx.get("tab_id"),
        "tab_name": ctx.get("tab_name"),
        "connection_name": ctx.get("connection_name"),
        "database": ctx.get("database"),
        "is_connected": ctx.get("is_connected"),
        "blocks": blocks,
        "focused_block": ctx.get("focused_block"),
    }
    variables = ctx.get("variables") or {}
    if variables:
        snap["variables"] = variables
    if ctx.get("is_connected"):
        name = ctx.get("connection_name") or "database"
        snap["how_to_use"] = (
            f"This tab is already connected to {name}. "
            "Do NOT call datapyn_database operation=connect or open. "
            "Run datapyn_query (SQL or Python) on this session. "
            "In-memory variables are listed under variables."
        )
    else:
        snap["how_to_use"] = (
            "This tab is not connected. Use datapyn_database operation=connect "
            "with a saved connection_name before SQL."
        )
    if result:
        snap["result"] = {
            "rows": result.get("rows"),
            "columns": result.get("columns"),
            "preview": result.get("preview"),
        }
    last_error = exec_state.get("last_error") or ctx.get("last_error")
    if last_error:
        snap["last_error"] = last_error
    return snap


def _context_blob(context: Optional[dict[str, Any]]) -> str:
    payload = _agent_snapshot(dict(context or {}))
    blob = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if len(blob) > _MAX_CONTEXT_CHARS:
        return blob[:_MAX_CONTEXT_CHARS] + "\n... (truncated)"
    return blob


def format_acp_prompt_parts(
    user_text: str,
    context: Optional[dict[str, Any]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """ACP content blocks: instructions, tab JSON, attachments, user text.

    Tab context is plain text (not a datapyn:// resource) so agents do not try
    to fetch a remote DataPyn server.
    """
    from src.services.pynia.acp.attachments import prompt_blocks_for_attachments

    ctx = dict(context or {})
    directive = action_directive(user_text, ctx)
    headline = _context_headline(ctx)
    start_here = ""
    try:
        from src.services.pynia.focus_context import start_here_directive

        start_here = start_here_directive(ctx.get("focused_block_detail"))
    except Exception:
        start_here = ""
    why = (
        f"{_TOOL_BLURB}\n\n"
        f"WHY YOU WERE CALLED\n"
        f"User: {user_text or '(see attached files)'}\n"
        f"{headline}\n"
        f"{directive}"
    )
    if start_here:
        why += f"\n{start_here}"
    where = (
        "WHERE YOU ARE (already in this process — do not HTTP-fetch it):\n"
        "CURRENT TAB JSON\n"
        + _context_blob(ctx)
    )
    parts: list[dict[str, Any]] = [
        {"type": "text", "text": why},
        {"type": "text", "text": where},
        {"type": "text", "text": _tools_block()},
    ]
    parts.extend(prompt_blocks_for_attachments(attachments or []))
    parts.append({"type": "text", "text": user_text or "(see attached files)"})
    return parts


def _main_window(registry) -> Any:
    if registry is None:
        return None
    legacy = getattr(registry, "legacy_registry", None) or registry
    return getattr(legacy, "_main_window", None) or getattr(registry, "_main_window", None)


def _session_widget(main_window, tab_id: str):
    widgets = getattr(main_window, "_session_widgets", None) or {}
    widget = widgets.get(tab_id) if isinstance(widgets, dict) else None
    if widget is not None:
        return widget
    if isinstance(widgets, dict):
        for candidate in widgets.values():
            session = getattr(candidate, "session", None)
            if session is not None and getattr(session, "session_id", None) == tab_id:
                return candidate
    tabs = getattr(main_window, "session_tabs", None)
    if tabs is not None:
        try:
            count = int(tabs.count())
        except Exception:
            count = 0
        for idx in range(count):
            candidate = tabs.widget(idx)
            session = getattr(candidate, "session", None)
            if session is not None and getattr(session, "session_id", None) == tab_id:
                return candidate
    if hasattr(main_window, "_get_current_session_widget"):
        try:
            return main_window._get_current_session_widget()
        except Exception:
            return None
    return None


def _block_summaries(block_editor) -> list[dict[str, Any]]:
    blocks = getattr(block_editor, "blocks", []) or []
    last_focused = None
    if hasattr(block_editor, "get_last_focused_block"):
        last_focused = block_editor.get_last_focused_block()
    elif hasattr(block_editor, "focused_block"):
        last_focused = block_editor.focused_block
    out: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        try:
            code = block.get_code() if hasattr(block, "get_code") else ""
            name = block.get_block_name() if hasattr(block, "get_block_name") else f"block{i + 1}"
            language = block.get_language() if hasattr(block, "get_language") else "unknown"
            preview = code[:_MAX_BLOCK_PREVIEW]
            if len(code) > _MAX_BLOCK_PREVIEW:
                preview += " ..."
            out.append(
                {
                    "index": i,
                    "name": name or f"block{i + 1}",
                    "language": language,
                    "lines": len((code or "").splitlines()),
                    "focused": block is last_focused,
                    "code_preview": preview,
                }
            )
        except Exception:
            continue
    return out


def collect_tab_context(tab_id: str, tab_name: str = "", registry=None) -> dict[str, Any]:
    """Snapshot of the active DataPyn tab for the ACP agent."""
    context: dict[str, Any] = {
        "tab_id": tab_id,
        "tab_name": tab_name or "",
    }
    mw = _main_window(registry)
    if mw is None:
        return context

    if registry is not None and hasattr(registry, "pin_session") and tab_id:
        try:
            registry.pin_session(tab_id)
        except Exception:
            pass

    widget = _session_widget(mw, tab_id)
    session = getattr(widget, "session", None) if widget else None
    if session is not None:
        context["connection_name"] = getattr(session, "connection_name", "") or ""
        context["database"] = getattr(session, "database", "") or ""
        try:
            context["is_connected"] = bool(session.is_connected)
        except Exception:
            context["is_connected"] = False
        if not context["tab_name"]:
            context["tab_name"] = getattr(session, "title", "") or ""

    if widget is not None:
        editor = getattr(widget, "editor", None)
        blocks = _block_summaries(editor)
        if blocks:
            context["blocks"] = blocks
            context["focused_block"] = next(
                (b["name"] for b in blocks if b.get("focused")), None
            )
        try:
            from src.services.copilot.mcp_tools import _namespace_summary, _session_namespace

            variables = _namespace_summary(_session_namespace(widget))
            if variables:
                context["variables"] = variables
        except Exception as exc:
            logger.debug("ACP tab context: variables skipped: %s", exc)

    try:
        from src.services.pynia.execution_context import build_execution_context

        execution = build_execution_context(mw, tab_id)
        if execution:
            context["execution_state"] = execution
    except Exception as exc:
        logger.debug("ACP tab context: execution_state skipped: %s", exc)

    try:
        from src.services.pynia.focus_context import focused_block_payload

        editor = getattr(widget, "editor", None) if widget is not None else None
        focus = focused_block_payload(editor) if editor else None
        if focus:
            context["focused_block_detail"] = focus
    except Exception as exc:
        logger.debug("ACP tab context: focused block skipped: %s", exc)

    return context


def format_acp_prompt(
    user_text: str,
    context: Optional[dict[str, Any]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Flattened prompt for tests and agents that only accept a single text block."""
    chunks: list[str] = []
    for part in format_acp_prompt_parts(user_text, context, attachments=attachments):
        kind = part.get("type")
        if kind == "text":
            chunks.append(str(part.get("text") or ""))
        elif kind == "image":
            name = part.get("name") or "image"
            chunks.append(f"[attached image: {name} ({part.get('mimeType') or 'image'})]")
        elif kind == "resource":
            resource = part.get("resource") or {}
            chunks.append(str(resource.get("text") or ""))
    return "\n\n".join(chunks)
