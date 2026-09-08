"""Tests for async Monaco static completion payload building."""

from src.editors.monaco.monaco_sql_completions import (
    build_python_completions,
    build_sql_completions,
    quote_sql_completion_insert,
)


def test_build_sql_completions_includes_tables_columns_and_keywords():
    schema = {
        "tables": [{"name": "vendas", "schema": "dbo", "type": "TABLE"}],
        "columns": {"vendas": [{"name": "id", "type": "int"}]},
    }
    completions = build_sql_completions(schema)
    labels = {item["label"] for item in completions}
    assert "vendas" in labels
    assert "id" in labels
    assert "SELECT" in labels
    column = next(item for item in completions if item["label"] == "id")
    assert column["kind"] == "field"
    assert "int" in column["detail"]
    assert column["category"] == "column"
    assert column["insertText"] == "id"
    table = next(item for item in completions if item["label"] == "vendas")
    assert table["kind"] == "class"
    assert table["category"] == "table"
    assert table["insertText"] == "vendas"


def test_build_sql_completions_quotes_postgresql_identifiers():
    schema = {
        "db_type": "postgresql",
        "tables": [{"name": "PullRequests", "schema": "metrics", "type": "TABLE"}],
        "columns": {"metrics.PullRequests": [{"name": "Id", "type": "int"}]},
    }
    completions = build_sql_completions(schema)
    table = next(item for item in completions if item["label"] == "PullRequests")
    assert table["insertText"] == '"PullRequests"'
    assert table["filterText"] == "PullRequests"
    column = next(item for item in completions if item["label"] == "Id")
    assert column["insertText"] == '"Id"'
    keyword = next(item for item in completions if item["label"] == "SELECT")
    assert keyword["insertText"] == "SELECT"


def test_quote_sql_completion_insert_postgresql_parts():
    assert quote_sql_completion_insert("PullRequests", "postgresql", "table") == '"PullRequests"'
    assert quote_sql_completion_insert("metrics.PullRequests", "postgres", "table") == (
        '"metrics"."PullRequests"'
    )
    assert quote_sql_completion_insert("Id", "postgresql", "column") == '"Id"'
    assert quote_sql_completion_insert("metrics", "postgresql", "schema") == '"metrics"'
    assert quote_sql_completion_insert("SELECT", "postgresql", "keyword") == "SELECT"
    assert quote_sql_completion_insert("PullRequests", "sqlserver", "table") == "PullRequests"


def test_build_python_completions_includes_namespace_and_keywords():
    completions = build_python_completions({"df": object(), "_hidden": 1})
    labels = {item["label"] for item in completions}
    assert "df" in labels
    assert "_hidden" not in labels
    assert "def" in labels
    assert "pd" in labels


def test_build_python_completions_includes_session_connection_variables():
    completions = build_python_completions(
        {
            "block1": object(),
            "db_username": "root",
            "db_host": "localhost",
        }
    )
    labels = {item["label"] for item in completions}
    assert "block1" in labels
    assert "db_username" in labels
    assert "db_host" in labels
