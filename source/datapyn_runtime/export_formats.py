"""Bounded clipboard text and streaming file writers with cancellation."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import io
import json
import math
import sys

from .sql_export import missing, script_parts
from .values import scalar

MAX_TEXT_BYTES = 16 * 1024 * 1024
EXCEL_INTEGER_LIMIT = 10**15 - 1
DECIMAL_FORMATS = tuple("0." + "0" * scale for scale in range(1, 31))


def _excel_value(value):
    """Keep native cell types independently of the grid's JSON transport encoding.

    Excel numbers support 15 significant decimal digits and no subnormal
    floats; native dates span 1900..9999, have millisecond precision and no
    timezone. Use literal text only when that format cannot retain the original
    value. Never infer a number or date from a string returned by SQL.
    """
    if type(value).__module__.startswith("numpy"):
        if type(value).__name__ in {"datetime64", "timedelta64"}:
            import pandas as pd
            value = pd.Timestamp(value) if type(value).__name__ == "datetime64" else pd.Timedelta(value)
        elif hasattr(value, "item"):
            try:
                value = value.item()
            except (ValueError, TypeError):
                return scalar(value), None
    if missing(value):
        return None, None
    if isinstance(value, (str, bool)):
        return value, None
    if isinstance(value, int):
        return (str(value) if abs(value) > EXCEL_INTEGER_LIMIT else value), None
    if isinstance(value, Decimal):
        _, digits, exponent = value.as_tuple()
        significant = len(digits)
        while significant > 1 and digits[significant - 1] == 0:
            significant -= 1
        numeric = float(value)
        if significant > 15 or not math.isfinite(numeric) or value and abs(numeric) < sys.float_info.min:
            return str(value), None
        number_format = DECIMAL_FORMATS[-exponent - 1] if -30 <= exponent < 0 else None
        return value, number_format
    if isinstance(value, float):
        return (str(value) if value and abs(value) < sys.float_info.min else value), None
    if isinstance(value, datetime):
        if (value.utcoffset() is not None or not 1900 <= value.year <= 9999
                or value.microsecond % 1000 or getattr(value, "nanosecond", 0)):
            return value.isoformat(), None
        return value, "yyyy-mm-dd hh:mm:ss.000" if value.microsecond else "yyyy-mm-dd hh:mm:ss"
    if isinstance(value, date):
        if not 1900 <= value.year <= 9999:
            return value.isoformat(), None
        return value, "yyyy-mm-dd"
    if isinstance(value, time):
        if value.utcoffset() is not None or value.microsecond % 1000:
            return value.isoformat(), None
        return value, "hh:mm:ss.000" if value.microsecond else "hh:mm:ss"
    if isinstance(value, timedelta):
        if value < timedelta(0) or value.microseconds % 1000 or getattr(value, "nanoseconds", 0):
            return str(value), None
        return value, "[h]:mm:ss.000" if value.microseconds else "[h]:mm:ss"
    return scalar(value), None


class BoundedText(io.StringIO):
    def __init__(self, limit=MAX_TEXT_BYTES):
        super().__init__()
        self.limit = limit
        self.bytes = 0

    def write(self, text):
        self.bytes += len(text.encode("utf-8"))
        if self.bytes > self.limit:
            raise ValueError("Clipboard export exceeds 16 MiB; export to a file or select fewer rows")
        return super().write(text)


def _json_write(frame, output, options, control):
    orient = options.get("orient", "records")
    if orient not in {"records", "split", "index", "columns", "values", "table"}:
        raise ValueError("Choose a supported JSON orientation")
    lines = options.get("lines", False)
    if lines and orient != "records":
        raise ValueError("JSON lines requires records orientation")
    columns = [str(column) for column in frame.columns]
    if orient not in {"values"} and len(set(columns)) != len(columns):
        raise ValueError("JSON requires distinct column names")
    if orient in {"index", "columns"} and not frame.index.is_unique:
        raise ValueError("This JSON orientation requires a unique row index")
    if orient in {"index", "columns"}:
        keys = set()
        for position, value in enumerate(frame.index):
            if position % 1000 == 0:
                control.check()
            key = str(value)
            if key in keys:
                raise ValueError("JSON index keys must remain unique when converted to strings")
            keys.add(key)
    indent = options.get("indent")
    if indent is not None and (isinstance(indent, bool) or not isinstance(indent, int) or not 0 <= indent <= 8):
        raise ValueError("JSON indent must be between 0 and 8")
    def dump(value):
        json.dump(value, output, ensure_ascii=False, allow_nan=False, indent=None if lines else indent, default=scalar)
    include_index = bool(options.get("index", False))
    index_name = str(frame.index.name or "index")
    if include_index and orient in {"records", "table"} and index_name in columns:
        raise ValueError("The row index name conflicts with a JSON data column")
    if orient == "columns":
        output.write("{")
        for position, column in enumerate(columns):
            if position:
                output.write(",")
            dump(column)
            output.write(":{")
            for index, (key, value) in enumerate(frame.iloc[:, position].items()):
                if index:
                    output.write(",")
                dump(str(key))
                output.write(":")
                dump(scalar(value))
                if index % 500 == 0:
                    control.advance(int((position * len(frame) + index) / max(1, len(columns))))
            output.write("}")
        output.write("}")
        return
    if orient == "split":
        output.write('{"columns":')
        dump(columns)
        if include_index:
            output.write(',"index":')
            dump([scalar(value) for value in frame.index])
        output.write(',"data":')
    elif orient == "table":
        from pandas.io.json._table_schema import build_table_schema
        output.write('{"schema":')
        dump(build_table_schema(frame, index=include_index))
        output.write(',"data":')
    if not lines:
        output.write("{" if orient == "index" else "[")
    for position, row in enumerate(frame.itertuples(index=False, name=None)):
        if position and not lines:
            output.write(",")
        if orient == "index":
            dump(str(frame.index[position]))
            output.write(":")
        value = list(map(scalar, row)) if orient in {"split", "values"} else dict(zip(columns, map(scalar, row)))
        if include_index and orient in {"records", "table"}:
            value = {index_name: scalar(frame.index[position]), **value}
        dump(value)
        if lines:
            output.write("\n")
        elif indent:
            output.write("\n")
        if position % 500 == 0:
            control.advance(position)
    if not lines:
        output.write("}" if orient == "index" else "]")
    if orient in {"split", "table"}:
        output.write("}")
    if not lines:
        output.write("\n")


def write_text(frame, output, export_format, options, control):
    if export_format in {"csv", "tsv", "txt", "excel"}:
        delimiter = "\t" if export_format == "excel" else options.get("delimiter", "\t" if export_format == "tsv" else ";")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("Delimiter must be exactly one character")
        decimal = options.get("decimal", ".")
        if decimal not in {".", ","}:
            raise ValueError("Decimal must be a dot or comma")
        for start in range(0, max(1, len(frame)), 10000):
            control.check()
            frame.iloc[start:start + 10000].to_csv(output, sep=delimiter, index=bool(options.get("index", False)),
                                                 header=bool(options.get("include_header", True)) and start == 0,
                                                 decimal=decimal)
            control.advance(min(start + 10000, len(frame)))
    elif export_format == "json":
        _json_write(frame, output, options, control)
    elif export_format == "sql":
        for fragment in script_parts(frame, options, control):
            output.write(fragment)
    else:
        raise ValueError("Copy CSV, TSV, Excel text, JSON or SQL; binary formats require a file")
    control.check()


def write_file(frame, path, export_format, options, control):
    if export_format in {"csv", "tsv", "txt", "json", "sql"}:
        encoding = options.get("encoding", "utf-8-sig") if export_format in {"csv", "tsv", "txt"} else "utf-8"
        with path.open("w", encoding=encoding, newline="") as output:
            write_text(frame, output, export_format, options, control)
    elif export_format in {"xlsx", "excel"}:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        header = bool(options.get("include_header", True))
        index = bool(options.get("index", False))
        if len(frame) + int(header) > 1048576 or len(frame.columns) + int(index) > 16384:
            raise ValueError("Excel supports at most 1,048,576 rows and 16,384 columns; use CSV or Parquet")
        name = options.get("sheet_name", "DataPyn")
        if not isinstance(name, str) or not 1 <= len(name) <= 31 or any(character in name for character in "\\/*?:[]"):
            raise ValueError("Choose an Excel sheet name of at most 31 characters without \\ / * ? : [ ]")
        book = Workbook(write_only=True)
        sheet = book.create_sheet(name)
        def cell(value):
            value, number_format = _excel_value(value)
            item = WriteOnlyCell(sheet, value=value)
            if number_format:
                item.number_format = number_format
            if isinstance(value, str):
                # A query result beginning with '=' is data, never a formula.
                item.data_type = "s"
            return item
        try:
            if header:
                sheet.append([cell(value) for value in ([frame.index.name or "index"] if index else []) + list(frame.columns)])
            for position, row in enumerate(frame.itertuples(index=False, name=None)):
                if position % 500 == 0:
                    control.advance(position)
                sheet.append([cell(value) for value in ((frame.index[position],) if index else ()) + row])
            control.check()
            book.save(path)
        finally:
            book.close()
            if not sheet.closed:
                sheet.close()
            writer = getattr(sheet, "_writer", None)
            if writer and getattr(writer, "out", None):
                from pathlib import Path
                Path(writer.out).unlink(missing_ok=True)
    elif export_format == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq
        compression = options.get("compression", "snappy")
        if compression == "none":
            compression = None
        if compression not in {None, "snappy", "gzip", "zstd", "brotli", "lz4"}:
            raise ValueError("Choose a supported Parquet compression")
        writer = None
        try:
            schema = pa.Schema.from_pandas(frame, preserve_index=bool(options.get("index", False)))
            for start in range(0, max(1, len(frame)), 100000):
                control.check()
                table = pa.Table.from_pandas(frame.iloc[start:start + 100000], schema=schema,
                                             preserve_index=bool(options.get("index", False)))
                if writer is None:
                    writer = pq.ParquetWriter(path, table.schema, compression=compression)
                writer.write_table(table)
                control.advance(min(start + 100000, len(frame)))
        finally:
            if writer:
                writer.close()
    else:
        raise ValueError(f"Unsupported export format: {export_format}")
    control.check()
