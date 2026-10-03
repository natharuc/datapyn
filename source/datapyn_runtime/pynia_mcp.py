"""Authenticated loopback MCP bridge for this desktop runtime."""

from __future__ import annotations

import json
import secrets
import socket
import threading

from src.services.pynia.tools.definitions import pynia_tool_definitions
from src.services.pynia.acp.mcp_helpers import normalize_mcp_tool_name, wrap_tool_result

MAX_MESSAGE_BYTES = 2 * 1024 * 1024


def tool_definitions():
    return [{"name": item["name"], "description": item["description"],
             "inputSchema": {"type": "object", "properties": {
                 name: {key: value for key, value in definition.items() if key != "optional"}
                 for name, definition in item["parameters"].items()},
                 "required": [name for name, definition in item["parameters"].items() if not definition.get("optional")]}}
            for item in pynia_tool_definitions()]


def wrap_result(result):
    return wrap_tool_result(result)


class McpBridge:
    def __init__(self, execute):
        self.execute = execute
        self.token = secrets.token_urlsafe(32)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(8)
        self.socket.settimeout(0.3)
        self.port = self.socket.getsockname()[1]
        self.closed = threading.Event()
        self.clients = set()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(32)
        threading.Thread(target=self._accept, name="pynia-mcp", daemon=True).start()

    def _accept(self):
        while not self.closed.is_set():
            try:
                client, _address = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                client.close()
                continue
            with self.lock:
                self.clients.add(client)
            threading.Thread(target=self._client, args=(client,), daemon=True).start()

    def _client(self, client):
        try:
            client.settimeout(10)
            stream = client.makefile("rb")
            handshake = json.loads(stream.readline(MAX_MESSAGE_BYTES + 1))
            if not secrets.compare_digest(str(handshake.get("token", "")), self.token):
                return
            session_id = str(handshake.get("tab_id", ""))
            client.settimeout(None)
            while not self.closed.is_set():
                raw = stream.readline(MAX_MESSAGE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_MESSAGE_BYTES:
                    break
                request = json.loads(raw)
                response = self.handle(request, session_id)
                if response is not None:
                    client.sendall((json.dumps(response, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        finally:
            with self.lock:
                self.clients.discard(client)
            client.close()
            self.slots.release()

    def handle(self, request, session_id):
        method, request_id = request.get("method"), request.get("id")
        if request_id is None:
            return None
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "datapyn-mcp", "version": "2.0.0"},
                      "instructions": "You are inside DataPyn desktop. Use datapyn_* tools for this tab; no HTTP API exists."}
        elif method == "tools/list":
            result = {"tools": tool_definitions()}
        elif method == "tools/call":
            params = request.get("params") or {}
            name = normalize_mcp_tool_name(str(params.get("name", "")).split("__")[-1])
            try:
                if name not in {item["name"] for item in tool_definitions()}:
                    raise ValueError("Unknown DataPyn tool")
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                result = wrap_result(self.execute(session_id, name, arguments))
            except Exception as exc:
                result = wrap_result({"error": str(exc)})
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def close(self):
        self.closed.set()
        self.socket.close()
        with self.lock:
            for client in list(self.clients):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()
