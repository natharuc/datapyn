"""One typed filter/sort contract shared by paging, exports, charts and stats."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
from numbers import Integral, Number


def column_label(frame, name):
    if not isinstance(name, str):
        raise ValueError("column must be its string name from the result descriptor")
    matches = [label for label in frame.columns if str(label) == name]
    if not matches:
        raise ValueError(f"Unknown column: {name}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous column name: {name}; duplicate names cannot be sorted or filtered by name")
    return matches[0]


def _coerce(series, value, pd):
    if value is None:
        return None
    dtype = series.dtype
    sample = next((item for item in series.head(200).array if item is not None and item is not pd.NA and not (isinstance(item, float) and math.isnan(item))), None)
    if pd.api.types.is_bool_dtype(dtype) or isinstance(sample, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, str)):
            normalized = str(value).strip().casefold()
            if normalized in {"true", "1", "yes", "sim"}:
                return True
            if normalized in {"false", "0", "no", "não", "nao"}:
                return False
        raise ValueError("Boolean filters require true or false")
    if pd.api.types.is_numeric_dtype(dtype) or isinstance(sample, Number):
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError("Numeric filters require a finite number")
            if pd.api.types.is_integer_dtype(dtype) or isinstance(sample, Integral):
                if number != number.to_integral_value():
                    raise ValueError("Integer filters require a whole number")
                return int(number)
            return number if isinstance(sample, Decimal) else float(number)
        except (InvalidOperation, TypeError) as error:
            raise ValueError("Numeric filters require a valid number") from error
    if pd.api.types.is_datetime64_any_dtype(dtype):
        try:
            timestamp = pd.Timestamp(value)
            timezone = getattr(dtype, "tz", None)
            if timezone is not None and timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize(timezone)
            elif timezone is None and timestamp.tzinfo is not None:
                timestamp = timestamp.tz_convert("UTC").tz_localize(None)
            return timestamp
        except (ValueError, TypeError) as error:
            raise ValueError("Date filters require an ISO date or datetime") from error
    if isinstance(sample, (date, datetime)):
        try:
            return datetime.fromisoformat(str(value)) if isinstance(sample, datetime) else date.fromisoformat(str(value))
        except (ValueError, TypeError) as error:
            raise ValueError("Date filters require an ISO date or datetime") from error
    return str(value) if pd.api.types.is_string_dtype(dtype) else value


def _specs(params):
    spec = params.get("filter") or {}
    if not isinstance(spec, dict):
        raise ValueError("filter must be an object")
    filters = spec.get("filters") or []
    if not isinstance(filters, list) or len(filters) > 64:
        raise ValueError("Use at most 64 column filters")
    filters = list(filters)
    if "column" in spec:
        filters.append(spec)
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each column filter must be an object")
        if item.get("operator", "contains") not in {"is_null", "not_null", "contains", "equals", "gt", "lt", "gte", "lte"}:
            raise ValueError(f"Unsupported filter operator: {item.get('operator')}")
        if item.get("operator", "contains") == "contains" and len(str(item.get("value", ""))) > 1000:
            raise ValueError("filter text exceeds 1000 characters")
    text = str(spec.get("text") or "")
    if len(text) > 1000:
        raise ValueError("filter text exceeds 1000 characters")
    sort = params.get("sort") or {}
    if not isinstance(sort, dict):
        raise ValueError("sort must be an object")
    if sort and sort.get("direction", "asc") not in {"asc", "desc"}:
        raise ValueError("sort direction must be asc or desc")
    return filters, text, sort


def pandas_positions(frame, params):
    """Filter/sort only positional indices and one key, never all data columns."""
    import numpy as np
    import pandas as pd
    filters, text, sort = _specs(params)
    mask = None
    if text:
        mask = np.zeros(len(frame), dtype=bool)
        for index in range(len(frame.columns)):
            mask |= frame.iloc[:, index].astype("string").str.contains(text, case=False, regex=False, na=False).to_numpy(dtype=bool, na_value=False)
    for item in filters:
        series = frame[column_label(frame, item.get("column"))]
        operator, value = item.get("operator", "contains"), item.get("value")
        if operator in {"is_null", "not_null"}:
            part = series.isna() if operator == "is_null" else series.notna()
        elif operator == "contains":
            part = series.astype("string").str.contains(str("" if value is None else value), case=False, regex=False, na=False)
        else:
            typed = _coerce(series, value, pd)
            if typed is None:
                if operator != "equals":
                    raise ValueError("Choose is_null or not_null to filter null values")
                part = series.isna()
            else:
                part = getattr(series, {"equals": "eq", "gt": "gt", "lt": "lt", "gte": "ge", "lte": "le"}[operator])(typed).fillna(False)
        part = part.to_numpy(dtype=bool, na_value=False)
        mask = part if mask is None else mask & part
    if mask is None and not sort:
        return None
    dtype = np.uint32 if len(frame) <= 2**32 else np.uint64
    positions = np.flatnonzero(mask).astype(dtype, copy=False) if mask is not None else np.arange(len(frame), dtype=dtype)
    if sort:
        label = column_label(frame, sort.get("column"))
        keys = frame[label].iloc[positions]
        narrow = pd.DataFrame({"key": keys.array, "position": positions})
        positions = narrow.sort_values("key", ascending=sort.get("direction", "asc") == "asc", kind="mergesort", na_position="last")["position"].to_numpy(copy=True)
    return positions


def polars_positions(frame, params):
    """Native expressions retain only mask/key/positions, not a pandas copy."""
    import pandas as pd
    import polars as pl
    filters, text, sort = _specs(params)
    expressions = []
    if text:
        parts = []
        for name in frame.columns:
            part = pl.col(name).cast(pl.String, strict=False).str.to_uppercase().str.contains(text.upper(), literal=True).fill_null(False)
            if frame[name].dtype.is_float():
                part = part & ~pl.col(name).is_nan().fill_null(False)
            parts.append(part)
        expressions.append(pl.any_horizontal(parts))
    for item in filters:
        name = column_label(frame, item.get("column"))
        series = frame[name]
        column = pl.col(name)
        nulls = column.is_null() | column.is_nan() if series.dtype.is_float() else column.is_null()
        operator, value = item.get("operator", "contains"), item.get("value")
        if operator in {"is_null", "not_null"}:
            part = nulls if operator == "is_null" else ~nulls
        elif operator == "contains":
            part = column.cast(pl.String, strict=False).str.to_uppercase().str.contains(str("" if value is None else value).upper(), literal=True)
            part = part & ~nulls
        else:
            typed = _coerce(series.head(200).to_pandas(use_pyarrow_extension_array=True), value, pd)
            if typed is None:
                if operator != "equals":
                    raise ValueError("Choose is_null or not_null to filter null values")
                part = nulls
            else:
                part = {"equals": column.__eq__, "gt": column.__gt__, "lt": column.__lt__, "gte": column.__ge__, "lte": column.__le__}[operator](typed)
                if series.dtype.is_float():
                    part = part & ~nulls
        expressions.append(part.fill_null(False))
    if not expressions and not sort:
        return None
    position_name, key_name, mask_name = "__positions", "__key", "__mask"
    selected = [pl.int_range(0, pl.len(), dtype=pl.UInt32 if len(frame) <= 2**32 else pl.UInt64).alias(position_name)]
    if expressions:
        selected.append(pl.all_horizontal(expressions).alias(mask_name))
    if sort:
        name = column_label(frame, sort.get("column"))
        key = pl.col(name)
        if frame[name].dtype.is_float():
            key = pl.when(key.is_nan()).then(None).otherwise(key)
        selected.append(key.alias(key_name))
    index = frame.select(selected)
    if expressions:
        index = index.filter(pl.col(mask_name))
    if sort:
        index = index.sort(key_name, descending=sort.get("direction", "asc") == "desc", nulls_last=True, maintain_order=True)
    return index[position_name].to_numpy().copy()


def apply_view(frame, params):
    positions = pandas_positions(frame, params)
    return frame if positions is None else frame.iloc[positions]
