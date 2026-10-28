"""Connection recovery never replays SQL or terminates an owned transaction.

Providers are synthetic DBAPI errors and SQLAlchemy uses the local ODBC fake.
No credentials, network/database endpoints or native user windows are used.
"""

from types import SimpleNamespace
import errno
import ssl

import pyodbc
import pytest

from src.database.connection_recovery import ConnectionLostError, classify_connection_error
from src.database.database_connector import DatabaseConnector
from test_transaction_driver import OdbcConnection, OdbcCursor, odbc, open_connector  # noqa: F401
from test_sql_command_feedback_connector import Result, connector_for


@pytest.mark.parametrize("dialect,error,expected", [
    ("sqlserver", pyodbc.OperationalError("08S01", "link failed"), True),
    ("sqlserver", pyodbc.InterfaceError("08003", "not open"), True),
    ("sqlserver", pyodbc.OperationalError("HYT00", "statement timeout"), False),
    ("sqlserver", pyodbc.Error("HY010", "function sequence error"), False),
    ("sqlserver", pyodbc.Error("HY008", "cancelled"), False),
    ("sqlserver", pyodbc.InterfaceError("28000", "login failed"), False),
    ("sqlserver", pyodbc.ProgrammingError("42000", "syntax error"), False),
    ("postgresql", SimpleNamespace(), False),
    ("postgresql", RuntimeError("server closed the connection unexpectedly"), True),
    ("postgresql", RuntimeError("SSL connection has been closed unexpectedly"), True),
    ("postgresql", RuntimeError("[57P01] admin shutdown"), True),
    ("postgresql", RuntimeError("[57014] query cancelled"), False),
    ("mysql", RuntimeError(2006, "server gone away"), True),
    ("mariadb", RuntimeError(2013, "lost connection"), True),
    ("mysql", RuntimeError(1045, "authentication failed"), False),
    ("mysql", RuntimeError(1064, "invalid SQL"), False),
    ("databricks", RuntimeError("[INVALID_HANDLE.SESSION_CLOSED] invalid session"), True),
    ("databricks", RuntimeError("[SCHEMA_NOT_FOUND] bad catalog/schema"), False),
    ("databricks", RuntimeError("request timeout"), False),
    ("sqlite", RuntimeError("Cannot operate on a closed database."), True),
    ("sqlite", RuntimeError("database is locked"), False),
    ("sqlite", RuntimeError("no such table: t"), False),
    ("postgresql", ConnectionResetError("connection reset"), True),
    ("databricks", BrokenPipeError("pipe broken"), True),
    ("mysql", OSError(errno.ECONNRESET, "reset"), True),
    ("mysql", TimeoutError("statement timeout"), False),
])
def test_transport_classifier_is_specific_to_connection_loss(dialect, error, expected):
    assert classify_connection_error(error, dialect) is expected


def test_classifier_checks_wrapped_driver_causes_but_never_overrides_auth_or_certificate_errors():
    wrapped = RuntimeError("provider wrapper")
    wrapped.orig = pyodbc.OperationalError("08S01", "transport")
    assert classify_connection_error(wrapped, "sqlserver")
    wrapped.orig = RuntimeError(2003, "failed opening MySQL socket")
    wrapped.orig.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
    assert not classify_connection_error(wrapped, "mysql")
    wrapped.orig = pyodbc.InterfaceError("28000", "auth error")
    wrapped.orig.__cause__ = ConnectionResetError("close after rejected auth")
    assert not classify_connection_error(wrapped, "sqlserver")
    wrapped.orig = wrapped
    assert not classify_connection_error(wrapped, "sqlserver")


@pytest.mark.parametrize("http_code,expected", [(401, False), (403, False), (None, True)])
def test_databricks_request_context_preserves_network_causes_and_auth_exclusions(http_code, expected):
    error = RuntimeError("Databricks request failed")
    error.context = {"original-exception": ConnectionResetError("connection reset"), "http-code": http_code}
    assert classify_connection_error(error, "databricks") is expected


def test_actual_databricks_request_exception_retains_its_network_cause_in_args():
    from databricks.sql.exc import RequestError
    error = RequestError("Error during request to server", {"original-exception": "reset"}, None,
                         ConnectionResetError("connection reset"))
    assert classify_connection_error(error, "databricks")


@pytest.mark.parametrize("message", ["Attempt to use a closed connection.", "The cursor's connection has been closed."])
def test_odbc_and_tds_explicit_closed_socket_errors_are_recognized(message):
    assert classify_connection_error(pyodbc.ProgrammingError(message), "sqlserver")


