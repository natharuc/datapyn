from __future__ import annotations

import sys
import os
import subprocess
import time
import json

import pytest

from datapyn_runtime.database import SQLiteConnector
from datapyn_runtime.database import ConnectorPool
from datapyn_runtime.explorer import ObjectExplorer, quote
from datapyn_runtime.language import dispatch
from datapyn_runtime.language import namespace_snapshot
from datapyn_runtime.kernel import ResultStore
from datapyn_runtime.values import scalar
from test_runtime import Client, ROOT


@pytest.fixture
def connector():
    connector = SQLiteConnector(":memory:")
    connector.execute_query("CREATE TABLE sample(id INTEGER PRIMARY KEY, title TEXT); CREATE VIEW titles AS SELECT title FROM sample;")
    yield connector
    connector.disconnect()


def test_explorer_loads_tables_without_columns_then_caches_column_request(connector):
    explorer = ObjectExplorer(connector)
    queries = []
    connector.connection.set_trace_callback(queries.append)
    root = explorer.list({})
    assert root["nodes"][0]["name"] == "main"
    schema = explorer.list({"node": root["nodes"][0]})["nodes"][0]
    category = explorer.list({"node": schema})["nodes"][0]
    tables = explorer.list({"node": category})
    assert [node["name"] for node in tables["nodes"]] == ["sample"]
    assert not any("table_xinfo" in query.lower() or "table_info" in query.lower() for query in queries)
    columns = explorer.list({"node": tables["nodes"][0]})
    assert [node["name"] for node in columns["nodes"]] == ["id", "title"]
    count = len(queries)
    assert explorer.list({"node": tables["nodes"][0]}) == columns
    assert len(queries) == count
    details = explorer.details({"name": "sample", "schema": "main"})
    assert details["primary_key"]["constrained_columns"] == ["id"]
    assert "CREATE TABLE sample" in details["definition"]


def test_explorer_query_quotes_identifiers_and_validates_row_limit(connector):
    explorer = ObjectExplorer(connector)
    assert '"main"."bad""name"' in explorer.query({"name": 'bad"name'})["code"]
    assert quote("sqlserver", "dbo", "a]b") == "[dbo].[a]]b]"
    assert quote("mysql", "a`b") == "`a``b`"
    with pytest.raises(ValueError):
        explorer.query({"name": "sample", "limit": 0})


def test_completion_lazily_loads_only_referenced_cross_schema_columns(connector):
    connector.execute_query("ATTACH DATABASE ':memory:' AS reporting; CREATE TABLE reporting.sales(amount INTEGER, product TEXT);")
    explorer = ObjectExplorer(connector)
    schema = explorer.completion_schema("SELECT s. FROM reporting.sales s")
    assert "reporting" in schema["schemas"]
    assert "reporting.sales" in schema["columns"]
    assert "main.sample" not in schema["columns"]
    result = dispatch("language.complete", {"language": "sql", "code": "SELECT s. FROM reporting.sales s", "line": 1, "column": 10}, {"schema": schema})
    assert {"amount", "product"} <= {item["label"] for item in result["items"]}


def test_sqlserver_explorer_routines_are_separate_and_queries_quote_schema():
    import pandas as pd
    class Fake:
        db_type = "sqlserver"
        connection_params = {"database": "db", "schema": "dbo"}
        queries = []
        def execute_query(self, query):
            self.queries.append(query)
            return pd.DataFrame({"name": ["routine"]})
    connector = Fake()
    explorer = ObjectExplorer(connector)
    procedures = explorer.objects("bad'name", "procedure")
    assert procedures[0]["kind"] == "procedure"
    assert "s.name='bad''name'" in connector.queries[-1] and "'P','PC'" in connector.queries[-1]
    functions = explorer.objects("dbo", "function")
    assert functions[0]["kind"] == "function" and "'FN','IF','TF','FS','FT'" in connector.queries[-1]


