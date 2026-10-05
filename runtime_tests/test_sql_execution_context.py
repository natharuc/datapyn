"""Context is observed on the executing DBAPI session, including partial errors."""

import re
from types import SimpleNamespace

import pyodbc
import pytest

from datapyn_runtime.database import ConnectorPool
from datapyn_runtime.explorer import ObjectExplorer
from datapyn_runtime.sql_context import changes_sql_context, sql_code_mask, sql_statements
from src.database.database_connector import DatabaseConnector


class PhysicalConnection:
    def __init__(self, db_type):
        self.db_type = db_type
        self.database = "before"
        self.schema = "public" if db_type == "postgresql" else "default" if db_type == "databricks" else "dbo"
        self.search_path = self.schema
        self.commands = []
        self.closed = 0
        self.temporary_tables = set()
        self.transaction_before = None
        self.local = False
        self.info = {}

    def cursor(self):
        return Cursor(self)

    def commit(self):
        if self.local and self.transaction_before:
            self.schema, self.search_path = self.transaction_before
        self.transaction_before = None
        self.local = False

    def rollback(self):
        if self.transaction_before:
            self.schema, self.search_path = self.transaction_before
        self.transaction_before = None
        self.local = False

    def close(self):
        # SQLAlchemy returns this physical session to its pool, without closing it.
        self.closed += 1


class Cursor:
    rowcount = -1
    messages = []

    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rows = []

    def execute(self, query, *params):
        physical = self.connection
        physical.commands.append(query)
        self.description, self.rows = None, []
        if query.startswith("SELECT DB_NAME()"):
            self.rows = [(physical.database, physical.schema)]
            return
        if query == "SELECT DATABASE()":
            self.rows = [(physical.database,)]
            return
        if query.startswith("SELECT current_catalog()"):
            self.rows = [(physical.database, physical.schema)]
            return
        if query.startswith("SELECT current_database()"):
            self.rows = [(physical.database, physical.schema, physical.search_path)]
            return
        if query == "SELECT CONNECTION_ID()":
            self.rows = [(123,)]
            return
        for command in sql_statements(query, physical.db_type):
            clean = sql_code_mask(command, physical.db_type).strip()
            if clean.upper().startswith("FAIL"):
                raise pyodbc.Error("statement failed")
            use = re.fullmatch(r"USE\s+(?:(CATALOG|DATABASE|SCHEMA)\s+)?(.+)", clean, re.I)
            if use:
                if physical.db_type == "postgresql":
                    raise pyodbc.Error("PostgreSQL does not support USE")
                target = use[2].strip().strip('`[]"')
                if target == "missing":
                    raise pyodbc.Error("context does not exist")
                kind = str(use[1] or "").upper()
                if physical.db_type == "databricks" and kind != "CATALOG":
                    names = [part.strip('`"') for part in target.split(".")]
                    if len(names) == 2:
                        physical.database, physical.schema = names
                    else:
                        physical.schema = target
                else:
                    physical.database = target
                    if physical.db_type == "databricks":
                        physical.schema = "default"
            elif clean.upper().startswith("SET "):
                schema_alias = re.fullmatch(r"SET\s+(?:(SESSION|LOCAL)\s+)?SCHEMA\s+'([^']+)'", command.strip(), re.I)
                if schema_alias:
                    clean = f"SET {schema_alias[1] or ''} search_path TO {schema_alias[2]}"
                match = re.fullmatch(r"SET\s+(?:(SESSION|LOCAL)\s+)?search_path\s*(?:TO|=)\s*(.+)", clean, re.I)
                if not match:
                    match = re.fullmatch(r"SET\s+(?:(SESSION|LOCAL)\s+)?search_path\s*(?:TO|=)\s*(.+)", command.strip(), re.I)
                if not match:
                    raise pyodbc.Error("invalid SET")
                if not physical.transaction_before:
                    physical.transaction_before = physical.schema, physical.search_path
                physical.local = str(match[1] or "").upper() == "LOCAL"
                physical.search_path = "" if match[2] == "''" else match[2]
                candidates = [part.strip().strip('"') for part in physical.search_path.split(",")]
                physical.schema = next((item for item in candidates if item in {"public", "reporting"}), "")
            elif clean.upper() == "COMMIT":
                physical.commit()
            elif clean.upper().startswith("SELECT"):
                self.description, self.rows = [("answer",)], [(42,)]
            elif clean.upper().startswith("CREATE TABLE #"):
                physical.temporary_tables.add(clean.split()[2].split("(")[0])

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchmany(self, size=1000):
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows

    def nextset(self):
        return False

    def close(self):
        pass


