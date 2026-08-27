"""Normalize ACP tool/thinking events for the Pynia chat activity block."""

from __future__ import annotations

from typing import Any, Optional

from src.services.pynia.acp.mcp_host import normalize_mcp_tool_name

_MAX_THINKING_CHARS = 8_000

_HIDDEN_TITLES = frozenset({
    "",
    "tool_call",
    "tool_call_update",
    "tool_search_tool",
    "execute",
    "read",
    "edit",
    "search",
    "fetch",
    "other",
})

_RUNNING = frozenset({"pending", "in_progress", "running", "inprogress"})
_DONE = frozenset({"completed", "complete", "success", "ok", "done"})
_ERROR = frozenset({"failed", "error", "cancelled", "canceled", "timed_out"})


def display_tool_title(raw: str) -> str:
    """Strip Copilot chrome: datapyn-datapyn_query → datapyn_query."""
    return normalize_mcp_tool_name((raw or "").strip())


def _status_from(raw: str, *, default: str) -> str:
    value = (raw or "").strip().lower()
    if value in _ERROR:
        return "error"
    if value in _DONE:
        return "completed"
    if value in _RUNNING:
        return "running"
    return default


def _error_text(payload: dict[str, Any], nested: dict[str, Any]) -> str:
    content = payload.get("content") or nested.get("content") or []
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        bits: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                bits.append(str(item.get("text")))
            elif isinstance(item, str):
                bits.append(item)
        return "\n".join(bits).strip()
    return str(payload.get("error") or nested.get("error") or "").strip()


def format_activity_tool(payload: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Compact tool row for the collapsible working block. None = skip."""
    data = payload if isinstance(payload, dict) else {}
    kind = str(data.get("sessionUpdate") or "")
    nested = data.get("toolCall") if isinstance(data.get("toolCall"), dict) else {}
    tool_id = str(
        data.get("toolCallId")
        or nested.get("toolCallId")
        or nested.get("id")
        or data.get("id")
        or ""
    ).strip()
    title = display_tool_title(str(data.get("title") or nested.get("title") or ""))
    raw_status = str(data.get("status") or nested.get("status") or "")
    is_error = bool(data.get("isError") or nested.get("isError") or raw_status.lower() in _ERROR)
    default_status = "completed" if kind == "tool_call_update" else "running"
    status = _status_from(raw_status, default=default_status)
    if is_error:
        status = "error"
    error = _error_text(data, nested) if status == "error" else ""
    if title.lower() in _HIDDEN_TITLES:
        title = ""
    if not title and not tool_id:
        return None
    card: dict[str, Any] = {
        "id": tool_id or title,
        "status": status,
    }
    if title:
        card["title"] = title
    elif kind != "tool_call_update":
        card["title"] = "tool"
    if error:
        card["error"] = error
    return card


def merge_activity_tool(tools: list[dict[str, Any]], card: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert or update a tool row by id."""
    tid = str(card.get("id") or "")
    if tid:
        for item in tools:
            if item.get("id") == tid:
                for key, value in card.items():
                    if key in {"title", "error"} and not value:
                        continue
                    item[key] = value
                return tools
    tools.append(dict(card))
    return tools


def clip_thinking(existing: str, chunk: str) -> str:
    blob = (existing or "") + (chunk or "")
    if len(blob) > _MAX_THINKING_CHARS:
        return blob[-_MAX_THINKING_CHARS:]
    return blob
