"""
Stream SQL result sets directly to CSV or Parquet without materializing full DataFrames.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Sequence

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from src.core.session_result_storage import PARQUET_COMPRESSION

STREAM_EXPORT_CHUNK_ROWS = 5_000
STREAM_ARROW_CHUNK_ROWS = 5_000
STREAM_ARROW_ROW_GROUP_ROWS = 50_000
CSV_YIELD_EVERY_ROWS = 1_000


def normalize_csv_options(csv_options: dict | None) -> dict[str, Any]:
    opts = csv_options or {}
    return {
        "sep": opts.get("sep", opts.get("delimiter", ",")),
        "decimal": opts.get("decimal", "."),
        "encoding": opts.get("encoding", "utf-8-sig"),
        "header": opts.get("header", True),
    }


def _csv_cell(value: Any, *, decimal: str = ".") -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    if isinstance(value, float):
        text = str(value)
        if decimal != ".":
            return text.replace(".", decimal)
        return text
    if isinstance(value, Decimal):
        text = str(value)
        if decimal != ".":
            return text.replace(".", decimal)
        return text
    return str(value)


class CsvStreamWriter:
    """Append row chunks to a CSV file with configurable delimiter/encoding."""

    def __init__(
        self,
        path: Path,
        *,
        sep: str = ",",
        decimal: str = ".",
        encoding: str = "utf-8-sig",
        header: bool = True,
    ):
        self.path = Path(path)
        self._sep = sep
        self._decimal = decimal
        self._header = header
        self._file = self.path.open("w", encoding=encoding, newline="")
        self._writer: csv.writer | None = None
        self.rows_written = 0

    def write_header(self, columns: Sequence[str]) -> None:
        self._writer = csv.writer(self._file, delimiter=self._sep)
        if self._header:
            self._writer.writerow(list(columns))

    def write_chunk(self, rows: Sequence[Sequence[Any]]) -> None:
        if self._writer is None:
            raise RuntimeError("CSV header not written")
        for idx, row in enumerate(rows):
            self._writer.writerow([_csv_cell(v, decimal=self._decimal) for v in row])
            self.rows_written += 1
            if (idx + 1) % CSV_YIELD_EVERY_ROWS == 0:
                _gil_yield()

    def close(self) -> None:
        self._file.close()

    def abort(self) -> None:
        self.close()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _gil_yield() -> None:
    time.sleep(0.001)


def iter_rows_chunked(
    cursor_or_result,
    chunk_size: int = STREAM_EXPORT_CHUNK_ROWS,
) -> Iterator[tuple[list[str], list]]:
    """Yield (column_names, rows_chunk) without accumulating the full result."""
    columns: list[str] = []
    description = getattr(cursor_or_result, "description", None)
    if description:
        columns = [col[0] for col in description]
    elif hasattr(cursor_or_result, "keys"):
        try:
            columns = list(cursor_or_result.keys())
        except Exception:
            columns = []

    if not columns:
        return

    while True:
        chunk = cursor_or_result.fetchmany(chunk_size)
        if not chunk:
            break
        yield columns, list(chunk)
        _gil_yield()


def _infer_pa_type(value: Any) -> pa.DataType:
    if value is None:
        return pa.null()
    if isinstance(value, bool):
        return pa.bool_()
    if isinstance(value, int) and not isinstance(value, bool):
        return pa.int64()
    if isinstance(value, float):
        return pa.float64()
    if isinstance(value, Decimal):
        return pa.float64()
    if isinstance(value, datetime):
        return pa.timestamp("us")
    if isinstance(value, date):
        return pa.date32()
    if isinstance(value, dt_time):
        return pa.time64("us")
    if isinstance(value, bytes):
        return pa.binary()
    return pa.string()


def _merge_pa_types(current: pa.DataType, new: pa.DataType) -> pa.DataType:
    if pa.types.is_null(current):
        return new
    if pa.types.is_null(new):
        return current
    if current.equals(new):
        return current
    if pa.types.is_integer(current) and pa.types.is_integer(new):
        return pa.int64()
    if pa.types.is_floating(current) or pa.types.is_floating(new):
        if pa.types.is_integer(current) or pa.types.is_integer(new) or pa.types.is_floating(new) or pa.types.is_floating(current):
            return pa.float64()
    if pa.types.is_timestamp(current) or pa.types.is_timestamp(new):
        return pa.timestamp("us")
    return pa.string()


def _merge_pa_type(current: pa.DataType, new: pa.DataType) -> pa.DataType:
    return _merge_pa_types(current, new)


def _infer_schema(columns: list[str], rows: list) -> pa.Schema:
    col_types: list[pa.DataType] = []
    for col_idx in range(len(columns)):
        inferred = pa.null()
        for row in rows:
            if col_idx < len(row):
                inferred = _merge_pa_type(inferred, _infer_pa_type(row[col_idx]))
        # An all-NULL column infers as pa.null(), which Parquet cannot write and
        # which rejects any real value arriving in a later chunk ("Invalid null
        # value"). Promote it to string — the most permissive type — so later
        # non-null values coerce cleanly via the fallback path.
        if pa.types.is_null(inferred):
            inferred = pa.string()
        col_types.append(inferred)
    return pa.schema([pa.field(name, dtype) for name, dtype in zip(columns, col_types)])


def _coerce_value(value: Any, target: pa.DataType) -> Any:
    if value is None:
        return None
    if pa.types.is_string(target) or pa.types.is_large_string(target):
        return _csv_cell(value)
    if pa.types.is_boolean(target):
        return bool(value)
    if pa.types.is_integer(target):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if pa.types.is_floating(target):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if pa.types.is_timestamp(target):
        if isinstance(value, datetime):
            return value
        return None
    if pa.types.is_date(target):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return None
    if pa.types.is_binary(target):
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")
    return _csv_cell(value)


def _chunk_to_table(columns: list[str], rows: list, schema: pa.Schema | None) -> tuple[pa.Table, pa.Schema]:
    if not columns:
        return pa.table({}), schema or pa.schema([])

    if schema is None:
        schema = _infer_schema(columns, rows)

    if rows:
        try:
            records = [
                {
                    columns[i]: (row[i] if i < len(row) else None)
                    for i in range(len(columns))
                }
                for row in rows
            ]
            table = pa.Table.from_pylist(records, schema=schema)
            return table, schema
        except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, TypeError):
            pass

    col_types = [schema.field(name).type for name in columns]
    arrays: dict[str, list] = {name: [] for name in columns}
    for row in rows:
        for col_idx, name in enumerate(columns):
            value = row[col_idx] if col_idx < len(row) else None
            arrays[name].append(_coerce_value(value, col_types[col_idx]))

    table = pa.table({name: pa.array(arrays[name], type=col_types[i]) for i, name in enumerate(columns)})
    return table, schema


class ParquetStreamWriter:
    """Write row chunks as Parquet row groups."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._writer: pq.ParquetWriter | None = None
        self._schema: pa.Schema | None = None
        self.rows_written = 0

    def write_header(self, columns: Sequence[str]) -> None:
        self._columns = list(columns)

    def write_chunk(self, columns: list[str], rows: list) -> None:
        if not columns:
            return
        table, self._schema = _chunk_to_table(columns, rows, self._schema)
        if self._writer is None:
            self._writer = pq.ParquetWriter(
                self.path,
                self._schema,
                compression=PARQUET_COMPRESSION,
            )
        self._writer.write_table(table)
        self.rows_written += len(rows)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def abort(self) -> None:
        self.close()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


