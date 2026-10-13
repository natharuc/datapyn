"""DBAPI transaction ownership through real SQLAlchemy pools, no database I/O."""

from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pyodbc
import pytest
from sqlalchemy import text

from src.database.database_connector import DatabaseConnector, OperationCancelled
from src.database.transaction_scope import transaction_state


class OdbcConnection:
    def __init__(self, autocommit=False):
        self.autocommit = autocommit
        self.commands = []
        self.commits = self.rollbacks = self.closed = 0
        self.transaction_count = 0
        self.failed = False
        self.converter = None

    def cursor(self):
        return OdbcCursor(self)

    def commit(self):
        self.commits += 1
        self.transaction_count = 0

    def rollback(self):
        self.rollbacks += 1
        self.transaction_count = 0

    def close(self):
        self.closed += 1

    def add_output_converter(self, datatype, callback):
        self.converter = datatype

    def getinfo(self, identifier):
        return "16.0.1000.1"


class OdbcCursor:
    messages = []
    rowcount = -1

    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rows = []

    def execute(self, sql, *params):
        raw = self.connection
        raw.commands.append((sql, raw.autocommit))
        self.description, self.rows = None, []
        head = sql.strip().upper()
        if "@@TRANCOUNT" in head:
            row = (raw.transaction_count, -1 if raw.failed else 1 if raw.transaction_count else 0)
        elif "SERVERPROPERTY" in head:
            row = ("16.0.1000.1",)
        elif "SCHEMA_NAME()" in head:
            row = ("dbo",)
        elif "SYS.SYSTEM_VIEWS" in head:
            row = ("dm_exec_sessions",)
        elif "TRANSACTION_ISOLATION_LEVEL" in head:
            row = ("READ COMMITTED",)
        elif "TEST MAX SUPPORT" in head:
            row = ("test max support",)
        elif "FN_LISTEXTENDEDPROPERTY" in head:
            row = (1,)
        elif head.startswith("BEGIN"):
            raw.transaction_count += 1
            return self
        elif head.startswith("COMMIT"):
            raw.transaction_count = max(0, raw.transaction_count - 1)
            raw.failed = False
            return self
        elif head.startswith("ROLLBACK"):
            raw.transaction_count = 0
            raw.failed = False
            return self
        elif head.startswith("FAIL"):
            raw.failed = bool(raw.transaction_count)
            raise pyodbc.Error("controlled statement failure")
        elif head.startswith("CANCEL"):
            raise OperationCancelled()
        elif head.startswith("SELECT"):
            row = (1,)
        else:
            self.rowcount = 2
            return self
        self.description = [(f"v{index}", None, None, None, None, None, None) for index in range(len(row))]
        self.rows = [row]
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, size):
        return self.fetchall()

    def nextset(self):
        return False

    def close(self):
        pass


@pytest.fixture
def odbc(monkeypatch):
    opened = []
    def connect(*args, **kwargs):
        raw = OdbcConnection(autocommit=kwargs.get("autocommit", False))
        opened.append(raw)
        return raw
    monkeypatch.setattr(pyodbc, "connect", connect)
    return opened


def open_connector(automatic_transactions):
    connector = DatabaseConnector()
    assert connector.connect("sqlserver", "fixture.invalid", 1433, "sample", "fixture", "fixture",
                             driver="ODBC Driver 18 for SQL Server", automatic_transactions=automatic_transactions)
    return connector


