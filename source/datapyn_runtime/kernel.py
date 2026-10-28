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
import types

from . import database
from .paths import workspace_root
from .values import describe_variables, preview, scalar
from .stdio import isolate_kernel_output
from .process_group import initialize_kernel_group, exit_kernel_and_children
from .language import namespace_snapshot
from .desktop_services import enable_user_packages
from .rich_outputs import RichOutputs
from .sql_commands import command_result, command_results as normalized_commands, frame_command_results, is_command_frame
from .transaction_settings import editor_context_key, context_automatic_transactions
from .sql_safety_guard import require_kernel_review, require_query_review, guard_python_engines

MAX_OUTPUT_BYTES = 256 * 1024
from .result_store import ResultStore, MAX_PAGE_ROWS, MAX_RESULT_HANDLES


def python_uses_database(code, namespace=None):
    """Local DataFrame work must remain available while a database is offline."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    nodes = list(ast.walk(tree))
    if any(isinstance(node, ast.Name) and node.id == "db_engine" for node in nodes):
        return True
    # A legacy DataFrame/user function called sql is ordinary Python. New local
    # definitions can still call the managed helper lazily before replacing it.
    shadows_sql = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "sql"
                      or isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "sql" for node in nodes)
    existing = (namespace or {}).get("sql")
    managed = existing is None or type(existing) is types.FunctionType and existing.__dict__.get("_datapyn_sql_helper") is True
    return managed and not shadows_sql and any(isinstance(node, ast.Name) and node.id == "sql" for node in nodes)


def connection_loss_error(error):
    """SQLAlchemy can wrap a managed engine's transport error in DBAPIError."""
    from src.database.connection_recovery import ConnectionLostError
    from .errors import safe_exception_attribute
    pending, seen = [error], set()
    while pending and len(seen) < 12:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ConnectionLostError):
            return current
        # An exception handled by user/library fallback code is not the cause
        # of the new failure. Only explicit wrappers/causes retain ownership.
        pending.extend((safe_exception_attribute(current, "orig"), safe_exception_attribute(current, "__cause__")))
    return None


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


