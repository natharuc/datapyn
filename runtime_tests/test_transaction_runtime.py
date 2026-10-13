"""Execution policies and preserved user transactions, without external servers."""

from copy import deepcopy
import itertools
import sqlite3

import pandas as pd
import pytest

from datapyn_runtime import transaction_settings as settings
from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.configurations import ConfigurationTransfer
from datapyn_runtime.database import ConnectorPool, PendingTransactionError, SQLiteConnector
from datapyn_runtime.legacy_settings import preferences_from_ini
from datapyn_runtime.stream_export import run as stream_export
from datapyn_runtime.table_export import export_table
from datapyn_runtime.workspace import read_document, write_document
from test_connection_catalog import Secrets
from test_runtime import Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "broker"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "broker"))
    runtime = Client()
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.mark.parametrize(("global_enabled", "snapshot", "block_disabled"), itertools.product((False, True), repeat=3))
def test_global_disable_dominates_snapshots_and_block_overrides(tmp_path, global_enabled, snapshot, block_disabled):
    path = tmp_path / "transaction_settings.json"
    settings.settings_set({"automatic_transactions": global_enabled}, path)
    params = {"_transaction_settings_path": str(path), "automatic_transactions": snapshot,
              "disable_automatic_transactions": block_disabled}
    assert settings.effective_automatic_transactions(params) is (global_enabled and snapshot and not block_disabled)


@pytest.mark.parametrize("value", ("false", 0, 1, None, {}, []))
def test_transaction_booleans_do_not_coerce_strings_or_numbers(tmp_path, value):
    path = tmp_path / "transaction_settings.json"
    with pytest.raises(ValueError, match="boolean"):
        settings.settings_set({"automatic_transactions": value}, path)
    for field in ("automatic_transactions", "disable_automatic_transactions"):
        with pytest.raises(ValueError, match="boolean"):
            settings.effective_automatic_transactions({field: value, "_transaction_settings_path": str(path)})
    assert not path.exists()


def test_old_installation_defaults_to_automatic_without_rewriting_files(tmp_path):
    path = tmp_path / "transaction_settings.json"
    assert settings.settings_get(path) == {"automatic_transactions": True}
    assert settings.effective_automatic_transactions({"_transaction_settings_path": str(path)}) is True
    assert not path.exists()


def test_static_diagnostics_never_read_transaction_policy_or_change_cached_params(monkeypatch):
    from test_diagnostic_jobs import supervisor_stub
    monkeypatch.setattr(settings, "settings_get", lambda *args: pytest.fail("static diagnostics read transaction settings"))
    runtime = supervisor_stub()
    params = {"session_id": "session", "block_id": "block", "diagnostic_id": "diagnostic", "language": "sql", "code": "SELECT 1"}
    assert runtime.dispatch("language.diagnostics", params, 1) is None
    runtime.background.submit.assert_called_once_with(1, "language.diagnostics", params, {"version": 2})


def database_file(tmp_path):
    path = tmp_path / "data.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE records (value INTEGER)")
    return path


def test_manual_sql_failure_and_metadata_never_finish_pending_transaction(tmp_path):
    path = database_file(tmp_path)
    connector = SQLiteConnector(str(path), automatic_transactions=False)
    try:
        connector.execute_query("BEGIN; INSERT INTO records VALUES (7)")
        with pytest.raises(sqlite3.OperationalError):
            connector.execute_query("INSERT INTO missing_table VALUES (1)")
        assert connector.get_transaction_state() == {"automatic_transactions": False, "pending": True, "state": "active"}
        from sqlalchemy import inspect
        assert "records" in inspect(connector.engine).get_table_names()
        assert connector.has_pending_transaction()
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT * FROM records").fetchall() == []
        assert connector.execute_query("SELECT * FROM records").iloc[0, 0] == 7
        connector.execute_query("COMMIT")
        assert not connector.has_pending_transaction()
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT * FROM records").fetchall() == [(7,)]
    finally:
        connector.disconnect()


def scope(config, block, enabled=False):
    return {"connection_id": "db", "_connection_config": config, "block_id": block,
            "_execution_scope_id": block, "automatic_transactions": enabled}


