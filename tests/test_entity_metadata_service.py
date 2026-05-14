"""
Tests for entity metadata introspection helpers.
"""

import pandas as pd

from src.services.entity_metadata_service import (
    EntityMetadataService,
    build_display_data_type,
    split_qualified_name,
)


class FakeConnector:
    def __init__(self):
        self.db_type = "mysql"
        self.queries = []

    def get_current_database(self):
        return "analytics"

    def execute_query(self, query: str):
        self.queries.append(query)
        compact_query = " ".join(query.split())

        if "FROM INFORMATION_SCHEMA.TABLES" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "schema_name": "analytics",
                        "entity_name": "orders",
                        "entity_type": "BASE TABLE",
                        "table_rows": 9876543210,
                        "size_bytes": 8192,
                    }
                ]
            )
        if "FROM INFORMATION_SCHEMA.COLUMNS" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "column_name": "id",
                        "data_type": "decimal",
                        "numeric_precision": 20,
                        "numeric_scale": 12,
                        "is_nullable": "NO",
                        "column_default": "",
                        "ordinal_position": 1,
                    },
                    {
                        "column_name": "customer_name",
                        "data_type": "varchar",
                        "character_maximum_length": 50,
                        "is_nullable": "YES",
                        "column_default": None,
                        "ordinal_position": 2,
                    },
                ]
            )
        if "FROM INFORMATION_SCHEMA.STATISTICS" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "index_name": "PRIMARY",
                        "non_unique": 0,
                        "column_name": "id",
                        "seq_in_index": 1,
                    },
                    {
                        "index_name": "idx_customer_name",
                        "non_unique": 1,
                        "column_name": "customer_name",
                        "seq_in_index": 1,
                    },
                ]
            )
        raise AssertionError(f"Unexpected query: {query}")


class FakeSqlServerConnector:
    def __init__(
        self,
        *,
        entity_type: str = "TABLE",
        deny_row_count: bool = False,
        deny_size: bool = False,
        deny_indexes: bool = False,
    ):
        self.db_type = "sqlserver"
        self.queries = []
        self.entity_type = entity_type
        self.deny_row_count = deny_row_count
        self.deny_size = deny_size
        self.deny_indexes = deny_indexes

    def get_current_database(self):
        return "Gecon"

    def execute_query(self, query: str):
        self.queries.append(query)
        compact_query = " ".join(query.split())

        if "FROM sys.objects o" in compact_query and "WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR')" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "schema_name": "dbo",
                        "entity_name": "orders",
                        "entity_type": self.entity_type,
                        "object_type_code": "U" if self.entity_type == "TABLE" else "V",
                    }
                ]
            )
        if "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id JOIN sys.partitions p" in compact_query:
            if self.deny_row_count:
                raise Exception("VIEW DATABASE PERFORMANCE STATE permission denied")
            return pd.DataFrame([[9876543210123]])
        if "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id JOIN sys.indexes i ON i.object_id = t.object_id" in compact_query:
            if self.deny_size:
                raise Exception("The SELECT permission was denied on the object")
            return pd.DataFrame([[16384]])
        if "FROM INFORMATION_SCHEMA.COLUMNS" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "column_name": "id",
                        "data_type": "bigint",
                        "is_nullable": "NO",
                        "column_default": None,
                        "ordinal_position": 1,
                    },
                    {
                        "column_name": "customer_name",
                        "data_type": "varchar",
                        "character_maximum_length": 50,
                        "is_nullable": "YES",
                        "column_default": None,
                        "ordinal_position": 2,
                    },
                ]
            )
        if "FROM sys.indexes i" in compact_query and "JOIN sys.index_columns ic" in compact_query:
            if self.deny_indexes:
                raise Exception("The user does not have permission to perform this action")
            return pd.DataFrame(
                [
                    {
                        "index_name": "PK_orders",
                        "type_desc": "CLUSTERED",
                        "is_unique": 1,
                        "is_primary_key": 1,
                        "column_name": "id",
                        "key_ordinal": 1,
                    }
                ]
            )

        raise AssertionError(f"Unexpected query: {query}")


