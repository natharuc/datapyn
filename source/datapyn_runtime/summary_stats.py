"""Selection statistics beside the kernel; no Qt or lossy Decimal conversion."""

from decimal import Decimal, InvalidOperation, localcontext

from .values import scalar

SAMPLE_ROWS = 100_000
TYPE_SAMPLE_ROWS = 200


def _decimal(value):
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, bool):
        return Decimal(int(value))
    try:
        text = str(value).strip()
        if not text or len(text) > 4096:
            return None
        converted = Decimal(text)
        return converted if converted.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def numeric_values(series, pd):
    """Use the legacy head-sample threshold; coerce strings without float64."""
    if pd.api.types.is_numeric_dtype(series.dtype):
        import numpy as np
        values = series.dropna()
        if pd.api.types.is_float_dtype(series.dtype):
            values = values[np.isfinite(values)]
        # NumPy integer reductions overflow and float medians round large keys.
        if pd.api.types.is_integer_dtype(series.dtype) and not values.empty:
            maximum = max(abs(int(values.min())), abs(int(values.max())))
            if maximum > 2**53 - 1 or maximum > (2**63 - 1) // len(values):
                return pd.Series([Decimal(int(value)) for value in values], dtype=object)
        return values
    sample = series.iloc[:TYPE_SAMPLE_ROWS].dropna()
    if sample.empty:
        sample = series.dropna().iloc[:TYPE_SAMPLE_ROWS]
    if sample.empty:
        return None
    valid = sum(_decimal(value) is not None for value in sample)
    if valid < max(1, len(sample) // 2):
        return None
    return pd.Series([converted for value in series for converted in [_decimal(value)] if converted is not None], dtype=object)


def numeric_stats(values):
    if values.empty:
        return dict.fromkeys(("sum", "mean", "min", "max", "median", "std", "coefficient"))
    if getattr(values.dtype, "kind", "") in {"i", "u"}:
        maximum = max(abs(int(values.min())), abs(int(values.max())))
        if maximum > 2**53 - 1 or maximum > (2**63 - 1) // len(values):
            values = values.map(lambda value: Decimal(int(value)))
    if str(values.dtype) != "object":
        average = values.mean()
        coefficient = values.std(ddof=0) / average * 100 if average != 0 and len(values) > 1 else None
        return {key: scalar(value) for key, value in (("sum", values.sum()), ("mean", average),
                ("min", values.min()), ("max", values.max()), ("median", values.median()),
                ("std", values.std()), ("coefficient", coefficient))}
    decimals = [_decimal(value) for value in values]
    decimals = [value for value in decimals if value is not None]
    if not decimals:
        return dict.fromkeys(("sum", "mean", "min", "max", "median", "std", "coefficient"))
    integer_digits = max(max(1, value.adjusted() + 1) for value in decimals)
    scale = max(max(0, -value.as_tuple().exponent) for value in decimals)
    with localcontext() as context:
        context.prec = max(128, 2 * (integer_digits + scale) + len(str(len(decimals))) + 16)
        total = sum(decimals, Decimal(0))
        average = total / len(decimals)
        squared = sum(((value - average) ** 2 for value in decimals), Decimal(0))
        standard = (squared / (len(decimals) - 1)).sqrt() if len(decimals) > 1 else None
        coefficient = (squared / len(decimals)).sqrt() / average * 100 if average != 0 and len(decimals) > 1 else None
        decimals.sort()
        middle = len(decimals) // 2
        median = decimals[middle] if len(decimals) % 2 else (decimals[middle - 1] + decimals[middle]) / 2
        return {key: scalar(value) for key, value in (("sum", total), ("mean", average),
                ("min", decimals[0]), ("max", decimals[-1]), ("median", median),
                ("std", standard), ("coefficient", coefficient))}


def summarize_frame(frame, pd):
    columns, numeric_columns = [], []
    ranges = frame.attrs.get("_datapyn_selected_rows", {})
    cell_count = sum(sum(end - start + 1 for start, end in selected) for selected in ranges.values()) if ranges else len(frame) * len(frame.columns)
    for index, column in enumerate(frame.columns[:200]):
        series = frame.iloc[:, index]
        selected_ranges = ranges.get(index)
        if selected_ranges is not None:
            parts = [series.iloc[start:end + 1] for start, end in selected_ranges]
            series = parts[0] if len(parts) == 1 else pd.concat(parts)
        item = {"name": str(column), "dtype": str(series.dtype), "count": len(series), "null_count": int(series.isna().sum())}
        numeric = numeric_values(series, pd)
        if numeric is not None:
            numeric_columns.append(numeric)
            item.update(numeric_stats(numeric))
            sample = numeric.iloc[:SAMPLE_ROWS]
            item.update(numeric_count=len(numeric), distinct=int(sample.nunique()),
                        distinct_sampled=len(numeric) > SAMPLE_ROWS, sample_rows=len(sample))
        else:
            sample = series.iloc[:SAMPLE_ROWS].astype("string").dropna()
            counts = sample.value_counts(dropna=True).head(10)
            item.update(distinct=int(sample.nunique()), sampled=len(series) > SAMPLE_ROWS,
                        sample_rows=min(len(series), SAMPLE_ROWS),
                        top=[{"value": str(key)[:240], "count": int(value)} for key, value in counts.items()])
        columns.append(item)
    # Only numeric vectors are combined; no DataFrame or rows cross the RPC.
    numeric = pd.concat(numeric_columns, ignore_index=True) if numeric_columns else pd.Series([], dtype=float)
    aggregates = {"count_numeric": len(numeric), **numeric_stats(numeric)}
    return {"row_count": len(frame), "column_count": len(frame.columns), "cell_count": cell_count,
            "columns": columns, "columns_truncated": len(frame.columns) > 200, "aggregates": aggregates}
