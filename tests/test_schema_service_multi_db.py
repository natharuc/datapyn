import pandas as pd

from src.services.schema_service import SchemaService


class FakeMultiDbConnector:
    def __init__(self, db_type: str, responses=None):
        self.db_type = db_type
        self.responses = responses or {}
        self.queries = []

    def execute_query(self, query: str):
        compact_query = " ".join(query.split())
        self.queries.append(compact_query)
        for token, response in self.responses.items():
            if token in compact_query:
                return response
        return pd.DataFrame()


def run_schema_service_sync(service: SchemaService):
    service._run_in_thread_with_signal = lambda func, callback: callback(func())


def test_mysql_lazy_tables_use_requested_database(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeMultiDbConnector(
        "mysql",
        responses={
            "WHERE TABLE_SCHEMA = 'analytics'": pd.DataFrame([
                {"TABLE_NAME": "orders", "TABLE_TYPE": "BASE TABLE"},
                {"TABLE_NAME": "daily_metrics", "TABLE_TYPE": "VIEW"},
            ])
        },
    )
    captured = []
    service.tables_loaded.connect(lambda database, schema, tables: captured.append((database, schema, tables)))

    service.load_tables_for_schema(connector, "Conn", "analytics", "")

    assert any("WHERE TABLE_SCHEMA = 'analytics'" in query for query in connector.queries)
    assert captured[0][0:2] == ("analytics", "")
    assert [table["name"] for table in captured[0][2]] == ["orders", "daily_metrics"]
    assert captured[0][2][0]["schema"] == "analytics"
    assert captured[0][2][0]["database"] == "analytics"


def test_mysql_lazy_columns_use_requested_database(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeMultiDbConnector(
        "mysql",
        responses={
            "WHERE TABLE_SCHEMA = 'analytics' AND TABLE_NAME = 'orders'": pd.DataFrame([
                {"COLUMN_NAME": "id", "DATA_TYPE": "bigint", "IS_NULLABLE": "NO"},
                {"COLUMN_NAME": "total", "DATA_TYPE": "decimal", "IS_NULLABLE": "YES"},
            ])
        },
    )
    captured = []
    service.columns_loaded.connect(
        lambda database, schema, table, columns: captured.append((database, schema, table, columns))
    )

    service.load_columns_for_table(connector, "Conn", "analytics", "analytics", "orders")

    assert any(
        "WHERE TABLE_SCHEMA = 'analytics' AND TABLE_NAME = 'orders'" in query
        for query in connector.queries
    )
    assert captured[0][0:3] == ("analytics", "analytics", "orders")
    assert [column["name"] for column in captured[0][3]] == ["id", "total"]


def test_sqlserver_lazy_tables_use_requested_database(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeMultiDbConnector(
        "sqlserver",
        responses={
            "FROM [warehouse].INFORMATION_SCHEMA.TABLES": pd.DataFrame([
                {"TABLE_SCHEMA": "dbo", "TABLE_NAME": "users", "TABLE_TYPE": "BASE TABLE"},
                {"TABLE_SCHEMA": "reporting", "TABLE_NAME": "totals", "TABLE_TYPE": "VIEW"},
            ])
        },
    )
    captured = []
    service.tables_loaded.connect(lambda database, schema, tables: captured.append((database, schema, tables)))

    service.load_tables_for_schema(connector, "Conn", "warehouse", "")

    assert any("FROM [warehouse].INFORMATION_SCHEMA.TABLES" in query for query in connector.queries)
    assert captured[0][0:2] == ("warehouse", "")
    assert captured[0][2][0]["database"] == "warehouse"
    assert captured[0][2][0]["schema"] == "dbo"


def test_sqlserver_lazy_columns_use_requested_database(qapp):
    service = SchemaService()
    run_schema_service_sync(service)
    connector = FakeMultiDbConnector(
        "sqlserver",
        responses={
            "FROM [warehouse].INFORMATION_SCHEMA.COLUMNS": pd.DataFrame([
                {"COLUMN_NAME": "id", "DATA_TYPE": "int", "IS_NULLABLE": "NO"},
                {"COLUMN_NAME": "name", "DATA_TYPE": "nvarchar", "IS_NULLABLE": "YES"},
            ])
        },
    )
    captured = []
    service.columns_loaded.connect(
        lambda database, schema, table, columns: captured.append((database, schema, table, columns))
    )

    service.load_columns_for_table(connector, "Conn", "warehouse", "dbo", "users")

    assert any("FROM [warehouse].INFORMATION_SCHEMA.COLUMNS" in query for query in connector.queries)
    assert any("TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'users'" in query for query in connector.queries)
    assert captured[0][0:3] == ("warehouse", "dbo", "users")
    assert [column["name"] for column in captured[0][3]] == ["id", "name"]