"""Matplotlib chart theme and palettes for DataPyn visualizations."""

from __future__ import annotations

from typing import Any

_THEME_APPLIED = False


def apply_matplotlib_chart_theme() -> None:
    """One-time rcParams tuned for dark, clean session charts."""
    global _THEME_APPLIED
    if _THEME_APPLIED:
        return
    try:
        import matplotlib as mpl
    except ImportError:
        return

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
            "font.size": 10,
            "axes.titlesize": 15,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "axes.facecolor": "#1a1d24",
            "figure.facecolor": "#14161b",
            "axes.edgecolor": "#4a5162",
            "axes.labelcolor": "#d8dbe3",
            "xtick.color": "#9aa3b5",
            "ytick.color": "#9aa3b5",
            "text.color": "#d8dbe3",
            "grid.color": "#3d4455",
            "grid.linestyle": "--",
            "grid.linewidth": 0.65,
            "grid.alpha": 0.45,
            "axes.grid": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "figure.dpi": 120,
            "savefig.dpi": 120,
            "lines.antialiased": True,
            "patch.antialiased": True,
        }
    )
    _THEME_APPLIED = True


def chart_palettes() -> dict[str, list[str]]:
    return {
        "default": ["#5b8def", "#3ddc97", "#f6c343", "#f472b6", "#a78bfa", "#38bdf8", "#fb923c"],
        "categorical": ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#c084fc", "#22d3ee"],
        "teal": ["#2dd4bf", "#14b8a6", "#38bdf8", "#5b8def", "#818cf8", "#a5b4fc"],
        "warm": ["#fb923c", "#f59e0b", "#f472b6", "#ef4444", "#c026d3", "#a855f7"],
        "ocean": ["#0ea5e9", "#06b6d4", "#14b8a6", "#3b82f6", "#6366f1", "#8b5cf6"],
    }


def resolve_palette(config: dict, count: int, *, is_color_like) -> list[str]:
    custom = [
        color
        for color in config.get("custom_colors", []) or []
        if isinstance(color, str) and is_color_like(color)
    ]
    if custom:
        base = custom
    else:
        palettes = chart_palettes()
        key = str(config.get("palette", "default") or "default")
        base = palettes.get(key, palettes["default"])
    return [base[index % len(base)] for index in range(max(1, count))]


def lighten_edge_color(fill: str, amount: float = 0.12) -> str:
    try:
        from matplotlib.colors import to_rgb, to_hex
        import colorsys

        r, g, b = to_rgb(fill)
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        l = min(1.0, l + amount)
        return to_hex(colorsys.hls_to_rgb(h, l, s))
    except Exception:
        return fill
