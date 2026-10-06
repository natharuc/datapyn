"""SQL command feedback stays separate from stored frames and survives reset."""

from collections import OrderedDict
from types import SimpleNamespace
import threading

import pandas as pd
import pytest

from datapyn_runtime.database import SQLiteConnector
from datapyn_runtime.sql_commands import command_results
from datapyn_runtime.supervisor import Job, SessionRuntime
from test_runtime import client
from test_sql_execution_context import run_kernel_jobs


def feedback(index, command, rows=None):
    return {"statement_index": index, "command": command, "rows_affected": rows}


def connect(client, path=":memory:"):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})


def test_command_only_execution_does_not_create_frame_namespace_or_completion(client):
    connect(client)
    finished = client.execute("CREATE TABLE data(id INTEGER); INSERT INTO data VALUES (1),(2); UPDATE data SET id=id+1 WHERE id=99",
                              "commands", language="sql", variable_name="commands_df")
    assert finished["status"] == "succeeded", finished
    assert finished["command_results"] == [feedback(1, "CREATE"), feedback(2, "INSERT", 2), feedback(3, "UPDATE", 0)]
    assert finished["results"] == []
    assert "commands_df" not in {item["name"] for item in finished["variables"]}
    check = client.execute("assert 'commands_df' not in globals(); assert 'df' not in globals()", "namespace")
    assert check["status"] == "succeeded" and check["command_results"] == []
    completion = client.request("language.complete", {"session_id": "a", "language": "python", "code": "commands_d", "line": 1, "column": 11})
    assert "commands_df" not in {item["label"] for item in completion["items"]}


def test_commands_preserve_existing_dataframe_and_its_handle(client):
    connect(client)
    previous = client.execute("SELECT 37 AS value", "previous", language="sql")
    finished = client.execute("CREATE TABLE data(id INTEGER)", "command", language="sql")
    assert finished["results"] == [] and finished["command_results"] == [feedback(1, "CREATE")]
    assert client.page(previous)["rows"] == [[37]]
    current = client.execute("assert df.value.tolist() == [37]; df", "python")
    assert client.page(current)["rows"] == [[37]]


def test_mixed_script_keeps_only_data_frames_and_contiguous_variable_names(client):
    connect(client)
    finished = client.execute("CREATE TABLE data(id INTEGER); INSERT INTO data VALUES (7),(8); "
                              "SELECT * FROM data; UPDATE data SET id=id+1; SELECT * FROM data",
                              "mixed", language="sql", variable_name="rows")
    assert finished["command_results"] == [feedback(1, "CREATE"), feedback(2, "INSERT", 2), feedback(4, "UPDATE", 2)]
    assert [item["variable_name"] for item in finished["results"]] == ["rows", "rows1"]
    assert client.page(finished)["rows"] == [[7], [8]]
    second = client.request("result.page", {"session_id": "a", "result_id": finished["results"][1]["result_id"]})
    assert second["rows"] == [[8], [9]]


def test_legitimate_result_column_and_success_text_remain_tabular(client):
    connect(client)
    finished = client.execute("SELECT 'Command(s) executed successfully.' AS Result", "real-result", language="sql")
    assert finished["command_results"] == []
    assert client.page(finished)["rows"] == [["Command(s) executed successfully."]]
    assert finished["results"][0]["columns"][0]["name"] == "Result"


def test_returning_is_tabular_and_has_command_feedback(client):
    connect(client)
    client.execute("CREATE TABLE data(id INTEGER)", "create", language="sql")
    finished = client.execute("INSERT INTO data VALUES(7),(8) RETURNING id", "returning", language="sql")
    assert finished["command_results"] == [feedback(1, "INSERT", 2)]
    assert client.page(finished)["rows"] == [[7], [8]]
    updated = client.execute("WITH picked AS (SELECT id FROM data) UPDATE data SET id=id+1 WHERE id IN (SELECT id FROM picked) RETURNING id",
                             "cte-returning", language="sql")
    assert updated["command_results"] == [feedback(1, "UPDATE")]
    assert client.page(updated)["rows"] == [[8], [9]]


def test_failure_preserves_completed_commands_without_retry_or_stale_feedback(client):
    connect(client)
    finished = client.execute("CREATE TABLE data(id INTEGER); INSERT INTO data VALUES(7); SELECT * FROM missing",
                              "failed", language="sql")
    assert finished["status"] == "failed"
    assert finished["command_results"] == [feedback(1, "CREATE"), feedback(2, "INSERT", 1)]
    assert finished["results"] == []
    # The adapter's rollback behavior remains intact: feedback is not a commit.
    next_sql = client.execute("SELECT count(*) AS value FROM data", "after-failure", language="sql")
    assert next_sql["command_results"] == [] and client.page(next_sql)["rows"] == [[0]]
    next_python = client.execute("print('ready')", "after-sql")
    assert next_python["command_results"] == []