def test_actual_tds_eof_is_recognized_without_a_sqlstate():
    from pytds.tds_base import ClosedConnectionError
    assert classify_connection_error(ClosedConnectionError(), "sqlserver")


@pytest.mark.parametrize("code", ["ssh_auth_failed", "ssh_host_key_unknown", "ssh_host_key_changed", "ssh_cancelled"])
def test_ssh_security_and_cancellation_errors_never_retry_even_with_network_causes(code):
    from datapyn_runtime.ssh_tunnel import SshTunnelError
    error = SshTunnelError("SSH blocked", code=code)
    error.__cause__ = ConnectionResetError("closed after rejection")
    assert not classify_connection_error(error, "postgresql")


def test_automatic_closed_pooled_socket_is_rejected_before_submitting_sql():
    connector, raw = connector_for("mysql", {"SELECT 7": [Result(rows=((7,),), columns=("n",))]})
    raw.open = False
    with pytest.raises(ConnectionLostError) as caught:
        connector.execute_query("SELECT 7")
    assert raw.executed == []
    assert caught.value.details["submitted"] is False


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("stage", ["execute", "fetch", "nextset"])
def test_sqlserver_transport_loss_stops_go_batches_without_replay_or_commit(odbc, monkeypatch, automatic, stage):
    connector = open_connector(automatic)
    raw = odbc[-1]
    before = (raw.commits, raw.rollbacks)
    original_execute = OdbcCursor.execute
    original_fetch = OdbcCursor.fetchmany
    original_nextset = OdbcCursor.nextset

    def failing_execute(cursor, sql, *params):
        value = original_execute(cursor, sql, *params)
        if stage == "execute" and sql == "SELECT 99":
            raise pyodbc.OperationalError("08S01", "network lost")
        return value

    def failing_fetch(cursor, *args):
        if stage == "fetch" and cursor.connection.commands[-1][0] == "SELECT 99":
            raise pyodbc.OperationalError("08S01", "network lost")
        return original_fetch(cursor, *args)

    def failing_nextset(cursor):
        if stage == "nextset" and cursor.connection.commands[-1][0] == "SELECT 99":
            raise pyodbc.OperationalError("08S01", "network lost")
        return original_nextset(cursor)

    monkeypatch.setattr(OdbcCursor, "execute", failing_execute)
    monkeypatch.setattr(OdbcCursor, "fetchmany", failing_fetch)
    monkeypatch.setattr(OdbcCursor, "nextset", failing_nextset)
    try:
        with pytest.raises(ConnectionLostError) as caught:
            connector.execute_query("SELECT 99\nGO\nUPDATE sample SET value=2")
        assert [sql for sql, _mode in raw.commands].count("SELECT 99") == 1
        assert "UPDATE sample SET value=2" not in [sql for sql, _mode in raw.commands]
        assert raw.commits == before[0]
        if not automatic:
            assert raw.rollbacks == before[1] and raw.closed == 0
        assert caught.value.details == {"acknowledgement_required": not automatic, "submitted": True, "session_state_lost": True}
        assert connector.get_transaction_state()["state"] == "unknown"
    finally:
        connector.disconnect()


@pytest.mark.parametrize("dialect,error", [("mysql", RuntimeError(2013, "transport")),
    ("mariadb", RuntimeError(2006, "transport")), ("postgresql", OSError(errno.ECONNRESET, "transport")),
    ("databricks", RuntimeError("invalid session handle"))])
def test_other_provider_execution_loss_is_structured_and_never_replayed(dialect, error):
    statement = "SELECT 7"
    connector, raw = connector_for(dialect, {statement: [error]})
    with pytest.raises(ConnectionLostError) as caught:
        connector.execute_query(statement)
    assert raw.executed.count(statement) == 1
    assert raw.commits == 0
    assert caught.value.details["submitted"] is True
    assert connector.get_connection_recovery_state()["required"] is True