def test_off_python_metadata_engine_is_native_autocommit_before_its_first_statement(tmp_path):
    path = database_file(tmp_path)
    connector = SQLiteConnector(str(path), automatic_transactions=False)
    try:
        with connector.engine.connect() as connection:
            assert connection.connection.driver_connection.isolation_level is None
            connection.exec_driver_sql("INSERT INTO records VALUES (11)")
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT * FROM records").fetchall() == [(11,)]
        connector.execute_query("BEGIN; INSERT INTO records VALUES (12)")
        assert pd.read_sql("SELECT * FROM records", connector.engine)["value"].tolist() == [11]
        assert connector.has_pending_transaction()
        connector.execute_query("ROLLBACK")
    finally:
        connector.disconnect()


def test_pending_block_rejects_toggle_and_retarget_but_other_blocks_remain_independent(tmp_path):
    path = database_file(tmp_path)
    config = {"db_type": "sqlite", "database": str(path)}
    pool = ConnectorPool(idle_timeout=1)
    try:
        first = pool.activate(scope(config, "first"))
        first.execute_query("BEGIN; INSERT INTO records VALUES (8)")
        physical = first.connection
        with pytest.raises(PendingTransactionError):
            pool.activate(scope(config, "first", True))
        with pytest.raises(PendingTransactionError):
            pool.activate(scope({**config, "database": str(tmp_path / "elsewhere.sqlite")}, "first"))
        assert first.connection is physical and first.has_pending_transaction()
        second = pool.activate(scope(config, "second", True))
        assert second is not first
        assert second.execute_query("SELECT COUNT(*) AS count FROM records").iloc[0, 0] == 0
        pool.activate(scope(config, "first")).execute_query("ROLLBACK")
        third = pool.activate(scope(config, "first", True))
        assert third.automatic_transactions and not first.has_pending_transaction()
    finally:
        pool.disconnect()


def test_default_automatic_blocks_share_the_prepared_session_and_temporary_tables(tmp_path):
    config = {"db_type": "sqlite", "database": str(database_file(tmp_path))}
    pool = ConnectorPool()
    try:
        prepared = pool.activate({"connection_id": "db", "config": config}, default=True)
        first = pool.activate(scope(config, "first", True))
        assert first is prepared
        first.execute_query("CREATE TEMPORARY TABLE temp_values (value INTEGER); INSERT INTO temp_values VALUES (9)")
        second = pool.activate(scope(config, "second", True))
        assert second is first
        assert second.execute_query("SELECT * FROM temp_values").iloc[0, 0] == 9
        manual_first = pool.activate(scope(config, "manual-first"))
        manual_second = pool.activate(scope(config, "manual-second"))
        assert manual_first is not manual_second and manual_first is not prepared
    finally:
        pool.disconnect()


def test_in_memory_database_lanes_share_only_their_saved_logical_connection():
    config = {"db_type": "sqlite"}
    pool = ConnectorPool()
    try:
        first = pool.activate({"connection_id": "first-db", "config": config}, default=True)
        first.execute_query("CREATE TABLE records(value INTEGER); INSERT INTO records VALUES (21)")
        other = pool.activate({"connection_id": "second-db", "config": config}, default=True)
        other.execute_query("CREATE TABLE records(value INTEGER); INSERT INTO records VALUES (22)")
        assert first.execute_query("SELECT * FROM records").iloc[0, 0] == 21
        assert other.execute_query("SELECT * FROM records").iloc[0, 0] == 22
        manual = pool.activate({**scope(config, "manual"), "connection_id": "first-db"})
        assert manual.execute_query("SELECT * FROM records").iloc[0, 0] == 21
        assert manual.connection is not first.connection
    finally:
        pool.disconnect()


def test_completion_refresh_borrows_only_its_blocks_manual_temporary_session(tmp_path):
    from datapyn_runtime.explorer import ObjectExplorer
    config = {"db_type": "sqlite", "database": str(database_file(tmp_path))}
    pool = ConnectorPool()
    try:
        first = pool.activate(scope(config, "first"))
        first.execute_query("BEGIN")
        export_table(pd.DataFrame({"value": [14]}), {"table": "private_temp", "temporary": True}, first)
        pool.activate(scope(config, "second", True))
        selected = pool.activate({"connection_id": "db", "_connection_config": config, "block_id": "first", "_metadata_scope": True,
                                  "automatic_transactions": False})
        assert selected is first
        snapshot = ObjectExplorer(selected).completion_schema("SELECT * FROM private_temp")
        assert any(table["name"] == "private_temp" for table in snapshot["tables"])
        assert first.has_pending_transaction()
        other = pool.activate({"connection_id": "db", "_connection_config": config, "block_id": "second", "_metadata_scope": True})
        assert other is not first
        assert not any(table["name"] == "private_temp" for table in ObjectExplorer(other).completion_schema()["tables"])
        first.execute_query("ROLLBACK")
    finally:
        pool.disconnect()