def make_connector(db_type):
    physical = PhysicalConnection(db_type)
    connector = DatabaseConnector()
    connector.db_type = db_type
    connector.connection_params = {"database": "before", "schema": physical.schema}
    if db_type == "databricks":
        connector.connection_params.update(databricks_catalog="before", databricks_schema=physical.schema)
    if db_type == "postgresql":
        connector.connection_params["postgresql_schema"] = physical.schema
    connector.engine = SimpleNamespace(raw_connection=lambda: physical, dialect=SimpleNamespace(default_schema_name="dbo"))
    return connector, physical


@pytest.mark.parametrize("db_type", ["sqlserver", "mysql", "mariadb", "postgresql", "databricks"])
def test_context_words_in_comments_strings_and_quoted_names_never_probe(db_type):
    code = "-- USE ignored\nSELECT 'USE nope; SET search_path TO fake', \"USE name\", `USE more` /* USE hidden */"
    assert not changes_sql_context(code, db_type)
    if db_type == "postgresql":
        assert not changes_sql_context("SELECT $$SET search_path TO fake;$$", db_type)
        assert not changes_sql_context('SELECT "SET search_path TO fake"', db_type)
    connector, physical = make_connector(db_type)
    connector.execute_query("SELECT 'USE nope' /* USE hidden */")
    assert not any("DB_NAME()" in query or query.startswith("SELECT DATABASE()") or query.startswith("SELECT current_") for query in physical.commands)


@pytest.mark.parametrize("db_type", ["sqlserver", "mysql", "mariadb"])
@pytest.mark.parametrize("suffix", ["", "; SELECT 42", "; FAIL"])
def test_database_switch_success_and_partial_failure(db_type, suffix):
    connector, physical = make_connector(db_type)
    code = "/* USE wrong */ USE [after]" if db_type == "sqlserver" else "-- comment\nUSE `after`"
    if suffix.endswith("FAIL"):
        with pytest.raises(Exception, match="statement failed"):
            connector.execute_query(code + suffix)
    else:
        connector.execute_query(code + suffix)
    assert connector.get_current_database() == physical.database == "after"
    assert physical.closed == 1
    assert sum("DB_NAME()" in query or query == "SELECT DATABASE()" for query in physical.commands) == 1


@pytest.mark.parametrize("db_type", ["sqlserver", "mysql", "mariadb", "databricks"])
def test_failed_use_does_not_change_connector_or_ui_context(db_type):
    connector, physical = make_connector(db_type)
    previous = ObjectExplorer(connector).context()
    with pytest.raises(Exception, match="context does not exist"):
        connector.execute_query("USE CATALOG missing" if db_type == "databricks" else "USE missing")
    assert ObjectExplorer(connector).context() == previous
    assert connector.get_current_database() == physical.database == "before"


@pytest.mark.parametrize(("command", "database", "schema"), [
    ("USE CATALOG `after`", "after", "default"),
    ("USE SCHEMA `reporting`", "before", "reporting"),
    ("USE DATABASE `reporting`", "before", "reporting"),
    ("USE `after`.`reporting`", "after", "reporting"),
    ("USE CATALOG after; USE SCHEMA reporting; SELECT 42", "after", "reporting"),
])
def test_databricks_distinguishes_catalog_and_schema_in_real_executed_statements(command, database, schema):
    connector, physical = make_connector("databricks")
    connector.execute_query(command)
    assert ObjectExplorer(connector).context() == {"db_type": "databricks", "database": database, "schema": schema}
    assert physical.database == database and physical.schema == schema
    assert all(";" not in query for query in physical.commands), "The driver accepts one statement per execute"


def test_databricks_successful_switch_before_error_remains_visible():
    connector, physical = make_connector("databricks")
    with pytest.raises(Exception, match="statement failed"):
        connector.execute_query("USE CATALOG after; USE DATABASE reporting; FAIL")
    assert connector.get_current_catalog() == physical.database == "after"
    assert connector.get_current_schema() == physical.schema == "reporting"


