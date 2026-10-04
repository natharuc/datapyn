"""Parquet persistence must not turn nullable integer values into floats."""

from decimal import Decimal
import json

import pandas as pd
import polars as pl
from polars.testing import assert_frame_equal, assert_series_equal
import pyarrow.parquet as parquet
import pytest

from datapyn_runtime.result_store import ResultStore
from datapyn_runtime import variable_snapshot as snapshot
from test_runtime import Client


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    snapshot.settings_set({"settings": {"enabled": True, "restore_on_startup": True, "max_size_mb": 50}})
    return ResultStore(pd, pl)


def roundtrip(store, namespace):
    saved = snapshot.save({"session_id": "precision"}, namespace, store)
    assert saved["saved"] and not saved["skipped"]
    restored = {}
    result = snapshot.restore({"session_id": "precision"}, restored, store)
    return saved, restored, result


def test_nullable_object_bigints_remain_exact_after_parquet_restore_and_resave(isolated):
    frame = pd.DataFrame({"large": pd.Series([None] * 250 + [2**53 + 1, 2] * 25, dtype=object)})
    saved, restored, result = roundtrip(isolated, {"late": frame})
    path, _ = snapshot._current("precision")
    on_disk = parquet.read_table(path / saved["variables"][0]["file"])
    # This pinpoints the original bug: the Parquet bytes were already correct.
    assert on_disk["large"][250].as_py() == 2**53 + 1
    pd.testing.assert_frame_equal(frame, restored["late"])
    page = isolated.page({"result_id": result["results"][0]["result_id"], "offset": 250, "limit": 2})
    assert page["rows"] == [[str(2**53 + 1)], [2]]
    _, again, _ = roundtrip(isolated, restored)
    pd.testing.assert_frame_equal(frame, again["late"])


def test_pandas_nullable_dtypes_index_decimal_and_ns_survive(isolated):
    frame = pd.DataFrame({
        "signed": pd.Series([None, 2**53 + 1, -2**53 - 1], dtype="Int64"),
        "unsigned": pd.Series([2**63 + 1, None, 2**64 - 1], dtype="UInt64"),
        "decimal": [Decimal("1.234567890123456789"), None, Decimal("9.000000000000000001")],
        "date": pd.to_datetime(["2026-10-04T01:02:03.123456789Z", None, "2026-10-05T00:00:00Z"], format="ISO8601"),
        "float": [1.25, None, 3.5],
    })
    frame.index = pd.MultiIndex.from_tuples([(1, "same"), (1, "same"), (2, "last")], names=["id", "group"])
    _, restored, _ = roundtrip(isolated, {"frame": frame})
    pd.testing.assert_frame_equal(frame, restored["frame"])


def test_pandas_series_and_nullable_bigint_index_preserve_precision(isolated):
    index = pd.Index([None, 2**53 + 1, None], dtype=object, name="identifier")
    series = pd.Series([None, 2**53 + 3, 7], dtype=object, index=index, name="original")
    _, restored, _ = roundtrip(isolated, {"series": series})
    pd.testing.assert_series_equal(series, restored["series"])


def test_nullable_object_multiindex_levels_and_integer_extension_index_remain_exact(isolated):
    object_index = pd.Index([None, 2**53 + 1, None], dtype=object)
    multi = pd.MultiIndex.from_arrays([object_index, ["same", "same", "last"]], names=["identifier", "group"])
    extension = pd.Index(pd.array([None, 2**53 + 1, None], dtype="Int64"), name="identifier")
    namespace = {"multi": pd.DataFrame({"amount": [7, 8, 9]}, index=multi),
                 "extension": pd.DataFrame({"amount": [7, 8, 9]}, index=extension)}
    _, restored, _ = roundtrip(isolated, namespace)
    for name, original in namespace.items():
        pd.testing.assert_frame_equal(original, restored[name])


