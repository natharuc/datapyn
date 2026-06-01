"""Tests for async Monaco static completion payload building."""

from src.editors.monaco.monaco_sql_completions import build_python_completions, build_sql_completions


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


def test_build_python_completions_includes_namespace_and_keywords():
    completions = build_python_completions({"df": object(), "_hidden": 1})
    labels = {item["label"] for item in completions}
    assert "df" in labels
    assert "_hidden" not in labels
    assert "def" in labels
    assert "pd" in labels
