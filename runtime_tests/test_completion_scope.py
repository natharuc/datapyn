"""Connection scopes must match the metadata used by actual editor requests."""

from collections import OrderedDict, deque
import sqlite3
import threading
from types import SimpleNamespace

import pandas as pd
import pytest

from datapyn_runtime.database import ConnectorPool, SQLiteConnector
from datapyn_runtime.explorer import ObjectExplorer
from datapyn_runtime.language import dispatch
from datapyn_runtime.sql_context import metadata_signature
from datapyn_runtime.supervisor import Job, MAX_QUEUED_JOBS, SessionRuntime


@pytest.mark.parametrize(("db_type", "schema"), [
    ("sqlserver", "dbo"), ("mysql", "warehouse"), ("mariadb", "warehouse"),
    ("postgresql", "reporting"), ("databricks", "finance"),
])
def test_native_schema_getter_does_not_replace_other_driver_context(db_type, schema, monkeypatch):
    class Connector:
        connection_params = {"database": "warehouse", "postgresql_schema": "reporting", "databricks_schema": "finance"}
        def get_current_database(self):
            return self.connection_params["database"]
        def get_current_schema(self):
            # This is the production connector's actual fallback behavior.
            return self.connection_params["postgresql_schema"] if self.db_type == "postgresql" else self.connection_params["databricks_schema"] if self.db_type == "databricks" else "default"
        def execute_query(self, query):
            return pd.DataFrame({"name": [schema if "SHOW SCHEMAS" in query else "warehouse"]})
    class Inspector:
        def get_schema_names(self):
            return [schema]
        def get_table_names(self, *, schema):
            assert schema == expected_schema
            return ["sales"]
        def get_view_names(self, *, schema):
            assert schema == expected_schema
            return []
        def get_columns(self, name, *, schema):
            assert name == "sales" and schema == expected_schema
            return [{"name": "amount", "type": "INTEGER"}]
    connector = Connector()
    connector.db_type = db_type
    expected_schema = schema
    monkeypatch.setattr("sqlalchemy.inspect", lambda engine: Inspector())
    connector.engine = object()
    explorer = ObjectExplorer(connector)
    assert explorer.context()["schema"] == schema
    snapshot = explorer.completion_schema("SELECT s. FROM sales s")
    assert snapshot["current_schema"] == schema
    result = dispatch("language.complete", {"language": "sql", "code": "SELECT s. FROM sales s", "line": 1, "column": 10}, {"schema": snapshot})
    assert {item["label"] for item in result["items"]} == {"amount"}


def test_sqlserver_snapshot_keeps_qualified_identity_but_suggests_bare_focused_tables(monkeypatch):
    class Inspector:
        def get_schema_names(self):
            return ["dbo"]
        def get_table_names(self, *, schema):
            assert schema == "dbo"
            return ["Sales"]
        def get_view_names(self, *, schema):
            return []
        def get_columns(self, name, *, schema):
            assert (schema, name) == ("dbo", "Sales")
            return [{"name": "ID", "type": "INTEGER"}]
    connector = SimpleNamespace(db_type="sqlserver", connection_params={"database": "ESIM"}, engine=object(),
                                execute_query=lambda query: pd.DataFrame({"name": ["ESIM"]}))
    monkeypatch.setattr("sqlalchemy.inspect", lambda engine: Inspector())
    snapshot = ObjectExplorer(connector).completion_schema("SELECT s. FROM Sales s")
    assert snapshot["database"] == "ESIM" and snapshot["current_schema"] == snapshot["schema"] == "dbo"
    assert snapshot["tables"] == [{"name": "Sales", "schema": "dbo", "catalog": "ESIM", "key": "ESIM.dbo.Sales", "type": "TABLE"}]
    assert snapshot["columns"]["ESIM.dbo.Sales"][0]["name"] == "ID"
    for code in ("SELECT * FROM ", "SELECT "):
        result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": len(code) + 1}, {"schema": snapshot})
        assert [item for item in result["items"] if item["kind"] == "table"] == [
            {"label": "Sales", "kind": "table", "detail": "TABLE - ESIM.dbo.Sales", "category": "table", "insert_text": "[Sales]"},
        ]
    result = dispatch("language.complete", {"language": "sql", "code": "SELECT s. FROM Sales s", "line": 1, "column": 10}, {"schema": snapshot})
    assert {item["label"] for item in result["items"]} == {"ID"}


