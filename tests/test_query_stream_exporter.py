"""Tests for streaming SQL export (CSV / Parquet)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.database.query_stream_exporter import (
    CsvStreamWriter,
    ParquetStreamWriter,
    StreamExportResult,
    _arrow_table_rows,
    _csv_options_use_native_arrow,
    iter_rows_chunked,
    make_result_path,
    normalize_csv_options,
    stream_arrow_to_file,
    stream_result_set_to_file,
)


class MockCursor:
    def __init__(self, columns, rows, chunk_size=2):
        self.description = [(c,) for c in columns]
        self._rows = list(rows)
        self._chunk_size = chunk_size
        self._pos = 0

    def fetchmany(self, size):
        chunk = self._rows[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


class MockArrowCursor:
    """Simulates Databricks fetchmany_arrow batches."""

    def __init__(self, batches: list[pa.Table]):
        self._batches = list(batches)
        self._index = 0

    def fetchmany_arrow(self, size: int) -> pa.Table:
        if self._index >= len(self._batches):
            return pa.table({})
        batch = self._batches[self._index]
        self._index += 1
        if batch.num_rows <= size:
            return batch
        return batch.slice(0, size)


class TestStreamArrowToFile:
    def test_arrow_streaming_parquet(self, tmp_path):
        cursor = MockArrowCursor(
            [
                pa.table({"id": [1, 2], "val": [10, 20]}),
                pa.table({"id": [3], "val": [30]}),
            ]
        )
        path = tmp_path / "arrow.parquet"
        rows = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="parquet",
        )
        assert rows == 3
        assert pq.read_table(path).num_rows == 3

    def test_arrow_streaming_csv(self, tmp_path):
        cursor = MockArrowCursor([pa.table({"x": [1, 2], "y": ["a", "b"]})])
        path = tmp_path / "arrow.csv"
        rows = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="csv",
        )
        assert rows == 2
        text = path.read_text(encoding="utf-8-sig")
        assert "x" in text
        assert "a" in text

    def test_arrow_cancel_removes_partial_parquet(self, tmp_path):
        path = tmp_path / "cancel.parquet"
        cursor = MockArrowCursor([pa.table({"v": list(range(5))})])
        cancelled = {"v": False}

        def is_cancelled():
            if not cancelled["v"]:
                cancelled["v"] = True
                return False
            return True

        result = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="parquet",
            is_cancelled=is_cancelled,
        )
        assert result == -1
        assert not path.exists()

    def test_arrow_casts_mismatched_schema(self, tmp_path):
        path = tmp_path / "mixed.parquet"
        cursor = MockArrowCursor(
            [
                pa.table({"val": [1, 2]}),
                pa.table({"val": ["text"]}),
            ]
        )
        rows = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="parquet",
        )
        assert rows == 3
        df = pq.read_table(path).to_pandas()
        assert len(df) == 3
        assert str(df["val"].iloc[2]) == "text"

    def test_arrow_csv_with_default_csv_options_uses_native_path(self, tmp_path):
        """UI always passes csv_options; default decimal must avoid Python cell materialization."""
        opts = normalize_csv_options(
            {"delimiter": ",", "decimal": ".", "encoding": "utf-8-sig", "header": True}
        )
        assert _csv_options_use_native_arrow(opts) is True
        cursor = MockArrowCursor([pa.table({"id": [1, 2], "name": ["a", "b"]})])
        path = tmp_path / "native.csv"
        rows = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="csv",
            csv_options=opts,
        )
        assert rows == 2
        text = path.read_text(encoding="utf-8-sig")
        assert "id" in text and "name" in text
        assert "1" in text and "a" in text
        assert "2" in text and "b" in text

    def test_arrow_csv_custom_decimal_still_formats(self, tmp_path):
        opts = {"delimiter": ";", "decimal": ",", "encoding": "utf-8", "header": True}
        assert _csv_options_use_native_arrow(normalize_csv_options(opts)) is False
        cursor = MockArrowCursor([pa.table({"amount": [1.5, 2.25], "qty": [2, 3]})])
        path = tmp_path / "custom_arrow.csv"
        rows = stream_arrow_to_file(
            cursor.fetchmany_arrow,
            path=path,
            export_format="csv",
            csv_options=opts,
        )
        assert rows == 2
        content = path.read_text(encoding="utf-8")
        assert "1,5;2" in content
        assert "2,25;3" in content

    def test_arrow_table_rows_column_oriented(self):
        table = pa.table({"a": [1, 2], "b": ["x", "y"]})
        assert _arrow_table_rows(table) == [[1, "x"], [2, "y"]]


class TestIterRowsChunked:
    def test_yields_all_rows_in_chunks(self):
        cursor = MockCursor(["a", "b"], [(1, 2), (3, 4), (5, 6)], chunk_size=2)
        chunks = list(iter_rows_chunked(cursor, chunk_size=2))
        assert len(chunks) == 2
        assert chunks[0] == (["a", "b"], [(1, 2), (3, 4)])
        assert chunks[1] == (["a", "b"], [(5, 6)])


class TestMakeResultPath:
    def test_single_file_uses_base_suffix(self, tmp_path):
        p = make_result_path(tmp_path / "out.csv", 1, "csv")
        assert p.name == "out.csv"

    def test_multiple_files_get_suffix(self, tmp_path):
        p = make_result_path(tmp_path / "data.parquet", 2, "parquet")
        assert p.name == "data_2.parquet"


class TestCsvStreamWriter:
    def test_writes_header_and_rows(self, tmp_path):
        path = tmp_path / "test.csv"
        writer = CsvStreamWriter(path)
        writer.write_header(["id", "name"])
        writer.write_chunk([(1, "alice"), (2, "bob")])
        writer.close()
        text = path.read_text(encoding="utf-8-sig")
        assert "id,name" in text
        assert "alice" in text

    def test_abort_removes_file(self, tmp_path):
        path = tmp_path / "partial.csv"
        writer = CsvStreamWriter(path)
        writer.write_header(["x"])
        writer.abort()
        assert not path.exists()


class TestParquetStreamWriter:
    def test_writes_row_groups(self, tmp_path):
        path = tmp_path / "test.parquet"
        writer = ParquetStreamWriter(path)
        writer.write_header(["id", "val"])
        writer.write_chunk(["id", "val"], [(1, 10), (2, 20)])
        writer.write_chunk(["id", "val"], [(3, 30)])
        writer.close()
        table = pq.read_table(path)
        assert table.num_rows == 3
        assert table.column("id").to_pylist() == [1, 2, 3]


class TestStreamResultSetToFile:
    def test_csv_streaming(self, tmp_path):
        cursor = MockCursor(["x"], [(1,), (2,), (3,)], chunk_size=2)
        path = tmp_path / "stream.csv"
        rows = stream_result_set_to_file(
            ["x"],
            iter_rows_chunked(cursor, chunk_size=2),
            path=path,
            export_format="csv",
        )
        assert rows == 3
        assert path.read_text(encoding="utf-8-sig").count("\n") >= 3

    def test_csv_stream_writer_uses_separator_and_decimal(self, tmp_path):
        cursor = MockCursor(["amount", "qty"], [(1.5, 2), (2.25, 3)], chunk_size=2)
        path = tmp_path / "custom.csv"
        rows = stream_result_set_to_file(
            ["amount", "qty"],
            iter_rows_chunked(cursor, chunk_size=2),
            path=path,
            export_format="csv",
            csv_options={"delimiter": ";", "decimal": ",", "encoding": "utf-8", "header": True},
        )
        assert rows == 2
        content = path.read_text(encoding="utf-8")
        assert content.startswith("amount;qty")
        assert "1,5;2" in content
        assert "2,25;3" in content

    def test_parquet_streaming(self, tmp_path):
        cursor = MockCursor(["n"], [(1,), (2,)], chunk_size=1)
        path = tmp_path / "stream.parquet"
        rows = stream_result_set_to_file(
            ["n"],
            iter_rows_chunked(cursor, chunk_size=1),
            path=path,
            export_format="parquet",
        )
        assert rows == 2
        assert pq.read_table(path).num_rows == 2

    def test_cancel_removes_partial_csv(self, tmp_path):
        path = tmp_path / "cancel.csv"

        def big_iter():
            cols = ["v"]
            for i in range(5):
                yield cols, [(i,)]

        cancelled = {"v": False}

        def is_cancelled():
            if not cancelled["v"]:
                cancelled["v"] = True
                return False
            return True

        result = stream_result_set_to_file(
            ["v"],
            big_iter(),
            path=path,
            export_format="csv",
            is_cancelled=is_cancelled,
        )
        assert result == -1
        assert not path.exists()

    def test_empty_result_writes_header_only(self, tmp_path):
        path = tmp_path / "empty.csv"
        rows = stream_result_set_to_file(
            ["a", "b"],
            iter([]),
            path=path,
            export_format="csv",
        )
        assert rows == 0
        content = path.read_text(encoding="utf-8-sig").strip()
        assert content == "a,b"

    def test_parquet_stable_schema_across_chunks(self, tmp_path):
        path = tmp_path / "mixed.parquet"

        def mixed_iter():
            yield ["val"], [(1,), (2,)]
            yield ["val"], [("text",)]

        rows = stream_result_set_to_file(
            ["val"],
            mixed_iter(),
            path=path,
            export_format="parquet",
        )
        assert rows == 3
        df = pq.read_table(path).to_pandas()
        assert len(df) == 3

    def test_parquet_all_null_column_then_real_values(self, tmp_path):
        """A column entirely NULL in the first chunk must not crash with
        'Invalid null value' when real values arrive in later chunks."""
        path = tmp_path / "nulls.parquet"

        def iter_chunks():
            yield ["x", "y"], [(None, 1), (None, 2)]
            yield ["x", "y"], [("a", 3), (None, 4)]

        rows = stream_result_set_to_file(
            ["x", "y"],
            iter_chunks(),
            path=path,
            export_format="parquet",
        )
        assert rows == 4
        df = pq.read_table(path).to_pandas()
        assert len(df) == 4
        assert list(df["y"]) == [1, 2, 3, 4]

    def test_parquet_all_null_column_end_to_end(self, tmp_path):
        """A column that stays entirely NULL across all chunks writes fine."""
        path = tmp_path / "allnull.parquet"

        def iter_chunks():
            yield ["x", "y"], [(None, 1), (None, 2)]
            yield ["x", "y"], [(None, 3)]

        rows = stream_result_set_to_file(
            ["x", "y"],
            iter_chunks(),
            path=path,
            export_format="parquet",
        )
        assert rows == 3
        df = pq.read_table(path).to_pandas()
        assert list(df["y"]) == [1, 2, 3]
        assert all(v is None for v in df["x"])


class TestGilYield:
    def test_gil_yield_after_chunk(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        import src.database.query_stream_exporter as mod

        yields = []
        monkeypatch.setattr(mod, "_gil_yield", lambda: yields.append(1))

        cursor = MockCursor(["x"], [(1,), (2,)], chunk_size=2)
        path = tmp_path / "y.csv"
        mod.stream_result_set_to_file(
            ["x"],
            mod.iter_rows_chunked(cursor, chunk_size=2),
            path=path,
            export_format="csv",
        )
        assert len(yields) >= 1
