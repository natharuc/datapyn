"""Editor parity and bounded snapshots, without Qt or a live database."""

import math
import threading
import time
from types import SimpleNamespace

import pandas as pd
import polars as pl
import pytest

from datapyn_runtime import language
from datapyn_runtime.background import BackgroundJobs
from datapyn_runtime.language import dispatch, namespace_snapshot
from datapyn_runtime.sql_context import metadata_signature


def complete(code, *, context=None, line=1, column=None, **params):
    if column is None:
        column = len(code.split("\n")[line - 1].encode("utf-16-le")) // 2 + 1
    return dispatch("language.complete", {"language": "python", "code": code, "line": line, "column": column, **params}, context)["items"]


def labels(items):
    return {item["label"] for item in items}


def test_global_imports_and_previous_blocks_are_used_without_execution():
    assert "date" in labels(complete("dt.", global_imports="import datetime as dt"))
    assert "calculate_value" in labels(complete("calcul", preamble="def calculate_value(value):\n    raise AssertionError('never execute')"))
    assert "sqrt" in labels(complete("calculation.", preamble="import math as calculation"))
    assert "date" in labels(complete("dt.", global_imports="import datetime as dt", preamble="unclosed = '''unterminated peer"))
    assert "date" in labels(complete("dt.", global_imports="import datetime as dt", preamble="def incomplete(:"))


def test_imported_aliases_and_opaque_namespace_variables_survive_snapshot():
    snapshot = namespace_snapshot({"calculation": math, "root": math.sqrt, "opaque": object()})
    assert snapshot["calculation"]["module"] == "math"
    assert snapshot["root"]["qualname"] == "sqrt"
    assert "sqrt" in labels(complete("calculation.", context={"variables": snapshot}))
    assert "root" in labels(complete("roo", context={"variables": snapshot}))
    assert "opaque" in labels(complete("opa", context={"variables": snapshot}))


def test_snapshot_never_inspects_spoofed_dataframe_or_stringifies_custom_columns():
    class DataFrame:
        __module__ = "pandas.core.frame"
        @property
        def columns(self):
            raise AssertionError("User properties must never run")
    class Column:
        def __str__(self):
            raise AssertionError("User stringification must never run")
    snapshot = namespace_snapshot({"spoof": DataFrame(), "real": pd.DataFrame([[1]], columns=[Column()])})
    assert snapshot["spoof"] == {"type": "DataFrame"}
    assert snapshot["real"]["columns"] == []


def test_wide_dataframe_columns_beyond_old_hundred_column_cutoff_complete():
    frame = pd.DataFrame(columns=[f"field{index}" for index in range(250)])
    snapshot = namespace_snapshot({"frame": frame})
    assert "field249" in labels(complete("frame['field249", context={"variables": snapshot}))


def test_pandas_and_polars_keep_their_actual_methods_and_columns():
    snapshot = namespace_snapshot({"pd_frame": pd.DataFrame({"sample": [1], "sales total": [2]}), "pl_frame": pl.DataFrame({"sample": [1]})})
    pandas = labels(complete("pd_frame.", context={"variables": snapshot}))
    polars = labels(complete("pl_frame.", context={"variables": snapshot}))
    assert {"query", "sample"} <= pandas
    assert "sales total" not in pandas
    assert {"with_columns", "sample"} <= polars
    assert "query" not in polars


def test_polars_columns_complete_only_in_brackets_while_pandas_supports_attributes():
    snapshot = namespace_snapshot({
        "pandas_frame": pd.DataFrame({"sales_total": [7], "sales total": [8]}),
        "polars_frame": pl.DataFrame({"sales_total": [7], "sales total": [8]}),
    })
    context = {"variables": snapshot}
    assert "sales_total" in labels(complete("pandas_frame.sales", context=context))
    assert "sales_total" not in labels(complete("polars_frame.sales", context=context))
    assert {"sales_total", "sales total"} == labels(complete('polars_frame["', context=context))
    assert "head" in labels(complete("polars_frame.he", context=context))
    assert "with_columns" in labels(complete("polars_frame.with_c", context=context))


