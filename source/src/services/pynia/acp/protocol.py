"""ACP handshake constants and JSON-RPC payloads (shared by every agent)."""

from __future__ import annotations

from typing import Any, Optional

PROTOCOL_VERSION = 1
CLIENT_NAME = "DataPyn"
CLIENT_TITLE = "Pynia"


def client_version() -> str:
    try:
        from importlib.metadata import version

        return version("DataPyn")
    except Exception:
        return "0.0.0"


def initialize_params(version: str = "0.0.0") -> dict[str, Any]:
    """Client hello advertised to Claude, Copilot, Codex, and Cursor."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
            "session": {"configOptions": {"boolean": {}}},
        },
        "clientInfo": {
            "name": CLIENT_NAME,
            "title": CLIENT_TITLE,
            "version": version or "0.0.0",
        },
    }


def session_new_params(cwd: str, mcp_servers: Optional[list[dict]] = None) -> dict[str, Any]:
    return {"cwd": cwd, "mcpServers": mcp_servers or []}


def set_config_option_params(session_id: str, config_id: str, value: str) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "configId": config_id,
        "type": "id",
        "value": value,
    }


def set_model_params(session_id: str, model_id: str) -> dict[str, Any]:
    return {"sessionId": session_id, "modelId": model_id, "model": model_id}


def session_prompt_params(session_id: str, prompt: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sessionId": session_id, "prompt": prompt}
