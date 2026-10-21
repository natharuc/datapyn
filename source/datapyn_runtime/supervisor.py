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
from .export_control import EXPORT_METHODS
from .process_group import own_process_group
from .workspace import read_document, write_document
from .background import BackgroundJobs
from .connection_catalog import ConnectionCatalog
from .errors import serialize_runtime_error
from .configurations import ConfigurationTransfer
from .desktop_services import DesktopServices
from .pynia import PyniaService
from . import profiles
from .sql_commands import command_result, command_results
from .transaction_settings import editor_context_key

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
    command_results: list[dict] = field(default_factory=list)


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
        self._export_cancel = self._context.Event()
        self._import_cancel = self._context.Event()
        self._process = None
        self._group = None
        self._commands = None
        self._events = None
        self._event_reader = None
        self._reader_error = None
        self._incoming = queue.Queue(maxsize=64)
        self._restart_times = deque(maxlen=4)
        self._sql_safety_epoch = uuid.uuid4().hex
        self._sql_safety_revision = 0
        self._sql_safety_default = {}
        self._sql_safety_default_name = None
        self._sql_safety_active = {}
        self.language_contexts = OrderedDict()
        self.language_variables = {}
        self.language_version = 0
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
            operation_id = params.get("operation_id")
            if method in EXPORT_METHODS and operation_id:
                pending = ([self._active] if self._active else []) + list(self._queue)
                if any(job.method in EXPORT_METHODS and job.params.get("operation_id") == operation_id for job in pending):
                    raise RuntimeErrorResponse("duplicate_operation", "operation_id must be unique among pending exports")
            if method == "data.import" and operation_id:
                pending = ([self._active] if self._active else []) + list(self._queue)
                if any(job.method == "data.import" and job.params.get("operation_id") == operation_id for job in pending):
                    raise RuntimeErrorResponse("duplicate_operation", "operation_id must be unique among pending imports")
            if method == "execution.run":
                execution_id = params["execution_id"]
                if execution_id in self._states:
                    raise RuntimeErrorResponse("duplicate_execution", "execution_id must be unique within the session")
                self._states[execution_id] = "queued"
                self._trim_states()
            from .sql_safety_guard import CONTEXT_MUTATIONS
            if method in CONTEXT_MUTATIONS:
                self._sql_safety_revision = getattr(self, "_sql_safety_revision", 0) + 1
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

    def cancel_export(self, operation_id):
        queued = None
        with self._lock:
            if self._active and self._active.method in EXPORT_METHODS and self._active.params.get("operation_id") == operation_id:
                self._export_cancel.set()
                return {"operation_id": operation_id, "status": "cancelling"}
            for job in self._queue:
                if job.method in EXPORT_METHODS and job.params.get("operation_id") == operation_id:
                    queued = job
                    self._queue.remove(job)
                    break
        if queued is None:
            return {"operation_id": operation_id, "status": "already_finished"}
        self.emit({"event": "result.export_progress", "payload": {"session_id": self.session_id,
                   "operation_id": operation_id, "phase": "cancelled", "current": 0, "total": 0}})
        if queued.request_id is not None:
            self.emit({"id": queued.request_id, "error": {"code": "cancelled", "message": "Export cancelled before starting"}})
        return {"operation_id": operation_id, "status": "cancelled"}

    def cancel_import(self, operation_id):
        queued = None
        with self._lock:
            if self._active and self._active.method == "data.import" and self._active.params.get("operation_id") == operation_id:
                self._import_cancel.set()
                return {"operation_id": operation_id, "status": "cancelling"}
            for job in self._queue:
                if job.method == "data.import" and job.params.get("operation_id") == operation_id:
                    queued = job
                    self._queue.remove(job)
                    break
        if queued is None:
            return {"operation_id": operation_id, "status": "already_finished"}
        self.emit({"event": "data.import_progress", "payload": {"session_id": self.session_id,
                   "operation_id": operation_id, "phase": "cancelled", "current": 0, "total": 0}})
        if queued.request_id is not None:
            self.emit({"id": queued.request_id, "error": {"code": "cancelled", "message": "Import cancelled before starting"}})
        return {"operation_id": operation_id, "status": "cancelled"}

    def _launch(self):
        commands_recv, commands_send = self._context.Pipe(duplex=False)
        events_recv, events_send = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=kernel_main,
            args=(self.session_id, commands_recv, events_send, self.idle_timeout, self._export_cancel, self._import_cancel),
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
                if "command_result" in message:
                    # Record immediately on the reader, even while cancellation
                    # takes precedence over queued output/completion events.
                    self._receive_command_result(message)
                    continue
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

    def _receive_command_result(self, message):
        with self._lock:
            job = self._active
            if not job or job.method != "execution.run" or message.get("job_id") != job.job_id:
                return
            result = command_result(message.get("command_result"))
            if result is not None:
                job.command_results.append(result)

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
            payload = {
                "session_id": self.session_id,
                "execution_id": execution_id,
                "status": status,
                "duration_ms": round((time.monotonic() - job.started_at) * 1000, 3) if job.started_at else 0,
                "error": message,
                "results": [],
                "command_results": command_results(job.command_results),
                "variables": [],
            }
            from .notifications import capture_completion
            self._emit_finished(payload, capture_completion(job.params, payload))
        elif job.request_id is not None:
            self.emit({"id": job.request_id, "error": {"code": "kernel_reset", "message": message}})

    def _emit_finished(self, payload, prepared=None):
        # The local completion is delivered before scheduling any external IO.
        payload.setdefault("command_results", [])
        self.emit({"event": "execution.finished", "payload": payload})
        if prepared is not None and self.deliver_notification is not None:
            try:
                self.deliver_notification(None, prepared)
            except Exception as error:
                (prepared.get("_secrets") or {}).clear()
                prepared.pop("_secrets", None)
                self.emit({"event": "notifications.delivery_finished", "payload": {
                    **prepared.get("_completion_context", {}),
                    "deliveries": {channel: {"status": "failed", "error": f"{type(error).__name__}: notification scheduling failed"}
                                   for channel, enabled in prepared["notification"]["channels"].items() if enabled},
                }})

    def _reset_kernel(self, reason: str, active: Job | None, stale: list[Job]):
        self._sql_safety_revision = getattr(self, "_sql_safety_revision", 0) + 1
        self._sql_safety_default = {}
        self._sql_safety_default_name = None
        self._sql_safety_active = {}
        self._stop_process()
        with self._lock:
            self._active = None
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
        if "command_result" in message:
            self._receive_command_result(message)
            return
        with self._lock:
            # A cancellation command takes precedence over an unconsumed result.
            if self._pending_reset is not None:
                return
            if message.get("ready"):
                self._ready = True
                self.emit({"event": "session.ready", "payload": {"session_id": self.session_id}})
                return
            if "sql_safety_context" in message:
                self._sql_safety_active = message["sql_safety_context"]
                return
            if "language_context" in message:
                context = message["language_context"]
                key = context.get("key", "default")
                self.language_version += 1
                if context.get("metadata_invalidated"):
                    for old_key, old_context in self.language_contexts.items():
                        same_connection = old_context.get("connection_id") == context.get("connection_id")
                        same_owner = (context.get("metadata_invalidation_scope") != "block"
                                      or old_context.get("block_id") == context.get("block_id")
                                      or (context.get("scope_inherited") is True
                                          and old_context.get("scope_inherited") is True))
                        if context.get("metadata_invalidation_scope") == "block":
                            same_owner = same_owner and (old_context.get("automatic_transactions", True) == context.get("automatic_transactions", True))
                        if same_connection and same_owner:
                            old_context["schema"] = {}
                            old_context["schema_complete"] = False
                            self._context_codes.pop(old_key, None)
                self.language_contexts[key] = {**self.language_contexts.get(key, {}), **context}
                merged = self.language_contexts[key]
                merged["version"] = self.language_version
                self.language_contexts.move_to_end(key)
                while len(self.language_contexts) > 32:
                    old_key, _old_context = self.language_contexts.popitem(last=False)
                    self._context_codes.pop(old_key, None)
                self.language_variables = context.get("variables", self.language_variables)
                if not any(job.method == "language.context" and self.context_key(job.params) == key for job in self._queue):
                    self._context_requests.discard(key)
                self.emit({"event": "language.context_updated", "payload": {
                    "session_id": self.session_id, "connection_id": merged.get("connection_id"),
                    "database": merged.get("database", ""), "schema": merged.get("schema_name", ""),
                    "version": self.language_version, "variables": self.language_variables,
                    **({"automatic_transactions": context["automatic_transactions"]}
                       if isinstance(context.get("automatic_transactions"), bool) else {}),
                    **({"block_id": context["block_id"]} if context.get("block_id") else {}),
                    **({"scope_inherited": True} if context.get("scope_inherited") is True else {}),
                    **({"schema_snapshot": context["schema"]} if "schema" in context else {}),
                    **({"metadata_state": context["metadata_state"], "schema_error": context.get("schema_error")}
                       if "metadata_state" in context else {}),
                    **({"requested_scope": context["requested_scope"]} if "requested_scope" in context else {}),
                    **({"metadata_invalidated": True} if context.get("metadata_invalidated") else {}),
                    **({"metadata_invalidation_scope": context["metadata_invalidation_scope"]}
                       if context.get("metadata_invalidation_scope") in {"connection", "block"} else {}),
                }})
                return
            event = message.get("event")
            if event:
                payload = message["payload"]
                if event == "execution.finished":
                    if not self._active or message.get("job_id") != self._active.job_id:
                        return
                    self._states[payload["execution_id"]] = payload["status"]
                    self._sql_safety_revision = getattr(self, "_sql_safety_revision", 0) + 1
                    if payload.get("scope_inherited") is True and isinstance(payload.get("context_change"), dict):
                        self._sql_safety_default.update(payload["context_change"].get("current") or {})
                    self._active = None
                    self._emit_finished(payload, message.get("notification_delivery"))
                    return
                elif event.startswith("execution.") and (not self._active or self._active.method != "execution.run"):
                    return
                self.emit({"event": event, "payload": payload})
                return
            job = self._active
            if job is None or message.get("job_id") != job.job_id:
                return
            self._active = None
            if "result" in message:
                from .connection_catalog import without_secrets
                if job.method == "connection.connect":
                    self._sql_safety_default = without_secrets(message["result"].get("config") or {})
                    self._sql_safety_default_name = job.params.get("_connection_name") or job.params.get("connection_name")
                elif job.method == "connection.disconnect":
                    self._sql_safety_default = {}
                    self._sql_safety_default_name = None
                elif job.method == "explorer.use_database":
                    self._sql_safety_default.update(message["result"])
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
                        self._queue.clear()
                    if len(self._restart_times) >= 3 and now - self._restart_times[-3] < 10:
                        raise RuntimeError("Session worker repeatedly failed to start")
                    self._reset_kernel("worker_crashed", active, stale)
                    continue
                with self._lock:
                    if self._ready and self._active is None and self._queue and self._pending_reset is None:
                        job = self._queue.popleft()
                        job.started_at = time.monotonic()
                        if job.method in EXPORT_METHODS:
                            self._export_cancel.clear()
                        if job.method == "data.import":
                            self._import_cancel.clear()
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
                self._queue.clear()
            self._stop_process()
            with self._lock:
                self._active = None
            for job in ([active] if active else []) + queued:
                self._finish_interrupted(job, "cancelled", "Session closed or unavailable")

    def close(self):
        with self._lock:
            self._closed = True
        self._wake.set()
        self._thread.join(timeout=5)

    @staticmethod
    def context_key(params):
        return editor_context_key(params)

    def editor_context(self, params, *, refresh=True, force=False):
        with self._lock:
            key = self.context_key(params)
            context = dict(self.language_contexts.get(key) or {})
            if params.get("block_id") and "scope_inherited" not in params:
                # Older clients prepare a connection-wide snapshot before
                # requesting completion with a block id. Modern clients send
                # an explicit ownership flag and never borrow this snapshot.
                legacy_params = {name: value for name, value in params.items() if name != "block_id"}
                legacy_context = self.language_contexts.get(self.context_key(legacy_params)) or {}
                if legacy_context.get("schema") and (not context.get("schema")
                        or legacy_context.get("version", 0) > context.get("version", 0)):
                    context = dict(legacy_context)
            context["variables"] = dict(self.language_variables)
            context["version"] = self.language_version
            if not refresh:
                return context
            code = params.get("code", "")
            from .sql_context import metadata_signature
            db_type = str((params.get("_connection_config") or params.get("config") or {}).get("db_type") or "")
            signature = metadata_signature(code, db_type) if params.get("language") == "sql" and isinstance(code, str) and len(code) <= MAX_CODE_BYTES else ()
            previous_signature, previous_time = self._context_codes.get(key, (None, 0))
            now = time.monotonic()
            needs_context = force or signature != previous_signature or now - previous_time >= 60
            if params.get("language") == "sql" and key in self._context_requests and needs_context:
                pending = next((job for job in self._queue if job.method == "language.context" and self.context_key(job.params) == key), None)
                if pending is not None:
                    # Typing a different relation while metadata waits behind
                    # user code replaces the pending document rather than
                    # queueing one database crawl per keystroke.
                    pending.params = {**params, **({"refresh": True} if force or pending.params.get("refresh") else {})}
                    self._context_codes[key] = (signature, now)
                elif len(self._queue) < MAX_QUEUED_JOBS:
                    # An in-flight crawl cannot be rewritten. Keep exactly one
                    # coalesced follow-up for the newest code/forced reload.
                    self._queue.append(Job("language.context", {**params, **({"refresh": True} if force else {})}))
                    self._context_codes[key] = (signature, now)
                    self._wake.set()
            elif params.get("language") == "sql" and needs_context:
                # Metadata work waits safely behind executions. The language
                # request itself immediately uses the latest immutable snapshot.
                self._context_requests.add(key)
                if len(self._queue) < MAX_QUEUED_JOBS:
                    self._queue.append(Job("language.context", {**params, **({"refresh": True} if force else {})}))
                    self._context_codes[key] = (signature, now)
                    self._wake.set()
                else:
                    self._context_requests.discard(key)
            return context

    def prepare_context(self, params):
        """Warm the focused SQL scope without invoking a completion provider."""
        with self._lock:
            if self._closed or self._failed:
                raise RuntimeErrorResponse("session_unavailable", "This session is unavailable; create a new session")
            context = self.editor_context({**params, "language": "sql"}, force=bool(params.get("refresh")))
            queued = self.context_key(params) in self._context_requests
            if not queued and len(self._queue) >= MAX_QUEUED_JOBS and (params.get("refresh") or not context.get("schema")):
                raise RuntimeErrorResponse("queue_full", "This session already has 64 queued operations")
            return {"status": "queued" if queued else "ready", "context_version": context.get("version", 0)}