def test_build_display_data_type_formats_lengths_and_scale():
    assert build_display_data_type(
        {"data_type": "decimal", "numeric_precision": 20, "numeric_scale": 12},
        "mysql",
    ) == "decimal(20,12)"
    assert build_display_data_type(
        {"data_type": "varchar", "character_maximum_length": 50},
        "mysql",
    ) == "varchar(50)"
    assert build_display_data_type(
        {"data_type": "string", "character_maximum_length": 50},
        "databricks",
    ) == "string(50)"


def test_split_qualified_name_strips_quotes():
    assert split_qualified_name('[dbo]."orders"') == ["dbo", "orders"]
    assert split_qualified_name("`main`.`sales`.`orders`") == ["main", "sales", "orders"]


def test_mysql_metadata_service_returns_columns_rows_and_indexes():
    connector = FakeConnector()

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders")

    assert metadata["entity_name"] == "orders"
    assert metadata["schema"] == "analytics"
    assert metadata["row_count"] == 9876543210
    assert metadata["size_pretty"] == "8.00 KB"
    assert metadata["columns"][0]["display_type"] == "decimal(20,12)"
    assert metadata["columns"][1]["display_type"] == "varchar(50)"
    assert metadata["indexes"][0]["type"] == "PRIMARY KEY"
    assert metadata["indexes"][0]["columns"] == "id"
    assert metadata["indexes"][1]["name"] == "idx_customer_name"
    assert not any("COUNT(*)" in query for query in connector.queries)


def test_mysql_metadata_row_count_supports_values_above_int32():
    connector = FakeConnector()

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders")

    assert metadata["row_count"] > 2_147_483_647
    assert isinstance(metadata["row_count"], int)


def test_mysql_view_metadata_skips_row_count():
    connector = FakeConnector()

    original_execute = connector.execute_query

    def execute_view(query: str):
        compact_query = " ".join(query.split())
        if "FROM INFORMATION_SCHEMA.TABLES" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "schema_name": "analytics",
                        "entity_name": "orders_view",
                        "entity_type": "VIEW",
                        "table_rows": 1234567890123,
                        "size_bytes": 4096,
                    }
                ]
            )
        return original_execute(query)

    connector.execute_query = execute_view

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders_view")

    assert metadata["entity_type"] == "VIEW"
    assert metadata["row_count"] is None


def test_sqlserver_metadata_uses_catalog_queries_and_large_row_count():
    connector = FakeSqlServerConnector()

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders")

    assert metadata["entity_name"] == "orders"
    assert metadata["schema"] == "dbo"
    assert metadata["row_count"] == 9876543210123
    assert metadata["size_pretty"] == "16.00 KB"
    assert metadata["indexes_supported"] is True
    assert metadata["indexes"][0]["type"] == "PRIMARY KEY"
    assert any("sys.partitions" in query for query in connector.queries)
    assert any("sys.allocation_units" in query for query in connector.queries)
    assert not any("dm_db_partition_stats" in query for query in connector.queries)


def test_sqlserver_metadata_permission_fallback_keeps_window_data():
    connector = FakeSqlServerConnector(
        deny_row_count=True,
        deny_size=True,
        deny_indexes=True,
    )

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders")

    assert metadata["entity_name"] == "orders"
    assert metadata["row_count"] is None
    assert metadata["size_bytes"] is None
    assert metadata["size_pretty"] == ""
    assert metadata["indexes"] == []
    assert metadata["indexes_supported"] is False
    assert metadata["columns"][0]["name"] == "id"
    assert metadata["columns"][1]["display_type"] == "varchar(50)"


def test_sqlserver_view_metadata_skips_catalog_row_count():
    connector = FakeSqlServerConnector(entity_type="VIEW")

    metadata = EntityMetadataService().fetch_entity_info(connector, "orders")

    assert metadata["entity_type"] == "VIEW"
    assert metadata["row_count"] is None
    assert metadata["size_bytes"] is None
    assert not any("SUM(p.rows)" in query for query in connector.queries)