@pytest.mark.parametrize("stream", [False, True])
def test_generic_commit_failure_is_not_silenced_or_reported_as_success(tmp_path, stream):
    connector, raw = connector_for("postgresql", {"UPDATE t SET value=2": [Result(1)]})
    attempts = []

    def commit():
        attempts.append(True)
        raise OSError(errno.ECONNRESET, "commit acknowledgement lost")

    raw.commit = commit
    with pytest.raises(ConnectionLostError) as caught:
        if stream:
            connector.stream_query_to_files("UPDATE t SET value=2", base_path=tmp_path / "result", export_format="csv")
        else:
            connector.execute_query("UPDATE t SET value=2")
    assert raw.executed == ["UPDATE t SET value=2"] and len(attempts) == 1
    assert caught.value.details["acknowledgement_required"] is True
    assert connector.get_transaction_state() == {"automatic_transactions": True, "pending": None, "state": "unknown"}


@pytest.mark.parametrize("automatic", [True, False])
def test_sqlserver_streaming_transport_loss_stops_following_batches(tmp_path, odbc, monkeypatch, automatic):
    connector = open_connector(automatic)
    raw = odbc[-1]
    commits = raw.commits
    original = OdbcCursor.execute

    def fail(cursor, sql, *params):
        value = original(cursor, sql, *params)
        if sql == "SELECT 99":
            raise pyodbc.OperationalError("08S01", "transport")
        return value

    monkeypatch.setattr(OdbcCursor, "execute", fail)
    try:
        with pytest.raises(ConnectionLostError):
            connector.stream_query_to_files("SELECT 99\nGO\nUPDATE sample SET value=2", base_path=tmp_path / "result", export_format="csv")
        assert raw.commits == commits
        assert "UPDATE sample SET value=2" not in [sql for sql, _ in raw.commands]
    finally:
        connector.disconnect()


@pytest.mark.parametrize("state", [{"pending": True, "state": "active"}, {"pending": None, "state": "unknown"}, None])
def test_manual_pending_or_uncertain_lane_is_never_probed_or_reset(odbc, state):
    connector = open_connector(False)
    raw = odbc[-1]
    connector._transaction_state_cache = state
    connector._last_connection_validation = 0
    before = (list(raw.commands), raw.commits, raw.rollbacks)
    try:
        connector.validate_connection_for_execution()
        assert (raw.commands, raw.commits, raw.rollbacks) == before
        assert connector.get_connection_recovery_state() is None
    finally:
        connector.disconnect()


def test_idle_health_validation_is_throttled_and_does_not_commit_or_rollback_manual_work(odbc, monkeypatch):
    connector = open_connector(False)
    raw = odbc[-1]
    clock = [100]
    connector._last_connection_validation = 100
    monkeypatch.setattr("src.database.database_connector.time.monotonic", lambda: clock[0])
    original = (raw.commits, raw.rollbacks)
    count = lambda: sum(sql == "SELECT 1" for sql, _ in raw.commands)
    before = count()
    try:
        clock[0] = 101
        connector.validate_connection_for_execution()
        assert count() == before
        clock[0] = 116
        connector.validate_connection_for_execution()
        assert count() == before + 1
        clock[0] = 120
        connector.validate_connection_for_execution()
        assert count() == before + 1 and (raw.commits, raw.rollbacks) == original
    finally:
        connector.disconnect()


def test_idle_manual_native_disconnect_is_recoverable_without_unknown_transaction_ack(odbc):
    connector = open_connector(False)
    raw = odbc[-1]
    raw.closed = True
    try:
        with pytest.raises(ConnectionLostError) as caught:
            connector.validate_connection_for_execution()
        assert caught.value.details == {"acknowledgement_required": False, "submitted": False, "session_state_lost": True}
    finally:
        connector.disconnect()


@pytest.mark.parametrize("automatic", [True, False])
def test_sqlalchemy_engine_errors_recover_without_invalidating_an_independent_manual_lane(odbc, monkeypatch, automatic):
    connector = open_connector(automatic)
    if not automatic:
        connector.execute_query("BEGIN TRANSACTION")
    manual = connector._manual_raw_conn
    original = OdbcCursor.execute

    def fail(cursor, sql, *params):
        value = original(cursor, sql, *params)
        if sql == "SELECT 99":
            raise pyodbc.OperationalError("08S01", "transport")
        return value

    monkeypatch.setattr(OdbcCursor, "execute", fail)
    try:
        with pytest.raises(Exception) as caught:
            with connector.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 99")
        if automatic:
            assert isinstance(caught.value, ConnectionLostError)
            assert connector.get_connection_recovery_state()["submitted"]
        else:
            assert not isinstance(caught.value, ConnectionLostError)
            assert connector.get_connection_recovery_state() is None
            assert manual.transaction_count == 1 and manual.closed == 0
    finally:
        connector.disconnect()