ExportFormat = Literal["csv", "parquet"]


@dataclass
class StreamExportResult:
    files: list[Path] = field(default_factory=list)
    row_counts: list[int] = field(default_factory=list)
    columns_per_file: list[list[str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total_rows(self) -> int:
        return sum(self.row_counts)


def make_result_path(base_path: Path, file_index: int, export_format: ExportFormat) -> Path:
    """Build path for result set N (1-based suffix when multiple)."""
    base_path = Path(base_path)
    suffix = ".csv" if export_format == "csv" else ".parquet"
    if file_index <= 1:
        if base_path.suffix.lower() in (".csv", ".parquet"):
            return base_path
        return base_path.with_suffix(suffix)
    stem = base_path.stem if base_path.suffix else base_path.name
    parent = base_path.parent if base_path.parent != Path(".") else Path(".")
    return parent / f"{stem}_{file_index}{suffix}"


def _sanitize_schema_for_parquet(schema: pa.Schema) -> pa.Schema:
    """Promote null-typed columns to string so Parquet can write them.

    A column that is entirely NULL arrives as pa.null() (from the driver or from
    inference). Parquet cannot write the null type and later non-null values
    raise "Invalid null value". String is the most permissive fallback.
    """
    needs_fix = any(pa.types.is_null(field.type) for field in schema)
    if not needs_fix:
        return schema
    return pa.schema(
        [
            pa.field(name, pa.string() if pa.types.is_null(field.type) else field.type)
            for name, field in zip(schema.names, schema)
        ]
    )


def _merge_arrow_schemas(current: pa.Schema | None, table: pa.Table) -> pa.Schema:
    if current is None:
        return table.schema
    merged_fields: list[pa.Field] = []
    seen: set[str] = set()
    for name in current.names:
        seen.add(name)
        if name in table.column_names:
            cur_type = current.field(name).type
            new_type = table.schema.field(name).type
            merged_fields.append(pa.field(name, _merge_pa_type(cur_type, new_type)))
        else:
            merged_fields.append(current.field(name))
    for name in table.column_names:
        if name not in seen:
            merged_fields.append(table.schema.field(name))
    return pa.schema(merged_fields)


def _cast_arrow_table(table: pa.Table, schema: pa.Schema) -> pa.Table:
    try:
        return table.cast(schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, TypeError):
        pass
    try:
        return pa.Table.from_pylist(table.to_pylist(), schema=schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, TypeError):
        pass
    # Last resort: stringify every column so mixed-type batches still land on disk.
    records = table.to_pylist()
    string_schema = pa.schema([pa.field(name, pa.string()) for name in table.column_names])
    return pa.Table.from_pylist(
        [{name: _csv_cell(row.get(name)) for name in table.column_names} for row in records],
        schema=string_schema,
    )


def _write_parquet_slices(
    writer: pq.ParquetWriter,
    table: pa.Table,
    *,
    slice_rows: int = STREAM_ARROW_ROW_GROUP_ROWS,
) -> int:
    written = 0
    if table.num_rows <= slice_rows:
        writer.write_table(table)
        return table.num_rows
    offset = 0
    while offset < table.num_rows:
        length = min(slice_rows, table.num_rows - offset)
        writer.write_table(table.slice(offset, length))
        written += length
        offset += length
        _gil_yield()
    return written


def _abort_stream_path(path: Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _arrow_table_rows(table: pa.Table) -> list[list[Any]]:
    return [
        [table.column(col_idx)[row_idx].as_py() for col_idx in range(table.num_columns)]
        for row_idx in range(table.num_rows)
    ]


def _stream_arrow_to_csv_manual(
    arrow_fetcher: Callable[[int], pa.Table | None],
    *,
    path: Path,
    columns: list[str] | None,
    csv_options: dict,
    is_cancelled: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
) -> int:
    opts = normalize_csv_options(csv_options)
    writer = CsvStreamWriter(
        path,
        sep=opts["sep"],
        decimal=opts["decimal"],
        encoding=opts["encoding"],
        header=opts["header"],
    )
    rows_written = 0
    header_written = False
    try:
        while True:
            if is_cancelled and is_cancelled():
                writer.abort()
                return -1
            table = arrow_fetcher(STREAM_ARROW_CHUNK_ROWS)
            if table is None or table.num_rows == 0:
                break
            use_columns = columns or list(table.column_names)
            if not header_written:
                writer.write_header(use_columns)
                header_written = True
            chunk_rows = _arrow_table_rows(table)
            writer.write_chunk(chunk_rows)
            rows_written += len(chunk_rows)
            if on_chunk:
                on_chunk(len(chunk_rows))
            if is_cancelled and is_cancelled():
                writer.abort()
                return -1
            _gil_yield()
        if rows_written == 0 and columns:
            writer.write_header(columns)
        writer.close()
        return rows_written
    except Exception:
        writer.abort()
        raise


def stream_arrow_to_file(
    arrow_fetcher: Callable[[int], pa.Table | None],
    *,
    path: Path,
    export_format: ExportFormat,
    columns: list[str] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    csv_options: dict | None = None,
) -> int:
    """Stream Arrow tables from fetchmany_arrow directly to CSV or Parquet."""
    if export_format == "csv" and csv_options is not None:
        return _stream_arrow_to_csv_manual(
            arrow_fetcher,
            path=path,
            columns=columns,
            csv_options=csv_options,
            is_cancelled=is_cancelled,
            on_chunk=on_chunk,
        )

    path = Path(path)
    rows_written = 0
    schema: pa.Schema | None = None
    writer_schema: pa.Schema | None = None
    pq_writer: pq.ParquetWriter | None = None
    csv_file = None
    csv_writer: pacsv.CSVWriter | None = None

    def _abort() -> None:
        nonlocal pq_writer, csv_file, csv_writer
        if pq_writer is not None:
            try:
                pq_writer.close()
            except Exception:
                pass
            pq_writer = None
        if csv_writer is not None:
            try:
                csv_writer.close()
            except Exception:
                pass
            csv_writer = None
        if csv_file is not None:
            try:
                csv_file.close()
            except Exception:
                pass
            csv_file = None
        _abort_stream_path(path)

    try:
        while True:
            if is_cancelled and is_cancelled():
                _abort()
                return -1

            table = arrow_fetcher(STREAM_ARROW_CHUNK_ROWS)
            if table is None or table.num_rows == 0:
                break

            schema = _merge_arrow_schemas(schema, table)
            target_schema = writer_schema or schema

            if (
                export_format == "parquet"
                and pq_writer is not None
                and writer_schema is not None
                and not schema.equals(writer_schema)
            ):
                pq_writer.close()
                pq_writer = None
                existing = pq.read_table(path)
                upgraded = _cast_arrow_table(existing, schema)
                write_schema = _sanitize_schema_for_parquet(schema)
                pq_writer = pq.ParquetWriter(
                    path,
                    write_schema,
                    compression=PARQUET_COMPRESSION,
                )
                _write_parquet_slices(pq_writer, upgraded)
                writer_schema = write_schema
                target_schema = write_schema

            cast_table = _cast_arrow_table(table, target_schema)

            if export_format == "parquet":
                if pq_writer is None:
                    write_schema = _sanitize_schema_for_parquet(schema)
                    writer_schema = write_schema
                    target_schema = write_schema
                    cast_table = _cast_arrow_table(table, target_schema)
                    pq_writer = pq.ParquetWriter(
                        path,
                        target_schema,
                        compression=PARQUET_COMPRESSION,
                    )
                rows_written += _write_parquet_slices(pq_writer, cast_table)
            else:
                if csv_writer is None:
                    csv_file = path.open("wb")
                    csv_file.write(b"\xef\xbb\xbf")
                    csv_writer = pacsv.CSVWriter(csv_file, schema)
                csv_writer.write_table(cast_table)
                rows_written += cast_table.num_rows

            if on_chunk:
                on_chunk(table.num_rows)
            if is_cancelled and is_cancelled():
                _abort()
                return -1
            _gil_yield()

        if rows_written == 0 and columns:
            empty_schema = pa.schema([pa.field(name, pa.string()) for name in columns])
            if export_format == "parquet":
                pq_writer = pq.ParquetWriter(path, empty_schema, compression=PARQUET_COMPRESSION)
                pq_writer.write_table(empty_schema.empty_table())
                pq_writer.close()
            else:
                csv_file = path.open("wb")
                csv_file.write(b"\xef\xbb\xbf")
                csv_writer = pacsv.CSVWriter(csv_file, empty_schema)
                csv_writer.write_table(empty_schema.empty_table())
                csv_writer.close()
                csv_file.close()
        elif export_format == "parquet" and pq_writer is not None:
            pq_writer.close()
        elif export_format == "csv" and csv_writer is not None:
            csv_writer.close()
            if csv_file is not None:
                csv_file.close()

        return rows_written
    except Exception:
        _abort()
        raise


def stream_result_set_to_file(
    columns: list[str],
    row_iter: Iterator[tuple[list[str], list]],
    *,
    path: Path,
    export_format: ExportFormat,
    is_cancelled: Callable[[], bool] | None = None,
    on_chunk: Callable[[int], None] | None = None,
    csv_options: dict | None = None,
) -> int:
    """Stream one result set to a file. Returns rows written."""
    if export_format == "csv":
        opts = normalize_csv_options(csv_options)
        writer: CsvStreamWriter | ParquetStreamWriter = CsvStreamWriter(
            path,
            sep=opts["sep"],
            decimal=opts["decimal"],
            encoding=opts["encoding"],
            header=opts["header"],
        )
        writer.write_header(columns)
        rows_written = 0
        try:
            for _cols, chunk in row_iter:
                if is_cancelled and is_cancelled():
                    writer.abort()
                    return -1
                writer.write_chunk(chunk)
                rows_written = writer.rows_written
                if on_chunk:
                    on_chunk(len(chunk))
                _gil_yield()
            writer.close()
            return rows_written
        except Exception:
            writer.abort()
            raise
    else:
        pq_writer = ParquetStreamWriter(path)
        if columns:
            pq_writer.write_header(columns)
        rows_written = 0
        try:
            for cols, chunk in row_iter:
                if is_cancelled and is_cancelled():
                    pq_writer.abort()
                    return -1
                use_cols = cols or columns
                if not use_cols and chunk:
                    use_cols = [f"col_{i}" for i in range(len(chunk[0]))]
                pq_writer.write_chunk(use_cols, chunk)
                rows_written = pq_writer.rows_written
                if on_chunk:
                    on_chunk(len(chunk))
                _gil_yield()
            if rows_written == 0 and columns:
                pq_writer.write_chunk(columns, [])
            pq_writer.close()
            return rows_written
        except Exception:
            pq_writer.abort()
            raise
