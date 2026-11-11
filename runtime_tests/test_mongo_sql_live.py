"""Optional contract against an explicitly provided, disposable local MongoDB.

DATAPYN_TEST_MONGO_URI must be a credential-free loopback URI. Tests create and
drop only a fresh UUID-named database; they never use an existing database.
No server is downloaded, installed or started by this test module.
"""

from datetime import datetime, timezone
from decimal import Decimal
import os
from urllib.parse import urlsplit
import uuid

from bson import Decimal128, Int64, ObjectId
from pymongo import MongoClient, monitoring
import pytest

from datapyn_runtime.mongo_sql import UnsupportedMongoSql, compile_query

URI = os.environ.get("DATAPYN_TEST_MONGO_URI", "")
pytestmark = pytest.mark.skipif(not URI, reason="DATAPYN_TEST_MONGO_URI not provided (isolated local MongoDB only)")


class _Commands(monitoring.CommandListener):
    def __init__(self):
        self.names = []

    def started(self, event):
        self.names.append(event.command_name)

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


@pytest.fixture(scope="module")
def live_database():
    parsed = urlsplit(URI)
    if (parsed.scheme != "mongodb" or parsed.hostname not in {"127.0.0.1", "::1"}
            or not parsed.port or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in {"", "/"}):
        raise pytest.UsageError("DATAPYN_TEST_MONGO_URI must contain only mongodb://127.0.0.1:port or [::1]:port")
    commands = _Commands()
    client = MongoClient(URI, directConnection=True, tz_aware=True, retryReads=False, retryWrites=False,
                         serverSelectionTimeoutMS=3000, connectTimeoutMS=3000, socketTimeoutMS=5000,
                         event_listeners=[commands])
    name = "datapyn_sql_test_" + uuid.uuid4().hex
    try:
        client.admin.command("ping")
        database = client[name]
        database.cases.insert_many([
            {"_id": 1, "x": 1, "name": "one", "active": True, "nested": {"city": "Recife"},
             "amount": Decimal128("123.40"), "oid": ObjectId("000000000000000000000001"),
             "large": Int64(2**60), "at": datetime(2026, 1, 1, tzinfo=timezone.utc), "payload": b"\x00\xff"},
            {"_id": 2, "x": 2, "name": "two", "active": False},
            {"_id": 3, "x": None, "name": "null"},
            {"_id": 4, "name": "missing"},
            {"_id": 5, "x": [1, 2], "name": "array"},
            {"_id": 6, "x": "2", "name": "string"},
            {"_id": 7, "x": False, "name": "boolean"},
            {"_id": 8, "x": 3, "name": "three"},
            {"_id": 9, "x": [], "name": "empty-array"},
        ])
        yield database, commands
    finally:
        try:
            # The only destructive test action targets the fresh name owned
            # above, never a database supplied by the environment/URI.
            assert name.startswith("datapyn_sql_test_") and len(name) == len("datapyn_sql_test_") + 32
            client.drop_database(name)
        finally:
            client.close()


def _run(database, query, parameters=None, batch_size=2):
    compiled = compile_query(query, parameters, database=database.name)
    if compiled.limit_zero:
        return []
    assert compiled.database == database.name
    with database[compiled.collection].aggregate(compiled.pipeline, batchSize=batch_size, maxTimeMS=5000) as cursor:
        return list(cursor)


@pytest.mark.parametrize(("predicate", "ids"), [
    ("x = 1", [1]),
    ("x <> 1", [2, 8]),
    ("NOT (x = 1)", [2, 8]),
    ("x < 2", [1]),
    ("x >= 2", [2, 8]),
    ("x IS NULL", [3, 4]),
    ("x IS NOT NULL", [1, 2, 5, 6, 7, 8, 9]),
    ("NOT (x IS NULL)", [1, 2, 5, 6, 7, 8, 9]),
    ("x IN (1, 2, NULL)", [1, 2]),
    ("x NOT IN (1, NULL)", []),
    ("x NOT IN (1, 2)", [8]),
    ("x = NULL", []),
    ("NOT (x = NULL)", []),
    ("x = 1 OR x IS NULL", [1, 3, 4]),
    ("x = 1 AND x IS NULL", []),
    ("NOT (x = 1 OR x IS NULL)", [2, 8]),
    ("active", [1]),
    ("NOT active", [2]),
])
def test_scalar_predicates_null_missing_and_arrays_on_mongodb(live_database, predicate, ids):
    database, _ = live_database
    rows = _run(database, f"SELECT _id FROM cases WHERE {predicate} ORDER BY _id")
    assert [row["_id"] for row in rows] == ids


