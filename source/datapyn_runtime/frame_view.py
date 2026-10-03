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


def apply_view(frame, params):
    import pandas as pd

    spec = params.get("filter") or {}
    if not isinstance(spec, dict):
        raise ValueError("filter must be an object")
    filters = spec.get("filters") or []
    if not isinstance(filters, list) or len(filters) > 64:
        raise ValueError("Use at most 64 column filters")
    filters = list(filters)
    if "column" in spec:
        filters.append(spec)
    mask = None
    if "text" in spec and spec["text"]:
        text = str(spec["text"])
        if len(text) > 1000:
            raise ValueError("filter text exceeds 1000 characters")
        mask = pd.Series(False, index=frame.index)
        for index in range(len(frame.columns)):
            mask |= frame.iloc[:, index].astype("string").str.contains(text, case=False, regex=False, na=False)
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each column filter must be an object")
        series = frame[column_label(frame, item.get("column"))]
        operator, value = item.get("operator", "contains"), item.get("value")
        if operator in {"is_null", "not_null"}:
            part = series.isna() if operator == "is_null" else series.notna()
        elif operator == "contains":
            text = str("" if value is None else value)
            if len(text) > 1000:
                raise ValueError("filter text exceeds 1000 characters")
            part = series.astype("string").str.contains(text, case=False, regex=False, na=False)
        elif operator in {"equals", "gt", "lt", "gte", "lte"}:
            typed = _coerce(series, value, pd)
            if typed is None:
                if operator != "equals":
                    raise ValueError("Choose is_null or not_null to filter null values")
                part = series.isna()
            else:
                part = getattr(series, {"equals": "eq", "gt": "gt", "lt": "lt", "gte": "ge", "lte": "le"}[operator])(typed).fillna(False)
        else:
            raise ValueError(f"Unsupported filter operator: {operator}")
        mask = part if mask is None else mask & part
    if mask is not None:
        frame = frame.loc[mask]
    sort = params.get("sort") or {}
    if sort:
        if not isinstance(sort, dict):
            raise ValueError("sort must be an object")
        label = column_label(frame, sort.get("column"))
        direction = sort.get("direction", "asc")
        if direction not in {"asc", "desc"}:
            raise ValueError("sort direction must be asc or desc")
        frame = frame.sort_values(label, ascending=direction == "asc", kind="mergesort", na_position="last")
    return frame
