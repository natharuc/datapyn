"""Shared pure MCP result/name normalization for both desktop frontends."""
from __future__ import annotations
import json
from typing import Any

def normalize_mcp_tool_name(name: str) -> str:
    """Strip Copilot chrome prefixes: datapyn-datapyn_query → datapyn_query."""
    raw = str(name or "").strip()
    lowered = raw.lower()
    for prefix in ("datapyn-", "datapyn/", "datapyn."):
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            lowered = raw.lower()
    return raw


def wrap_tool_result(raw: Any) -> dict[str, Any]:
    """MCP tools/call result. Pass through content; never JSON-stringify it."""
    if isinstance(raw, dict) and raw.get("error"):
        return _mcp_error(str(raw["error"]))
    if isinstance(raw, dict) and isinstance(raw.get("content"), list):
        return {
            "content": raw["content"],
            "isError": bool(raw.get("isError")),
        }
    if isinstance(raw, str):
        return {"content": [{"type": "text", "text": raw}], "isError": False}
    text = json.dumps(raw, ensure_ascii=False, default=str) if raw is not None else ""
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _mcp_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}
