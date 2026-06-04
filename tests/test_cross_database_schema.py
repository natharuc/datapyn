"""Tests for cross-database SQL schema helpers."""

import pytest

from source.src.services.cross_database_schema import (
    extract_referenced_catalogs,
    extract_referenced_table_refs,
    prepare_editor_sql_schema,
)
from source.src.services.sql_autocomplete_service import SqlAutoCompleteService
from source.src.services.sql_schema_validator import validate_sql_schema


def test_extract_referenced_catalogs_from_double_dot():
    sql = "SELECT * FROM premio JOIN esim..pessoa p ON 1 = 1"
    refs = extract_referenced_catalogs(sql, current_database="Provisao", db_type="mssql")
    assert "esim" in {name.lower() for name in refs}


def test_prepare_editor_sql_schema_includes_referenced_database():
    schema = {
        "database": "Provisao",
        "db_type": "mssql",
        "tables": [
            {"name": "Premio", "schema": "dbo", "key": "dbo.Premio"},
            {"name": "Pessoa", "schema": "dbo", "database": "ESIM", "key": "ESIM.dbo.Pessoa"},
        ],
        "columns": {
            "dbo.Premio": [{"name": "Id", "type": "int"}],
            "ESIM.dbo.Pessoa": [{"name": "Nome", "type": "varchar"}],
        },
    }
    prepared = prepare_editor_sql_schema(
        schema,
        db_type="mssql",
        referenced_catalogs={"ESIM"},
    )
    table_names = {table["name"] for table in prepared["tables"]}
    assert "Premio" in table_names
    assert "Pessoa" in table_names
    assert "ESIM.dbo.Pessoa" in prepared["columns"]


def test_autocomplete_resolves_esim_double_dot_table():
    schema = {
        "database": "Provisao",
        "db_type": "mssql",
        "tables": [
            {
                "name": "Pessoa",
                "schema": "dbo",
                "database": "ESIM",
                "key": "ESIM.dbo.Pessoa",
            },
        ],
        "columns": {
            "ESIM.dbo.Pessoa": [
                {"name": "IdPessoa", "type": "int"},
                {"name": "Nome", "type": "varchar"},
            ],
        },
    }
    service = SqlAutoCompleteService()
    service.set_schema({**schema, "db_type": "mssql"})

    sql = "SELECT esim..pessoa."
    completions = service.get_completions(sql, 0, len(sql))
    labels = {item[0] for item in completions}
    assert "IdPessoa" in labels
    assert "Nome" in labels


def test_table_completions_after_esim_double_dot_prefix():
    schema = {
        "database": "Provisao",
        "db_type": "mssql",
        "tables": [
            {"name": "Premio", "schema": "dbo", "key": "dbo.Premio"},
            {
                "name": "AnaliticoPMBAC",
                "schema": "dbo",
                "database": "ESIM",
                "key": "ESIM.dbo.AnaliticoPMBAC",
            },
        ],
        "columns": {},
    }
    service = SqlAutoCompleteService()
    service.set_schema({**schema, "db_type": "mssql"})

    sql = "select * from esim..ana"
    completions = service.get_completions(sql, 0, len(sql))
    labels = {item[0] for item in completions}
    assert "AnaliticoPMBAC" in labels
    assert "Premio" not in labels


def test_validator_accepts_cross_database_column():
    schema = {
        "database": "Provisao",
        "db_type": "mssql",
        "tables": [
            {
                "name": "AnaliticoPMBAC",
                "schema": "dbo",
                "database": "ESIM",
                "key": "ESIM.dbo.AnaliticoPMBAC",
            },
        ],
        "columns": {
            "ESIM.dbo.AnaliticoPMBAC": [{"name": "COMPETENCIA", "type": "int"}],
        },
    }
    sql = "SELECT COMPETENCIA FROM ESIM..AnaliticoPMBAC WHERE COMPETENCIA = 202401"
    markers = validate_sql_schema(sql, schema)
    assert not any("COMPETENCIA" in marker.message for marker in markers)
