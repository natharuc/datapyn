from datetime import date
from decimal import Decimal

import pandas as pd
import polars as pl
import pytest

from datapyn_runtime.data_tools import dispatch
from datapyn_runtime.frame_view import apply_view
from datapyn_runtime.kernel import ResultStore


def test_typed_and_filters_global_text_and_stable_sort():
    frame = pd.DataFrame({"name": ["Alpha", "alpha", "Beta", "Alpha"], "value": [1, 3, 2, 3], "ok": [False, True, True, True]})
    filtered = apply_view(frame, {"filter": {"text": "alpha", "filters": [
        {"column": "value", "operator": "gte", "value": "3"}, {"column": "ok", "operator": "equals", "value": "true"}]},
        "sort": {"column": "value", "direction": "desc"}})
    assert filtered.index.tolist() == [1, 3]
    assert len(frame) == 4


def test_exact_integer_and_decimal_and_null_filters():
    frame = pd.DataFrame({"big": [2**60, 2**60 + 1], "decimal": [Decimal("1.234567890123456789"), None]})
    filtered = apply_view(frame, {"filter": {"filters": [
        {"column": "big", "operator": "equals", "value": str(2**60 + 1)},
        {"column": "decimal", "operator": "is_null"}]}})
    assert filtered.index.tolist() == [1]
    filtered = apply_view(frame, {"filter": {"column": "decimal", "operator": "equals", "value": "1.234567890123456789"}})
    assert filtered.index.tolist() == [0]


def test_dates_and_timezone_are_coerced():
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True), "date": [date(2026, 1, 1), date(2026, 1, 2)]})
    result = apply_view(frame, {"filter": {"filters": [{"column": "timestamp", "operator": "gte", "value": "2026-01-02"},
                                                    {"column": "date", "operator": "lte", "value": "2026-01-02"}]}})
    assert result.index.tolist() == [1]


def test_namespace_summary_and_export_use_same_combined_view(tmp_path):
    namespace = {"df": pd.DataFrame({"x": [1, 2, 3], "name": ["a", "b", "a"]})}
    store = ResultStore(pd, pl)
    params = {"variable_name": "df", "filter": {"filters": [{"column": "x", "operator": "gt", "value": "1"}, {"column": "name", "operator": "equals", "value": "a"}]}}
    summary = dispatch("result.summary", params, namespace, store)
    assert summary["row_count"] == 1
    path = tmp_path / "same.csv"
    dispatch("result.export", {**params, "path": str(path)}, namespace, store)
    assert pd.read_csv(path, sep=";")["x"].tolist() == [3]


@pytest.mark.parametrize("filter", [{"filters": [1]}, {"filters": [{}] * 65}, {"column": "x", "operator": "gte", "value": "bad"},
                                  {"column": "x", "operator": "gt", "value": None}, {"column": "x", "operator": "wat", "value": 1}])
def test_invalid_filters_are_explicit_errors(filter):
    with pytest.raises(ValueError):
        apply_view(pd.DataFrame({"x": [1]}), {"filter": filter})


def test_unknown_and_ambiguous_columns_never_select_another_field():
    frame = pd.DataFrame([[1, 2]], columns=["x", "x"])
    with pytest.raises(ValueError, match="Ambiguous"):
        apply_view(frame, {"filter": {"column": "x", "operator": "equals", "value": 1}})
    with pytest.raises(ValueError, match="Unknown"):
        apply_view(frame, {"sort": {"column": "missing"}})
