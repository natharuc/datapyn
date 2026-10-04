"""Completion notifications retain execution identity without transport waits."""

from collections import OrderedDict
from copy import deepcopy
import threading
from types import SimpleNamespace

import pytest

from datapyn_runtime.supervisor import Job, SessionRuntime, Supervisor
from test_runtime import Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    value = Client()
    try:
        yield value
    finally:
        value.close()


def envelope(block_id, *, emit=True):
    return {"emit_notification": emit, "config": {"enabled": True, "title": "{{tab_name}}/{{block_name}}",
            "message": "{{rows}}/{{result[0][0]}}/{{marker}}/{{error}}"},
            "context": {"tab_name": "Analysis", "block_name": block_id, "block_id": block_id, "rows": 999}}


def test_consecutive_executions_capture_completion_before_next_job_changes_namespace(client):
    client.session()
    client.request("execution.run", {
        "session_id": "a", "execution_id": "first", "language": "python",
        "code": "marker = 'first'\ndf = pd.DataFrame({'value': [7]})\ndf", "notification": envelope("first-block"),
    })
    client.request("execution.run", {
        "session_id": "a", "execution_id": "second", "language": "python",
        "code": "marker = 'second'\ndf.iat[0,0] = 99\nimport time\ntime.sleep(.25)",
        "notification": envelope("second-block", emit=False),
    })
    first = client.event("execution.finished", execution_id="first")
    assert first["status"] == "succeeded"
    assert first["notification"]["title"] == "Analysis/first-block"
    assert first["notification"]["message"] == "1/7/first/"
    assert not any(key.startswith("_") for key in first["notification"])
    second = client.event("execution.finished", execution_id="second")
    assert second["status"] == "succeeded" and "notification" not in second
    assert first["notification"]["message"] == "1/7/first/"


def test_failure_on_intermediate_block_notifies_that_execution_without_stale_result(client):
    client.session()
    client.execute("pd.DataFrame({'old': [999]})", "older-result")
    finished = client.execute("marker = 'failed-block'\nraise ValueError('expected failure')", "failed",
                              notification=envelope("failed-block", emit=False))
    assert finished["status"] == "failed"
    response = finished["notification"]
    assert response["title"] == "Analysis/failed-block" and response["success"] is False
    assert response["message"].startswith("0/{{result[0][0]}}/failed-block/")
    assert "expected failure" in response["message"]
    printed = client.execute("marker = 'print-block'\nprint('no dataframe result')", "print-only",
                             notification=envelope("print-block"))
    assert printed["notification"]["message"] == "0/{{result[0][0]}}/print-block/"


def test_running_and_queued_cancellations_keep_block_identity_and_clear_message(client):
    client.session()
    client.request("execution.run", {
        "session_id": "a", "execution_id": "running", "language": "python", "code": "import time\ntime.sleep(20)",
        "notification": {"context": {"block_id": "running-block"}},
    })
    client.event("execution.started", execution_id="running")
    client.request("execution.run", {
        "session_id": "a", "execution_id": "queued", "language": "python", "code": "1",
        "notification": {"context": {"block_id": "queued-block"}, "emit_notification": False},
    })
    client.request("execution.cancel", {"session_id": "a", "execution_id": "queued"})
    queued = client.event("execution.finished", execution_id="queued")
    assert queued["status"] == "cancelled"
    assert queued["notification"]["message"] == "Execução cancelada."
    client.request("execution.cancel", {"session_id": "a", "execution_id": "running"})
    running = client.event("execution.finished", execution_id="running")
    assert running["status"] == "cancelled"
    assert running["notification"]["status"] == "cancelled"
    assert running["notification"]["title"] == "Execução cancelada"
    assert running["notification"]["message"] == "Execução cancelada."


def test_notification_uses_block_connection_and_database_not_frontend_defaults(client, tmp_path):
    client.session()
    source = client.request("connections.save", {"connection": {"name": "Default connection", "config": {
        "db_type": "sqlite", "database": str(tmp_path / "default.sqlite"),
    }}})
    target = client.request("connections.save", {"connection": {"name": "Block connection", "config": {
        "db_type": "sqlite", "database": str(tmp_path / "target.sqlite"),
    }}})
    client.request("connection.connect", {"session_id": "a", "connection_id": source["id"]})
    notification = {"config": {"enabled": True, "message": "{{connection}}/{{database}}"},
                    "context": {"connection": "Wrong frontend default", "database": "wrong-db", "workspace_id": "origin"}}
    finished = client.execute("SELECT 7 AS value", "specific-connection", language="sql", connection_id=target["id"], notification=notification)
    assert finished["status"] == "succeeded"
    assert finished["notification"]["message"] == f"Block connection/{tmp_path / 'target.sqlite'}"
    # A later execution returning to the default must retain that name rather
    # than reusing the previously activated block connection's label.
    finished = client.execute("SELECT 8 AS value", "default-connection", language="sql", notification=notification)
    assert finished["notification"]["message"] == f"Default connection/{tmp_path / 'default.sqlite'}"
    client.request("result.export_table", {"session_id": "a", "variable_name": "df", "table": "exported", "connection_id": target["id"]})
    finished = client.execute("SELECT 9 AS value", "default-after-export", language="sql", notification=notification)
    assert finished["notification"]["message"] == f"Default connection/{tmp_path / 'default.sqlite'}"
    client.session("no-connection")
    finished = client.execute("print('local Python')", "local-python", "no-connection", notification=notification)
    assert finished["notification"]["message"] == "Wrong frontend default/wrong-db"


