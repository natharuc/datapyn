"""Real SQLAlchemy/Databricks compilation over an entirely offline DBAPI stub."""

from decimal import Decimal
import threading
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool, StaticPool

from datapyn_runtime.export_control import ExportCancelled
from datapyn_runtime.table_export import export_table, _temporary_exists


class Cursor:
    def __init__(self, physical):
        self.physical = physical
        self.description = None
        self.rows = []
        self.rowcount = -1
        self.active_command_id = None

    def execute(self, sql, parameters=None):
        self.physical.executed.append((sql, parameters))
        self.description, self.rows = None, []
        if sql.startswith("SHOW TABLES"):
            self.description = [(name, "string", None, None, None, None, True) for name in ("database", "tableName", "isTemporary")]
            self.rows = list(self.physical.tables)
        elif sql.startswith("SHOW VIEWS"):
            self.description = [(name, "string", None, None, None, None, True) for name in ("namespace", "viewName", "isTemporary")]
        elif sql.startswith("CREATE TEMPORARY TABLE"):
            if self.physical.create_error:
                raise RuntimeError(self.physical.create_error)
        elif sql.startswith("INSERT"):
            if self.physical.block_insert:
                self.active_command_id = object()
                self.physical.started.set()
                assert self.physical.released.wait(3), "offline test cursor was not cancelled"
                if self.physical.cancelled:
                    raise RuntimeError("operation cancelled")
            if self.physical.insert_error:
                raise RuntimeError(self.physical.insert_error)
        elif sql.startswith("DESCRIBE"):
            self.description = [(name, "string", None, None, None, None, True) for name in ("col_name", "data_type", "comment")]
            self.rows = [("id", "bigint", None)]

    def executemany(self, *_args):
        raise AssertionError("Databricks executemany would issue one request per row")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        self.active_command_id = None

    def cancel(self):
        self.physical.cancel_calls += 1
        self.physical.cancelled = True
        self.physical.released.set()


class Physical:
    def __init__(self):
        self.executed = []
        self.tables = []
        self.create_error = None
        self.insert_error = None
        self.block_insert = False
        self.started = threading.Event()
        self.released = threading.Event()
        self.cancelled = False
        self.cancel_calls = 0
        self.closed = 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed += 1


def make_connector(physical=None, poolclass=StaticPool, factory=None):
    physical = physical or Physical()
    engine = create_engine("databricks://token:offline@offline.invalid?http_path=/offline&catalog=main&schema=default",
                           creator=factory or (lambda: physical), poolclass=poolclass)
    return SimpleNamespace(db_type="databricks", engine=engine, connection_params={"database": "main", "schema": "default"}), physical


def insert_requests(physical):
    return [(sql, parameters) for sql, parameters in physical.executed if sql.startswith("INSERT")]


