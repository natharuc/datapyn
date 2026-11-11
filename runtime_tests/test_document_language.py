from datapyn_runtime.language import dispatch
from datapyn_runtime.sql_context import metadata_signature
from datapyn_runtime.syntax_diagnostics import diagnose


def schema(kind="mongodb", **extra):
    return {"db_type": kind, "database": "db", "current_schema": "", "metadata_partial": True,
            "tables": [{"name": "Events", "key": "Events"}, {"name": "events", "key": "events"}],
            "columns": {"Events": [{"name": "UpperField", "type": "int"}, {"name": "address.city", "type": "str"}],
                        "events": [{"name": "lower_field", "type": "str"}]}, **extra}


def complete(code, snapshot):
    position = code.index("|")
    text = code.replace("|", "")
    return dispatch("language.complete", {"language": "sql", "code": text, "line": 1, "column": position + 1},
                    {"schema": snapshot, "version": 1})["items"]


def test_case_sensitive_collections_use_their_own_columns():
    assert {item["label"] for item in complete("SELECT e.| FROM Events e", schema())} == {"UpperField", "address.city"}
    assert {item["label"] for item in complete("SELECT e.| FROM events e", schema())} == {"lower_field"}


def test_nested_column_suggestions_are_paths_not_literal_dotted_keys():
    items = complete("SELECT e.| FROM Events e", schema())
    nested = next(item for item in items if item["label"] == "address.city")
    assert nested["insert_text"] == "address.city"
    nested_tail = complete("SELECT e.address.| FROM Events e", schema())
    assert {item["label"] for item in nested_tail} == {"city"}
    assert nested_tail[0]["insert_text"] == "city"


def test_document_metadata_signature_keeps_case_and_ignores_literals():
    assert metadata_signature("SELECT * FROM Events", "mongodb") != metadata_signature("SELECT * FROM events", "mongodb")
    assert metadata_signature("SELECT * FROM Events WHERE text='FROM ignored'", "mongodb") == metadata_signature("SELECT * FROM Events", "mongodb")


def test_mongo_validation_understands_subset_and_is_not_tsql():
    code = 'SELECT e.address.city AS city FROM "Events" e WHERE e.age > @age LIMIT 10'
    result = diagnose({"code": code, "language": "sql", "db_type": "mongodb", "locale": "pt-BR"},
                      {"schema": schema(), "schema_complete": True})
    assert result["status"] == "complete" and result["markers"] == []
    invalid = diagnose({"code": "SELECT COUNT(*) FROM Events", "language": "sql", "db_type": "mongodb", "locale": "pt-BR"})
    assert invalid["markers"] and "Use SELECT" in invalid["markers"][0]["message"]


def test_cosmos_native_json_syntax_is_marked_partial_without_false_errors():
    result = diagnose({"code": 'SELECT VALUE {"name": c.name, "tags": c.tags} FROM c WHERE c["status"] = "active"',
                       "language": "sql", "db_type": "cosmosdb", "locale": "pt-BR"})
    assert result["status"] == "partial" and result["markers"] == []
    invalid = diagnose({"code": "SELECT * FROM c WHERE (c.id = 'x'", "language": "sql", "db_type": "cosmosdb"})
    assert invalid["markers"]


def test_cosmos_mongo_uses_the_selected_api_dialect():
    result = diagnose({"code": "SELECT * FROM events JOIN other ON events.id=other.id", "language": "sql", "db_type": "cosmosdb"},
                      {"schema": schema("cosmosdb", capabilities={"sql_dialect": "mongodb"})})
    assert result["markers"] and result["status"] == "complete"


def test_inferred_schema_does_not_report_unseen_fields_as_nonexistent():
    result = diagnose({"code": "SELECT not_in_sample FROM events", "language": "sql", "db_type": "mongodb"},
                      {"schema_complete": True, "schema": schema()})
    assert result["markers"] == []