def test_queue_result_explicit_success_frame_survives_print_only_final_block(client):
    client.session()
    first = client.execute("pd.DataFrame({'value': [7,8]})", "queue-first")
    # Another stored result must not replace the ID passed by this queue.
    client.execute("pd.DataFrame({'unrelated': [999]})", "unrelated")
    notification = envelope("last-block")
    notification["config"]["message"] = "{{rows}}/{{result[0][0]}}"
    notification["queue_result"] = {"result_id": first["results"][0]["result_id"], "rows": 2}
    finished = client.execute("print('done')", "queue-last", notification=notification)
    assert finished["notification"]["message"] == "2/7"
    finished = client.execute("raise ValueError('failed')", "queue-error", notification=notification)
    assert finished["notification"]["message"] == "0/{{result[0][0]}}"


def prepared_notification():
    return {"version": 1, "notification": {"enabled": True, "send_external": True, "channels": {"telegram": True, "email": False}},
            "_settings": {"recipient": "internal"}, "_secrets": {"telegram_bot_token": "private-secret"},
            "_completion_context": {"session_id": "a", "execution_id": "one", "block_id": "source-block", "workspace_id": "original-workspace"}}


def test_local_completion_precedes_slow_external_delivery_and_routes_only_safe_status():
    events, pending = [], []
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._emit = events.append
    supervisor._internal_lock = threading.RLock()
    supervisor._internal = {}
    supervisor._notification_deliveries = {}
    supervisor.background = SimpleNamespace(submit=lambda *args: pending.append(args))
    session = SessionRuntime.__new__(SessionRuntime)
    session._lock = threading.RLock()
    session._pending_reset = None
    session._states = OrderedDict()
    session.emit = supervisor._deliver
    session.deliver_notification = supervisor.deliver_notification
    session._active = Job("execution.run", {"execution_id": "one"})
    finished = {"session_id": "a", "execution_id": "one", "status": "succeeded", "notification": {"title": "Completed"}}
    session._receive({"event": "execution.finished", "payload": finished, "job_id": session._active.job_id,
                      "notification_delivery": prepared_notification()})
    assert events == [{"event": "execution.finished", "payload": finished}]
    assert session._active is None and pending
    # Delivery can finish arbitrarily later; the execution already completed.
    request_id, method, prepared, _ = pending[0]
    assert method == "notifications.deliver_prepared" and prepared["_secrets"]["telegram_bot_token"] == "private-secret"
    supervisor._deliver({"id": request_id, "result": {"deliveries": {"telegram": {"status": "sent"}}, "_secrets": "must-not-escape"}})
    assert events[-1] == {"event": "notifications.delivery_finished", "payload": {
        "session_id": "a", "execution_id": "one", "block_id": "source-block", "workspace_id": "original-workspace", "deliveries": {"telegram": {"status": "sent"}},
    }}
    assert not supervisor._notification_deliveries


def test_delivery_scheduler_failure_never_changes_local_execution():
    events = []
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._emit = events.append
    supervisor._internal_lock = threading.RLock()
    supervisor._internal = {}
    supervisor._notification_deliveries = {}
    def reject(*args):
        raise ValueError("queue full: private-secret")
    supervisor.background = SimpleNamespace(submit=reject)
    prepared = prepared_notification()
    supervisor.deliver_notification(None, prepared)
    assert events[-1]["event"] == "notifications.delivery_finished"
    assert events[-1]["payload"]["deliveries"] == {"telegram": {"status": "failed", "error": "Notification delivery failed"}}
    assert "private-secret" not in str(events)
    assert "_secrets" not in prepared and not supervisor._notification_deliveries


def test_explicit_send_keeps_original_rpc_delivery_contract():
    requests = []
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.background = SimpleNamespace(submit=lambda *args: requests.append(deepcopy(args)))
    prepared = prepared_notification()
    supervisor.deliver_notification(42, prepared)
    assert requests == [(42, "notifications.deliver_prepared", prepared, {})]
