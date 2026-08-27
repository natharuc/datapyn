"""Stdio MCP proxy — ACP agents spawn this; it tunnels to the DataPyn MCP host."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time


def _connect(host: str, port: int, token: str, tab_id: str) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=10)
    sock.sendall((json.dumps({"token": token, "tab_id": tab_id}) + "\n").encode("utf-8"))
    return sock


def _log(message: str) -> None:
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _main() -> int:
    host = os.environ.get("DATAPYN_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("DATAPYN_MCP_PORT", "0") or "0")
    token = os.environ.get("DATAPYN_MCP_TOKEN", "")
    tab_id = os.environ.get("DATAPYN_TAB_ID", "")
    if not port or not token:
        _log("DATAPYN_MCP_PORT and DATAPYN_MCP_TOKEN are required")
        return 2

    lock = threading.Lock()
    state: dict = {"sock": None, "alive": True}

    def attach() -> socket.socket | None:
        backoff = 0.2
        while state["alive"]:
            try:
                sock = _connect(host, port, token, tab_id)
                with lock:
                    old = state["sock"]
                    state["sock"] = sock
                if old is not None and old is not sock:
                    try:
                        old.close()
                    except Exception:
                        pass
                _log("datapyn mcp_stdio connected")
                return sock
            except Exception as exc:
                _log(f"datapyn mcp_stdio reconnect: {exc}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 2.0)
        return None

    def pump() -> None:
        buf = b""
        while state["alive"]:
            with lock:
                sock = state["sock"]
            if sock is None:
                time.sleep(0.05)
                continue
            try:
                chunk = sock.recv(65536)
                if not chunk:
                    raise ConnectionError("eof")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    sys.stdout.buffer.write(line + b"\n")
                    sys.stdout.buffer.flush()
            except Exception as exc:
                if not state["alive"]:
                    return
                _log(f"datapyn mcp_stdio socket dropped: {exc}")
                buf = b""
                attach()

    try:
        state["sock"] = _connect(host, port, token, tab_id)
    except Exception as exc:
        _log(f"datapyn mcp_stdio connect failed: {exc}")
        return 2

    threading.Thread(target=pump, daemon=True, name="datapyn-mcp-pump").start()
    try:
        for line in sys.stdin.buffer:
            if not state["alive"]:
                break
            payload = line if line.endswith(b"\n") else line + b"\n"
            with lock:
                sock = state["sock"]
            if sock is None:
                sock = attach()
            if sock is None:
                continue
            try:
                sock.sendall(payload)
            except Exception:
                sock = attach()
                if sock is not None:
                    try:
                        sock.sendall(payload)
                    except Exception:
                        pass
    except Exception:
        pass
    state["alive"] = False
    with lock:
        sock = state["sock"]
        state["sock"] = None
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
