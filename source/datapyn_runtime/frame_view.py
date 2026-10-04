"""One typed filter/sort contract shared by paging, exports, charts and stats."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import math
from numbers import Integral, Number
import re

MAX_KIND_ROWS = 10_000
MAX_KIND_VALUES = 200
TRUE_VALUES = frozenset({"true", "1", "t", "yes", "y", "sim", "s"})
FALSE_VALUES = frozenset({"false", "0", "f", "no", "n", "não", "nao"})


def bool_value(value):
    if isinstance(value, (bool, Integral, str)):
        normalized = str(value).strip().casefold()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
    return None


def column_kind(series, pd):
    """Infer object columns from a bounded sample, never full-column unique."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return "bool"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "date"
    flags, count = [True, True, True], 0
    for value in series.head(MAX_KIND_ROWS).dropna().head(MAX_KIND_VALUES).array:
        count += 1
        flags = [flags[0] and bool_value(value) is not None, flags[1] and isinstance(value, Number),
                 flags[2] and isinstance(value, (date, datetime))]
        if not any(flags):
            return "text"
    if count and flags[0]:
        return "bool"
    if count and flags[1]:
        return "number"
    if count and flags[2]:
        return "date"
    return "text"


def column_label(frame, name):
    if not isinstance(name, str):
        raise ValueError("column must be its string name from the result descriptor")
    matches = [label for label in frame.columns if str(label) == name]
    if not matches:
        raise ValueError(f"Unknown column: {name}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous column name: {name}; duplicate names cannot be sorted or filtered by name")
    return matches[0]


def _coerce(series, value, pd, *, integer_bound=None):
    if value is None:
        return None
    dtype = series.dtype
    sample_values = series.head(MAX_KIND_ROWS).dropna().head(MAX_KIND_VALUES).array
    sample = next(iter(sample_values), None)
    kind = column_kind(series, pd)
    if pd.api.types.is_bool_dtype(dtype) or isinstance(sample, bool) or kind == "bool" and (not isinstance(sample, Number) or bool_value(value) is not None):
        boolean = bool_value(value)
        if boolean is not None:
            return boolean
        raise ValueError("Boolean filters require true or false")
    if pd.api.types.is_numeric_dtype(dtype) or isinstance(sample, Number):
        try:
            token = str(value).strip().replace(",", ".")
            if len(token) > 1024:
                raise ValueError("Numeric filter exceeds 1024 characters")
            number = Decimal(token)
            if not number.is_finite():
                raise ValueError("Numeric filters require a finite number")
            if abs(number.as_tuple().exponent) > 1000 or abs(number.adjusted()) > 1000:
                raise ValueError("Numeric filter exponent exceeds 1000")
            integer = pd.api.types.is_integer_dtype(dtype) or isinstance(sample, Integral) and (
                integer_bound is None or all(isinstance(item, Integral) for item in sample_values))
            if integer:
                if number != number.to_integral_value():
                    if integer_bound is None:
                        raise ValueError("Integer filters require a whole number")
                    number = number.to_integral_value(rounding=ROUND_CEILING if integer_bound == "lower" else ROUND_FLOOR)
                return int(number)
            if isinstance(sample, Decimal) or integer_bound is not None and not pd.api.types.is_numeric_dtype(dtype):
                return number
            floating = float(number)
            if not math.isfinite(floating):
                raise ValueError("Numeric filters require a finite number")
            return floating
        except (InvalidOperation, TypeError) as error:
            raise ValueError("Numeric filters require a valid number") from error
    if pd.api.types.is_datetime64_any_dtype(dtype) or isinstance(sample, datetime):
        try:
            timestamp = pd.Timestamp(value)
            timezone = getattr(dtype, "tz", None) or getattr(sample, "tzinfo", None)
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


def _range_bounds(series, item, pd):
    lower = next((item[key] for key in ("value", "min", "start") if key in item), None)
    upper = next((item[key] for key in ("value_to", "max", "end") if key in item), None)
    lower = None if lower is None or isinstance(lower, str) and not lower.strip() else _coerce(series, lower, pd, integer_bound="lower")
    raw_upper = upper
    upper = None if upper is None or isinstance(upper, str) and not upper.strip() else _coerce(series, upper, pd, integer_bound="upper")
    exclusive = bool(upper is not None and column_kind(series, pd) == "date" and isinstance(raw_upper, str)
                     and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_upper.strip()))
    if exclusive:
        upper = upper + pd.DateOffset(days=1) if isinstance(upper, datetime) else upper + timedelta(days=1)
    return lower, upper, exclusive