def test_pandas_class_members_win_column_collisions_in_attributes_only():
    snapshot = namespace_snapshot({"frame": pd.DataFrame({"head": [1], "query": [2], "columns": [3], "sales_total": [4]})})
    context = {"variables": snapshot}
    for name in ("head", "query", "columns"):
        items = [item for item in complete("frame." + name, context=context) if item["label"] == name]
        assert items and all(item["kind"] != "field" for item in items)
    assert {"head", "query", "columns", "sales_total"} == labels(complete('frame["', context=context))
    assert next(item for item in complete("frame.sales", context=context) if item["label"] == "sales_total")["kind"] == "field"


def test_dataframe_bracket_completion_escapes_quotes_and_replaces_entire_value(monkeypatch):
    snapshot = {"frame": {"type": "DataFrame", "columns": ["sales total", "sales'quoted", "sales\\path"]}}
    # Namespace string keys should not invoke slow dataframe static inference.
    import jedi
    monkeypatch.setattr(jedi, "Script", lambda *args, **kwargs: pytest.fail("Dataframe string-key completion invoked Jedi"))
    items = complete("frame['sa old']", column=10, context={"variables": snapshot})
    assert labels(items) == {"sales total", "sales'quoted", "sales\\path"}
    assert all(item["start_column"] == 8 and item["end_column"] == 14 for item in items)
    assert next(item for item in items if item["label"] == "sales'quoted")["insert_text"] == "sales\\'quoted"
    assert complete("frame['absent", context={"variables": snapshot}) == []
    assert complete("deleted_frame['", context={"variables": snapshot}) == []


@pytest.mark.parametrize("name", ["ação", "Δados", "数据", "a\u0301", "℘"])
def test_unicode_dataframe_names_use_snapshot_columns_without_path_inference(name, monkeypatch):
    snapshot = namespace_snapshot({name: pd.DataFrame({"amount": [7]})})
    import jedi
    monkeypatch.setattr(jedi, "Script", lambda *args, **kwargs: pytest.fail("String-key completion invoked Jedi"))
    assert labels(complete(name + '["', context={"variables": snapshot})) == {"amount"}
    assert complete(name + '["unknown', context={"variables": snapshot}) == []


@pytest.mark.parametrize("db_type", ["databricks", "sqlserver"])
def test_foreign_catalog_schema_table_and_columns_load_lazily_without_use(db_type, monkeypatch):
    from datapyn_runtime.explorer import ObjectExplorer
    class Connector:
        connection_params = {"database": "current", "schema": "dbo"}
        queries = []
        def execute_query(self, query):
            self.queries.append(query)
            if query in {"SHOW CATALOGS", "SELECT name FROM sys.databases WHERE state_desc='ONLINE' ORDER BY name"}:
                return pd.DataFrame({"name": ["current", "other"]})
            if "sys.schemas" in query or "SHOW SCHEMAS" in query:
                return pd.DataFrame({"name": ["dbo"]})
            if "SHOW TABLES" in query:
                return pd.DataFrame({"tableName": ["sales"]})
            if "INFORMATION_SCHEMA.TABLES" in query:
                return pd.DataFrame({"name": ["sales"], "kind": ["BASE TABLE"]})
            if "SHOW COLUMNS" in query:
                return pd.DataFrame({"col_name": ["amount"]})
            if "INFORMATION_SCHEMA.COLUMNS" in query:
                return pd.DataFrame({"name": ["amount"], "type": ["INTEGER"]})
            raise AssertionError(query)
    connector = Connector()
    connector.db_type = db_type
    explorer = ObjectExplorer(connector)
    monkeypatch.setattr(explorer, "schemas", lambda database: ["dbo"])
    monkeypatch.setattr(explorer, "objects", lambda schema, category: [])
    namespace = explorer.completion_schema("SELECT * FROM other.")
    assert namespace["catalog_schemas"]["other"] == ["dbo"]
    assert not any("COLUMNS" in query or "SHOW TABLES" in query or "INFORMATION_SCHEMA.TABLES" in query for query in connector.queries)
    tables = explorer.completion_schema("SELECT * FROM other.dbo.")
    assert "other.dbo.sales" in {table["key"] for table in tables["tables"]}
    code = "SELECT s. FROM other.dbo.sales s"
    schema = explorer.completion_schema(code)
    items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})["items"]
    assert "amount" in labels(items)
    count = len(connector.queries)
    explorer.completion_schema(code)
    assert len(connector.queries) == count and not any(query.startswith("USE ") for query in connector.queries)


