"""ACP JSON-RPC client over stdio (NDJSON)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .catalog import hidden_popen_kwargs, popen_argv

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1


class AcpClient(QObject):
    """Speaks Agent Client Protocol v1 with one agent subprocess.

    I/O runs on a daemon thread; signals are emitted for the Qt main thread.
    """

    session_update = pyqtSignal(str, dict)  # sessionId, update
    permission_request = pyqtSignal(object, dict)  # rpc_id, params
    rpc_error = pyqtSignal(str)
    stderr_line = pyqtSignal(str)
    process_exited = pyqtSignal(int)
    initialized = pyqtSignal(dict)

    def __init__(self, agent_id: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._alive = False
        self.agent_capabilities: dict[str, Any] = {}
        self.auth_methods: list[dict[str, Any]] = []

    @property
    def is_running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def start(
        self,
        command: str,
        args: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        if self.is_running:
            return
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        kwargs = hidden_popen_kwargs()
        self._proc = subprocess.Popen(
            popen_argv(command, args),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or None,
            env=merged_env,
            bufsize=0,
            **kwargs,
        )
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_stdout, daemon=True, name=f"acp-out-{self.agent_id}"
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, daemon=True, name=f"acp-err-{self.agent_id}"
        )
        self._reader.start()
        self._stderr_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._alive = False
        proc = self._proc
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None
        with self._lock:
            for _rpc_id, (event, slot) in self._pending.items():
                slot["error"] = {"code": -32000, "message": "agent process stopped"}
                event.set()
            self._pending.clear()

    def request(self, method: str, params: Optional[dict] = None, timeout: float = 60.0) -> dict:
        """Synchronous JSON-RPC request. Must not be called on the GUI thread
        for long operations — use the host worker instead."""
        rpc_id, event, slot = self._begin(method, params or {})
        if not event.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(rpc_id, None)
            raise TimeoutError(f"ACP {method} timed out after {timeout}s")
        if "error" in slot:
            err = slot["error"]
            raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
        return slot.get("result") or {}

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def respond(self, rpc_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    def respond_error(self, rpc_id: Any, code: int, message: str) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": code, "message": message},
            }
        )

    def initialize(self, client_name: str = "DataPyn", client_version: str = "0.0.0") -> dict:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": client_name, "version": client_version},
            },
            timeout=30.0,
        )
        self.agent_capabilities = result.get("agentCapabilities") or {}
        self.auth_methods = result.get("authMethods") or []
        self.initialized.emit(result)
        return result

    def authenticate(self, method_id: str) -> dict:
        return self.request("authenticate", {"methodId": method_id}, timeout=120.0)

    def session_new(self, cwd: str, mcp_servers: list[dict] | None = None) -> str:
        result = self.request(
            "session/new",
            {"cwd": cwd, "mcpServers": mcp_servers or []},
            timeout=30.0,
        )
        session_id = result.get("sessionId") or result.get("session_id") or ""
        if not session_id:
            raise RuntimeError("session/new did not return sessionId")
        return str(session_id)

    def session_load(self, session_id: str, cwd: str, mcp_servers: list[dict] | None = None) -> Any:
        return self.request(
            "session/load",
            {"sessionId": session_id, "cwd": cwd, "mcpServers": mcp_servers or []},
            timeout=60.0,
        )

    def session_resume(self, session_id: str, cwd: str, mcp_servers: list[dict] | None = None) -> Any:
        return self.request(
            "session/resume",
            {"sessionId": session_id, "cwd": cwd, "mcpServers": mcp_servers or []},
            timeout=30.0,
        )

    def session_prompt(self, session_id: str, text: str, timeout: float = 300.0) -> dict:
        return self.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            },
            timeout=timeout,
        )

    def session_cancel(self, session_id: str) -> None:
        self.notify("session/cancel", {"sessionId": session_id})

    def session_close(self, session_id: str) -> None:
        caps = self.agent_capabilities.get("sessionCapabilities") or {}
        if "close" not in caps and not self.agent_capabilities.get("closeSession"):
            return
        try:
            self.request("session/close", {"sessionId": session_id}, timeout=10.0)
        except Exception as exc:
            logger.debug("session/close ignored: %s", exc)

    def _begin(self, method: str, params: dict) -> tuple[int, threading.Event, dict]:
        event = threading.Event()
        slot: dict = {}
        with self._lock:
            rpc_id = self._next_id
            self._next_id += 1
            self._pending[rpc_id] = (event, slot)
        self._write({"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params})
        return rpc_id, event, slot

    def _write(self, payload: dict) -> None:
        proc = self._proc
        if not proc or not proc.stdin:
            raise RuntimeError("ACP agent is not running")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            while self._alive and proc.poll() is None:
                raw = proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("ACP non-JSON stdout: %s", line[:200])
                    continue
                self._dispatch(msg)
        except Exception as exc:
            logger.warning("ACP stdout reader failed: %s", exc)
            self.rpc_error.emit(str(exc))
        finally:
            code = proc.poll() if proc else -1
            self.process_exited.emit(int(code if code is not None else -1))

    def _read_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip()
                if text:
                    self.stderr_line.emit(text)
        except Exception:
            pass

    def _dispatch(self, msg: dict) -> None:
        rpc_id = msg.get("id")
        method = msg.get("method")
        if method == "session/update":
            params = msg.get("params") or {}
            self.session_update.emit(str(params.get("sessionId") or ""), params.get("update") or {})
            return
        if method == "session/request_permission":
            self.permission_request.emit(rpc_id, msg.get("params") or {})
            return
        if rpc_id is not None and method:
            # Other agent→client requests: reject so the agent can continue.
            self.respond_error(rpc_id, -32601, f"Method not implemented: {method}")
            return
        if rpc_id is not None:
            with self._lock:
                pending = self._pending.pop(int(rpc_id), None)
            if not pending:
                return
            event, slot = pending
            if "error" in msg:
                slot["error"] = msg["error"]
            else:
                slot["result"] = msg.get("result")
            event.set()
