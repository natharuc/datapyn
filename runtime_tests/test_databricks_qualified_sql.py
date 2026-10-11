"""Databricks names keep their namespace without rewriting SQL or live access."""

from types import SimpleNamespace

import pandas as pd
import pytest

from datapyn_runtime.explorer import ObjectExplorer
from datapyn_runtime.language import dispatch
from datapyn_runtime.sql_completion import RuntimeSqlAutoCompleteService
from src.database.database_connector import DatabaseConnector
from test_sql_execution_context import PhysicalConnection, make_connector, run_kernel_jobs


def complete(code, snapshot):
    position = code.index("s.") + 3
    return dispatch("language.complete", {"language": "sql", "code": code, "line": 1,
                                         "column": position}, {"schema": snapshot})["items"]


def namespace_snapshot():
    relations = [("current", "focused", "sales", "focused_value"),
                 ("current", "reporting", "sales", "reporting_value"),
                 ("other", "focused", "sales", "foreign_value"),
                 ("other", "reporting", "sales", "foreign_reporting_value")]
    return {"db_type": "databricks", "database": "current", "current_schema": "focused",
            "schemas": ["focused", "reporting"], "metadata_loaded": True,
            "tables": [{"catalog": catalog, "schema": schema, "name": name,
                        "key": f"{catalog}.{schema}.{name}"} for catalog, schema, name, _ in relations],
            "columns": {f"{catalog}.{schema}.{name}": [{"name": column, "type": "BIGINT"}]
                        for catalog, schema, name, column in relations}}


@pytest.mark.parametrize(("relation", "field"), [
    ("sales", "focused_value"),
    ("focused.sales", "focused_value"),
    ("reporting.sales", "reporting_value"),
    ("current.focused.sales", "focused_value"),
    ("other.focused.sales", "foreign_value"),
    ("`other`.`reporting`.`sales`", "foreign_reporting_value"),
    ("OTHER.REPORTING.SALES", "foreign_reporting_value"),
])
def test_completion_uses_exact_databricks_name_resolution(relation, field):
    assert {item["label"] for item in complete(f"SELECT s. FROM {relation} s", namespace_snapshot())} == {field}


@pytest.mark.parametrize("relation", ["missing.focused.sales", "missing.sales", "current.missing.sales"])
def test_missing_qualified_relation_never_borrows_focused_fields(relation):
    assert complete(f"SELECT s. FROM {relation} s", namespace_snapshot()) == []


def test_relative_relation_never_uses_a_foreign_catalog_or_different_schema():
    snapshot = namespace_snapshot()
    snapshot["tables"] = [table for table in snapshot["tables"] if table["catalog"] != "current"]
    for relation in ("sales", "focused.sales", "reporting.sales"):
        assert complete(f"SELECT s. FROM {relation} s", snapshot) == []
    snapshot = namespace_snapshot()
    snapshot["tables"] = [table for table in snapshot["tables"] if table["schema"] != "focused"]
    assert complete("SELECT s. FROM sales s", snapshot) == []


def test_unqualified_temporary_relation_wins_without_shadowing_qualified_table():
    snapshot = namespace_snapshot()
    snapshot["tables"].append({"name": "sales", "schema": "", "catalog": "", "key": "sales", "temporary": True})
    snapshot["columns"]["sales"] = [{"name": "temporary_value", "type": "BIGINT"}]
    assert {item["label"] for item in complete("SELECT s. FROM sales s", snapshot)} == {"temporary_value"}
    assert {item["label"] for item in complete("SELECT s. FROM current.focused.sales s", snapshot)} == {"focused_value"}


def test_missing_foreign_table_does_not_report_valid_field_as_unknown():
    code = "SELECT s.valid_remote_value FROM other.focused.sales s"
    snapshot = namespace_snapshot()
    snapshot["tables"] = [table for table in snapshot["tables"] if table["catalog"] == "current"]
    result = dispatch("language.diagnostics", {"language": "sql", "code": code, "db_type": "databricks"}, {"schema": snapshot, "schema_complete": True})
    assert result["markers"] == []


def test_known_foreign_table_reports_real_column_errors_in_its_own_namespace():
    code = "SELECT s.foreign_value, s.focused_value FROM other.focused.sales s"
    result = dispatch("language.diagnostics", {"language": "sql", "code": code, "db_type": "databricks"}, {"schema": namespace_snapshot(), "schema_complete": True})
    assert [marker["message"] for marker in result["markers"]] == ["Unknown column 's.focused_value'"]


