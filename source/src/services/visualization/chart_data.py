"""Shared chart data preparation for session visualizations."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.services.visualization import resolve_palette


def resolve_df_column(df: pd.DataFrame, column_name: str):
    if df is None or not column_name:
        return None
    for column in df.columns:
        if str(column) == str(column_name):
            return column
    return None


def valid_chart_color(value: Any, fallback: str = "") -> str:
    color = str(value or "").strip()
    if not color:
        return fallback
    try:
        from matplotlib.colors import is_color_like

        return color if is_color_like(color) else fallback
    except Exception:
        return color if color.startswith("#") else fallback


def chart_color(config: dict, key: str, fallback: str) -> str:
    return valid_chart_color(config.get(key, ""), fallback)


def safe_chart_label(value: Any) -> str:
    text = str(value)
    text = "".join(char if char.isprintable() else " " for char in text).strip()
    if len(text) > 36:
        text = text[:33] + "..."
    return text or " "


def chart_max_points(config: dict) -> int:
    chart_type = str(config.get("type", "bar") or "bar")
    if chart_type == "pie":
        return 24
    if chart_type in {"line", "scatter", "area"}:
        return 500
    return 120


def chart_palette(config: dict, count: int) -> list[str]:
    try:
        from matplotlib.colors import is_color_like
    except Exception:
        is_color_like = lambda color: isinstance(color, str) and bool(str(color).strip())

    return resolve_palette(config, count, is_color_like=is_color_like)


def prepare_chart_data(df: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[str]]:
    """Pivot/aggregate source data into a chart-ready frame and x labels."""
    from src.language import S

    x_column = resolve_df_column(df, config.get("x_column", ""))
    y_columns = [resolve_df_column(df, column) for column in config.get("y_columns", []) or []]
    y_columns = [column for column in y_columns if column is not None]
    if not y_columns:
        raise ValueError(S.visualization.chart_no_y_column)

    group_column = resolve_df_column(df, config.get("group_by", ""))
    work = df.copy()
    if x_column is None:
        work["__datapyn_x__"] = [str(index) for index in work.index]
        x_key = "__datapyn_x__"
    else:
        x_key = x_column

    selected = [x_key] + y_columns
    if group_column is not None:
        selected.append(group_column)

    nulls = config.get("nulls", "zero")
    if nulls == "drop":
        work = work.dropna(subset=selected)

    aggregation = config.get("aggregation", "sum")
    for column in y_columns:
        if aggregation != "count":
            work[column] = pd.to_numeric(work[column], errors="coerce")
        if nulls == "zero":
            work[column] = work[column].fillna(0)

    if group_column is not None and len(y_columns) == 1:
        plot_data = work.pivot_table(
            index=x_key,
            columns=group_column,
            values=y_columns[0],
            aggfunc=aggregation,
            fill_value=0 if nulls == "zero" else None,
            dropna=False,
        )
        plot_data.columns = [str(column) for column in plot_data.columns]
    else:
        plot_data = work.groupby(x_key, dropna=False)[y_columns].agg(aggregation)
        plot_data.columns = [str(column) for column in plot_data.columns]

    plot_data = plot_data.apply(pd.to_numeric, errors="coerce")
    if nulls == "zero":
        plot_data = plot_data.fillna(0)
    else:
        plot_data = plot_data.dropna(how="all")

    if config.get("sort") == "x_asc":
        try:
            plot_data = plot_data.sort_index()
        except TypeError:
            plot_data = plot_data.sort_index(key=lambda index: index.astype(str))
    elif config.get("sort") == "y_desc" and not plot_data.empty:
        plot_data = plot_data.sort_values(by=plot_data.columns[0], ascending=False)

    if config.get("normalize") or config.get("stacking") == "percent":
        row_sums = plot_data.sum(axis=1).replace(0, pd.NA)
        plot_data = plot_data.div(row_sums, axis=0).fillna(0) * 100

    max_points = chart_max_points(config)
    if len(plot_data) > max_points:
        plot_data = plot_data.head(max_points)

    labels = [safe_chart_label(value) for value in plot_data.index]
    return plot_data, labels


def format_chart_number(value: Any, config: dict) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    decimals = int(config.get("label_decimals", 1) or 0)
    return f"{number:,.{decimals}f}"
