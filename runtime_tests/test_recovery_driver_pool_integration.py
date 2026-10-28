"""Real pool/connector/SQLAlchemy regressions with an in-memory ODBC driver.

Only the DBAPI transport and process isolation hooks are replaced. No sockets,
credentials, native windows or production databases are used by these tests.
"""

from copy import deepcopy
from types import SimpleNamespace

import pyodbc
import pytest

from datapyn_runtime import database, kernel
from src.database.connection_recovery import ConnectionLostError
from src.database.database_connector import DatabaseConnector
from test_transaction_driver import OdbcConnection, OdbcCursor, odbc  # noqa: F401


def target(automatic=False):
    return {
        "connection_id": "fixture-saved",
        "block_id": "analysis",
        "_execution_scope_id": "analysis",
        "scope_inherited": True,
        "automatic_transactions": automatic,
        "database": "ESIM",
        "schema": "dbo",
        "config": {
            "db_type": "sqlserver", "host": "fixture.invalid", "port": 1433,
            "database": "ESIM", "schema": "dbo", "username": "fixture",
            "password": "fixture", "driver": "ODBC Driver 18 for SQL Server",
        },
    }


@pytest.fixture
def pool(odbc):
    value = database.ConnectorPool()
    try:
        yield value
    finally:
        value.disconnect()


def fail_statement(monkeypatch, statement, raw=None):
    original = OdbcCursor.execute

    def execute(cursor, sql, *parameters):
        value = original(cursor, sql, *parameters)
        if sql == statement and (raw is None or cursor.connection is raw):
            raise pyodbc.OperationalError("08S01", "synthetic link failure")
        return value

    monkeypatch.setattr(OdbcCursor, "execute", execute)


def commands(opened, statement):
    return sum(sql == statement for raw in opened for sql, _mode in raw.commands)


def test_idle_manual_select_failure_recovers_on_the_next_activation_without_ack_or_replay(pool, odbc, monkeypatch):
    request = target()
    previous = pool.activate(request, default=True, validate=True)
    assert isinstance(previous, DatabaseConnector)
    raw = previous._manual_raw_conn
    statement = "SELECT TOP 100 * FROM VW_U21_A_SALF"
    fail_statement(monkeypatch, statement, raw)
    events = []
    pool.on_recovery = lambda outcome, scope: events.append((outcome, scope))

    with pytest.raises(ConnectionLostError) as caught:
        previous.execute_query(statement)
    assert caught.value.details["submitted"] is True
    assert caught.value.details["acknowledgement_required"] is False
    assert previous.get_transaction_state()["state"] == "unknown"

    replacement = pool.activate(request, validate=True)
    assert replacement is not previous and isinstance(replacement, DatabaseConnector)
    assert [event[0]["phase"] for event in events] == ["recovering", "ready"]
    ready = events[-1][0]
    assert ready["acknowledgement_required"] is False
    assert ready["state_loss_acknowledged"] is False
    assert ready["transaction_state"]["pending"] is False
    assert ready["transaction_state"]["state"] == "idle"
    assert raw.closed == 1 and raw.commits == raw.rollbacks == 0
    assert replacement.connection_params["database"] == "ESIM"
    assert replacement.connection_params["schema"] == "dbo"
    assert replacement.execute_query("SELECT 42 AS next_execution").iloc[0, 0] == 1
    assert commands(odbc, statement) == 1
    assert commands(odbc, "SELECT 42 AS next_execution") == 1