def test_hard_cancel_keeps_completed_commands_from_kernel_reader(client, tmp_path):
    connect(client, tmp_path / "cancel.sqlite")
    client.execute("CREATE TABLE data(id INTEGER)", "create", language="sql")
    installed = client.execute(
        "import time\n"
        "def wait_after_insert():\n"
        "    print('sql-is-waiting', flush=True)\n"
        "    time.sleep(30)\n"
        "    return 1\n"
        "db_engine.raw_connection().driver_connection.create_function('wait_after_insert', 0, wait_after_insert)", "install")
    assert installed["status"] == "succeeded", installed
    client.request("execution.run", {"session_id": "a", "execution_id": "cancelled", "language": "sql",
                   "code": "INSERT INTO data VALUES (7); SELECT wait_after_insert()"})
    client.wait(lambda message: message.get("event") == "execution.output"
                and message["payload"].get("execution_id") == "cancelled"
                and "sql-is-waiting" in message["payload"].get("text", ""))
    client.request("execution.cancel", {"session_id": "a", "execution_id": "cancelled"})
    finished = client.event("execution.finished", "cancelled")
    assert finished["status"] == "cancelled"
    assert finished["command_results"] == [feedback(1, "INSERT", 1)]
    client.event("session.reset", session_id="a")
    client.event("session.ready", session_id="a")
    events = [message["event"] for message in client.all_messages if message.get("event") in {"execution.finished", "session.reset"}
              and (message["event"] == "session.reset" or message["payload"].get("execution_id") == "cancelled")]
    assert events == ["execution.finished", "session.reset"]


def test_sqlite_metadata_is_defensive_and_comments_are_not_commands():
    connector = SQLiteConnector(":memory:")
    try:
        frame = connector.execute_query("-- just a comment\n /* nothing to run */")
        assert frame.attrs["datapyn_command_result"] is True
        assert frame.attrs["datapyn_command_results"] == []
        connector.execute_query("CREATE TABLE data(id INTEGER); INSERT INTO data VALUES(1)")
        snapshot = connector.get_last_command_results()
        snapshot[0]["command"] = "mutated"
        assert connector.get_last_command_results() == [feedback(1, "CREATE"), feedback(2, "INSERT", 1)]
    finally:
        connector.disconnect()


@pytest.mark.parametrize("tag", [False, "true", 1])
def test_only_explicit_true_frame_tag_is_removed(tag, monkeypatch, tmp_path):
    marker = pd.DataFrame({"Result": ["Command(s) executed successfully."]})
    marker.attrs["datapyn_command_result"] = tag
    marker.attrs["datapyn_command_results"] = [feedback(1, "UPDATE", 0)]
    connector = SimpleNamespace(db_type="mysql", engine=None, connection_params={"database": "before"},
                                execute_query=lambda *args, **kwargs: marker)
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "ignored by fake connector"}])
    finished = next(message["payload"] for message in messages if message.get("event") == "execution.finished")
    assert finished["status"] == "succeeded", finished
    assert len(finished["results"]) == 1 and finished["command_results"] == [feedback(1, "UPDATE", 0)]


def test_tagged_frames_are_skipped_before_naming_real_results(monkeypatch, tmp_path):
    marker = pd.DataFrame({"Result": ["Command executed successfully."]})
    marker.attrs.update(datapyn_command_result=True, datapyn_command_results=[feedback(1, "UPDATE", 1)])
    values = [marker, pd.DataFrame({"value": [7]}), marker, pd.DataFrame({"value": [8]})]
    connector = SimpleNamespace(db_type="mysql", engine=None, connection_params={"database": "before"},
                                execute_query=lambda *args, **kwargs: values)
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "ignored by fake connector", "variable_name": "data"}])
    finished = next(message["payload"] for message in messages if message.get("event") == "execution.finished")
    assert finished["command_results"] == [feedback(1, "UPDATE", 1)]
    assert [result["variable_name"] for result in finished["results"]] == ["data", "data1"]
    contexts = [message["language_context"]["variables"] for message in messages if "language_context" in message]
    assert contexts[-1]["data"]["columns"] == ["value"]


def session_stub():
    session = SessionRuntime.__new__(SessionRuntime)
    session.session_id = "session"
    session._lock = threading.RLock()
    session._states = OrderedDict()
    session._pending_reset = None
    session._active = Job("execution.run", {"execution_id": "running"})
    session.deliver_notification = None
    return session


def test_reader_captures_only_matching_execution_even_when_reset_is_pending(monkeypatch):
    session = session_stub()
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args: None)
    messages = []
    session.emit = messages.append
    active = session._active
    session._pending_reset = ("cancelled", active, [])
    session._receive({"command_result": feedback(1, "UPDATE", 0), "job_id": active.job_id})
    session._receive({"command_result": feedback(2, "DELETE", 9), "job_id": "stale-job"})
    session._receive({"command_result": {"statement_index": 0}, "job_id": active.job_id})
    assert active.command_results == [feedback(1, "UPDATE", 0)]
    session._finish_interrupted(active, "cancelled", "cancelled")
    queued = Job("execution.run", {"execution_id": "queued"})
    session._finish_interrupted(queued, "cancelled", "queued")
    assert messages[0]["payload"]["command_results"] == [feedback(1, "UPDATE", 0)]
    assert messages[1]["payload"]["command_results"] == []


def test_command_metadata_is_wire_safe_and_copied():
    import numpy as np

    raw = [feedback(np.int64(2), "UPDATE", np.int64(0)), feedback(1, "CREATE", -1), {"statement_index": True, "command": "invalid"}]
    normalized = command_results(raw)
    assert normalized == [feedback(1, "CREATE"), feedback(2, "UPDATE", 0)]
    assert type(normalized[1]["rows_affected"]) is int
    normalized[0]["command"] = "mutated"
    assert raw[1]["command"] == "CREATE"