def test_definitions_preserve_native_sql_and_generate_table_columns_when_unavailable():
    import pandas as pd
    class Fake:
        db_type = "sqlserver"
        connection_params = {"database": "db", "schema": "dbo"}
        queries = []
        def execute_query(self, query):
            self.queries.append(query)
            return pd.DataFrame({"definition": ["CREATE PROCEDURE [dbo].[sample] AS SELECT 37;"]})
    explorer = ObjectExplorer(Fake())
    result = explorer.definition("quoted'name", "d]o", "procedure", {})
    assert not result["definition_is_generated"] and "CREATE PROCEDURE" in result["definition"]
    assert "[d]]o].[quoted''name]" in explorer.connector.queries[0]
    result = explorer.definition("sample", "dbo", "table", {"columns": [
        {"name": "quoted]name", "display_type": "nvarchar(max)", "nullable": False, "default": "N'example'"},
        {"name": "value", "data_type": "numeric", "numeric_precision": 18, "numeric_scale": 3, "nullable": "YES"},
    ], "primary_key": {"constrained_columns": ["quoted]name"]}})
    assert result["definition_is_generated"]
    assert "[quoted]]name] nvarchar(max) NOT NULL" in result["definition"]
    assert "[value] numeric(18,3) NULL" in result["definition"]
    assert "DEFAULT N'example'" in result["definition"] and "PRIMARY KEY ([quoted]]name])" in result["definition"]
    assert explorer.definition("sample", "dbo", "table", {"columns": [{"name": "unknown"}]})["definition"] == ""


def test_editor_sql_aliases_and_ctes_reuse_legacy_parser(connector):
    explorer = ObjectExplorer(connector)
    code = "SELECT t. FROM sample AS t"
    schema = explorer.completion_schema(code)
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})
    assert {"id", "title"} <= {item["label"] for item in result["items"]}
    code = "WITH selected AS (SELECT id, title FROM sample) SELECT s. FROM selected s"
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": code.index("s. FROM") + 3}, {"schema": schema})
    assert {"id", "title"} <= {item["label"] for item in result["items"]}


def test_namespace_snapshots_never_execute_user_properties():
    class Example:
        @property
        def columns(self):
            raise AssertionError("Properties must not run during editor snapshots")
    assert namespace_snapshot({"obj": Example()}) == {"obj": {"type": "Example"}}


def test_idle_connection_reap_preserves_default_config_and_memory_database(tmp_path):
    pool = ConnectorPool(idle_timeout=5)
    first = pool.activate({"config": {"db_type": "sqlite", "database": str(tmp_path / "sample.sqlite")}}, default=True)
    first.execute_query("CREATE TABLE sample(value INTEGER)")
    key = pool.active_key
    pool.last_used[key] -= 10
    assert pool.reap_idle() == ["transient"] and pool.active is None
    assert pool.default_config["database"] == str(tmp_path / "sample.sqlite")
    resumed = pool.activate({})
    assert resumed is not first
    memory = pool.activate({"config": {"db_type": "sqlite"}}, default=True)
    pool.last_used[pool.active_key] -= 10
    assert not pool.reap_idle() and pool.active is memory
    pool.disconnect()


def test_result_view_is_reused_across_pages_and_data_actions_then_invalidated(monkeypatch):
    import pandas as pd
    import polars as pl
    from datapyn_runtime.data_tools import selected_frame
    store = ResultStore(pd, pl)
    frame = pd.DataFrame({"value": [7, 1, 5, 3]})
    identifier = store.register(frame, "df")["result_id"]
    calls = []
    original = pd.DataFrame.sort_values
    def sort(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, "sort_values", sort)
    params = {"result_id": identifier, "sort": {"column": "value", "direction": "asc"}, "filter": {"column": "value", "operator": "gt", "value": 2}}
    assert store.page({**params, "offset": 0, "limit": 2})["rows"] == [[3], [5]]
    assert store.page({**params, "offset": 2, "limit": 2})["rows"] == [[7]]
    assert selected_frame(params, {}, store)["value"].tolist() == [3, 5, 7]
    assert len(calls) == 1 and len(store.views) == 1
    frame.loc[0, "value"] = 9
    store.invalidate_views()
    assert store.page({**params, "offset": 2, "limit": 2})["rows"] == [[9]]
    assert len(calls) == 2


