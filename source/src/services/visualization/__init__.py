"""Session chart rendering helpers."""

from importlib import import_module

_EXPORTS = {
    "apply_matplotlib_chart_theme": ".chart_style",
    "chart_palettes": ".chart_style",
    "resolve_palette": ".chart_style",
    "prepare_chart_data": ".chart_data",
    "render_session_chart_html": ".plotly_charts",
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "apply_matplotlib_chart_theme",
    "chart_palettes",
    "resolve_palette",
    "prepare_chart_data",
    "render_session_chart_html",
]