class MetadataConnector:
    db_type = "databricks"
    connection_params = {"database": "current", "schema": "focused"}

    def __init__(self, *, discover=True, schemas=True, table="sales"):
        self.queries = []
        self.discover = discover
        self.schemas = schemas
        self.table = table

    def execute_query(self, query):
        self.queries.append(query)
        if query == "SHOW CATALOGS":
            if not self.discover:
                raise PermissionError("Catalog listing is not available")
            return pd.DataFrame({"name": ["current", "other"]})
        if query.startswith("SHOW SCHEMAS IN"):
            if not self.schemas:
                raise PermissionError("Schema listing is not available")
            return pd.DataFrame({"name": ["focused", "reporting"]})
        if query.startswith("SHOW TABLES IN"):
            return pd.DataFrame({"tableName": [self.table]})
        if query.startswith("SHOW COLUMNS IN"):
            return pd.DataFrame({"col_name": ["foreign_value"]})
        raise AssertionError(query)


@pytest.mark.parametrize("discover", [True, False])
@pytest.mark.parametrize("schemas", [True, False])
def test_full_qualification_loads_remote_metadata_without_catalog_discovery(monkeypatch, discover, schemas):
    connector = MetadataConnector(discover=discover, schemas=schemas)
    explorer = ObjectExplorer(connector)
    monkeypatch.setattr(explorer, "schemas", lambda catalog: ["focused", "reporting"])
    monkeypatch.setattr(explorer, "objects", lambda schema, category: [explorer._node("sales", "table", schema=schema)] if category == "table" else [])
    monkeypatch.setattr(explorer, "columns", lambda *args: pytest.fail("A foreign relation must not probe focused columns"))
    code = "SELECT s. FROM other.reporting.sales s"
    snapshot = explorer.completion_schema(code)
    assert {item["label"] for item in complete(code, snapshot)} == {"foreign_value"}
    assert snapshot["columns"]["other.reporting.sales"] == [{"name": "foreign_value", "type": ""}]
    assert snapshot["catalog_schemas"]["other"] == ["reporting"]
    assert not any(query.startswith("USE ") or query.startswith("SHOW SCHEMAS") for query in connector.queries)
    queries = list(connector.queries)
    explorer.completion_schema(code)
    # Failed global discovery is not cached, but successful direct metadata is.
    assert [query for query in connector.queries[len(queries):] if query != "SHOW CATALOGS"] == []
    assert explorer.context()["database"] == "current" and explorer.context()["schema"] == "focused"


def test_quoted_foreign_paths_escape_parts_and_keep_literal_dots(monkeypatch):
    connector = MetadataConnector(discover=False, schemas=False, table="sales.items")
    explorer = ObjectExplorer(connector)
    monkeypatch.setattr(explorer, "schemas", lambda catalog: ["focused"])
    monkeypatch.setattr(explorer, "objects", lambda *args: [])
    code = "SELECT s. FROM `other``catalog`.`report.ing`.`sales.items` s"
    snapshot = explorer.completion_schema(code)
    assert "SHOW TABLES IN `other``catalog`.`report.ing`" in connector.queries
    assert "SHOW COLUMNS IN `other``catalog`.`report.ing`.`sales.items`" in connector.queries
    assert {item["label"] for item in complete(code, snapshot)} == {"foreign_value"}


@pytest.mark.parametrize(("relation", "expected"), [
    ("sales", [("focused", "sales")]),
    ("reporting.sales", [("reporting", "sales")]),
    ("current.reporting.sales", [("reporting", "sales")]),
    ("other.reporting.sales", []),
])
def test_only_matching_focused_relations_load_columns(monkeypatch, relation, expected):
    connector = MetadataConnector()
    explorer = ObjectExplorer(connector)
    monkeypatch.setattr(explorer, "schemas", lambda catalog: ["focused", "reporting"])
    monkeypatch.setattr(explorer, "objects", lambda schema, category: [explorer._node("sales", "table", schema=schema)] if category == "table" else [])
    requested = []
    monkeypatch.setattr(explorer, "columns", lambda name, schema: requested.append((schema, name)))
    explorer.completion_schema(f"SELECT * FROM {relation}")
    assert requested == expected


@pytest.mark.parametrize("relation", ["sales", "focused.sales", "current.focused.sales", "other.reporting.sales", "`cat-a`.`schema-a`.`table-a`", "`cat``a`.`schema.a`.`table.a`"])
@pytest.mark.parametrize("mode", ["frame", "stream"])
def test_driver_keeps_qualified_sql_and_selected_context(relation, mode, monkeypatch, tmp_path):
    connector, physical = make_connector("databricks")
    physical.schema = connector.connection_params["databricks_schema"] = "focused"
    code = f"SELECT * FROM {relation} WHERE id = :id"
    if mode == "stream":
        monkeypatch.setattr(connector, "_stream_write_result_set", lambda *args, **kwargs: True)
        connector.stream_query_to_files(code, parameters=[{"name": "id", "value": 7, "sql_type": "integer"}],
                                        base_path=tmp_path / "rows.csv", export_format="csv")
    else:
        connector.execute_query(code, parameters=[{"name": "id", "value": 7, "sql_type": "integer"}])
    assert len(physical.commands) == 1
    assert f"FROM {relation}" in physical.commands[0]
    assert connector.get_current_database() == "before" and connector.get_current_schema() == "focused"
    assert physical.database == "before" and physical.schema == "focused"


