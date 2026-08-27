"""Permission policy for ACP tool calls from Pynia.

DataPyn MCP tools always auto-allow. Confirmation is reserved for
destructive SQL/shell (DROP, DELETE, UPDATE, TRUNCATE, and similar).
"""

from __future__ import annotations

import re
from typing import Any

_DESTRUCTIVE = re.compile(
    r"\bdrop\s+(table|database|schema|index|view|procedure|function)\b"
    r"|\btruncate\b"
    r"|\bdelete\s+from\b"
    r"|\bupdate\s+\S+\s+set\b"
    r"|\balter\s+(table|database|schema)\b"
    r"|\binsert\s+into\b"
    r"|\bmerge\s+into\b"
    r"|\bgrant\b"
    r"|\brevoke\b"
    r"|rm\s+-rf"
    r"|remove-item\b"
    r"|format\s+[a-z]:"
    r"|del\s+/[fs]",
    re.IGNORECASE,
)

_HTTP_PROBE = re.compile(
    r"\bcurl\b"
    r"|\bwget\b"
    r"|\binvoke-webrequest\b"
    r"|https?://(localhost|127\.0\.0\.1)"
    r"|\blocalhost:\d+"
    r"|\b127\.0\.0\.1:\d+",
    re.IGNORECASE,
)

HTTP_PROBE_REJECT_MESSAGE = (
    "There is no DataPyn HTTP server. You are inside the DataPyn desktop IDE. "
    "Use datapyn_* MCP tools (datapyn_inspect, datapyn_query, datapyn_chart, …) "
    "instead of curl/localhost."
)

_ASK_KINDS = frozenset({"delete", "move"})


def _tool(params: dict[str, Any]) -> dict[str, Any]:
    tool = params.get("toolCall")
    return tool if isinstance(tool, dict) else params


def _bits(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None or value is False:
            continue
        if isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _identity_text(params: dict[str, Any]) -> str:
    tool = _tool(params)
    raw = tool.get("rawInput") if isinstance(tool.get("rawInput"), dict) else {}
    extra = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    return _bits(
        tool.get("title"),
        tool.get("kind"),
        tool.get("toolName"),
        tool.get("name"),
        params.get("title"),
        raw.get("name"),
        raw.get("tool"),
        raw.get("server"),
        extra.get("name"),
        extra.get("tool"),
        extra.get("server"),
    ).lower()


def _command_text(params: dict[str, Any]) -> str:
    tool = _tool(params)
    parts: list[str] = []
    for raw in (tool.get("rawInput"), tool.get("input")):
        if isinstance(raw, str):
            parts.append(raw)
        elif isinstance(raw, dict):
            for key in ("command", "sql", "query", "script", "code", "statement"):
                val = raw.get(key)
                if val:
                    parts.append(str(val))
            commands = raw.get("commands")
            if isinstance(commands, list):
                parts.extend(str(item) for item in commands)
    for item in tool.get("commands") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("command") or item.get("cmd") or ""))
        else:
            parts.append(str(item))
    title = str(tool.get("title") or params.get("title") or "")
    if title:
        parts.append(title)
    return " ".join(parts)


def is_datapyn_tool(params: dict[str, Any]) -> bool:
    text = _identity_text(params)
    return "datapyn_" in text or "datapyn-mcp" in text or "datapyn mcp" in text


def is_http_probe(params: dict[str, Any]) -> bool:
    if is_datapyn_tool(params):
        return False
    return bool(_HTTP_PROBE.search(_command_text(params)))


def permission_should_reject(params: dict[str, Any]) -> bool:
    """True for localhost/HTTP probes that invent a DataPyn server."""
    return is_http_probe(params)


def permission_should_ask(params: dict[str, Any]) -> bool:
    """True only for destructive shell/SQL. DataPyn tools always auto-allow."""
    if is_datapyn_tool(params) or permission_should_reject(params):
        return False
    tool = _tool(params)
    kind = str(tool.get("kind") or "").lower()
    if kind in _ASK_KINDS:
        return True
    return bool(_DESTRUCTIVE.search(_command_text(params)))


def reject_option_id(params: dict[str, Any]) -> str:
    options = params.get("options") or []
    ids = [str(o.get("optionId") or o.get("id") or "") for o in options if isinstance(o, dict)]
    for preferred in ("reject-once", "reject_once", "reject", "deny"):
        if preferred in ids:
            return preferred
    for oid in ids:
        if "reject" in oid.lower() or "deny" in oid.lower():
            return oid
    return "reject-once"


def allow_option_id(params: dict[str, Any]) -> str:
    options = params.get("options") or []
    ids = [str(o.get("optionId") or o.get("id") or "") for o in options if isinstance(o, dict)]
    for preferred in ("allow-always", "allow_always", "allow-once", "allow_once", "allow"):
        if preferred in ids:
            return preferred
    for oid in ids:
        if "allow" in oid.lower() and "always" in oid.lower():
            return oid
    for oid in ids:
        if "allow" in oid.lower():
            return oid
    return "allow-once"


def permission_summary(params: dict[str, Any]) -> str:
    tool = _tool(params)
    title = str(tool.get("title") or params.get("title") or "").strip()
    command = ""
    for raw in (tool.get("rawInput"), tool.get("input")):
        if isinstance(raw, str) and raw.strip():
            command = raw.strip()
            break
        if isinstance(raw, dict):
            for key in ("command", "sql", "query"):
                val = str(raw.get(key) or "").strip()
                if val:
                    command = val
                    break
        if command:
            break
    if title and command:
        snippet = command.replace("\n", " ")[:160]
        return f"{title}: {snippet}"
    if title:
        return title
    if command:
        return command.replace("\n", " ")[:200]
    kind = str(tool.get("kind") or "").strip()
    return kind or "Allow this action?"
