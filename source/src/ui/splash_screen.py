"""
Splash Screen - Tela de carregamento do DataPyn

Exibe o logo imediatamente após QApplication; atualiza barra de progresso durante o boot.
"""

from __future__ import annotations

import functools
import os
import sys

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QRegion,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QSplashScreen

# DataPyn brand (site / installer)
C_BG = QColor("#0c111b")
C_BG_DEEP = QColor("#070b12")
C_TEXT = QColor("#eef2f7")
C_MUTED = QColor("#8b9cb3")
C_DIM = QColor("#5c6d85")
C_ACCENT = QColor("#3369ff")
C_CYAN = QColor("#33c2ff")
C_BAR_BG = QColor("#161f30")

_ROUND_RADIUS = 14


def _assets_base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "src", "assets")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _svg_path() -> str:
    return os.path.join(_assets_base(), "datapyn_logo.svg")


@functools.lru_cache(maxsize=1)
def _get_version() -> str:
    try:
        import tomllib

        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
        pyproject = os.path.join(base, "pyproject.toml")
        if os.path.isfile(pyproject):
            with open(pyproject, "rb") as handle:
                data = tomllib.load(handle)
            return str(data.get("project", {}).get("version", "")) or "1.0.0"
    except Exception:
        pass
    return "1.0.0"


def _ui_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    if sys.platform == "win32":
        family = "Segoe UI"
    elif sys.platform == "darwin":
        font = QFont()
        font.setPointSize(size)
        font.setWeight(weight)
        return font
    else:
        family = "Ubuntu"
    font = QFont(family, size, weight)
    if not font.exactMatch() and family != "Segoe UI":
        font = QFont()
        font.setPointSize(size)
        font.setWeight(weight)
    return font


def _transparent_pixmap(width: int, height: int) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _rounded_rect_path(width: int, height: int, radius: float = _ROUND_RADIUS) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    return path


class SplashScreen(QSplashScreen):
    """Splash com frame estático em cache e overlay leve de progresso."""

    WIDTH = 460
    HEIGHT = 340

    _LOGO_SIZE = 108
    _BAR_MARGIN = 56
    _BAR_Y = HEIGHT - 72
    _BAR_H = 6

    def __init__(self):
        super().__init__(_transparent_pixmap(self.WIDTH, self.HEIGHT))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._progress = 0
        self._status_text = "Iniciando…"
        self._version = _get_version()

        svg = _svg_path()
        self._svg_renderer = QSvgRenderer(svg) if os.path.isfile(svg) else None

        self._base_pixmap = _transparent_pixmap(self.WIDTH, self.HEIGHT)
        self._paint_static(self._base_pixmap)
        self._apply_progress_overlay()
        self._apply_rounded_mask()

    def _apply_rounded_mask(self) -> None:
        path = _rounded_rect_path(self.WIDTH, self.HEIGHT)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _paint_static(self, target: QPixmap) -> None:
        target.fill(Qt.GlobalColor.transparent)
        rounded = _rounded_rect_path(self.WIDTH, self.HEIGHT)

        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        grad_bg = QLinearGradient(0, 0, 0, self.HEIGHT)
        grad_bg.setColorAt(0, C_BG)
        grad_bg.setColorAt(1, C_BG_DEEP)
        painter.fillPath(rounded, grad_bg)

        painter.setClipPath(rounded)

        border_pen = QColor(148, 163, 184, 40)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.WIDTH - 1, self.HEIGHT - 1), _ROUND_RADIUS, _ROUND_RADIUS)

        logo_x = (self.WIDTH - self._LOGO_SIZE) // 2
        logo_y = 52
        if self._svg_renderer and self._svg_renderer.isValid():
            self._svg_renderer.render(
                painter, QRectF(logo_x, logo_y, self._LOGO_SIZE, self._LOGO_SIZE)
            )

        title_y = logo_y + self._LOGO_SIZE + 14
        painter.setFont(_ui_font(20, QFont.Weight.Bold))
        painter.setPen(C_TEXT)
        painter.drawText(QRectF(0, title_y, self.WIDTH, 30), Qt.AlignmentFlag.AlignCenter, "DataPyn")

        painter.setFont(_ui_font(10))
        painter.setPen(C_MUTED)
        painter.drawText(
            QRectF(0, title_y + 28, self.WIDTH, 22),
            Qt.AlignmentFlag.AlignCenter,
            "SQL + Python · Pynia",
        )

        painter.setFont(_ui_font(9))
        painter.setPen(C_DIM)
        painter.drawText(
            QRectF(0, self.HEIGHT - 36, self.WIDTH, 18),
            Qt.AlignmentFlag.AlignCenter,
            f"v{self._version}",
        )

        painter.end()

    def _apply_progress_overlay(self) -> None:
        pixmap = self._base_pixmap.copy()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(_rounded_rect_path(self.WIDTH, self.HEIGHT))

        bar_x = self._BAR_MARGIN
        bar_w = self.WIDTH - 2 * self._BAR_MARGIN
        bar_y = self._BAR_Y

        track = QPainterPath()
        track.addRoundedRect(QRectF(bar_x, bar_y, bar_w, self._BAR_H), 3, 3)
        painter.fillPath(track, C_BAR_BG)

        if self._progress > 0:
            fill_w = max(self._BAR_H, bar_w * self._progress / 100)
            grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
            grad.setColorAt(0, C_ACCENT)
            grad.setColorAt(1, C_CYAN)
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(bar_x, bar_y, fill_w, self._BAR_H), 3, 3)
            painter.fillPath(fill, grad)

        painter.setFont(_ui_font(9))
        painter.setPen(C_MUTED)
        painter.drawText(
            QRectF(bar_x, bar_y + 12, bar_w, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._status_text,
        )

        painter.end()
        self.setPixmap(pixmap)

    def set_progress(self, value: int, status: str = "") -> None:
        self._progress = max(0, min(100, value))
        if status:
            self._status_text = status
        self._apply_progress_overlay()
        self.repaint()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def finish_with_window(self, window) -> None:
        self.set_progress(100, "Pronto!")
        QTimer.singleShot(120, lambda: self._do_finish(window))

    def _do_finish(self, window) -> None:
        self.finish(window)
        window.show()