def test_runtime_adapter_retains_sqlserver_metadata_schema_discarded_by_reused_driver(monkeypatch):
    import src.database.database_connector as production
    from datapyn_runtime.database import connect
    class Connector:
        SUPPORTED_DATABASES = {"sqlserver"}
        def connect(self, **options):
            self.db_type = options["db_type"]
            # This is the reused SQL Server driver's actual public config shape.
            self.connection_params = {"database": options["database"]}
            return True
        def is_connected(self):
            return True
    monkeypatch.setattr(production, "DatabaseConnector", Connector)
    config = {"db_type": "sqlserver", "database": "ESIM", "schema": "reporting"}
    connector = connect(config)
    assert connector.connection_params == {"database": "ESIM", "schema": "reporting"}
    assert ObjectExplorer(connector).context() == {"db_type": "sqlserver", "database": "ESIM", "schema": "reporting"}
    assert config == {"db_type": "sqlserver", "database": "ESIM", "schema": "reporting"}


@pytest.mark.parametrize(("physical", "selected", "expected_default", "expected_focus"), [
    ("dbo", "", "dbo", "dbo"),
    ("finance", "", "finance", "finance"),
    (None, "", "dbo", "dbo"),
    ("", "", "dbo", "dbo"),
    ("dbo", "reporting", "dbo", "reporting"),
    ("finance", "reporting", "finance", "reporting"),
    (None, "reporting", "dbo", "reporting"),
])
def test_sqlserver_login_default_is_separate_from_selected_metadata_schema(physical, selected, expected_default, expected_focus, monkeypatch):
    class Inspector:
        def get_schema_names(self):
            return ["dbo", "finance", "reporting"]
        def get_table_names(self, *, schema):
            assert schema == expected_focus
            return ["Sales"]
        def get_view_names(self, *, schema):
            return []
    queries = []
    def execute(query):
        queries.append(query)
        return pd.DataFrame({"name": ["ESIM"]})
    config = {"database": "ESIM", **({"schema": selected} if selected else {})}
    engine = SimpleNamespace(dialect=SimpleNamespace(default_schema_name=physical))
    connector = SimpleNamespace(db_type="sqlserver", connection_params=config, engine=engine, execute_query=execute)
    monkeypatch.setattr("sqlalchemy.inspect", lambda engine: Inspector())
    explorer = ObjectExplorer(connector)
    snapshot = explorer.completion_schema()
    assert snapshot["default_schema"] == expected_default
    assert snapshot["current_schema"] == snapshot["schema"] == expected_focus
    assert snapshot["tables"][0]["key"] == f"ESIM.{expected_focus}.Sales"
    code = "SELECT * FROM "
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": len(code) + 1}, {"schema": snapshot})
    assert {item["label"] for item in result["items"] if item["kind"] == "table"} == {"Sales"}
    before = list(queries)
    for _ in range(10):
        assert explorer.context()["schema"] == expected_focus
        assert explorer.sqlserver_default_schema() == expected_default
    assert queries == before


def test_sqlite_current_context_prepares_actual_attached_relations():
    connector = SQLiteConnector(":memory:")
    try:
        connector.execute_query("CREATE TABLE sample(id INTEGER)")
        snapshot = ObjectExplorer(connector).completion_schema("SELECT s. FROM main.sample s")
        assert snapshot["current_schema"] == "main"
        assert snapshot["columns"]["main.sample"][0]["name"] == "id"
    finally:
        connector.disconnect()


@pytest.mark.parametrize("db_type", ["postgresql", "databricks", "sqlserver", "mysql", "mariadb"])
def test_switching_database_resets_inherited_schema_but_preserves_explicit_schema(db_type, monkeypatch):
    configs = []
    def connect(config):
        configs.append(dict(config))
        return SimpleNamespace(disconnect=lambda: None)
    monkeypatch.setattr("datapyn_runtime.database.connect", connect)
    pool = ConnectorPool()
    config = {"db_type": db_type, "database": "before", "schema": "old_schema", "postgresql_schema": "old_schema", "databricks_schema": "old_schema"}
    pool.activate({"config": config, "database": "after"})
    assert configs[-1]["database"] == "after"
    assert not {"schema", "postgresql_schema", "databricks_schema"}.intersection(configs[-1])
    pool.activate({"config": config, "database": "after", "schema": "chosen_schema"})
    assert configs[-1]["schema"] == "chosen_schema"
    assert config["schema"] == "old_schema"


def test_postgres_database_picker_lists_only_connectable_non_template_databases():
    queries = []
    def execute(query):
        queries.append(query)
        return pd.DataFrame({"datname": ["accounts", "warehouse"]})
    explorer = ObjectExplorer(SimpleNamespace(db_type="postgresql", connection_params={"database": "warehouse"}, execute_query=execute))
    assert explorer.databases() == ["accounts", "warehouse"]
    assert "has_database_privilege(datname, 'CONNECT')" in queries[0]
    assert "datallowconn AND NOT datistemplate" in queries[0]