def test_sql_created_temporary_completion_uses_real_owner_socket_and_rollback_removes_it(tmp_path):
    from datapyn_runtime.explorer import ObjectExplorer
    connector = SQLiteConnector(str(database_file(tmp_path)), automatic_transactions=False)
    try:
        explorer = ObjectExplorer(connector)
        code = 'BEGIN; CREATE TEMP TABLE "OwnTemp" (id INTEGER, label TEXT)'
        connector.execute_query(code)
        assert explorer.refresh_sql_temporaries(code)
        snapshot = explorer.completion_schema("SELECT t. FROM OwnTemp t")
        assert any(table["name"] == "OwnTemp" for table in snapshot["tables"])
        assert {column["name"] for column in snapshot["columns"]["temp.OwnTemp"]} == {"id", "label"}
        assert connector.has_pending_transaction()
        connector.execute_query("ROLLBACK")
        assert explorer.refresh_sql_temporaries("ROLLBACK")
        assert not any(table["name"] == "OwnTemp" for table in explorer.completion_schema()["tables"])
    finally:
        connector.disconnect()


@pytest.mark.parametrize("dialect", ("sqlserver", "mssql"))
def test_sqlserver_temporary_existence_quotes_the_owner_name_inside_the_bind(dialect):
    from datapyn_runtime.table_export import _temporary_exists
    from types import SimpleNamespace
    calls = []
    def execute(sql, params):
        calls.append((str(sql), params))
        return SimpleNamespace(scalar=lambda: 123)
    name = "#same.name] across sessions"
    assert _temporary_exists(SimpleNamespace(execute=execute), name, dialect)
    assert calls == [("SELECT OBJECT_ID(:name, 'U')", {"name": "tempdb..[#same.name]] across sessions]"})]


def test_idle_and_capacity_eviction_preserve_pending_and_unknown_lanes(tmp_path, monkeypatch):
    pool = ConnectorPool(idle_timeout=1)
    config = {"db_type": "sqlite", "database": str(database_file(tmp_path))}
    try:
        first = pool.activate(scope(config, "first"))
        first.execute_query("BEGIN")
        first_key = pool.active_key
        pool.last_used[first_key] = 0
        assert pool.reap_idle() == [] and first_key in pool.items
        first.execute_query("ROLLBACK")
        monkeypatch.setattr(first, "has_pending_transaction", lambda: (_ for _ in ()).throw(ConnectionError("unknown")))
        assert pool.reap_idle() == [] and first_key in pool.items
        for index in range(8):
            pool.activate({**scope(config, f"other-{index}", True), "connection_id": f"db-{index}"})
        assert first_key in pool.items and len(pool.items) == 8
    finally:
        pool.disconnect()


def test_manual_table_export_and_stream_use_the_same_uncommitted_session(tmp_path):
    path = database_file(tmp_path)
    connector = SQLiteConnector(str(path), automatic_transactions=False)
    try:
        connector.execute_query("BEGIN")
        exported = export_table(pd.DataFrame({"value": [2, 3]}), {"table": "records", "if_exists": "append"}, connector)
        assert exported["row_count"] == 2 and connector.has_pending_transaction()
        result = stream_export(connector, "SELECT * FROM records", path=str(tmp_path / "pending.csv"))
        assert result["total_rows"] == 2 and connector.has_pending_transaction()
        with pytest.raises(sqlite3.OperationalError):
            stream_export(connector, "SELECT * FROM missing_table", path=str(tmp_path / "missing.csv"))
        assert connector.has_pending_transaction()
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT * FROM records").fetchall() == []
        connector.execute_query("ROLLBACK")
        assert connector.execute_query("SELECT COUNT(*) AS count FROM records").iloc[0, 0] == 0
    finally:
        connector.disconnect()