def test_jedi_namespace_diagnostics_format_and_parameter_scan_are_qt_free():
    context = {"variables": {"names": {"type": "list"}, "df": {"type": "DataFrame", "columns": ["id"]}}}
    completions = dispatch("language.complete", {"language": "python", "code": "names.", "line": 1, "column": 7}, context)
    assert "append" in {item["label"] for item in completions["items"]}
    diagnostics = dispatch("language.diagnostics", {"language": "python", "code": "names.append(missing)"}, context)
    assert diagnostics["markers"][0]["message"] == "Undefined name: missing"
    formatted = dispatch("language.format", {"language": "python", "code": "x= [1,2]"})
    assert formatted["error"] is None and "x = [1, 2]" in formatted["code"]
    scan = dispatch("parameters.scan", {"codes": ["SELECT @count, ::today:: -- @ignored", "x=::today::"], "shared_delimiter": "::name::"})
    assert [parameter["name"] for parameter in scan["sql_parameters"]] == ["count"]
    assert [parameter["name"] for parameter in scan["shared_parameters"]] == ["today"]
    # Test runners may import Qt through installed plugins. Check a clean
    # interpreter, exactly as the sidecar starts in production.
    check = subprocess.run([sys.executable, "-c", "import sys; from datapyn_runtime.language import dispatch; from src.services.entity_metadata_service import EntityMetadataService; dispatch('parameters.scan', {'codes':['SELECT @id, {{day}}']}); assert not any(m.startswith('PyQt6') for m in sys.modules)"],
                           env={**os.environ, "PYTHONPATH": str(ROOT / "source")}, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    client = Client()
    yield client
    client.close()


def saved(client, name):
    return client.request("connections.save", {"connection": {"name": name, "config": {"db_type": "sqlite", "database": ":memory:"}}})["id"]


def test_profile_routes_keep_separate_engines_and_namespace(client):
    client.session()
    a, b = saved(client, "a"), saved(client, "b")
    connected = client.request("connection.connect", {"session_id": "a", "connection_id": a})
    assert connected["connection_id"] == a and connected["schema"] == "main" and "password" not in connected["config"]
    for identifier, value in ((a, 7), (b, 13)):
        result = client.execute(f"CREATE TABLE routed(value INTEGER); INSERT INTO routed VALUES ({value}); SELECT * FROM routed;",
                                f"sql-{value}", language="sql", connection_id=identifier)
        assert client.page(result)["rows"] == [[value]]
    result = client.execute("pd.read_sql('SELECT value FROM routed', db_engine)", "python-b", connection_id=b)
    assert client.page(result)["rows"] == [[13]]
    result = client.execute("SELECT value FROM routed", "sql-a", language="sql", connection_id=a)
    assert client.page(result)["rows"] == [[7]]
    assert client.request("connection.disconnect", {"session_id": "a", "connection_id": b})["status"] == "disconnected"


def test_editor_requests_stay_responsive_during_execution(client):
    client.session()
    client.execute("names = []", "initial")
    client.event("language.context_updated", session_id="a")
    # Warm Jedi once, then verify editing is independent from user execution.
    client.request("language.complete", {"session_id": "a", "language": "python", "code": "names.", "line": 1, "column": 7})
    client.request("execution.run", {"session_id": "a", "execution_id": "slow", "language": "python", "code": "import time; time.sleep(3)"})
    client.event("execution.started", "slow")
    start = time.monotonic()
    result = client.request("language.complete", {"session_id": "a", "language": "python", "code": "names.", "line": 1, "column": 7})
    assert "append" in {item["label"] for item in result["items"]}
    assert time.monotonic() - start < 2
    assert client.event("execution.finished", "slow")["status"] == "succeeded"


def test_numpy_scalar_subclasses_are_plain_builtin_wire_values():
    import numpy as np
    import pickle
    for value in (np.float64(6), np.float64("nan"), np.float32(3.5), np.int64(37),
                  np.int64(2**60 + 3), np.bool_(True), np.str_("sample")):
        converted = scalar(value)
        assert type(converted) in {type(None), int, float, bool, str}
        assert b"numpy" not in pickle.dumps(converted)
    assert scalar(np.int64(2**60 + 3)) == str(2**60 + 3)


def test_sql_python_summary_after_language_requests_returns_without_native_broker_import(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    client.execute("SELECT 1 AS id, 'one' AS title UNION ALL SELECT 2, 'two'", "summary-sql", language="sql")
    client.request("language.complete", {"session_id": "a", "language": "python", "code": "df.", "line": 1, "column": 4})
    client.request("language.format", {"language": "python", "code": "x=1\n"})
    client.request("language.diagnostics", {"language": "python", "code": "def broken(:"})
    finished = client.execute("df['value'] = df['id'] * 3\ndf", "summary-python")
    result = client.request("result.summary", {"session_id": "a", "result_id": finished["results"][0]["result_id"],
                                              "scope": {"row_ranges": [[1, 1]], "column_indices": [2]}})
    assert result["columns"][0]["sum"] == 6
    assert result["columns"][0]["mean"] == 6 and result["columns"][0]["std"] is None
    assert client.page(finished)["rows"] == [[1, "one", 3], [2, "two", 6]]


def test_bound_sql_and_python_parameters_support_custom_shared_delimiter(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    definitions = client.request("parameters.scan", {"codes": ["SELECT @value AS value, ::shared:: AS shared"], "shared_delimiter": "::name::"})
    definitions["sql_parameters"][0].update({"value": "quoted' OR 1=1 --", "sql_type": "text", "type_source": "manual"})
    definitions["shared_parameters"][0].update({"value": "42", "sql_type": "integer", "type_source": "manual"})
    result = client.execute("SELECT @value AS value, ::shared:: AS shared", "parameters-sql", language="sql", shared_delimiter="::name::", **definitions)
    assert client.page(result)["rows"] == [["quoted' OR 1=1 --", 42]]
    result = client.execute("pd.DataFrame({'answer':[::shared:: + 1]})", "parameters-python", shared_delimiter="::name::", shared_parameters=definitions["shared_parameters"])
    assert client.page(result)["rows"] == [[43]]


def test_sql_download_streams_multiple_results_without_replacing_dataframe(client, tmp_path):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    client.execute("df = pd.DataFrame({'existing': [7]})", "existing")
    path = tmp_path / "download.csv"
    finished = client.execute(
        "SELECT @value AS sample; SELECT 'second' AS label", "download", language="sql",
        sql_parameters=[{"name": "value", "value": "quoted'", "sql_type": "text", "type_source": "manual"}],
        export={"path": str(path), "format": "csv"},
    )
    assert finished["status"] == "succeeded" and finished["results"] == []
    assert finished["export"]["total_rows"] == 2
    assert len(finished["export"]["files"]) == 2
    assert "quoted'" in path.read_text(encoding="utf-8-sig")
    assert "second" in (tmp_path / "download_2.csv").read_text(encoding="utf-8-sig")
    assert not list(tmp_path.glob(".datapyn-export-*"))
    assert client.page(client.execute("df", "retained"))["rows"] == [[7]]
    progress = client.event("execution.export_progress", "download")
    assert progress["rows"] == 1 and progress["size_bytes"] >= 0


def test_failed_sql_download_preserves_destination_and_removes_stages(client, tmp_path):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    path = tmp_path / "download.csv"
    path.write_text("original", encoding="utf-8")
    finished = client.execute("SELECT 1 AS value; SELECT missing FROM absent", "failed-download", language="sql",
                              export={"path": str(path), "format": "csv"})
    assert finished["status"] == "failed"
    assert path.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".datapyn-export-*"))


def test_idle_connection_closes_engine_then_reconnects_for_next_query(client, tmp_path):
    client.request("connection.idle_timeout", {"seconds": 1})
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(tmp_path / "idle.sqlite")}})
    finished = client.execute("CREATE TABLE sample(value INTEGER); INSERT INTO sample VALUES (7)", "setup-idle", language="sql")
    assert finished["status"] == "succeeded"
    assert client.event("connection.idle_closed", session_id="a")["connection_ids"] == ["transient"]
    assert client.page(client.execute("SELECT value FROM sample", "resumed-idle", language="sql"))["rows"] == [[7]]