@pytest.mark.parametrize(("code", "expected", "error"), [
    ('SET search_path TO "reporting", public', "reporting", False),
    ('SET SESSION search_path = reporting; SELECT 42', "reporting", False),
    ('SET LOCAL search_path TO reporting; SELECT 42', "public", False),
    ('SET search_path TO reporting; FAIL', "public", True),
    ('SET search_path TO reporting; COMMIT; FAIL', "reporting", True),
    ('SET search_path TO nonexistent', "", False),
    ("SET search_path TO ''", "", False),
    ("SET SCHEMA 'reporting'", "reporting", False),
    ('USE DATABASE after', "public", True),
])
def test_postgresql_reports_committed_context_and_preserves_database(code, expected, error):
    connector, physical = make_connector("postgresql")
    if error:
        with pytest.raises(Exception):
            connector.execute_query(code)
    else:
        connector.execute_query(code)
    assert connector.get_current_database() == physical.database == "before"
    assert ObjectExplorer(connector).context()["schema"] == physical.schema == expected
    if not code.startswith("USE"):
        assert connector.connection_params["postgresql_search_path"] == physical.search_path


@pytest.mark.parametrize(("db_type", "code", "database", "schema"), [
    ("sqlserver", "USE after; SELECT 42", "after", "dbo"),
    ("mysql", "USE after; SELECT 42", "after", "after"),
    ("databricks", "USE CATALOG after; USE DATABASE reporting; SELECT 42", "after", "reporting"),
    ("postgresql", "SET search_path TO reporting; SELECT 42", "before", "reporting"),
    ("postgresql", "SET LOCAL search_path TO reporting; SELECT 42", "before", "public"),
])
def test_streaming_download_reconciles_the_same_physical_context(db_type, code, database, schema, tmp_path, monkeypatch):
    connector, physical = make_connector(db_type)
    monkeypatch.setattr(connector, "_stream_write_result_set", lambda *args, **kwargs: True)
    connector.stream_query_to_files(code, base_path=tmp_path / "result.csv", export_format="csv")
    assert ObjectExplorer(connector).context() == {"db_type": db_type, "database": database, "schema": schema}
    assert physical.closed == 1


@pytest.mark.parametrize("collision", [False, True])
def test_pool_moves_switched_physical_session_without_old_alias_or_lost_temp_tables(monkeypatch, collision):
    created = []
    def connect(config):
        connector, physical = make_connector("sqlserver")
        connector.connection_params.update(database=config["database"], schema=config.get("schema") or "dbo")
        physical.database = config["database"]
        connector.has_temporary_tables = True
        connector.disconnect = lambda: pytest.fail("A retained temporary session must stay connected")
        created.append(connector)
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": "sqlserver", "database": "before"}
    params = {"config": config, "connection_id": "profile", "database": "before", "block_id": "one"}
    if collision:
        existing = pool.activate({**params, "database": "after", "schema": "dbo", "block_id": "two"})
    original = pool.activate(params)
    explorer = pool.explorer()
    original.execute_query("CREATE TABLE #scratch(id int); USE after")
    physical = original.engine.raw_connection()
    assert "#scratch" in physical.temporary_tables
    pool.reindex_active(explorer.context(), params)
    updated = {**params, "database": "after", "schema": "dbo"}
    assert pool.activate(updated) is original
    assert pool.explorer() is explorer
    assert pool.activate({key: value for key, value in updated.items() if key != "block_id"}) is original
    assert pool.activate({**params, "block_id": "three"}) is not original
    assert "#scratch" in physical.temporary_tables
    assert pool.activate(updated) is original
    if collision:
        assert pool.activate({**updated, "block_id": "two"}) is existing


def test_inherited_change_updates_default_and_reuses_same_connector(monkeypatch):
    connector, physical = make_connector("mysql")
    monkeypatch.setattr("datapyn_runtime.database.connect", lambda config: connector)
    pool = ConnectorPool()
    pool.activate({"config": {"db_type": "mysql", "database": "before"}, "connection_id": "profile"}, default=True)
    connector.execute_query("USE after")
    pool.reindex_active(ObjectExplorer(connector).context(), {"block_id": "one"})
    assert pool.default_config["database"] == "after"
    assert pool.activate({"block_id": "two"}) is connector


