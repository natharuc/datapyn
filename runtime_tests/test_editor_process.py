"""Frozen-style persistent completion without executing the runtime as Python."""

import threading
from types import SimpleNamespace

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


@pytest.mark.parametrize("ready,broken_write,exitcode,expected", [
    (False, False, 75, "initialization (exit code 75)"),
    (True, False, -1073741819, "inference (exit code 0xC0000005)"),
    (True, True, 9, "inference (exit code 9)"),
    (True, False, 0, "inference (exit code 0)"),
])
def test_unexpected_worker_exit_reports_stage_and_native_code_without_retry(monkeypatch, ready, broken_write, exitcode, expected):
    worker = CompletionProcess(threading.Event())
    worker.ready = ready
    joins, starts, stops = [], [], []
    process = SimpleNamespace(join=lambda **options: joins.append(options), exitcode=exitcode)
    def receive():
        raise EOFError
    def send(request):
        if broken_write:
            raise BrokenPipeError
    pipe = SimpleNamespace(poll=lambda timeout: True, recv=receive, send=send)
    def start():
        starts.append(True)
        return process, pipe
    monkeypatch.setattr(worker, "_start", start)
    monkeypatch.setattr(worker, "_stop", lambda: stops.append(True))
    response = worker.request({"code": "df."}, {})
    assert response["error"]["code"] == "editor_unavailable"
    assert expected in response["error"]["message"]
    assert "EOFError" not in response["error"]["message"]
    assert len(starts) == len(stops) == 1, "A failed request must not silently retry"
    assert joins == [{"timeout": 0.1}]
    # A later, explicit user request can initialize a new interpreter normally.
    worker.ready = False
    messages = iter([{"ready": True}, {"result": {"items": [{"label": "columns"}]}}])
    pipe.recv = lambda: next(messages)
    pipe.send = lambda request: None
    assert worker.request({"code": "df."}, {})["result"]["items"] == [{"label": "columns"}]
    assert len(starts) == 2 and len(stops) == 1


def test_editor_reports_bootstrap_failure_before_stdio_and_imports(monkeypatch):
    import datapyn_runtime.editor_process as editor
    def fail():
        raise RuntimeError("owned bootstrap failed")
    monkeypatch.setattr(editor, "initialize_kernel_group", fail)
    messages, closed = [], []
    editor._editor_main(SimpleNamespace(send=messages.append, close=lambda: closed.append(True)))
    assert closed == [True]
    assert messages == [{"error": {"code": "editor_unavailable", "message": "Python autocomplete initialization: RuntimeError: owned bootstrap failed"}}]
