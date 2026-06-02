"""
Focused block context for Pynia — the block the user was editing when they sent chat.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.copilot.mcp_tools import MCPToolRegistry


def focused_block_payload(
    block_editor,
    *,
    max_lines: int = 400,
    max_chars: int = 24_000,
) -> Optional[Dict[str, Any]]:
    """Build rich context for the block the user last focused in the editor."""
    if not block_editor:
        return None

    block = None
    if hasattr(block_editor, "get_last_focused_block"):
        block = block_editor.get_last_focused_block()
    elif hasattr(block_editor, "focused_block"):
        block = block_editor.focused_block
    if not block:
        return None

    try:
        code = block.get_code() if hasattr(block, "get_code") else ""
        name = block.get_block_name() if hasattr(block, "get_block_name") else ""
        language = block.get_language() if hasattr(block, "get_language") else "unknown"
        index = block_editor.blocks.index(block) if block in getattr(block_editor, "blocks", []) else 0
    except (ValueError, RuntimeError):
        return None

    from src.services.copilot.mcp_tools import _infer_block_hints, _truncate_code_for_tool

    hints = _infer_block_hints(code or "", language)
    code_for_model, truncate_note = _truncate_code_for_tool(
        code or "",
        max_lines=max_lines,
        max_chars=max_chars,
    )

    selection = ""
    if hasattr(block, "has_selection") and block.has_selection():
        selection = (block.get_selected_text() or "")[:2000]

    payload: Dict[str, Any] = {
        "name": name or f"block{index + 1}",
        "index": index,
        "language": language,
        "lines": len((code or "").splitlines()),
        "hints": hints,
        "is_primary_target": True,
        "code": code_for_model,
    }
    if truncate_note:
        payload["code_note"] = truncate_note
    if selection:
        payload["selection"] = selection
    from src.services.pynia.block_summary import enrich_focus_detail

    return enrich_focus_detail(payload)


def apply_focused_block_defaults(
    tool_name: str,
    args: Dict[str, Any],
    legacy: "MCPToolRegistry",
) -> Dict[str, Any]:
    """
    When the model omits block_name/index, default to the user's focused block.
    """
    out = dict(args or {})
    if out.get("block_name") or out.get("block_index") is not None:
        return out

    block_tools = {
        "datapyn_inspect",
        "datapyn_run",
        "datapyn_edit",
    }
    if tool_name not in block_tools:
        return out
    if out.get("kind") not in (None, "", "block"):
        if tool_name == "datapyn_inspect" and out.get("kind") != "block":
            return out

    mw = getattr(legacy, "_main_window", None)
    if not mw:
        return out
    session_widget = legacy._get_active_session_widget() if hasattr(legacy, "_get_active_session_widget") else None
    if not session_widget:
        return out
    block_editor = legacy._get_block_editor(session_widget) if hasattr(legacy, "_get_block_editor") else None
    focus = focused_block_payload(block_editor, max_lines=1)
    if not focus:
        return out
    out["block_name"] = focus["name"]
    out.setdefault("_pynia_focus_defaulted", True)
    return out


def start_here_directive(focus: Optional[Dict[str, Any]]) -> str:
    if not focus:
        return (
            "**START HERE**: No block had editor focus. Ask which block to use or use "
            "`datapyn_snapshot` action=blocks once."
        )
    name = focus.get("name", "")
    lang = focus.get("language", "")
    lines = focus.get("lines", 0)
    hints = ", ".join(focus.get("hints") or []) or "none"
    return (
        f"**START HERE**: The user was focused on block `{name}` ({lang}, {lines} lines, hints: {hints}). "
        f"Treat `{name}` as the primary target. Its code is in `focused_block_detail` below — "
        f"do not call `datapyn_inspect` on `{name}` unless you need a different section (use around=). "
        f"Prefer `datapyn_edit` / `datapyn_run` on `{name}` directly."
    )
