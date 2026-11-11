"""Compiler boundary tests; optional live tests assert server-side semantics."""

from datetime import datetime, timezone
from decimal import Decimal

from bson import BSON, Decimal128, ObjectId
import pytest

from datapyn_runtime.mongo_sql import UnsupportedMongoSql, compile_query


def test_projection_alias_database_and_order_are_server_side():
    compiled = compile_query("SELECT u.name AS person, u.address.city AS city FROM analytics.users u "
                             "WHERE u.age >= :minimum ORDER BY person, u.age DESC LIMIT 10 OFFSET 2",
                             {"minimum": 18}, database="other")
    assert compiled.database == "analytics"
    assert compiled.collection == "users"
    assert compiled.columns == ["person", "city"]
    assert compiled.pipeline[0] == {"$match": {"age": {"$gte": 18}}}
    assert compiled.pipeline[-4:] == [
        {"$sort": {"name": 1, "age": -1}}, {"$skip": 2}, {"$limit": 10},
        {"$project": {"person": {"$ifNull": ["$name", None]},
                      "city": {"$ifNull": ["$address.city", None]}, "_id": 0}},
    ]
    assert "$expr" in compiled.pipeline[1]["$match"]
    BSON.encode({"pipeline": compiled.pipeline})


def test_zero_limit_never_becomes_mongo_unlimited_query():
    compiled = compile_query("SELECT name FROM users LIMIT 0")
    assert compiled.limit_zero is True
    assert {"$match": {"$expr": {"$literal": False}}} in compiled.pipeline
    assert not any("$limit" in stage for stage in compiled.pipeline)
    assert compiled.columns == ["name"]


@pytest.mark.parametrize("sql", ["SELECT * FROM users", "SELECT u.* FROM users u"])
def test_wildcard_keeps_document_structure(sql):
    compiled = compile_query(sql, database="db")
    assert compiled.database == "db" and compiled.collection == "users"
    assert compiled.columns is None and compiled.pipeline == []


@pytest.mark.parametrize("query", [
    "DELETE FROM users", "UPDATE users SET age=1", "DROP DATABASE db", "TRUNCATE TABLE users",
    "SELECT * FROM users; DELETE FROM users", "SELECT * FROM users; SELECT * FROM orders",
    "WITH x AS (SELECT * FROM users) SELECT * FROM x", "SELECT * FROM (SELECT * FROM users) q",
    "SELECT * FROM users JOIN orders ON users.id=orders.id", "SELECT * FROM users, orders",
    "SELECT COUNT(*) FROM users", "SELECT DISTINCT name FROM users", "SELECT age FROM users GROUP BY age",
    "SELECT * FROM users UNION SELECT * FROM orders", "SELECT ROW_NUMBER() OVER() FROM users",
    "SELECT * INTO other FROM users", "SELECT * FROM users FOR UPDATE", "SELECT * FROM users TABLESAMPLE (10)",
    "SELECT * FROM users WHERE age BETWEEN 1 AND 10", "SELECT * FROM users WHERE name LIKE 'N%'",
    "SELECT * FROM users WHERE age IN (SELECT age FROM older)", "SELECT COALESCE(name,'') FROM users",
    "SELECT * EXCEPT(age) FROM users", "SELECT * REPLACE(1 AS age) FROM users",
    "SELECT * FROM a.b.c", "SELECT * FROM users u(id)", "SELECT", "SELECT FROM users", "SELECT 1",
    "SELECT * FROM users LIMIT -1", "SELECT * FROM users LIMIT 1.5", "SELECT * FROM users LIMIT '5'",
    "SELECT * FROM users LIMIT 2 WITH TIES", "SELECT * FROM users ORDER BY age ASC NULLS LAST",
    "SELECT * FROM users ORDER BY age DESC NULLS FIRST", "SELECT * FROM users ORDER BY RAND()",
    "SELECT 1 AS fixed FROM users ORDER BY fixed", "SELECT a AS x,b AS x FROM users",
    'SELECT a AS "x.y" FROM users', 'SELECT "a.b" FROM users', 'SELECT "$where" FROM users',
    "SELECT * FROM users WHERE age IN ()", "SELECT * FROM users WHERE age IN (other)",
])
def test_unsupported_syntax_is_rejected_instead_of_approximated(query):
    with pytest.raises(UnsupportedMongoSql):
        compile_query(query)


