"""Real file formats, view scopes, precision and transactions of the Qt-free API."""

from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import polars as pl
import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
os.environ.setdefault("DATAPYN_SHARED_PARAMETER_DELIMITER", "{{name}}")

from datapyn_runtime.kernel import ResultStore
from datapyn_runtime import data_tools as tools


@pytest.fixture
def context():
    frame = pd.DataFrame({"group": ["a", "b", "a", "c"], "value": [4, 2, 8, 1], "nullable": [1.0, None, 3.0, 4.0]})
    store = ResultStore(pd, pl)
    namespace = {"df": frame, "pd": pd}
    ref = store.register(frame, "df")
    return namespace, store, ref


def call(context, method, **params):
    namespace, store, ref = context
    return tools.dispatch(method, {"result_id": ref["result_id"], **params}, namespace, store)


def test_selection_applies_after_sort_filter_without_mutation(context):
    namespace, store, ref = context
    data = tools.selected_frame({"result_id": ref["result_id"], "sort": {"column": "value", "direction": "desc"},
                                 "filter": {"text": "a"}, "scope": {"row_ranges": [[1, 1]], "column_indices": [1]}}, namespace, store)
    assert data.values.tolist() == [[4]]
    assert namespace["df"]["value"].tolist() == [4, 2, 8, 1]


def test_discontiguous_ranges_do_not_include_or_duplicate_extra_rows(context):
    namespace, store, ref = context
    data = tools.selected_frame({"result_id": ref["result_id"], "scope": {"row_ranges": [[0, 0], [2, 3], [3, 3]], "column_indices": [1]}}, namespace, store)
    assert data.values.tolist() == [[4], [8], [1]]


def test_disjoint_rectangles_do_not_export_or_summarize_extra_cells(tmp_path):
    namespace = {"df": pd.DataFrame({"a": [1, 2, 300, 400, 500, 600], "b": [900, 800, 700, 600, 5, 6]})}
    store = ResultStore(pd, pl)
    scope = {"rectangles": [{"x": 0, "y": 0, "width": 1, "height": 2}, {"x": 1, "y": 4, "width": 1, "height": 2}]}
    params = {"variable_name": "df", "scope": scope}
    summary = tools.dispatch("result.summary", params, namespace, store)
    assert [(column["count"], column["null_count"], column["sum"]) for column in summary["columns"]] == [(2, 0, 3), (2, 0, 11)]
    path = tmp_path / "selected.json"
    tools.dispatch("result.export", {**params, "path": str(path)}, namespace, store)
    assert json.loads(path.read_text()) == [{"a": 1, "b": None}, {"a": 2, "b": None}, {"a": None, "b": 5}, {"a": None, "b": 6}]
    assert namespace["df"].iat[0, 1] == 900


def test_sparse_selection_preserves_bigint_in_holes(tmp_path):
    namespace = {"df": pd.DataFrame({"a": [2**60, 2**60 + 1], "b": [4, 5]})}
    store = ResultStore(pd, pl)
    path = tmp_path / "big.json"
    tools.dispatch("result.export", {"variable_name": "df", "path": str(path), "scope": {"rectangles": [
        {"x": 0, "y": 0, "width": 1, "height": 1}, {"x": 1, "y": 1, "width": 1, "height": 1}]}}, namespace, store)
    assert json.loads(path.read_text())[0]["a"] == str(2**60)


@pytest.mark.parametrize("scope", [{"row_ranges": []}, {"row_ranges": [[-1, 1]]}, {"row_ranges": [[0, 10]]}, {"column_indices": [True]}, {"column_indices": []}])
def test_invalid_scope_is_rejected(context, scope):
    with pytest.raises(ValueError):
        call(context, "result.summary", scope=scope)


@pytest.mark.parametrize("format", ["csv", "xlsx", "json", "parquet"])
def test_exports_round_trip_real_files(context, tmp_path, format):
    path = tmp_path / f"data.{format}"
    response = call(context, "result.export", path=str(path), format=format)
    assert response["row_count"] == 4
    readers = {"csv": lambda: pd.read_csv(path, sep=";"), "xlsx": lambda: pd.read_excel(path),
               "json": lambda: pd.read_json(path), "parquet": lambda: pd.read_parquet(path)}
    pd.testing.assert_frame_equal(readers[format](), context[0]["df"])