class Supervisor:
    """Dispatch protocol requests; execution never blocks this request thread."""

    def __init__(self, emit):
        self._emit = emit
        self.emit = self._deliver
        self._internal = {}
        self._internal_lock = threading.RLock()
        self._notification_deliveries = {}
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
        if request_id is not None:
            # Preserve the existing explicit notifications.send RPC response.
            self.background.submit(request_id, "notifications.deliver_prepared", prepared, {})
            return
        notification = prepared["notification"]
        channels = [channel for channel, enabled in notification["channels"].items() if enabled]
        if not notification["send_external"] or not channels:
            (prepared.get("_secrets") or {}).clear()
            prepared.pop("_secrets", None)
            return
        identifier = "notification:" + uuid.uuid4().hex
        with self._internal_lock:
            self._notification_deliveries[identifier] = {**prepared.get("_completion_context", {}), "_channels": channels}
        try:
            self.background.submit(identifier, "notifications.deliver_prepared", prepared, {})
        except Exception as error:
            self._deliver({"id": identifier, "error": {"message": f"{type(error).__name__}: notification scheduling failed"}})
            (prepared.get("_secrets") or {}).clear()
            prepared.pop("_secrets", None)

    def _deliver(self, message):
        request_id = message.get("id")
        event = message.get("event")
        execution_id = message.get("payload", {}).get("execution_id") if event else None
        with self._internal_lock:
            notification = self._notification_deliveries.pop(request_id, None) if request_id else None
            if notification is not None:
                channels = notification.pop("_channels", [])
                deliveries = message.get("result", {}).get("deliveries", {})
                if "error" in message:
                    deliveries = {channel: {"status": "failed", "error": "Notification delivery failed"} for channel in channels}
                self._emit({"event": "notifications.delivery_finished", "payload": {**notification, "deliveries": deliveries}})
                return
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
        submitted = {**params, "session_id": session_id}
        session = self._session(submitted)
        with self._internal_lock:
            self._internal[identifier] = (done, box)
        try:
            with session._lock:
                routed = self._route(submitted)
                if method in {"execution.run", "result.export_table"}:
                    routed.update(self.sql_safety_guard.authorize(method, submitted, self._sql_safety_binding(submitted), allow_ticket=False))
                session.enqueue(method, routed, identifier)
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
        submitted = {**params, "session_id": session_id, "execution_id": identifier}
        session = self._session(submitted)
        with self._internal_lock:
            self._internal[identifier] = (done, box)
        try:
            with session._lock:
                routed = self._route(submitted)
                routed.update(self.sql_safety_guard.authorize("execution.run", submitted, self._sql_safety_binding(submitted), allow_ticket=False))
                session.enqueue("execution.run", routed)
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

    @property
    def sql_safety_guard(self):
        guard = getattr(self, "_sql_safety_guard", None)
        if guard is None:
            from .sql_safety_guard import SqlSafetyGuard
            guard = self._sql_safety_guard = SqlSafetyGuard()
        return guard

    def _sql_safety_binding(self, params):
        """Public target identity only; reviewing never resolves OS credentials."""
        from .connection_catalog import without_secrets
        from copy import deepcopy
        session = self._session(params)
        default = getattr(session, "_sql_safety_default", {})
        active = getattr(session, "_sql_safety_active", {})
        config = params.get("config") or params.get("_connection_config") or default or active.get("config") or {}
        identifier = params.get("connection_id")
        saved = None
        if identifier or params.get("connection_name"):
            with self.catalog._lock:
                if not identifier:
                    identifier = self.catalog.resolve_ref(params.get("connection_group"), params["connection_name"])
                saved = deepcopy(self.catalog._find("connections", identifier))
                config = self.catalog.resolve_ssh(saved["config"], resolve_credentials=False)
        uses_active_fallback = not (identifier or params.get("connection_name") or params.get("config") or params.get("_connection_config") or default)
        connection_name = saved.get("name") if saved else params.get("connection_name") or config.get("name") or getattr(session, "_sql_safety_default_name", None) or active.get("connection_name")
        return {"profile": str(self.profile_path), "session_epoch": getattr(session, "_sql_safety_epoch", session.session_id),
                "session_revision": getattr(session, "_sql_safety_revision", 0), "connection_id": identifier,
                "connection_name": connection_name,
                "uses_active_fallback": uses_active_fallback,
                "active_fallback": active if uses_active_fallback else None,
                "saved_connection": without_secrets(saved), "config": without_secrets(deepcopy(config)),
                "db_type": config.get("db_type", "")}

    def _authorize_sql(self, method, params, session):
        from .sql_safety_guard import CONTEXT_ACTIVATIONS, ConfirmationRequiredError
        binding = self._sql_safety_binding(params)
        authorization = self.sql_safety_guard.authorize(method, params, binding)
        if authorization["_sql_safety_authorized"] and binding["uses_active_fallback"]:
            pending = ([session._active] if session._active else []) + list(session._queue)
            if any(job.method in CONTEXT_ACTIVATIONS for job in pending):
                raise ConfirmationRequiredError()
        return authorization

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

    def _route(self, params, *, capture_transaction_policy=True):
        routed = dict(params)
        routed.pop("confirmation_token", None)
        for key in list(routed):
            if key.startswith("_sql_safety_"):
                routed.pop(key)
        if capture_transaction_policy:
            routed.pop("_execution_scope_id", None)
            routed.pop("_metadata_scope", None)
            from .transaction_settings import settings_path, validate_execution_options, effective_automatic_transactions
            validate_execution_options(routed)
            routed["_transaction_settings_path"] = str(settings_path())
            routed["_automatic_transactions_snapshot"] = effective_automatic_transactions(routed)
        identifier = routed.get("connection_id")
        credential_identifier = routed.pop("credential_connection_id", None)
        if credential_identifier is not None:
            self._identifier(credential_identifier, "credential_connection_id")
            if identifier or not isinstance(routed.get("config"), dict):
                raise ValueError("credential_connection_id requires a draft config and no connection_id")
        resolve_database_password = routed.get("resolve_database_password", True)
        if not isinstance(resolve_database_password, bool):
            raise ValueError("resolve_database_password must be a boolean")
        if not identifier and routed.get("connection_name"):
            identifier = self.catalog.resolve_ref(routed.get("connection_group"), routed["connection_name"])
            routed["connection_id"] = identifier
        reference = identifier or credential_identifier
        if reference:
            self._identifier(reference, "connection_id" if identifier else "credential_connection_id")
            # The display name lives outside the driver config. Capture it
            # without changing engine keys or exposing credentials to the UI.
            with self.catalog._lock:
                from .connection_catalog import ssh_identity
                from .database import database_credential_identity, connection_test_config
                saved = self.catalog._find("connections", reference)
                draft = routed.get("config")
                has_draft = isinstance(draft, dict)
                public_saved = self.catalog.resolve_ssh(saved["config"], resolve_credentials=False)
                public_draft = self.catalog.resolve_ssh(draft, resolve_credentials=False) if has_draft else None
                same_database = not has_draft or database_credential_identity(public_saved) == database_credential_identity(public_draft)
                same_ssh = not has_draft or bool((public_draft.get("ssh") or {}).get("enabled")) and ssh_identity(public_saved) == ssh_identity(public_draft)
                routed["_connection_config"] = self.catalog.config(reference,
                    resolve_database_password=resolve_database_password and same_database,
                    resolve_ssh_credentials=same_ssh)
                routed["_connection_name"] = saved["name"]
                if credential_identifier:
                    routed["config"] = public_draft
                    routed["_connection_config"] = connection_test_config(routed, match_database_identity=True)
        # A client may configure a database, but may not redirect host trust to
        # an arbitrary file. Every profile owns an independent pin registry.
        needs_ssh = any(isinstance(routed.get(key), dict) and (routed[key].get("ssh") or {}).get("enabled")
                        for key in ("config", "_connection_config"))
        for key in ("config", "_connection_config"):
            if isinstance(routed.get(key), dict):
                routed[key] = self.catalog.resolve_ssh(routed[key])
                routed[key].pop("_ssh_trust_path", None)
                routed[key].pop("_ssh_catalog_path", None)
                if needs_ssh or (routed[key].get("ssh") or {}).get("enabled"):
                    routed[key]["_ssh_trust_path"] = str(self.profile_path / "ssh_known_hosts.json")
                if routed[key].get("ssh_tunnel_id"):
                    routed[key]["_ssh_catalog_path"] = str(self.catalog.path)
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
            error = serialize_runtime_error(exc, default_code="invalid_params")
            self.emit({"id": request_id, "error": error})
        except Exception as exc:
            self.emit({"id": request_id, "error": serialize_runtime_error(exc, default_code="internal_error")})

    def dispatch(self, method: str, params: dict, request_id: int):
        if method == "system.info":
            from src.database.sqlserver_network_auth import sqlserver_authentication_capabilities
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
                    "sqlserver_authentication": sqlserver_authentication_capabilities(),
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
            background = self.background.active_count
            with self._internal_lock:
                background += self._flushes
            packages = int(self.desktop_services.busy)
            return {"busy": bool(executions or packages or pynia or background),
                    "executions": executions, "packages": packages, "pynia": pynia, "background": background}
        if method.startswith("connections.") or method.startswith("groups."):
            return self.catalog.dispatch(method, params)
        if method in {"transactions.settings.get", "transactions.settings.set"}:
            from .transaction_settings import settings_get, settings_set
            return settings_get() if method.endswith(".get") else settings_set(params)
        if method in {"sql.safety.settings.get", "sql.safety.settings.set"}:
            from .sql_safety_settings import settings_get, settings_set
            return settings_get() if method.endswith(".get") else settings_set(params)
        if method in {"ssh.tunnels.list", "ssh.tunnels.save", "ssh.tunnels.delete"}:
            return self.catalog.dispatch(method, params)
        if method == "ssh.tunnels.test":
            from .connection_catalog import normalized_ssh, ssh_identity, SSH_SECRET_KEYS
            from copy import deepcopy
            if params.get("test_id") is not None:
                self._identifier(params["test_id"], "test_id")
            draft = params.get("config")
            if draft is not None and not isinstance(draft, dict):
                raise ValueError("SSH config must be an object")
            identifier = params.get("tunnel_id")
            public = normalized_ssh({**draft, "enabled": True}) if draft is not None else None
            config = self.catalog.tunnel_config(identifier, resolve_credentials=False) if identifier else {}
            same_identity = public is None or ssh_identity({"ssh": config}) == ssh_identity({"ssh": public})
            if identifier and same_identity:
                config = self.catalog.tunnel_config(identifier)
            if draft is not None:
                secrets = {key: config[key] for key in SSH_SECRET_KEYS if config.get(key)} if same_identity else {}
                secrets.update({key: str(draft[key]) for key in SSH_SECRET_KEYS if draft.get(key)})
                config = {**public, **secrets}
            auth = config.get("auth_method") or "password"
            config.pop("passphrase" if auth == "password" else "password", None)
            self.background.submit(request_id, method, {**deepcopy(params), "config": config,
                "_ssh_trust_path": str(self.profile_path / "ssh_known_hosts.json")}, {})
            return None
        if method == "ssh.host_key.trust":
            from .ssh_tunnel import SshTrustStore
            return SshTrustStore(self.profile_path / "ssh_known_hosts.json").confirm(params.get("details"))
        if method.startswith("configurations."):
            if method == "configurations.import" and self.dispatch("system.activity", {}, request_id)["busy"]:
                raise RuntimeErrorResponse("workspace_busy", "Wait for executions, packages, Pynia and background operations before importing settings")
            return ConfigurationTransfer(self.profile_path, self.catalog, self.desktop_services.packages).dispatch(method, params)
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
        if method == "language.cancel":
            session_id = params.get("session_id")
            if session_id is not None:
                self._identifier(session_id, "session_id")
            return self.background.cancel_completion(session_id, self._identifier(params.get("block_id"), "block_id"),
                                                     self._identifier(params.get("completion_id"), "completion_id"))
        if method == "language.diagnostics.cancel":
            session_id = params.get("session_id")
            if session_id is not None:
                self._identifier(session_id, "session_id")
            return self.background.cancel_diagnostics(session_id, self._identifier(params.get("block_id"), "block_id"),
                                                     self._identifier(params.get("diagnostic_id"), "diagnostic_id"))
        if method == "language.diagnostics":
            code = params.get("code")
            if params.get("language") not in {"sql", "python"} or not isinstance(code, str):
                raise RuntimeErrorResponse("invalid_params", "language must be sql/python and code a string")
            for field in ("session_id", "block_id", "diagnostic_id"):
                if params.get(field) is not None:
                    self._identifier(params[field], field)
            if len(code) > MAX_CODE_BYTES or len(code.encode("utf-8")) > MAX_CODE_BYTES:
                if params.get("block_id"):
                    self.background.diagnostic_jobs.cancel_block(params.get("session_id"), params["block_id"])
                return {"status": "partial", "markers": [], "message": (
                    "A validação foi pausada: o bloco ultrapassa o limite de 1 MiB."
                    if params.get("locale") == "pt-BR" else
                    "Validation paused: this block exceeds the 1 MiB limit.")}
            routed = self._route(params, capture_transaction_policy=False)
            context = self._session(params).editor_context(routed, refresh=False) if params.get("session_id") else {}
            self.background.submit(request_id, method, routed, context)
            return None
        if method == "language.prepare":
            code = params.get("code", "")
            if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
                raise RuntimeErrorResponse("invalid_params", "code must be a string of at most 1 MiB")
            if "refresh" in params and not isinstance(params["refresh"], bool):
                raise RuntimeErrorResponse("invalid_params", "refresh must be a boolean")
            return self._session(params).prepare_context(self._route({**params, "code": code}))
        if method in {"language.complete", "language.format", "parameters.scan"}:
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
            self.background.diagnostic_jobs.cancel_session(session.session_id)
            self.pynia.detach(session.session_id)
            self._flush_snapshot(session)
            del self.sessions[session.session_id]
            session.close()
            return {"session_id": session.session_id, "status": "closed"}
        if method == "execution.review":
            from .sql_safety_guard import CONTEXT_MUTATIONS, CONTEXT_ACTIVATIONS
            reviewed_method = params.get("method", "execution.run")
            session = self._session(params)
            with session._lock:
                pending = ([session._active] if session._active else []) + list(session._queue)
                binding = self._sql_safety_binding(params)
                review = self.sql_safety_guard.review(reviewed_method, params, binding)
                guarded_pending = CONTEXT_MUTATIONS | (CONTEXT_ACTIVATIONS if binding["uses_active_fallback"] else set())
                if review["confirmation_required"] and any(job.method in guarded_pending for job in pending):
                    with self.sql_safety_guard.lock:
                        self.sql_safety_guard.tickets.pop(review["confirmation_token"], None)
                    raise RuntimeErrorResponse("session_busy", "Aguarde a execução atual antes de revisar os comandos SQL.")
                if binding.get("connection_name"):
                    review["connection_name"] = binding["connection_name"]
                return review
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
            notification = params.get("notification")
            if notification is not None:
                if not isinstance(notification, dict) or not isinstance(notification.get("context", {}), dict):
                    raise RuntimeErrorResponse("invalid_params", "notification and its context must be objects")
                if not isinstance(notification.get("emit_notification", True), bool):
                    raise RuntimeErrorResponse("invalid_params", "emit_notification must be a boolean")
            download = params.get("export")
            normalized_download = None
            if download is not None:
                if params["language"] != "sql" or not isinstance(download, dict):
                    raise RuntimeErrorResponse("invalid_params", "Only SQL executions can download directly to a file")
                from .stream_export import _destination, _options
                export_format = download.get("format", "csv")
                destination = _destination(download.get("path"), export_format)
                options, _, _ = _options(download.get("options"))
                options["stage_id"] = uuid.uuid4().hex
                normalized_download = {"path": str(destination), "format": export_format, "options": options}
            with session._lock:
                authorization = self._authorize_sql(method, params, session)
                routed = self._route(params)
                routed.update(authorization)
                if normalized_download is not None:
                    routed["export"] = normalized_download
                session.enqueue(method, routed)
            return {"execution_id": execution_id, "status": "queued"}
        if method == "execution.cancel":
            return self._session(params).cancel(self._identifier(params.get("execution_id"), "execution_id"))
        if method in {"connection.connect", "connection.disconnect", "schema.get", "result.page", "result.column_values", "result.release", "explorer.list", "explorer.details", "explorer.query", "explorer.use_database"}:
            routed = self._route(params)
            if method == "connection.connect" and not isinstance(routed.get("config") or routed.get("_connection_config"), dict):
                raise RuntimeErrorResponse("invalid_params", "config must be an object")
            if method in {"result.page", "result.column_values", "result.release"}:
                self._identifier(params.get("result_id"), "result_id")
            self._session(params).enqueue(method, routed, request_id)
            return None
        if method == "result.export_cancel":
            return self._session(params).cancel_export(self._identifier(params.get("operation_id"), "operation_id"))
        if method == "data.import_cancel":
            return self._session(params).cancel_import(self._identifier(params.get("operation_id"), "operation_id"))
        if method in {"data.import", "variable.inspect", "variable.delete", "result.export", "result.export_text", "result.summary", "result.chart", "result.chart_export", "result.artifact_write", "result.export_table", "document.read", "document.script_export", "variable.archive.list", "variable.archive.export", "variable.archive.import"}:
            if params.get("operation_id") is not None:
                self._identifier(params["operation_id"], "operation_id")
            session = self._session(params)
            with session._lock:
                routed = self._route(params)
                if method == "result.export_table":
                    routed.update(self._authorize_sql(method, params, session))
                session.enqueue(method, routed, request_id)
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
            self._notification_deliveries.clear()
            for done, box in self._internal.values():
                box["error"] = {"message": "Runtime is closing"}
                done.set()
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()
        try:
            profiles.close_stores()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Could not flush the workspace session database during shutdown")
            raise