def test_denied_database_discovery_does_not_disable_local_completion(monkeypatch):
    connector = SQLiteConnector(":memory:")
    try:
        connector.execute_query("CREATE TABLE sample(title TEXT)")
        explorer = ObjectExplorer(connector)
        monkeypatch.setattr(explorer, "databases", lambda: (_ for _ in ()).throw(PermissionError("catalog unavailable")))
        snapshot = explorer.completion_schema("SELECT s. FROM sample s")
        assert snapshot["databases"] == [":memory:"]
        assert snapshot["columns"]["main.sample"][0]["name"] == "title"
    finally:
        connector.disconnect()


def test_catalog_beyond_ten_thousand_names_keeps_lazy_columns_and_last_table(monkeypatch):
    loaded_columns = []
    class Inspector:
        def get_schema_names(self):
            return ["dbo"]
        def get_table_names(self, *, schema):
            return [f"sample_{index:05d}" for index in range(12001)]
        def get_view_names(self, *, schema):
            return []
        def get_columns(self, name, *, schema):
            loaded_columns.append((schema, name))
            return [{"name": "late_catalog_value", "type": "INTEGER"}]
    connector = SimpleNamespace(db_type="sqlserver", connection_params={"database": "warehouse"}, engine=object(),
                                execute_query=lambda query: pd.DataFrame({"name": ["warehouse"]}))
    monkeypatch.setattr("sqlalchemy.inspect", lambda engine: Inspector())
    explorer = ObjectExplorer(connector)
    empty = explorer.completion_schema()
    assert len(empty["tables"]) == 12001 and loaded_columns == []
    code = "SELECT t. FROM sample_12000 t"
    snapshot = explorer.completion_schema(code)
    assert loaded_columns == [("dbo", "sample_12000")]
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": snapshot})
    assert {item["label"] for item in result["items"]} == {"late_catalog_value"}
    explorer.completion_schema(code)
    assert loaded_columns == [("dbo", "sample_12000")]


def test_database_discovery_keeps_names_beyond_old_five_thousand_cutoff():
    names = [f"database_{index:05d}" for index in range(6001)]
    connector = SimpleNamespace(db_type="postgresql", connection_params={"database": names[0]},
                                execute_query=lambda query: pd.DataFrame({"datname": names}))
    assert ObjectExplorer(connector).databases() == names


@pytest.mark.parametrize(("db_type", "quoted"), [
    ("sqlserver", "[reporting].[customers]"), ("postgresql", '"reporting"."customers"'),
    ("mysql", "`reporting`.`customers`"), ("mariadb", "`reporting`.`customers`"),
    ("databricks", "`reporting`.`customers`"), ("sqlite", '"reporting"."customers"'),
])
def test_comma_sources_use_dialect_lexer_without_select_or_function_noise(db_type, quoted):
    code = f"SELECT coalesce(s.amount, 0), c.title FROM sales s, {quoted} c WHERE c.title IN ('FROM fake, ignored', 'also ignored')"
    references, _, _ = metadata_signature(code, db_type)
    assert references == (("reporting", "customers"), ("sales",))
    references, _, _ = metadata_signature(code + "; SELECT one, two", db_type)
    assert references == (("reporting", "customers"), ("sales",))


def test_comma_sources_respect_subquery_depth_comments_and_incomplete_quoted_fields():
    code = "SELECT q.value, c.name FROM (SELECT id, value FROM inner_source i, inner_second j) q, customers c /* , fake */ WHERE c.name = 'literal, fake'"
    assert metadata_signature(code)[0] == (("customers",), ("inner_second",), ("inner_source",))
    code = 'SELECT id FROM source s, customers c WHERE c."unfinished'
    assert metadata_signature(code)[0] == (("customers",), ("source",))
    assert metadata_signature("SELECT a FROM first_source\nGO\nSELECT one, two", "sqlserver")[0] == (("first_source",),)


def test_comma_join_lazily_loads_both_physical_tables_in_real_sqlite():
    connector = SQLiteConnector(":memory:")
    try:
        connector.execute_query("CREATE TABLE sales(amount INTEGER); CREATE TABLE customers(name TEXT); CREATE TABLE untouched(skip TEXT)")
        code = "SELECT c. FROM sales s, customers c"
        snapshot = ObjectExplorer(connector).completion_schema(code)
        assert set(snapshot["columns"]) == {"main.sales", "main.customers"}
        result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": snapshot})
        assert {item["label"] for item in result["items"]} == {"name"}
    finally:
        connector.disconnect()