def test_temp_export_uses_native_bounded_multivalue_inserts_not_executemany():
    connector, physical = make_connector()
    try:
        events = []
        frame = pd.DataFrame({"id": range(2501), "text": ["ação'\\; DROP TABLE t"] * 2501})
        result = export_table(frame, {"table": "work", "temporary": True, "chunksize": 100000}, connector, progress=events.append)
        requests = insert_requests(physical)
        assert len(requests) == 3
        assert [len(parameters) // 2 for _sql, parameters in requests] == [1000, 1000, 501]
        assert all("DROP TABLE" not in sql and "ação" not in sql for sql, _parameters in requests)
        assert requests[0][1]["text_m0"] == "ação'\\; DROP TABLE t"
        assert sum(len(parameters) // 2 for _sql, parameters in requests) == len(frame)
        assert result["row_count"] == 2501 and connector.has_temporary_tables
        assert events[-1] == {"phase": "completed", "current": 2501, "total": 2501}
        ddl = next(sql for sql, _params in physical.executed if sql.startswith("CREATE TEMPORARY"))
        assert "USING" not in ddl and "TBLPROPERTIES" not in ddl
    finally:
        connector.engine.dispose()


def test_permanent_append_also_avoids_one_network_request_per_row():
    connector, physical = make_connector()
    try:
        result = export_table(pd.DataFrame({"id": range(250)}), {"table": "work", "if_exists": "append"}, connector)
        assert result["row_count"] == 250
        assert len(insert_requests(physical)) == 1
        assert len(insert_requests(physical)[0][1]) == 250
    finally:
        connector.engine.dispose()


def test_wide_columns_obey_bind_budget_and_preserve_exact_decimal_nulls():
    connector, physical = make_connector()
    try:
        frame = pd.DataFrame({f"n{index}": range(201) for index in range(99)})
        frame["amount"] = [Decimal("123456789.00000001")] * 200 + [None]
        export_table(frame, {"table": "wide", "temporary": True}, connector)
        requests = insert_requests(physical)
        assert [len(parameters) for _sql, parameters in requests] == [10000, 10000, 100]
        assert requests[0][1]["amount_m0"] == Decimal("123456789.00000001")
        assert requests[-1][1]["amount_m0"] is None
    finally:
        connector.engine.dispose()


def test_large_string_subbatches_have_progress_and_oversized_single_rows_are_isolated(monkeypatch):
    import datapyn_runtime.table_export as module
    monkeypatch.setattr(module, "DATABRICKS_BATCH_BYTES", 300)
    connector, physical = make_connector()
    try:
        events = []
        frame = pd.DataFrame({"text": ["x" * 150, "y" * 150, "z" * 500, "last"]})
        export_table(frame, {"table": "large", "temporary": True}, connector, progress=events.append)
        requests = insert_requests(physical)
        assert [list(parameters.values()) for _sql, parameters in requests] == [["x" * 150], ["y" * 150], ["z" * 500], ["last"]]
        assert events[-1]["current"] == 4
    finally:
        connector.engine.dispose()


@pytest.mark.parametrize("message", ["[PARSE_SYNTAX_ERROR] Syntax error at or near 'TEMPORARY'", "CREATE TEMPORARY TABLE is not supported yet", "[UNSUPPORTED_FEATURE.TEMPORARY_TABLE] unsupported"])
def test_unsupported_compute_fails_clearly_without_creating_permanent_fallback(message):
    connector, physical = make_connector()
    physical.create_error = message
    try:
        with pytest.raises(ValueError, match="Runtime 18.1"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector)
        assert not insert_requests(physical)
        assert not any(sql.startswith("CREATE TABLE") for sql, _params in physical.executed)
        assert not getattr(connector, "has_temporary_tables", False)
    finally:
        connector.engine.dispose()


def test_permissions_and_insert_errors_propagate_without_retries_or_invented_completion():
    connector, physical = make_connector()
    physical.create_error = "permission denied for CREATE TEMPORARY TABLE"
    try:
        with pytest.raises(RuntimeError, match="permission denied"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector)
        physical.create_error = None
        physical.insert_error = "invalid integer value"
        events = []
        with pytest.raises(RuntimeError, match="invalid integer"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector, progress=events.append)
        assert len(insert_requests(physical)) == 1
        assert not any(event["phase"] == "completed" for event in events)
    finally:
        connector.engine.dispose()


def test_exact_temporary_lookup_ignores_permanent_namesake_and_quotes_pattern():
    connector, physical = make_connector()
    try:
        physical.tables = [("default", "work.table'|*", False), ("", "unrelated", True)]
        with connector.engine.connect() as connection:
            assert not _temporary_exists(connection, "work.table'|*", "databricks")
            physical.tables.append(("", "WORK.TABLE'|*", True))
            assert _temporary_exists(connection, "work.table'|*", "databricks")
        sql = physical.executed[-1][0]
        assert sql.startswith("SHOW TABLES LIKE '") and "table''" in sql
        assert "\\\\." in sql and "\\\\x7c" in sql and "\\\\x2a" in sql
    finally:
        connector.engine.dispose()


def test_pinning_preserves_engine_alias_and_checkout_hooks_and_physical_session():
    physicals = []
    def factory():
        physical = Physical()
        physicals.append(physical)
        return physical
    connector, _ignored = make_connector(poolclass=QueuePool, factory=factory)
    alias = connector.engine
    checkouts = []
    event.listen(alias, "checkout", lambda connection, *_args: checkouts.append(connection))
    try:
        with alias.connect():
            pass
        export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector)
        with alias.connect() as first, alias.connect() as second:
            assert first.connection.dbapi_connection is second.connection.dbapi_connection
        assert connector.engine is alias and isinstance(alias.pool, StaticPool)
        assert physicals[0].closed == 1
        assert checkouts[-3:] == [physicals[1]] * 3
    finally:
        alias.dispose()


def test_cancel_interrupts_cursor_while_execute_is_waiting_and_removes_hooks():
    connector, physical = make_connector()
    physical.block_insert = True
    cancelled = threading.Event()
    events = []
    def request_cancel():
        assert physical.started.wait(2)
        cancelled.set()
    requester = threading.Thread(target=request_cancel)
    requester.start()
    try:
        with pytest.raises(ExportCancelled):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector,
                         progress=events.append, cancelled=cancelled.is_set)
        requester.join(2)
        assert physical.cancel_calls == 1
        assert events[-1]["phase"] == "cancelled"
        assert not any(event["phase"] == "completed" for event in events)
        assert not list(connector.engine.dispatch.before_cursor_execute)
        assert not list(connector.engine.dispatch.after_cursor_execute)
        assert not list(connector.engine.dialect.dispatch.handle_error)
    finally:
        requester.join(2)
        connector.engine.dispose()


