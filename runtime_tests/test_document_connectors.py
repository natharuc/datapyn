"""Document SDK contracts without service credentials or external databases."""

from collections import deque
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from datapyn_runtime import database
from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.cosmos_connector import CosmosConnector
from datapyn_runtime.database_capabilities import capabilities_for
from datapyn_runtime.document_config import normalize_document_config
from datapyn_runtime.document_connector import DocumentConnector, DocumentDatabaseError
from datapyn_runtime.document_explorer import DocumentExplorer
from datapyn_runtime.document_sql import read_query
from datapyn_runtime.elasticsearch_connector import ElasticsearchConnector
from datapyn_runtime.errors import serialize_runtime_error
from datapyn_runtime.mongodb_connector import MongoDBConnector


MONGO = {"db_type": "mongodb", "mongodb_uri": "mongodb://localhost:27017", "database": "analysis"}
COSMOS = {"db_type": "cosmosdb", "endpoint": "https://example.documents.azure.com", "database": "analysis",
          "container": "events", "account_key": "test-secret-only"}
ELASTIC = {"db_type": "elasticsearch", "endpoint": "https://example.invalid"}


class Secrets:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return dict(self.values.get(key, {}))

    def set(self, key, value):
        self.values[key] = dict(value)


@pytest.mark.parametrize("config", [MONGO, COSMOS, ELASTIC, {**MONGO, "db_type": "cosmosdb", "cosmos_api": "mongodb"}])
def test_document_capabilities_are_read_only_and_do_not_invent_sqlalchemy(config):
    value = capabilities_for(config["db_type"], config)
    assert value["read_only"] and value["streaming"]
    assert not any(value[key] for key in ("sqlalchemy", "table_export", "temporary_tables", "manual_transactions", "ssh"))


@pytest.mark.parametrize("uri", ["mongodb://user:secret@localhost/db", "mongodb+srv://user@host/db",
                                "mongodb://host/db?tlsCertificateKeyFilePassword=secret",
                                "mongodb://host/db?authMechanismProperties=AWS_SESSION_TOKEN:secret",
                                "mongodb://host/db#password=secret"])
def test_mongo_public_uri_rejects_embedded_credentials(uri):
    with pytest.raises(ValueError):
        normalize_document_config({**MONGO, "mongodb_uri": uri})


def test_endpoints_refuse_credentials_redirect_queries_and_cosmos_plain_http():
    for endpoint in ("https://name:secret@host", "https://host?token=secret", "https://host#token"):
        with pytest.raises(ValueError):
            normalize_document_config({**ELASTIC, "endpoint": endpoint})
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_document_config({**COSMOS, "endpoint": "http://host"})


@pytest.mark.parametrize("config", [COSMOS, MONGO, ELASTIC])
def test_document_ca_picker_field_reaches_the_sdk_configuration(config):
    normalized = normalize_document_config({**config, "ssl_ca": "C:/certs/company.pem"})
    assert normalized["ca_certificate"] == "C:/certs/company.pem"
    changed = normalize_document_config({**normalized, "ssl_ca": "C:/certs/other.pem"})
    assert changed["ca_certificate"] == "C:/certs/other.pem"
    cleared = normalize_document_config({**changed, "ssl_ca": ""})
    assert "ca_certificate" not in cleared


def test_document_secret_edits_and_endpoint_changes_never_reuse_another_account_key(tmp_path):
    secrets = Secrets()
    catalog = ConnectionCatalog(tmp_path / "connections.json", secrets)
    saved = catalog.save_connection({"name": "cosmos", "config": COSMOS}, save_password=True)
    assert saved["has_password"]
    assert "test-secret-only" not in catalog.path.read_text()
    assert catalog.config(saved["id"])["account_key"] == "test-secret-only"
    saved["config"]["account_key"] = ""
    edited = catalog.save_connection(saved, save_password=True)
    assert catalog.config(edited["id"])["account_key"] == "test-secret-only"
    edited["config"]["endpoint"] = "https://other.documents.azure.com"
    changed = catalog.save_connection(edited, save_password=True)
    assert not changed["has_password"]
    assert "account_key" not in catalog.config(changed["id"])
    assert "test-secret-only" not in json.dumps(catalog.export_document("tauri"))


