from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time

import pytest

from datapyn_runtime.pynia import PyniaService
from datapyn_runtime.supervisor import Supervisor

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "helpers" / "fake_acp_agent.py"


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "workspace"))
        monkeypatch.setenv("PYTHONPATH", str(ROOT / "source"))
        self.messages = queue.Queue()
        self.pending = []
        self.runtime = Supervisor(self.messages.put)
        self.runtime.pynia.launch_resolver = lambda spec: (sys.executable, [str(FAKE)])
        self.sequence = 0
        self.request("session.create", {"session_id": "a"})
        self.event("session.ready")

    def wait(self, predicate):
        for index, message in enumerate(self.pending):
            if predicate(message):
                return self.pending.pop(index)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if predicate(message):
                return message
            self.pending.append(message)
        raise AssertionError(self.pending)

    def request(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.runtime.receive({"id": request_id, "method": method, "params": params or {}})
        response = self.wait(lambda message: message.get("id") == request_id)
        assert "error" not in response, response
        return response["result"]

    def event(self, event):
        return self.wait(lambda message: message.get("event") == event)["payload"]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    harness = Harness(tmp_path, monkeypatch)
    yield harness
    harness.runtime.close()


def prepare(harness):
    harness.request("pynia.select_agent", {"session_id": "a", "agent_id": "claude"})
    harness.wait(lambda message: message.get("event") == "pynia.state" and message["payload"]["state"]["selectors"]["model"].get("values"))


def test_real_acp_stdio_streaming_thinking_permissions_config_and_durable_history(harness):
    prepare(harness)
    state = harness.request("pynia.state", {"session_id": "a"})
    assert state["selectors"]["model"]["current"] == "auto"
    harness.request("pynia.config", {"session_id": "a", "config_id": "model", "value": "sonnet", "kind": "model"})
    harness.wait(lambda message: message.get("event") == "pynia.state" and message["payload"]["state"]["selectors"]["model"]["current"] == "sonnet")
    harness.request("pynia.prompt", {"session_id": "a", "text": "think pong ask-permission", "context": {"blocks": [{"name": "sample", "language": "python", "code": "x=1"}]}})
    assert harness.event("pynia.chunk")["text"] == "pong"
    assert harness.event("pynia.thinking")["text"] == "hmm"
    permission = harness.event("pynia.permission")
    assert permission["params"]["toolCall"]["kind"] == "delete"
    harness.request("pynia.answer_permission", {"session_id": "a", "request_id": permission["request_id"], "option_id": "reject-once"})
    harness.event("pynia.turn_ended")
    state = harness.request("pynia.state", {"session_id": "a"})
    assert state["locked"] and not state["busy"]
    assert state["messages"][-1]["content"] == "pong"
    assert state["messages"][-1]["activity"]["thinking"] == "hmm"
    path = harness.runtime.pynia._path("a")
    assert json.loads(path.read_text())["messages"][-1]["content"] == "pong"
    blocked = []
    harness.runtime.receive({"id": 999, "method": "pynia.select_agent", "params": {"session_id": "a", "agent_id": "codex"}})
    assert harness.wait(lambda message: message.get("id") == 999)["error"]
    harness.request("pynia.clear", {"session_id": "a"})
    assert not harness.request("pynia.state", {"session_id": "a"})["locked"]


def test_mcp_tools_execute_actual_session_sql_python_and_page_results(harness):
    prepare(harness)
    harness.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    service = harness.runtime.pynia
    result = service._tool("a", "datapyn_query", {"language": "sql", "code": "CREATE TABLE sample(value INTEGER); INSERT INTO sample VALUES (17); SELECT * FROM sample"})
    assert result["results"][0]["rows"] == [[17]]
    result = service._tool("a", "datapyn_query", {"language": "python", "code": "df.assign(doubled=df.value * 2)"})
    assert result["results"][0]["rows"] == [[17, 34]]
    variables = service._tool("a", "datapyn_snapshot", {"action": "variables"})
    assert "df" in {variable["name"] for variable in variables["variables"]}
    details = service._tool("a", "datapyn_database", {"operation": "describe", "table_name": "sample", "schema_name": "main"})
    assert details["columns"][0]["name"] == "value"
    # Silent probes must never create phantom editor execution events.
    assert not any(message.get("event", "").startswith("execution.") for message in harness.pending)


def test_mcp_frontend_reply_and_authenticated_socket(harness):
    prepare(harness)
    service = harness.runtime.pynia
    results = []
    thread = threading.Thread(target=lambda: results.append(service._tool("a", "datapyn_edit", {"operation": "rename", "new_name": "renamed"})))
    thread.start()
    request = harness.event("pynia.tool_request")
    assert request["name"] == "datapyn_edit"
    harness.request("pynia.tool_reply", {"request_id": request["request_id"], "result": {"renamed": True}})
    thread.join(timeout=2)
    assert results == [{"renamed": True}]
    bridge = service.mcp
    with socket.create_connection(("127.0.0.1", bridge.port)) as client:
        client.sendall((json.dumps({"token": bridge.token, "tab_id": "a"}) + "\n").encode())
        client.sendall(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
        result = json.loads(client.makefile("rb").readline())
        assert len(result["result"]["tools"]) == 9
    with socket.create_connection(("127.0.0.1", bridge.port)) as client:
        client.sendall(b'{"token":"wrong","tab_id":"a"}\n')
        client.settimeout(2)
        assert client.recv(10) == b""


def test_inline_completion_has_its_own_acp_session(harness):
    prepare(harness)
    result = harness.request("pynia.inline", {"session_id": "a", "body": "pd.<CURSOR>", "timeout": 4})
    assert result["text"] == "ghost_text"
    state = harness.request("pynia.state", {"session_id": "a"})
    assert state["completion_session_id"] != state["acp_session_id"]
    assert not state["messages"]


def test_new_acp_services_import_without_qt():
    env = dict(os.environ, PYTHONPATH=str(ROOT / "source"))
    result = subprocess.run([sys.executable, "-c", "import sys; import datapyn_runtime.pynia; from src.services.pynia.acp.client_transport import AcpTransport; assert not any(m.startswith('PyQt6') for m in sys.modules)"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_kernel_event_reader_is_replaced_on_cancel_and_joined_on_close(harness):
    session = harness.runtime.sessions["a"]
    original_reader = session._event_reader
    harness.request("execution.run", {"session_id": "a", "execution_id": "reader-reset", "language": "python",
                                     "code": "import time; time.sleep(10)"})
    harness.event("execution.started")
    harness.request("execution.cancel", {"session_id": "a", "execution_id": "reader-reset"})
    assert harness.event("execution.finished")["status"] == "cancelled"
    harness.event("session.reset")
    harness.event("session.ready")
    assert not original_reader.is_alive()
    current_reader = session._event_reader
    assert current_reader is not original_reader and current_reader.is_alive()
    harness.request("session.close", {"session_id": "a"})
    assert not current_reader.is_alive() and not session._thread.is_alive()