def test_cancel_between_batches_reports_rows_that_databricks_already_keeps():
    connector, physical = make_connector()
    cancelled = threading.Event()
    events = []
    def progress(update):
        events.append(update)
        if update["phase"] == "writing" and update["current"] == 1000:
            cancelled.set()
    try:
        with pytest.raises(ExportCancelled, match="1000 rows"):
            export_table(pd.DataFrame({"id": range(2500)}), {"table": "work", "temporary": True}, connector,
                         progress=progress, cancelled=cancelled.is_set)
        assert len(insert_requests(physical)) == 1
        assert events[-1] == {"phase": "cancelled", "current": 1000, "total": 2500}
    finally:
        connector.engine.dispose()


def test_transient_cursor_cancel_failure_is_retried_until_native_cancel_succeeds(monkeypatch):
    original = Cursor.cancel
    def transient_cancel(cursor):
        if cursor.physical.cancel_calls == 0:
            cursor.physical.cancel_calls += 1
            raise RuntimeError("offline transient network failure")
        original(cursor)
    monkeypatch.setattr(Cursor, "cancel", transient_cancel)
    connector, physical = make_connector()
    physical.block_insert = True
    cancelled = threading.Event()
    requester = threading.Thread(target=lambda: (physical.started.wait(2), cancelled.set()))
    requester.start()
    try:
        with pytest.raises(ExportCancelled):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector,
                         cancelled=cancelled.is_set)
        assert physical.cancel_calls == 2 and physical.cancelled
        assert len(insert_requests(physical)) == 1
        assert not list(connector.engine.dispatch.before_cursor_execute)
    finally:
        requester.join(2)
        connector.engine.dispose()


def test_cancel_failures_stop_after_three_attempts_without_retrying_sql(monkeypatch):
    def failed_cancel(cursor):
        cursor.physical.cancel_calls += 1
        raise RuntimeError("offline unavailable cancellation endpoint")
    monkeypatch.setattr(Cursor, "cancel", failed_cancel)
    connector, physical = make_connector()
    physical.block_insert = True
    cancelled = threading.Event()
    def request():
        assert physical.started.wait(2)
        cancelled.set()
        assert physical.released.wait(1.7) is False
        physical.released.set()
    requester = threading.Thread(target=request)
    requester.start()
    try:
        with pytest.raises(ExportCancelled):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector,
                         cancelled=cancelled.is_set)
        assert physical.cancel_calls == 3
        assert len(insert_requests(physical)) == 1
    finally:
        requester.join(2)
        connector.engine.dispose()