def test_catalog_never_returns_unknown_casing_or_nested_credential_fields(tmp_path):
    catalog = ConnectionCatalog(tmp_path / "connections.json", Secrets())
    with pytest.raises(ValueError, match="lowercase"):
        catalog.save_connection({"name": "test", "config": {**ELASTIC, "API_KEY": "not-for-json"}})
    saved = catalog.save_connection({"name": "test", "config": {**ELASTIC, "metadata": {"API_KEY": "not-for-json"}}})
    assert "not-for-json" not in json.dumps(saved)
    assert "not-for-json" not in catalog.path.read_text()


def test_native_sql_parameters_are_bound_without_rewriting_literals():
    query = "SELECT * FROM items WHERE x=@x AND literal='@x :x; DELETE'"
    elastic, params = read_query(query, {"x": "');DROP TABLE t--"}, provider="elasticsearch")
    assert elastic == "SELECT * FROM items WHERE x=? AND literal='@x :x; DELETE'"
    assert params == ["');DROP TABLE t--"]
    cosmos, params = read_query("SELECT * FROM c WHERE c.x=:x OR c.y=:x", {"x": 5}, provider="cosmosdb")
    assert cosmos == "SELECT * FROM c WHERE c.x=@x OR c.y=@x"
    assert params == [{"name": "@x", "value": 5}]


@pytest.mark.parametrize("query", ["DELETE FROM items", "SELECT * FROM t; DROP TABLE t", "UPDATE c SET x=1"])
def test_native_sql_rejects_writes_before_transport(query):
    with pytest.raises(ValueError):
        read_query(query, provider="cosmosdb")


class Cursor:
    def __init__(self, rows):
        self.rows, self.closed = rows, False

    def __iter__(self):
        for row in self.rows:
            if isinstance(row, BaseException):
                raise row
            yield row

    def close(self):
        self.closed = True


def mongo_adapter(monkeypatch, rows):
    cursor = Cursor(rows)
    class FakeClient:
        def __init__(self, uri, **kwargs):
            self.options, self.calls, self.closed = kwargs, [], False
            self.admin = self

        def command(self, name):
            return {"ok": 1}

        def __getitem__(self, name):
            return self

        def aggregate(self, pipeline, **kwargs):
            self.calls.append((pipeline, kwargs))
            return cursor

        def close(self):
            self.closed = True
    monkeypatch.setattr("pymongo.MongoClient", FakeClient)
    adapter = MongoDBConnector(MONGO)
    adapter.connect()
    return adapter, cursor


def test_mongo_pipeline_is_remote_no_retries_and_original_types_survive(monkeypatch):
    from bson import Decimal128, ObjectId
    identifier = ObjectId()
    adapter, cursor = mongo_adapter(monkeypatch, [{"_id": identifier, "amount": Decimal128("1.234567890123456789"),
                                                 "large": 9223372036854775807, "nested": {"a": [1, 2]}}])
    frame = adapter.execute_query("SELECT * FROM events LIMIT 5")
    assert frame.loc[0, "_id"] is identifier
    assert frame.loc[0, "amount"] == Decimal("1.234567890123456789")
    assert frame.loc[0, "large"] == 9223372036854775807
    assert frame.loc[0, "nested"] == {"a": [1, 2]}
    assert frame.attrs["datapyn_document_result"]
    assert not adapter.client.options["retryReads"] and not adapter.client.options["retryWrites"]
    assert len(adapter.client.calls) == 1 and cursor.closed
    assert any("$limit" in stage for stage in adapter.client.calls[0][0])


def test_mongo_unsupported_and_limit_zero_do_not_open_query_cursor(monkeypatch):
    adapter, cursor = mongo_adapter(monkeypatch, [])
    with pytest.raises(ValueError):
        adapter.execute_query("SELECT * FROM events JOIN other ON events.a=other.a")
    frame = adapter.execute_query("SELECT name FROM events LIMIT 0")
    assert frame.empty and list(frame.columns) == ["name"]
    assert adapter.client.calls == []


@pytest.mark.parametrize("error_type", ["reconnect", "not_primary"])
def test_mongo_getmore_failure_closes_cursor_and_does_not_repeat_query(monkeypatch, error_type):
    from pymongo.errors import AutoReconnect, NotPrimaryError
    from src.database.connection_recovery import ConnectionLostError
    error = NotPrimaryError("secret document body", {"code": 10107}) if error_type == "not_primary" else AutoReconnect("secret document body")
    adapter, cursor = mongo_adapter(monkeypatch, [{"a": 1}] * 1000 + [error])
    with pytest.raises(ConnectionLostError) as caught:
        adapter.execute_query("SELECT * FROM events")
    assert "secret document body" not in str(caught.value)
    assert cursor.closed and len(adapter.client.calls) == 1
    assert adapter.get_connection_recovery_state()["required"]


