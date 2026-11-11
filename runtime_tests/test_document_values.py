from datetime import datetime, timezone
from decimal import Decimal
import io
import json

from bson import Decimal128, Int64, ObjectId
import pandas as pd
import pytest

from datapyn_runtime.export_formats import write_file, write_text
from datapyn_runtime.values import document_json, scalar


class Control:
    def check(self):
        pass

    def advance(self, count):
        pass


def test_grid_nested_documents_are_json_without_mutating_frame_values():
    document = {"name": "Árvore", "ids": [1, 2], "info": {"ok": True, "nothing": None}}
    value = scalar(document)
    assert json.loads(value) == document
    assert 'Árvore' in value and "'name'" not in value
    assert isinstance(document["info"], dict)


def test_nested_ejson_preserves_bson_types_and_precision():
    oid = ObjectId("0123456789abcdef01234567")
    value = json.loads(document_json({"oid": oid, "amount": Decimal128("1234567890123456.123456789"),
                                     "integer": Int64(2**60 + 3), "decimal": Decimal("1.2300"),
                                     "nan": float("nan"), "when": datetime(2026, 11, 11, tzinfo=timezone.utc)}))
    assert value["oid"] == {"$oid": str(oid)}
    assert value["integer"] == {"$numberLong": str(2**60 + 3)}
    assert value["amount"] == {"$numberDecimal": "1234567890123456.123456789"}
    assert value["decimal"] == {"$numberDecimal": "1.2300"}
    assert value["nan"] == {"$numberDouble": "NaN"}
    assert value["when"] == {"$date": "2026-11-11T00:00:00+00:00"}


@pytest.mark.parametrize("orient", ["records", "split", "values", "index", "columns", "table"])
def test_export_json_keeps_structure_for_every_orientation(orient):
    frame = pd.DataFrame({"document": [{"a": [1, {"b": True}]}], "name": ["text"]})
    output = io.StringIO()
    write_text(frame, output, "json", {"orient": orient}, Control())
    exported = json.loads(output.getvalue())
    if orient == "records":
        cell = exported[0]["document"]
    elif orient == "index":
        cell = exported["0"]["document"]
    elif orient == "columns":
        cell = exported["document"]["0"]
    elif orient == "table":
        cell = exported["data"][0]["document"]
    elif orient == "split":
        cell = exported["data"][0][0]
    else:
        cell = exported[0][0]
    assert cell == {"a": [1, {"b": True}]}


def test_csv_compounds_are_json_and_scalar_sql_types_remain_native():
    frame = pd.DataFrame({"document": [{"a": [1, 2]}], "number": [Decimal("2.50")]})
    output = io.StringIO()
    write_text(frame, output, "csv", {"delimiter": ";"}, Control())
    exported = pd.read_csv(io.StringIO(output.getvalue()), sep=";", dtype=str)
    assert json.loads(exported.loc[0, "document"]) == {"a": [1, 2]}
    assert exported.loc[0, "number"] == "2.50"
    assert isinstance(frame.loc[0, "document"], dict)


def test_json_document_frame_uses_ejson_without_losing_bson_decimal_type():
    frame = pd.DataFrame({"amount": [Decimal("123456789012345.1200")]}, dtype=object)
    frame.attrs["datapyn_document_result"] = True
    output = io.StringIO()
    write_text(frame, output, "json", {}, Control())
    assert json.loads(output.getvalue())[0]["amount"] == {"$numberDecimal": "123456789012345.1200"}


def test_circular_values_have_a_clear_error_instead_of_recursing():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="Circular"):
        document_json(value)


def test_parquet_document_columns_have_lossless_encoding_and_native_scalars(tmp_path):
    import pyarrow.parquet as pq
    oid = ObjectId("0123456789abcdef01234567")
    frame = pd.DataFrame({"id": [oid, oid], "nested": [{"a": [1, 2]}, {"a": [3]}],
                          "mixed": [2**60 + 3, "text"], "number": [1, 2],
                          "amount": [Decimal("2.500"), Decimal("3.125")]}, dtype=object)
    frame.attrs["datapyn_document_result"] = True
    path = tmp_path / "documents.parquet"
    write_file(frame, path, "parquet", {}, Control())
    table = pq.read_table(path)
    assert table.column("number").to_pylist() == [1, 2]
    assert table.column("amount").to_pylist() == [Decimal("2.500"), Decimal("3.125")]
    assert json.loads(table.column("id")[0].as_py()) == {"$oid": str(oid)}
    assert json.loads(table.column("nested")[0].as_py()) == {"a": [1, 2]}
    assert json.loads(table.column("mixed")[0].as_py()) == {"$numberLong": str(2**60 + 3)}
    assert table.schema.field("nested").metadata[b"datapyn.encoding"] == b"extended-json"
    assert isinstance(frame.loc[0, "id"], ObjectId)


def test_parquet_document_type_inference_sees_late_values(tmp_path):
    import pyarrow.parquet as pq
    frame = pd.DataFrame({"amount": [None] * 100_001 + [Decimal("4.12345")]}, dtype=object)
    frame.attrs["datapyn_document_result"] = True
    path = tmp_path / "late.parquet"
    write_file(frame, path, "parquet", {}, Control())
    assert pq.read_table(path).column("amount")[-1].as_py() == Decimal("4.12345")


def test_document_grid_filter_and_sort_use_the_json_shown_in_cells():
    import polars as pl
    from datapyn_runtime.result_store import ResultStore
    frame = pd.DataFrame({"data": [{"a": 2}, {"a": 1}, None]}, dtype=object)
    frame.attrs["datapyn_document_result"] = True
    store = ResultStore(pd, pl)
    result = store.register(frame, "data")
    request = {"result_id": result["result_id"]}
    assert store.page({**request, "filter": {"column": "data", "value": '"a":1'}})["rows"] == [['{"a":1}']]
    assert store.page({**request, "filter": {"text": '"a":2'}})["rows"] == [['{"a":2}']]
    assert store.page({**request, "sort": {"column": "data", "direction": "asc"}})["rows"] == [['{"a":1}'], ['{"a":2}'], [None]]
    assert isinstance(frame.loc[0, "data"], dict)