def test_block_override_survives_dpw_incremental_session_save_and_clone(tmp_path, monkeypatch):
    from datapyn_runtime import profiles
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    profiles.close_stores()
    original = {"version": "1.0", "blocks": [{"language": "sql", "code": "SELECT 1", "block_key": "one",
                                                "disable_automatic_transactions": True, "vendor": {"keep": True}}]}
    try:
        path = tmp_path / "analysis.dpw"
        write_document(str(path), original)
        assert read_document(str(path))["document"] == original
        state = {"documents": [{"sessionId": "stable", "title": "Analysis", "document": original}],
                 "preferences": {"automaticTransactions": False}, "activeIndex": 0}
        profiles.save({"state": state})
        revised = deepcopy(original)
        revised["blocks"][0]["code"] = "SELECT 2"
        profiles.patch({"upserts": [{"sessionId": "stable", "document": revised}]})
        cloned = profiles.clone({"profile_id": "default", "name": "Copy", "include_credentials": False})
        restored = profiles.state({"profile_id": cloned["id"]})["state"]
        assert restored["documents"][0]["document"] == revised
        assert restored["preferences"]["automaticTransactions"] is False
        assert not (profiles.profile_path(cloned["id"]) / settings.FILE_NAME).exists()
    finally:
        profiles.close_stores()


def test_portable_transaction_preference_preserves_ini_and_imports_global(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "global"))
    source = tmp_path / "source-profile"
    target = tmp_path / "target-profile"
    transfer = ConfigurationTransfer(source, ConnectionCatalog(source / "connections.json", Secrets()))
    folder = tmp_path / "exported"
    transfer.export_folder({"path": str(folder), "preferences": {"automaticTransactions": False}})
    assert preferences_from_ini((folder / "DataPyn.ini").read_bytes())["automaticTransactions"] is False
    other = ConfigurationTransfer(target, ConnectionCatalog(target / "connections.json", Secrets()))
    inspection = other.inspect({"path": str(folder)})
    result = other.import_folder({"path": str(folder), "preview_token": inspection["preview_token"]})
    assert result["preferences"]["automaticTransactions"] is False
    assert settings.settings_get() == {"automatic_transactions": False}
    assert not (target / settings.FILE_NAME).exists()


def test_global_rpc_persists_across_profiles_and_restart_without_executing_drafts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "runtime"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "runtime"))
    first = Client()
    try:
        assert first.request("transactions.settings.get") == {"automatic_transactions": True}
        assert first.request("transactions.settings.set", {"automatic_transactions": False}) == {"automatic_transactions": False}
        profile = first.request("workspace.profiles.create", {"name": "Separate"})
        first.request("workspace.profiles.select", {"profile_id": profile["id"]})
        assert first.request("transactions.settings.get")["automatic_transactions"] is False
    finally:
        first.close()
    second = Client()
    try:
        assert second.request("transactions.settings.get")["automatic_transactions"] is False
        second.session()
        assert second.response("execution.run", {"session_id": "a", "execution_id": "bad", "language": "sql", "code": "SELECT 1",
                                                 "disable_automatic_transactions": "false"})["error"]
        second.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
        finished = second.execute("SELECT 42 AS value", language="sql", block_id="block", automatic_transactions=True,
                                  disable_automatic_transactions=False, _automatic_transactions_snapshot=True)
        assert finished["status"] == "succeeded" and finished["automatic_transactions"] is False
        assert finished["transaction_state"] == {"automatic_transactions": False, "pending": False, "state": "idle"}
    finally:
        second.close()