def test_mongo_permission_error_is_not_transport_even_when_operation_failed():
    from pymongo.errors import OperationFailure
    adapter = MongoDBConnector(MONGO)
    adapter._connected = True
    with pytest.raises(DocumentDatabaseError) as caught:
        adapter._failure(OperationFailure("private document body", code=13), submitted=True)
    assert caught.value.status_code == 403
    assert not adapter.get_connection_recovery_state()["required"]
    assert "private document body" not in str(caught.value)


@pytest.mark.parametrize("status, category", [(401, "authentication"), (403, "permission"), (404, "not_found"),
                                             (429, "throttling"), (408, "timeout"), (400, "syntax")])
def test_document_errors_have_concise_categories_without_transport_recovery(status, category):
    adapter = DocumentConnector(ELASTIC)
    adapter._connected = True
    with pytest.raises(DocumentDatabaseError) as caught:
        adapter._failure(DocumentDatabaseError("Brief diagnostic", status_code=status), submitted=True)
    assert serialize_runtime_error(caught.value)["error_info"]["category"] == category
    assert not adapter.get_connection_recovery_state()["required"]


def test_cosmos_mongo_throttling_is_not_a_network_failure():
    from pymongo.errors import OperationFailure
    adapter = DocumentConnector({**MONGO, "db_type": "cosmosdb", "cosmos_api": "mongodb"})
    with pytest.raises(DocumentDatabaseError) as caught:
        adapter._failure(OperationFailure("contains sensitive document", code=16500), submitted=True)
    assert caught.value.status_code == 429 and "sensitive" not in str(caught.value)


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.closed = data, status, False

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield json.dumps(self.data).encode()

    def close(self):
        self.closed = True


def elastic_adapter(monkeypatch, pages):
    class Http:
        def __init__(self):
            self.headers, self.calls = {}, []
            self.responses = deque(pages)

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return self.responses.popleft()

        def close(self):
            pass
    monkeypatch.setattr("requests.Session", Http)
    adapter = ElasticsearchConnector(ELASTIC)
    adapter.connect()
    return adapter


def test_elasticsearch_consumes_empty_pages_and_releases_cursor(monkeypatch):
    adapter = elastic_adapter(monkeypatch, [Response({"rows": [[1]]}),
        Response({"columns": [{"name": "x", "type": "long"}], "rows": [], "cursor": "a"}),
        Response({"rows": [], "cursor": "b"}), Response({"rows": [[42]], "cursor": "c"}),
        Response({"rows": [[43]]})])
    frame = adapter.execute_query('SELECT x FROM "events"')
    assert frame["x"].tolist() == [42, 43]
    assert len(adapter.session.calls) == 5
    assert all(call[2]["allow_redirects"] is False for call in adapter.session.calls)


def test_elasticsearch_page_error_never_publishes_partial_frame_and_closes_cursor(monkeypatch):
    adapter = elastic_adapter(monkeypatch, [Response({"rows": [[1]]}),
        Response({"columns": [{"name": "x"}], "rows": [[1]], "cursor": "a"}),
        Response({"error": {"reason": "contains password=secret"}}, 400), Response({"succeeded": True})])
    with pytest.raises(DocumentDatabaseError):
        adapter.execute_query("SELECT x FROM events")
    assert adapter.session.calls[-1][1].endswith("/_sql/close")
    assert adapter.session.calls[-1][2]["json"] == {"cursor": "a"}


