"""Typed header controls share exact views and bounded original-value suggestions."""

from datetime import date
from decimal import Decimal
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest

from datapyn_runtime.data_tools import dispatch
from datapyn_runtime.result_store import ResultStore, MAX_SUGGESTION_BYTES
from test_runtime import Client


def registered(frame, native=False):
    store = ResultStore(pd, pl)
    frame = pl.from_pandas(frame) if native else frame
    return store, store.register(frame, "frame")["result_id"]


def filtered(store, identifier, column, operator, value=None, **options):
    return store.page({"result_id": identifier,
                       "filter": {"column": column, "operator": operator, "value": value, **options}})["rows"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("operator,value,expected", [
    ("starts_with", "a.[", [0, 1]),
    ("ends_with", ".[END]", [0, 2]),
    ("equals", "STRASSE", [3, 4]),
    ("contains", ".[", [0, 1, 2]),
])
def test_literal_text_filters_case_insensitive_and_null_safe(native, operator, value, expected):
    frame = pd.DataFrame({"id": range(6), "text": ["A.[x].[End]", "a.[y]", "z.[END]", "straße", "STRASSE", None]})
    store, identifier = registered(frame, native)
    assert [row[0] for row in filtered(store, identifier, "text", operator, value)] == expected
    assert len(store.frames[identifier]) == 6


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("lower,upper,expected", [
    ("1.5", "2.5", [2]), ("-2.5", "-1.5", [-2]),
    ("1.5", "1.6", []), (None, "-1.5", [-3, -2]), ("2.5", "", [3]),
])
def test_integer_ranges_allow_fractional_limits_without_float_rounding(native, lower, upper, expected):
    store, identifier = registered(pd.DataFrame({"value": pd.Series([-3, -2, -1, 1, 2, 3, None], dtype="Int64")}), native)
    assert [row[0] for row in filtered(store, identifier, "value", "between", lower, value_to=upper)] == expected


@pytest.mark.parametrize("native", [False, True])
def test_bigint_and_decimal_ranges_keep_exact_boundaries(native):
    big = 2**63 + 17
    frame = pd.DataFrame({"big": pd.Series([big, big + 1, big + 2, None], dtype="UInt64"),
                          "amount": [Decimal("1.000000000000000001"), Decimal("1.000000000000000002"), Decimal("1.000000000000000003"), None]})
    store, identifier = registered(frame, native)
    assert filtered(store, identifier, "big", "between", str(big) + ".1", value_to=str(big + 1) + ".9") == [[str(big + 1), "1.000000000000000002"]]
    assert filtered(store, identifier, "amount", "between", "1,000000000000000002", value_to="1.000000000000000002") == [[str(big + 1), "1.000000000000000002"]]


def test_object_numeric_range_does_not_round_when_first_value_is_integer():
    frame = pd.DataFrame({"value": pd.Series([1, Decimal("1.750000000000000001"), 1.8, None], dtype=object)})
    store, identifier = registered(frame)
    assert filtered(store, identifier, "value", "between", "1.7", value_to="1.750000000000000001") == [["1.750000000000000001"]]


@pytest.mark.parametrize("native", [False, True])
def test_range_aliases_open_limits_and_scalar_integer_compatibility(native):
    store, identifier = registered(pd.DataFrame({"value": pd.Series([1, 2, 3, None], dtype="Int64")}), native)
    for lower, upper in (("min", "max"), ("start", "end")):
        params = {"result_id": identifier, "filter": {"column": "value", "operator": "between", lower: "1.5", upper: "2.5"}}
        assert store.page(params)["rows"] == [[2]]
    assert filtered(store, identifier, "value", "between", "", value_to=None) == [[1], [2], [3], [None]]
    assert filtered(store, identifier, "value", "equals", "2") == [[2]]
    with pytest.raises(ValueError, match="whole number"):
        filtered(store, identifier, "value", "gte", "1.5")


@pytest.mark.parametrize("native", [False, True])
def test_calendar_date_upper_includes_whole_day_but_datetime_is_exact_to_ns(native):
    dates = pd.to_datetime(["2026-03-29T00:00:00.000000001", "2026-03-29T12:00:00.000000002",
                            "2026-03-29T23:59:59.999999999", "2026-03-30T00:00:00", None], format="ISO8601")
    store, identifier = registered(pd.DataFrame({"id": range(5), "when": dates}), native)
    assert [row[0] for row in filtered(store, identifier, "when", "between", "2026-03-29", value_to="2026-03-29")] == [0, 1, 2]
    assert [row[0] for row in filtered(store, identifier, "when", "between", None, value_to="2026-03-29T12:00:00.000000001")] == [0]
    assert [row[0] for row in filtered(store, identifier, "when", "between", "2026-03-29T12:00:00.000000002", value_to="2026-03-29T12:00:00.000000002")] == [1]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25"])
def test_calendar_day_upper_uses_timezone_calendar_across_dst(native, day):
    start = pd.Timestamp(day, tz="Europe/Berlin")
    end = start + pd.DateOffset(days=1)
    assert (end - start).total_seconds() in (23 * 3600, 25 * 3600)
    store, identifier = registered(pd.DataFrame({"when": [start, end - pd.Timedelta(1, unit="ns"), end]}), native)
    rows = filtered(store, identifier, "when", "between", day, value_to=day)
    assert len(rows) == 2 and rows[-1][0] == (end - pd.Timedelta(1, unit="ns")).isoformat()


@pytest.mark.parametrize("native", [False, True])
def test_plain_date_and_long_null_prefix_use_same_bounded_type_inference(native):
    frame = pd.DataFrame({"day": [None] * 250 + [date(2026, 10, 3), date(2026, 10, 4)],
                          "amount": [None] * 250 + [Decimal("7.000000000000000001"), Decimal("7.000000000000000002")]})
    store, identifier = registered(frame, native)
    assert filtered(store, identifier, "day", "between", "2026-10-03", value_to="2026-10-03") == [["2026-10-03", "7.000000000000000001"]]
    assert filtered(store, identifier, "amount", "equals", "7.000000000000000002") == [["2026-10-04", "7.000000000000000002"]]
    assert store.column_values({"result_id": identifier, "column": "day"})["kind"] == "date"
    assert store.column_values({"result_id": identifier, "column": "amount"})["kind"] == "number"


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("value,expected", [("t", [0, 2]), ("y", [0, 2]), ("s", [0, 2]), ("f", [1]), ("n", [1]), ("nao", [1])])
def test_nullable_boolean_aliases(native, value, expected):
    store, identifier = registered(pd.DataFrame({"id": range(4), "enabled": pd.Series([True, False, True, None], dtype="boolean")}), native)
    assert [row[0] for row in filtered(store, identifier, "enabled", "equals", value)] == expected


@pytest.mark.parametrize("native", [False, True])
def test_bool_like_strings_are_inferred_and_filtered_after_null_prefix(native):
    aliases = ["T", "y", "sim", "s", "1", "F", "n", "nao", "0"]
    store, identifier = registered(pd.DataFrame({"value": [None] * 250 + aliases}), native)
    suggestions = store.column_values({"result_id": identifier, "column": "value"})
    assert suggestions["kind"] == "bool" and suggestions["values"] == aliases
    assert [row[0] for row in filtered(store, identifier, "value", "equals", "true")] == aliases[:5]
    assert [row[0] for row in filtered(store, identifier, "value", "equals", "false")] == aliases[5:]


@pytest.mark.parametrize("native", [False, True])
def test_compound_header_filters_export_same_stable_view_and_selection(native):
    frame = pd.DataFrame({"id": [0, 1, 2, 3, 4], "key": [2., 1., 2., None, 2.], "text": ["Allowed", "allowed", "ALLOWED", "allowed", "skip"]}, index=[9] * 5)
    store, identifier = registered(frame, native)
    params = {"result_id": identifier, "filter": {"filters": [
        {"column": "text", "operator": "starts_with", "value": "allow"},
        {"column": "key", "operator": "between", "value": "1", "value_to": "2"}]},
        "sort": {"column": "key", "direction": "desc"}}
    assert [row[0] for row in store.page(params)["rows"]] == [0, 2, 1]
    output = dispatch("result.export_text", {**params, "format": "json", "scope": {"row_ranges": [[1, 2]], "column_indices": [0]}}, {}, store)
    assert json.loads(output["text"]) == [{"id": 2}, {"id": 1}]
    with_nulls = store.page({"result_id": identifier, "sort": params["sort"]})
    assert [row[0] for row in with_nulls["rows"]] == [0, 2, 4, 1, 3]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("value,match", [("1e1001", "exponent"), ("1e-1001", "exponent"), ("9" * 1025, "1024"), ("1e400", "finite"), ("nan", "finite"), ("inf", "finite")])
def test_numeric_filters_reject_unbounded_or_nonfinite_inputs(native, value, match):
    store, identifier = registered(pd.DataFrame({"value": [1.5]}), native)
    with pytest.raises(ValueError, match=match):
        filtered(store, identifier, "value", "between", value)


@pytest.mark.parametrize("native", [False, True])
def test_suggestions_preserve_decimal_bigint_ns_and_skip_nulls(native):
    frame = pd.DataFrame({"big": pd.Series([2**63 + 1, None, 2**63 + 1], dtype="UInt64"),
                          "amount": [Decimal("1.234567890123456789"), None, Decimal("1.234567890123456789")],
                          "when": pd.to_datetime(["2026-10-04T01:02:03.123456789", None, "2026-10-04T01:02:03.123456789"])})
    store, identifier = registered(frame, native)
    for column, kind, values in (("big", "number", [str(2**63 + 1)]), ("amount", "number", ["1.234567890123456789"]),
                                 ("when", "date", ["2026-10-04T01:02:03.123456789"])):
        result = store.column_values({"result_id": identifier, "column": column})
        assert result == {"values": values, "kind": kind, "sampled": False, "scanned_rows": 3, "total_rows": 3}


@pytest.mark.parametrize("native", [False, True])
def test_suggestions_use_original_column_and_skip_full_view_or_distinct(monkeypatch, native):
    store, identifier = registered(pd.DataFrame({"value": range(100)}), native)
    def forbidden(*args, **kwargs):
        raise AssertionError("Suggestions must not materialize a view or full distinct")
    monkeypatch.setattr(store, "_frame_and_positions", forbidden)
    monkeypatch.setattr(pd.Series, "unique", forbidden)
    monkeypatch.setattr(pl.Series, "unique", forbidden)
    monkeypatch.setattr(pl.DataFrame, "to_pandas", forbidden)
    result = store.column_values({"result_id": identifier, "column": "value", "filter": {"text": "99"}, "sort": {"column": "value", "direction": "desc"}, "limit": 3})
    assert result == {"values": [0, 1, 2], "kind": "number", "sampled": True, "scanned_rows": 3, "total_rows": 100}


def test_ten_million_row_source_scans_only_first_ten_thousand(monkeypatch):
    values = np.broadcast_to(np.array([7], dtype=np.int64), (10_000_000,))
    frame = pd.DataFrame({"value": values}, copy=False)
    assert np.shares_memory(frame["value"].to_numpy(), values)
    store, identifier = registered(frame)
    def forbidden(*args, **kwargs):
        raise AssertionError("No full distinct")
    monkeypatch.setattr(pd.Series, "unique", forbidden)
    result = store.column_values({"result_id": identifier, "column": "value"})
    assert result == {"values": [7], "kind": "number", "sampled": True, "scanned_rows": 10_000, "total_rows": 10_000_000}


@pytest.mark.parametrize("native", [False, True])
def test_suggestions_do_not_look_beyond_budgeted_prefix(native):
    store, identifier = registered(pd.DataFrame({"value": [None] * 10_000 + ["late"]}), native)
    result = store.column_values({"result_id": identifier, "column": "value"})
    assert result == {"values": [], "kind": "text", "sampled": True, "scanned_rows": 10_000, "total_rows": 10_001}


@pytest.mark.parametrize("native", [False, True])
def test_suggestions_skip_large_values_without_truncation_and_bound_utf8_bytes(native):
    strings = ["huge" * 1000] + [str(i) + "漢" * 990 for i in range(100)] + ["small"]
    store, identifier = registered(pd.DataFrame({"value": strings}), native)
    result = store.column_values({"result_id": identifier, "column": "value"})
    assert result["sampled"] and "small" in result["values"]
    assert all(value in strings and len(value) <= 1000 for value in result["values"])
    assert len(json.dumps(result["values"], ensure_ascii=False).encode("utf-8")) <= MAX_SUGGESTION_BYTES
    assert store.frames[identifier]["value"][0] == strings[0]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"limit": True}, {"column": "missing"}])
def test_suggestion_parameters_are_validated(params):
    store, identifier = registered(pd.DataFrame({"value": [1]}))
    with pytest.raises(ValueError):
        store.column_values({"result_id": identifier, "column": "value", **params})


def test_real_stdio_column_values_and_ranges_share_export_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    client = Client()
    try:
        client.session()
        finished = client.execute("frame = pd.DataFrame({'id': [1, 2, 3], 'label': ['Alpha', 'ALPHA', 'Beta']})\nframe")
        params = {"session_id": "a", "result_id": finished["results"][0]["result_id"]}
        assert client.request("result.column_values", {**params, "column": "label"})["values"] == ["Alpha", "ALPHA", "Beta"]
        view = {**params, "filter": {"column": "id", "operator": "between", "value": "1.5", "value_to": "2.5"}}
        assert client.request("result.page", view)["rows"] == [[2, "ALPHA"]]
        assert json.loads(client.request("result.export_text", {**view, "format": "json"})["text"]) == [{"id": 2, "label": "ALPHA"}]
        client.session("other")
        assert "error" in client.response("result.column_values", {**params, "session_id": "other", "column": "label"})
        assert client.request("result.column_values", {**params, "column": "label", "limit": 1})["sampled"]
    finally:
        client.close()
