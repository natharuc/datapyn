"""
Splash Screen - Tela de carregamento do DataPyn

Exibe o logo SVG com barra de progresso enquanto a aplicacao inicializa.
"""

import os
import sys

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSplashScreen


def _get_svg_path() -> str:
    """Retorna caminho do logo SVG, funciona em dev e no EXE"""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, "src", "assets", "datapyn_logo.svg") if getattr(sys, "frozen", False) else os.path.join(base_path, "assets", "datapyn_logo.svg")


def _get_version() -> str:
    """Le versao do pyproject.toml"""
    try:
        import tomllib

        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
        pyproject_path = os.path.join(base_path, "pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                return data.get("project", {}).get("version", "1.0.0")
    except Exception:
        pass
    return "1.0.0"


class SplashScreen(QSplashScreen):
    """Splash screen com logo SVG, barra de progresso e mensagens de status."""

    # Dimensoes
    WIDTH = 480
    HEIGHT = 360

    # Cores
    BG_COLOR = QColor("#181A20")
    ACCENT_COLOR = QColor("#3369FF")
    ACCENT_END = QColor("#6C8CFF")
    TEXT_COLOR = QColor("#CCCCCC")
    TEXT_DIM = QColor("#888888")
    BAR_BG = QColor("#2D2D30")

    def __init__(self):
        # Cria pixmap base
        pixmap = QPixmap(self.WIDTH, self.HEIGHT)
        pixmap.fill(Qt.GlobalColor.transparent)
        super().__init__(pixmap)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self._progress = 0
        self._status_text = "Initializing..."
        self._version = _get_version()

        # Carrega SVG
        svg_path = _get_svg_path()
        self._svg_renderer = None
        if os.path.exists(svg_path):
            self._svg_renderer = QSvgRenderer(svg_path)

        # Renderiza o pixmap completo
        self._render_pixmap()

    def _render_pixmap(self):
        """Renderiza o splash completo no pixmap."""
        pixmap = QPixmap(self.WIDTH, self.HEIGHT)
        pixmap.fill(self.BG_COLOR)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # -- Borda sutil arredondada --
        border_path = QPainterPath()
        border_path.addRoundedRect(QRectF(0, 0, self.WIDTH, self.HEIGHT), 12, 12)
        painter.setClipPath(border_path)
        painter.fillPath(border_path, self.BG_COLOR)

        # Linha accent no topo
        grad_top = QLinearGradient(0, 0, self.WIDTH, 0)
        grad_top.setColorAt(0, self.ACCENT_COLOR)
        grad_top.setColorAt(1, self.ACCENT_END)
        painter.fillRect(0, 0, self.WIDTH, 3, grad_top)

        # -- Logo SVG --
        logo_size = 128
        logo_x = (self.WIDTH - logo_size) // 2
        logo_y = 40
        if self._svg_renderer:
            self._svg_renderer.render(
                painter, QRectF(logo_x, logo_y, logo_size, logo_size)
            )

        # -- Titulo --
        title_y = logo_y + logo_size + 16
        font_title = QFont("Segoe UI", 22, QFont.Weight.Bold)
        painter.setFont(font_title)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            QRectF(0, title_y, self.WIDTH, 36),
            Qt.AlignmentFlag.AlignCenter,
            "DataPyn",
        )

        # -- Subtitulo --
        sub_y = title_y + 34
        font_sub = QFont("Segoe UI", 10)
        painter.setFont(font_sub)
        painter.setPen(self.TEXT_DIM)
        painter.drawText(
            QRectF(0, sub_y, self.WIDTH, 20),
            Qt.AlignmentFlag.AlignCenter,
            "Data Analysis Tool",
        )

        # -- Versao --
        font_ver = QFont("Segoe UI", 8)
        painter.setFont(font_ver)
        painter.setPen(self.TEXT_DIM)
        painter.drawText(
            QRectF(0, self.HEIGHT - 28, self.WIDTH, 20),
            Qt.AlignmentFlag.AlignCenter,
            f"v{self._version}",
        )

        # -- Barra de progresso (fundo) --
        bar_x = 60
        bar_y = self.HEIGHT - 60
        bar_w = self.WIDTH - 120
        bar_h = 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.BAR_BG)
        bar_path = QPainterPath()
        bar_path.addRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)
        painter.drawPath(bar_path)

        # -- Barra de progresso (preenchida) --
        if self._progress > 0:
            fill_w = bar_w * self._progress / 100
            grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
            grad.setColorAt(0, self.ACCENT_COLOR)
            grad.setColorAt(1, self.ACCENT_END)
            painter.setBrush(grad)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)
            painter.drawPath(fill_path)

        # -- Texto de status --
        status_y = bar_y + 10
        font_status = QFont("Segoe UI", 8)
        painter.setFont(font_status)
        painter.setPen(self.TEXT_DIM)
        painter.drawText(
            QRectF(bar_x, status_y, bar_w, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._status_text,
        )

        painter.end()
        self.setPixmap(pixmap)

    def set_progress(self, value: int, status: str = ""):
        """Atualiza progresso (0-100) e mensagem de status."""
        self._progress = max(0, min(100, value))
        if status:
            self._status_text = status
        self._render_pixmap()
        self.repaint()
        # Processa eventos para manter splash responsivo
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def finish_with_window(self, window):
        """Anima o fechamento do splash e mostra a janela."""
        self.set_progress(100, "Ready!")
        # Pequeno delay para o usuario ver 100%
        QTimer.singleShot(300, lambda: self._do_finish(window))

    def _do_finish(self, window):
        """Fecha o splash e mostra a janela principal."""
        self.finish(window)
        window.show()
