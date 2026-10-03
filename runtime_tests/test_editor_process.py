"""Frozen-style persistent completion without executing the runtime as Python."""

import threading

import pytest

from datapyn_runtime.editor_process import CompletionProcess
from test_runtime import process_is_alive


def test_completion_worker_uses_main_thread_inference_and_reuses_process(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("DATAPYN_PACKAGES_PATH", str(tmp_path / "packages"))
    closed = threading.Event()
    worker = CompletionProcess(closed)
    try:
        dataframe = worker.request({"language": "python", "code": "df.", "line": 1, "column": 4},
                                   {"variables": {"df": {"type": "DataFrame", "columns": ["sample"]}}})
        assert "columns" in {item["label"] for item in dataframe["result"]["items"]}
        process = worker.process
        identifier = process.pid
        names = worker.request({"language": "python", "code": "names.", "line": 1, "column": 7},
                               {"variables": {"names": {"type": "list"}}})
        assert "append" in {item["label"] for item in names["result"]["items"]}
        assert worker.process is process
    finally:
        closed.set()
        worker.close()
    assert worker.process is None and process._closed
    assert not process_is_alive(identifier)
    with pytest.raises(RuntimeError, match="closing"):
        worker.request({"language": "python", "code": "df.", "line": 1, "column": 4}, {})


def test_completion_timeout_resets_worker_and_stale_request_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    closed = threading.Event()
    worker = CompletionProcess(closed)
    params = {"language": "python", "code": "df.", "line": 1, "column": 4}
    context = {"variables": {"df": {"type": "DataFrame"}}}
    try:
        assert worker.request(params, context, superseded=lambda: True)["result"]["superseded"]
        assert worker.process is None
        with pytest.raises(TimeoutError):
            worker.request(params, context, timeout=0.001)
        assert worker.process is None and worker.group is None
        assert "columns" in {item["label"] for item in worker.request(params, context)["result"]["items"]}
    finally:
        closed.set()
        worker.close()


def test_frozen_jedi_script_selects_embedded_interpreter_explicitly(monkeypatch):
    import jedi
    import datapyn_runtime.language as language
    captured = {}
    class Script:
        def __init__(self, code, **options):
            captured.update(options)
        def complete(self, line, column):
            return []
    monkeypatch.setattr(language, "_JEDI_ENVIRONMENT", None)
    monkeypatch.setattr(language.sys, "frozen", True, raising=False)
    monkeypatch.setattr(jedi, "Script", Script)
    assert language._python_complete("df.", 1, 3, {}) == []
    assert isinstance(captured["environment"], jedi.InterpreterEnvironment)