def test_broker_reports_only_the_requested_blocks_pending_state_and_preserves_it(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})
    first = client.execute("BEGIN; INSERT INTO records VALUES (5)", "begin", language="sql", block_id="first",
                           disable_automatic_transactions=True)
    assert first["status"] == "succeeded" and first["transaction_state"]["pending"] is True
    other = client.execute("SELECT COUNT(*) AS count FROM records", "other", language="sql", block_id="second")
    assert client.page(other)["rows"] == [[0]] and other["transaction_state"]["pending"] is False
    rejected = client.execute("SELECT 99", "rejected", language="sql", block_id="first")
    assert rejected["status"] == "failed" and rejected["error_code"] == "transaction_pending"
    assert rejected["transaction_state"] == {"automatic_transactions": False, "pending": True, "state": "active"}
    rollback = client.execute("ROLLBACK", "rollback", language="sql", block_id="first",
                              disable_automatic_transactions=True)
    assert rollback["status"] == "succeeded" and rollback["transaction_state"]["pending"] is False
    enabled = client.execute("SELECT COUNT(*) AS count FROM records", "enabled", language="sql", block_id="first")
    assert client.page(enabled)["rows"] == [[0]] and enabled["automatic_transactions"] is True


def test_block_only_connection_without_a_tab_default_still_isolates_later_blocks(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    first = client.execute("BEGIN; INSERT INTO records VALUES (99)", "block-only", language="sql", block_id="first",
                           disable_automatic_transactions=True, config={"db_type": "sqlite", "database": str(path)})
    assert first["status"] == "succeeded" and first["transaction_state"]["pending"] is True
    second = client.execute("SELECT * FROM records", "without-default", language="sql", block_id="second")
    assert client.page(second)["rows"] == [] and second["transaction_state"]["pending"] is False
    rollback = client.execute("ROLLBACK", "resolve-first", language="sql", block_id="first", disable_automatic_transactions=True)
    assert rollback["status"] == "succeeded" and rollback["transaction_state"]["pending"] is False


def test_queued_execution_keeps_its_authoritative_policy_snapshot(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})
    client.request("execution.run", {"session_id": "a", "execution_id": "wait", "language": "python", "code": "import time; time.sleep(0.5)"})
    client.event("execution.started", "wait")
    client.request("transactions.settings.set", {"automatic_transactions": False})
    client.request("execution.run", {"session_id": "a", "execution_id": "queued", "language": "sql",
                                     "code": "BEGIN; INSERT INTO records VALUES (6)", "block_id": "queued-block",
                                     "automatic_transactions": True, "disable_automatic_transactions": False})
    client.request("transactions.settings.set", {"automatic_transactions": True})
    finished = client.event("execution.finished", "queued")
    assert finished["status"] == "succeeded" and finished["automatic_transactions"] is False
    assert finished["transaction_state"]["pending"] is True
    rollback = client.execute("ROLLBACK", "resolve", language="sql", block_id="queued-block", disable_automatic_transactions=True)
    assert rollback["status"] == "succeeded" and rollback["transaction_state"]["pending"] is False


def test_python_sql_helper_uses_its_block_snapshot_and_retained_connection(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})
    first = client.execute("sql('BEGIN; INSERT INTO records VALUES (13)'); sql('SELECT * FROM records')", "python-sql",
                           block_id="python", disable_automatic_transactions=True)
    assert client.page(first)["rows"] == [[13]] and first["transaction_state"]["pending"] is True
    assert first["command_results"]
    other = client.execute("pd.read_sql('SELECT * FROM records', db_engine)", "python-other", block_id="other")
    assert client.page(other)["rows"] == []
    rollback = client.execute("sql('ROLLBACK')", "python-rollback", block_id="python", disable_automatic_transactions=True)
    assert rollback["status"] == "succeeded" and rollback["transaction_state"]["pending"] is False
    alias = client.execute("old_sql = sql", "alias", block_id="alias")
    assert alias["status"] == "succeeded"
    stale = client.execute("old_sql('SELECT 1')", "stale", block_id="other")
    assert stale["status"] == "failed" and "currently executing block" in stale["error"]