def test_postgresql_empty_resolved_scope_does_not_alias_public_or_reconnect(monkeypatch):
    created = []
    def connect(config):
        connector, physical = make_connector("postgresql")
        created.append(connector)
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": "postgresql", "database": "before"}
    params = {"config": config, "connection_id": "profile", "block_id": "one"}
    original = pool.activate(params, default=True)
    original.execute_query("SET search_path TO nonexistent")
    pool.reindex_active(pool.explorer().context(), params)
    assert pool.default_config["postgresql_search_path"] == "nonexistent"
    assert pool.activate({**params, "schema": ""}) is original
    assert pool.activate({"block_id": "one"}) is original
    assert pool.activate({**params, "schema": "public", "block_id": "two"}) is not original
    assert len(created) == 2


def test_repeated_collision_retains_both_changed_physical_sessions(monkeypatch):
    def connect(config):
        connector, physical = make_connector("sqlserver")
        connector.connection_params["database"] = physical.database = config["database"]
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": "sqlserver", "database": "before"}
    params = {"config": config, "connection_id": "profile", "block_id": "one"}
    pool.activate({**params, "database": "after", "schema": "dbo", "block_id": "two"})
    originals = []
    for _ in range(2):
        original = pool.activate(params)
        original.execute_query("USE after")
        pool.reindex_active(pool.explorer().context(), params)
        originals.append(original)
    assert len(pool.items) == 3
    assert all(connector in pool.items.values() for connector in originals)


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "databricks"])
def test_checkout_applies_changed_namespace_once_per_physical_connection(db_type, monkeypatch):
    connector, physical = make_connector(db_type)
    connector._connection_config = {"database": "before", "schema": physical.schema}
    captured = []
    monkeypatch.setattr("src.database.database_connector.event.listens_for", lambda *args: lambda handler: captured.append(handler))
    connector._register_engine_checkout_hooks(db_type)
    handler = captured[0]
    record = SimpleNamespace(info=physical.info)
    handler(physical, record, None)
    assert physical.commands == []
    connector.execute_query("USE CATALOG after" if db_type == "databricks" else "USE after")
    commands = list(physical.commands)
    handler(physical, record, None)
    assert physical.commands == commands, "A reconciled connection needs no additional USE"
    second = PhysicalConnection(db_type)
    second_record = SimpleNamespace(info=second.info)
    handler(second, second_record, None)
    assert len(second.commands) == (2 if db_type == "databricks" else 1)
    handler(second, second_record, None)
    assert len(second.commands) == (2 if db_type == "databricks" else 1)
    assert second.database == "after"


def test_databricks_compound_statement_retains_internal_semicolons():
    code = "/* leading */ BEGIN SELECT 1; SELECT 2; END"
    assert sql_statements(code, "databricks") == [code]
    routine = "CREATE OR REPLACE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END"
    assert sql_statements(routine, "databricks") == [routine]


def test_postgresql_set_config_search_path_trigger_ignores_other_settings_and_literals():
    assert changes_sql_context("SELECT set_config('search_path', 'reporting,public', false)", "postgresql")
    assert not changes_sql_context("SELECT set_config('statement_timeout', '1000', false)", "postgresql")
    assert not changes_sql_context("SELECT 'set_config(''search_path'', ''fake'', false)'", "postgresql")


@pytest.mark.parametrize("literal", [r"'it\'s; ok'", r'"it\"s; ok"', r"r'backslash\; intact'"])
def test_databricks_escaped_and_raw_literals_keep_inner_semicolons(literal):
    assert sql_statements(f"SELECT {literal}; USE SCHEMA reporting", "databricks") == [f"SELECT {literal}", "USE SCHEMA reporting"]
    assert not changes_sql_context(f"SELECT {literal}", "databricks")