def test_json_excel_preserve_precision_and_do_not_execute_formula(tmp_path):
    namespace = {"df": pd.DataFrame({"big": [2**60], "decimal": [Decimal("1.234567890123456789")], "text": ["=1+1"]})}
    store = ResultStore(pd, pl)
    path = tmp_path / "data.json"
    tools.dispatch("result.export", {"variable_name": "df", "path": str(path)}, namespace, store)
    assert json.loads(path.read_text())[0] == {"big": str(2**60), "decimal": "1.234567890123456789", "text": "=1+1"}
    path = tmp_path / "data.xlsx"
    tools.dispatch("result.export", {"variable_name": "df", "path": str(path)}, namespace, store)
    from openpyxl import load_workbook
    book = load_workbook(path)
    assert book.active["C2"].data_type == "s"
    assert book.active["C2"].value == "=1+1"
    assert book.active["A2"].value == str(2**60)
    book.close()


@pytest.mark.parametrize("by_result", [False, True])
def test_native_polars_export_preserves_nullable_uint64_and_decimal(tmp_path, by_result):
    frame = pl.DataFrame({
        "big": pl.Series([2**64 - 1, None], dtype=pl.UInt64),
        "amount": pl.Series([Decimal("1.234567890123456789"), None], dtype=pl.Decimal(30, 18)),
    })
    store = ResultStore(pd, pl)
    ref = store.register(frame, "df")
    path = tmp_path / "native-polars.json"
    params = {"result_id": ref["result_id"]} if by_result else {"variable_name": "df"}
    tools.dispatch("result.export", {**params, "path": str(path)}, {"df": frame}, store)
    assert json.loads(path.read_text()) == [
        {"big": str(2**64 - 1), "amount": "1.234567890123456789"},
        {"big": None, "amount": None},
    ]


def test_failed_export_does_not_truncate_existing_destination(context, tmp_path):
    path = tmp_path / "existing.txt"
    path.write_text("keep")
    with pytest.raises(ValueError):
        call(context, "result.export", path=str(path), format="unknown")
    assert path.read_text() == "keep"
    assert list(tmp_path.iterdir()) == [path]


def test_sql_insert_quotes_identifiers_and_binds_values(context, tmp_path):
    path = tmp_path / "data.sql"
    call(context, "result.export", path=str(path), options={"db_type": "sqlite", "table_name": 'my"table'})
    content = path.read_text()
    assert 'INSERT INTO "my""table"' in content
    assert "'a'" in content
    assert "NULL" in content


def test_import_data_registers_namespace_and_ref_without_overwrite(context, tmp_path):
    path = tmp_path / "2026 new.csv"
    path.write_text("x;y\n1;2\n", encoding="utf-8")
    namespace, store, _ = context
    response = tools.dispatch("data.import", {"path": str(path)}, namespace, store)
    assert response["variable_name"] == "df_2026_new"
    assert namespace["df_2026_new"].values.tolist() == [[1, 2]]
    assert response["result"]["result_id"] in store.frames
    with pytest.raises(ValueError, match="already exists"):
        tools.dispatch("data.import", {"path": str(path)}, namespace, store)
    with pytest.raises(ValueError, match="runtime"):
        tools.dispatch("data.import", {"path": str(path), "variable_name": "pd", "overwrite": True}, namespace, store)


def test_inspect_is_paged_and_deletion_releases_frame(context):
    namespace, store, ref = context
    namespace["items"] = list(range(1000))
    inspected = tools.dispatch("variable.inspect", {"name": "items", "offset": 900, "limit": 100}, namespace, store)
    assert inspected["total_entries"] == 1000
    assert len(inspected["entries"]) == 100
    assert inspected["entries"][0]["value"] == "900"
    tools.dispatch("variable.delete", {"name": "df"}, namespace, store)
    assert "df" not in namespace and ref["result_id"] not in store.frames
    assert ref["result_id"] not in store.descriptors
    with pytest.raises(ValueError, match="runtime"):
        tools.dispatch("variable.delete", {"name": "pd"}, namespace, store)


def test_deleting_polars_frame_releases_its_converted_handle_and_keeps_alias():
    frame = pl.DataFrame({"amount": [12]})
    namespace = {"df": frame, "other": frame}
    store = ResultStore(pd, pl)
    deleted = store.register(frame, "df")
    kept = store.register(frame, "other")
    tools.delete_variable({"name": "df"}, namespace, store)
    assert "df" not in namespace and namespace["other"] is frame
    assert deleted["result_id"] not in store.frames
    assert deleted["result_id"] not in store.descriptors
    assert kept["result_id"] in store.descriptors
    assert store.page({"result_id": kept["result_id"], "offset": 0, "limit": 10})["rows"] == [[12]]


