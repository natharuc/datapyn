from src.services.syntax_validator import (
    LARGE_SQL_LINE_LIMIT,
    MAX_SQL_STATEMENTS_TO_VALIDATE,
    is_large_sql_document,
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


def test_validate_python_undefined_name():
    markers = validate_python("print(block1)\n", namespace={"other": 1})
    assert len(markers) == 1
    assert "block1" in markers[0].message


def test_validate_python_known_namespace_name():
    markers = validate_python("print(block1)\n", namespace={"block1": []})
    assert markers == []


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


def test_validate_sql_without_schema_skips_column_check():
    markers = validate_sql("SELECT nope FROM dbo.users", db_type="mssql")
    assert not any("unknown column" in m.message.lower() for m in markers)


def test_is_large_sql_document_by_lines():
    # LARGE_SQL_LINE_LIMIT lines => count("\n")+1 >= limit
    big = "SELECT 1;\n" * LARGE_SQL_LINE_LIMIT
    assert is_large_sql_document(big)


def test_validate_sql_large_script_skips_fast():
    # Synthetic script matching the freeze pattern (many IF NOT EXISTS blocks).
    block = (
        "IF NOT EXISTS (SELECT 1 FROM TABUABIOMETRICA WHERE TABUAID = {i})\n"
        "BEGIN\n"
        "    INSERT INTO TABUABIOMETRICA (TABUAID) VALUES ({i});\n"
        "END\n"
    )
    # Build well over the line limit so validation is skipped entirely.
    sql = "".join(block.format(i=i) for i in range(LARGE_SQL_LINE_LIMIT // 2 + 100))
    assert is_large_sql_document(sql)

    import time

    t0 = time.perf_counter()
    markers = validate_sql(sql, db_type="mssql")
    elapsed = time.perf_counter() - t0

    assert len(markers) == 1
    assert "skipped for large script" in markers[0].message.lower()
    assert markers[0].severity == "warning"
    # Must return immediately — full sqlglot parse of this script freezes the app.
    assert elapsed < 1.0


def test_validate_sql_medium_script_does_not_run_schema_walk():
    """Schema validation is O(n²); medium scripts must skip it even under line limit."""
    # Under LARGE_SQL_LINE_LIMIT but well over the 500-line schema gate.
    sql = "\n".join(f"SELECT {i};" for i in range(600))
    assert not is_large_sql_document(sql)

    schema = {
        "db_type": "mssql",
        "tables": ["users"],
        "columns": {"users": [{"name": "id"}]},
    }
    import time

    t0 = time.perf_counter()
    markers = validate_sql(sql, db_type="mssql", schema=schema)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0
    # No schema markers expected — walk skipped; SELECTs are valid.
    assert markers == []


def test_get_completions_large_script_is_fast():
    from src.services.sql_autocomplete_service import SqlAutoCompleteService

    block = (
        "IF NOT EXISTS (SELECT 1 FROM T WHERE ID = {i})\n"
        "BEGIN\n"
        "    INSERT INTO T (ID) VALUES ({i});\n"
        "END\n"
    )
    sql = "".join(block.format(i=i) for i in range(LARGE_SQL_LINE_LIMIT // 2 + 50))
    assert is_large_sql_document(sql)

    import time

    service = SqlAutoCompleteService()
    lines = sql.split("\n")
    t0 = time.perf_counter()
    completions = service.get_completions(sql, len(lines) - 1, len(lines[-1]))
    elapsed = time.perf_counter() - t0
    assert isinstance(completions, list)
    assert elapsed < 1.0


def test_validate_sql_caps_statement_count():
    """Under the line limit but with many statements: only parse a capped amount."""
    # Keep well under LARGE_SQL_LINE_LIMIT while exceeding MAX_SQL_STATEMENTS_TO_VALIDATE.
    n = MAX_SQL_STATEMENTS_TO_VALIDATE + 50
    sql = "\n".join(f"SELECT {i};" for i in range(n))
    assert not is_large_sql_document(sql)

    markers = validate_sql(sql, db_type="mssql")

    # All statements are valid SELECT — no error markers expected.
    assert markers == []


def test_validate_sql_silences_sqlglot_warnings(caplog):
    """T-SQL IF/BEGIN often triggers sqlglot WARNINGs; validation must not flood logs."""
    block = (
        "IF NOT EXISTS (SELECT 1 FROM T WHERE ID = {i})\n"
        "BEGIN\n"
        "    INSERT INTO T (ID) VALUES ({i});\n"
        "END\n"
    )
    # Enough to exercise sqlglot fallback, far under the large-doc skip.
    sql = "".join(block.format(i=i) for i in range(20))
    assert not is_large_sql_document(sql)

    import logging

    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        validate_sql(sql, db_type="mssql")

    assert not any(r.name == "sqlglot" and r.levelno == logging.WARNING for r in caplog.records)


def test_validate_sql_small_script_still_reports_errors():
    markers = validate_sql("SELECT FROM", db_type="mssql")
    assert len(markers) >= 1
    assert not any("skipped for large script" in m.message.lower() for m in markers)
