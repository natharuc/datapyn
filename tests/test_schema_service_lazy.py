"""SchemaService lazy loading modes."""

from unittest.mock import MagicMock

import pytest

from src.services.schema_service import (
    SCHEMA_LAZY_AUTOCOMPLETE,
    SCHEMA_LAZY_FULL,
    SCHEMA_LAZY_MINIMAL,
    SchemaWorker,
)


def test_schema_worker_minimal_loads_databricks_schemas():
    connector = MagicMock()
    connector.db_type = "databricks"
    connector.get_current_catalog.return_value = "main"
    connector.get_current_schema.return_value = "default"
    connector.get_current_database_context.return_value = "main.default"
    connector.execute_query.side_effect = [
        __import__("pandas").DataFrame({"catalog": ["main", "hive_metastore"]}),
        __import__("pandas").DataFrame({"schema": ["default", "audit"]}),
    ]

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_MINIMAL)
    schema = {}
    worker.finished.connect(lambda result: schema.update(result))
    worker.run()

    assert "SHOW CATALOGS" in str(connector.execute_query.call_args_list[0])
    assert "SHOW SCHEMAS IN `main`" in str(connector.execute_query.call_args_list[1])
    assert schema["catalog_schemas"]["main"] == ["audit", "default"]


def test_schema_cache_identity_uses_connection_group():
    from src.services.schema_service import SchemaService

    service = SchemaService()
    service.update_cached_schema(
        "DBX",
        {"tables": [], "columns": {}, "database": "main"},
        session_id="s1",
        connection_group="MAG",
    )
    cached = service.get_cached_schema("DBX", session_id="s1", connection_group="MAG")
    assert cached is not None
    assert cached["database"] == "main"

    other = service.get_cached_schema("DBX", session_id="s1", connection_group="OTHER")
    assert other is None


def test_schema_worker_minimal_loads_databases_only():
    """Minimal mode loads the cheap server database list but skips tables/columns/routines."""
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_MINIMAL)
    worker.run()

    calls = [str(call.args[0]) for call in connector.execute_query.call_args_list]
    # The single cheap catalog query for the server database list.
    assert any("sys.databases" in q for q in calls)
    # No tables/columns/routines metadata in minimal mode.
    assert not any("INFORMATION_SCHEMA.TABLES" in q for q in calls)
    assert not any("INFORMATION_SCHEMA.COLUMNS" in q for q in calls)
    assert not any("INFORMATION_SCHEMA.ROUTINES" in q for q in calls)


def test_schema_worker_autocomplete_loads_tables_not_databases():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE)
    worker.run()

    calls = [str(call.args[0]) for call in connector.execute_query.call_args_list]
    assert not any("sys.databases" in q for q in calls)
    assert any("INFORMATION_SCHEMA.TABLES" in q for q in calls)
    assert any("INFORMATION_SCHEMA.COLUMNS" in q for q in calls)
    assert any("INFORMATION_SCHEMA.ROUTINES" in q for q in calls)


def test_schema_worker_full_loads_databases():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_FULL)
    worker.run()

    calls = [str(call.args[0]) for call in connector.execute_query.call_args_list]
    assert any("sys.databases" in q for q in calls)


def test_load_databases_emits_databases_loaded(qtbot):
    """SchemaService.load_databases fetches the server db list and emits databases_loaded."""
    import pandas as pd

    from src.services.schema_service import SchemaService

    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.execute_query.return_value = pd.DataFrame({"name": ["master", "AppDb", "tempdb"]})

    service = SchemaService()
    captured: dict = {}

    def _on_loaded(connection_name, session_id, databases):
        captured["connection_name"] = connection_name
        captured["session_id"] = session_id
        captured["databases"] = list(databases or [])

    service.databases_loaded.connect(_on_loaded)

    service.load_databases(connector, "Gecon", session_id="sid-1")

    qtbot.waitUntil(lambda: "databases" in captured, timeout=3000)

    assert captured["connection_name"] == "Gecon"
    assert captured["session_id"] == "sid-1"
    assert captured["databases"] == ["master", "AppDb", "tempdb"]

    service.cleanup()