def test_kernel_preserves_mixed_qualified_queries_and_publishes_frames_without_scope_changes(monkeypatch, tmp_path):
    connector, physical = make_connector("databricks")
    physical.schema = connector.connection_params["databricks_schema"] = "focused"
    messages = run_kernel_jobs(monkeypatch, tmp_path, connector, [{
        "code": "SELECT * FROM sales; SELECT * FROM reporting.sales; SELECT * FROM other.reporting.sales",
        "schema": "focused",
    }, {"language": "python", "schema": "focused", "code": "assert len(df) == len(df1) == len(df2) == 1; assert db_database == 'before'; assert db_schema == 'focused'"}])
    finished = [item["payload"] for item in messages if item.get("event") == "execution.finished"]
    assert all(item["status"] == "succeeded" for item in finished), finished
    assert len(finished[0]["results"]) == 3
    assert all("context_change" not in item for item in finished)
    assert physical.commands == ["SELECT * FROM sales", "SELECT * FROM reporting.sales", "SELECT * FROM other.reporting.sales"]


def test_databricks_resolver_accepts_no_context_legacy_snapshots():
    service = RuntimeSqlAutoCompleteService()
    service.set_schema({"db_type": "databricks", "tables": [{"name": "sample"}], "columns": {"sample": [{"name": "id"}]}})
    assert service._find_schema_entry("sample")["columns"][0]["name"] == "id"


@pytest.mark.parametrize("token", ["offline-token", ""])
def test_real_databricks_dialect_passes_catalog_and_schema_as_separate_sdk_arguments(monkeypatch, token):
    from databricks.sqlalchemy import DatabricksDialect
    from sqlalchemy.engine import make_url

    monkeypatch.setattr("src.database.database_connector._get_oauth_token_cache_path", lambda host: "offline-cache")
    url, options = DatabaseConnector()._build_connection_string(
        "databricks", "offline.invalid", 443, "mag_bronze", "", token,
        schema="gecon", http_path="/sql/1.0/warehouses/offline")
    positional, sdk = DatabricksDialect().create_connect_args(make_url(url))
    assert positional == []
    assert sdk["catalog"] == "mag_bronze" and sdk["schema"] == "gecon"
    assert sdk["http_path"] == "/sql/1.0/warehouses/offline"
    assert options["enable_telemetry"] is False
    assert sdk["access_token"] == (token or None)


def test_actual_sdk_cursor_keeps_users_cross_catalog_query_unchanged():
    from databricks.sql.client import Cursor

    requests = []
    connection = SimpleNamespace(session=SimpleNamespace(session_id="offline"),
                                 lz4_compression=True, use_cloud_fetch=True, use_inline_params=False)
    backend = SimpleNamespace(execute_command=lambda **params: requests.append(params))
    cursor = Cursor(connection, backend)
    code = "select * from mag_prata_seguradora.financeiro.premio limit 10"
    cursor.execute(code)
    assert len(requests) == 1 and requests[0]["operation"] == code
    assert requests[0]["parameters"] == []
    assert "mag_bronze" not in requests[0]["operation"]


def physical_databricks(database="spark_catalog", schema="mag_bronze", *, reject_catalog=False, ignore_catalog=False):
    physical = PhysicalConnection("databricks")
    physical.database, physical.schema = database, schema
    cursor_factory = physical.cursor

    def cursor():
        value = cursor_factory()
        execute = value.execute

        def execute_statement(code, parameters=None):
            if code.startswith("USE CATALOG") and reject_catalog:
                physical.commands.append(code)
                raise ConnectionError("This compute does not support USE CATALOG")
            if code.startswith("USE CATALOG") and ignore_catalog:
                physical.commands.append(code)
                value.description, value.rows = None, []
                return
            execute(code)
            if value.description:
                value.description = [(column[0], "bigint", None, None, None, None, True) for column in value.description]
        value.execute = execute_statement
        return value
    physical.cursor = cursor
    return physical


def connect_with_real_dialect(monkeypatch, physical):
    from sqlalchemy import create_engine

    monkeypatch.setattr("src.database.database_connector.create_engine",
                        lambda url, **options: create_engine(url, creator=lambda: physical, **options))
    connector = DatabaseConnector()
    connector.connect("databricks", "offline.invalid", 443, "mag_bronze", password="offline-token",
                      schema="gecon", http_path="/sql/1.0/warehouses/offline")
    return connector


