"""Responsive session supervisor: user code only runs in spawned kernels."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import multiprocessing
import platform
import queue
import threading
import time
import uuid

from . import PROTOCOL_VERSION
from .kernel import kernel_main
from .process_group import own_process_group
from .workspace import read_document, write_document
from .background import BackgroundJobs
from .connection_catalog import ConnectionCatalog
from .desktop_services import DesktopServices
from .pynia import PyniaService
from . import profiles

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
    def __init__(self, session_id: str, emit, idle_timeout=300, deliver_notification=None):
        self.session_id = session_id
        self.emit = emit
        self.idle_timeout = idle_timeout
        self.deliver_notification = deliver_notification
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
        self._event_reader = None
        self._reader_error = None
        self._incoming = queue.Queue(maxsize=64)
        self._restart_times = deque(maxlen=4)
        self.language_contexts = OrderedDict()
        self.language_variables = {}
        self._context_requests = set()
        self._context_codes = {}
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
            args=(self.session_id, commands_recv, events_send, self.idle_timeout),
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
        self._reader_error = None
        self._incoming = queue.Queue(maxsize=64)
        self._event_reader = threading.Thread(target=self._read_events, args=(events_recv, self._incoming),
                                              name=f"session-events-{self.session_id}", daemon=True)
        self._event_reader.start()

    def _read_events(self, connection, incoming):
        try:
            while True:
                message = connection.recv()
                while not self._closed and connection is self._events:
                    try:
                        incoming.put(message, timeout=0.1)
                        self._wake.set()
                        break
                    except queue.Full:
                        continue
                else:
                    return
        except (EOFError, OSError):
            pass
        except Exception as exc:
            if connection is self._events:
                self._reader_error = f"Kernel response could not be decoded ({type(exc).__name__})"
        finally:
            self._wake.set()

    def _stop_process(self):
        process = self._process
        connections = (self._commands, self._events)
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
        self._process = self._commands = self._events = None
        reader, self._event_reader = self._event_reader, None
        if reader is not None:
            reader.join(timeout=1)
        for connection in connections:
            if connection is not None:
                connection.close()

    def _finish_interrupted(self, job: Job, status: str, message: str):
        if job.method == "execution.run":
            download = job.params.get("export")
            if download:
                from .stream_export import cleanup
                try:
                    cleanup(download["path"], download["options"]["stage_id"])
                except OSError:
                    pass
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
        with self._lock:
            self.language_contexts.clear()
            self.language_variables.clear()
            self._context_requests.clear()
            self._context_codes.clear()
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
            if "language_context" in message:
                context = message["language_context"]
                key = context.get("key", "default")
                self.language_contexts[key] = {**self.language_contexts.get(key, {}), **context}
                self.language_contexts.move_to_end(key)
                while len(self.language_contexts) > 32:
                    old_key, _old_context = self.language_contexts.popitem(last=False)
                    self._context_codes.pop(old_key, None)
                self.language_variables = context.get("variables", self.language_variables)
                self._context_requests.discard(key)
                self.emit({"event": "language.context_updated", "payload": {
                    "session_id": self.session_id, "connection_id": context.get("connection_id"),
                    "database": context.get("database", ""), "schema": context.get("schema_name", ""),
                }})
                return
            event = message.get("event")
            if event:
                payload = message["payload"]
                if event == "execution.finished":
                    if not self._active or message.get("job_id") != self._active.job_id:
                        return
                    self._states[payload["execution_id"]] = payload["status"]
                    self._active = None
                elif event.startswith("execution.") and (not self._active or self._active.method != "execution.run"):
                    return
                self.emit({"event": event, "payload": payload})
                return
            job = self._active
            if job is None or message.get("job_id") != job.job_id:
                return
            self._active = None
            if job.request_id is not None:
                if "notification_delivery" in message:
                    try:
                        self.deliver_notification(job.request_id, message["notification_delivery"])
                    except Exception as exc:
                        self.emit({"id": job.request_id, "error": {"code": "operation_failed", "message": str(exc)}})
                else:
                    self.emit({"id": job.request_id, **({"result": message["result"]} if "result" in message else {"error": message["error"]})})

    def _loop(self):
        try:
            self._launch()
            while True:
                # Clear before reading state so a concurrent producer's signal
                # remains set until its command or event has been consumed.
                self._wake.clear()
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
                for _ in range(64):
                    try:
                        self._receive(self._incoming.get_nowait())
                    except queue.Empty:
                        break
                if not self._incoming.empty():
                    self._wake.set()
                if self._reader_error:
                    raise RuntimeError(self._reader_error)
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
                self._wake.wait(0.25)
        except BaseException as exc:
            with self._lock:
                self._failed = True
            self.emit({"event": "session.error", "payload": {"session_id": self.session_id, "error": str(exc)}})
        finally:
            with self._lock:
                active, queued = self._active, list(self._queue)
                self._active = None
                self._queue.clear()
            self._stop_process()
            for job in ([active] if active else []) + queued:
                self._finish_interrupted(job, "cancelled", "Session closed or unavailable")

    def close(self):
        with self._lock:
            self._closed = True
        self._wake.set()
        self._thread.join(timeout=5)

    @staticmethod
    def context_key(params):
        return "|".join(str(params.get(key) or "") for key in ("connection_id", "database", "schema")) or "default"

    def editor_context(self, params):
        with self._lock:
            key = self.context_key(params)
            context = dict(self.language_contexts.get(key) or {})
            context["variables"] = dict(self.language_variables)
            code = params.get("code", "")
            previous_code, previous_time = self._context_codes.get(key, (None, 0))
            now = time.monotonic()
            needs_context = not context.get("schema") or (code != previous_code and now - previous_time > 0.4)
            if params.get("language") == "sql" and key not in self._context_requests and needs_context:
                # Metadata work waits safely behind executions. The language
                # request itself immediately uses the latest immutable snapshot.
                self._context_requests.add(key)
                if len(self._queue) < MAX_QUEUED_JOBS:
                    self._queue.append(Job("language.context", dict(params)))
                    self._context_codes[key] = (code, now)
                    self._wake.set()
                else:
                    self._context_requests.discard(key)
            return context


class Supervisor:
    """Dispatch protocol requests; execution never blocks this request thread."""

    def __init__(self, emit):
        self._emit = emit
        self.emit = self._deliver
        self._internal = {}
        self._internal_lock = threading.RLock()
        self._flushes = 0
        self.profile_path = profiles.profile_path()
        import os
        os.environ["DATAPYN_WORKSPACE_PATH"] = str(self.profile_path)
        self.sessions: dict[str, SessionRuntime] = {}
        self.closing = False
        self._catalog = None
        self.idle_timeout = 300
        self.background = BackgroundJobs(self.emit)
        self.desktop_services = DesktopServices(emit)
        self.pynia = PyniaService(self.emit, self.internal_rpc, self.internal_query, lambda: self.catalog, state_path=self.profile_path)

    def deliver_notification(self, request_id, prepared):
        self.background.submit(request_id, "notifications.deliver_prepared", prepared, {})

    def _deliver(self, message):
        request_id = message.get("id")
        event = message.get("event")
        execution_id = message.get("payload", {}).get("execution_id") if event else None
        with self._internal_lock:
            pending = self._internal.get(request_id) if request_id else self._internal.get(execution_id)
            if pending:
                done, box = pending
                if event == "execution.output":
                    box["output"] = (box.get("output", "") + message["payload"].get("text", ""))[-65536:]
                elif event == "execution.finished":
                    box["finished"] = message["payload"]
                    done.set()
                elif not event:
                    box.update(message)
                    done.set()
                return
        self._emit(message)

    def internal_rpc(self, session_id, method, params, *, timeout=120):
        identifier, done, box = "pynia:" + uuid.uuid4().hex, threading.Event(), {}
        routed = self._route({**params, "session_id": session_id})
        with self._internal_lock:
            self._internal[identifier] = (done, box)
        try:
            self._session(routed).enqueue(method, routed, identifier)
            if not done.wait(timeout=timeout):
                raise TimeoutError(f"The DataPyn runtime operation exceeded {timeout} seconds")
            if "error" in box:
                raise RuntimeError(box["error"].get("message", "Runtime operation failed"))
            return box.get("result", {})
        finally:
            with self._internal_lock:
                self._internal.pop(identifier, None)

    def internal_query(self, session_id, params):
        language, code = params.get("language"), params.get("code")
        if language not in {"sql", "python"} or not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError("language must be sql/python and code at most 1 MiB")
        identifier, done, box = "pynia:" + uuid.uuid4().hex, threading.Event(), {}
        routed = self._route({**params, "session_id": session_id, "execution_id": identifier})
        with self._internal_lock:
            self._internal[identifier] = (done, box)
        try:
            self._session(routed).enqueue("execution.run", routed)
            if not done.wait(timeout=120):
                self._session(routed).cancel(identifier)
                raise TimeoutError("The Pynia execution exceeded 120 seconds and was cancelled")
            finished = box["finished"]
            if finished["status"] != "succeeded":
                return {"error": finished.get("error", "Execution failed"), "output": box.get("output", "")}
            results = []
            for result in finished.get("results", [])[:8]:
                page = self.internal_rpc(session_id, "result.page", {"result_id": result["result_id"], "offset": 0, "limit": 100})
                results.append({**result, **page})
            return {"status": "succeeded", "output": box.get("output", ""), "results": results, "variables": finished.get("variables", [])}
        finally:
            with self._internal_lock:
                self._internal.pop(identifier, None)

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = ConnectionCatalog(path=self.profile_path / "connections.json")
        return self._catalog

    def _flush_snapshot(self, session, *, timeout=15):
        from .variable_snapshot import settings_get
        try:
            if not settings_get()["enabled"]:
                return {"session_id": session.session_id, "skipped": "disabled"}
            with session._lock:
                if session._closed or session._failed or not session._ready or session._active or session._queue:
                    return {"session_id": session.session_id, "skipped": "unavailable_or_busy"}
                if session._process is None or not session._process.is_alive():
                    return {"session_id": session.session_id, "skipped": "unavailable"}
            saved = self.internal_rpc(session.session_id, "snapshot.save", {}, timeout=timeout)
            if not saved.get("saved"):
                self.emit({"event": "snapshot.warning", "payload": {"session_id": session.session_id, **saved}})
            return {"session_id": session.session_id, **saved}
        except Exception as exc:
            warning = {"session_id": session.session_id, "saved": False, "error": f"{type(exc).__name__}: {exc}"}
            self.emit({"event": "snapshot.warning", "payload": warning})
            return warning

    def _flush_workspace(self, request_id, sessions):
        from concurrent.futures import ThreadPoolExecutor, wait
        response = {"id": request_id, "result": {"sessions": [], "flushed": 0}}
        executor, futures = None, []
        accounted = threading.Event()

        def finish(_future=None):
            with self._internal_lock:
                if not accounted.is_set() and all(future.done() for future in futures):
                    accounted.set()
                    self._flushes -= 1

        try:
            if sessions:
                # Each snapshot still executes serially inside its owning kernel.
                # Independent kernels flush concurrently with one aggregate deadline.
                executor = ThreadPoolExecutor(max_workers=len(sessions), thread_name_prefix="workspace-flush")
                futures = [executor.submit(self._flush_snapshot, session, timeout=14) for session in sessions]
                complete, _pending = wait(futures, timeout=15)
                results = [future.result() for future in futures if future in complete]
                results.extend({"session_id": session.session_id, "saved": False, "error": "Snapshot flush deadline exceeded"}
                               for session, future in zip(sessions, futures) if future not in complete)
                response["result"] = {"sessions": results,
                                      "flushed": sum(bool(result.get("saved")) for result in results)}
        except Exception as exc:
            response = {"id": request_id, "error": {"code": "operation_failed", "message": str(exc)}}
        finally:
            # Do not wait beyond the aggregate response deadline for slow local
            # I/O. Keep activity/profile guards until any unfinished jobs end.
            for future in futures:
                future.add_done_callback(finish)
            finish()
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            self.emit(response)

    def _route(self, params):
        routed = dict(params)
        identifier = routed.get("connection_id")
        if not identifier and routed.get("connection_name"):
            identifier = self.catalog.resolve_ref(routed.get("connection_group"), routed["connection_name"])
            routed["connection_id"] = identifier
        if identifier:
            self._identifier(identifier, "connection_id")
            routed["_connection_config"] = self.catalog.config(identifier)
        return routed

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
                    "connection_catalog": True,
                    "lazy_explorer": True,
                    "editor_intelligence": True,
                },
            }
        if method == "system.shutdown":
            self.closing = True
            return {"status": "closing"}
        if method == "system.flush_workspace":
            with self._internal_lock:
                if self._flushes:
                    raise RuntimeErrorResponse("workspace_busy", "The workspace is already being saved")
                self._flushes += 1
            threading.Thread(target=self._flush_workspace, args=(request_id, list(self.sessions.values())),
                             name="flush-workspace", daemon=True).start()
            return None
        if method == "system.activity":
            executions = 0
            for session in list(self.sessions.values()):
                with session._lock:
                    executions += len(session._queue) + int(session._active is not None)
            with self.pynia.lock:
                pynia = len(self.pynia.installations) + sum(
                    int(conversation.state.busy or conversation.state.config_loading or conversation.inline_lock.locked())
                    for conversation in list(self.pynia.conversations.values())
                )
            with self.background.lock:
                background = self.background.active_count
            with self._internal_lock:
                background += self._flushes
            packages = int(self.desktop_services.busy)
            return {"busy": bool(executions or packages or pynia or background),
                    "executions": executions, "packages": packages, "pynia": pynia, "background": background}
        if method.startswith("connections.") or method.startswith("groups."):
            return self.catalog.dispatch(method, params)
        if method.startswith("workspace.profiles."):
            if method == "workspace.profiles.select":
                if self._flushes or self.background.active_count or self.desktop_services.busy or self.pynia.installations or any(conversation.state.busy or conversation.state.config_loading or conversation.inline_lock.locked() for conversation in self.pynia.conversations.values()):
                    raise RuntimeErrorResponse("workspace_busy", "Wait for background operations and Pynia before switching workspaces")
                for session in self.sessions.values():
                    with session._lock:
                        if session._active or session._queue:
                            raise RuntimeErrorResponse("workspace_busy", "Finish or cancel queued executions before switching workspaces")
                # Validate the target before disposing the current workspace.
                profiles.profile_path(params.get("profile_id"))
                result = profiles.dispatch(method, params)
                self.pynia.close()
                for session in list(self.sessions.values()):
                    self._flush_snapshot(session)
                for session in list(self.sessions.values()):
                    session.close()
                self.sessions.clear()
                if self.background.completion_worker is not None:
                    self.background.completion_worker.reset()
                self.profile_path = profiles.profile_path()
                import os
                os.environ["DATAPYN_WORKSPACE_PATH"] = str(self.profile_path)
                self._catalog = None
                self.pynia = PyniaService(self.emit, self.internal_rpc, self.internal_query, lambda: self.catalog, state_path=self.profile_path)
                return result
            return profiles.dispatch(method, params)
        if method.startswith("packages."):
            self.desktop_services.submit(request_id, method, params)
            return None
        if method.startswith("pynia."):
            if params.get("session_id"):
                self._session(params)
            if method == "pynia.inline":
                def inline():
                    try:
                        self.emit({"id": request_id, "result": self.pynia.dispatch(method, params)})
                    except Exception as exc:
                        self.emit({"id": request_id, "error": {"code": "operation_failed", "message": str(exc)}})
                threading.Thread(target=inline, name="pynia-inline", daemon=True).start()
                return None
            return self.pynia.dispatch(method, params)
        if method in {"notifications.settings.get", "notifications.settings.set", "notifications.test", "snapshot.settings.get", "snapshot.settings.set", "snapshot.list", "snapshot.delete"}:
            self.background.submit(request_id, method, params, {})
            return None
        if method in {"notifications.evaluate", "notifications.send", "snapshot.save", "snapshot.restore"}:
            self._session(params).enqueue(method, params, request_id)
            return None
        if method in {"diagnostics.info", "diagnostics.save"}:
            self.background.submit(request_id, method, params, {})
            return None
        if method == "connection.test":
            if params.get("test_id") is not None:
                self._identifier(params["test_id"], "test_id")
            self.background.submit(request_id, method, self._route(params), {})
            return None
        if method == "connection.test_cancel":
            return self.background.cancel_test(self._identifier(params.get("test_id"), "test_id"))
        if method == "connection.idle_timeout":
            seconds = params.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 86400:
                raise RuntimeErrorResponse("invalid_params", "seconds must be between zero (disabled) and 86400")
            self.idle_timeout = seconds
            for session in self.sessions.values():
                session.idle_timeout = seconds
                session.enqueue(method, {"seconds": seconds})
            return {"seconds": seconds}
        if method in {"language.complete", "language.diagnostics", "language.format", "parameters.scan"}:
            routed = self._route(params)
            context = self._session(params).editor_context(routed) if params.get("session_id") else {}
            self.background.submit(request_id, method, routed, context)
            return None
        if method == "session.create":
            session_id = self._identifier(params.get("session_id") or uuid.uuid4().hex, "session_id")
            if session_id in self.sessions:
                session = self.sessions[session_id]
                with session._lock:
                    if session._closed or session._failed:
                        raise RuntimeErrorResponse("session_unavailable", "Close this failed session before recreating it")
                    if len(session._queue) < MAX_QUEUED_JOBS:
                        session._queue.append(Job("namespace.snapshot", {}))
                        session._wake.set()
                    return {"session_id": session_id, "status": "existing", "ready": session._ready,
                            "execution_id": session._active.params.get("execution_id") if session._active else None,
                            "queued_operations": len(session._queue)}
            if len(self.sessions) >= MAX_SESSIONS:
                raise RuntimeErrorResponse("session_limit", "The preview supports at most 16 simultaneous sessions")
            self.sessions[session_id] = SessionRuntime(session_id, self.emit, self.idle_timeout, self.deliver_notification)
            return {"session_id": session_id, "status": "created"}
        if method == "session.close":
            session = self._session(params)
            self.pynia.detach(session.session_id)
            self._flush_snapshot(session)
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
            from src.core.parameter_settings import use_shared_parameter_delimiter
            try:
                with use_shared_parameter_delimiter(params.get("shared_delimiter", "{{name}}")):
                    pass
            except (ValueError, TypeError, AttributeError) as exc:
                raise RuntimeErrorResponse("invalid_params", str(exc)) from exc
            variable_name = params.get("variable_name")
            if variable_name is not None and (not isinstance(variable_name, str) or not variable_name.isidentifier() or variable_name.startswith("__")):
                raise RuntimeErrorResponse("invalid_params", "variable_name must be a valid Python identifier")
            download = params.get("export")
            if download is not None:
                if params["language"] != "sql" or not isinstance(download, dict):
                    raise RuntimeErrorResponse("invalid_params", "Only SQL executions can download directly to a file")
                from .stream_export import _destination, _options
                export_format = download.get("format", "csv")
                destination = _destination(download.get("path"), export_format)
                options, _, _ = _options(download.get("options"))
                options["stage_id"] = uuid.uuid4().hex
                params = {**params, "export": {"path": str(destination), "format": export_format, "options": options}}
            session.enqueue(method, self._route(params))
            return {"execution_id": execution_id, "status": "queued"}
        if method == "execution.cancel":
            return self._session(params).cancel(self._identifier(params.get("execution_id"), "execution_id"))
        if method in {"connection.connect", "connection.disconnect", "schema.get", "result.page", "result.release", "explorer.list", "explorer.details", "explorer.query", "explorer.use_database"}:
            routed = self._route(params)
            if method == "connection.connect" and not isinstance(routed.get("config") or routed.get("_connection_config"), dict):
                raise RuntimeErrorResponse("invalid_params", "config must be an object")
            if method in {"result.page", "result.release"}:
                self._identifier(params.get("result_id"), "result_id")
            self._session(params).enqueue(method, routed, request_id)
            return None
        if method in {"data.import", "variable.inspect", "variable.delete", "result.export", "result.summary", "result.chart", "result.chart_export", "result.artifact_write", "result.export_table", "document.read", "document.script_export"}:
            self._session(params).enqueue(method, self._route(params), request_id)
            return None
        if method in {"workspace.read", "workspace.write"}:
            path = params.get("path")
            if not isinstance(path, str) or not path:
                raise RuntimeErrorResponse("invalid_params", "path must be a nonempty string")
            return read_document(path) if method == "workspace.read" else write_document(path, params.get("document"))
        raise RuntimeErrorResponse("method_not_found", f"Unknown method: {method}")

    def close(self):
        self.background.close()
        self.desktop_services.close()
        self.pynia.close()
        for session in list(self.sessions.values()):
            self._flush_snapshot(session)
        with self._internal_lock:
            for done, box in self._internal.values():
                box["error"] = {"message": "Runtime is closing"}
                done.set()
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()
