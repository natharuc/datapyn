"""Kernel destination invalidation after partially completed native exports."""

from contextlib import contextmanager
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

from datapyn_runtime import database, kernel


@pytest.mark.parametrize("outcome", ["insert_failure", "cancelled", "publish_failure", "activation_failure"])
def test_export_destination_is_invalidated_before_source_context_restoration(outcome, monkeypatch, tmp_path):
    from databricks.sqlalchemy import DatabricksDialect
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    for method in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, method, lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    cancelled = threading.Event()
    source = database.SQLiteConnector(":memory:")
    statements, messages, explorers, pools = [], [], {}, []

    class Rows:
        def mappings(self):
            return []

    class Connection:
        def in_transaction(self):
            return True

        def exec_driver_sql(self, statement):
            statements.append(statement)
            if statement.startswith("CREATE TEMPORARY") and outcome == "cancelled":
                cancelled.set()
            return Rows()

        def execute(self, statement, parameters=None):
            statements.append(str(statement.compile(dialect=DatabricksDialect())))
            if outcome == "insert_failure":
                raise RuntimeError("INSERT failed after CREATE")

    class Engine:
        dialect = DatabricksDialect()
        pool = StaticPool(creator=lambda: None)

        @contextmanager
        def begin(self):
            yield Connection()

    destination = SimpleNamespace(db_type="databricks", engine=Engine(),
                                  connection_params={"database": "destination", "schema": "reporting"},
                                  disconnect=lambda: None)

    def connect(config):
        if config["db_type"] == "sqlite":
            return source
        if outcome == "activation_failure":
            raise ConnectionError("Destination activation failed")
        return destination

    monkeypatch.setattr(database, "connect", connect)
    original_pool = database.ConnectorPool

    class TrackedPool(original_pool):
        def __init__(self, *args):
            super().__init__(*args)
            pools.append(self)

        def explorer(self):
            value = super().explorer()
            if self.active_key[0] not in explorers:
                explorers[self.active_key[0]] = value
                value.cache["stale"] = "cached objects"
                value.column_cache["stale"] = "cached columns"
            return value

    monkeypatch.setattr(database, "ConnectorPool", TrackedPool)
    jobs = [
        {"method": "connection.connect", "job_id": "connect", "params": {
            "connection_id": "source", "config": {"db_type": "sqlite", "database": ":memory:"}}},
        {"method": "execution.run", "job_id": "seed", "params": {
            "execution_id": "seed", "language": "python",
            "code": "original_engine=db_engine\nframe=pd.DataFrame({'id':[7]})"}},
        {"method": "result.export_table", "job_id": "export", "params": {
            "connection_id": "destination", "config": {"db_type": "databricks", "database": "destination"},
            "database": "destination", "connection_schema": "reporting", "schema": "", "table": "partial",
            "temporary": True, "variable_name": "frame", "operation_id": "export-operation"}},
        {"method": "execution.run", "job_id": "check", "params": {
            "execution_id": "check", "language": "python", "code":
            "assert db_engine is original_engine\nassert db_type=='sqlite'\n"
            "assert db_database==':memory:'\nassert db_schema=='main'\n"
            "assert frame['id'].tolist()==[7]"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]

    class Commands:
        def poll(self, timeout):
            return True

        def recv(self):
            return jobs.pop(0)

        def close(self):
            pass

    def send(message):
        messages.append(message)
        if message.get("language_context", {}).get("metadata_invalidated") and outcome == "publish_failure":
            raise RuntimeError("Context publication failed")
        if message.get("job_id") == "check":
            pool = pools[0]
            assert pool.active is source and pool.default_id == "source"
            assert pool.active_key == pool.default_active_key
            assert pool.default_config["db_type"] == "sqlite"

    kernel.kernel_main("session", Commands(), SimpleNamespace(send=send, close=lambda: None), export_cancel=cancelled)
    exported = next(message for message in messages if message.get("job_id") == "export")
    assert exported["error"]["code"] == ("cancelled" if outcome == "cancelled" else "operation_failed")
    checked = next(message for message in messages if message.get("job_id") == "check")
    assert checked["payload"]["status"] == "succeeded", checked
    invalidations = [message["language_context"] for message in messages
                     if message.get("language_context", {}).get("metadata_invalidated")]
    assert explorers["source"].cache and explorers["source"].column_cache
    if outcome == "activation_failure":
        assert not invalidations and not statements
    else:
        assert len(invalidations) == 1
        assert invalidations[0]["connection_id"] == "destination"
        assert invalidations[0]["database"] == "destination" and invalidations[0]["schema_name"] == "reporting"
        assert not explorers["destination"].cache and not explorers["destination"].column_cache
        assert any(statement.startswith("CREATE TEMPORARY TABLE") for statement in statements)
        assert "partial" in destination._datapyn_temporary_tables
        assert destination.has_temporary_tables
