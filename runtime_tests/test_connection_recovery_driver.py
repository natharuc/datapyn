"""Connection recovery never replays SQL or terminates an owned transaction.

Providers are synthetic DBAPI errors and SQLAlchemy uses the local ODBC fake.
No credentials, network/database endpoints or native user windows are used.
"""

from types import SimpleNamespace
import errno
import ssl

import pyodbc
import pytest

from src.database.connection_recovery import ConnectionLostError, classify_connection_error, is_read_only_query
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
    ("sqlserver", pyodbc.InterfaceError("08004", "Cannot open database requested by the login (4060)"), False),
    ("sqlserver", pyodbc.ProgrammingError("42000", "The server principal cannot access this database (916)"), False),
    ("sqlserver", pyodbc.ProgrammingError("42S02", "Invalid object name (208)"), False),
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


@pytest.mark.parametrize("state,message", [("42S02", "Invalid object name (208)"),
    ("42000", "Database access denied (916)"), ("08004", "Cannot open database (4060)"),
    ("HYT00", "Statement timeout")])
def test_handled_transport_context_does_not_reclassify_a_new_sql_error(state, message):
    error = pyodbc.OperationalError(state, message)
    error.__context__ = ConnectionResetError("handled earlier attempt")
    assert not classify_connection_error(error, "sqlserver")


@pytest.mark.parametrize("dialect,query,expected", [
    ("sqlserver", "SELECT TOP 100 * FROM VW_U21_A_SALF", True),
    ("sqlserver", "SELECT COUNT(*), MAX(id) FROM sample", True),
    ("postgresql", 'SELECT "id" FROM public.sample WHERE id > 1', True),
    ("mysql", "SELECT * FROM `sample` LIMIT 10", True),
    ("mariadb", "SELECT * FROM sample WHERE value = 'DELETE FROM t'", True),
    ("databricks", "SELECT * FROM catalog.schema.sample LIMIT 10", True),
    ("sqlite", "SELECT * FROM sample WHERE id = ?", True),
    ("sqlserver", "WITH x AS (SELECT * FROM sample) SELECT * FROM x", True),
    ("sqlserver", "SELECT * INTO #copy FROM sample", False),
    ("sqlserver", "SELECT @value = id FROM sample", False),
    ("sqlserver", "SELECT * FROM sample WITH (UPDLOCK)", False),
    ("sqlserver", "SELECT 1\nGO\nUPDATE sample SET value=1", False),
    ("postgresql", "SELECT * FROM sample FOR UPDATE", False),
    ("postgresql", "WITH x AS (DELETE FROM sample RETURNING *) SELECT * FROM x", False),
    ("postgresql", "SELECT nextval('sequence')", False),
    ("postgresql", "SELECT public.mutate()", False),
    ("mysql", "SELECT * INTO OUTFILE '/tmp/copy' FROM sample", False),
    ("mysql", "SELECT GET_LOCK('name', 1)", False),
    ("sqlserver", "UPDATE sample SET value=1; SELECT * FROM sample", False),
    ("sqlserver", "SELECT 1; SELECT 2", False),
    ("sqlserver", "EXEC sample", False),
    ("sqlserver", "SELECT 'unterminated", False),
])
def test_confirmation_read_classifier_rejects_mutations_and_opaque_commands(dialect, query, expected):
    assert is_read_only_query(query, dialect) is expected


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
            assert caught.value.details["submitted"]
            assert caught.value._datapyn_connector is connector
            assert connector.get_connection_recovery_state() is None
        else:
            assert not isinstance(caught.value, ConnectionLostError)
            assert connector.get_connection_recovery_state() is None
            assert manual.transaction_count == 1 and manual.closed == 0
    finally:
        connector.disconnect()


