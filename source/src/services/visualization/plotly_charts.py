"""Interactive Plotly charts for DataPyn session visualizations."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.design_system.tokens import get_chart_colors
from src.services.visualization.chart_data import (
    chart_color,
    chart_palette,
    format_chart_number,
    prepare_chart_data,
)


def _opacity(config: dict, key: str, default_percent: int) -> float:
    try:
        value = int(config.get(key, default_percent))
    except (TypeError, ValueError):
        value = default_percent
    return max(0.0, min(1.0, value / 100.0))


def _line_dash(config: dict) -> str | None:
    return {
        "solid": None,
        "dashed": "dash",
        "dotted": "dot",
        "dashdot": "dashdot",
    }.get(str(config.get("line_style", "solid") or "solid"))


def _axis_layout(title_text: str, text: str, grid: str, axis_line: str, show_grid: bool) -> dict[str, Any]:
    axis: dict[str, Any] = {
        "title": {"text": str(title_text or ""), "font": {"color": text, "size": 12}},
        "tickfont": {"color": text, "size": 11},
        "gridcolor": grid,
        "linecolor": axis_line,
        "showgrid": show_grid,
        "zeroline": False,
    }
    return axis


def _layout(config: dict) -> dict[str, Any]:
    chart_colors = get_chart_colors()
    paper = chart_color(config, "background_color", chart_colors.figure_bg)
    plot_bg = chart_color(config, "background_color", chart_colors.axes_bg)
    text = chart_color(config, "text_color", chart_colors.text)
    grid = chart_color(config, "grid_color", chart_colors.grid)
    axis_line = chart_color(config, "axis_color", chart_colors.axes_edge)
    show_grid = bool(config.get("show_grid", True))

    layout: dict[str, Any] = {
        "paper_bgcolor": paper,
        "plot_bgcolor": plot_bg,
        "font": {"family": "Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif", "color": text, "size": 12},
        "margin": {"l": 56, "r": 24, "t": 56 if config.get("title") else 32, "b": 72},
        "hovermode": "x unified",
        "hoverlabel": {"bgcolor": paper, "bordercolor": axis_line, "font": {"color": text}},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"color": text},
            "bgcolor": "rgba(0,0,0,0)",
        },
        "xaxis": _axis_layout(
            config.get("x_label") or config.get("x_column") or "",
            text,
            grid,
            axis_line,
            show_grid,
        ),
        "yaxis": _axis_layout(
            config.get("y_label")
            or ("%" if config.get("normalize") or config.get("stacking") == "percent" else ""),
            text,
            grid,
            axis_line,
            show_grid,
        ),
    }
    title = str(config.get("title", "") or "").strip()
    if title:
        layout["title"] = {"text": title, "x": 0, "xanchor": "left", "font": {"size": 16, "color": text}}
    if not config.get("show_legend", True):
        layout["showlegend"] = False
    if not bool(config.get("show_axis_line", False)):
        layout["xaxis"]["showline"] = False
        layout["yaxis"]["showline"] = False
    return layout


def _text_labels(values, config: dict) -> list[str] | None:
    if not config.get("show_data_labels"):
        return None
    return [format_chart_number(value, config) for value in values]


def _add_cartesian_traces(fig, plot_data: pd.DataFrame, labels: list[str], config: dict, colors: list[str]) -> None:
    import plotly.graph_objects as go

    chart_type = str(config.get("type", "bar") or "bar")
    stacked = config.get("stacking") in {"stacked", "percent"}
    horizontal = bool(config.get("horizontal", False)) and chart_type == "bar"
    series_names = list(plot_data.columns)
    barmode = "relative" if stacked else "group"

    if chart_type == "pie":
        return

    if chart_type == "bar":
        for index, name in enumerate(series_names):
            values = plot_data[name].fillna(0).astype(float).tolist()
            trace_kwargs = {
                "name": str(name),
                "marker": {"color": colors[index % len(colors)], "line": {"width": 0}},
                "opacity": _opacity(config, "bar_opacity", 94),
            }
            text = _text_labels(values, config)
            if text:
                trace_kwargs["text"] = text
                trace_kwargs["textposition"] = "outside" if not horizontal else "auto"
            if horizontal:
                fig.add_trace(go.Bar(y=labels, x=values, orientation="h", **trace_kwargs))
            else:
                fig.add_trace(go.Bar(x=labels, y=values, **trace_kwargs))
        fig.update_layout(barmode=barmode)
        if horizontal:
            fig.update_yaxes(categoryorder="array", categoryarray=labels)
        else:
            fig.update_xaxes(categoryorder="array", categoryarray=labels)
        return

    if chart_type == "area":
        fill_mode = "tonexty" if stacked else "tozeroy"
        for index, name in enumerate(series_names):
            values = plot_data[name].fillna(0).astype(float).tolist()
            fig.add_trace(
                go.Scatter(
                    x=labels,
                    y=values,
                    name=str(name),
                    mode="lines",
                    line={"color": colors[index % len(colors)], "width": int(config.get("line_width", 2) or 2)},
                    fill=fill_mode if index else "tozeroy",
                    stackgroup="one" if stacked else None,
                    fillcolor=_rgba(colors[index % len(colors)], _opacity(config, "area_opacity", 35)),
                    opacity=0.95,
                )
            )
        return

    show_line = bool(config.get("show_line", True))
    show_markers = bool(config.get("show_markers", True))
    marker_size = max(4, int(config.get("marker_size", 6) or 6))
    line_width = max(1, int(config.get("line_width", 2) or 2))
    dash = _line_dash(config)

    for index, name in enumerate(series_names):
        values = plot_data[name].astype(float).tolist()
        color = colors[index % len(colors)]
        if chart_type == "scatter":
            mode = "markers"
        elif show_line and show_markers:
            mode = "lines+markers"
        elif show_line:
            mode = "lines"
        else:
            mode = "markers"
        trace = go.Scatter(
            x=labels,
            y=values,
            name=str(name),
            mode=mode,
            line={"color": color, "width": line_width, "dash": dash},
            marker={"color": color, "size": marker_size, "line": {"width": 0}},
            text=_text_labels(values, config),
            textposition="top center",
        )
        fig.add_trace(trace)


def _rgba(hex_color: str, alpha: float) -> str:
    try:
        from matplotlib.colors import to_rgb

        r, g, b = to_rgb(hex_color)
        return f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{alpha:.3f})"
    except Exception:
        return hex_color


def _build_pie(fig, plot_data: pd.DataFrame, config: dict, colors: list[str]) -> None:
    import plotly.graph_objects as go

    series = plot_data.iloc[:, 0].fillna(0).astype(float)
    series = series[series > 0]
    if series.empty:
        from src.language import S

        raise ValueError(S.visualization.chart_no_data)

    labels = [str(label) for label in series.index]
    values = series.to_numpy().tolist()
    textinfo = "label+percent" if config.get("show_data_labels") else "label"
    fig.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            marker={"colors": colors[: len(values)], "line": {"color": chart_color(config, "background_color", "#14161b"), "width": 2}},
            textinfo=textinfo,
            textfont={"size": 11},
            sort=False,
        )
    )
    fig.update_layout(showlegend=bool(config.get("show_legend", True)))


def render_session_chart_html(df: pd.DataFrame, config: dict) -> str:
    """Build a self-contained interactive Plotly HTML document."""
    from src.language import S

    if df is None or df.empty:
        raise ValueError(S.visualization.chart_no_data)

    import plotly.graph_objects as go

    plot_data, labels = prepare_chart_data(df, config)
    if plot_data.empty:
        raise ValueError(S.visualization.chart_no_data)

    colors = chart_palette(config, len(plot_data.columns))
    fig = go.Figure()
    chart_type = str(config.get("type", "bar") or "bar")

    if chart_type == "pie":
        _build_pie(fig, plot_data, config, colors)
        layout = _layout(config)
        layout["margin"] = {"l": 12, "r": 12, "t": 48, "b": 12}
        layout["xaxis"] = {"visible": False}
        layout["yaxis"] = {"visible": False}
        fig.update_layout(**layout)
    else:
        _add_cartesian_traces(fig, plot_data, labels, config, colors)
        layout = _layout(config)
        if len(labels) > 8 and not (config.get("horizontal") and chart_type == "bar"):
            layout["xaxis"]["tickangle"] = -35
            layout["margin"]["b"] = 96
        fig.update_layout(**layout)

    html = fig.to_html(
        include_plotlyjs="inline",
        full_html=True,
        config={
            "displayModeBar": True,
            "scrollZoom": True,
            "responsive": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )
    return _inject_dark_page_style(html, chart_color(config, "background_color", get_chart_colors().figure_bg))


def _inject_dark_page_style(html: str, background: str) -> str:
    """Force Plotly page/modebar backgrounds to match the app dark theme."""
    bg = str(background or "#181a1f")
    dark_css = f"""
<style>
html, body {{
    margin: 0 !important;
    padding: 0 !important;
    background: {bg} !important;
    background-color: {bg} !important;
    overflow: hidden;
}}
.plotly-graph-div, .js-plotly-plot, .plot-container, .svg-container {{
    background: {bg} !important;
    background-color: {bg} !important;
}}
.modebar, .modebar-group, .modebar-btn {{
    background: rgba(24, 26, 31, 0.92) !important;
}}
.modebar-btn path {{
    fill: #b8bcc8 !important;
}}
</style>
"""
    lower = html.lower()
    if "</head>" in lower:
        index = lower.index("</head>")
        return html[:index] + dark_css + html[index:]
    return dark_css + html
