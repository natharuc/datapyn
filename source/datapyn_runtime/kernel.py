"""A persistent interpreter owned by one session, with no UI objects or Qt."""

from __future__ import annotations

import ast
import base64
import io
import os
from pathlib import Path
import sys
import threading
import time
import traceback

from . import database
from .values import describe_variables, preview, scalar
from .stdio import isolate_kernel_output
from .process_group import initialize_kernel_group, exit_kernel_and_children
from .language import namespace_snapshot
from .desktop_services import enable_user_packages
from .rich_outputs import RichOutputs

MAX_OUTPUT_BYTES = 256 * 1024
from .result_store import ResultStore, MAX_PAGE_ROWS, MAX_RESULT_HANDLES


class OutputCapture:
    """Stream small batches with a shared stdout/stderr budget per execution."""

    def __init__(self, emit, session_id: str, execution_id: str):
        self.emit = emit
        self.session_id = session_id
        self.execution_id = execution_id
        self._lock = threading.Lock()
        self._buffers = {"stdout": "", "stderr": ""}
        self._remaining = MAX_OUTPUT_BYTES
        self._truncated = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="execution-output", daemon=True)
        self._thread.start()

    def write(self, stream: str, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() argument must be str")
        with self._lock:
            if self._remaining > 0:
                data = text.encode("utf-8", errors="replace")
                accepted = data[: self._remaining]
                self._remaining -= len(accepted)
                self._buffers[stream] += accepted.decode("utf-8", errors="ignore")
                if len(data) > len(accepted):
                    self._mark_truncated()
            elif text:
                self._mark_truncated()
        return len(text)

    def _mark_truncated(self):
        if not self._truncated:
            self._truncated = True
            self._buffers["stderr"] += "\n[DataPyn: output truncated after 256 KiB]\n"

    def flush(self):
        with self._lock:
            batches = self._buffers
            self._buffers = {"stdout": "", "stderr": ""}
        for stream, text in batches.items():
            for offset in range(0, len(text), 4096):
                self.emit("execution.output", {
                    "session_id": self.session_id,
                    "execution_id": self.execution_id,
                    "stream": stream,
                    "text": text[offset : offset + 4096],
                })

    def _pump(self):
        while not self._stop.wait(0.1):
            self.flush()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1)
        self.flush()


class CapturedStream(io.TextIOBase):
    def __init__(self, capture: OutputCapture, stream: str):
        self.capture = capture
        self.stream = stream

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def write(self, text):
        return self.capture.write(self.stream, text)

    def flush(self):
        self.capture.flush()

    def isatty(self):
        return False



def execute_python(code: str, namespace: dict, filename: str):
    """Evaluate the final expression, preserving Python compound statements."""
    tree = ast.parse(code, filename=filename)
    if not tree.body:
        return None
    if isinstance(tree.body[-1], ast.Expr):
        statements = ast.Module(body=tree.body[:-1], type_ignores=[])
        ast.fix_missing_locations(statements)
        exec(compile(statements, filename, "exec"), namespace)
        expression = ast.Expression(body=tree.body[-1].value)
        ast.fix_missing_locations(expression)
        return eval(compile(expression, filename, "eval"), namespace)
    exec(compile(tree, filename, "exec"), namespace)
    return None


def capture_figures() -> list[dict]:
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return []
    outputs = []
    try:
        for number in plt.get_fignums()[:8]:
            buffer = io.BytesIO()
            plt.figure(number).savefig(buffer, format="png", dpi=120, bbox_inches="tight")
            data = buffer.getvalue()
            if len(data) <= 2 * 1024 * 1024:
                outputs.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime": "image/png"})
    finally:
        plt.close("all")
    return outputs


def _watch_parent():
    """Owned kernels exit if a sidecar is killed without running cleanup."""
    from multiprocessing import parent_process
    from multiprocessing.connection import wait

    parent = parent_process()
    if parent is not None:
        wait([parent.sentinel])
        exit_kernel_and_children()


