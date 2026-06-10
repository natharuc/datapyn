"""Build grid selection summaries for the Summarize panel."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

TEXT_PREVIEW_LIMIT = 48
SUMMARIZE_MAX_MATERIALIZED_ROWS = 5000
# Text stats (distinct/top) on millions of Python strings are GIL-heavy even
# in a worker thread; above this row count they are computed on a sample and
# displayed with an approximation marker.
TEXT_STATS_SAMPLE_ROWS = 100_000
# Full-column C calls (to_numeric, dropna) never release the GIL; bounding
# them to slices with explicit yields keeps the UI thread alive while the
# summarize worker crunches millions of rows.
NUMERIC_CHUNK_ROWS = 100_000


def _gil_yield() -> None:
    time.sleep(0.0005)


def _to_numeric_chunked(series: pd.Series) -> pd.Series:
    """pd.to_numeric in bounded slices so one column never starves the UI."""
    if pd.api.types.is_numeric_dtype(series):
        return series
    n = len(series)
    if n <= NUMERIC_CHUNK_ROWS:
        return pd.to_numeric(series, errors="coerce")
    parts = []
    for start in range(0, n, NUMERIC_CHUNK_ROWS):
        parts.append(
            pd.to_numeric(series.iloc[start : start + NUMERIC_CHUNK_ROWS], errors="coerce")
        )
        _gil_yield()
    return pd.concat(parts)
CellPair = Tuple[int, int]
RowRange = Tuple[int, int]


def has_summarize_selection(scope: Optional[dict]) -> bool:
    scope = scope or {}
    if scope.get("row_ranges") and scope.get("bound_cols"):
        return True
    return bool(scope.get("cells"))


def _format_number(value: float, *, decimals: Optional[int] = None) -> str:
    if pd.isna(value):
        return "—"
    if decimals is not None:
        return f"{value:,.{decimals}f}"
    abs_val = abs(value)
    if abs_val >= 1_000_000_000 or abs_val >= 1000:
        return f"{value:,.2f}"
    if abs_val >= 1:
        return f"{value:,.4g}"
    return f"{value:.6g}"


def _format_count(value: int) -> str:
    return f"{value:,}"


def _format_percent(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:.2f}%"


def format_with_column_config(value: Any, format_config: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    from src.ui.components.results_viewer import _grid_format_display_value

    return _grid_format_display_value(value, format_config)


def _resolve_scope(
    df: pd.DataFrame,
    cells: Optional[Sequence[CellPair]],
) -> tuple[str, List[CellPair], List[int], List[int]]:
    cell_list = [(int(r), int(c)) for r, c in (cells or []) if r is not None and c is not None]
    if cell_list:
        rows = sorted({row for row, _ in cell_list})
        cols = sorted({col for _, col in cell_list})
        return "selection", cell_list, rows, cols

    return "empty", [], [], []


def _series_for_column(df: pd.DataFrame, rows: Sequence[int], col_index: int) -> pd.Series:
    if df is None or df.empty or col_index < 0 or col_index >= len(df.columns):
        return pd.Series(dtype=object)
    row_indexes = [row for row in rows if 0 <= row < len(df)]
    if not row_indexes:
        return pd.Series(dtype=object)
    return df.iloc[row_indexes, col_index]


def _series_for_column_ranges(df: pd.DataFrame, row_ranges: Sequence[RowRange], col_index: int) -> pd.Series:
    if df is None or df.empty or col_index < 0 or col_index >= len(df.columns):
        return pd.Series(dtype=object)
    parts = []
    for start, end in row_ranges:
        start = max(0, int(start))
        end = min(len(df) - 1, int(end))
        if start <= end:
            parts.append(df.iloc[start : end + 1, col_index])
    if not parts:
        return pd.Series(dtype=object)
    if len(parts) == 1:
        return parts[0]
    return pd.concat(parts, ignore_index=True)


def _rows_from_ranges(row_ranges: Sequence[RowRange]) -> List[int]:
    rows: List[int] = []
    for start, end in row_ranges:
        rows.extend(range(int(start), int(end) + 1))
    return rows


def _row_count_from_ranges(row_ranges: Sequence[RowRange]) -> int:
    return sum(int(end) - int(start) + 1 for start, end in row_ranges)


def _column_is_numeric(
    series: pd.Series,
    col_index: int,
    numeric_column_indices: Optional[Set[int]],
) -> bool:
    from src.ui.components.results_viewer import _grid_column_is_numeric

    if _grid_column_is_numeric(series):
        return True
    if numeric_column_indices is not None and col_index in numeric_column_indices:
        sample = series.dropna()
        if len(sample) > 10_000:
            sample = sample.head(10_000)
        converted = pd.to_numeric(sample, errors="coerce")
        return int(converted.notna().sum()) > 0
    return False


def _top_text_value(series: pd.Series) -> str:
    cleaned = series.dropna().astype(str)
    if cleaned.empty:
        return "—"
    counts = cleaned.value_counts()
    top_value = str(counts.index[0])
    if len(top_value) > TEXT_PREVIEW_LIMIT:
        top_value = top_value[: TEXT_PREVIEW_LIMIT - 1] + "…"
    if len(counts) == 1:
        return top_value
    return f"{top_value} ({counts.iloc[0]:,})"


def _text_column_stats(series: pd.Series) -> tuple[str, str]:
    """Return (distinct_display, top_display) bounded for huge selections.

    Avoids astype(str) full-column passes (1M string allocations) and samples
    above TEXT_STATS_SAMPLE_ROWS; sampled stats are prefixed with '≈'.
    """
    # Slice BEFORE dropna: a full dropna() over millions of object cells is
    # itself one long GIL-held C call.
    sampled = len(series) > TEXT_STATS_SAMPLE_ROWS
    if sampled:
        non_null = series.head(TEXT_STATS_SAMPLE_ROWS).dropna()
        if non_null.empty:
            non_null = series.dropna().head(TEXT_STATS_SAMPLE_ROWS)
    else:
        non_null = series.dropna()
    if non_null.empty:
        return "0", "—"

    try:
        counts = non_null.value_counts()
    except TypeError:
        # Unhashable cells (lists/dicts) — fall back to string conversion.
        counts = non_null.astype(str).value_counts()

    distinct = len(counts)
    top_value = str(counts.index[0])
    if len(top_value) > TEXT_PREVIEW_LIMIT:
        top_value = top_value[: TEXT_PREVIEW_LIMIT - 1] + "…"
    top = top_value if distinct == 1 else f"{top_value} ({int(counts.iloc[0]):,})"

    prefix = "≈" if sampled else ""
    return f"{prefix}{distinct:,}", (f"{prefix}{top}" if sampled else top)


def _concat_numeric_arrays(parts: List[np.ndarray]) -> np.ndarray:
    if not parts:
        return np.empty(0, dtype=float)
    if len(parts) == 1:
        return parts[0]
    return np.concatenate(parts)


def _collect_numeric_values(df: pd.DataFrame, cells: Sequence[CellPair]) -> np.ndarray:
    values: List[float] = []
    for row, col in cells:
        if row < 0 or col < 0 or row >= len(df) or col >= len(df.columns):
            continue
        numeric = pd.to_numeric(df.iloc[row, col], errors="coerce")
        if pd.notna(numeric):
            values.append(float(numeric))
    return np.asarray(values, dtype=float)


def _numeric_cols_only(df: pd.DataFrame, cols: Sequence[int]) -> List[int]:
    """Keep only numeric-ish columns (sampled check) before full coercion.

    Running pd.to_numeric over millions of text values just to discard them
    holds the GIL for seconds per column and freezes the app.
    """
    from src.ui.components.results_viewer import _grid_column_is_numeric

    keep: List[int] = []
    for col_index in cols:
        if col_index < 0 or col_index >= len(df.columns):
            continue
        if _grid_column_is_numeric(df.iloc[:, col_index]):
            keep.append(col_index)
    return keep


def _collect_numeric_values_for_columns(
    df: pd.DataFrame,
    rows: Sequence[int],
    cols: Sequence[int],
) -> np.ndarray:
    parts: List[np.ndarray] = []
    row_indexes = [row for row in rows if 0 <= row < len(df)]
    if not row_indexes:
        return np.empty(0, dtype=float)
    for col_index in _numeric_cols_only(df, cols):
        numeric = pd.to_numeric(df.iloc[row_indexes, col_index], errors="coerce")
        arr = numeric.to_numpy(dtype=float, na_value=np.nan)
        arr = arr[~np.isnan(arr)]
        if arr.size:
            parts.append(arr)
    return _concat_numeric_arrays(parts)


def _collect_numeric_values_for_ranges(
    df: pd.DataFrame,
    row_ranges: Sequence[RowRange],
    cols: Sequence[int],
) -> np.ndarray:
    parts: List[np.ndarray] = []
    numeric_cols = _numeric_cols_only(df, cols)
    if not numeric_cols:
        return np.empty(0, dtype=float)
    for start, end in row_ranges:
        start = max(0, int(start))
        end = min(len(df) - 1, int(end))
        if start > end:
            continue
        # Bounded sub-slices: a single 1M-row to_numeric is one GIL-held call.
        for sub_start in range(start, end + 1, NUMERIC_CHUNK_ROWS):
            sub_end = min(end, sub_start + NUMERIC_CHUNK_ROWS - 1)
            chunk = df.iloc[sub_start : sub_end + 1]
            for col_index in numeric_cols:
                numeric = pd.to_numeric(chunk.iloc[:, col_index], errors="coerce")
                arr = numeric.to_numpy(dtype=float, na_value=np.nan)
                arr = arr[~np.isnan(arr)]
                if arr.size:
                    parts.append(arr)
            _gil_yield()
    return _concat_numeric_arrays(parts)


def _build_aggregates(
    df: pd.DataFrame,
    cells: Sequence[CellPair],
    rows: Sequence[int],
    cols: Sequence[int],
    numeric_values: np.ndarray,
    *,
    cells_selected: Optional[int] = None,
    rows_count: Optional[int] = None,
) -> List[Dict[str, str]]:
    count_cells = cells_selected if cells_selected is not None else len(cells)
    count_numeric = int(numeric_values.size)
    row_total = rows_count if rows_count is not None else len(rows)
    aggregates: List[Dict[str, str]] = [
        {"key": "rows", "value": _format_count(row_total)},
        {"key": "cols", "value": _format_count(len(cols))},
        {"key": "count", "value": _format_count(count_cells)},
        {"key": "count_numeric", "value": _format_count(count_numeric)},
    ]

    if count_numeric == 0:
        aggregates.extend([
            {"key": "sum", "value": "—"},
            {"key": "avg", "value": "—"},
            {"key": "min", "value": "—"},
            {"key": "max", "value": "—"},
            {"key": "median", "value": "—"},
            {"key": "coefficient", "value": "—"},
        ])
        return aggregates

    total = float(numeric_values.sum())
    avg = float(numeric_values.mean())
    aggregates.extend([
        {"key": "sum", "value": _format_number(total, decimals=2)},
        {"key": "avg", "value": _format_number(avg, decimals=4)},
        {"key": "min", "value": _format_number(float(numeric_values.min()), decimals=2)},
        {"key": "max", "value": _format_number(float(numeric_values.max()), decimals=2)},
        {"key": "median", "value": _format_number(float(np.median(numeric_values)), decimals=2)},
    ])

    if avg != 0 and count_numeric > 1:
        coeff = float(numeric_values.std(ddof=0) / avg * 100)
        aggregates.append({"key": "coefficient", "value": _format_percent(coeff)})
    else:
        aggregates.append({"key": "coefficient", "value": "—"})

    return aggregates


def build_selection_summary(
    df: Optional[pd.DataFrame],
    cells: Optional[Sequence[CellPair]],
    *,
    row_ranges: Optional[Sequence[RowRange]] = None,
    bound_cols: Optional[Sequence[int]] = None,
    result_label: str = "",
    column_formats: Optional[Dict[str, Any]] = None,
    numeric_column_indices: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """Return a summary payload for the Summarize panel."""
    empty = {
        "title": result_label or "",
        "subtitle": "",
        "scope": "empty",
        "rows_selected": 0,
        "cols_selected": 0,
        "cells_selected": 0,
        "grand_total": None,
        "columns": [],
        "aggregates": [],
    }
    if df is None or df.empty:
        empty["subtitle"] = "no_data"
        return empty

    has_cells = bool(cells)
    has_ranges = row_ranges is not None and bound_cols is not None
    if not has_cells and not has_ranges:
        empty["subtitle"] = "no_selection"
        return empty

    format_map = dict(column_formats or {})
    use_ranges = row_ranges is not None and bound_cols is not None
    if use_ranges:
        target_cols = sorted({int(col) for col in bound_cols if col is not None})
        target_cols = [col for col in target_cols if 0 <= col < len(df.columns)]
        row_ranges = [(int(start), int(end)) for start, end in row_ranges]
        target_rows = (
            _rows_from_ranges(row_ranges)
            if _row_count_from_ranges(row_ranges) <= SUMMARIZE_MAX_MATERIALIZED_ROWS
            else []
        )
        scope = "selection"
        target_cells: List[CellPair] = []
        cells_selected = _row_count_from_ranges(row_ranges) * len(target_cols)
        numeric_values = _collect_numeric_values_for_ranges(df, row_ranges, target_cols)
    else:
        scope, target_cells, target_rows, target_cols = _resolve_scope(df, cells)
        row_ranges = None
        if scope == "selection":
            numeric_values = _collect_numeric_values(df, target_cells)
            cells_selected = len(target_cells)
        else:
            numeric_values = _collect_numeric_values_for_columns(df, target_rows, target_cols)
            cells_selected = len(target_rows) * len(target_cols)

    columns: List[Dict[str, Any]] = []
    for col_index in target_cols:
        if col_index < 0 or col_index >= len(df.columns):
            continue
        column_name = str(df.columns[col_index])
        col_cells = [(row, col) for row, col in target_cells if col == col_index]
        col_rows = sorted({row for row, _ in col_cells}) if col_cells else target_rows
        if use_ranges and row_ranges is not None:
            series = _series_for_column_ranges(df, row_ranges, col_index)
        else:
            series = _series_for_column(df, col_rows, col_index)
        total = int(len(series))
        format_config = format_map.get(column_name, format_map.get(str(column_name), {"type": "default"}))

        # Detect type first (sampled) so text columns skip the full to_numeric pass.
        is_numeric = _column_is_numeric(series, col_index, numeric_column_indices)
        numeric_count = 0
        if is_numeric:
            numeric_series = _to_numeric_chunked(series)
            numeric_count = int(numeric_series.notna().sum())

        if is_numeric and numeric_count > 0:
            valid = numeric_series.dropna()
            col_sum = float(valid.sum())
            # nunique hashes every value (GIL-held ~200ms per 1M rows); sample
            # huge columns and mark the result as approximate.
            if len(valid) > TEXT_STATS_SAMPLE_ROWS:
                distinct_display = f"≈{int(valid.head(TEXT_STATS_SAMPLE_ROWS).nunique()):,}"
            else:
                distinct_display = _format_count(int(valid.nunique(dropna=True)))
            columns.append({
                "name": column_name,
                "kind": "numeric",
                "format": format_config,
                "count": _format_count(total),
                "sum": format_with_column_config(col_sum, format_config),
                "avg": format_with_column_config(float(valid.mean()), format_config),
                "min": format_with_column_config(float(valid.min()), format_config),
                "max": format_with_column_config(float(valid.max()), format_config),
                "distinct": distinct_display,
                "sum_raw": col_sum,
            })
            time.sleep(0.001)
            continue

        distinct_display, top_display = _text_column_stats(series)
        columns.append({
            "name": column_name,
            "kind": "text",
            "format": format_config,
            "count": _format_count(total),
            "sum": "—",
            "avg": "—",
            "min": "—",
            "max": "—",
            "distinct": distinct_display,
            "top": top_display,
        })
        time.sleep(0.001)

    grand_total = float(numeric_values.sum()) if numeric_values.size else None
    rows_selected = _row_count_from_ranges(row_ranges) if use_ranges and row_ranges else len(target_rows)
    return {
        "title": result_label or "",
        "subtitle": "selection" if scope == "selection" else "all",
        "scope": scope,
        "rows_selected": rows_selected,
        "cols_selected": len(target_cols),
        "cells_selected": cells_selected,
        "grand_total": grand_total,
        "grand_total_display": _format_number(grand_total, decimals=2) if grand_total is not None else None,
        "columns": columns,
        "aggregates": _build_aggregates(
            df,
            target_cells if scope == "selection" else [],
            target_rows,
            target_cols,
            numeric_values,
            cells_selected=cells_selected,
            rows_count=rows_selected,
        ),
    }
