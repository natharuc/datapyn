"""Lossless EJSON columns for document values without a native Arrow type."""

from datetime import date, datetime, time
from decimal import Decimal
import json

from .values import document_json


def _kind(value):
    if value is None or type(value).__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int" if -(2**63) <= value < 2**63 else "document"
    if isinstance(value, (str, float, Decimal, datetime, date, time, bytes)):
        return type(value).__name__
    return "document"


def parquet_schema(frame, *, index=False):
    """Inspect each column once; do not copy/encode a full million-row frame."""
    import pyarrow as pa

    encoded = []
    fields = []
    base = pa.Schema.from_pandas(frame.head(0), preserve_index=index)
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        kinds = set()
        if series.dtype == object:
            for value in series.array:
                kind = _kind(value)
                if kind is not None:
                    kinds.add(kind)
                if "document" in kinds or len(kinds) > 1:
                    break
        if "document" in kinds or len(kinds) > 1:
            encoded.append(position)
            fields.append(pa.field(str(name), pa.string(), metadata={b"datapyn.encoding": b"extended-json"}))
        else:
            # Arrow sees the entire column, so late non-NULL values determine
            # its type even when the first exported row group is all NULL.
            fields.append(pa.field(str(name), pa.array(series, from_pandas=True).type))
    fields.extend(base.field(position) for position in range(len(frame.columns), len(base)))
    metadata = dict(base.metadata or {})
    if encoded:
        metadata[b"datapyn.extended_json_columns"] = json.dumps([str(frame.columns[index]) for index in encoded]).encode("utf-8")
    return pa.schema(fields, metadata=metadata), encoded


def parquet_chunk(frame, encoded):
    if not encoded:
        return frame
    chunk = frame.copy(deep=False)
    for position in encoded:
        chunk.isetitem(position, frame.iloc[:, position].map(
            lambda value: None if value is None or type(value).__name__ in {"NAType", "NaTType"} else document_json(value)))
    return chunk