@pytest.mark.parametrize("prior", ["idle", "active", "unknown"])
@pytest.mark.parametrize("statement", ["SELECT TOP 100 * FROM sample", "UPDATE sample SET value=2"])
def test_manual_read_loss_confirms_only_real_or_uncertain_state(odbc, monkeypatch, prior, statement):
    connector = open_connector(False)
    raw = connector._manual_raw_conn
    if prior == "active":
        connector.execute_query("BEGIN TRANSACTION")
    elif prior == "unknown":
        connector.get_manual_connection()  # A public borrower may execute arbitrary SQL.
    before = (raw.commits, raw.rollbacks)
    original = OdbcCursor.execute

    def fail(cursor, sql, *params):
        value = original(cursor, sql, *params)
        if sql == statement:
            raise pyodbc.OperationalError("08S01", "transport failed")
        return value

    monkeypatch.setattr(OdbcCursor, "execute", fail)
    try:
        with pytest.raises(ConnectionLostError) as caught:
            connector.execute_query(statement)
        expected = prior != "idle" or statement.startswith("UPDATE")
        assert caught.value.details["acknowledgement_required"] is expected
        assert connector.has_pending_transaction() is expected
        assert [sql for sql, _ in raw.commands].count(statement) == 1
        assert (raw.commits, raw.rollbacks) == before
    finally:
        connector.disconnect()


@pytest.mark.parametrize("stage,requires_ack", [("commit", True), ("rollback", False)])
def test_sqlalchemy_cleanup_is_not_mistaken_for_an_uncertain_commit(odbc, stage, requires_ack):
    connector = open_connector(True)
    raw = odbc[-1]

    def fail():
        raise pyodbc.OperationalError("08S01", "connection lost during " + stage)

    setattr(raw, stage, fail)
    try:
        with pytest.raises(ConnectionLostError) as caught:
            with connector.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 7")
                if stage == "commit":
                    connection.commit()
        assert caught.value.details["acknowledgement_required"] is requires_ack
        assert caught.value._datapyn_connector is connector
        assert connector.get_connection_recovery_state() is None
    finally:
        connector.disconnect()


@pytest.mark.parametrize("automatic", [True, False])
def test_checkout_database_permission_errors_propagate_without_executing_on_wrong_database(odbc, monkeypatch, automatic):
    connector = open_connector(automatic)
    original = OdbcCursor.execute
    requested_query = "SELECT TOP 100 * FROM sample"

    def deny(cursor, sql, *params):
        value = original(cursor, sql, *params)
        if sql == "USE [denied]":
            raise pyodbc.InterfaceError("08004", "Cannot open database requested by the login (4060)")
        return value

    monkeypatch.setattr(OdbcCursor, "execute", deny)
    connector.connection_params["database"] = "denied"
    try:
        with pytest.raises(Exception) as caught:
            with connector.engine.connect() as connection:
                connection.exec_driver_sql(requested_query)
        assert not isinstance(caught.value, ConnectionLostError)
        assert "4060" in str(caught.value)
        assert not any(sql == requested_query for raw in odbc for sql, _ in raw.commands)
        assert connector.get_connection_recovery_state() is None
        connector.connection_params["database"] = "sample"
        with connector.engine.connect() as connection:
            assert connection.exec_driver_sql(requested_query).scalar() == 1
    finally:
        connector.disconnect()


@pytest.mark.parametrize("state,native,message,category", [
    ("42S02", 208, "Invalid object name 'missing'.", "not_found"),
    ("42000", 916, "The server principal cannot access the database.", "permission"),
    ("08004", 4060, "Cannot open database requested by the login.", "permission"),
])
def test_sqlserver_batch_errors_keep_the_provider_for_clean_runtime_messages(odbc, monkeypatch, state, native, message, category):
    from datapyn_runtime.errors import format_error
    connector = open_connector(False)
    target = "SELECT TOP 100 * FROM missing"
    original = OdbcCursor.execute
    provider = pyodbc.ProgrammingError(state,
        f"[{state}] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]{message} ({native}) (SQLExecDirectW)")

    def fail(cursor, sql, *params):
        value = original(cursor, sql, *params)
        if sql == target:
            raise provider
        return value

    monkeypatch.setattr(OdbcCursor, "execute", fail)
    try:
        with pytest.raises(Exception) as caught:
            connector.execute_query(target)
        assert caught.value.orig is provider
        assert caught.value._datapyn_provider_errors == (provider,)
        assert not isinstance(caught.value, ConnectionLostError)
        assert connector.get_connection_recovery_state() is None
        info = format_error(caught.value, language="sql")
        assert info["category"] == category
        assert info["message"] == message
        assert target not in info["technical_details"]
    finally:
        connector.disconnect()
