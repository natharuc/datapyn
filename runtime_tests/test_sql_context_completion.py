"""SQL editor regressions reproduced through the shipped Qt-free adapter."""

import pytest

from datapyn_runtime.language import dispatch
from datapyn_runtime.sql_context import metadata_signature, sql_statement_boundaries


def items(marked, db_type="sqlite"):
    offset = marked.index("|")
    code = marked.replace("|", "")
    before = code[:offset]
    schema = {"db_type": db_type, "database": "db", "current_schema": "main", "schemas": ["main"],
              "tables": [{"name": "sales", "schema": "main"}, {"name": "customers", "schema": "main"}],
              "columns": {"main.sales": [{"name": "value"}, {"name": 'value"quoted'}], "main.customers": [{"name": "customer_name"}]}}
    return dispatch("language.complete", {"language": "sql", "code": code, "line": before.count("\n") + 1,
                                        "column": len(before.split("\n")[-1].encode("utf-16-le")) // 2 + 1}, {"schema": schema})["items"]


@pytest.mark.parametrize("db_type", ["sqlite", "sqlserver", "postgresql", "mysql", "databricks"])
@pytest.mark.parametrize("marked", [
    "SELECT s . | FROM main.sales s JOIN main.customers c ON 1=1",
    'SELECT "s".| FROM main.sales "s" JOIN main.customers c ON 1=1',
    'SELECT "Σ".| FROM main.sales "Σ"',
    "SELECT s.| /* ; JOIN fake */ FROM main.sales s",
    "SELECT s.| FROM main.sales s WHERE value = 'a;b'",
    "SELECT (SELECT s.| FROM main.sales s) FROM main.customers s",
    "SELECT s.| FROM main.sales s; SELECT s.value FROM main.customers s",
])
def test_ordinary_alias_columns_remain_correct_across_dialects(db_type, marked):
    assert {item["label"] for item in items(marked, db_type)} == {"value", 'value"quoted'}


@pytest.mark.parametrize("db_type,quote,close", [("sqlserver", "[", "]"), ("sqlite", '"', '"'), ("postgresql", '"', '"'), ("mysql", "`", "`"), ("databricks", "`", "`")])
def test_partial_quoted_field_with_join_only_returns_its_alias_columns(db_type, quote, close):
    for suffix in ("", "lue" + close):
        marked = f"SELECT s.{quote}va|{suffix} FROM main.sales s JOIN main.customers c ON 1=1"
        assert {item["label"] for item in items(marked, db_type)} == {"value", 'value"quoted'}


@pytest.mark.parametrize("db_type,alias", [("sqlserver", "[a]]b]"), ("postgresql", '"a""b"'), ("mysql", "`a``b`")])
def test_escaped_quoted_aliases_resolve_their_exact_binding(db_type, alias):
    assert {item["label"] for item in items(f"SELECT {alias}.| FROM main.sales {alias}", db_type)} == {"value", 'value"quoted'}


@pytest.mark.parametrize("db_type", ["sqlite", "postgresql", "mysql", "sqlserver", "databricks"])
def test_alias_wins_over_schema_namespace(db_type):
    assert {item["label"] for item in items("SELECT main.| FROM main.sales main", db_type)} == {"value", 'value"quoted'}


@pytest.mark.parametrize("prefix,expected", [('"A"', {"value", 'value"quoted'}), ("a", {"customer_name"}), ("A", {"customer_name"}), ('"a"', {"customer_name"})])
def test_postgresql_quoted_alias_case_remains_distinct(prefix, expected):
    assert {item["label"] for item in items(f'SELECT {prefix}.| FROM main.sales "A" JOIN main.customers a ON TRUE', "postgresql")} == expected


@pytest.mark.parametrize("marked", ["SELECT 's.va|", "SELECT s.value -- s.va|", "SELECT s.value -- s.va|\nFROM main.sales s", "SELECT /* nested /* ; */ s.va|", "SELECT $$s.va|$$ FROM main.sales s"])
def test_literals_and_comments_never_infer_code(marked):
    assert items(marked, "postgresql") == []


def test_semicolons_and_go_inside_names_literals_comments_do_not_split_statements():
    code = "SELECT [a;b], 'c;d', $$e;f$$ /* ; */;\nSELECT 2\nGO\nSELECT 'GO' -- ;\n"
    boundaries = sql_statement_boundaries(code, "postgresql")
    assert boundaries == [(code.index(";\n"), code.index(";\n") + 1)]
    tsql = "SELECT 'GO' -- ;\nGO -- batch\nSELECT [a;b];"
    assert len(sql_statement_boundaries(tsql, "sqlserver")) == 2


def test_metadata_references_survive_comment_markers_inside_literals():
    before = metadata_signature("SELECT '-- FROM fake' AS marker FROM reporting.sales s WHERE s.value='/* JOIN fake */'")
    assert before == metadata_signature("SELECT 1 AS marker FROM reporting.sales s WHERE s.value=1")


@pytest.mark.parametrize("literal", ["'C:\\'", "E'a\\'b'", "e'line\\\\path'"])
def test_postgresql_regular_strings_and_explicit_escape_strings_keep_following_query_visible(literal):
    assert {item["label"] for item in items(f"SELECT {literal} AS marker, s.| FROM main.sales s", "postgresql")} == {"value", 'value"quoted'}


def test_postgresql_escape_string_remains_a_literal_at_the_cursor():
    assert items("SELECT E'a\\'s.va| FROM main.sales s", "postgresql") == []


@pytest.mark.parametrize("db_type", ["mysql", "mariadb"])
def test_mysql_backslash_escape_strings_keep_following_query_visible(db_type):
    assert {item["label"] for item in items("SELECT 'a\\'b' AS marker, s.| FROM main.sales s", db_type)} == {"value", 'value"quoted'}