def test_summary_is_json_safe_and_reports_selected_data(context):
    summary = call(context, "result.summary", scope={"column_indices": [1], "row_ranges": [[0, 0], [2, 2]]})
    assert summary["row_count"] == 2
    assert summary["columns"][0]["sum"] == 12
    assert summary["columns"][0]["mean"] == 6
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("chart_type", ["bar", "line", "area", "scatter", "pie"])
def test_charts_reuse_legacy_aggregation_with_no_qt(context, chart_type):
    qt_before = {name for name in sys.modules if name.startswith("PyQt")}
    response = call(context, "result.chart", config={"type": chart_type, "x_column": "group", "y_columns": ["value"], "aggregation": "sum"})
    trace = response["figure"]["data"][0]
    assert trace["values" if chart_type == "pie" else "y"] == [12.0, 2.0, 1.0]
    assert response["point_count"] == 3
    assert {name for name in sys.modules if name.startswith("PyQt")} == qt_before


def test_chart_imports_are_qt_free_in_fresh_interpreter():
    code = """import sys,pandas as pd,polars as pl
from datapyn_runtime.kernel import ResultStore
from datapyn_runtime.data_tools import dispatch
dispatch('result.chart', {'variable_name':'df','config':{'x_column':'x','y_columns':['y']}},
         {'df':pd.DataFrame({'x':['a'],'y':[2]})}, ResultStore(pd,pl))
assert not any(name.startswith('PyQt') for name in sys.modules)
"""
    response = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "source")}, timeout=30)
    assert response.returncode == 0, response.stderr


def test_export_table_uses_real_transaction_and_quotes(context):
    class Connector:
        engine = create_engine("sqlite:///:memory:")
    namespace, store, ref = context
    params = {"result_id": ref["result_id"], "table": 'table"name', "if_exists": "fail"}
    response = tools.dispatch("result.export_table", params, namespace, store, Connector())
    assert response["row_count"] == 4
    with Connector.engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM "table""name"')).scalar() == 4
    with pytest.raises(ValueError):
        tools.dispatch("result.export_table", params, namespace, store, Connector())
    Connector.engine.dispose()


def test_code_and_notebook_roundtrip_preserve_cells(tmp_path):
    source = tmp_path / "source.ipynb"
    source.write_text(json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Header\n"], "metadata": {"tag": "x"}},
                                                {"cell_type": "code", "source": "x = 1", "metadata": {}}], "metadata": {"custom": 1}}))
    read = tools.read_document({"path": str(source)})
    assert [block["cell_type"] for block in read["blocks"]] == ["markdown", "code"]
    target = tmp_path / "saved.ipynb"
    tools.export_script({"path": str(target), "blocks": read["blocks"], "notebook_metadata": read["notebook_metadata"]})
    assert tools.read_document({"path": str(target)})["blocks"] == read["blocks"]
    assert json.loads(target.read_text())["metadata"] == {"custom": 1}


def test_notebook_preserves_empty_cells_and_empty_notebook_metadata(tmp_path):
    source = tmp_path / "empty-cells.ipynb"
    source.write_text(json.dumps({"cells": [{"cell_type": "code", "source": [], "metadata": {"name": "first"}},
                                          {"cell_type": "markdown", "source": "  ", "metadata": {}},
                                          {"cell_type": "raw", "source": [], "metadata": {}}], "metadata": {}}))
    read = tools.read_document({"path": str(source)})
    assert [block["cell_type"] for block in read["blocks"]] == ["code", "markdown", "raw"]
    assert [block["code"] for block in read["blocks"]] == ["", "  ", ""]
    target = tmp_path / "roundtrip.ipynb"
    tools.export_script({"path": str(target), "blocks": read["blocks"], "notebook_metadata": read["notebook_metadata"]})
    assert tools.read_document({"path": str(target)})["blocks"] == read["blocks"]
    assert json.loads(target.read_text())["metadata"] == {}


def test_mixed_script_compiles_and_handles_quotes_safely(tmp_path):
    target = tmp_path / "analysis.py"
    tools.export_script({"path": str(target), "blocks": [{"language": "sql", "code": "SELECT '\"\"\"' AS text", "name": "data"},
                                                          {"language": "python", "code": "print(data)"}]})
    content = target.read_text()
    compile(content, str(target), "exec")
    assert "DATAPYN_DATABASE_URL" in content


def test_parameterized_script_compiles(tmp_path):
    target = tmp_path / "analysis.py"
    tools.export_script({"path": str(target), "blocks": [{"language": "sql", "code": "SELECT @name", "name": "df", "sql_parameters": [
        {"name": "name", "sql_type": "text", "value": "O'Reilly", "id": "sqlparam:name"}]}]})
    compile(target.read_text(), str(target), "exec")
    assert "SELECT :name" in target.read_text()