def kernel_main(session_id: str, commands, events, idle_timeout=300, export_cancel=None, import_cancel=None):
    initialize_kernel_group()
    # C extensions, os.write() and child subprocesses must never inherit the
    # NDJSON protocol descriptors. Python print() is streamed separately below.
    isolate_kernel_output()
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("DATAPYN_SHARED_PARAMETER_DELIMITER", "{{name}}")
    os.environ.setdefault("DATAPYN_WORKSPACE_PATH", str(workspace_root()))
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
    context_params = {}
    connection_labels = {}
    snapshot_dirty = False

    def recovery_event(outcome, params):
        config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
        event = {"session_id": session_id, **outcome,
                 "automatic_transactions": context_automatic_transactions(params),
                 "requested_scope": {field: params.get(field) for field in ("connection_id", "database", "schema")}}
        if params.get("block_id"):
            event["block_id"] = params["block_id"]
        if params.get("scope_inherited") is True:
            event["scope_inherited"] = True
        if config.get("db_type"):
            event["db_type"] = config["db_type"]
        emit("connection.recovery", event)
        if outcome["phase"] == "ready":
            send({"language_context": {"key": editor_context_key(params), "variables": namespace_snapshot(namespace),
                  "connection_id": params.get("connection_id") or pool.default_id,
                  "block_id": params.get("block_id"), "scope_inherited": params.get("scope_inherited") is True,
                  "automatic_transactions": context_automatic_transactions(params),
                  "db_type": config.get("db_type", ""), "database": params.get("database") or config.get("database", ""),
                  "schema_name": params.get("schema") if params.get("schema") is not None else config.get("schema", ""),
                  "requested_scope": {field: params.get(field) for field in ("connection_id", "database", "schema")},
                  "schema": {}, "metadata_invalidated": True,
                  "metadata_invalidation_scope": "connection" if context_automatic_transactions(params) else "block"}})

    pool.on_recovery = recovery_event

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

    def publish_safety_context():
        from .connection_catalog import without_secrets
        config = pool.configs.get(pool.active_key, {}) if pool.active_key else {}
        config = pool._normalized_config(config) if config else {}
        safe = without_secrets({field: value for field, value in config.items()
                                if not field.startswith("_") and field != "automatic_transactions"})
        send({"sql_safety_context": {"config": safe,
              "connection_id": pool.active_key[0] if pool.active_key else None,
              "connection_name": connection_labels.get(pool.active_key)}})

    def activate(params, *, default=False, validate=False):
        nonlocal connector, context_key, context_params
        connector = pool.activate(params, default=default, validate=validate)
        config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
        name = params.get("_connection_name") or config.get("name")
        if name:
            connection_labels[pool.active_key] = str(name)
        for key in list(connection_labels):
            if key not in pool.items:
                del connection_labels[key]
        context_key = editor_context_key(params)
        context_params = dict(params)
        # This in-memory snapshot never opens a connection or reads credentials.
        # It identifies the fallback target even if a later metadata read fails.
        publish_safety_context()
        resolved = pool.explorer().context()
        namespace.update({
            "db_engine": connector.engine, "db_type": connector.db_type,
            "db_database": resolved["database"],
            "db_host": connector.connection_params.get("host", ""),
            "db_username": connector.connection_params.get("username", ""),
            "db_schema": resolved["schema"],
        })
        return connector

    def publish_context(params=None, *, metadata=False, invalidated=False, invalidation_scope="connection", namespace_only=False):
        publish_safety_context()
        params = context_params if params is None else params
        key = editor_context_key(params) if namespace_only else context_key
        context = {"key": key, "variables": namespace_snapshot(namespace), "connection_id": pool.active_key[0] if pool.active_key else None,
                   "automatic_transactions": context_automatic_transactions(params)}
        if namespace_only:
            context["connection_id"] = params.get("connection_id") or pool.default_id
        if params.get("block_id"):
            context["block_id"] = params["block_id"]
        if params.get("scope_inherited"):
            context["scope_inherited"] = True
        if connector is not None and not namespace_only:
            context["automatic_transactions"] = getattr(connector, "automatic_transactions", True)
            resolved = pool.explorer().context()
            context.update(db_type=resolved["db_type"], database=resolved["database"], schema_name=resolved["schema"],
                           requested_scope={field: params.get(field) for field in ("connection_id", "database", "schema")})
        if invalidated:
            context.update({"schema": {}, "metadata_invalidated": True, "metadata_invalidation_scope": invalidation_scope})
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
            # The UI can request completion as soon as restored data appears.
            # Publish its immutable columns before announcing availability.
            publish_context()
            emit("namespace.changed", {"session_id": session_id, **restored})
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
                        publish_safety_context()
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
                from .transaction_settings import effective_automatic_transactions
                params = dict(params)
                params["automatic_transactions"] = params.get("_automatic_transactions_snapshot")
                if params["automatic_transactions"] is None:
                    params["automatic_transactions"] = effective_automatic_transactions(job["params"])
                if params.get("block_id") or params["automatic_transactions"] is False:
                    params["_execution_scope_id"] = str(params.get("block_id") or "__session__")
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
                error_info = None
                connection_error = None
                pool.last_recovery = None
                command_results = []
                execution_connection = None
                executing_connector = None
                previous_affinity = pool.block_affinity.get(str(params.get("_execution_scope_id") or ""))
                previous_connector = pool.items.get(previous_affinity)
                physical_scope_changed = False
                sql_helper_scope = {"active": True}
                managed_sql_queries = []
                previous_context = None
                previous_search_path = None
                sql_scope_changed = False
                rich_capture.begin()
                from .errors import suppress_internal_console_logs
                diagnostic_logging = suppress_internal_console_logs()
                diagnostic_logging.__enter__()
                try:
                    safety_config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
                    safety_enabled, safety_authorized = require_kernel_review("execution.run", params, safety_config.get("db_type", ""))
                    before = {name: id(value) for name, value in namespace.items() if store.is_frame(value)}
                    uses_database = params["language"] == "sql" or python_uses_database(params["code"], namespace)
                    if uses_database and (params.get("connection_id") or params.get("_connection_config") or params.get("config")
                            or pool.default_config is not None or connector is not None):
                        activate(params, default=bool(params.get("scope_inherited")), validate=True)
                    if connector is not None and uses_database:
                        executing_connector = connector
                        physical_scope_changed = previous_connector is not None and previous_connector is not connector
                        previous_context = pool.explorer().context()
                        previous_search_path = connector.connection_params.get("postgresql_search_path")
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
                            def command_completed(value):
                                result = command_result(value)
                                if result is not None:
                                    command_results.append(result)
                                    send({"command_result": result, "job_id": job_id})

                            previous_callback = getattr(connector, "command_result_callback", None)
                            connector.command_result_callback = command_completed
                            try:
                                value = connector.execute_query(params["code"], parameters=parameters or None,
                                                                automatic_transactions=params["automatic_transactions"])
                            finally:
                                # Read before metadata probes can execute another SQL
                                # statement and replace the connector's snapshot.
                                getter = getattr(connector, "get_last_command_results", None)
                                if callable(getter):
                                    command_results = normalized_commands(getter())
                                connector.command_result_callback = previous_callback
                            values = value if isinstance(value, list) else [value]
                            metadata = frame_command_results(values)
                            if metadata is not None:
                                command_results = metadata
                            for index, frame in enumerate(frame for frame in values if not is_command_frame(frame)):
                                name = params.get("variable_name") or "df"
                                if index:
                                    name = f"{name}{index}"
                                namespace[name] = frame
                                if store.is_frame(frame):
                                    results.append(store.register(frame, name))
                    else:
                        enable_user_packages()
                        def make_sql_helper(target, mode, scope):
                            def run_sql(query, parameters=None):
                                nonlocal command_results, target, executing_connector, previous_context
                                if not scope["active"]:
                                    raise ConnectionError("Use sql() from the currently executing block")
                                if target is None:
                                    target = activate(params, default=bool(params.get("scope_inherited")), validate=True)
                                    executing_connector = target
                                    previous_context = pool.explorer().context()
                                require_query_review(query, safety_enabled, safety_authorized, target.db_type)
                                from .sql_commands import command_results as normalize_results, is_command_frame
                                if isinstance(query, str):
                                    managed_sql_queries.append(query)
                                try:
                                    value = target.execute_query(query, parameters=parameters, automatic_transactions=mode)
                                finally:
                                    feedback = getattr(target, "get_last_command_results", None)
                                    if callable(feedback):
                                        command_results.extend(normalize_results(feedback()))
                                if is_command_frame(value):
                                    return None
                                return value
                            return run_sql
                        previous_sql = namespace.get("sql")
                        if "sql" not in namespace or (type(previous_sql) is types.FunctionType and previous_sql.__dict__.get("_datapyn_sql_helper") is True):
                            helper = make_sql_helper(executing_connector, params["automatic_transactions"], sql_helper_scope)
                            helper._datapyn_sql_helper = True
                            namespace["sql"] = helper
                        code = params["code"]
                        if params.get("shared_parameters"):
                            from src.utils.sql_parameter_service import prepare_python_code_with_shared_parameters
                            code = prepare_python_code_with_shared_parameters(code, params["shared_parameters"])
                        with guard_python_engines(safety_enabled, safety_authorized):
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
                except BaseException as exc:
                    lost_error = connection_loss_error(exc)
                    if lost_error is not None:
                        owner = getattr(lost_error, "_datapyn_connector", None)
                        if any(owner is item for item in pool.items.values()):
                            executing_connector = owner
                        exc = lost_error
                    from .errors import exception_code
                    code = exception_code(exc)
                    if code == "transaction_pending":
                        affinity = pool.block_affinity.get(str(params.get("_execution_scope_id") or ""))
                        executing_connector = pool.items.get(affinity)
                    from .errors import serialize_runtime_error, error_summary
                    formatted = serialize_runtime_error(exc, language=params["language"])
                    error_info = formatted["error_info"]
                    error = formatted["message"]
                    if isinstance(code, str) and code.startswith(("ssh_", "transaction_", "destructive_sql_", "connection_lost", "connection_unavailable")):
                        connection_error = formatted
                        if code == "ssh_host_key_unknown":
                            error_info["message"] = (error_info["message"] + " Abra o cadastro da conexão e use Testar conexão para conferir e confirmar a fingerprint SSH.")[:8192]
                            error = error_summary(error_info)
                finally:
                    sql_helper_scope["active"] = False
                    diagnostic_logging.__exit__(None, None, None)
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
                    "command_results": command_results,
                    "variables": describe_variables(namespace),
                    "automatic_transactions": params["automatic_transactions"],
                }
                transaction_connector = executing_connector
                if executing_connector is not None and executing_connector.db_type in {"sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite"}:
                    payload["db_type"] = executing_connector.db_type
                if params.get("block_id"):
                    payload["block_id"] = params["block_id"]
                if "scope_inherited" in params:
                    payload["scope_inherited"] = params["scope_inherited"] is True
                if error:
                    payload["error"] = error
                    payload["error_info"] = error_info
                if connection_error:
                    payload["error_code"] = connection_error["code"]
                    payload["error_details"] = connection_error.get("details", {})
                    if connection_error["code"] in {"connection_lost", "connection_unavailable"}:
                        payload["connection_lost"] = True
                if error and executing_connector is not None:
                    affected = next((key for key, item in pool.items.items() if item is executing_connector), None)
                    lost = pool.recovery_state(executing_connector, pool.configs.get(affected, {}))
                    if lost:
                        payload["connection_lost"] = True
                        # Repair the transport for the NEXT command. The failed
                        # job remains failed, including SQL that may have run.
                        try:
                            if affected is not None:
                                replacement = pool._recover_key(affected, params)
                                transaction_connector = replacement
                                replacement_key = next(key for key, item in pool.items.items() if item is replacement)
                                if replacement_key != affected and affected in connection_labels:
                                    connection_labels[replacement_key] = connection_labels.pop(affected)
                                if connector is executing_connector:
                                    connector = replacement
                                    namespace["db_engine"] = replacement.engine
                                    publish_safety_context()
                        except Exception:
                            pass
                if pool.last_recovery:
                    payload["connection_recovery"] = dict(pool.last_recovery)
                    if error and pool.last_recovery.get("session_state_lost") is True:
                        # A failed preflight may report an SSH trust/auth error
                        # before assigning executing_connector. It still lost
                        # a cached transport, so clients must retain old grids.
                        payload["connection_lost"] = True
                    if (error_info and error_info["category"] == "network"
                            and pool.last_recovery.get("phase") == "ready"):
                        # The failed command stays failed, but recovery has
                        # already completed; asking to reconnect is now stale.
                        error_info["title"] = "Execução interrompida"
                        error_info["message"] = "A conexão foi restabelecida. A execução interrompida não foi repetida."
                        if (connection_error or {}).get("details", {}).get("submitted") is True:
                            error_info["message"] += " Confira seu resultado antes de executar novamente."
                        from .errors import error_summary
                        error = payload["error"] = error_summary(error_info)
                # Recovery events arrive before this terminal event. Reading
                # the dead connector here would overwrite the new idle state
                # with "unknown" and leave the UI blocked after reconnecting.
                transaction_state = pool._transaction_snapshot(transaction_connector)
                if transaction_state is not None:
                    payload["transaction_state"] = transaction_state
                elif callable(getattr(transaction_connector, "get_transaction_state", None)):
                    payload["transaction_state"] = {"automatic_transactions": params["automatic_transactions"],
                                                    "pending": None, "state": "unknown"}
                if rich_outputs:
                    payload["rich_outputs"] = rich_outputs
                if download_result is not None:
                    payload["export"] = download_result
                if (params["language"] == "sql" or managed_sql_queries) and previous_context is not None and connector is not None:
                    current_context = pool.explorer().context()
                    sql_scope_changed = current_context != previous_context or (connector.db_type == "postgresql" and connector.connection_params.get("postgresql_search_path") != previous_search_path)
                    if current_context != previous_context:
                        identifier = pool.active_key[0] if pool.active_key else pool.default_id
                        payload["context_change"] = {
                            "previous": previous_context, "current": current_context,
                            "connection_id": None if identifier == "transient" else identifier,
                            "requested_scope": {field: params.get(field) for field in ("connection_id", "database", "schema")},
                        }
                    if sql_scope_changed:
                        old_key = pool.active_key
                        pool.reindex_active(current_context, params)
                        if old_key in connection_labels:
                            connection_labels[pool.active_key] = connection_labels.pop(old_key)
                        namespace.update(db_database=current_context["database"], db_schema=current_context["schema"])
                        identifier = pool.active_key[0] if pool.active_key else pool.default_id
                        context_key = editor_context_key({**params, "connection_id": None if identifier == "transient" else identifier,
                                                          "database": current_context["database"], "schema": current_context["schema"]})
                # A failed block may have partially changed a frame in place.
                # Keep the previous durable generation until a later success.
                snapshot_dirty = error is None
                metadata_code = params["code"] if params["language"] == "sql" else "\n".join(managed_sql_queries)
                temporary_metadata_changed = False
                if metadata_code and executing_connector is connector and getattr(connector, "automatic_transactions", True) is False:
                    refresh = getattr(pool.explorer(), "refresh_sql_temporaries", None)
                    if callable(refresh):
                        try:
                            temporary_metadata_changed = refresh(metadata_code, force=error is not None)
                        except Exception as exc:
                            emit("language.refresh_failed", {"session_id": session_id, "block_id": params.get("block_id"), "error": type(exc).__name__})
                # All blocks share this interpreter's namespace. Publish its
                # immutable names/types/columns before clients observe the
                # completed execution, without waiting for database metadata.
                if params["language"] == "python" and (executing_connector is None or executing_connector is not connector):
                    publish_context(params, namespace_only=True)
                elif connector is None or executing_connector is connector:
                    publish_context(params)
                from .notifications import capture_completion
                notification = capture_completion(params, payload, namespace, store, connection_context=execution_connection)
                send({"event": "execution.finished", "payload": payload, "job_id": job_id,
                      **({"notification_delivery": notification} if notification is not None else {})})
                from .sql_context import changes_metadata
                invalidated = executing_connector is not None and executing_connector is connector and (physical_scope_changed or bool(metadata_code) and (sql_scope_changed or temporary_metadata_changed or changes_metadata(metadata_code)))
                if invalidated:
                    from .table_export import refresh_temporary_tables
                    pool.explorer().cache.clear()
                    pool.explorer().column_cache.clear()
                    try:
                        if changes_metadata(metadata_code):
                            refresh_temporary_tables(connector)
                        publish_context(params, invalidated=True, invalidation_scope="connection" if changes_metadata(metadata_code) else "block")
                    except Exception as exc:
                        emit("language.refresh_failed", {"session_id": session_id, "block_id": params.get("block_id"), "error": str(exc)[:2048]})
                continue
            try:
                if method == "connection.connect":
                    activate(params, default=True)
                    from .connection_catalog import without_secrets
                    resolved = pool.explorer().context()
                    safe_config = without_secrets({**(pool.default_config or {}), **resolved})
                    result = {"status": "connected", "connection_id": params.get("connection_id"), "config": safe_config, **resolved}
                    publish_context()
                elif method == "connection.recover":
                    outcome = pool.recover(params)
                    connector = pool.active
                    if connector is not None and outcome["phase"] == "ready":
                        context_key = editor_context_key(params)
                        context_params = dict(params)
                        name = params.get("_connection_name")
                        if name:
                            connection_labels[pool.active_key] = str(name)
                        resolved = pool.explorer().context()
                        namespace.update(db_engine=connector.engine, db_type=connector.db_type,
                                         db_database=resolved["database"], db_schema=resolved["schema"],
                                         db_host=connector.connection_params.get("host", ""),
                                         db_username=connector.connection_params.get("username", ""))
                        publish_context(params, invalidated=True, invalidation_scope="block")
                        from .connection_catalog import without_secrets
                        result = {**outcome, **resolved, "config": without_secrets({**(pool.configs.get(pool.active_key) or {}), **resolved})}
                    else:
                        result = outcome
                elif method == "connection.disconnect":
                    pool.disconnect(params.get("connection_id"))
                    connector = pool.active
                    publish_safety_context()
                    if connector is None:
                        for name in ("db_engine", "db_type", "db_database", "db_host", "db_username", "db_schema"):
                            namespace.pop(name, None)
                    result = {"status": "disconnected", "connection_id": params.get("connection_id")}
                elif method == "connection.idle_timeout":
                    pool.idle_timeout = params["seconds"]
                    result = {"seconds": pool.idle_timeout}
                elif method == "schema.get":
                    activate({**params, "_metadata_scope": True})
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
                    if method == "explorer.use_database":
                        affinity = pool.block_affinity.get(str(params.get("block_id") or ""))
                        owner = pool.items.get(affinity)
                        if owner is not None and database.pending_transaction(owner):
                            from .explorer import ObjectExplorer
                            current = ObjectExplorer(owner).context()
                            changed = (routed.get("connection_id") not in {None, affinity[0]}
                                       or routed.get("database") not in {None, "", current["database"]}
                                       or routed.get("schema") not in {None, current["schema"]})
                            if changed:
                                raise database.PendingTransactionError()
                    else:
                        routed["_metadata_scope"] = True
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
                        activate({**params, "_metadata_scope": True})
                        if params.get("refresh"):
                            pool.explorer().cache.clear()
                            pool.explorer().column_cache.clear()
                        publish_context(params, metadata=True)
                    except Exception as exc:
                        key = editor_context_key(params)
                        config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
                        send({"language_context": {"key": key, "variables": namespace_snapshot(namespace),
                              "connection_id": params.get("connection_id") or pool.default_id,
                              "database": params.get("database") or config.get("database", ""),
                              "schema_name": params.get("schema") or config.get("schema") or config.get("postgresql_schema") or config.get("databricks_schema") or "",
                              "schema": {}, "schema_complete": False, "metadata_state": "error",
                              "requested_scope": {field: params.get(field) for field in ("connection_id", "database", "schema")},
                              "block_id": params.get("block_id"),
                              "scope_inherited": params.get("scope_inherited") is True,
                              "automatic_transactions": context_automatic_transactions(params),
                              "schema_error": f"{type(exc).__name__}: {exc}"[:2048]}})
                    result = {"status": "updated"}
                elif method in {"data.import", "variable.inspect", "variable.delete", "result.export", "result.export_text", "result.summary", "result.chart", "result.chart_export", "result.export_table", "document.read", "document.script_export", "variable.archive.list", "variable.archive.export", "variable.archive.import"}:
                    from .data_tools import dispatch as data_dispatch
                    operation_id = params.get("operation_id")
                    def export_progress(update):
                        if operation_id:
                            event = "data.import_progress" if method == "data.import" else "result.export_progress"
                            emit(event, {"session_id": session_id, "operation_id": operation_id, **update})
                    if method == "result.export_table":
                        safety_config = params.get("_connection_config") or params.get("config") or pool.default_config or {}
                        require_kernel_review(method, params, safety_config.get("db_type", ""))
                        previous_connector, previous_key, previous_context = connector, pool.active_key, context_key
                        previous_context_params = context_params
                        connection_names = ("db_engine", "db_type", "db_database", "db_host", "db_username", "db_schema")
                        previous_variables = {name: namespace[name] for name in connection_names if name in namespace}
                        destination_activated = False
                        try:
                            routed = dict(params)
                            routed["automatic_transactions"] = params.get("_automatic_transactions_snapshot", True)
                            routed["_execution_scope_id"] = str(params.get("block_id") or "__session__")
                            routed.pop("schema", None)
                            if params.get("connection_schema"):
                                routed["schema"] = params["connection_schema"]
                            activate(routed)
                            destination_activated = True
                            result = data_dispatch(method, params, namespace, store, connector=connector,
                                                   progress=export_progress, cancelled=export_cancel.is_set if export_cancel else None)
                        finally:
                            try:
                                if destination_activated:
                                    # CREATE can persist even when a later INSERT
                                    # fails/cancels. Refresh the destination before
                                    # restoring the editor's connection context.
                                    for key, explorer in pool.explorers.items():
                                        if key[0] == pool.active_key[0]:
                                            explorer.cache.clear()
                                            explorer.column_cache.clear()
                                    publish_context(invalidated=True)
                            finally:
                                connector, context_key = previous_connector, previous_context
                                context_params = previous_context_params
                                pool.active_key = previous_key if previous_key in pool.items else None
                                for name in connection_names:
                                    namespace.pop(name, None)
                                namespace.update(previous_variables)
                                if connector is not None and "db_engine" in previous_variables:
                                    namespace["db_engine"] = connector.engine
                                publish_safety_context()
                    elif method == "variable.inspect" and params.get("variable_name") == "__namespace__":
                        result = {"variables": describe_variables(namespace)}
                    else:
                        cancellation = import_cancel if method == "data.import" else export_cancel
                        result = data_dispatch(method, params, namespace, store, connector=connector,
                                               progress=export_progress, cancelled=cancellation.is_set if cancellation else None)
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
                        publish_context()
                        emit("namespace.changed", {"session_id": session_id, **result})
                else:
                    raise ValueError(f"Unknown kernel method: {method}")
                send({"job_id": job_id, "result": result})
            except BaseException as exc:
                from .export_control import ExportCancelled
                from .errors import serialize_runtime_error
                send({"job_id": job_id, "error": serialize_runtime_error(exc, default_code="cancelled" if isinstance(exc, ExportCancelled) else "operation_failed")})
    finally:
        pool.disconnect()
        commands.close()
        events.close()