def test_metadata_ddl_recognition_ignores_comments_and_literals():
    from datapyn_runtime.sql_context import changes_metadata
    assert changes_metadata("CREATE TABLE sample(id INTEGER)")
    assert changes_metadata("CREATE OR REPLACE VIEW sample AS SELECT 1")
    assert not changes_metadata("SELECT 'CREATE TABLE sample' -- ALTER TABLE sample\n/* DROP TABLE sample */")


def test_utf16_cursor_after_astral_character_is_converted_for_jedi():
    assert "append" in labels(complete("emoji = '😀'; names.", context={"variables": {"names": {"type": "list"}}}))
    with pytest.raises(ValueError, match="boundary"):
        complete("'😀'", column=3)
    with pytest.raises(ValueError):
        complete("x", column=20)
    with pytest.raises(ValueError):
        complete("x", line=2, column=1)


def test_sql_quotes_postgres_identifiers_without_importing_qt():
    schema = {"db_type": "postgresql", "tables": [{"name": "Order Details", "schema": "public"}], "columns": {"public.Order Details": [{"name": "total price", "type": "numeric"}]}}
    code = "SELECT d. FROM \"Order Details\" d"
    items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})["items"]
    item = next(item for item in items if item["label"] == "total price")
    assert item["insert_text"] == '"total price"' and item["category"] == "column"


@pytest.mark.parametrize(("db_type", "expected"), [("sqlite", '"select"'), ("sqlserver", "[select]"), ("mysql", "`select`"), ("mariadb", "`select`"), ("databricks", "`select`")])
def test_reserved_identifier_completions_are_valid_in_each_sql_dialect(db_type, expected):
    schema = {"db_type": db_type, "tables": [{"name": "sample"}], "columns": {"sample": [{"name": "select"}, {"name": 'a"b'}]}}
    code = "SELECT t. FROM sample t"
    items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})["items"]
    assert next(item for item in items if item["label"] == "select")["insert_text"] == expected
    if db_type == "sqlite":
        assert next(item for item in items if item["label"] == 'a"b')["insert_text"] == '"a""b"'


def test_sql_service_reuses_index_per_immutable_snapshot(monkeypatch):
    from src.services.sql_autocomplete_service import SqlAutoCompleteService
    original = SqlAutoCompleteService.set_schema
    calls = []
    def set_schema(self, schema):
        calls.append(schema)
        return original(self, schema)
    monkeypatch.setattr(SqlAutoCompleteService, "set_schema", set_schema)
    schema = {"tables": [{"name": "sample"}]}
    for code in ("SELECT ", "SELECT s", "SELECT sa"):
        dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": len(code) + 1}, {"schema": schema})
    assert calls == [schema]


def test_sql_catalog_beyond_payload_bound_is_filtered_before_limit():
    schema = {"db_type": "sqlite", "tables": [{"name": f"table_{index:05d}"} for index in range(5000)], "columns": {"table_04999": [{"name": f"field{index:04d}"} for index in range(1000)]}}
    code = "SELECT * FROM table_04999"
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": len(code) + 1}, {"schema": schema})
    assert "table_04999" in labels(result["items"])
    code = "SELECT t.field0999 FROM table_04999 t"
    result = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": code.index(" FROM") + 1}, {"schema": schema})
    assert "field0999" in labels(result["items"])


@pytest.mark.parametrize(("identifier", "expected"), [('public."IdTable"', "IdColumn"), ('public."idtable"', "idcolumn"), ("public.IDTABLE", "idcolumn")])
def test_postgres_quoted_table_case_and_unquoted_folding_are_preserved(identifier, expected):
    schema = {"db_type": "postgresql", "tables": [{"name": "IdTable", "schema": "public"}, {"name": "idtable", "schema": "public"}],
              "columns": {"public.IdTable": [{"name": "IdColumn"}], "public.idtable": [{"name": "idcolumn"}]}}
    code = f"SELECT t. FROM {identifier} t"
    items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})["items"]
    assert labels(items) == {expected}


def test_postgres_quoted_unknown_case_does_not_borrow_other_table_columns():
    schema = {"db_type": "postgresql", "tables": [{"name": "IdTable", "schema": "public"}], "columns": {"public.IdTable": [{"name": "IdColumn"}]}}
    code = 'SELECT t. FROM public."idtable" t'
    assert dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 10}, {"schema": schema})["items"] == []


