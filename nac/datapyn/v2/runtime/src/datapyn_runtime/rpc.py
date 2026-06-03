"""Minimal JSON-RPC 2.0 over newline-delimited JSON (stdio)."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, Optional

Handler = Callable[[Dict[str, Any]], Any]


class JsonRpcServer:
    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = message.get("id")
        method = message.get("method")
        if not method:
            return self._error(msg_id, -32600, "Invalid Request: missing method")

        handler = self._handlers.get(method)
        if handler is None:
            return self._error(msg_id, -32601, f"Method not found: {method}")

        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self._error(msg_id, -32602, "Invalid params")

        try:
            result = handler(params)
            if msg_id is None:
                return None
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as exc:  # noqa: BLE001 — surface to client
            return self._error(msg_id, -32000, str(exc))

    def _error(
        self, msg_id: Any, code: int, message: str, data: Any = None
    ) -> Optional[Dict[str, Any]]:
        if msg_id is None:
            return None
        err: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": err}

    def run_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._write(
                    self._error(None, -32700, "Parse error")
                    or {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
                )
                continue
            if not isinstance(message, dict):
                continue
            response = self.handle(message)
            if response is not None:
                self._write(response)

    @staticmethod
    def _write(payload: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def request(method: str, params: Optional[Dict[str, Any]] = None, msg_id: int = 1) -> str:
    """Serialize a JSON-RPC request (for tests/clients)."""
    body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": msg_id}
    if params is not None:
        body["params"] = params
    return json.dumps(body, ensure_ascii=False)