def test_sql_helper_never_overwrites_a_legacy_dataframe_or_user_function_named_sql(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    selected = client.execute("SELECT 17 AS value", "legacy-sql", language="sql", variable_name="sql")
    assert client.page(selected)["rows"] == [[17]]
    reused = client.execute("sql", "legacy-read")
    assert client.page(reused)["rows"] == [[17]]
    function = client.execute("def sql(query):\n    return pd.DataFrame({'value': [query]})\nsql('user function')", "own-function")
    assert client.page(function)["rows"] == [["user function"]]
    preserved = client.execute("sql('still user function')", "own-function-again")
    assert client.page(preserved)["rows"] == [["still user function"]]


def wait_metadata(client, params, mode):
    client.request("language.prepare", {**params, "automatic_transactions": mode, "refresh": True})
    return client.wait(lambda message: message.get("event") == "language.context_updated"
                       and message["payload"].get("block_id") == params["block_id"]
                       and message["payload"].get("automatic_transactions") is mode
                       and message["payload"].get("metadata_state") == "ready")["payload"]


def test_mode_switch_without_ddl_invalidates_the_blocks_new_physical_metadata(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})
    params = {"session_id": "a", "block_id": "same", "scope_inherited": False, "code": "SELECT * FROM "}
    first = client.execute("CREATE TEMP TABLE private_mode_temp (value INTEGER)", "manual-temp", language="sql",
                           block_id="same", scope_inherited=False, disable_automatic_transactions=True)
    assert first["status"] == "succeeded" and first["transaction_state"]["pending"] is False
    manual = wait_metadata(client, params, False)
    assert any(table["name"] == "private_mode_temp" for table in manual["schema_snapshot"]["tables"])
    switched = client.execute("SELECT 1 AS value", "auto-switch", language="sql", block_id="same", scope_inherited=False)
    assert switched["status"] == "succeeded"
    invalidated = client.wait(lambda message: message.get("event") == "language.context_updated"
                             and message["payload"].get("block_id") == "same"
                             and message["payload"].get("metadata_invalidated")
                             and message["payload"].get("automatic_transactions") is True)["payload"]
    assert invalidated["metadata_invalidation_scope"] == "block"
    automatic = wait_metadata(client, params, True)
    assert not any(table["name"] == "private_mode_temp" for table in automatic["schema_snapshot"]["tables"])
    completion = client.request("language.complete", {**params, "language": "sql", "automatic_transactions": True,
                                                     "line": 1, "column": 15, "completion_id": "new-mode"})
    assert not any("private_mode_temp" in item["label"] for item in completion["items"])
    # A late request for the old mode can still inspect its retained lane;
    # its reply is tagged and cannot replace the automatic snapshot.
    late = wait_metadata(client, params, False)
    assert any(table["name"] == "private_mode_temp" for table in late["schema_snapshot"]["tables"])
    automatic_again = wait_metadata(client, params, True)
    assert not any(table["name"] == "private_mode_temp" for table in automatic_again["schema_snapshot"]["tables"])


def test_new_policy_metadata_and_readonly_explorer_preserve_old_pending_lane(client, tmp_path):
    path = database_file(tmp_path)
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(path)}})
    first = client.execute("BEGIN; INSERT INTO records VALUES (37); CREATE TEMP TABLE private_pending (id INTEGER)",
                           "pending-meta", language="sql", block_id="same", scope_inherited=False,
                           disable_automatic_transactions=True)
    assert first["transaction_state"]["pending"] is True
    params = {"session_id": "a", "block_id": "same", "scope_inherited": False, "code": "SELECT * FROM "}
    automatic = wait_metadata(client, params, True)
    assert not any(table["name"] == "private_pending" for table in automatic["schema_snapshot"]["tables"])
    manual = wait_metadata(client, params, False)
    assert any(table["name"] == "private_pending" for table in manual["schema_snapshot"]["tables"])
    details = client.request("explorer.details", {"session_id": "a", "block_id": "same", "automatic_transactions": False,
                                                 "name": "private_pending", "schema": "temp", "temporary": True})
    assert details["columns"][0]["name"] == "id"
    rejected = client.response("explorer.use_database", {"session_id": "a", "block_id": "same",
                                                        "automatic_transactions": False, "database": "other-database"})
    assert rejected["error"]["code"] == "transaction_pending"
    with sqlite3.connect(path) as observer:
        assert observer.execute("SELECT * FROM records").fetchall() == []
    rollback = client.execute("ROLLBACK", "after-metadata", language="sql", block_id="same", scope_inherited=False,
                              disable_automatic_transactions=True)
    assert rollback["status"] == "succeeded" and rollback["transaction_state"]["pending"] is False


