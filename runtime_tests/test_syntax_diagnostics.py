"""Static editor diagnostics: real parsers, no execution or database access."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from datapyn_runtime.language import dispatch
from datapyn_runtime import syntax_diagnostics as syntax


def check(code, language="python", **params):
    return dispatch("language.diagnostics", {"code": code, "language": language, **params})


@pytest.mark.parametrize("code", [
    "x = 1\nprint(x)",
    "def f(value):\n    return value + 1\nf(2)",
    "def f(x):\n    def nested(y):\n        return x+y\n    return nested(1)",
    "[value*2 for value in range(5)]",
    "{value:value*2 for value in range(5)}",
    "(value*2 for value in range(5))",
    "[x+y for x in range(5) for y in range(x)]",
    "(lambda value: value*2)(1)",
    "try:\n    1/0\nexcept Exception as error:\n    print(error)",
    "match 1:\n    case value:\n        print(value)",
])
def test_valid_python_scopes_have_no_false_name_errors(code):
    result = check(code)
    assert result["status"] == "complete"
    assert result["markers"] == []
    assert result["duration_ms"] >= 0


@pytest.mark.parametrize("code", ["def f(x)\n return x", "return 1", "break", "continue", "await f()"])
def test_python_parser_and_compiler_scope_errors_are_errors(code):
    result = check(code, locale="pt-BR")
    assert result["status"] == "complete"
    assert result["markers"][0]["severity"] == "error"
    assert result["markers"][0]["message"].startswith("Python:")


def test_python_syntax_and_scope_errors_are_located_in_utf16():
    result = check("x = '😀'; return 1", locale="pt-BR")
    assert result["markers"][0]["start_column"] == 11
    result = check("x = '😀'; missing")
    marker = result["markers"][0]
    assert (marker["start_column"], marker["end_column"]) == (11, 18)
    assert marker["message"] == "Undefined name: missing"
    assert marker["severity"] == "warning"
    result = check("x = '😀'; y =")
    assert result["markers"][0]["start_column"] == 14


def test_python_context_includes_peer_blocks_and_global_imports_without_execution(tmp_path):
    target = tmp_path / "executed.txt"
    result = check("print(peer, imported, session_value)",
                   preamble=f"peer = 3\nopen({str(target)!r}, 'w').write('unsafe')",
                   global_imports="import impossible_package_that_is_not_installed as imported")
    assert [marker["message"] for marker in result["markers"]] == ["Undefined name: session_value"]
    assert not target.exists()
    result = dispatch("language.diagnostics", {"language": "python", "code": "print(session_value)"},
                      {"variables": {"session_value": {"type": "int"}}})
    assert result["markers"] == []


def test_python_unknown_comprehension_names_warn_but_targets_do_not_leak():
    result = check("[missing+x for x in range(3)]\nx")
    assert [marker["message"] for marker in result["markers"]] == ["Undefined name: missing", "Undefined name: x"]
    assert all(marker["severity"] == "warning" for marker in result["markers"])


@pytest.mark.parametrize("delimiter, code", [
    ("{{name}}", "x = {{value}} + 1\nprint(x)"),
    ("::name::", "x = ::value:: + 1\nprint(x)"),
    ("{name}", "x = {value} + 1\nprint(x)"),
])
def test_python_parameters_preserve_syntax_and_positions(delimiter, code):
    assert check(code, shared_delimiter=delimiter)["markers"] == []
    result = check(code.splitlines()[0] + " + missing", shared_delimiter=delimiter)
    marker = result["markers"][0]
    assert marker["start_column"] == code.splitlines()[0].index("+") + 7


@pytest.mark.parametrize("db_type, code", [
    ("sqlite", "SELECT :value, @value, {{shared}}; SELECT 2 AS next;"),
    ("mssql", "SELECT TOP 10 [Name] FROM [dbo].[People] WHERE [id]=@value;"),
    ("postgresql", "SELECT data::jsonb ->> 'key' FROM public.events LIMIT 10;"),
    ("mysql", "SELECT `name` FROM `people` LIMIT 10;"),
    ("databricks", "SELECT * FROM catalog.schema.table QUALIFY ROW_NUMBER() OVER (ORDER BY id)=1;"),
])
def test_dialect_validation_does_not_require_database_schema(db_type, code):
    result = check(code, "sql", db_type=db_type)
    assert result["status"] == "complete"
    assert result["markers"] == []


def test_sql_preserves_indentation_multiple_statements_and_batch_line_numbers():
    result = check("SELECT 1;  SELECT FROM", "sql", locale="pt-BR")
    marker = result["markers"][0]
    assert (marker["start_line"], marker["start_column"], marker["end_column"]) == (1, 19, 23)
    assert marker["message"] == "SQL: esperado um nome de tabela após FROM/JOIN"
    result = check("SELECT 'GO\nline';\nGO -- separator\n\n   SELECT FROM", "sql")
    marker = result["markers"][0]
    assert (marker["start_line"], marker["start_column"]) == (5, 11)


def test_sql_unicode_ranges_and_lexical_errors_are_clear():
    result = check("SELECT '😀', FROM", "sql")
    marker = result["markers"][0]
    assert (marker["start_column"], marker["end_column"]) == (14, 18)
    assert "<Token" not in marker["message"]
    result = check("SELECT 'unterminated", "sql", locale="pt-BR")
    assert result["markers"][0]["start_column"] == 8
    assert "não fechado" in result["markers"][0]["message"]


@pytest.mark.parametrize("code, expected_column", [("SELECT", 1), ("SELECT FROM t", 1), ("SELECT 1; SELECT FROM t", 11)])
def test_empty_select_is_not_incorrectly_declared_valid(code, expected_column):
    result = check(code, "sql")
    assert result["markers"][0]["start_column"] == expected_column
    assert "requires a column" in result["markers"][0]["message"]


def test_go_inside_strings_identifiers_comments_is_not_a_separator():
    for code in ["SELECT 'hello\nGO\nworld';", 'SELECT "GO";', "SELECT 1 /*\nGO\n*/;", "-- GO\nSELECT 1;",
                 "SELECT 1 /* outer\n/* nested */\nGO\n*/;"]:
        result = check(code, "sql", db_type="mssql")
        assert result["status"] == "complete"
        assert result["markers"] == []


def test_sql_declares_unsupported_commands_as_partial_instead_of_false_error():
    result = check("BEGIN SELECT 1; SELECT 2; END\nGO\nSELECT FROM", "sql", db_type="mssql")
    assert result["status"] == "partial"
    assert "dialect" in result["message"]
    assert result["markers"][0]["start_line"] == 3


def test_python_null_bytes_are_located_and_named_clearly():
    result = check("x=1\x00\n", locale="pt-BR")
    assert result["markers"][0]["start_column"] == 4
    assert result["markers"][0]["message"] == "Python: o código contém um caractere nulo."


def test_limits_are_explicit_and_never_declared_valid():
    oversized = check("#" * (syntax.MAX_SYNTAX_BYTES + 1), locale="pt-BR")
    assert oversized["status"] == "partial" and "1 MiB" in oversized["message"]
    large_batch = check("--" + "x" * syntax.MAX_SQL_BATCH_CHARACTERS, "sql")
    assert large_batch["status"] == "partial" and "256 KiB" in large_batch["message"]
    many = check("SELECT 1;\n" * (syntax.MAX_SQL_STATEMENTS + 1), "sql")
    assert many["status"] == "partial" and "500" in many["message"]
    deep = check("SELECT " + "(" * 101 + "1" + ")" * 101, "sql")
    assert deep["status"] == "partial" and "100" in deep["message"]


def test_cancelled_and_exhausted_budget_return_partial(monkeypatch):
    result = dispatch("language.diagnostics", {"language": "python", "code": "x=1"}, should_abort=lambda: True)
    assert result["status"] == "partial" and result["markers"] == []
    monkeypatch.setattr(syntax, "SYNTAX_BUDGET_SECONDS", 0)
    result = check("SELECT FROM", "sql")
    assert result["status"] == "partial" and result["markers"] == []


def test_inactive_peer_syntax_does_not_prevent_current_block_syntax_validation():
    result = check("def f(x)\n return x", preamble="def malformed(", global_imports="import os", locale="pt-BR")
    assert result["status"] == "complete"
    assert result["markers"][0]["message"] == "Python: esperado ':' ao final da instrução"
    result = check("print(before, imported)", preamble="before=1\ndef incomplete():\n",
                   global_imports="import package_not_installed as imported")
    assert result["markers"] == []


def test_locale_en_us_keeps_english_messages_and_no_payloads_execute(tmp_path):
    target = tmp_path / "should-not-exist.txt"
    result = check(f"open({str(target)!r}, 'w').write('unsafe')", locale="en-US")
    assert result["status"] == "complete" and not target.exists()
    result = check("SELECT FROM", "sql", locale="en-US")
    assert "Expected table name" in result["markers"][0]["message"]
