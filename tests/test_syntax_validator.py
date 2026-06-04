from src.services.syntax_validator import (
    validate_code,
    validate_python,
    validate_sql,
)


def test_validate_python_ok():
    assert validate_python("x = 1\n") == []


def test_validate_python_syntax_error_line():
    markers = validate_python("def foo(\n")
    assert len(markers) == 1
    assert markers[0].start_line >= 1
    assert "SyntaxError" in markers[0].message


def test_validate_sql_ok():
    markers = validate_sql("SELECT 1", db_type="mssql")
    assert markers == []


def test_validate_sql_bad_syntax():
    markers = validate_sql("SELECT FROM", db_type="mssql")
    assert len(markers) >= 1


def test_validate_sql_go_batches():
    sql = "SELECT 1\nGO\nSELECT FROM\n"
    markers = validate_sql(sql, db_type="mssql")
    assert len(markers) >= 1
    assert any(m.start_line >= 3 for m in markers)


def test_validate_code_skips_cross():
    assert validate_code("cross", "{{ x }}") == []