def kernel_main(session_id: str, commands, events, idle_timeout=300, export_cancel=None):
    initialize_kernel_group()
    # C extensions, os.write() and child subprocesses must never inherit the
    # NDJSON protocol descriptors. Python print() is streamed separately below.
    isolate_kernel_output()
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("DATAPYN_SHARED_PARAMETER_DELIMITER", "{{name}}")
    os.environ.setdefault("DATAPYN_WORKSPACE_PATH", str(Path.home() / ".datapyn-tauri-preview"))
    threading.Thread(target=_watch_parent, name="runtime-parent-watch", daemon=True).start()
    send_lock = threading.Lock()

    def send(message):
        with send_lock:
            events.send(message)

    def emit(event, payload):
        send({"event": event, "payload": payload})

    enable_user_packages()
    import numpy as np
    import pandas as pd
    import polars as pl

    namespace = {"pd": pd, "np": np, "pl": pl}
    store = ResultStore(pd, pl)
    pool = database.ConnectorPool(idle_timeout)
    rich_capture = RichOutputs()
    namespace.setdefault("display", rich_capture.display)
    connector = None
    context_key = "default"
    connection_labels = {}
    snapshot_dirty = False

    def autosave():
        nonlocal snapshot_dirty
        if not snapshot_dirty:
            return
        # Namespace access and Parquet serialization remain on the interpreter
        # thread, after pending commands have drained. Failed saves retry only
        # after another successful mutation, rather than on every idle tick.
        snapshot_dirty = False
        try:
            from .variable_snapshot import save
            saved = save({"session_id": session_id}, namespace, store)
            if saved.get("reason") != "disabled":
                event = "snapshot.saved" if saved.get("saved") else "snapshot.warning"
                emit(event, {"session_id": session_id, **saved})
        except Exception as exc:
            emit("snapshot.warning", {"session_id": session_id, "saved": False, "error": f"{type(exc).__name__}: {exc}"})

    def activate(params, *, default=False):
        nonlocal connector, context_key
        connector = pool.activate(params, default=default)
        config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
        name = params.get("_connection_name") or config.get("name")
        if name:
            connection_labels[pool.active_key] = str(name)
        for key in list(connection_labels):
            if key not in pool.items:
                del connection_labels[key]
        context_key = "|".join(str(params.get(key) or "") for key in ("connection_id", "database", "schema")) or "default"
        namespace.update({
            "db_engine": connector.engine, "db_type": connector.db_type,
            "db_database": connector.connection_params.get("database", ""),
            "db_host": connector.connection_params.get("host", ""),
            "db_username": connector.connection_params.get("username", ""),
            "db_schema": pool.explorer().context()["schema"],
        })
        return connector

    def publish_context(params=None, *, metadata=False, invalidated=False):
        key = context_key
        context = {"key": key, "variables": namespace_snapshot(namespace), "connection_id": pool.active_key[0] if pool.active_key else None}
        if invalidated:
            context.update({"schema": {}, "metadata_invalidated": True})
        if metadata and connector is not None:
            schema = pool.explorer().completion_schema((params or {}).get("code", ""))
            context.update({"schema": schema, "database": schema.get("database", ""),
                            "schema_name": schema.get("current_schema", ""),
                            "metadata_state": "ready", "schema_error": None,
                            "requested_scope": {field: (params or {}).get(field) for field in ("connection_id", "database", "schema")},
                            "schema_complete": bool((params or {}).get("code")),
                            "version": time.monotonic_ns()})
        send({"language_context": context})

    send({"ready": True})
    try:
        from .variable_snapshot import settings_get, restore
        settings = settings_get()
        if settings["enabled"] and settings["restore_on_startup"]:
            restored = restore({"session_id": session_id}, namespace, store)
            emit("namespace.changed", {"session_id": session_id, **restored})
            publish_context()
    except Exception as exc:
        emit("snapshot.error", {"session_id": session_id, "error": str(exc)})
    try:
        while True:
            try:
                if not commands.poll(1):
                    autosave()
                    closed = pool.reap_idle()
                    if closed:
                        connector = pool.active
                        if connector is None:
                            namespace.pop("db_engine", None)
                        emit("connection.idle_closed", {"session_id": session_id, "connection_ids": closed})
                    continue
                job = commands.recv()
            except EOFError:
                return
            method = job["method"]
            params = job["params"]
            job_id = job["job_id"]
            if method == "shutdown":
                return
            if method == "execution.run":
                execution_id = params["execution_id"]
                started = time.perf_counter()
                emit("execution.started", {"session_id": session_id, "execution_id": execution_id})
                capture = OutputCapture(emit, session_id, execution_id)
                from src.core.parameter_settings import use_shared_parameter_delimiter
                delimiter_context = use_shared_parameter_delimiter(params.get("shared_delimiter", "{{name}}"))
                delimiter_context.__enter__()
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = CapturedStream(capture, "stdout"), CapturedStream(capture, "stderr")
                results, rich_outputs, error, download_result = [], [], None, None
                execution_connection = None
                rich_capture.begin()
                try:
                    before = {name: id(value) for name, value in namespace.items() if store.is_frame(value)}
                    if params.get("connection_id") or params.get("_connection_config") or pool.default_config is not None:
                        activate(params)
                    if connector is not None:
                        execution_connection = {"database": connector.connection_params.get("database", "")}
                        if pool.active_key in connection_labels:
                            execution_connection["connection"] = connection_labels[pool.active_key]
                    if params["language"] == "sql":
                        if connector is None:
                            raise ConnectionError("Connect this session to a database first")
                        parameters = params.get("parameters")
                        if parameters is None:
                            parameters = (params.get("sql_parameters") or []) + (params.get("shared_parameters") or [])
                        if params.get("export"):
                            from .stream_export import run as stream_download
                            download = params["export"]
                            last_progress = {}
                            def progress(update):
                                now = time.monotonic()
                                key = update["file_index"]
                                if key not in last_progress or now - last_progress[key] >= 0.1:
                                    last_progress[key] = now
                                    emit("execution.export_progress", {"session_id": session_id,
                                        "execution_id": execution_id, **update})
                            download_result = stream_download(
                                connector, params["code"], path=download["path"],
                                export_format=download["format"], parameters=parameters or None,
                                options=download["options"], on_progress=progress,
                            )
                        else:
                            value = connector.execute_query(params["code"], parameters=parameters or None)
                            values = value if isinstance(value, list) else [value]
                            for index, frame in enumerate(values):
                                name = params.get("variable_name") or "df"
                                if index:
                                    name = f"{name}{index}"
                                namespace[name] = frame
                                if store.is_frame(frame):
                                    results.append(store.register(frame, name))
                    else:
                        enable_user_packages()
                        code = params["code"]
                        if params.get("shared_parameters"):
                            from src.utils.sql_parameter_service import prepare_python_code_with_shared_parameters
                            code = prepare_python_code_with_shared_parameters(code, params["shared_parameters"])
                        value = execute_python(code, namespace, f"<datapyn:{execution_id}>")
                        name = params.get("variable_name")
                        if value is None:
                            changed = [(key, val) for key, val in namespace.items() if store.is_frame(val) and before.get(key) != id(val)]
                            if changed:
                                name, value = changed[-1]
                        if store.is_frame(value):
                            if not name:
                                name = next((key for key, val in namespace.items() if val is value and not key.startswith("_")), "result")
                            namespace[name] = value
                            results.append(store.register(value, name))
                        elif value is not None:
                            if not rich_capture.capture(value):
                                print(preview(value, limit=8192))
                    for output in capture_figures():
                        rich_capture.add(output)
                    rich_outputs = rich_capture.outputs
                except BaseException:
                    error = traceback.format_exc()[-32_768:]
                finally:
                    delimiter_context.__exit__(None, None, None)
                    sys.stdout, sys.stderr = old_stdout, old_stderr
                    capture.close()
                    store.invalidate_views()
                    pool.touch_active()
                payload = {
                    "session_id": session_id,
                    "execution_id": execution_id,
                    "status": "failed" if error else "succeeded",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "results": results,
                    "variables": describe_variables(namespace),
                }
                if error:
                    payload["error"] = error
                if rich_outputs:
                    payload["rich_outputs"] = rich_outputs
                if download_result is not None:
                    payload["export"] = download_result
                # A failed block may have partially changed a frame in place.
                # Keep the previous durable generation until a later success.
                snapshot_dirty = error is None
                # All blocks share this interpreter's namespace. Publish its
                # immutable names/types/columns before clients observe the
                # completed execution, without waiting for database metadata.
                publish_context()
                from .notifications import capture_completion
                notification = capture_completion(params, payload, namespace, store, connection_context=execution_connection)
                send({"event": "execution.finished", "payload": payload, "job_id": job_id,
                      **({"notification_delivery": notification} if notification is not None else {})})
                from .sql_context import changes_metadata
                invalidated = params["language"] == "sql" and connector is not None and changes_metadata(params["code"])
                if invalidated:
                    from .table_export import refresh_temporary_tables
                    refresh_temporary_tables(connector)
                    pool.explorer().cache.clear()
                    pool.explorer().column_cache.clear()
                    publish_context(invalidated=True)
                continue
            try:
                if method == "connection.connect":
                    activate(params, default=True)
                    safe_config = {key: value for key, value in (pool.default_config or {}).items()
                                   if key not in {"password", "token", "access_token", "client_secret"}}
                    result = {"status": "connected", "connection_id": params.get("connection_id"), "config": safe_config, **pool.explorer().context()}
                    publish_context()
                elif method == "connection.disconnect":
                    pool.disconnect(params.get("connection_id"))
                    connector = pool.active
                    if connector is None:
                        for name in ("db_engine", "db_type", "db_database", "db_host", "db_username", "db_schema"):
                            namespace.pop(name, None)
                    result = {"status": "disconnected", "connection_id": params.get("connection_id")}
                elif method == "connection.idle_timeout":
                    pool.idle_timeout = params["seconds"]
                    result = {"seconds": pool.idle_timeout}
                elif method == "schema.get":
                    activate(params)
                    result = database.schema(connector)
                elif method == "result.page":
                    result = store.page(params)
                elif method == "result.column_values":
                    result = store.column_values(params)
                elif method == "result.release":
                    result = store.release(params["result_id"])
                elif method == "namespace.snapshot":
                    result = {"variables": describe_variables(namespace), "results": list(store.descriptors.values())}
                    emit("namespace.changed", {"session_id": session_id, **result})
                elif method == "result.artifact_write":
                    result = rich_capture.write(params)
                elif method.startswith("explorer."):
                    routed = dict(params)
                    node = params.get("node") or {}
                    if node.get("database"):
                        routed.setdefault("database", node["database"])
                    activate(routed, default=method == "explorer.use_database")
                    if method == "explorer.use_database":
                        result = pool.explorer().context()
                        publish_context(invalidated=True)
                    elif method == "explorer.snapshot":
                        result = pool.explorer().completion_schema()
                    else:
                        result = pool.explorer().dispatch(method, params)
                elif method == "language.context":
                    try:
                        activate(params)
                        if params.get("refresh"):
                            pool.explorer().cache.clear()
                            pool.explorer().column_cache.clear()
                        publish_context(params, metadata=True)
                    except Exception as exc:
                        key = "|".join(str(params.get(key) or "") for key in ("connection_id", "database", "schema")) or "default"
                        config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
                        send({"language_context": {"key": key, "variables": namespace_snapshot(namespace),
                              "connection_id": params.get("connection_id") or pool.default_id,
                              "database": params.get("database") or config.get("database", ""),
                              "schema_name": params.get("schema") or config.get("schema") or config.get("postgresql_schema") or config.get("databricks_schema") or "",
                              "schema": {}, "schema_complete": False, "metadata_state": "error",
                              "requested_scope": {field: params.get(field) for field in ("connection_id", "database", "schema")},
                              "schema_error": f"{type(exc).__name__}: {exc}"[:2048]}})
                    result = {"status": "updated"}
                elif method in {"data.import", "variable.inspect", "variable.delete", "result.export", "result.export_text", "result.summary", "result.chart", "result.chart_export", "result.export_table", "document.read", "document.script_export", "variable.archive.list", "variable.archive.export", "variable.archive.import"}:
                    from .data_tools import dispatch as data_dispatch
                    operation_id = params.get("operation_id")
                    def export_progress(update):
                        if operation_id:
                            emit("result.export_progress", {"session_id": session_id, "operation_id": operation_id, **update})
                    if method == "result.export_table":
                        previous_connector, previous_key, previous_context = connector, pool.active_key, context_key
                        connection_names = ("db_engine", "db_type", "db_database", "db_host", "db_username", "db_schema")
                        previous_variables = {name: namespace[name] for name in connection_names if name in namespace}
                        try:
                            routed = dict(params)
                            routed.pop("schema", None)
                            if params.get("connection_schema"):
                                routed["schema"] = params["connection_schema"]
                            activate(routed)
                            result = data_dispatch(method, params, namespace, store, connector=connector,
                                                   progress=export_progress, cancelled=export_cancel.is_set if export_cancel else None)
                            for key, explorer in pool.explorers.items():
                                if key[0] == pool.active_key[0]:
                                    explorer.cache.clear()
                                    explorer.column_cache.clear()
                            publish_context(invalidated=True)
                        finally:
                            connector, context_key = previous_connector, previous_context
                            pool.active_key = previous_key if previous_key in pool.items else None
                            for name in connection_names:
                                namespace.pop(name, None)
                            namespace.update(previous_variables)
                            if connector is not None and "db_engine" in previous_variables:
                                namespace["db_engine"] = connector.engine
                    elif method == "variable.inspect" and params.get("variable_name") == "__namespace__":
                        result = {"variables": describe_variables(namespace)}
                    else:
                        result = data_dispatch(method, params, namespace, store, connector=connector,
                                               progress=export_progress, cancelled=export_cancel.is_set if export_cancel else None)
                    if method in {"data.import", "variable.delete", "variable.archive.import"}:
                        snapshot_dirty = True
                        store.invalidate_views()
                        publish_context()
                elif method.startswith("notifications."):
                    from .notifications import dispatch as notification_dispatch, prepare
                    if method == "notifications.send":
                        send({"job_id": job_id, "notification_delivery": prepare(params, namespace, store)})
                        continue
                    result = notification_dispatch(method, params, namespace, store)
                elif method.startswith("snapshot."):
                    from .variable_snapshot import dispatch as snapshot_dispatch
                    result = snapshot_dispatch(method, params, namespace, store)
                    if method == "snapshot.save":
                        snapshot_dirty = False
                    if method == "snapshot.restore":
                        snapshot_dirty = False
                        store.invalidate_views()
                        emit("namespace.changed", {"session_id": session_id, **result})
                        publish_context()
                else:
                    raise ValueError(f"Unknown kernel method: {method}")
                send({"job_id": job_id, "result": result})
            except BaseException as exc:
                from .export_control import ExportCancelled
                send({"job_id": job_id, "error": {"code": "cancelled" if isinstance(exc, ExportCancelled) else "operation_failed", "message": f"{type(exc).__name__}: {exc}"}})
    finally:
        pool.disconnect()
        commands.close()
        events.close()