def test_projection_nested_paths_literals_and_order_alias(live_database):
    database, _ = live_database
    assert _run(database, "SELECT p.nested.city AS cidade, p.name AS nome, '$x' AS literal FROM cases p WHERE p._id = 1") == [
        {"cidade": "Recife", "nome": "one", "literal": "$x"}]
    rows = _run(database, "SELECT c.x AS value FROM cases c WHERE c.x >= 1 ORDER BY value DESC LIMIT 2 OFFSET 1")
    assert rows == [{"value": 2}, {"value": 1}]


@pytest.mark.parametrize(("field", "value"), [
    ("oid", ObjectId("000000000000000000000001")),
    ("amount", Decimal("123.40")),
    ("large", Int64(2**60)),
    ("at", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ("payload", b"\x00\xff"),
])
def test_bson_parameter_types_are_not_stringified(live_database, field, value):
    database, _ = live_database
    rows = _run(database, f"SELECT _id, {field} AS original FROM cases WHERE {field} = :value", {"value": value})
    assert len(rows) == 1 and rows[0]["_id"] == 1
    actual = rows[0]["original"]
    assert actual.to_decimal() == value if isinstance(actual, Decimal128) else actual == value


def test_real_cursor_uses_getmore_without_reexecuting_aggregate(live_database):
    database, commands = live_database
    commands.names.clear()
    rows = _run(database, "SELECT _id FROM cases ORDER BY _id LIMIT 7", batch_size=2)
    assert [row["_id"] for row in rows] == list(range(1, 8))
    assert commands.names.count("aggregate") == 1
    assert "getMore" in commands.names


def test_limit_zero_does_not_send_a_query(live_database):
    database, commands = live_database
    commands.names.clear()
    assert _run(database, "SELECT _id FROM cases LIMIT 0") == []
    assert not commands.names


def test_real_adapter_preserves_bson_types_in_dataframe(live_database):
    from datapyn_runtime.mongodb_connector import MongoDBConnector
    database, _ = live_database
    connector = MongoDBConnector({"db_type": "mongodb", "mongodb_uri": URI, "database": database.name})
    try:
        connector.connect()
        frame = connector.execute_query(
            "SELECT amount, oid, large, at, payload, nested FROM cases WHERE _id = :id", {"id": 1})
        assert frame.columns.to_list() == ["amount", "oid", "large", "at", "payload", "nested"]
        assert len(frame) == 1
        row = frame.iloc[0]
        assert row["amount"] == Decimal("123.40")
        assert row["oid"] == ObjectId("000000000000000000000001")
        assert row["large"] == 2**60
        assert row["at"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert row["payload"] == b"\x00\xff"
        assert row["nested"] == {"city": "Recife"}
        assert frame.attrs["datapyn_document_result"] is True
        assert connector.execute_query("SELECT oid FROM cases LIMIT 0").columns.to_list() == ["oid"]
    finally:
        connector.disconnect()


def test_real_adapter_explorer_lists_and_infers_bounded_metadata(live_database):
    from datapyn_runtime.document_explorer import DocumentExplorer
    from datapyn_runtime.mongodb_connector import MongoDBConnector
    database, _ = live_database
    connector = MongoDBConnector({"db_type": "mongodb", "mongodb_uri": URI, "database": database.name})
    try:
        connector.connect()
        explorer = DocumentExplorer(connector)
        assert database.name in explorer.databases()
        nodes = explorer.list({"node": {"kind": "database", "name": database.name}})["nodes"]
        assert any(node["name"] == "cases" and node["object_type"] == "collection" for node in nodes)
        details = explorer.details({"name": "cases", "database": database.name})
        fields = {column["name"]: column for column in details["columns"]}
        assert "nested.city" in fields and fields["nested.city"]["partial"] is True
        assert fields["x"]["dtype"] == "mixed"
    finally:
        connector.disconnect()


@pytest.mark.parametrize("query", [
    "DELETE FROM cases", "SELECT COUNT(*) FROM cases", "SELECT * FROM cases JOIN other ON cases._id = other._id",
    "SELECT * FROM cases UNION SELECT * FROM other", "SELECT * FROM cases; SELECT * FROM cases",
])
def test_unsupported_sql_is_rejected_before_any_server_command(live_database, query):
    from datapyn_runtime.mongodb_connector import MongoDBConnector
    database, commands = live_database
    connector = MongoDBConnector({"db_type": "mongodb", "mongodb_uri": URI, "database": database.name})
    connector.client = database.client
    commands.names.clear()
    with pytest.raises(UnsupportedMongoSql):
        list(connector.iter_batches(query))
    assert not commands.names
