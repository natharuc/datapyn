"""Bounded, JSON-safe previews and page values; never pickle a result to the UI."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import math
from types import ModuleType
from typing import Any

JS_SAFE_INTEGER = 2**53 - 1


def scalar(value: Any) -> str | int | float | bool | None:
    """Preserve values JSON/JavaScript can represent without losing precision."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) <= JS_SAFE_INTEGER else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
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
    variables = []
    for name, value in list(namespace.items()):
        if name.startswith("_") or name in {"pd", "np", "pl", "plt"} or isinstance(value, ModuleType):
            continue
        variables.append({"name": name, "type": type(value).__name__, "preview": preview(value)})
        if len(variables) >= 200:
            break
    return variables