def test_native_polars_snapshot_never_converts_nullable_numbers_to_pandas(isolated, monkeypatch):
    frame = pl.DataFrame({
        "unsigned": pl.Series([None, 2**63 + 1, 2**64 - 1], dtype=pl.UInt64),
        "amount": pl.Series([Decimal("1.234567890123456789"), None, Decimal("9.000000000000000001")], dtype=pl.Decimal(38, 18)),
        "when": pl.from_pandas(pd.Series(pd.to_datetime(["2026-10-04T01:02:03.123456789Z", None, "2026-10-05T00:00:00Z"], format="ISO8601"))),
    })
    def forbidden(*args, **kwargs):
        raise AssertionError("Native snapshot cannot convert full frames to pandas")
    monkeypatch.setattr(pl.DataFrame, "to_pandas", forbidden)
    saved, restored, result = roundtrip(isolated, {"polar": frame})
    assert saved["variables"][0]["storage"] == "polars"
    assert_frame_equal(frame, restored["polar"])
    page = isolated.page({"result_id": result["results"][0]["result_id"], "offset": 1, "limit": 1, "column_limit": 1})
    assert page["rows"] == [[str(2**63 + 1)]]


@pytest.mark.parametrize("series", [
    pl.Series("large", [None, 2**63 + 1], dtype=pl.UInt64),
    pl.Series("amount", [None, Decimal("1.234567890123456789")], dtype=pl.Decimal(38, 18)),
])
def test_native_polars_series_preserves_name_dtype_and_values(isolated, series):
    _, restored, _ = roundtrip(isolated, {"series": series})
    assert_series_equal(series, restored["series"])


@pytest.mark.parametrize("kind", ["pandas_frame", "polars_frame", "polars_series"])
@pytest.mark.parametrize("dtype,big", [("UInt64", 2**63 + 1), (object, 2**53 + 1)])
def test_legacy_v1_pandas_encoded_snapshots_restore_exact_nullable_integers(isolated, kind, dtype, big):
    frame = pd.DataFrame({"large": pd.Series([None, big], dtype=dtype)}, index=pd.Index([0, 1], name="old_index"))
    snapshot.save({"session_id": "precision"}, {"legacy": frame}, isolated)
    path, manifest = snapshot._current("precision")
    manifest["version"] = 1
    manifest["variables"][0]["kind"] = kind
    manifest["variables"][0].pop("storage")
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    restored = {}
    snapshot.restore({"session_id": "precision"}, restored, isolated)
    value = restored["legacy"]
    if kind == "pandas_frame":
        pd.testing.assert_frame_equal(frame, value)
    elif kind == "polars_frame":
        assert_frame_equal(value, pl.DataFrame({"large": pl.Series([None, big], dtype=pl.UInt64 if dtype == "UInt64" else pl.Int64)}))
    else:
        assert_series_equal(value, pl.Series("large", [None, big], dtype=pl.UInt64 if dtype == "UInt64" else pl.Int64))


def test_restart_restores_late_nullable_object_values_without_precision_loss(isolated):
    client = Client()
    try:
        client.session("late-precision")
        client.event("namespace.changed", session_id="late-precision")
        code = "late = pd.DataFrame({'large': pd.Series([None]*250 + [9007199254740993, 2]*25, dtype=object)})\nlate"
        finished = client.execute(code, session_id="late-precision")
        assert client.page(finished, session_id="late-precision", offset=250, limit=2)["rows"] == [["9007199254740993"], [2]]
        client.request("session.close", {"session_id": "late-precision"})
        client.session("late-precision")
        restored = client.event("namespace.changed", session_id="late-precision")
        ref = next(item for item in restored["results"] if item["variable_name"] == "late")
        params = {"session_id": "late-precision", "result_id": ref["result_id"]}
        assert client.request("result.page", {**params, "offset": 250, "limit": 2})["rows"] == [["9007199254740993"], [2]]
        assert client.request("result.column_values", {**params, "column": "large"})["values"] == ["9007199254740993", 2]
        view = {**params, "filter": {"column": "large", "operator": "between", "value": "9007199254740993", "value_to": "9007199254740993"}}
        assert client.request("result.page", view)["total_rows"] == 25
    finally:
        client.close()
