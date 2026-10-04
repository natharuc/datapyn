"""Cached SQL metadata warnings reuse the syntax AST without another parse."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from datapyn_runtime.language import dispatch
from datapyn_runtime import sql_schema_diagnostics as metadata


def schema():
    return {"db_type": "mssql", "tables": [{"name": "users", "schema": "dbo"}, {"name": "orders", "schema": "dbo"}],
            "columns": {"dbo.users": [{"name": "id"}, {"name": "email"}],
                        "dbo.orders": [{"name": "id"}, {"name": "user_id"}]}}


def check(code, cached=None, *, complete=True, locale="en-US", version=1):
    return dispatch("language.diagnostics", {"language": "sql", "code": code, "locale": locale},
                    {"schema": cached if cached is not None else schema(), "schema_complete": complete, "version": version})


@pytest.mark.parametrize("code, message", [
    ("SELECT bad FROM dbo.users", "Unknown column 'bad'"),
    ("SELECT u.bad FROM dbo.users u", "Unknown column 'u.bad'"),
    ("SELECT z.id FROM dbo.users u", "Unknown table or alias 'z'"),
    ("SELECT id FROM dbo.missing", "Unknown table 'dbo.missing'"),
    ("UPDATE dbo.users SET bad=1 WHERE id=2", "Unknown column 'bad'"),
    ("DELETE FROM dbo.users WHERE bad=1", "Unknown column 'bad'"),
])
def test_cached_complete_schema_keeps_table_column_alias_warnings(code, message):
    result = check(code)
    assert result["status"] == "complete"
    assert [item["message"] for item in result["markers"]] == [message]
    assert result["markers"][0]["severity"] == "warning"


@pytest.mark.parametrize("code", [
    "SELECT u.email FROM dbo.users u WHERE u.id=1",
    "WITH c AS (SELECT id FROM dbo.users) SELECT id FROM c",
    "WITH c(other) AS (SELECT id FROM dbo.users) SELECT other FROM c",
    "SELECT s.id FROM (SELECT id FROM dbo.users) s",
    "SELECT id AS other FROM dbo.users ORDER BY other",
    "SELECT u.id FROM dbo.users u WHERE EXISTS (SELECT 1 FROM dbo.orders o WHERE o.user_id=u.id)",
    "CREATE TABLE #t(id int); SELECT id FROM #t",
    "SELECT id INTO #t FROM dbo.users; SELECT id FROM #t",
    "DECLARE @t TABLE (id int); SELECT id FROM @t",
    "UPDATE dbo.users SET email='x' WHERE id=2",
])
def test_aliases_cte_subqueries_correlations_and_temporary_relations_are_valid(code):
    result = check(code)
    assert result["status"] == "complete"
    assert result["markers"] == []


@pytest.mark.parametrize("code, message", [
    ("WITH c AS (SELECT id FROM dbo.users) SELECT bad FROM c", "Unknown column 'bad'"),
    ("SELECT s.bad FROM (SELECT id FROM dbo.users) s", "Unknown column 's.bad'"),
    ("CREATE TABLE #t(id int); SELECT bad FROM #t", "Unknown column 'bad'"),
])
def test_derived_relations_keep_unknown_column_warnings(code, message):
    assert message in [item["message"] for item in check(code)["markers"]]


def test_partial_and_unloaded_schema_never_create_false_name_warnings():
    assert check("SELECT bad FROM dbo.missing", complete=False)["markers"] == []
    cached = schema()
    cached["columns"] = {"dbo.orders": cached["columns"]["dbo.orders"]}
    assert check("SELECT u.bad FROM dbo.users u", cached)["markers"] == []
    assert check("WITH c AS (SELECT * FROM dbo.users) SELECT bad FROM c", cached)["markers"] == []


def test_schema_positions_are_original_utf16_and_messages_localized():
    result = check("SELECT '😀', u.bad FROM dbo.users u", locale="pt-BR")
    marker = result["markers"][0]
    assert (marker["start_column"], marker["end_column"]) == (16, 19)
    assert marker["message"] == "Coluna não encontrada nos metadados carregados: u.bad"
    result = check("SELECT wrong.id FROM dbo.users u")
    assert (result["markers"][0]["start_column"], result["markers"][0]["end_column"]) == (8, 13)


def test_metadata_uses_existing_ast_without_extra_parsing_or_database(monkeypatch):
    import sqlglot
    from sqlglot.parser import Parser
    from datapyn_runtime.sql_completion import RuntimeSqlAutoCompleteService
    calls = []
    original = Parser.parse
    def parse(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata validation must reuse the parsed AST")
    monkeypatch.setattr(Parser, "parse", parse)
    monkeypatch.setattr(sqlglot, "parse", forbidden)
    monkeypatch.setattr(sqlglot, "parse_one", forbidden)
    monkeypatch.setattr(RuntimeSqlAutoCompleteService, "_parse_statement", forbidden)
    monkeypatch.setattr(RuntimeSqlAutoCompleteService, "_collect_script_state", forbidden)
    result = check("SELECT u.bad FROM dbo.users u")
    assert result["markers"][0]["message"] == "Unknown column 'u.bad'"
    assert calls == [1]


def test_content_and_version_index_invalidate_in_place_mutation_and_are_bounded():
    cached = schema()
    assert check("SELECT new_column FROM dbo.users", cached)["markers"]
    cached["columns"]["dbo.users"].append({"name": "new_column"})
    assert check("SELECT new_column FROM dbo.users", cached)["markers"] == []
    for version in range(8):
        assert check("SELECT id FROM dbo.users", cached, version=version)["markers"] == []
    assert len(metadata._INDEXES) <= 4
    assert metadata._INDEX_BYTES <= metadata.MAX_SCHEMA_CACHE_BYTES


def test_metadata_limits_do_not_silence_real_syntax_errors(monkeypatch):
    monkeypatch.setattr(metadata, "MAX_SCHEMA_ITEMS", 0)
    result = check("SELECT FROM", locale="pt-BR")
    assert result["status"] == "partial"
    assert result["markers"][0]["severity"] == "error"
    assert "esperado um nome" in result["markers"][0]["message"]
