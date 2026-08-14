"""Fake ACP agent for tests — NDJSON JSON-RPC over stdio."""

from __future__ import annotations

import json
import sys


_FAKE_CONFIG_OPTIONS = [
    {
        "id": "model",
        "category": "model",
        "name": "Model",
        "currentValue": "auto",
        "options": [
            {"value": "auto", "name": "Auto"},
            {"value": "sonnet", "name": "Sonnet"},
        ],
    },
    {
        "id": "thought_level",
        "category": "thought_level",
        "name": "Reasoning",
        "currentValue": "auto",
        "options": [
            {"value": "auto", "name": "Auto"},
            {"value": "off", "name": "Off"},
            {"value": "low", "name": "Low"},
            {"value": "medium", "name": "Medium"},
            {"value": "high", "name": "High"},
        ],
    },
]


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    session_n = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        rpc_id = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "protocolVersion": 1,
                        "agentCapabilities": {"loadSession": False},
                        "authMethods": [],
                    },
                }
            )
        elif method == "authenticate":
            _send({"jsonrpc": "2.0", "id": rpc_id, "result": {}})
        elif method == "session/new":
            session_n += 1
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "sessionId": f"sess-{session_n}",
                        "configOptions": _FAKE_CONFIG_OPTIONS,
                    },
                }
            )
        elif method == "session/prompt":
            sid = params.get("sessionId") or ""
            text = ""
            for part in params.get("prompt") or []:
                if isinstance(part, dict):
                    text += part.get("text") or ""
            reply = "pong" if "pong" in text.lower() else "ok"
            if "ghost" in text.lower() or "<CURSOR>" in text:
                reply = "ghost_text"
            _send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": sid,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": reply},
                        },
                    },
                }
            )
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"stopReason": "end_turn"},
                }
            )
        elif method in {"session/load", "session/resume"}:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32000, "message": "cannot restore"},
                }
            )
        elif method == "session/close":
            _send({"jsonrpc": "2.0", "id": rpc_id, "result": {}})
        elif method == "session/cancel":
            continue
        elif method in {"session/set_config_option", "session/set_model"}:
            value = params.get("value") or params.get("modelId") or params.get("model") or "auto"
            config_id = str(params.get("configId") or "")
            options = []
            for option in _FAKE_CONFIG_OPTIONS:
                item = dict(option)
                if item["id"] == config_id or (config_id == "" and item["id"] == "model"):
                    item["currentValue"] = value
                options.append(item)
            _send({"jsonrpc": "2.0", "id": rpc_id, "result": {"configOptions": options}})
        elif rpc_id is not None:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"unknown {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
