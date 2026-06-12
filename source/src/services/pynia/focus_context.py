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
    # mode=write without a block_name means "create a new block" — defaulting
    # to the focused block here would overwrite the user's code instead.
    if tool_name == "datapyn_run" and (out.get("mode") or "").lower().strip() == "write":
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


def focused_block_chip_payload(
    block_editor,
    *,
    max_lines: int = 400,
    max_chars: int = 24_000,
) -> Optional[Dict[str, Any]]:
    """
    Compact display payload for the composer / message attachment chip.

    The chip only needs name/language/line-count, so it reads those directly
    from the block — it does NOT build the full focused_block_payload (code
    truncation + AST structure parse), which ran on every focus change and was
    a real source of editor lag.
    """
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
        name = block.get_block_name() if hasattr(block, "get_block_name") else ""
        language = block.get_language() if hasattr(block, "get_language") else "unknown"
        code = block.get_code() if hasattr(block, "get_code") else ""
        index = block_editor.blocks.index(block) if block in getattr(block_editor, "blocks", []) else 0
    except (ValueError, RuntimeError):
        return None

    name = str(name or f"block{index + 1}")
    language = str(language or "unknown")
    lines = len((code or "").splitlines())
    line_range = f"1-{lines}" if lines > 1 else ("1" if lines == 1 else "")
    label = f"{name}:{line_range}" if line_range else name
    return {
        "type": "focused_block",
        "block_name": name,
        "language": language,
        "lines": lines,
        "line_range": line_range,
        "label": label,
        "index": index,
        "is_primary_target": True,
    }


def attached_references_directive(refs) -> str:
    """Directive for #block/#tab references the user typed in the chat.

    Explicit attachments outrank the focused block as the target.
    """
    if not refs:
        return ""
    labels = []
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("ok"):
            continue
        if ref.get("type") == "block":
            labels.append(
                f"block `{ref.get('name', '?')}` "
                f"({ref.get('language', '?')}, {ref.get('lines', 0)} lines)"
            )
        elif ref.get("type") == "tab":
            labels.append(f"tab `{ref.get('title', '?')}`")
    if not labels:
        return ""
    return (
        "**USER ATTACHMENTS (highest priority)**: the user explicitly referenced "
        + ", ".join(labels)
        + ". Their full content is in `active_references` in the context JSON — "
        "treat them as the primary targets, above the focused block, and do not "
        "re-inspect them."
    )


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
        f"Treat `{name}` as the primary target. Its code and `structure_summary` are in "
        f"`focused_block_detail` below — do not call `datapyn_inspect` or `datapyn_snapshot` on `{name}`. "
        f"For edits or logic changes, use `datapyn_edit` on `{name}` immediately (one tool round)."
    )