def test_late_policy_metadata_reply_does_not_overwrite_or_invalidate_other_policy():
    from collections import OrderedDict
    import threading
    from datapyn_runtime.supervisor import SessionRuntime
    runtime = SessionRuntime.__new__(SessionRuntime)
    runtime._lock = threading.RLock()
    runtime._pending_reset = None
    runtime.language_contexts = OrderedDict()
    runtime.language_version, runtime.language_variables = 0, {}
    runtime._context_codes, runtime._context_requests, runtime._queue = {}, set(), []
    runtime.session_id, messages = "session", []
    runtime.emit = messages.append
    params = {"connection_id": "db", "block_id": "same", "scope_inherited": False}
    for mode, names, invalidated in ((False, ["manual"], False), (True, ["automatic"], False), (False, [], True)):
        context = {"key": runtime.context_key({**params, "automatic_transactions": mode}), "connection_id": "db",
                   "block_id": "same", "automatic_transactions": mode, "variables": {},
                   "schema": {"tables": names}, "metadata_invalidated": invalidated, "metadata_invalidation_scope": "block"}
        runtime._receive({"language_context": context})
    assert runtime.editor_context({**params, "automatic_transactions": True}, refresh=False)["schema"]["tables"] == ["automatic"]
    assert messages[-1]["payload"]["automatic_transactions"] is False


def test_manual_schema_get_reads_uncommitted_and_temporary_owner_objects_without_finishing(tmp_path):
    from datapyn_runtime.database import schema
    connector = SQLiteConnector(str(database_file(tmp_path)), automatic_transactions=False)
    class ObservedConnection:
        def __init__(self, raw):
            self.raw = raw
            self.commits = self.rollbacks = self.closed = 0
        def __getattr__(self, name):
            return getattr(self.raw, name)
        def commit(self):
            self.commits += 1
            return self.raw.commit()
        def rollback(self):
            self.rollbacks += 1
            return self.raw.rollback()
        def close(self):
            self.closed += 1
            return self.raw.close()
    observed = ObservedConnection(connector.connection)
    connector.connection = observed
    try:
        connector.execute_query("BEGIN; CREATE TABLE pending_regular(id INTEGER); CREATE TEMP TABLE pending_temp(label TEXT)")
        result = schema(connector)
        objects = {(table["schema"], table["name"]): table for table in result["tables"]}
        assert objects[("main", "pending_regular")]["columns"] == [{"name": "id", "dtype": "INTEGER", "nullable": True}]
        assert objects[("temp", "pending_temp")]["columns"] == [{"name": "label", "dtype": "TEXT", "nullable": True}]
        assert result["schemas"] == ["main", "temp"]
        assert observed.in_transaction and (observed.commits, observed.rollbacks, observed.closed) == (0, 0, 0)
        with sqlite3.connect(connector.database) as observer:
            assert observer.execute("SELECT name FROM sqlite_master WHERE name='pending_regular'").fetchall() == []
        connector.execute_query("ROLLBACK")
    finally:
        connector.disconnect()


def test_production_manual_schema_get_borrows_owner_inspector_and_retains_public_shape(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from datapyn_runtime.database import schema
    calls = []
    engine, owner = object(), object()
    @contextmanager
    def borrowed():
        calls.append("borrow")
        yield owner
        calls.append("return_without_finishing")
    inspector = SimpleNamespace(get_schema_names=lambda: ["dbo"], get_table_names=lambda **_: ["pending_regular"],
                                get_columns=lambda *_args, **_kwargs: [{"name": "value", "type": "INTEGER", "nullable": False}])
    monkeypatch.setattr("sqlalchemy.inspect", lambda connection: inspector if connection is owner else pytest.fail("schema inspected an independent engine"))
    connector = SimpleNamespace(db_type="sqlserver", engine=engine, automatic_transactions=False,
                                connection_params={"database": "db"}, table_export_connection=borrowed,
                                _datapyn_temporary_tables={"#own": {"schema": "", "columns": [{"name": "id", "type": "BIGINT", "nullable": False}]}})
    result = schema(connector)
    assert result == {"db_type": "sqlserver", "database": "db", "schemas": ["dbo"], "tables": [
        {"name": "pending_regular", "schema": "dbo", "kind": "table", "columns": [{"name": "value", "dtype": "INTEGER", "nullable": False}]},
        {"name": "#own", "schema": "", "kind": "table", "columns": [{"name": "id", "dtype": "BIGINT", "nullable": False}]},
    ]}
    assert calls == ["borrow", "return_without_finishing"]
