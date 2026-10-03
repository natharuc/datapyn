"""Responsive session supervisor: user code only runs in spawned kernels."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import multiprocessing
import platform
import threading
import time
import uuid

from . import PROTOCOL_VERSION
from .kernel import kernel_main
from .process_group import own_process_group
from .workspace import read_document, write_document

MAX_SESSIONS = 16
MAX_QUEUED_JOBS = 64
MAX_CODE_BYTES = 1024 * 1024


class RuntimeErrorResponse(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Job:
    method: str
    params: dict
    request_id: int | None = None
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = 0.0


class SessionRuntime:
    def __init__(self, session_id: str, emit):
        self.session_id = session_id
        self.emit = emit
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._failed = False
        self._ready = False
        self._queue: deque[Job] = deque()
        self._active: Job | None = None
        self._pending_reset = None
        self._states: OrderedDict[str, str] = OrderedDict()
        self._context = multiprocessing.get_context("spawn")
        self._process = None
        self._group = None
        self._commands = None
        self._events = None
        self._restart_times = deque(maxlen=4)
        self._thread = threading.Thread(target=self._loop, name=f"session-{session_id}", daemon=True)
        self._thread.start()

    def enqueue(self, method: str, params: dict, request_id: int | None = None):
        with self._lock:
            if self._closed or self._failed:
                raise RuntimeErrorResponse("session_unavailable", "This session is unavailable; create a new session")
            if len(self._queue) >= MAX_QUEUED_JOBS:
                raise RuntimeErrorResponse("queue_full", "This session already has 64 queued operations")
            if method == "execution.run":
                execution_id = params["execution_id"]
                if execution_id in self._states:
                    raise RuntimeErrorResponse("duplicate_execution", "execution_id must be unique within the session")
                self._states[execution_id] = "queued"
                self._trim_states()
            self._queue.append(Job(method, dict(params), request_id))
        self._wake.set()

    def _trim_states(self):
        if len(self._states) > 2048:
            for key, state in list(self._states.items()):
                if state in {"succeeded", "failed", "cancelled"}:
                    del self._states[key]
                    if len(self._states) <= 1024:
                        break

    def cancel(self, execution_id: str):
        queued = None
        with self._lock:
            if self._pending_reset is not None:
                return {"execution_id": execution_id, "status": "cancelling"}
            if self._active and self._active.method == "execution.run" and self._active.params["execution_id"] == execution_id:
                stale = list(self._queue)
                self._queue.clear()
                self._pending_reset = ("cancelled", self._active, stale)
                self._states[execution_id] = "cancelling"
                self._wake.set()
                return {"execution_id": execution_id, "status": "cancelling"}
            for job in self._queue:
                if job.method == "execution.run" and job.params["execution_id"] == execution_id:
                    queued = job
                    self._queue.remove(job)
                    break
            if queued is None:
                if execution_id in self._states:
                    return {"execution_id": execution_id, "status": "already_finished"}
                raise RuntimeErrorResponse("unknown_execution", "execution_id was not found in this session")
        self._finish_interrupted(queued, "cancelled", "Execution cancelled before starting")
        return {"execution_id": execution_id, "status": "cancelled"}

    def _launch(self):
        commands_recv, commands_send = self._context.Pipe(duplex=False)
        events_recv, events_send = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=kernel_main,
            args=(self.session_id, commands_recv, events_send),
            name=f"datapyn-kernel-{self.session_id}",
        )
        try:
            process.start()
            group = own_process_group(process.pid)
        except BaseException:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if not process.is_alive():
                    process.close()
            commands_send.close()
            events_recv.close()
            raise
        finally:
            commands_recv.close()
            events_send.close()
        self._process, self._commands, self._events, self._group = process, commands_send, events_recv, group
        self._ready = False

    def _stop_process(self):
        process = self._process
        if self._group is not None:
            self._group.close()
            self._group = None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if not process.is_alive():
                process.close()
        for connection in (self._commands, self._events):
            if connection is not None:
                connection.close()
        self._process = self._commands = self._events = None

    def _finish_interrupted(self, job: Job, status: str, message: str):
        if job.method == "execution.run":
            execution_id = job.params["execution_id"]
            with self._lock:
                self._states[execution_id] = status
            self.emit({"event": "execution.finished", "payload": {
                "session_id": self.session_id,
                "execution_id": execution_id,
                "status": status,
                "duration_ms": round((time.monotonic() - job.started_at) * 1000, 3) if job.started_at else 0,
                "error": message,
                "results": [],
                "variables": [],
            }})
        elif job.request_id is not None:
            self.emit({"id": job.request_id, "error": {"code": "kernel_reset", "message": message}})

    def _reset_kernel(self, reason: str, active: Job | None, stale: list[Job]):
        self._stop_process()
        if active is not None:
            self._finish_interrupted(active, "cancelled" if reason == "cancelled" else "failed",
                "Session kernel restarted; its in-memory namespace was lost" if reason == "cancelled" else "Session worker exited unexpectedly; its in-memory namespace was lost")
        for job in stale:
            self._finish_interrupted(job, "cancelled", "Queued operation invalidated by session restart")
        self.emit({"event": "session.reset", "payload": {
            "session_id": self.session_id,
            "reason": reason,
            "namespace_lost": True,
            "connection_lost": True,
        }})
        with self._lock:
            if self._closed:
                return
        self._launch()

    def _receive(self, message: dict):
        with self._lock:
            # A cancellation command takes precedence over an unconsumed result.
            if self._pending_reset is not None:
                return
            if message.get("ready"):
                self._ready = True
                self.emit({"event": "session.ready", "payload": {"session_id": self.session_id}})
                return
            event = message.get("event")
            if event:
                payload = message["payload"]
                if event == "execution.finished":
                    if not self._active or message.get("job_id") != self._active.job_id:
                        return
                    self._states[payload["execution_id"]] = payload["status"]
                    self._active = None
                elif not self._active or self._active.method != "execution.run":
                    return
                self.emit({"event": event, "payload": payload})
                return
            job = self._active
            if job is None or message.get("job_id") != job.job_id:
                return
            self._active = None
            if job.request_id is not None:
                self.emit({"id": job.request_id, **({"result": message["result"]} if "result" in message else {"error": message["error"]})})

    def _loop(self):
        try:
            self._launch()
            while True:
                with self._lock:
                    if self._closed:
                        break
                    reset = self._pending_reset
                    if reset is not None:
                        self._pending_reset = None
                        self._active = None
                if reset is not None:
                    self._reset_kernel(*reset)
                    continue
                if self._events.poll(0.03):
                    try:
                        self._receive(self._events.recv())
                    except (EOFError, OSError):
                        pass
                if not self._process.is_alive():
                    now = time.monotonic()
                    self._restart_times.append(now)
                    with self._lock:
                        active, stale = self._active, list(self._queue)
                        self._active = None
                        self._queue.clear()
                    if len(self._restart_times) >= 3 and now - self._restart_times[-3] < 10:
                        raise RuntimeError("Session worker repeatedly failed to start")
                    self._reset_kernel("worker_crashed", active, stale)
                    continue
                with self._lock:
                    if self._ready and self._active is None and self._queue and self._pending_reset is None:
                        job = self._queue.popleft()
                        job.started_at = time.monotonic()
                        self._active = job
                        if job.method == "execution.run":
                            self._states[job.params["execution_id"]] = "running"
                    else:
                        job = None
                if job is not None:
                    self._commands.send({"job_id": job.job_id, "method": job.method, "params": job.params})
                self._wake.wait(0.01)
                self._wake.clear()
        except BaseException as exc:
            with self._lock:
                self._failed = True
            self.emit({"event": "session.error", "payload": {"session_id": self.session_id, "error": str(exc)}})
        finally:
            with self._lock:
                active, queued = self._active, list(self._queue)
                self._active = None
                self._queue.clear()
            for job in ([active] if active else []) + queued:
                self._finish_interrupted(job, "cancelled", "Session closed or unavailable")
            self._stop_process()

    def close(self):
        with self._lock:
            self._closed = True
        self._wake.set()
        self._thread.join(timeout=5)


class Supervisor:
    """Dispatch protocol requests; execution never blocks this request thread."""

    def __init__(self, emit):
        self.emit = emit
        self.sessions: dict[str, SessionRuntime] = {}
        self.closing = False

    def _session(self, params):
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            raise RuntimeErrorResponse("unknown_session", "session_id was not found")
        return self.sessions[session_id]

    @staticmethod
    def _identifier(value, name):
        if not isinstance(value, str) or not value or len(value) > 128:
            raise RuntimeErrorResponse("invalid_params", f"{name} must be a nonempty string of at most 128 characters")
        return value

    def receive(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or isinstance(request_id, bool) or not isinstance(request_id, int):
                raise RuntimeErrorResponse("invalid_request", "Requests must be objects with an integer id")
            method = request.get("method")
            params = request.get("params", {})
            if not isinstance(method, str) or not isinstance(params, dict):
                raise RuntimeErrorResponse("invalid_request", "method must be a string and params an object")
            result = self.dispatch(method, params, request_id)
            if result is not None:
                self.emit({"id": request_id, "result": result})
        except RuntimeErrorResponse as exc:
            self.emit({"id": request_id, "error": {"code": exc.code, "message": str(exc)}})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.emit({"id": request_id, "error": {"code": "invalid_params", "message": str(exc)}})
        except Exception as exc:
            self.emit({"id": request_id, "error": {"code": "internal_error", "message": str(exc)}})

    def dispatch(self, method: str, params: dict, request_id: int):
        if method == "system.info":
            return {
                "protocol_version": PROTOCOL_VERSION,
                "python_version": platform.python_version(),
                "capabilities": {
                    "languages": ["sql", "python"],
                    "libraries": ["pandas", "numpy", "polars"],
                    "databases": ["sqlite", "sqlserver", "postgresql", "mysql", "mariadb", "databricks"],
                    "isolation": "process_per_session",
                    "cancel": "restart_session",
                    "pagination": True,
                    "max_page_rows": 1000,
                    "max_output_bytes": 256 * 1024,
                    "qt_required": False,
                },
            }
        if method == "system.shutdown":
            self.closing = True
            return {"status": "closing"}
        if method == "session.create":
            if len(self.sessions) >= MAX_SESSIONS:
                raise RuntimeErrorResponse("session_limit", "The preview supports at most 16 simultaneous sessions")
            session_id = self._identifier(params.get("session_id") or uuid.uuid4().hex, "session_id")
            if session_id in self.sessions:
                raise RuntimeErrorResponse("duplicate_session", "session_id already exists")
            self.sessions[session_id] = SessionRuntime(session_id, self.emit)
            return {"session_id": session_id, "status": "created"}
        if method == "session.close":
            session = self._session(params)
            del self.sessions[session.session_id]
            session.close()
            return {"session_id": session.session_id, "status": "closed"}
        if method == "execution.run":
            session = self._session(params)
            execution_id = self._identifier(params.get("execution_id"), "execution_id")
            if params.get("language") not in {"sql", "python"}:
                raise RuntimeErrorResponse("invalid_params", "language must be sql or python")
            code = params.get("code")
            if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
                raise RuntimeErrorResponse("invalid_params", "code must be a string of at most 1 MiB")
            variable_name = params.get("variable_name")
            if variable_name is not None and (not isinstance(variable_name, str) or not variable_name.isidentifier() or variable_name.startswith("__")):
                raise RuntimeErrorResponse("invalid_params", "variable_name must be a valid Python identifier")
            session.enqueue(method, params)
            return {"execution_id": execution_id, "status": "queued"}
        if method == "execution.cancel":
            return self._session(params).cancel(self._identifier(params.get("execution_id"), "execution_id"))
        if method in {"connection.connect", "schema.get", "result.page"}:
            if method == "connection.connect" and not isinstance(params.get("config"), dict):
                raise RuntimeErrorResponse("invalid_params", "config must be an object")
            if method == "result.page":
                self._identifier(params.get("result_id"), "result_id")
            self._session(params).enqueue(method, params, request_id)
            return None
        if method in {"workspace.read", "workspace.write"}:
            path = params.get("path")
            if not isinstance(path, str) or not path:
                raise RuntimeErrorResponse("invalid_params", "path must be a nonempty string")
            return read_document(path) if method == "workspace.read" else write_document(path, params.get("document"))
        raise RuntimeErrorResponse("method_not_found", f"Unknown method: {method}")

    def close(self):
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()