def test_sql_values_cannot_become_operators_or_field_references():
    value = "$where; DROP DATABASE db; --"
    compiled = compile_query("SELECT :value AS answer FROM users WHERE name = @value", {"value": value})
    projection = compiled.pipeline[-1]["$project"]["answer"]
    assert projection == {"$ifNull": [{"$literal": value}, None]}
    assert compiled.pipeline[0] == {"$match": {"name": {"$eq": value}}}
    BSON.encode({"pipeline": compiled.pipeline})
    pending = list(compiled.pipeline)
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            assert "$where" not in item and "$function" not in item
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def test_parameters_keep_bson_types_and_exact_precision():
    moment = datetime(2026, 11, 11, 12, 34, tzinfo=timezone.utc)
    oid = ObjectId("0123456789abcdef01234567")
    compiled = compile_query("SELECT :decimal AS amount, :big AS big, :oid AS oid, :at AS at FROM users",
                             {"decimal": Decimal("12345678901234567890.123456789"), "big": 2**63,
                              "oid": oid, "at": moment})
    decoded = BSON.encode({"pipeline": compiled.pipeline})
    assert BSON(decoded).decode()["pipeline"][-1]["$project"]["amount"]["$ifNull"][0]["$literal"] == Decimal128("12345678901234567890.123456789")
    assert compiled.pipeline[-1]["$project"]["big"]["$ifNull"][0]["$literal"] == Decimal128(str(2**63))
    assert compiled.pipeline[-1]["$project"]["oid"]["$ifNull"][0]["$literal"] == oid


@pytest.mark.parametrize("value", [{"$gt": 1}, [1, 2], float("nan"), float("inf"), Decimal("NaN"), int("1" * 40)])
def test_invalid_bound_values_fail_before_io(value):
    with pytest.raises(UnsupportedMongoSql):
        compile_query("SELECT * FROM users WHERE age=:value", {"value": value})


@pytest.mark.parametrize("limit", [True, -1, 1.5, "1", 2**63])
def test_pagination_parameters_are_not_coerced(limit):
    with pytest.raises(UnsupportedMongoSql):
        compile_query("SELECT * FROM users LIMIT :limit", {"limit": limit})


def test_missing_parameter_and_unnamed_placeholders_are_clear():
    for query in ["SELECT * FROM users WHERE age=:missing", "SELECT * FROM users WHERE age=?"]:
        with pytest.raises(UnsupportedMongoSql, match="parâmetro"):
            compile_query(query)


def test_resource_limits_do_not_parse_unbounded_input():
    with pytest.raises(UnsupportedMongoSql, match="128 KiB"):
        compile_query("SELECT * FROM users --" + "x" * (128 * 1024))
    with pytest.raises(UnsupportedMongoSql, match="complexa"):
        compile_query("SELECT * FROM users WHERE " + "(" * 120 + "age=1" + ")" * 120)


def test_data_definition_parameters_use_existing_typed_preparation():
    params = [{"id": "sqlparam:age", "name": "age", "label": "", "order": 0,
               "sql_type": "integer", "input_kind": "value", "value": "21", "required": True,
               "default_value": "", "options": [], "multi_select": False, "type_source": "default"}]
    compiled = compile_query("SELECT age FROM users WHERE age >= @age", params)
    assert compiled.pipeline[0] == {"$match": {"age": {"$gte": 21}}}


def test_comments_and_quoted_collection_do_not_enable_other_statements():
    compiled = compile_query('/* DELETE */ SELECT * FROM "audit-log" -- DROP DATABASE fake\n; ;')
    assert compiled.collection == "audit-log"
    assert compiled.pipeline == []
