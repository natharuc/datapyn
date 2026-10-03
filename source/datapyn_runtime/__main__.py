"""NDJSON entry point: python -m datapyn_runtime (PYTHONPATH=source)."""

from __future__ import annotations

import json
import multiprocessing
import queue
import sys
import threading

from .supervisor import Supervisor
from .stdio import detach_child_stdin

MAX_REQUEST_BYTES = 24 * 1024 * 1024


class ProtocolWriter:
    """Keep the request/control thread independent of stdout transport writes."""

    def __init__(self, stream):
        self.stream = stream
        self._queue = queue.Queue(maxsize=2048)
        self._broken = threading.Event()
        self._thread = threading.Thread(target=self._run, name="protocol-writer", daemon=True)
        self._thread.start()

    def emit(self, message):
        if self._broken.is_set():
            return
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            # Output events are expendable under transport backpressure;
            # terminal events/responses must never silently disappear.
            if message.get("event") == "execution.output":
                return
            try:
                self._queue.put(message, timeout=1)
            except queue.Full:
                self._broken.set()

    def _run(self):
        while True:
            message = self._queue.get()
            try:
                if message is None:
                    return
                self.stream.write(json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                self.stream.flush()
            except (BrokenPipeError, OSError, ValueError):
                self._broken.set()
                return
            finally:
                self._queue.task_done()

    def close(self):
        try:
            self._queue.put(None, timeout=1)
        except queue.Full:
            return
        self._thread.join(timeout=2)


def main():
    multiprocessing.freeze_support()
    if "--mcp-stdio" in sys.argv[1:]:
        from .mcp_stdio import main as mcp_main
        return mcp_main()
    child_stdin = detach_child_stdin()
    # Windows stdio defaults must not corrupt Unicode protocol data.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    writer = ProtocolWriter(sys.stdout)
    supervisor = Supervisor(writer.emit)
    try:
        while not supervisor.closing and not writer._broken.is_set():
            raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_REQUEST_BYTES:
                while raw and not raw.endswith(b"\n"):
                    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
                writer.emit({"id": None, "error": {"code": "request_too_large", "message": "Request exceeds 24 MiB"}})
                continue
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                writer.emit({"id": None, "error": {"code": "parse_error", "message": "Invalid UTF-8 JSON request"}})
                continue
            supervisor.receive(request)
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.close()
        writer.close()
        if child_stdin is not None:
            child_stdin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