class FakeSqlServerProcedureConnector:
    """Fake connector returning SQL Server procedure metadata."""

    def __init__(self, entity_type: str = "PROCEDURE"):
        self.db_type = "sqlserver"
        self.queries = []
        self.entity_type = entity_type

    def get_current_database(self):
        return "AppDB"

    def execute_query(self, query: str):
        self.queries.append(query)
        compact_query = " ".join(query.split())

        if "FROM sys.objects o" in compact_query and "WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR')" in compact_query:
            type_code = "P" if self.entity_type == "PROCEDURE" else "FN"
            return pd.DataFrame(
                [
                    {
                        "schema_name": "dbo",
                        "entity_name": "usp_GetOrders",
                        "entity_type": self.entity_type,
                        "object_type_code": type_code,
                    }
                ]
            )
        if "FROM INFORMATION_SCHEMA.PARAMETERS" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "parameter_name": "@CustomerId",
                        "data_type": "int",
                        "parameter_mode": "IN",
                        "character_maximum_length": None,
                        "numeric_precision": 10,
                        "numeric_scale": 0,
                        "ordinal_position": 1,
                    },
                    {
                        "parameter_name": "@MaxRows",
                        "data_type": "int",
                        "parameter_mode": "IN",
                        "character_maximum_length": None,
                        "numeric_precision": 10,
                        "numeric_scale": 0,
                        "ordinal_position": 2,
                    },
                ]
            )

        raise AssertionError(f"Unexpected query: {query}")


class FakeSqlServerTriggerConnector:
    """Fake connector returning SQL Server trigger metadata."""

    def __init__(self):
        self.db_type = "sqlserver"
        self.queries = []

    def get_current_database(self):
        return "AppDB"

    def execute_query(self, query: str):
        self.queries.append(query)
        compact_query = " ".join(query.split())

        if "FROM sys.objects o" in compact_query and "WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR')" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "schema_name": "dbo",
                        "entity_name": "trg_OrderAudit",
                        "entity_type": "TRIGGER",
                        "object_type_code": "TR",
                    }
                ]
            )
        if "FROM sys.triggers t" in compact_query:
            return pd.DataFrame(
                [
                    {
                        "trigger_name": "trg_OrderAudit",
                        "parent_table": "orders",
                        "parent_schema": "dbo",
                        "timing": "AFTER",
                        "events": "INSERT UPDATE",
                        "status": "Enabled",
                    }
                ]
            )

        raise AssertionError(f"Unexpected query: {query}")


def test_sqlserver_procedure_metadata_returns_parameters_and_section_type():
    connector = FakeSqlServerProcedureConnector(entity_type="PROCEDURE")

    metadata = EntityMetadataService().fetch_entity_info(connector, "usp_GetOrders")

    assert metadata["entity_name"] == "usp_GetOrders"
    assert metadata["entity_type"] == "PROCEDURE"
    assert metadata["section_type"] == "routine"
    assert metadata["row_count"] is None
    assert metadata["size_bytes"] is None
    assert len(metadata["parameters"]) == 2
    assert metadata["parameters"][0]["name"] == "@CustomerId"
    assert metadata["parameters"][0]["display_type"].startswith("int")
    assert metadata["parameters"][0]["direction"] == "IN"
    assert metadata["columns"] == []
    assert metadata["indexes"] == []
    assert metadata["indexes_supported"] is False


def test_sqlserver_function_metadata_returns_parameters_and_section_type():
    connector = FakeSqlServerProcedureConnector(entity_type="FUNCTION")

    metadata = EntityMetadataService().fetch_entity_info(connector, "usp_GetOrders")

    assert metadata["entity_type"] == "FUNCTION"
    assert metadata["section_type"] == "routine"
    assert len(metadata["parameters"]) == 2


def test_sqlserver_trigger_metadata_returns_trigger_info():
    connector = FakeSqlServerTriggerConnector()

    metadata = EntityMetadataService().fetch_entity_info(connector, "trg_OrderAudit")

    assert metadata["entity_name"] == "trg_OrderAudit"
    assert metadata["entity_type"] == "TRIGGER"
    assert metadata["section_type"] == "trigger"
    assert metadata["row_count"] is None
    assert len(metadata["parameters"]) >= 1
    parent_row = next((p for p in metadata["parameters"] if p["name"] == "Parent Table"), None)
    assert parent_row is not None
    assert "orders" in parent_row["display_type"]
