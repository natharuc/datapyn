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
    "You already have powers: run SQL/Python, read the Results grid, create/edit "
    "blocks, and create charts. Act. Do not narrate how the user could do it in the UI.\n\n"
    "ALWAYS prefer a DataPyn MCP tool (`datapyn_*` on server `datapyn`) over bash, "
    "curl, files, or asking which option to pick. If a datapyn tool exists for the "
    "job, call it in this turn. Never curl localhost / 127.0.0.1. If a tool errors, "
    "read the error text — it is not a 'server connection' failure.\n\n"
    "Route immediately:\n"
    "- graph / chart / gráfico / plot → datapyn_chart (operation=create). "
    "If execution_state.active_result or chart_sources is in context, use it now. "
    "Pick sensible type/x_column/y_columns from the grid. Do not ask graph vs block.\n"
    "- run / execute / rodar / F5 → datapyn_run\n"
    "- change / edit / fix code → datapyn_edit on the focused block\n"
    "- new block / new tab → datapyn_blocks\n"
    "- inspect result / grid / dataframe → datapyn_inspect kind=block detail=result\n"
    "- ad-hoc SQL or Python (no editor change) → datapyn_query\n"
    "- schema / connections / tables → datapyn_database\n"
    "- what is in this tab / workspace → datapyn_snapshot\n"
    "- done / error toast → datapyn_notify\n\n"
    "The JSON below is the CURRENT TAB. Do not ask the user to paste data, SQL, or "
    "files that are already there. Never answer with a numbered menu of options "
    "(graph vs block vs visualization). Only ask when a required value is truly "
    "missing (no connection, no result grid at all) or the action is destructive."
)

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
            "(or datapyn_edit on the focused SQL block). Do not ask. Do not only explain."
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
    result = (ctx.get("execution_state") or {}).get("active_result") or {}
    cols = result.get("columns") or []
    if cols:
        bits.append("grid_columns=" + ", ".join(str(c) for c in cols[:20]))
        if result.get("rows") is not None:
            bits.append(f"rows={result.get('rows')}")
    focus = ctx.get("focused_block")
    if focus:
        bits.append(f"focused_block={focus}")
    if not bits:
        return "Current tab snapshot is attached as JSON."
    return "Current tab: " + "; ".join(bits)


def _context_blob(context: Optional[dict[str, Any]]) -> str:
    payload = dict(context or {})
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
    blob = _context_blob(ctx)
    directive = action_directive(user_text, ctx)
    headline = _context_headline(ctx)
    parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": f"{_TOOL_BLURB}\n\n{headline}\n{directive}",
        },
        {
            "type": "text",
            "text": "CURRENT TAB JSON (already in this process — do not HTTP-fetch it):\n" + blob,
        },
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
    widget = widgets.get(tab_id)
    if widget is not None:
        return widget
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
        "tools": [
            {"name": spec["name"], "description": spec["description"]}
            for spec in pynia_tool_definitions()
        ],
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
        context["is_connected"] = bool(getattr(session, "is_connected", False))
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