def test_ignored_open_session_namespace_is_verified_and_applied_before_cross_catalog_query(monkeypatch):
    physical = physical_databricks()
    connector = connect_with_real_dialect(monkeypatch, physical)
    try:
        assert physical.commands[:4] == ["SELECT current_catalog(), current_schema()",
                                        "USE CATALOG `mag_bronze`", "USE SCHEMA `gecon`",
                                        "SELECT current_catalog(), current_schema()"]
        assert physical.database == "mag_bronze" and physical.schema == "gecon"
        assert ObjectExplorer(connector).context() == {"db_type": "databricks", "database": "mag_bronze", "schema": "gecon"}
        before = len(physical.commands)
        code = "select * from mag_prata_seguradora.financeiro.premio limit 10"
        connector.execute_query(code)
        connector.execute_query(code)
        assert physical.commands[before:] == [code, code], "Verified pooled sessions need no repeated USE or context probes"
        assert physical.database == "mag_bronze" and physical.schema == "gecon"
    finally:
        connector.disconnect()


def test_matching_initial_namespace_needs_one_probe_without_redundant_use(monkeypatch):
    physical = physical_databricks("mag_bronze", "gecon")
    connector = connect_with_real_dialect(monkeypatch, physical)
    try:
        assert physical.commands == ["SELECT current_catalog(), current_schema()", "SELECT 1"]
        connector.execute_query("SELECT * FROM financeiro.premio")
        assert physical.commands[-1] == "SELECT * FROM financeiro.premio"
        assert physical.commands.count("SELECT current_catalog(), current_schema()") == 1
    finally:
        connector.disconnect()


@pytest.mark.parametrize("options", [{"reject_catalog": True}, {"ignore_catalog": True}])
def test_backend_that_cannot_apply_catalog_fails_connection_before_any_user_query(monkeypatch, options):
    physical = physical_databricks(**options)
    with pytest.raises(ConnectionError, match="support USE CATALOG|could not apply the selected catalog"):
        connect_with_real_dialect(monkeypatch, physical)
    assert not any("premio" in query or query == "SELECT 1" for query in physical.commands)


def test_each_new_physical_checkout_verifies_namespace_once(monkeypatch):
    connector, _physical = make_connector("databricks")
    connector.connection_params.update(database="mag_bronze", databricks_catalog="mag_bronze", databricks_schema="gecon")
    connector._connection_config = {"database": "mag_bronze", "schema": "gecon"}
    handlers = []
    monkeypatch.setattr("src.database.database_connector.event.listens_for", lambda *args: lambda handler: handlers.append(handler))
    connector._register_engine_checkout_hooks("databricks")
    for physical in (physical_databricks(), physical_databricks("hive_metastore", "default")):
        record = SimpleNamespace(info={})
        handlers[0](physical, record, None)
        assert (physical.database, physical.schema) == ("mag_bronze", "gecon")
        commands = list(physical.commands)
        handlers[0](physical, record, None)
        assert physical.commands == commands


def test_view_dependency_error_is_not_rewritten_retried_or_misattributed(monkeypatch):
    physical = physical_databricks("mag_bronze", "gecon")
    connector = connect_with_real_dialect(monkeypatch, physical)
    try:
        code = "select * from mag_prata_seguradora.financeiro.premio limit 10"
        error = RuntimeError("[SCHEMA_NOT_FOUND] The schema `spark_catalog`.`mag_bronze` cannot be found. SQLSTATE: 42704")
        factory = physical.cursor
        def cursor():
            value = factory()
            execute = value.execute
            def run(query, parameters=None):
                if query == code:
                    physical.commands.append(query)
                    raise error
                return execute(query, parameters)
            value.execute = run
            return value
        physical.cursor = cursor
        with pytest.raises(RuntimeError) as caught:
            connector.execute_query(code)
        assert caught.value is error
        assert physical.commands.count(code) == 1
        assert ObjectExplorer(connector).context() == {"db_type": "databricks", "database": "mag_bronze", "schema": "gecon"}
    finally:
        connector.disconnect()


def test_use_catalog_updates_databricks_reflection_namespace(monkeypatch):
    physical = physical_databricks("mag_bronze", "gecon")
    connector = connect_with_real_dialect(monkeypatch, physical)
    try:
        connector.execute_query("USE CATALOG mag_prata_seguradora; USE SCHEMA financeiro")
        assert connector.engine.dialect.catalog == "mag_prata_seguradora"
        assert connector.engine.dialect.schema == "financeiro"
        assert connector.get_current_catalog() == physical.database == "mag_prata_seguradora"
        assert connector.get_current_schema() == physical.schema == "financeiro"
    finally:
        connector.disconnect()