def test_real_manual_begin_transaction_still_blocks_automatic_replacement(pool, odbc, monkeypatch):
    request = target()
    previous = pool.activate(request, default=True)
    raw = previous._manual_raw_conn
    previous.execute_query("BEGIN TRANSACTION")
    assert previous.get_transaction_state()["pending"] is True
    statement = "SELECT TOP 100 * FROM report_in_transaction"
    fail_statement(monkeypatch, statement, raw)
    opened_before = len(odbc)

    with pytest.raises(ConnectionLostError) as caught:
        previous.execute_query(statement)
    assert caught.value.details["acknowledgement_required"] is True
    with pytest.raises(ConnectionLostError):
        pool.activate(request, validate=True)
    assert pool.last_recovery["phase"] == "blocked"
    assert len(odbc) == opened_before and pool.active is previous
    assert (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
    assert commands(odbc, statement) == 1

    outcome = pool.recover({**request, "acknowledge_state_loss": True})
    assert outcome["phase"] == "ready" and outcome["state_loss_acknowledged"] is True
    assert outcome["transaction_state"]["pending"] is False
    assert pool.active is not previous and raw.closed == 1
    assert commands(odbc, statement) == 1


@pytest.mark.parametrize("automatic", [False, True], ids=["manual", "automatic"])
@pytest.mark.parametrize("stage", ["statement", "rollback"])
def test_metadata_socket_failure_does_not_poison_the_real_pool_lane(pool, odbc, monkeypatch, automatic, stage):
    request = target(automatic)
    connector = pool.activate(request, default=True)
    retained = connector._manual_raw_conn
    if not automatic:
        connector.execute_query("BEGIN TRANSACTION")
    statement = "SELECT 3 AS metadata_fixture"
    if stage == "statement":
        fail_statement(monkeypatch, statement)
    else:
        original = OdbcConnection.rollback

        def rollback(raw):
            if getattr(raw, "fail_metadata_rollback", False):
                raw.fail_metadata_rollback = False
                raise pyodbc.OperationalError("08S01", "synthetic metadata rollback failure")
            return original(raw)

        monkeypatch.setattr(OdbcConnection, "rollback", rollback)

    with pytest.raises(Exception):
        with connector.engine.connect() as connection:
            connection.exec_driver_sql(statement)
            if stage == "rollback":
                connection.connection.driver_connection.fail_metadata_rollback = True

    assert connector.get_connection_recovery_state() is None
    assert pool.last_recovery is None
    assert pool.activate(request, validate=True) is connector
    assert connector.get_connection_recovery_state() is None
    assert connector.execute_query("SELECT 42 AS independent_execution").iloc[0, 0] == 1
    assert commands(odbc, statement) == 1
    if not automatic:
        assert connector._manual_raw_conn is retained
        assert retained.transaction_count == 1
        assert (retained.commits, retained.rollbacks, retained.closed) == (0, 0, 0)


def test_real_kernel_driver_pool_publishes_replacement_idle_state_and_preserves_python_data(odbc, monkeypatch, tmp_path):
    """Exercise the actual terminal payload rather than a fake connector state."""
    for method in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, method, lambda: None)
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.sql_safety_guard.settings_get", lambda *args: {"confirm_destructive_sql": False})
    statement = "SELECT TOP 100 * FROM kernel_report"
    fail_statement(monkeypatch, statement)
    request = {**target(), "_automatic_transactions_snapshot": False}
    jobs = [
        {"method": "connection.connect", "job_id": "connect", "params": deepcopy(request)},
        {"method": "execution.run", "job_id": "seed", "params": {**request, "execution_id": "seed", "language": "python", "code": "frame=pd.DataFrame({'id':[7]})"}},
        {"method": "execution.run", "job_id": "lost", "params": {**request, "execution_id": "lost", "language": "sql", "code": statement}},
        {"method": "execution.run", "job_id": "next", "params": {**request, "execution_id": "next", "language": "sql", "code": "SELECT 42 AS after_recovery"}},
        {"method": "execution.run", "job_id": "local", "params": {**request, "execution_id": "local", "language": "python", "code": "assert frame['id'].tolist()==[7]"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]

    class Commands:
        def poll(self, timeout):
            return True

        def recv(self):
            return jobs.pop(0)

        def close(self):
            pass

    messages = []
    kernel.kernel_main("real-driver-pool", Commands(), SimpleNamespace(send=messages.append, close=lambda: None))
    lost = next(message["payload"] for message in messages if message.get("job_id") == "lost")
    assert lost["status"] == "failed" and lost["connection_lost"] is True
    assert lost["connection_recovery"]["phase"] == "ready"
    assert lost["connection_recovery"]["acknowledgement_required"] is False
    assert lost["connection_recovery"]["state_loss_acknowledged"] is False
    assert lost["transaction_state"]["pending"] is False
    assert lost["transaction_state"]["state"] == "idle"
    assert lost["connection_recovery"]["transaction_state"] == lost["transaction_state"]
    for job_id in ("next", "local"):
        result = next(message["payload"] for message in messages if message.get("job_id") == job_id)
        assert result["status"] == "succeeded", result
    assert any(variable["name"] == "frame" for variable in lost["variables"])
    assert commands(odbc, statement) == 1
    assert commands(odbc, "SELECT 42 AS after_recovery") == 1
    assert not any(message.get("payload", {}).get("phase") == "blocked" for message in messages)