def test_session_create_is_idempotent_and_preserves_running_namespace(client):
    client.session()
    client.execute("retained_value = 37", "retained-variable")
    state = client.request("session.create", {"session_id": "a"})
    assert state["status"] == "existing" and state["ready"]
    snapshot = client.event("namespace.changed", session_id="a")
    assert any(variable["name"] == "retained_value" for variable in snapshot["variables"])
    client.request("execution.run", {"session_id": "a", "execution_id": "reconnect-running", "language": "python", "code": "import time; time.sleep(.3); pd.DataFrame({'retained':[retained_value]})"})
    client.event("execution.started", "reconnect-running")
    state = client.request("session.create", {"session_id": "a"})
    assert state["execution_id"] == "reconnect-running"
    assert client.page(client.event("execution.finished", "reconnect-running"))["rows"] == [[37]]


def test_cancelled_sql_download_cleans_stages_after_killing_kernel(client, tmp_path):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    client.execute("import time\nraw = db_engine.raw_connection()\nraw.driver_connection.create_function('slow', 1, lambda value: (time.sleep(.001), value)[1])\nraw.close()", "slow-function")
    destination = tmp_path / "cancelled.csv"
    destination.write_text("original", encoding="utf-8")
    client.request("execution.run", {"session_id": "a", "execution_id": "cancelled-download", "language": "sql",
        "code": "WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20000) SELECT slow(n) AS value FROM numbers",
        "export": {"path": str(destination), "format": "csv"}})
    client.event("execution.started", "cancelled-download")
    deadline = time.monotonic() + 5
    while not list(tmp_path.glob(".datapyn-export-*")) and time.monotonic() < deadline:
        time.sleep(.01)
    assert list(tmp_path.glob(".datapyn-export-*"))
    client.request("execution.cancel", {"session_id": "a", "execution_id": "cancelled-download"})
    assert client.event("execution.finished", "cancelled-download")["status"] == "cancelled"
    assert destination.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".datapyn-export-*"))