def test_cosmos_container_paging_and_empty_continuation_are_explicit():
    adapter = CosmosConnector(COSMOS)
    calls = []
    class Container:
        def query_items(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(by_page=lambda: iter([[], [{"x": 1}], [], [{"x": 2}]]))
    db = SimpleNamespace(get_container_client=lambda name: Container())
    adapter.client = SimpleNamespace(get_database_client=lambda name: db)
    frame = adapter.execute_query("SELECT c.x FROM c WHERE c.x=@x", {"x": 1})
    assert frame["x"].tolist() == [1, 2]
    assert calls[0]["parameters"] == [{"name": "@x", "value": 1}]
    assert adapter.connection_params["container"] == "events"
    adapter.connection_params["container"] = ""
    with pytest.raises(ValueError, match="container"):
        adapter.execute_query("SELECT * FROM c")


def test_pool_separates_cosmos_containers_and_keeps_relational_defaults(monkeypatch):
    opened = []
    def connect(config):
        adapter = CosmosConnector(config)
        adapter._connected = True
        opened.append(adapter)
        return adapter
    monkeypatch.setattr(database, "connect", connect)
    pool = database.ConnectorPool()
    first = pool.activate({"connection_id": "saved", "config": COSMOS, "container": "first"}, default=True)
    second = pool.activate({"connection_id": "saved", "config": COSMOS, "container": "second"})
    assert first is not second and len(opened) == 2
    assert pool.explorer().context()["container"] == "second"
    assert pool.default_config["container"] == "first"


def test_explorer_samples_only_referenced_collection_and_marks_fields_partial():
    adapter = MongoDBConnector(MONGO)
    samples = []
    adapter.databases = lambda: ["analysis"]
    adapter.collections = lambda database: ["events", "other"]
    def sample(database, collection):
        samples.append(collection)
        return [{"a": {"nested": 5}, "array": [1, 2]}, {"a": None, "later": 9}]
    adapter.sample = sample
    explorer = DocumentExplorer(adapter)
    snapshot = explorer.completion_schema("SELECT e.a FROM events e")
    assert samples == ["events"]
    assert snapshot["metadata_partial"] and snapshot["current_schema"] == ""
    assert {item["name"] for item in snapshot["columns"]["events"]} == {"a", "a.nested", "array", "later"}
    explorer.completion_schema("SELECT e.a FROM events e")
    assert samples == ["events"]


def test_document_stream_download_keeps_late_columns_and_compound_json(tmp_path):
    adapter = DocumentConnector(MONGO)
    def batches(query, parameters=None):
        yield [{"first": 1, "nested": {"a": [1, 2]}}]
        yield [{"first": 2, "late": "present"}]
    adapter.iter_batches = batches
    destination = tmp_path / "result.csv"
    from datapyn_runtime.stream_export import run
    result = run(adapter, "SELECT * FROM events", path=destination, export_format="csv")
    import csv
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["late"] == "present"
    assert json.loads(rows[0]["nested"]) == {"a": [1, 2]}
    assert result["total_rows"] == 2


def test_document_stream_failure_preserves_existing_destination(tmp_path):
    adapter = DocumentConnector(MONGO)
    def batches(query, parameters=None):
        yield [{"first": 1}]
        raise DocumentDatabaseError("Cursor expired")
    adapter.iter_batches = batches
    destination = tmp_path / "result.csv"
    destination.write_text("original")
    from datapyn_runtime.stream_export import run
    with pytest.raises(DocumentDatabaseError):
        run(adapter, "SELECT * FROM events", path=destination)
    assert destination.read_text() == "original"
    assert list(tmp_path.glob(".datapyn-export-*")) == []


def test_metadata_does_not_sample_names_in_comments_or_another_focused_database():
    adapter = MongoDBConnector(MONGO)
    adapter.databases = lambda: ["analysis", "other"]
    adapter.collections = lambda database: ["Events", "events", "ignored"]
    sampled = []
    adapter.sample = lambda database, name: sampled.append((database, name)) or [{"actual": 1}]
    snapshot = DocumentExplorer(adapter).completion_schema("SELECT e.actual FROM other.Events e -- FROM ignored\nWHERE e.actual='FROM events'")
    assert sampled == [("other", "Events")]
    assert "other.Events" in snapshot["columns"]
    assert "Events" not in snapshot["columns"]


def test_elasticsearch_dates_follow_declared_type_and_reject_malformed_rows(monkeypatch):
    from datetime import datetime, timezone
    adapter = elastic_adapter(monkeypatch, [Response({"rows": [[1]]}), Response({
        "columns": [{"name": "date", "type": "datetime"}, {"name": "text", "type": "keyword"}],
        "rows": [["2026-11-11T12:30:00Z", "2026-11-11T12:30:00Z"]]})])
    frame = adapter.execute_query("SELECT date, text FROM events")
    assert frame.loc[0, "date"] == datetime(2026, 11, 11, 12, 30, tzinfo=timezone.utc)
    assert frame.loc[0, "text"] == "2026-11-11T12:30:00Z"
    adapter.session.responses.append(Response({"columns": [{"name": "a"}], "rows": [[1, "must not disappear"]]}))
    with pytest.raises(DocumentDatabaseError, match="does not match"):
        adapter.execute_query("SELECT a FROM events")


@pytest.mark.parametrize("error_type", ["mongo", "azure"])
def test_wrapped_certificate_failure_never_requests_reconnection(error_type):
    if error_type == "mongo":
        from pymongo.errors import ServerSelectionTimeoutError
        error = ServerSelectionTimeoutError("TLS certificate verify failed; account_key=secret")
    else:
        from azure.core.exceptions import ServiceRequestError
        error = ServiceRequestError("TLS certificate verify failed; account_key=secret")
    adapter = DocumentConnector(MONGO)
    adapter._connected = True
    with pytest.raises(DocumentDatabaseError, match="certificate") as caught:
        adapter._failure(error, submitted=True)
    assert "secret" not in str(caught.value)
    assert not adapter.get_connection_recovery_state()["required"]


@pytest.mark.parametrize("automatic", [True, False])
def test_kernel_switch_removes_stale_engine_and_sql_helper_keeps_context(monkeypatch, automatic):
    from datapyn_runtime import kernel
    from datapyn_runtime.transaction_settings import editor_context_key
    opened = []
    def connect(config):
        if config["db_type"] == "sqlite":
            return database.SQLiteConnector(":memory:", config.get("automatic_transactions", True))
        adapter = DocumentConnector(config)
        adapter._connected = True
        adapter.databases = lambda: [config["database"]]
        adapter.collections = lambda database: ["events", "other"]
        adapter.sample = lambda database, collection: [{"name": "ok"}]
        def batches(query, parameters=None):
            yield [{"name": "ok"}]
        adapter.iter_batches = batches
        opened.append(adapter)
        return adapter
    monkeypatch.setattr(database, "connect", connect)
    for name in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, name, lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.sql_safety_guard.settings_get", lambda *args: {"confirm_destructive_sql": False})
    relational = {"config": {"db_type": "sqlite", "database": ":memory:"}, "connection_id": "local",
                  "_automatic_transactions_snapshot": automatic}
    target = {"config": {key: value for key, value in COSMOS.items() if key != "account_key"}, "connection_id": "document",
              "database": "analysis", "container": "events", "block_id": "block", "scope_inherited": True,
              "_automatic_transactions_snapshot": automatic}
    other = {**target, "container": "other"}
    jobs = [
        {"method": "connection.connect", "job_id": "sqlite", "params": relational},
        {"method": "execution.run", "job_id": "seed", "params": {**relational, "execution_id": "seed", "language": "python", "code": "assert db_engine is not None\nkeep=7"}},
        {"method": "connection.connect", "job_id": "doc", "params": target},
        {"method": "execution.run", "job_id": "query", "params": {**target, "execution_id": "query", "language": "python",
            "code": "assert 'db_engine' not in globals()\nassert keep==7\nassert db_container=='events'\nresult=sql('SELECT * FROM c')\nassert result.name.tolist()==['ok']"}},
        {"method": "explorer.use_database", "job_id": "switch", "params": other},
        {"method": "language.context", "job_id": "metadata", "params": {**other, "code": "SELECT c.name FROM c"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]
    class Commands:
        def poll(self, timeout): return True
        def recv(self): return jobs.pop(0)
        def close(self): pass
    messages = []
    kernel.kernel_main("session", Commands(), SimpleNamespace(send=messages.append, close=lambda: None))
    query = next(item["payload"] for item in messages if item.get("job_id") == "query")
    assert query["status"] == "succeeded", query
    connected = next(item["result"] for item in messages if item.get("job_id") == "doc")
    assert connected["container"] == "events" and not connected["capabilities"]["sqlalchemy"]
    updates = [item["language_context"] for item in messages if "language_context" in item]
    final = updates[-1]
    assert final["container"] == "other" and final["key"] == editor_context_key(other)
    assert final["requested_scope"]["container"] == "other"
    assert final["capabilities"]["manual_transactions"] is False
    assert final["automatic_transactions"] is automatic