def _polars_literal(value, dtype, pl):
    # Timestamp -> Python datetime conversion silently drops nanoseconds.
    if hasattr(value, "value") and dtype.base_type() == pl.Datetime:
        return pl.lit(value.value, dtype=pl.Int64).cast(pl.Datetime("ns", time_zone=dtype.time_zone))
    return pl.lit(value)


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
        for key in ("value", "value_to", "min", "max", "start", "end"):
            if isinstance(item.get(key), str) and len(item[key]) > 1024:
                raise ValueError("Filter values exceed 1024 characters")
        if item.get("operator", "contains") not in {"is_null", "not_null", "contains", "starts_with", "ends_with", "between", "equals", "gt", "lt", "gte", "lte"}:
            raise ValueError(f"Unsupported filter operator: {item.get('operator')}")
        if item.get("operator", "contains") in {"contains", "starts_with", "ends_with"} and len(str(item.get("value", ""))) > 1000:
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
        elif operator in {"contains", "starts_with", "ends_with"} or operator == "equals" and value is not None and column_kind(series, pd) == "text":
            values, token = series.astype("string").str.upper(), str("" if value is None else value).upper()
            part = values.str.contains(token, regex=False, na=False) if operator == "contains" else values.eq(token) if operator == "equals" else getattr(values.str, "startswith" if operator == "starts_with" else "endswith")(token, na=False)
        elif operator == "between":
            lower, upper, exclusive = _range_bounds(series, item, pd)
            if lower is None and upper is None:
                continue
            part = series.notna()
            if lower is not None:
                part &= series.ge(lower)
            if upper is not None:
                part &= series.lt(upper) if exclusive else series.le(upper)
        else:
            typed = _coerce(series, value, pd)
            if typed is None:
                if operator != "equals":
                    raise ValueError("Choose is_null or not_null to filter null values")
                part = series.isna()
            else:
                if isinstance(typed, bool) and not pd.api.types.is_bool_dtype(series.dtype):
                    normalized = series.astype("string").str.strip().str.casefold()
                    series = normalized.map({**dict.fromkeys(TRUE_VALUES, True), **dict.fromkeys(FALSE_VALUES, False)})
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
        elif operator in {"contains", "starts_with", "ends_with"} or operator == "equals" and value is not None and column_kind(series.head(MAX_KIND_ROWS).to_pandas(use_pyarrow_extension_array=True), pd) == "text":
            values, token = column.cast(pl.String, strict=False).str.to_uppercase(), str("" if value is None else value).upper()
            part = values.str.contains(token, literal=True) if operator == "contains" else values == token if operator == "equals" else getattr(values.str, "starts_with" if operator == "starts_with" else "ends_with")(token)
            part = part & ~nulls
        elif operator == "between":
            lower, upper, exclusive = _range_bounds(series.head(MAX_KIND_ROWS).to_pandas(use_pyarrow_extension_array=True), item, pd)
            if lower is None and upper is None:
                continue
            part = ~nulls
            if lower is not None:
                part &= column >= _polars_literal(lower, series.dtype, pl)
            if upper is not None:
                literal = _polars_literal(upper, series.dtype, pl)
                part &= column < literal if exclusive else column <= literal
        else:
            typed = _coerce(series.head(MAX_KIND_ROWS).to_pandas(use_pyarrow_extension_array=True), value, pd)
            if typed is None:
                if operator != "equals":
                    raise ValueError("Choose is_null or not_null to filter null values")
                part = nulls
            else:
                if isinstance(typed, bool) and series.dtype != pl.Boolean:
                    normalized = column.cast(pl.String, strict=False).str.strip_chars().str.to_lowercase()
                    column = pl.when(normalized.is_in(TRUE_VALUES)).then(True).when(normalized.is_in(FALSE_VALUES)).then(False).otherwise(None)
                typed = _polars_literal(typed, series.dtype, pl)
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