def run_kernel_jobs(monkeypatch, tmp_path, connector, executions):
    from datapyn_runtime import kernel
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path))
    monkeypatch.setattr(kernel, "initialize_kernel_group", lambda: None)
    monkeypatch.setattr(kernel, "isolate_kernel_output", lambda: None)
    monkeypatch.setattr(kernel, "_watch_parent", lambda: None)
    monkeypatch.setattr(kernel, "enable_user_packages", lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.database.connect", lambda config: connector)
    connector.disconnect = lambda: None
    config = {"db_type": connector.db_type, "database": "before"}
    jobs = [{"method": "connection.connect", "params": {"connection_id": "profile", "config": config}, "job_id": "connect"}]
    for index, params in enumerate(executions):
        jobs.append({"method": "execution.run", "params": {
            "execution_id": str(index), "language": "sql", "block_id": "one", "connection_id": "profile", "config": config, "database": "before", **params,
        }, "job_id": str(index)})
    jobs.append({"method": "shutdown", "params": {}, "job_id": "shutdown"})
    class Commands:
        def poll(self, timeout):
            return True
        def recv(self):
            return jobs.pop(0)
        def close(self):
            pass
    messages = []
    kernel.kernel_main("session", Commands(), SimpleNamespace(send=messages.append, close=lambda: None))
    return messages


@pytest.mark.parametrize(("db_type", "code", "database", "schema", "status"), [
    ("sqlserver", "USE after", "after", "dbo", "succeeded"),
    ("sqlserver", "USE after; FAIL", "after", "dbo", "failed"),
    ("mysql", "USE after; FAIL", "after", "after", "failed"),
    ("databricks", "USE CATALOG after; USE DATABASE reporting; FAIL", "after", "reporting", "failed"),
    ("postgresql", "SET search_path TO reporting; COMMIT; FAIL", "before", "reporting", "failed"),
])
def test_kernel_finished_context_and_namespace_match_actual_session_even_after_error(db_type, code, database, schema, status, monkeypatch, tmp_path):
    connector, physical = make_connector(db_type)
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [
        {"code": code},
        {"language": "python", "database": database, "schema": schema,
         "code": f"assert db_database == {database!r}; assert db_schema == {schema!r}"},
    ])
    finished = [item["payload"] for item in messages if item.get("event") == "execution.finished"]
    assert finished[0]["status"] == status
    assert finished[0]["block_id"] == "one"
    change = finished[0]["context_change"]
    assert change["connection_id"] == "profile"
    assert change["requested_scope"] == {"connection_id": "profile", "database": "before", "schema": None}
    assert change["current"] == {"db_type": db_type, "database": database, "schema": schema}
    assert change["previous"]["database"] == "before"
    assert finished[1]["status"] == "succeeded", finished[1]
    invalidation = next(item["language_context"] for item in messages if item.get("language_context", {}).get("metadata_invalidated"))
    assert invalidation["block_id"] == "one"
    assert invalidation["key"] == f"profile|{database}|{schema}|block:one"
    assert invalidation["database"] == database and invalidation["schema_name"] == schema
    assert invalidation["metadata_invalidation_scope"] == "block"


def test_kernel_failed_use_has_no_context_change_or_metadata_invalidation(monkeypatch, tmp_path):
    connector, physical = make_connector("mysql")
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "USE missing"}])
    finished = next(item["payload"] for item in messages if item.get("event") == "execution.finished")
    assert finished["status"] == "failed" and "context_change" not in finished
    assert not any(item.get("language_context", {}).get("metadata_invalidated") for item in messages)


def test_kernel_same_primary_search_path_change_invalidates_without_ui_change(monkeypatch, tmp_path):
    connector, physical = make_connector("postgresql")
    connector.connection_params.update(postgresql_search_path="public, old", postgresql_schema="public", schema="public")
    physical.search_path = "public, old"
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "SET search_path TO public, new"}])
    finished = next(item["payload"] for item in messages if item.get("event") == "execution.finished")
    assert finished["status"] == "succeeded" and "context_change" not in finished
    assert any(item.get("language_context", {}).get("metadata_invalidated") for item in messages)


def test_kernel_download_reports_changed_scope_without_materializing_frames(monkeypatch, tmp_path):
    connector, physical = make_connector("mysql")
    destination = tmp_path / "rows.csv"
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "USE after; SELECT 42", "export": {
        "path": str(destination), "format": "csv", "options": {},
    }}])
    finished = next(item["payload"] for item in messages if item.get("event") == "execution.finished")
    assert finished["status"] == "succeeded", finished
    assert finished["context_change"]["current"]["database"] == "after"
    assert finished["results"] == []
    assert destination.read_text(encoding="utf-8-sig").splitlines() == ["answer", "42"]


