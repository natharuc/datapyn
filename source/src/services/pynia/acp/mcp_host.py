"""In-process MCP TCP host that ACP agents reach through mcp_stdio."""

from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from src.services.pynia.tools.definitions import pynia_tool_definitions

logger = logging.getLogger(__name__)

MCP_INSTRUCTIONS = (
    "You are inside DataPyn, a desktop SQL/Python IDE. This MCP server runs "
    "in-process in the same DataPyn window — there is no HTTP API and nothing "
    "to curl on localhost. Call datapyn_* tools to inspect results, run SQL, "
    "edit blocks, and create charts: "
    + ", ".join(spec["name"] for spec in pynia_tool_definitions())
    + ". A tool error is not a dead server unless the message says Transport closed."
)


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


class PyniaMcpHost(QObject):
    """Accepts localhost TCP connections from mcp_stdio proxies."""

    tool_executed = pyqtSignal(str, str, dict)  # tab_id, tool_name, result
    _run_tool = pyqtSignal(str, dict, str, object, object)

    def __init__(self, registry, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._registry = registry
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._alive = False
        self.port = 0
        self.token = ""
        self.last_prompt_tab: dict[str, str] = {}
        self.current_tab: str = ""
        self._run_tool.connect(self._on_run_tool, Qt.ConnectionType.QueuedConnection)

    def start(self) -> None:
        if self._alive:
            return
        self.token = secrets.token_hex(16)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(1.0)
        self.port = int(self._sock.getsockname()[1])
        self._alive = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="pynia-mcp-host")
        self._thread.start()
        logger.info("Pynia MCP host on 127.0.0.1:%s", self.port)

    def stop(self) -> None:
        self._alive = False
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def mcp_server_config(self, tab_id: str, *, include_type: bool = False) -> dict[str, Any]:
        """ACP session/new payload (no type). Copilot JSON sets include_type=True."""
        import sys
        from pathlib import Path

        source_root = str(Path(__file__).resolve().parents[4])
        cfg: dict[str, Any] = {
            "name": "datapyn",
            "command": sys.executable,
            "args": ["-m", "src.services.pynia.acp.mcp_stdio"],
            "env": [
                {"name": "PYTHONPATH", "value": source_root},
                {"name": "DATAPYN_MCP_HOST", "value": "127.0.0.1"},
                {"name": "DATAPYN_MCP_PORT", "value": str(self.port)},
                {"name": "DATAPYN_MCP_TOKEN", "value": self.token},
                {"name": "DATAPYN_TAB_ID", "value": tab_id or ""},
            ],
        }
        if include_type:
            cfg["type"] = "stdio"
        return cfg

    def write_copilot_mcp_json(self, workspace: str, tab_id: str = "") -> str:
        """Copilot --acp ignores session/new mcpServers; load tools via CLI flag."""
        from pathlib import Path

        cfg = self.mcp_server_config(tab_id or self.current_tab or "", include_type=True)
        env = {item["name"]: item["value"] for item in cfg["env"]}
        payload = {
            "mcpServers": {
                "datapyn": {
                    "type": "stdio",
                    "command": cfg["command"],
                    "args": cfg["args"],
                    "tools": ["*"],
                    "env": env,
                }
            }
        }
        root = Path(workspace) / ".datapyn"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.debug("Could not create .datapyn dir: %s", exc)
            root = Path(workspace)
        path = root / "copilot-mcp.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        copilot_dir = Path(workspace) / ".copilot"
        try:
            copilot_dir.mkdir(parents=True, exist_ok=True)
            (copilot_dir / "mcp-config.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Could not write .copilot/mcp-config.json: %s", exc)
        return str(path)

    def write_cursor_mcp_json(self, workspace: str, tab_id: str) -> None:
        from pathlib import Path

        root = Path(workspace)
        cursor_dir = root / ".cursor"
        try:
            cursor_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.debug("Could not create .cursor dir: %s", exc)
            return
        cfg = self.mcp_server_config(tab_id)
        env = {item["name"]: item["value"] for item in cfg["env"]}
        payload = {
            "mcpServers": {
                "datapyn": {
                    "command": cfg["command"],
                    "args": cfg["args"],
                    "env": env,
                }
            }
        }
        path = cursor_dir / "mcp.json"
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Could not write Cursor MCP config: %s", exc)

    def _accept_loop(self) -> None:
        while self._alive and self._sock:
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        conn.settimeout(30.0)
        buf = b""
        tab_id = ""
        write_lock = threading.Lock()
        inflight = threading.Event()
        inflight.set()
        pending = {"n": 0}
        pending_lock = threading.Lock()

        def _tool_done() -> None:
            with pending_lock:
                pending["n"] = max(0, pending["n"] - 1)
                if pending["n"] == 0:
                    inflight.set()

        try:
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            line, buf = buf.split(b"\n", 1)
            hello = json.loads(line.decode("utf-8"))
            if hello.get("token") != self.token:
                conn.close()
                return
            tab_id = str(hello.get("tab_id") or "")
            conn.settimeout(None)
            while self._alive:
                while b"\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except json.JSONDecodeError:
                    continue
                method = str(request.get("method") or "")
                if method == "tools/call":
                    with pending_lock:
                        pending["n"] += 1
                        inflight.clear()
                    threading.Thread(
                        target=self._dispatch_tool,
                        args=(conn, write_lock, request, tab_id, _tool_done),
                        daemon=True,
                        name="pynia-mcp-tool",
                    ).start()
                    continue
                response = self._handle_mcp(request, tab_id)
                if response is not None:
                    _send_mcp(conn, write_lock, response)
        except Exception as exc:
            logger.info("MCP connection ended: %s", exc)
        finally:
            inflight.wait(timeout=120.0)
            try:
                conn.close()
            except Exception:
                pass

    def _dispatch_tool(
        self,
        conn: socket.socket,
        write_lock: threading.Lock,
        request: dict,
        tab_id: str,
        done=None,
    ) -> None:
        try:
            response = self._handle_mcp(request, tab_id)
            if response is not None and not _send_mcp(conn, write_lock, response):
                logger.warning("MCP tools/call reply dropped (socket closed)")
        except Exception as exc:
            logger.warning("MCP tools/call failed: %s", exc)
            req_id = request.get("id")
            if req_id is not None:
                _send_mcp(
                    conn,
                    write_lock,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": str(exc)},
                    },
                )
        finally:
            if done is not None:
                try:
                    done()
                except Exception:
                    pass

    def _handle_mcp(self, request: dict, tab_id: str) -> Optional[dict]:
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "notifications/initialized" or req_id is None and method.startswith("notifications/"):
            return None
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "datapyn-mcp", "version": "1.0.0"},
                "instructions": MCP_INSTRUCTIONS,
            }
        elif method == "tools/list":
            result = {"tools": self._registry.list_tools()}
        elif method == "tools/call":
            name = normalize_mcp_tool_name(params.get("name", ""))
            arguments = params.get("arguments") or {}
            effective_tab = (
                tab_id
                or self.current_tab
                or next(iter(self.last_prompt_tab.values()), "")
            )
            result = self._execute_tool(name, arguments, effective_tab)
        elif method == "ping":
            result = {}
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _execute_tool(self, name: str, arguments: dict, tab_id: str) -> dict:
        box: dict = {}
        event = threading.Event()
        self._run_tool.emit(name, arguments, tab_id, box, event)
        if not event.wait(timeout=120):
            return _mcp_error("Tool timed out")
        raw = box.get("result") or {"error": "no result"}
        self.tool_executed.emit(tab_id, name, raw if isinstance(raw, dict) else {"result": raw})
        return wrap_tool_result(raw)

    def _on_run_tool(self, name: str, arguments: dict, tab_id: str, box: dict, event: threading.Event) -> None:
        try:
            if tab_id and hasattr(self._registry, "pin_session"):
                self._registry.pin_session(tab_id)
            box["result"] = self._registry.execute(name, arguments or {})
        except Exception as exc:
            box["result"] = {"error": str(exc)}
        finally:
            event.set()


def _send_mcp(conn: socket.socket, write_lock: threading.Lock, payload: dict) -> bool:
    """Write one NDJSON MCP message. Dead sockets are dropped, never raised."""
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        with write_lock:
            conn.sendall(line.encode("utf-8"))
        return True
    except (OSError, ConnectionError) as exc:
        logger.debug("MCP write dropped: %s", exc)
        return False


def _mcp_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}