def test_cancel_retry_does_not_target_cursor_after_execute_already_completed(monkeypatch):
    def failed_cancel(cursor):
        cursor.physical.cancel_calls += 1
        # Query completion wins before the next backoff, so no later retry may
        # target this closed cursor or another operation on the retained pool.
        cursor.physical.released.set()
        raise RuntimeError("offline transient cancellation failure")
    monkeypatch.setattr(Cursor, "cancel", failed_cancel)
    connector, physical = make_connector()
    physical.block_insert = True
    cancelled = threading.Event()
    requester = threading.Thread(target=lambda: (physical.started.wait(2), cancelled.set()))
    requester.start()
    try:
        with pytest.raises(ExportCancelled, match="1 rows"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True}, connector,
                         cancelled=cancelled.is_set)
        assert physical.cancel_calls == 1
        assert not list(connector.engine.dispatch.before_cursor_execute)
    finally:
        requester.join(2)
        connector.engine.dispose()


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_temp_survives_with_explorer_and_autocomplete_columns(cancel):
    from datapyn_runtime.explorer import ObjectExplorer
    connector, physical = make_connector()
    cancelled = threading.Event()
    physical.insert_error = "invalid insert" if not cancel else None
    def progress(update):
        if cancel and update["phase"] == "writing" and update["current"] == 1000:
            cancelled.set()
    try:
        with pytest.raises(ExportCancelled if cancel else RuntimeError):
            export_table(pd.DataFrame({"id": range(2500)}), {"table": "partial", "temporary": True}, connector,
                         progress=progress, cancelled=cancelled.is_set)
        assert connector.has_temporary_tables
        assert connector._datapyn_temporary_tables["partial"]["schema"] == ""
        explorer = ObjectExplorer(connector)
        explorer.schemas = lambda _database: ["default"]
        explorer.databases = lambda: ["main"]
        assert explorer.columns("partial", "")[0]["name"] == "id"
        snapshot = explorer.completion_schema("SELECT * FROM partial")
        assert any(table["temporary"] and table["key"] == "partial" for table in snapshot["tables"])
        assert snapshot["columns"]["partial"][0]["name"] == "id"
        with connector.engine.connect() as connection:
            assert connection.connection.dbapi_connection is physical
    finally:
        connector.engine.dispose()


def test_existing_temp_append_failure_registers_columns_and_retains_session():
    connector, physical = make_connector()
    physical.tables = [("", "work", True)]
    physical.insert_error = "invalid insert"
    try:
        with pytest.raises(RuntimeError, match="invalid insert"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "work", "temporary": True, "if_exists": "append"}, connector)
        assert connector.has_temporary_tables
        assert connector._datapyn_temporary_tables["work"]["columns"][0]["name"] == "id"
        assert not any(sql.startswith("CREATE") for sql, _parameters in physical.executed)
    finally:
        connector.engine.dispose()


@pytest.mark.parametrize("create_error", [None, "CREATE TEMPORARY TABLE is not supported yet"])
def test_replace_temp_updates_registry_only_after_successful_ddl(create_error):
    connector, physical = make_connector()
    physical.tables = [("", "work", True)]
    connector.has_temporary_tables = True
    connector._datapyn_temporary_tables = {"WORK": {"schema": "", "columns": [{"name": "old"}]}}
    physical.create_error = create_error
    physical.insert_error = "invalid insert"
    try:
        with pytest.raises(ValueError if create_error else RuntimeError):
            export_table(pd.DataFrame({"new": [1]}), {"table": "work", "temporary": True, "if_exists": "replace"}, connector)
        if create_error:
            assert connector._datapyn_temporary_tables == {}
            assert not connector.has_temporary_tables
        else:
            assert list(connector._datapyn_temporary_tables) == ["work"]
            assert connector._datapyn_temporary_tables["work"]["columns"][0]["name"] == "new"
            assert connector.has_temporary_tables
    finally:
        connector.engine.dispose()


def test_failed_initial_create_never_registers_a_nonexistent_temp():
    connector, physical = make_connector()
    physical.create_error = "permission denied"
    try:
        with pytest.raises(RuntimeError, match="permission denied"):
            export_table(pd.DataFrame({"id": [1]}), {"table": "missing", "temporary": True}, connector)
        assert not getattr(connector, "_datapyn_temporary_tables", {})
        assert not getattr(connector, "has_temporary_tables", False)
    finally:
        connector.engine.dispose()
