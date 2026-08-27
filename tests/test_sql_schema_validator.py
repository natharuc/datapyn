from src.services.sql_schema_validator import validate_sql_schema
from src.services.syntax_validator import validate_sql


SAMPLE_SCHEMA = {
    "tables": [
        {"name": "users", "schema": "dbo", "type": "TABLE"},
        {"name": "orders", "schema": "dbo", "type": "TABLE"},
    ],
    "columns": {
        "dbo.users": [
            {"name": "id", "type": "int"},
            {"name": "email", "type": "varchar"},
        ],
        "dbo.orders": [
            {"name": "id", "type": "int"},
            {"name": "user_id", "type": "int"},
        ],
    },
}


def test_validate_sql_schema_unknown_column():
    sql = "SELECT bad_col FROM dbo.users"
    markers = validate_sql_schema(sql, SAMPLE_SCHEMA)
    assert markers
    assert any("bad_col" in m.message.lower() or "unknown column" in m.message.lower() for m in markers)


def test_validate_sql_schema_unknown_table():
    sql = "SELECT id FROM dbo.nope"
    markers = validate_sql_schema(sql, SAMPLE_SCHEMA)
    assert markers
    assert any("nope" in m.message.lower() for m in markers)


def test_validate_sql_schema_valid_query():
    sql = "SELECT u.email FROM dbo.users u WHERE u.id = 1"
    markers = validate_sql_schema(sql, SAMPLE_SCHEMA)
    assert markers == []


def test_validate_sql_includes_schema_markers():
    sql = "SELECT missing FROM dbo.users"
    markers = validate_sql(sql, db_type="mssql", schema=SAMPLE_SCHEMA)
    assert any("missing" in m.message.lower() for m in markers)


def test_validate_sql_schema_alias_before_from_not_false_positive():
    """Regression: cursor-at-end analysis used to replace trailing alias with placeholder."""
    schema = {
        "db_type": "mssql",
        "tables": [{"name": "Premio", "schema": "dbo"}],
        "columns": {
            "Premio": [{"name": "PremioId"}, {"name": "CoberturaId"}],
            "dbo.Premio": [{"name": "PremioId"}, {"name": "CoberturaId"}],
        },
    }
    sql = "SELECT top 100 p.PremioId FROM Premio p"
    markers = validate_sql_schema(sql, schema)
    assert markers == []


def test_validate_sql_schema_join_alias_in_scope():
    schema = {
        "db_type": "mssql",
        "tables": [
            {"name": "Premio", "schema": "dbo"},
            {"name": "Cobertura", "schema": "dbo"},
        ],
        "columns": {
            "Premio": [{"name": "PremioId"}, {"name": "CoberturaId"}],
            "dbo.Premio": [{"name": "PremioId"}, {"name": "CoberturaId"}],
            "Cobertura": [{"name": "Id"}, {"name": "CoberturaId"}],
            "dbo.Cobertura": [{"name": "Id"}, {"name": "CoberturaId"}],
        },
    }
    sql = (
        "SELECT top 100 * FROM Premio p\n"
        "INNER JOIN Cobertura c ON c.CoberturaId = p.CoberturaId"
    )
    markers = validate_sql_schema(sql, schema)
    assert markers == []


def test_validate_sql_schema_unknown_column_underlines_token_not_select():
    schema = {
        "db_type": "mssql",
        "tables": [
            {"name": "Premio", "schema": "dbo"},
            {"name": "Cobertura", "schema": "dbo"},
        ],
        "columns": {
            "dbo.Premio": [
                {"name": "PremioId", "type": "int"},
                {"name": "CoberturaId", "type": "uniqueidentifier"},
            ],
            "dbo.Cobertura": [
                {"name": "Id", "type": "int"},
                {"name": "Nome", "type": "varchar"},
            ],
        },
    }
    sql = (
        "SELECT top 100 * FROM Premio p\n"
        "JOIN Cobertura c on c.Cobertu = p.CoberturaId"
    )
    markers = validate_sql_schema(sql, schema)
    unknown = [m for m in markers if "c.Cobertu" in m.message or "Cobertu" in m.message]
    assert unknown, markers
    marker = unknown[0]
    assert marker.start_line == 2
    assert marker.start_column > 1
    assert "Cobertu" in sql.splitlines()[marker.start_line - 1][
        marker.start_column - 1 : marker.end_column - 1
    ]


def test_find_identifier_span_prefers_last_match():
    from src.services.sql_schema_validator import _find_identifier_span

    sql = "SELECT a.id FROM t a WHERE a.id = 1 AND a.bad = 2"
    span = _find_identifier_span(sql, "bad", "a")
    assert span is not None
    line, col, end_col = span
    assert line == 1
    snippet = sql[col - 1 : end_col - 1]
    assert "a.bad" in snippet.lower() or snippet.lower().endswith("bad")