def test_async_connection_test_does_not_create_session_or_leak_stdout(client):
    result = client.request("connection.test", {"config": {"db_type": "sqlite"}})
    assert result["success"] and result["db_type"] == "sqlite"
    info = client.request("system.info")
    assert info["capabilities"]["lazy_explorer"]


def test_connection_test_uses_unsaved_changes_and_preserves_keyring_secret(monkeypatch):
    import datapyn_runtime.database as database
    captured = []
    class Connector:
        db_type = "sqlserver"
        def disconnect(self):
            pass
    monkeypatch.setattr(database, "connect", lambda config: (captured.append(config), Connector())[1])
    database.test_connection({"_connection_config": {"db_type": "sqlserver", "host": "old", "password": "stored"},
                              "config": {"db_type": "sqlserver", "host": "edited", "password": ""}})
    assert captured[-1]["host"] == "edited" and captured[-1]["password"] == "stored"
    database.test_connection({"_connection_config": captured[-1], "config": {"password": "replacement"}})
    assert captured[-1]["password"] == "replacement"


def test_explicit_databricks_oauth_overrides_saved_token(monkeypatch):
    import src.database.database_connector as production
    from datapyn_runtime.database import connect
    captured = []
    class Connector:
        SUPPORTED_DATABASES = {"databricks"}
        def connect(self, **kwargs):
            captured.append(kwargs)
            return True
        def is_connected(self):
            return True
    monkeypatch.setattr(production, "DatabaseConnector", Connector)
    connect({"db_type": "databricks", "password": "stored-token", "databricks_auth_mode": "oauth"})
    assert captured[-1]["password"] == "" and "databricks_auth_mode" not in captured[-1]
    connect({"db_type": "databricks", "password": "stored-token"})
    assert captured[-1]["password"] == "stored-token"


