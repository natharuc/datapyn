"""A persistent interpreter owned by one session, with no UI objects or Qt."""

from __future__ import annotations

import ast
import base64
from collections import OrderedDict
import io
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

from . import database
from .values import describe_variables, preview, scalar
from .stdio import isolate_kernel_output
from .process_group import initialize_kernel_group, exit_kernel_and_children

MAX_OUTPUT_BYTES = 256 * 1024
MAX_PAGE_ROWS = 1000
MAX_RESULT_HANDLES = 64


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


class ResultStore:
    """Only the kernel owns DataFrames; the wire exposes opaque handles."""

    def __init__(self, pd, pl):
        self.pd = pd
        self.pl = pl
        self.frames: OrderedDict[str, object] = OrderedDict()

    def is_frame(self, value):
        return isinstance(value, (self.pd.DataFrame, self.pl.DataFrame, self.pd.Series, self.pl.Series))

    def register(self, value, variable_name: str) -> dict:
        if isinstance(value, self.pd.Series):
            value = value.to_frame()
        elif isinstance(value, self.pl.Series):
            value = value.to_frame().to_pandas()
        elif isinstance(value, self.pl.DataFrame):
            value = value.to_pandas()
        result_id = uuid.uuid4().hex
        self.frames[result_id] = value
        while len(self.frames) > MAX_RESULT_HANDLES:
            self.frames.popitem(last=False)
        return {
            "result_id": result_id,
            "variable_name": variable_name,
            "columns": [{"name": str(column), "dtype": str(dtype)} for column, dtype in zip(value.columns, value.dtypes)],
            "row_count": len(value),
        }

    @staticmethod
    def column_label(frame, wire_name):
        """Map string DTO names to the original label without mutating a frame."""
        if not isinstance(wire_name, str):
            raise ValueError("column must be its string name from the result descriptor")
        matches = [label for label in frame.columns if str(label) == wire_name]
        if not matches:
            raise ValueError(f"Unknown column: {wire_name}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous column name: {wire_name}; duplicate names cannot be sorted or filtered by name")
        return matches[0]

    def page(self, params: dict):
        result_id = params["result_id"]
        if result_id not in self.frames:
            raise KeyError("Result is unavailable; it may have been released or the kernel restarted")
        frame = self.frames[result_id]
        offset = params.get("offset", 0)
        limit = params.get("limit", 100)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_ROWS:
            raise ValueError("limit must be between 1 and 1000")
        filter_spec = params.get("filter") or {}
        if filter_spec:
            if not isinstance(filter_spec, dict):
                raise ValueError("filter must be an object")
            if "text" in filter_spec:
                text = str(filter_spec["text"])
                if len(text) > 1000:
                    raise ValueError("filter text exceeds 1000 characters")
                mask = self.pd.Series(False, index=frame.index)
                for index in range(len(frame.columns)):
                    mask |= frame.iloc[:, index].astype("string").str.contains(text, case=False, regex=False, na=False)
                frame = frame.loc[mask]
            elif "column" in filter_spec:
                column = self.column_label(frame, filter_spec["column"])
                series = frame[column]
                operator = filter_spec.get("operator", "contains")
                value = filter_spec.get("value", "")
                if operator == "contains":
                    mask = series.astype("string").str.contains(str(value), case=False, regex=False, na=False)
                elif operator == "equals":
                    mask = series.isna() if value is None else series.eq(value)
                elif operator == "gt":
                    mask = series.gt(value)
                elif operator == "lt":
                    mask = series.lt(value)
                else:
                    raise ValueError(f"Unsupported filter operator: {operator}")
                frame = frame.loc[mask]
        sort = params.get("sort") or {}
        if sort:
            if not isinstance(sort, dict):
                raise ValueError("sort must be an object")
            column = self.column_label(frame, sort.get("column"))
            direction = sort.get("direction", "asc")
            if direction not in {"asc", "desc"}:
                raise ValueError("sort direction must be asc or desc")
            frame = frame.sort_values(column, ascending=direction == "asc", kind="mergesort", na_position="last")
        rows = [[scalar(value) for value in row] for row in frame.iloc[offset : offset + limit].itertuples(index=False, name=None)]
        return {
            "columns": [{"name": str(column), "dtype": str(dtype)} for column, dtype in zip(frame.columns, frame.dtypes)],
            "rows": rows,
            "total_rows": len(frame),
            "offset": offset,
        }


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


def kernel_main(session_id: str, commands, events):
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

    import numpy as np
    import pandas as pd
    import polars as pl

    namespace = {"pd": pd, "np": np, "pl": pl}
    store = ResultStore(pd, pl)
    connector = None
    send({"ready": True})
    try:
        while True:
            try:
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
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = CapturedStream(capture, "stdout"), CapturedStream(capture, "stderr")
                results, rich_outputs, error = [], [], None
                try:
                    before = {name: id(value) for name, value in namespace.items() if store.is_frame(value)}
                    if params["language"] == "sql":
                        if connector is None:
                            raise ConnectionError("Connect this session to a database first")
                        value = connector.execute_query(params["code"], parameters=params.get("parameters"))
                        values = value if isinstance(value, list) else [value]
                        for index, frame in enumerate(values):
                            name = params.get("variable_name") or "df"
                            if index:
                                name = f"{name}{index}"
                            namespace[name] = frame
                            if store.is_frame(frame):
                                results.append(store.register(frame, name))
                    else:
                        value = execute_python(params["code"], namespace, f"<datapyn:{execution_id}>")
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
                            print(preview(value, limit=8192))
                    rich_outputs = capture_figures()
                except BaseException:
                    error = traceback.format_exc()[-32_768:]
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
                    capture.close()
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
                send({"event": "execution.finished", "payload": payload, "job_id": job_id})
                continue
            try:
                if method == "connection.connect":
                    new_connector = database.connect(params["config"])
                    if connector is not None:
                        connector.disconnect()
                    connector = new_connector
                    namespace.update({
                        "db_engine": connector.engine,
                        "db_type": connector.db_type,
                        "db_database": connector.connection_params.get("database", ""),
                        "db_host": connector.connection_params.get("host", ""),
                        "db_username": connector.connection_params.get("username", ""),
                    })
                    result = {"status": "connected", "db_type": connector.db_type}
                elif method == "schema.get":
                    result = database.schema(connector)
                elif method == "result.page":
                    result = store.page(params)
                else:
                    raise ValueError(f"Unknown kernel method: {method}")
                send({"job_id": job_id, "result": result})
            except BaseException as exc:
                send({"job_id": job_id, "error": {"code": "operation_failed", "message": f"{type(exc).__name__}: {exc}"}})
    finally:
        if connector is not None:
            connector.disconnect()
        commands.close()
        events.close()