@pytest.mark.parametrize(("current_schema", "expected"), [("reporting", "reporting_value"), ("Reporting", "quoted_schema_value")])
def test_postgres_unqualified_relations_follow_selected_schema_instead_of_public(current_schema, expected):
    snapshot = {"db_type": "postgresql", "database": "warehouse", "current_schema": current_schema,
                "tables": [{"name": "sample", "schema": name, "key": f"{name}.sample"} for name in ("public", "reporting", "Reporting")]
                          + [{"name": "other", "schema": "public", "key": "public.other"}],
                "columns": {"public.sample": [{"name": "public_value"}], "reporting.sample": [{"name": "reporting_value"}],
                            "Reporting.sample": [{"name": "quoted_schema_value"}], "public.other": [{"name": "other_value"}]}}
    code = "SELECT s. FROM sample s JOIN public.other o ON true"
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": snapshot})
    assert {item["label"] for item in result["items"]} == {expected}


def session_stub():
    session = SessionRuntime.__new__(SessionRuntime)
    session._lock = threading.RLock()
    session._wake = threading.Event()
    session._closed = session._failed = False
    session._queue = deque()
    session.language_contexts = OrderedDict()
    session.language_variables = {"frame": {"type": "DataFrame", "columns": ["title"]}}
    session.language_version = 4
    session._context_codes = {}
    session._context_requests = set()
    return session


def test_prepare_is_deduplicated_and_force_bypasses_metadata_ttl():
    session = session_stub()
    params = {"connection_id": "saved", "database": "database", "schema": "public", "code": "SELECT t. FROM sample t"}
    assert session.prepare_context(params) == {"status": "queued", "context_version": 4}
    assert session.prepare_context(params) == {"status": "queued", "context_version": 4}
    assert len(session._queue) == 1 and session._queue[0].method == "language.context"
    assert session._queue[0].params["language"] == "sql"
    key = session.context_key(params)
    session._queue.clear()
    session._context_requests.clear()
    session.language_contexts[key] = {"schema": {"db_type": "postgresql"}}
    assert session.prepare_context(params)["status"] == "ready"
    assert not session._queue
    assert session.prepare_context({**params, "refresh": True})["status"] == "queued"
    assert session._queue[0].params["refresh"] is True


def test_prepare_queue_pressure_never_silently_reports_ready_for_missing_context():
    session = session_stub()
    session._queue.extend(Job("namespace.snapshot", {}) for _ in range(MAX_QUEUED_JOBS))
    with pytest.raises(Exception, match="64 queued"):
        session.prepare_context({"connection_id": "saved", "code": ""})
    assert not session._context_requests


def test_pending_metadata_coalesces_changed_relations_and_keeps_forced_reload():
    session = session_stub()
    params = {"connection_id": "saved", "code": "SELECT a. FROM first_table a"}
    session.prepare_context(params)
    session.prepare_context({**params, "code": "SELECT b. FROM second_table b", "refresh": True})
    session.prepare_context({**params, "code": "SELECT c. FROM third_table c"})
    assert len(session._queue) == 1
    assert session._queue[0].params["code"] == "SELECT c. FROM third_table c"
    assert session._queue[0].params["refresh"] is True
    # Simulate the kernel starting its metadata request. Follow-up documents
    # must still be collapsed into one queued request while that crawl runs.
    session._queue.popleft()
    session.prepare_context({**params, "code": "SELECT d. FROM fourth_table d"})
    session.prepare_context({**params, "code": "SELECT e. FROM fifth_table e"})
    assert len(session._queue) == 1 and session._queue[0].params["code"] == "SELECT e. FROM fifth_table e"


def test_error_context_preserves_namespace_and_exposes_requested_scope():
    session = session_stub()
    session.session_id = "session"
    session._pending_reset = None
    messages = []
    session.emit = messages.append
    key = "saved|warehouse|finance"
    session.language_contexts[key] = {"schema": {"tables": [{"name": "obsolete"}]}}
    session._receive({"language_context": {"key": key, "schema": {}, "variables": session.language_variables,
                     "connection_id": "saved", "database": "warehouse", "schema_name": "finance", "schema_complete": False,
                     "metadata_state": "error", "schema_error": "PermissionError: unavailable",
                     "requested_scope": {"connection_id": "saved", "database": "warehouse", "schema": "finance"}}})
    payload = messages[-1]["payload"]
    assert payload["schema_snapshot"] == {} and payload["metadata_state"] == "error"
    assert payload["schema_error"] == "PermissionError: unavailable"
    assert payload["requested_scope"]["schema"] == "finance"
    assert payload["variables"]["frame"]["columns"] == ["title"]
    assert session.language_contexts[key]["schema"] == {}
