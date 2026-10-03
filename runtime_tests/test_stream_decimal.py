"""Cursor and Arrow downloads preserve SQL Decimal without IEEE-754 rounding."""

from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.database.query_stream_exporter import (
    STREAM_EXPORT_CHUNK_ROWS, ParquetStreamWriter, stream_arrow_to_file, stream_result_set_to_file,
)


def test_cursor_decimal_multichunk_scale_upgrade_roundtrips_and_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "cursor.parquet"
    first = Decimal("1234567890123456789012345678.1234567890")
    later = Decimal("1234567890123456789012345678.12345678901234567890")
    # Fail if the upgrade tries to read the entire previous download.
    original_read = pq.read_table
    monkeypatch.setattr(pq, "read_table", lambda *args, **kwargs: pytest.fail("Full-table schema rewrite"))
    writer = ParquetStreamWriter(path)
    writer.write_chunk(["amount"], [(first,)] * (STREAM_EXPORT_CHUNK_ROWS * 2 + 7))
    writer.write_chunk(["amount"], [(None,), (later,)])
    writer.write_chunk(["amount"], [(None,)])
    writer.close()
    table = original_read(path)
    assert pa.types.is_decimal256(table.schema.field("amount").type)
    values = table.column("amount").to_pylist()
    assert values[0] == first
    assert values[STREAM_EXPORT_CHUNK_ROWS * 2 + 6] == first
    assert values[-3:] == [None, later, None]
    assert pq.ParquetFile(path).num_row_groups >= 4
    assert not list(tmp_path.glob("*-upgrade-*.parquet"))


def test_integer_then_decimal_keeps_each_original_digit(tmp_path):
    path = tmp_path / "integer-decimal.parquet"
    exact = 2**60 + 3
    fraction = Decimal("1152921504606846979.00000000000001")
    count = stream_result_set_to_file(["amount"], iter([(["amount"], [(exact,)]), (["amount"], [(fraction,)])]), path=path, export_format="parquet")
    assert count == 2
    assert pq.read_table(path).column("amount").to_pylist() == [Decimal(exact), fraction]


def test_float_mixed_with_decimal_uses_lossless_text_fallback(tmp_path):
    path = tmp_path / "mixed.parquet"
    exact = Decimal("123456789012345678901234567890.123456")
    stream_result_set_to_file(["amount"], iter([(["amount"], [(exact,)]), (["amount"], [(1.5,)]), (["amount"], [(2.5,)])]), path=path, export_format="parquet")
    table = pq.read_table(path)
    assert pa.types.is_string(table.schema.field("amount").type)
    assert table.column("amount").to_pylist() == [str(exact), "1.5", "2.5"]


def test_arrow_decimal_schema_widens_without_rounding(tmp_path):
    path = tmp_path / "arrow.parquet"
    values = [Decimal("123456789012345678901234567890.12"), Decimal("123456789012345678901234567890.123456789012")]
    batches = iter([pa.table({"amount": [values[0]]}), pa.table({"amount": [values[1]]}), None])
    assert stream_arrow_to_file(lambda _: next(batches), path=path, export_format="parquet") == 2
    assert pq.read_table(path).column("amount").to_pylist() == values


def test_cancel_during_cursor_schema_upgrade_removes_all_stages(tmp_path, monkeypatch):
    path = tmp_path / "cancel.parquet"
    checks = 0
    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 3
    chunks = iter([(["amount"], [(Decimal("1.2"),)] * 10001), (["amount"], [(Decimal("1.23456789"),)])])
    assert stream_result_set_to_file(["amount"], chunks, path=path, export_format="parquet", is_cancelled=cancelled) == -1
    assert not path.exists()
    assert not list(tmp_path.glob("*-upgrade-*.parquet"))
