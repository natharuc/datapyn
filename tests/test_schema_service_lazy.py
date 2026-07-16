"""SchemaService lazy loading modes."""

from unittest.mock import MagicMock

import pytest

from src.services.schema_service import (
    SCHEMA_LAZY_AUTOCOMPLETE,
    SCHEMA_LAZY_FULL,
    SCHEMA_LAZY_MINIMAL,
    SchemaWorker,
)


def test_schema_worker_minimal_skips_metadata_queries():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_MINIMAL)
    worker.run()

    connector.execute_query.assert_not_called()


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
