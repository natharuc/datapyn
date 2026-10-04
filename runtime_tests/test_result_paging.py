"""Viewport projection, positional generations and native large frame ownership."""

from decimal import Decimal
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest

from datapyn_runtime.kernel import ResultStore
from datapyn_runtime import result_store, frame_view
from datapyn_runtime.data_tools import dispatch


def store_for(frame):
    store = ResultStore(pd, pl)
    return store, store.register(frame, "frame")["result_id"]


@pytest.mark.parametrize("native", [False, True])
def test_projected_page_is_exact_tile_without_repeated_descriptors(native):
    frame = pd.DataFrame(np.arange(120).reshape(10, 12), columns=[str(i) for i in range(12)])
    store, identifier = store_for(pl.from_pandas(frame) if native else frame)
    params = {"result_id": identifier, "offset": 4, "limit": 3, "column_offset": 7, "column_limit": 2}
    page = store.page(params)
    assert page["rows"] == [[55, 56], [67, 68], [79, 80]]
    assert [column["name"] for column in page["columns"]] == ["7", "8"]
    assert page["total_rows"] == 10 and page["total_columns"] == 12 and page["column_offset"] == 7
    minimal = store.page({**params, "include_columns": False})
    assert minimal["columns"] == [] and minimal["rows"] == page["rows"]
    default = store.page({"result_id": identifier, "limit": 2})
    assert len(default["columns"]) == 12 and "total_columns" not in default


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_native_views_share_stable_sort_nulls_filters_and_exact_values(native, direction):
    frame = pd.DataFrame({"key": [2., None, 1., 2., float("nan")], "big": [2**60+i for i in range(5)], "text": ["straße", "Other", "STRASSE", "straße", "last"]}, index=[2,2,1,1,2])
    store, identifier = store_for(pl.from_pandas(frame) if native else frame)
    params = {"result_id": identifier, "filter": {"text": "STRASSE"}, "sort": {"column": "key", "direction": direction}}
    expected = [2,0,3] if direction == "asc" else [0,3,2]
    assert [row[1] for row in store.page(params)["rows"]] == [str(2**60+i) for i in expected]
    nulls = store.page({"result_id": identifier, "filter": {"column": "key", "operator": "is_null"}})
    assert [row[1] for row in nulls["rows"]] == [str(2**60+1), str(2**60+4)]
    view = store.view(params)
    assert [str(item) for item in view["big"]] == [str(2**60+i) for i in expected]


def test_large_sorted_frame_caches_positions_once_for_last_page_and_export(monkeypatch):
    count = 10_000_000
    values = np.arange(count, 0, -1, dtype=np.int64)
    frame = pd.DataFrame({name: values for name in ("key", "b", "c", "d")}, copy=False)
    assert frame.memory_usage(index=True, deep=False).sum() > result_store.MAX_VIEW_BYTES
    store, identifier = store_for(frame)
    calls = []
    original = pd.DataFrame.sort_values
    def narrow_sort(self, *args, **kwargs):
        assert len(self.columns) <= 2, "Sorting must never copy the entire wide source frame"
        calls.append(self.shape)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, "sort_values", narrow_sort)
    params = {"result_id": identifier, "sort": {"column": "key"}, "column_offset": 2, "column_limit": 1, "include_columns": False}
    page = store.page({**params, "offset": count-200, "limit": 200})
    assert page["rows"][0] == [count-199] and page["rows"][-1] == [count]
    for offset in (0, 7000000, count-1):
        assert store.page({**params, "offset": offset, "limit": 1})["rows"] == [[offset+1]]
    assert len(calls) == 1 and store.view_bytes == count*4
    assert store.frames[identifier] is frame
    positions = next(iter(store.views.values()))[0]
    assert positions.dtype == np.uint32 and positions.flags.owndata


def test_polars_register_and_page_never_convert_full_frame_to_pandas(monkeypatch):
    frame = pl.DataFrame({"value": range(1_000_000), "nullable": pl.Series([2**63+1, None],dtype=pl.UInt64).extend_constant(None, 999998)})
    def forbidden(*args, **kwargs):
        raise AssertionError("Viewport operations must stay native")
    monkeypatch.setattr(pl.DataFrame, "to_pandas", forbidden)
    store, identifier = store_for(frame)
    assert store.frames[identifier] is frame
    page = store.page({"result_id": identifier, "offset": 0, "limit": 2, "column_offset": 1, "column_limit": 1})
    assert page["rows"] == [[str(2**63+1)], [None]]
    page = store.page({"result_id": identifier, "offset": 999999, "limit": 200})
    assert page["rows"] == [[999999, None]]


def test_native_polars_decimal_uint64_export_view_preserves_precision():
    frame = pl.DataFrame({"big": pl.Series([2**63+1,None], dtype=pl.UInt64), "decimal": pl.Series([Decimal("1.234567890123456789"), None], dtype=pl.Decimal(38,18))})
    store, identifier = store_for(frame)
    page = store.page({"result_id": identifier})
    assert page["rows"] == [[str(2**63+1), "1.234567890123456789"], [None,None]]
    output = dispatch("result.export_text", {"result_id": identifier, "format": "json"}, {}, store)
    assert json.loads(output["text"]) == [{"big":str(2**63+1),"decimal":"1.234567890123456789"},{"big":None,"decimal":None}]


