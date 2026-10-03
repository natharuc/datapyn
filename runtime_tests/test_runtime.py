"""Exercise the shipped stdio process, not a mock dispatcher or Qt fixture."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "source"), PYTHONIOENCODING="utf-8")
        env.pop("DATAPYN_RUNTIME_TRACE", None)
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "datapyn_runtime"], cwd=ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.messages = queue.Queue()
        self.pending = []
        self.all_messages = []
        self.diagnostics = []
        self.sequence = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        threading.Thread(target=self._read_errors, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    message = {"invalid_protocol": line}
                self.all_messages.append(message)
                self.messages.put(message)
        finally:
            self.messages.put({"eof": True})

    def _read_errors(self):
        for line in self.process.stderr:
            self.diagnostics.append(line)

    def wait(self, predicate, timeout=20):
        for index, message in enumerate(self.pending):
            if predicate(message):
                return self.pending.pop(index)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            assert "invalid_protocol" not in message, message
            assert not message.get("eof"), self.diagnostics
            if predicate(message):
                return message
            self.pending.append(message)
        raise AssertionError(f"Protocol timeout; stderr={self.diagnostics}, pending={self.pending}")

    def response(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        return self.wait(lambda item: item.get("id") == request_id)

    def request(self, method, params=None):
        response = self.response(method, params)
        assert "error" not in response, response
        return response["result"]

    def event(self, name, execution_id=None, session_id=None):
        return self.wait(lambda item: item.get("event") == name
                         and (execution_id is None or item["payload"].get("execution_id") == execution_id)
                         and (session_id is None or item["payload"].get("session_id") == session_id))["payload"]

    def session(self, name="a"):
        self.request("session.create", {"session_id": name})
        # This wait leaves the real supervisor blocked on protocol stdin. It
        # reproduces the Windows spawn-bootstrap regression without a GUI.
        self.event("session.ready", session_id=name)
        return name

    def execute(self, code, execution_id="one", session_id="a", language="python", **options):
        self.request("execution.run", {
            "session_id": session_id, "execution_id": execution_id,
            "language": language, "code": code, **options,
        })
        return self.event("execution.finished", execution_id=execution_id, session_id=session_id)

    def page(self, finished, session_id="a", **options):
        assert finished["status"] == "succeeded", finished
        return self.request("result.page", {
            "session_id": session_id, "result_id": finished["results"][0]["result_id"],
            "offset": 0, "limit": 100, **options,
        })

    def output(self, execution_id, stream="stdout"):
        return "".join(message["payload"]["text"] for message in self.all_messages
                       if message.get("event") == "execution.output"
                       and message["payload"]["execution_id"] == execution_id
                       and message["payload"]["stream"] == stream)

    def close(self):
        if self.process.poll() is None:
            try:
                self.request("system.shutdown")
                self.process.wait(timeout=10)
            except (AssertionError, OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


@pytest.fixture
def client():
    value = Client()
    try:
        yield value
    finally:
        value.close()


def test_protocol_validation_and_qt_free_dependencies(client):
    info = client.request("system.info")
    assert info["protocol_version"] == 1
    assert info["capabilities"]["qt_required"] is False
    client.process.stdin.write("not json\n")
    client.process.stdin.flush()
    assert client.wait(lambda item: item.get("id") is None)["error"]["code"] == "parse_error"
    assert client.response("unknown.method")["error"]["code"] == "method_not_found"
    assert client.response("execution.run", {"session_id": "absent"})["error"]["code"] == "unknown_session"
    client.session()
    finished = client.execute(
        "import sys, importlib.abc\n"
        "class NoQt(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname.startswith(('PyQt6', 'qtawesome', 'qt_material')):\n"
        "            raise ImportError('Qt dependency in runtime: ' + fullname)\n"
        "sys.meta_path.insert(0, NoQt())\n"
        "from src.database.database_connector import DatabaseConnector\n"
        "pd.DataFrame({'qt_loaded': [any(name.startswith('PyQt6') for name in sys.modules)]})"
    )
    assert client.page(finished)["rows"] == [[False]]


def test_sql_python_namespace_schema_and_multi_result_names(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    sql = client.execute(
        "CREATE TABLE sample (value INTEGER, label TEXT); INSERT INTO sample VALUES (1,'Alpha'),(2,'beta'); "
        "SELECT * FROM sample; SELECT 3 AS next_value", language="sql", variable_name="df",
    )
    assert [result["variable_name"] for result in sql["results"]] == ["df", "df1"]
    assert client.page(sql)["rows"] == [[1, "Alpha"], [2, "beta"]]
    schema = client.request("schema.get", {"session_id": "a"})
    assert schema["tables"][0]["columns"][0]["name"] == "value"
    python = client.execute(
        "total = int(df.value.sum()) + int(df1.next_value.iloc[0])\n"
        "pd.read_sql('SELECT value FROM sample', db_engine).assign(total=total)", "two",
    )
    assert client.page(python)["rows"] == [[1, 6], [2, 6]]
    assert any(variable["name"] == "total" for variable in python["variables"])
    assert client.execute("raise ValueError('expected')", "three")["status"] == "failed"
    assert client.page(client.execute("pd.DataFrame({'total':[total]})", "four"))["rows"] == [[6]]


def test_pagination_sort_filters_precision_and_polars(client):
    client.session()
    finished = client.execute(
        "from decimal import Decimal\n"
        "pd.DataFrame({'name':['Alpha','beta','Gamma'], 'n':[3,1,2], "
        "'large':[2**60]*3, 'amount':[Decimal('1.234567890123456789')]*3, 'missing':[None]*3})"
    )
    page = client.page(finished, offset=1, limit=1, sort={"column": "n", "direction": "desc"})
    assert page["total_rows"] == 3 and page["offset"] == 1
    assert page["rows"] == [["Gamma", 2, str(2**60), "1.234567890123456789", None]]
    assert client.page(finished, filter={"text": "BETA"})["rows"][0][0] == "beta"
    assert client.page(finished, filter={"column": "n", "operator": "gt", "value": 2})["total_rows"] == 1
    assert client.response("result.page", {"session_id": "a", "result_id": finished["results"][0]["result_id"], "limit": 1001})["error"]
    polars = client.execute("pl.DataFrame({'v':[4,5]})", "polars")
    assert client.page(polars)["rows"] == [[4], [5]]


def test_output_isolation_bound_and_concurrent_sessions(client):
    client.session("a")
    client.session("b")
    client.request("execution.run", {
        "session_id": "a", "execution_id": "output-a", "language": "python",
        "code": "import time\nfor i in range(10):\n    print('ONLY_A', flush=True)\n    time.sleep(.03)\n",
    })
    client.event("execution.started", "output-a")
    b = client.execute(
        "import os, subprocess, sys\n"
        "os.write(1, b'NATIVE_MUST_NOT_BE_PROTOCOL\\n')\n"
        "os.write(2, b'NATIVE_ERROR\\n')\n"
        "subprocess.run([sys.executable, '-c', \"print('SUBPROCESS_MUST_NOT_BE_PROTOCOL')\"])\n"
        "try:\n    input()\nexcept EOFError:\n    print('INPUT_EOF')\n"
        "print('ONLY_B')\nprint('stderr_B', file=sys.stderr)\n"
        "pd.DataFrame({'v':[22]})", "output-b", "b",
    )
    assert client.page(b, "b")["rows"] == [[22]]
    assert client.event("execution.finished", "output-a")["status"] == "succeeded"
    assert "ONLY_A" in client.output("output-a") and "ONLY_B" not in client.output("output-a")
    assert "ONLY_B" in client.output("output-b") and "ONLY_A" not in client.output("output-b")
    assert "INPUT_EOF" in client.output("output-b")
    assert "stderr_B" in client.output("output-b", "stderr")
    bounded = client.execute("print('x'*800000)", "bounded")
    assert bounded["status"] == "succeeded"
    assert len(client.output("bounded").encode()) <= 256 * 1024
    assert "truncated" in client.output("bounded", "stderr")
    assert not any("invalid_protocol" in item for item in client.all_messages)


def test_numeric_column_labels_and_ambiguous_labels(client):
    client.session()
    numeric = client.execute("numbers = pd.DataFrame([[3,'c'],[1,'a'],[2,'b']]); numbers")
    sorted_page = client.page(numeric, sort={"column": "0", "direction": "asc"})
    assert sorted_page["rows"] == [[1, "a"], [2, "b"], [3, "c"]]
    assert client.page(numeric, filter={"column": "1", "operator": "contains", "value": "B"})["rows"] == [[2, "b"]]
    # Resolution must not rename columns in the persistent Python namespace.
    assert client.page(client.execute("pd.DataFrame({'label':[type(numbers.columns[0]).__name__]})", "label"))["rows"][0][0] in {"int", "int64"}
    ambiguous = client.execute("pd.DataFrame([[1,2]], columns=[0,'0'])", "ambiguous")
    response = client.response("result.page", {
        "session_id": "a", "result_id": ambiguous["results"][0]["result_id"],
        "sort": {"column": "0", "direction": "asc"},
    })
    assert "Ambiguous column name" in response["error"]["message"]
    assert client.page(ambiguous)["rows"] == [[1, 2]]


def test_cancel_restart_queue_and_other_session_survives(client):
    client.session("a")
    client.session("b")
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    client.execute("preserved = 42", "preserve", "b")
    client.request("execution.run", {"session_id": "a", "execution_id": "loop", "language": "python", "code": "while True:\n    pass"})
    client.event("execution.started", "loop")
    client.request("execution.run", {"session_id": "a", "execution_id": "queued", "language": "python", "code": "print('should not run')"})
    assert client.request("execution.cancel", {"session_id": "a", "execution_id": "loop"})["status"] == "cancelling"
    assert client.event("execution.finished", "loop")["status"] == "cancelled"
    assert client.event("execution.finished", "queued")["status"] == "cancelled"
    reset = client.event("session.reset", session_id="a")
    assert reset["namespace_lost"] and reset["connection_lost"]
    recovered = client.execute("pd.DataFrame({'v':[7]})", "recovered")
    assert client.page(recovered)["rows"] == [[7]]
    disconnected = client.execute("SELECT 1", "must-reconnect", language="sql")
    assert disconnected["status"] == "failed" and "Connect this session" in disconnected["error"]
    other = client.execute("pd.DataFrame({'v':[preserved]})", "still-alive", "b")
    assert client.page(other, "b")["rows"] == [[42]]


def test_cancel_kills_user_subprocess_and_preserves_other_kernel(client):
    client.session("a")
    client.session("b")
    pid_result = client.execute(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "pd.DataFrame({'pid':[child.pid]})", "child",
    )
    child_pid = client.page(pid_result)["rows"][0][0]
    assert process_is_alive(child_pid)
    other_pid = client.page(client.execute("import os; pd.DataFrame({'pid':[os.getpid()]})", "other", "b"), "b")["rows"][0][0]
    client.request("execution.run", {"session_id": "a", "execution_id": "loop", "language": "python", "code": "while True:\n    pass"})
    client.event("execution.started", "loop")
    client.request("execution.cancel", {"session_id": "a", "execution_id": "loop"})
    client.event("session.reset", session_id="a")
    wait_for_process_exit(child_pid)
    assert process_is_alive(other_pid)
    assert client.page(client.execute("pd.DataFrame({'v':[1]})", "other-reused", "b"), "b")["rows"] == [[1]]


@pytest.mark.skipif(os.name != "nt", reason="Windows nested Job Object integration")
def test_nested_windows_job_allows_independent_kernel_reset(client, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "source"))
    from datapyn_runtime.process_group import WindowsJobGroup

    outer = WindowsJobGroup(client.process.pid)
    try:
        test_cancel_kills_user_subprocess_and_preserves_other_kernel(client)
    finally:
        client.close()
        outer.close()


def test_worker_crash_recovers_and_workspace_preserves_unknown_fields(client, tmp_path):
    client.session()
    child = client.execute(
        "import subprocess, sys; child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
        "pd.DataFrame({'pid':[child.pid]})", "child",
    )
    child_pid = client.page(child)["rows"][0][0]
    assert process_is_alive(child_pid)
    client.request("execution.run", {"session_id": "a", "execution_id": "crash", "language": "python", "code": "import os; os._exit(9)"})
    assert client.event("execution.finished", "crash")["status"] == "failed"
    assert client.event("session.reset", session_id="a")["reason"] == "worker_crashed"
    wait_for_process_exit(child_pid)
    assert client.page(client.execute("pd.DataFrame({'v':[9]})", "recovered"))["rows"] == [[9]]
    document = {"version": "1.0", "tabs": [{"name": "Sessão á", "blocks": [{"language": "sql", "code": "SELECT 1"}]}], "unknown": {"keep": True}}
    path = str(tmp_path / "sample.dpw")
    client.request("workspace.write", {"path": path, "document": document})
    assert client.request("workspace.read", {"path": path})["document"] == document


def process_is_alive(pid):
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            return kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(handle)
    try:
        # A dead orphan may remain a zombie until container PID1 reaps it.
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().rsplit(")", 1)[1].strip().startswith("Z"):
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def wait_for_process_exit(pid):
    deadline = time.monotonic() + 5
    while process_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(.05)
    assert not process_is_alive(pid)


@pytest.mark.parametrize("shutdown", ["eof", "terminate"])
def test_process_cleanup_without_orphan_kernel(client, shutdown):
    client.session()
    finished = client.execute("import os; pd.DataFrame({'pid':[os.getpid()]})")
    kernel_pid = client.page(finished)["rows"][0][0]
    assert process_is_alive(kernel_pid)
    child = client.execute(
        "import subprocess, sys; child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
        "pd.DataFrame({'pid':[child.pid]})", "child",
    )
    child_pid = client.page(child)["rows"][0][0]
    assert process_is_alive(child_pid)
    client.request("execution.run", {"session_id": "a", "execution_id": "loop", "language": "python", "code": "while True:\n    pass"})
    client.event("execution.started", "loop")
    if shutdown == "eof":
        client.process.stdin.close()
    else:
        client.process.terminate()
    client.process.wait(timeout=10)
    wait_for_process_exit(kernel_pid)
    wait_for_process_exit(child_pid)
