"""Chart configuration, exact aggregates, bounded preparation and snapshot exports."""

from decimal import Decimal
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest

from datapyn_runtime.data_tools import dispatch
from datapyn_runtime.result_store import ResultStore
from datapyn_runtime import chart_runtime
from test_runtime import Client


def source(frame, native=False):
    store = ResultStore(pd, pl)
    frame = pl.from_pandas(frame) if native else frame
    ref = store.register(frame, "frame")
    return store, {"result_id": ref["result_id"], "config": {"x_column": "x", "y_columns": ["y"]}}


def preview(store, params, **config):
    return dispatch("result.chart", {**params, "config": {**params["config"], **config}}, {}, store)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("aggregation,expected", [("sum", "3"), ("mean", "1.5"), ("median", "1.5"), ("min", "1"), ("max", "2"), ("count", "2")])
def test_six_aggregations_have_same_data_contract(native, aggregation, expected):
    store, params = source(pd.DataFrame({"x": ["a", "a"], "y": [1, 2]}), native)
    chart = preview(store, params, aggregation=aggregation)
    trace = chart["figure"]["data"][0]
    assert Decimal(trace["customdata"][0][1]) == Decimal(expected)
    assert chart["source_rows"] == 2 and chart["aggregated_point_count"] == 1
    assert chart["point_count"] == 1 and chart["bounded"] is False


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("kind,cap", [("bar", 120), ("line", 500), ("area", 500), ("scatter", 500), ("pie", 24)])
def test_exact_cap_is_not_reported_as_truncated(native, kind, cap):
    store, params = source(pd.DataFrame({"x": [f"{i:04}" for i in range(cap)], "y": [1] * cap}), native)
    chart = preview(store, params, type=kind)
    assert chart["point_count"] == chart["aggregated_point_count"] == cap
    assert chart["bounded"] is False and chart["truncated_points"] == 0
    store, params = source(pd.DataFrame({"x": [f"{i:04}" for i in range(cap + 3)], "y": [1] * (cap + 3)}), native)
    chart = preview(store, params, type=kind)
    assert chart["point_count"] == cap and chart["aggregated_point_count"] == cap + 3
    assert chart["bounded"] is True and chart["truncated_points"] == 3


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("kind", ["bar", "line", "area", "scatter", "pie"])
def test_exact_decimal_and_bigint_values_survive_geometry_and_export(native, kind, tmp_path):
    frame = pd.DataFrame({"x": ["a", "a"], "y": pd.Series([2**63 + 1, 2**63 + 1], dtype="UInt64")})
    store, params = source(frame, native)
    chart = preview(store, params, type=kind, show_data_labels=True, label_decimals=0)
    trace = chart["figure"]["data"][0]
    assert trace["customdata"] == [["a", "18446744073709551618"]]
    assert chart["geometry_approximate"] and "%{customdata[1]}" in trace["hovertemplate"]
    file = tmp_path / "exact.json"
    dispatch("result.chart_export", {"chart_id": chart["chart_id"], "path": str(file)}, {}, store)
    assert json.loads(file.read_text())["figure"] == chart["figure"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("aggregation,expected", [("sum", "3.000000000000000003"), ("mean", "1.5000000000000000015"), ("median", "1.5000000000000000015")])
def test_decimal_aggregation_keeps_precision_before_float_geometry(native, aggregation, expected):
    frame = pd.DataFrame({"x": ["a", "a"], "y": [Decimal("1.000000000000000001"), Decimal("2.000000000000000002")]})
    store, params = source(frame, native)
    chart = preview(store, params, aggregation=aggregation)
    assert chart["figure"]["data"][0]["customdata"][0][1] == expected
    if native and aggregation in {"mean", "median"}:
        assert chart["aggregation_engine"] == "pandas_exact"


@pytest.mark.parametrize("native", [False, True])
def test_sparse_pivot_does_not_convert_exact_integers_to_float(native):
    frame = pd.DataFrame({"x": ["a", "b"], "group": ["one", "two"], "y": pd.Series([2**53 + 1, 2**53 + 3], dtype="UInt64")})
    store, params = source(frame, native)
    chart = preview(store, params, group_by="group", nulls="keep")
    one, two = chart["figure"]["data"]
    assert one["customdata"] == [["a", "9007199254740993"], ["b", None]]
    assert two["customdata"] == [["a", None], ["b", "9007199254740995"]]


@pytest.mark.parametrize("native", [False, True])
def test_only_observed_categorical_series_are_pivoted(native):
    frame = pd.DataFrame({"x": ["a", "a", "b"], "group": pd.Categorical(["one", "two", "one"], categories=["one", "two", *[f"unused{i}" for i in range(100_000)]]), "y": [1, 2, 3]})
    store, params = source(frame, native)
    chart = preview(store, params, group_by="group")
    assert chart["series_count"] == 2 and {trace["name"] for trace in chart["figure"]["data"]} == {"one", "two"}


@pytest.mark.parametrize("native", [False, True])
def test_series_limit_is_checked_before_aggregation_or_pivot(native, monkeypatch):
    store, params = source(pd.DataFrame({"x": ["a"] * 51, "group": [str(i) for i in range(51)], "y": [1] * 51}), native)
    def forbidden(*args, **kwargs):
        raise AssertionError("Too many series must fail before aggregation/pivot")
    monkeypatch.setattr(pd.DataFrame, "groupby", forbidden)
    monkeypatch.setattr(pl.DataFrame, "group_by", forbidden)
    with pytest.raises(ValueError, match="50 series"):
        preview(store, params, group_by="group")


@pytest.mark.parametrize("native", [False, True])
def test_million_row_wide_source_projects_then_aggregates_once(native, monkeypatch):
    count = 1_000_000
    frame = pd.DataFrame({"x": np.arange(count) % 4, "y": np.ones(count, dtype=np.int64), **{f"unused{i}": np.zeros(count) for i in range(10)}}, copy=False)
    store, params = source(frame, native)
    if native:
        def forbidden(*args, **kwargs):
            raise AssertionError("Native chart aggregation must not convert the source to pandas")
        monkeypatch.setattr(pl.DataFrame, "to_pandas", forbidden)
    else:
        original = pd.DataFrame.copy
        def narrow_copy(self, *args, **kwargs):
            assert len(self.columns) <= 2
            return original(self, *args, **kwargs)
        monkeypatch.setattr(pd.DataFrame, "copy", narrow_copy)
    chart = preview(store, params)
    assert chart["source_rows"] == count and chart["point_count"] == 4
    assert chart["figure"]["data"][0]["y"] == [250000] * 4


@pytest.mark.parametrize("native", [False, True])
def test_chart_uses_sorted_filtered_view_before_exact_selection(native):
    frame = pd.DataFrame({"x": ["a", "a", "b", "b"], "y": [1, 2, 3, 4], "unused": [9] * 4}, index=[1] * 4)
    store, params = source(frame, native)
    params.update({"filter": {"column": "y", "operator": "between", "value": "1.5", "value_to": "4"},
                   "sort": {"column": "y", "direction": "desc"},
                   "scope": {"row_ranges": [[0, 1]], "column_indices": [0, 1]}})
    chart = preview(store, params)
    assert chart["source_rows"] == 2 and chart["figure"]["data"][0]["customdata"] == [["b", "7"]]


def test_snapshot_export_and_restyle_use_shown_figure_after_source_changes(tmp_path, monkeypatch):
    store, params = source(pd.DataFrame({"x": ["a", "a"], "y": [1, 2]}))
    shown = preview(store, params, title="Before")
    store.frames[params["result_id"]].iloc[0, 1] = 99
    file = tmp_path / "shown.json"
    dispatch("result.chart_export", {"chart_id": shown["chart_id"], "path": str(file)}, {}, store)
    assert json.loads(file.read_text())["figure"] == shown["figure"]
    def forbidden(*args, **kwargs):
        raise AssertionError("A style change cannot reaggregate the source")
    monkeypatch.setattr(chart_runtime, "prepare", forbidden)
    styled = dispatch("result.chart", {"chart_id": shown["chart_id"], "config": {**shown["config"], "title": "After", "font_size": 20}}, {}, store)
    assert styled["figure"]["data"][0]["customdata"] == shown["figure"]["data"][0]["customdata"]
    assert styled["figure"]["layout"]["title"]["text"] == "After"
    assert styled["chart_id"] != shown["chart_id"]
    assert styled["geometry_approximate"] == shown["geometry_approximate"]
    with pytest.raises(ValueError, match="data configuration"):
        dispatch("result.chart", {"chart_id": shown["chart_id"], "config": {**shown["config"], "aggregation": "mean"}}, {}, store)


def test_snapshot_eviction_and_session_isolation_are_explicit(tmp_path):
    store, params = source(pd.DataFrame({"x": ["a"], "y": [1]}))
    first = preview(store, params)
    for i in range(8):
        preview(store, params, title=str(i))
    with pytest.raises(ValueError, match="expired"):
        dispatch("result.chart_export", {"chart_id": first["chart_id"], "path": str(tmp_path / "expired.json")}, {}, store)
    last = preview(store, params)
    with pytest.raises(ValueError, match="another session"):
        dispatch("result.chart_export", {"chart_id": last["chart_id"], "path": str(tmp_path / "other.json")}, {}, ResultStore(pd, pl))


def test_font_layout_extensions_are_clamped_without_changing_defaults():
    store, params = source(pd.DataFrame({"x": ["a"], "y": [1]}))
    chart = preview(store, params, font_family="Ubuntu", font_size=100, title_size=1, tick_size=100, hover_mode="closest")
    layout = chart["figure"]["layout"]
    assert layout["font"] == {"family": "Ubuntu", "size": 24, "color": "#d6dce8"}
    assert layout["title"]["font"]["size"] == 10 and layout["xaxis"]["tickfont"]["size"] == 20
    assert layout["hovermode"] == "closest"


@pytest.mark.parametrize("kind", ["bar", "line", "area", "scatter", "pie"])
def test_title_and_legend_use_separate_header_bands_in_snapshot_export(kind, tmp_path):
    store, params = source(pd.DataFrame({"x": ["a", "b"], "y": [1, 2]}))
    chart = preview(store, params, type=kind, title="Análise · 10 milhões", title_size=32, font_size=24)
    layout = chart["figure"]["layout"]
    assert layout["title"]["yref"] == "container"
    assert layout["title"]["y"] == 1 and layout["title"]["yanchor"] == "top"
    assert layout["legend"]["y"] == 1 and layout["legend"]["yanchor"] == "bottom"
    assert layout["margin"]["t"] >= 86
    assert layout["margin"]["t"] >= layout["title"]["font"]["size"] + layout["legend"]["font"]["size"] + 30
    destination = tmp_path / f"{kind}.json"
    dispatch("result.chart_export", {"chart_id": chart["chart_id"], "path": str(destination)}, {}, store)
    assert json.loads(destination.read_text(encoding="utf-8"))["figure"]["layout"] == layout


def test_native_nan_drop_matches_pandas_multi_y_drop():
    frame = pl.DataFrame({"x": ["a", "b"], "y": [float("nan"), 2.], "other": [7., 3.]})
    store = ResultStore(pd, pl)
    ref = store.register(frame, "frame")
    chart = dispatch("result.chart", {"result_id": ref["result_id"], "config": {"x_column": "x", "y_columns": ["y", "other"], "nulls": "drop"}}, {}, store)
    assert chart["point_count"] == 1 and chart["figure"]["data"][1]["customdata"] == [["b", "3.0"]]


@pytest.mark.parametrize("native", [False, True])
def test_normalization_and_recurring_decimal_mean_are_bounded_and_usable(native):
    store, params = source(pd.DataFrame({"x": ["a", "a", "a"], "y": [Decimal(1), Decimal(0), Decimal(0)], "second": [2, 2, 2]}), native)
    mean = preview(store, params, aggregation="mean")
    assert mean["figure"]["data"][0]["customdata"][0][1].startswith("0.333333333333333333333333333333")
    normalized = preview(store, params, y_columns=["y", "second"], normalize=True)
    values = [trace["y"][0] for trace in normalized["figure"]["data"]]
    assert sum(values) == pytest.approx(100)
    assert all(len(trace["customdata"][0][1]) < 100 for trace in normalized["figure"]["data"])


def test_snapshot_byte_budget_evicts_before_eight_figures(tmp_path):
    store, params = source(pd.DataFrame({"x": ["a"], "y": [1]}))
    first = preview(store, params, extra_private="a" * (9 * 1024 * 1024))
    second = preview(store, params, extra_private="b" * (9 * 1024 * 1024))
    with pytest.raises(ValueError, match="expired"):
        dispatch("result.chart_export", {"chart_id": first["chart_id"], "path": str(tmp_path / "first.json")}, {}, store)
    dispatch("result.chart_export", {"chart_id": second["chart_id"], "path": str(tmp_path / "second.json")}, {}, store)
    with pytest.raises(ValueError, match="16 MiB"):
        preview(store, params, extra_private="a" * (16 * 1024 * 1024))


@pytest.mark.parametrize("native", [False, True])
def test_x_and_pivot_cardinality_budgets_fail_before_aggregation(native, monkeypatch):
    store, params = source(pd.DataFrame({"x": range(100_001), "y": [1] * 100_001}), native)
    def forbidden(*args, **kwargs):
        raise AssertionError("Cardinality must be bounded before grouping")
    monkeypatch.setattr(pd.DataFrame, "groupby", forbidden)
    monkeypatch.setattr(pl.DataFrame, "group_by", forbidden)
    with pytest.raises(ValueError, match="100000"):
        preview(store, params)
    count = 21_000
    store, params = source(pd.DataFrame({"x": list(range(count)) * 2, "group": [str(i % 50) for i in range(count * 2)], "y": [1] * (count * 2)}), native)
    with pytest.raises(ValueError, match="one million pivot cells"):
        preview(store, params, group_by="group")


def test_real_protocol_exports_snapshot_after_source_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    client = Client()
    try:
        client.session("charts")
        finished = client.execute("frame = pl.DataFrame({'x': ['a', 'a'], 'y': [1, 2]})\nframe", session_id="charts")
        params = {"session_id": "charts", "result_id": finished["results"][0]["result_id"], "config": {"x_column": "x", "y_columns": ["y"]}}
        shown = client.request("result.chart", params)
        client.execute("frame = pl.DataFrame({'x': ['changed'], 'y': [99]})", execution_id="mutate", session_id="charts")
        file = tmp_path / "shown.json"
        exported = client.request("result.chart_export", {"session_id": "charts", "chart_id": shown["chart_id"], "path": str(file)})
        assert exported["chart_id"] == shown["chart_id"]
        assert json.loads(file.read_text())["figure"] == shown["figure"]
        styled = client.request("result.chart", {"session_id": "charts", "chart_id": shown["chart_id"], "config": {**shown["config"], "title": "Styled"}})
        assert styled["figure"]["data"][0]["customdata"] == [["a", "3"]]
    finally:
        client.close()


@pytest.mark.parametrize("native", [False, True])
def test_count_supports_nullable_categorical_values_and_x_as_y(native):
    frame = pd.DataFrame({"x": ["a", "a", "a"], "y": pd.Categorical(["one", None, "two"])})
    store, params = source(frame, native)
    assert preview(store, params, aggregation="count", nulls="zero")["figure"]["data"][0]["customdata"] == [["a", "3"]]
    assert preview(store, params, aggregation="count", nulls="keep")["figure"]["data"][0]["customdata"] == [["a", "2"]]
    store, params = source(pd.DataFrame({"x": [1, 1, 2], "y": [1, 2, 3]}), native)
    assert preview(store, params, y_columns=["x"])["figure"]["data"][0]["y"] == [2, 2]
    with pytest.raises(ValueError, match="different X"):
        preview(store, params, group_by="x")


def test_original_sort_and_none_alias_restyle_without_false_data_change():
    store, params = source(pd.DataFrame({"x": ["b", "a"], "y": [1, 2]}))
    shown = preview(store, params, sort="original")
    styled = dispatch("result.chart", {"chart_id": shown["chart_id"], "config": {**shown["config"], "sort": "none", "title": "Style"}}, {}, store)
    assert styled["figure"]["data"] == shown["figure"]["data"]


@pytest.mark.parametrize("native", [False, True])
def test_group_category_can_have_same_name_as_x_header(native):
    frame = pd.DataFrame({"x": ["a", "b"], "group": ["x", "__chart_pivot_index__"], "y": [1, 2]})
    store, params = source(frame, native)
    chart = preview(store, params, group_by="group")
    assert {trace["name"] for trace in chart["figure"]["data"]} == {"x", "__chart_pivot_index__"}


@pytest.mark.parametrize("value,dtype", [(2**126, pl.Int128), (Decimal("9" * 38), pl.Decimal(38, 0))])
def test_native_sum_promotes_before_int128_or_decimal128_overflow(value, dtype):
    frame = pl.DataFrame({"x": ["a"] * 3, "y": pl.Series([value] * 3, dtype=dtype)})
    store = ResultStore(pd, pl)
    ref = store.register(frame, "frame")
    chart = dispatch("result.chart", {"result_id": ref["result_id"], "config": {"x_column": "x", "y_columns": ["y"]}}, {}, store)
    assert chart["aggregation_engine"] == "pandas_exact"
    expected = str(int(value) * 3)
    assert chart["figure"]["data"][0]["customdata"] == [["a", expected]]
