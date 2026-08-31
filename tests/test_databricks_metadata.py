from unittest.mock import MagicMock, patch

import pandas as pd

from src.services.schema_service import SCHEMA_LAZY_MINIMAL, SchemaService, SchemaWorker
from src.ui.components.object_explorer_panel import ObjectExplorerPanel
from src.workers import BlockConnectionWorker


class FakeDatabricksConnector:
    def __init__(self, responses=None, failures=None, current_catalog="main", current_schema="default"):
        self.db_type = "databricks"
        self.queries = []
        self.responses = responses or {}
        self.failures = failures or set()
        self.current_catalog = current_catalog
        self.current_schema = current_schema

    def execute_query(self, query: str):
        compact_query = " ".join(query.split())
        self.queries.append(compact_query)
        for token in self.failures:
            if token in compact_query:
                raise RuntimeError(f"forced failure for {token}")
        for token, response in self.responses.items():
            if token in compact_query:
                return response
        return pd.DataFrame()

    def get_current_catalog(self):
        return self.current_catalog

    def get_current_schema(self):
        return self.current_schema

    def get_current_database_context(self):
        if self.current_catalog and self.current_schema:
            return f"{self.current_catalog}.{self.current_schema}"
        return self.current_catalog or self.current_schema


def run_schema_service_sync(service: SchemaService):
    service._run_in_thread_with_signal = lambda func, callback: callback(func())


def test_databricks_lazy_tables_use_catalog_qualified_information_schema(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeDatabricksConnector({
        "information_schema.tables": pd.DataFrame([
            {"table_name": "customers", "table_type": "BASE TABLE"},
            {"table_name": "orders", "table_type": "VIEW"},
        ])
    })
    captured = []
    service.tables_loaded.connect(lambda catalog, schema, tables: captured.append((catalog, schema, tables)))

    service.load_tables_for_schema(connector, "Dbx", "main", "default")

    assert "USE CATALOG" not in "\n".join(connector.queries)
    assert any("FROM `main`.information_schema.tables" in query for query in connector.queries)
    assert captured[0][0:2] == ("main", "default")
    assert captured[0][2][0]["key"] == "main.default.customers"
    assert captured[0][2][1]["type"] == "VIEW"


def test_databricks_lazy_columns_fallback_uses_fully_qualified_describe(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeDatabricksConnector(
        responses={
            "DESCRIBE TABLE": pd.DataFrame([
                {"col_name": "id", "data_type": "BIGINT"},
                {"col_name": "payload", "data_type": "STRUCT<name:STRING>"},
                {"col_name": "# Partition Information", "data_type": ""},
            ])
        },
        failures={"information_schema.columns"},
    )
    captured = []
    service.columns_loaded.connect(
        lambda catalog, schema, table, columns: captured.append((catalog, schema, table, columns))
    )

    service.load_columns_for_table(connector, "Dbx", "main", "default", "customers")

    assert "USE CATALOG" not in "\n".join(connector.queries)
    assert any("DESCRIBE TABLE `main`.`default`.`customers`" in query for query in connector.queries)
    assert captured[0][0:3] == ("main", "default", "customers")
    assert [column["name"] for column in captured[0][3]] == ["id", "payload"]


def test_object_explorer_merges_lazy_databricks_metadata_into_schema(qapp):
    panel = ObjectExplorerPanel()
    schema = {
        "database": "main",
        "databases": ["main", "hive_metastore"],
        "tables": [],
        "columns": {},
        "db_type": "databricks",
    }
    panel.set_schema(schema, "Dbx", db_type="databricks")

    panel.add_schemas_to_catalog("hive_metastore", ["legacy"])
    panel.add_tables_to_schema("hive_metastore", "legacy", [{"name": "events", "type": "BASE TABLE"}])
    panel.add_columns_to_table(
        "hive_metastore",
        "legacy",
        "events",
        [{"name": "event_id", "type": "BIGINT"}],
    )

    current_schema = panel._current_schema
    assert current_schema["catalog_schemas"]["hive_metastore"] == ["legacy"]
    assert any(table["key"] == "hive_metastore.legacy.events" for table in current_schema["tables"])
    assert current_schema["columns"]["hive_metastore.legacy.events"][0]["name"] == "event_id"


def test_schema_service_tracks_current_databricks_context(qapp):
    connector = FakeDatabricksConnector(current_catalog="mag_bronze", current_schema="esim")
    captured = []
    worker = SchemaWorker(connector)
    worker.finished.connect(lambda schema: captured.append(schema))

    worker.run()

    assert captured
    assert captured[0]["database"] == "mag_bronze"
    assert captured[0]["current_schema"] == "esim"
    assert captured[0]["current_context"] == "mag_bronze.esim"


def test_schema_service_tracks_current_databricks_context(qapp):
    connector = FakeDatabricksConnector(current_catalog="mag_bronze", current_schema="esim")
    captured = []
    worker = SchemaWorker(connector)
    worker.finished.connect(lambda schema: captured.append(schema))

    worker.run()

    assert captured
    assert captured[0]["database"] == "mag_bronze"
    assert captured[0]["current_schema"] == "esim"
    assert captured[0]["current_context"] == "mag_bronze.esim"


def test_schema_worker_minimal_loads_current_catalog_schemas(qapp):
    connector = FakeDatabricksConnector(
        current_catalog="main",
        current_schema="default",
        responses={
            "SHOW CATALOGS": __import__("pandas").DataFrame({"catalog": ["main"]}),
            "SHOW SCHEMAS IN": __import__("pandas").DataFrame({"schema": ["default", "audit"]}),
        },
    )
    captured = []
    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_MINIMAL)
    worker.finished.connect(lambda schema: captured.append(schema))
    worker.run()

    assert any("SHOW SCHEMAS IN `main`" in query for query in connector.queries)
    assert captured[0]["catalog_schemas"]["main"] == ["audit", "default"]


def test_warm_catalog_schemas_skips_current_and_merges_others(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeDatabricksConnector({
        "SHOW SCHEMAS IN `mag_bronze`": pd.DataFrame([{"databaseName": "esim"}, {"databaseName": "default"}]),
        "SHOW SCHEMAS IN `hive_metastore`": pd.DataFrame([{"databaseName": "legacy"}]),
    })
    captured = []
    service.catalog_schemas_warmed.connect(lambda payload: captured.append(payload))

    service.warm_catalog_schemas(
        connector,
        "Dbx",
        ["main", "mag_bronze", "hive_metastore"],
        skip_catalog="main",
        session_id="sid-1",
    )

    assert captured
    loaded = captured[0]["loaded"]
    assert "main" not in loaded
    assert loaded["mag_bronze"] == ["esim", "default"]
    assert loaded["hive_metastore"] == ["legacy"]
    assert captured[0]["remaining"] == []


def test_block_connection_worker_passes_databricks_http_path(qapp):
    with patch("src.database.database_connector.DatabaseConnector") as connector_cls:
        connector = MagicMock()
        connector.is_connected.return_value = True
        connector_cls.return_value = connector

        worker = BlockConnectionWorker(
            db_type="databricks",
            host="workspace.cloud.databricks.com",
            port=443,
            database="main",
            username="",
            password="token",
            http_path="/sql/1.0/warehouses/abc",
        )
        worker.run()

    connector.connect.assert_called_once_with(
        db_type="databricks",
        host="workspace.cloud.databricks.com",
        port=443,
        database="main",
        username="",
        password="token",
        use_windows_auth=False,
        trust_server_certificate=False,
        http_path="/sql/1.0/warehouses/abc",
    )
