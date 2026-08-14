"""Stdio MCP proxy — ACP agents spawn this; it tunnels to the DataPyn MCP host."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading


def _main() -> int:
    host = os.environ.get("DATAPYN_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("DATAPYN_MCP_PORT", "0") or "0")
    token = os.environ.get("DATAPYN_MCP_TOKEN", "")
    tab_id = os.environ.get("DATAPYN_TAB_ID", "")
    if not port or not token:
        sys.stderr.write("DATAPYN_MCP_PORT and DATAPYN_MCP_TOKEN are required\n")
        return 2
    sock = socket.create_connection((host, port), timeout=10)
    sock.sendall((json.dumps({"token": token, "tab_id": tab_id}) + "\n").encode("utf-8"))

    def pump_socket() -> None:
        buf = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    sys.stdout.buffer.write(line + b"\n")
                    sys.stdout.buffer.flush()
        except Exception:
            pass
        finally:
            try:
                sys.stdin.close()
            except Exception:
                pass

    threading.Thread(target=pump_socket, daemon=True).start()
    try:
        for line in sys.stdin.buffer:
            sock.sendall(line if line.endswith(b"\n") else line + b"\n")
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