def test_filtered_view_cache_uses_positions_and_duplicate_index_never_expands_rows(monkeypatch):
    frame = pd.DataFrame({"key":[3,1,3,2],"decimal":[Decimal("1.000000000000000001")]*4}, index=[1,1,1,1])
    store, identifier = store_for(frame)
    calls = []
    original = frame_view.pandas_positions
    def tracked(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(frame_view,"pandas_positions",tracked)
    params={"result_id":identifier,"filter":{"column":"key","operator":"gte","value":"2"},"sort":{"column":"key"}}
    assert store.page(params)["rows"] == [[2,"1.000000000000000001"],[3,"1.000000000000000001"],[3,"1.000000000000000001"]]
    assert len(store.view(params)) == 3 and len(calls) == 1
    frame.iloc[1,0]=5
    store.invalidate_views()
    assert store.page(params)["total_rows"] == 4 and len(calls) == 2
    store.release(identifier)
    assert not store.views and store.view_bytes == 0


@pytest.mark.parametrize("params",[{"column_offset":True},{"column_offset":-1},{"column_limit":0},{"column_limit":257},{"include_columns":"false"},{"column_offset":5}])
def test_projection_bounds_are_explicit(params):
    store,identifier=store_for(pd.DataFrame({"a":[1]}))
    with pytest.raises(ValueError):
        store.page({"result_id":identifier,**params})


def test_index_budget_is_explicit_instead_of_recomputing_uncacheable_view(monkeypatch):
    store,identifier=store_for(pd.DataFrame({"a":range(10)}))
    monkeypatch.setattr(result_store,"MAX_VIEW_BYTES",16)
    original=frame_view.pandas_positions;calls=[]
    def tracked(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(frame_view,"pandas_positions",tracked)
    for _ in range(2):
        with pytest.raises(ValueError,match="refine the filter"):
            store.page({"result_id":identifier,"sort":{"column":"a"}})
    assert calls == [1]
    assert not store.views


@pytest.mark.parametrize("value",["x"*(8*1024*1024+1),b"x"*(4*1024*1024+1)],ids=["text","binary"])
def test_giant_single_cell_is_explicit_error_without_truncating_original(value):
    frame=pd.DataFrame({"value":[value]});store,identifier=store_for(frame)
    with pytest.raises(ValueError,match="8 MiB"):
        store.page({"result_id":identifier,"column_limit":1})
    assert frame.iloc[0,0] is value


@pytest.mark.parametrize("spec",[{"text":"nan"},{"column":"value","operator":"contains","value":"nan"}])
def test_polars_nan_text_filters_match_pandas_missing_semantics(spec):
    native=pl.DataFrame({"value":[float("nan"),None,1.0]})
    store,identifier=store_for(native)
    assert store.page({"result_id":identifier,"filter":spec})["rows"] == []


def test_polars_nanosecond_timestamp_page_preserves_precision(monkeypatch):
    frame=pl.DataFrame({"time":pl.Series([1_700_000_000_123_456_789],dtype=pl.Int64).cast(pl.Datetime("ns"))})
    store,identifier=store_for(frame)
    calls=[];original=pl.DataFrame.to_pandas
    def bounded(self,*args,**kwargs):
        calls.append(self.shape)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(pl.DataFrame,"to_pandas",bounded)
    page=store.page({"result_id":identifier})
    assert page["rows"][0][0].endswith(".123456789")
    assert calls == [(1,1)]


@pytest.mark.parametrize("layout",["fragmented","consolidated"])
def test_paging_never_consolidates_full_source_columns(layout,monkeypatch):
    values=np.arange(100000,dtype=np.int64)
    frame=pd.DataFrame({str(index):values for index in range(8)},copy=False) if layout=="fragmented" else pd.DataFrame(np.repeat(values[:,None],8,axis=1))
    store,identifier=store_for(frame)
    original=pd.DataFrame.__init__;allocations=[]
    def bounded(self,*args,**kwargs):
        original(self,*args,**kwargs)
        allocations.append(self.shape)
        assert len(self) <=200,"A viewport must never construct a full-length column projection"
    monkeypatch.setattr(pd.DataFrame,"__init__",bounded)
    page=store.page({"result_id":identifier,"offset":99900,"limit":100,"column_offset":3,"column_limit":2})
    assert page["rows"][0] == [99900,99900] and page["rows"][-1] == [99999,99999]
    assert allocations == [(100,2)]


def test_array_viewport_preserves_mixed_extensions_and_duplicate_column_labels():
    frame=pd.concat([pd.Series([2**63+1,None],dtype="UInt64"),pd.Series(pd.to_datetime(["2026-01-01T00:00:00.123456789",None])),pd.Series(["ação",pd.NA],dtype="string")],axis=1)
    frame.columns=["same","same","text"]
    store,identifier=store_for(frame)
    page=store.page({"result_id":identifier,"limit":2,"column_limit":3})
    assert page["rows"] == [[str(2**63+1),"2026-01-01T00:00:00.123456789","ação"],[None,None,None]]
    assert [column["name"] for column in page["columns"]] == ["same","same","text"]