def test_inherited_collision_keeps_changed_default_family_and_isolates_pinned_peer(monkeypatch):
    def connect(config):
        connector, physical = make_connector("sqlserver")
        connector.connection_params["database"] = physical.database = config["database"]
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": "sqlserver", "database": "before"}
    before = {"config": config, "connection_id": "profile", "database": "before", "schema": "dbo"}
    after = {**before, "database": "after"}
    pinned = pool.activate({**after, "block_id": "pinned"})
    original = pool.activate({**before, "block_id": "one", "scope_inherited": True}, default=True)
    original.execute_query("CREATE TABLE #scratch(id int); USE after")
    pool.reindex_active(pool.explorer().context(), {**before, "block_id": "one", "scope_inherited": True})
    assert pool.activate({**after, "block_id": "two", "scope_inherited": True}) is original
    assert pool.activate({**after, "block_id": "pinned"}) is pinned
    assert pool.activate({**after, "block_id": "two", "scope_inherited": True}) is original
    assert "#scratch" in original.engine.raw_connection().temporary_tables


def test_sqlserver_schema_default_fallback_does_not_replace_existing_peer(monkeypatch):
    def connect(config):
        connector, physical = make_connector("sqlserver")
        connector.connection_params["database"] = physical.database = config["database"]
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": "sqlserver", "database": "before"}
    params = {"config": config, "connection_id": "profile", "database": "before", "block_id": "one"}
    peer_scope = {**params, "database": "after", "block_id": "peer"}
    peer = pool.activate(peer_scope)
    original = pool.activate(params)
    original.execute_query("USE after")
    pool.reindex_active(pool.explorer().context(), params)
    assert pool.activate(peer_scope) is peer


@pytest.mark.parametrize("path", ["nonexistent", ""])
def test_postgresql_resolved_empty_path_survives_idle_recreation(path, monkeypatch):
    configs = []
    def connect(config):
        configs.append(dict(config))
        connector, physical = make_connector("postgresql")
        connector.disconnect = lambda: None
        if "postgresql_search_path" in config:
            connector.connection_params.update(postgresql_search_path=config["postgresql_search_path"], postgresql_schema=config["schema"], schema=config["schema"])
        return connector
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool(idle_timeout=1)
    params = {"connection_id": "profile", "config": {"db_type": "postgresql", "database": "before"}, "block_id": "one", "schema": "public"}
    connector = pool.activate(params)
    connector.execute_query(f"SET search_path TO {path or chr(39) + chr(39)}")
    pool.reindex_active(pool.explorer().context(), params)
    pool.last_used[pool.active_key] = 0
    assert pool.reap_idle() == ["profile"]
    recreated = pool.activate({**params, "schema": ""})
    assert recreated is not connector
    assert configs[-1]["schema"] == "" and configs[-1]["postgresql_search_path"] == path
    assert ObjectExplorer(recreated).context()["schema"] == ""


def test_postgresql_checkout_preserves_explicit_empty_search_path(monkeypatch):
    connector, physical = make_connector("postgresql")
    connector.connection_params.update(postgresql_search_path="", postgresql_schema="", schema="")
    captured = []
    monkeypatch.setattr("src.database.database_connector.event.listens_for", lambda *args: lambda handler: captured.append(handler))
    connector._register_engine_checkout_hooks("postgresql")
    captured[0](physical, SimpleNamespace(info={}), None)
    assert physical.commands == ["SET search_path TO ''"]
    assert physical.schema == ""


def test_kernel_inherited_context_key_and_default_namespace_are_explicit(monkeypatch, tmp_path):
    connector, physical = make_connector("mysql")
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "USE after", "scope_inherited": True}])
    context = next(item["language_context"] for item in messages if item.get("language_context", {}).get("metadata_invalidated"))
    assert context["key"] == "profile|after|after|block:one|scope:inherited"
    assert context["scope_inherited"] is True


@pytest.mark.parametrize("inherited", [False, True])
def test_kernel_finished_preserves_captured_inheritance_flag(inherited, monkeypatch, tmp_path):
    connector, physical = make_connector("mysql")
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{"code": "USE after", "scope_inherited": inherited}])
    finished = next(item["payload"] for item in messages if item.get("event") == "execution.finished")
    assert finished["block_id"] == "one"
    assert finished["scope_inherited"] is inherited
