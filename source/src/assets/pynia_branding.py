"""Pynia brand assets — official logo and Qt icon helpers."""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).resolve().parent
PYNIA_LOGO_PATH = _ASSETS_DIR / "pynia_logo.svg"
PYNIA_ICON_PATH = _ASSETS_DIR / "icons" / "pynia_icon.svg"


def pynia_logo_svg_text() -> str:
    """Return raw SVG markup for the official Pynia logo."""
    return PYNIA_LOGO_PATH.read_text(encoding="utf-8")


def pynia_logo_data_uri() -> str:
    """Data URI for embedding the logo in WebEngine/HTML."""
    encoded = base64.b64encode(pynia_logo_svg_text().encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _render_svg(path: Path, size: int, *, recolor: str | None) -> QIcon | None:
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        if recolor:
            content = re.sub(r"fill\s*:\s*#[0-9a-fA-F]{3,6}", f"fill:{recolor}", content)
            content = re.sub(r'fill="[^"]*"', f'fill="{recolor}"', content)

        renderer = QSvgRenderer(QByteArray(content.encode("utf-8")))
        if not renderer.isValid():
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        view_box = renderer.viewBox()
        if view_box.width() > 0 and view_box.height() > 0:
            scale = min(size / view_box.width(), size / view_box.height())
            draw_w = view_box.width() * scale
            draw_h = view_box.height() * scale
            x = (size - draw_w) / 2
            y = (size - draw_h) / 2
            from PyQt6.QtCore import QRectF

            renderer.render(painter, QRectF(x, y, draw_w, draw_h))
        else:
            renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception as exc:
        logger.debug("Failed to render Pynia SVG %s: %s", path.name, exc)
        return None


def load_pynia_logo(size: int = 24) -> QIcon | None:
    """Load the official gradient Pynia logo at the given square size."""
    return _render_svg(PYNIA_LOGO_PATH, size, recolor=None)


def load_pynia_icon(size: int = 20, color: str | None = None) -> QIcon | None:
    """Load a Pynia icon for toolbars and buttons.

    Uses the official logo by default. Pass *color* to fall back to the
    monochrome sparkle mark when a flat tint is required.
    """
    if color is None:
        logo = load_pynia_logo(size)
        if logo is not None:
            return logo
    return _render_svg(PYNIA_ICON_PATH, size, recolor=color or "#9cdcfe")
