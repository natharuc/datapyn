"""Bounded, JSON-safe previews and page values; never pickle a result to the UI."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
import math
from types import ModuleType
from typing import Any

JS_SAFE_INTEGER = 2**53 - 1


def document_value(value: Any):
    """JSON/EJSON value for one document/cell, preserving nested BSON and precision.

    This representation never replaces the object retained by the DataFrame.
    The ordinary JSON scalars stay readable; extended values use explicit tags.
    """
    def convert(item, ancestors, depth=0):
        if depth > 100:
            raise ValueError("Document nesting exceeds 100 levels")
        if isinstance(item, (dict, list, tuple)):
            if id(item) in ancestors:
                raise ValueError("Circular document values cannot be represented as JSON")
            ancestors = ancestors | {id(item)}
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("Document JSON keys must be strings")
                return {key: convert(child, ancestors, depth + 1) for key, child in item.items()}
            return [convert(child, ancestors, depth + 1) for child in item]
        if item is None or isinstance(item, (str, bool)):
            return item
        if isinstance(item, int):
            return int(item) if abs(item) <= JS_SAFE_INTEGER else {"$numberLong": str(item)}
        if isinstance(item, float):
            if math.isfinite(item):
                return float(item)
            return {"$numberDouble": "NaN" if math.isnan(item) else "Infinity" if item > 0 else "-Infinity"}
        if isinstance(item, Decimal):
            return {"$numberDecimal": str(item)}
        if isinstance(item, (datetime, date, time)):
            # Keep sub-millisecond precision (including pandas Timestamp).
            return {"$date": item.isoformat()} if not isinstance(item, time) else item.isoformat()
        if type(item).__name__ in {"NAType", "NaTType"}:
            return None
        if hasattr(item, "item"):
            converted = item.item()
            if converted is not item:
                return convert(converted, ancestors, depth + 1)
        from bson.json_util import default
        return default(item)

    return convert(value, set())


def document_json(value: Any) -> str:
    return json.dumps(document_value(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def scalar(value: Any) -> str | int | float | bool | None:
    """Preserve values JSON/JavaScript can represent without losing precision."""
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value) if abs(value) <= JS_SAFE_INTEGER else str(value)
    if isinstance(value, float):
        # NumPy float64 subclasses float. Returning it unchanged makes the
        # broker import NumPy while unpickling a supposedly plain DTO.
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (dict, list, tuple)):
        return document_json(value)
    # numpy scalars, pandas NA/NaT; imports stay inside the kernel.
    if hasattr(value, "item"):
        try:
            converted = value.item()
            if converted is not value:
                return scalar(converted)
        except (ValueError, TypeError):
            pass
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    try:
        return str(value)
    except BaseException:
        return f"<{type(value).__name__}>"


def preview(value: Any, limit: int = 240) -> str:
    try:
        if hasattr(value, "shape") and type(value).__name__ in {"DataFrame", "Series", "LazyFrame"}:
            return f"{type(value).__name__}{value.shape}"
        if isinstance(value, str):
            return repr(value[:limit])[:limit]
        if isinstance(value, (list, tuple)):
            return repr(value[:8])[:limit]
        if isinstance(value, dict):
            return repr(list(value.keys())[:8])[:limit]
        return repr(value)[:limit]
    except BaseException:
        return f"<{type(value).__name__}>"


def describe_variables(namespace: dict) -> list[dict]:
    from types import FunctionType
    variables = []
    for name, value in list(namespace.items()):
        if name.startswith("_") or name in {"pd", "np", "pl", "plt", "display"} or isinstance(value, ModuleType):
            continue
        if name == "sql" and type(value) is FunctionType and value.__dict__.get("_datapyn_sql_helper") is True:
            continue
        variables.append({"name": name, "type": type(value).__name__, "preview": preview(value)})
        if len(variables) >= 200:
            break
    return variables