def test_releasing_result_preserves_namespace_and_clears_cached_view(client):
    client.session()
    finished = client.execute("df = pd.DataFrame({'value':[37,42]})", "release-table")
    identifier = finished["results"][0]["result_id"]
    assert client.page(finished, filter={"column": "value", "operator": "gt", "value": "38"})["rows"] == [[42]]
    assert client.request("result.release", {"session_id": "a", "result_id": identifier})["released"]
    assert "error" in client.response("result.page", {"session_id": "a", "result_id": identifier})
    assert client.page(client.execute("df", "after-release"))["rows"] == [[37], [42]]


def test_activity_and_empty_workspace_flush_do_not_create_session(client):
    assert not client.request("system.activity")["busy"]
    assert client.request("system.flush_workspace") == {"sessions": [], "flushed": 0}
    client.session()
    client.request("execution.run", {"session_id": "a", "execution_id": "activity", "language": "python", "code": "import time; time.sleep(.2)"})
    client.event("execution.started", "activity")
    activity = client.request("system.activity")
    assert activity["busy"] and activity["executions"] == 1 and not activity["packages"]
    client.event("execution.finished", "activity")


def test_connection_test_can_be_cancelled_without_session_reset(client):
    client.session()
    client.execute("retained = 37", "before-test-cancel")
    client.sequence += 1
    request_id = client.sequence
    client.process.stdin.write(json.dumps({"id": request_id, "method": "connection.test", "params": {
        "test_id": "cancelled-test", "config": {"db_type": "sqlite"}}}) + "\n")
    client.process.stdin.flush()
    assert client.request("connection.test_cancel", {"test_id": "cancelled-test"})["status"] == "cancelling"
    response = client.wait(lambda message: message.get("id") == request_id)
    assert response["error"]["code"] == "cancelled"
    assert client.page(client.execute("pd.DataFrame({'retained':[retained]})", "after-test-cancel"))["rows"] == [[37]]


def test_broker_workspace_switch_isolates_catalog_and_closes_session(client):
    client.session()
    original = saved(client, "first-profile")
    profile = client.request("workspace.profiles.create", {"name": "Second"})
    selected = client.request("workspace.profiles.select", {"profile_id": profile["id"]})
    assert selected["active_id"] == profile["id"]
    assert not client.request("connections.list")["connections"]
    assert "error" in client.response("execution.run", {"session_id": "a", "execution_id": "old", "language": "python", "code": "1"})
    client.request("workspace.profiles.select", {"profile_id": "default"})
    assert client.request("connections.list")["connections"][0]["id"] == original


def test_broker_refuses_workspace_switch_during_execution(client):
    client.session()
    profile = client.request("workspace.profiles.create", {"name": "Second"})
    client.request("execution.run", {"session_id": "a", "execution_id": "long", "language": "python", "code": "import time; time.sleep(10)"})
    client.event("execution.started", "long")
    response = client.response("workspace.profiles.select", {"profile_id": profile["id"]})
    assert response["error"]["code"] == "workspace_busy"
    assert client.request("workspace.profiles.list")["active_id"] == "default"
    client.request("execution.cancel", {"session_id": "a", "execution_id": "long"})
    assert client.event("execution.finished", "long")["status"] == "cancelled"
