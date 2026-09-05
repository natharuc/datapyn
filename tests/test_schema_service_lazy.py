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


def test_schema_worker_minimal_marks_metadata_as_not_loaded():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None
    progress: list[str] = []
    captured: dict = {}

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_MINIMAL)
    worker.progress.connect(progress.append)
    worker.finished.connect(lambda schema: captured.update(schema))
    worker.run()

    assert captured["metadata_loaded"] is False
    assert not any("0 tables" in message for message in progress)


def test_schema_worker_full_marks_empty_metadata_as_loaded():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None
    progress: list[str] = []
    captured: dict = {}

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_FULL)
    worker.progress.connect(progress.append)
    worker.finished.connect(lambda schema: captured.update(schema))
    worker.run()

    assert captured["metadata_loaded"] is True
    assert any("0 tables" in message and "0 columns" in message for message in progress)


def test_schema_worker_carries_requested_database_context():
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "db_a"
    connector.get_current_database_context.return_value = "db_a"
    connector.execute_query.return_value = None
    captured: dict = {}

    worker = SchemaWorker(
        connector,
        lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
        requested_context="db_a",
        request_token=17,
    )
    worker.finished.connect(lambda schema: captured.update(schema))
    worker.run()

    assert captured["requested_context"] == "db_a"
    assert captured["connection_context"] == "db_a"
    assert captured["_schema_request_token"] == 17


def test_schema_worker_autocomplete_loads_databases_and_tables():
    """Autocomplete (connect path) preloads switch lists + table metadata."""
    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "AppDb"
    connector.get_current_database_context.return_value = "AppDb"
    connector.execute_query.return_value = None

    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE)
    worker.run()

    calls = [str(call.args[0]) for call in connector.execute_query.call_args_list]
    assert any("sys.databases" in q for q in calls)
    assert any("INFORMATION_SCHEMA.TABLES" in q for q in calls)
    assert any("INFORMATION_SCHEMA.COLUMNS" in q for q in calls)
    assert any("INFORMATION_SCHEMA.ROUTINES" in q for q in calls)


def test_schema_worker_autocomplete_loads_databricks_catalogs_and_current_schemas():
    import pandas as pd

    connector = MagicMock()
    connector.db_type = "databricks"
    connector.get_current_catalog.return_value = "main"
    connector.get_current_schema.return_value = "default"
    connector.get_current_database.return_value = "main"
    connector.get_current_database_context.return_value = "main.default"

    def _exec(query):
        q = str(query).upper()
        if "SHOW CATALOGS" in q:
            return pd.DataFrame({"catalog": ["main", "hive_metastore"]})
        if "SHOW SCHEMAS" in q:
            return pd.DataFrame({"schema": ["default", "bronze"]})
        return None

    connector.execute_query.side_effect = _exec
    captured = {}
    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE)
    worker.finished.connect(lambda schema: captured.update(schema))
    worker.run()

    assert "main" in captured.get("databases", [])
    assert "default" in (captured.get("catalog_schemas") or {}).get("main", [])
    assert "bronze" in (captured.get("catalog_schemas") or {}).get("main", [])


def test_schema_worker_autocomplete_loads_postgresql_schemas():
    import pandas as pd

    connector = MagicMock()
    connector.db_type = "postgresql"
    connector.get_current_database.return_value = "real_db"
    connector.get_current_database_context.return_value = "real_db"
    connector.get_current_schema.return_value = "public"

    def _exec(query):
        q = str(query).lower()
        if "current_database()" in q:
            return pd.DataFrame({"db": ["real_db"]})
        if "information_schema.schemata" in q:
            return pd.DataFrame({"schema_name": ["public", "metrics"]})
        return None

    connector.execute_query.side_effect = _exec
    captured = {}
    worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE)
    worker.finished.connect(lambda schema: captured.update(schema))
    worker.run()

    calls = [str(call.args[0]) for call in connector.execute_query.call_args_list]
    assert any("current_database()" in q.lower() for q in calls)
    assert any("information_schema.schemata" in q.lower() for q in calls)
    assert captured.get("databases") == ["real_db"]
    assert "public" in captured.get("schemas", [])
    assert "metrics" in captured.get("schemas", [])
    assert "pg_toast" not in captured.get("schemas", [])
    assert captured.get("current_schema") == "public"


def test_schema_service_ignores_stale_block_schema_result(qapp):
    from unittest.mock import patch

    from src.services.schema_service import SchemaService

    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "db_a"
    connector.get_current_database_context.return_value = "db_a"
    service = SchemaService()
    received: list[dict] = []
    service.schema_loaded.connect(lambda schema, *_args: received.append(schema))

    with patch("src.services.schema_service.QThread.start"):
        service.load_schema(
            connector,
            "Conn",
            session_id="sid-1",
            block_key="block-1",
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
            database_context="db_a",
        )
        old_worker = service._active_threads[-1][1]
        old_token = old_worker._request_token

        service.load_schema(
            connector,
            "Conn",
            session_id="sid-1",
            block_key="block-1",
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
            database_context="db_b",
        )
        new_worker = service._active_threads[-1][1]

    service._on_finished(
        {
            "database": "db_a",
            "current_context": "db_a",
            "connection_context": "db_a",
            "requested_context": "db_a",
            "tables": [{"name": "old_table"}],
            "columns": {},
        },
        "Conn",
        "sid-1",
        "block-1",
        request_token=old_token,
        expected_context="db_a",
    )
    assert received == []

    service._on_finished(
        {
            "database": "db_b",
            "current_context": "db_b",
            "connection_context": "db_b",
            "requested_context": "db_b",
            "tables": [{"name": "new_table"}],
            "columns": {},
        },
        "Conn",
        "sid-1",
        "block-1",
        request_token=new_worker._request_token,
        expected_context="db_b",
    )
    assert len(received) == 1
    assert received[0]["tables"][0]["name"] == "new_table"
    service.cleanup()


def test_schema_service_does_not_cancel_another_session_worker(qapp):
    from unittest.mock import patch

    from src.services.schema_service import SchemaService

    connector = MagicMock()
    connector.db_type = "sqlserver"
    connector.get_current_database.return_value = "db_a"
    connector.get_current_database_context.return_value = "db_a"
    service = SchemaService()

    with patch("src.services.schema_service.QThread.start"):
        service.load_schema(
            connector,
            "Conn",
            session_id="sid-1",
            block_key="block-1",
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
        )
        first_worker = service._active_threads[-1][1]

        service.load_schema(
            connector,
            "Conn",
            session_id="sid-2",
            block_key="block-1",
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
        )
        second_worker = service._active_threads[-1][1]

    assert first_worker._cancelled is False
    assert second_worker._cancelled is False
    service.cleanup()


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