def test_odbc_manual_mode_is_configured_before_first_sql_and_metadata_is_isolated(odbc):
    connector = open_connector(False)
    try:
        assert len(odbc) == 2
        metadata, raw = odbc
        assert all(autocommit for connection in odbc for _, autocommit in connection.commands)
        assert raw.converter == -155  # Preserve SQLAlchemy's datetimeoffset decoder.
        assert (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
        connector.execute_query("BEGIN TRANSACTION")
        assert connector.has_pending_transaction()
        connector.execute_query("UPDATE sample SET value=1\nGO\nSELECT 1")
        assert connector.get_transaction_state()["transaction_count"] == 1
        with connector.engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
        assert metadata.rollbacks > 0
        assert raw.transaction_count == 1 and raw.rollbacks == 0
        connector.execute_query("COMMIT TRANSACTION")
        assert not connector.has_pending_transaction()
        assert (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
    finally:
        connector.disconnect()
    assert raw.closed == 1


def test_odbc_automatic_mode_preserves_script_commit_and_driver_default(odbc):
    connector = open_connector(True)
    try:
        raw = odbc[0]
        assert raw.autocommit is False
        commits = raw.commits
        connector.execute_query("UPDATE sample SET value=1\nGO\nSELECT 1")
        assert raw.commits == commits + 1
        assert raw.rollbacks > 0
    finally:
        connector.disconnect()


def test_manual_error_cancel_and_mode_mismatch_never_finish_pending_transaction(odbc):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        connector.execute_query("BEGIN TRANSACTION")
        with pytest.raises(Exception, match="controlled statement failure"):
            connector.execute_query("FAIL")
        assert connector.get_transaction_state()["state"] == "failed"
        with pytest.raises(OperationCancelled):
            connector.execute_query("CANCEL")
        with pytest.raises(ConnectionError, match="modo de transação mudou"):
            connector.execute_query("SELECT 1", automatic_transactions=True)
        assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (1, 0, 0, 0)
        connector.execute_query("ROLLBACK TRANSACTION")
        assert not connector.has_pending_transaction()
    finally:
        connector.disconnect()


def test_streaming_and_sqlalchemy_export_share_retained_connection_without_finalizing(odbc, tmp_path):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        connector.execute_query("BEGIN TRANSACTION")
        result = connector.stream_query_to_files("SELECT 1", base_path=tmp_path / "result", export_format="csv",
                                                automatic_transactions=False)
        assert result.total_rows == 1
        with connector.table_export_connection() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
            connection.commit()  # The internal facade never owns user SQL work.
        with pytest.raises(RuntimeError, match="export failure"):
            with connector.table_export_connection() as connection:
                connection.execute(text("UPDATE sample SET value=2"))
                raise RuntimeError("export failure")
        assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (1, 0, 0, 0)
    finally:
        connector.disconnect()


def test_independent_block_connections_can_execute_while_another_transaction_is_pending(odbc):
    first, second = open_connector(False), open_connector(False)
    try:
        first.execute_query("BEGIN TRANSACTION")
        first._query_lock.acquire()
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                assert worker.submit(second.execute_query, "SELECT 1").result(timeout=1).iloc[0, 0] == 1
            assert first.get_transaction_state()["pending"] is None
        finally:
            first._query_lock.release()
        assert first.has_pending_transaction() and not second.has_pending_transaction()
    finally:
        first.disconnect()
        second.disconnect()


@pytest.mark.parametrize("dialect,raw,expected", [
    ("postgresql", SimpleNamespace(get_transaction_status=lambda: 0), {"pending": False, "state": "idle"}),
    ("postgresql", SimpleNamespace(get_transaction_status=lambda: 3), {"pending": True, "state": "failed"}),
    ("postgresql", SimpleNamespace(get_transaction_status=lambda: 4), {"pending": None, "state": "unknown"}),
    ("mysql", SimpleNamespace(server_status=1), {"pending": True, "state": "active"}),
    ("mariadb", SimpleNamespace(server_status=2), {"pending": False, "state": "idle"}),
    ("sqlite", SimpleNamespace(in_transaction=True), {"pending": True, "state": "active"}),
])
def test_driver_state_probes_use_actual_transaction_state(dialect, raw, expected):
    assert transaction_state(raw, dialect) == expected


def test_pending_transaction_rejects_context_switch_without_committing_or_closing(odbc):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        connector.execute_query("BEGIN TRANSACTION")
        with pytest.raises(ConnectionError, match="transação pendente"):
            connector.change_database("other_database")
        assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (1, 0, 0, 0)
        assert connector.connection_params["database"] == "sample"
    finally:
        connector.disconnect()


def test_manual_mode_never_reconnects_after_transport_abort(odbc):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        raw._tds_socket = SimpleNamespace(_datapyn_aborted=True)
        connector._close_sqlserver_raw_connection(raw)
        assert connector.get_transaction_state()["pending"] is None
        with pytest.raises(ConnectionError, match="interrompida"):
            connector.execute_query("SELECT 1")
        assert len(odbc) == 2 and (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
    finally:
        connector.disconnect()


@pytest.mark.parametrize("pending", [False, True])
def test_azure_manual_use_reconnects_only_when_actual_transaction_state_is_idle(odbc, pending):
    connector = DatabaseConnector()
    connector.connect("sqlserver", "fixture.database.windows.net", 1433, "sample", "fixture", "fixture",
                      driver="ODBC Driver 18 for SQL Server", automatic_transactions=False)
    try:
        original = connector.get_manual_connection()
        if pending:
            connector.execute_query("BEGIN TRANSACTION")
            with pytest.raises(ConnectionError, match="transação pendente"):
                connector.execute_query("USE other_database")
            assert connector.get_manual_connection() is original
            assert (original.transaction_count, original.commits, original.rollbacks, original.closed) == (1, 0, 0, 0)
        else:
            connector.execute_query("USE other_database")
            assert connector.connection_params["database"] == "other_database"
            assert connector.get_manual_connection() is not original
            assert (original.commits, original.rollbacks, original.closed) == (0, 0, 1)
    finally:
        connector.disconnect()


def test_postgres_manual_context_probe_does_not_reset_failed_explicit_transaction():
    raw = OdbcConnection(autocommit=True)
    raw.transaction_count = 1
    raw.failed = True
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector.automatic_transactions = False
    connector._manual_raw_conn = raw
    connector._context_probe_required = True
    # A failed PostgreSQL transaction rejects the context observation as well.
    raw.cursor = lambda: SimpleNamespace(execute=lambda sql: (_ for _ in ()).throw(RuntimeError("transaction aborted")),
                                        close=lambda: None)
    connector._reconcile_execution_context(raw)
    assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (1, 0, 0, 0)
    assert connector._requires_postgresql_autocommit("VACUUM") is False


def test_databricks_manual_setting_preserves_server_managed_transaction_semantics():
    connector = DatabaseConnector()
    connector.db_type = "databricks"
    connector.automatic_transactions = False
    assert connector.get_transaction_state() == {"automatic_transactions": False, "pending": False, "state": "unsupported"}


def test_idle_transaction_checks_are_cached_without_sql_roundtrips(odbc):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        connector.execute_query("BEGIN TRANSACTION")
        before = len(raw.commands)
        for _ in range(1000):
            assert connector.has_pending_transaction()
            assert connector.get_transaction_state()["transaction_count"] == 1
        assert len(raw.commands) == before
        connector.execute_query("COMMIT TRANSACTION")
        before = len(raw.commands)
        for _ in range(1000):
            assert not connector.has_pending_transaction()
            assert connector.get_transaction_state()["pending"] is False
        assert len(raw.commands) == before
        connector.execute_query("BEGIN TRANSACTION")
        connector.execute_query("ROLLBACK TRANSACTION")
        before = len(raw.commands)
        assert not connector.has_pending_transaction()
        assert len(raw.commands) == before
    finally:
        connector.disconnect()


def test_failed_cancelled_and_external_dbapi_operations_preserve_uncertainty_without_idle_io(odbc):
    connector = open_connector(False)
    try:
        raw = connector.get_manual_connection()
        connector.execute_query("BEGIN TRANSACTION")
        with pytest.raises(Exception, match="controlled statement failure"):
            connector.execute_query("FAIL")
        before = len(raw.commands)
        assert connector.has_pending_transaction()
        assert len(raw.commands) == before
        assert connector.get_transaction_state()["state"] == "failed"
        assert len(raw.commands) == before + 1
        connector.execute_query("ROLLBACK TRANSACTION")
        connector.execute_query("BEGIN TRANSACTION")
        with pytest.raises(OperationCancelled):
            connector.execute_query("CANCEL")
        before = len(raw.commands)
        assert connector.has_pending_transaction()
        assert len(raw.commands) == before
        assert connector.get_transaction_state()["state"] == "active"
        assert len(raw.commands) == before + 1
        connector.execute_query("ROLLBACK TRANSACTION")
        escaped = connector.get_manual_connection()
        escaped.cursor().execute("BEGIN TRANSACTION")
        before = len(raw.commands)
        assert connector.has_pending_transaction()
        assert len(raw.commands) == before
        assert connector.get_transaction_state()["transaction_count"] == 1
        assert len(raw.commands) == before + 1
    finally:
        connector.disconnect()


@pytest.mark.parametrize("value", [None, "false", 0, 1, []])
def test_connect_transaction_setting_rejects_non_booleans_without_driver_access(value, odbc):
    with pytest.raises(TypeError, match="must be a boolean"):
        DatabaseConnector().connect("sqlserver", "fixture.invalid", 1433, "sample", automatic_transactions=value)
    assert odbc == []