def test_qualified_column_with_literal_dot_quotes_the_physical_name_once():
    schema = {"db_type": "postgresql", "tables": [{"name": "left_side", "schema": "public"}, {"name": "right_side", "schema": "public"}],
              "columns": {"public.left_side": [{"name": "a.b"}], "public.right_side": [{"name": "value"}]}}
    code = "SELECT  FROM public.left_side l JOIN public.right_side r ON true"
    items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 8}, {"schema": schema})["items"]
    assert next(item for item in items if item["label"] == "l.a.b")["insert_text"] == '"l"."a.b"'


def test_cached_dotted_names_choose_longest_physical_suffix_for_each_alias():
    schema = {"db_type": "postgresql", "tables": [{"name": "left_side", "schema": "public"}, {"name": "right_side", "schema": "public"}],
              "columns": {"public.left_side": [{"name": "value.part"}, {"name": "deep.value.part"}], "public.right_side": [{"name": "id"}]}}
    for alias in ("l", "left_alias"):
        code = f"SELECT  FROM public.left_side {alias} JOIN public.right_side r ON true"
        items = dispatch("language.complete", {"language": "sql", "code": code, "line": 1, "column": 8}, {"schema": schema})["items"]
        assert next(item for item in items if item["label"] == f"{alias}.value.part")["insert_text"] == f'"{alias}"."value.part"'
        assert next(item for item in items if item["label"] == f"{alias}.deep.value.part")["insert_text"] == f'"{alias}"."deep.value.part"'


def test_python_result_cache_is_bounded_and_result_mutation_is_isolated(monkeypatch):
    language._PYTHON_RESULTS.clear()
    monkeypatch.setattr(language, "_PYTHON_CACHE_BYTES", 0)
    monkeypatch.setattr(language, "MAX_COMPLETION_CACHE_BYTES", 10)
    calls = []
    def infer(*args):
        calls.append(args)
        return [{"label": "cached", "kind": "variable", "insert_text": "cached"}]
    monkeypatch.setattr(language, "_python_complete_unlocked", infer)
    assert complete("a")
    first = complete("a")
    first[0]["label"] = "mutated"
    assert complete("a")[0]["label"] == "cached" and len(calls) == 1
    for code in ("abcd", "efgh", "ijkl"):
        complete(code)
    assert language._PYTHON_CACHE_BYTES <= 10
    language._PYTHON_RESULTS.clear()
    monkeypatch.setattr(language, "_PYTHON_CACHE_BYTES", 0)


def test_metadata_key_ignores_typing_fields_and_comment_or_literal_relations():
    before = metadata_signature("SELECT t. FROM reporting.sample t -- FROM ignored\nWHERE title='JOIN fake'")
    assert before == metadata_signature("SELECT t.title FROM reporting.sample t -- FROM another\nWHERE title='JOIN fake'")
    assert before != metadata_signature("SELECT t. FROM reporting.other t")
    assert before[0] == (("reporting", "sample"),)


def test_metadata_scanner_is_linear_for_a_100k_identifier_without_dots():
    started = time.perf_counter()
    assert metadata_signature("SELECT " + "a" * 100_000) == ((), (), False)
    assert time.perf_counter() - started < .5


def test_completion_cancel_is_exact_and_never_cancels_newer_block_request():
    jobs = BackgroundJobs(lambda event: None, completion_process=False)
    key = ("session", "block", "language.complete")
    try:
        jobs.latest[key] = 2
        jobs.completion_ids[key] = (2, "current")
        assert jobs.cancel_completion("session", "block", "old")["status"] == "already_finished"
        assert jobs.latest[key] == 2
        assert jobs.cancel_completion("session", "block", "current")["status"] == "cancelling"
        assert key not in jobs.latest
    finally:
        jobs.close()


def test_running_completion_process_observes_superseded_without_waiting_for_timeout(monkeypatch):
    from datapyn_runtime.editor_process import CompletionProcess
    closed = threading.Event()
    worker = CompletionProcess(closed)
    connection = SimpleNamespace(send=lambda value: None, poll=lambda timeout: False)
    process = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(worker, "_start", lambda: (process, connection))
    stopped = []
    monkeypatch.setattr(worker, "_stop", lambda: stopped.append(True))
    worker.ready = True
    checks = []
    def stale():
        checks.append(True)
        return len(checks) >= 2
    started = time.monotonic()
    assert worker.request({}, {}, timeout=12, superseded=stale)["result"]["superseded"]
    assert stopped and time.monotonic() - started < 0.1
