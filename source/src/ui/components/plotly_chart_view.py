"""Embedded interactive Plotly chart via QWebEngineView."""

from __future__ import annotations

import os
import tempfile

from PyQt6 import sip
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from src.design_system.tokens import get_colors

_BLANK_HTML = (
    "<html><head><style>html,body{margin:0;background:#181a1f;}</style></head>"
    "<body style='margin:0;background:#181a1f;color:#9aa3b5;"
    "font-family:sans-serif;display:flex;align-items:center;"
    "justify-content:center;height:100vh;'></body></html>"
)

_AFTER_LOAD_SCRIPT = """
document.documentElement.style.background = '#181a1f';
document.body.style.background = '#181a1f';
document.body.style.margin = '0';
var plot = document.querySelector('.plotly-graph-div');
if (plot) { plot.style.background = '#181a1f'; }
if (window.Plotly && plot) { Plotly.Plots.resize(plot); }
"""


class _ChartWebPage(QWebEnginePage):
    """Keep chart navigation inside the view."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if not is_main_frame:
            return True
        scheme = url.scheme().lower()
        if scheme in ("about", "data", "file", ""):
            return True
        return False


class PlotlyChartView(QWidget):
    """Renders Plotly HTML with zoom, pan, and hover tooltips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotlyChartView")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cleaned_up = False
        self._temp_html_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._webview = QWebEngineView(self)
        self._webview.setPage(_ChartWebPage(self._webview))
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)
        self._webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._webview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._webview.loadFinished.connect(self._on_load_finished)
        layout.addWidget(self._webview)

        colors = get_colors()
        chart_bg = QColor("#181a1f")
        palette = self._webview.palette()
        palette.setColor(QPalette.ColorRole.Window, chart_bg)
        palette.setColor(QPalette.ColorRole.Base, chart_bg)
        self._webview.setPalette(palette)
        self._webview.setAutoFillBackground(True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"""
            QWidget#plotlyChartView {{
                background-color: {colors.bg_primary};
                border: none;
            }}
            QWebEngineView {{
                background-color: #181a1f;
                border: none;
            }}
            """
        )

        self._html: str | None = None
        self._load_blank()

    def _load_blank(self) -> None:
        webview = getattr(self, "_webview", None)
        if webview is None or sip.isdeleted(webview):
            return
        webview.setHtml(_BLANK_HTML, QUrl("about:blank"))

    def _remove_temp_file(self) -> None:
        path = self._temp_html_path
        self._temp_html_path = None
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _on_load_finished(self, ok: bool) -> None:
        if self._cleaned_up or not ok:
            return
        webview = getattr(self, "_webview", None)
        if webview is None or sip.isdeleted(webview):
            return
        page = webview.page()
        if page is not None and not sip.isdeleted(page):
            page.runJavaScript(_AFTER_LOAD_SCRIPT)

    def set_html(self, html: str | None) -> None:
        if self._cleaned_up:
            return
        webview = getattr(self, "_webview", None)
        if webview is None or sip.isdeleted(webview):
            return

        self._html = html
        self._remove_temp_file()
        if not html:
            self._load_blank()
            return

        handle, path = tempfile.mkstemp(prefix="datapyn_chart_", suffix=".html")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as handle_file:
                handle_file.write(html)
        except Exception:
            os.close(handle)
            raise
        self._temp_html_path = path
        webview.load(QUrl.fromLocalFile(os.path.abspath(path)))

    def html(self) -> str | None:
        return self._html

    def clear(self) -> None:
        self.set_html(None)

    def cleanup(self) -> None:
        """Release WebEngine page/view before widget destruction (avoids Qt crashes)."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self._html = None
        self._remove_temp_file()

        webview = getattr(self, "_webview", None)
        if webview is None or sip.isdeleted(webview):
            self._webview = None
            return

        try:
            webview.stop()
            page = webview.page()
            if page is not None and not sip.isdeleted(page):
                replacement_page = QWebEnginePage(webview)
                webview.setPage(replacement_page)
                sip.delete(page)
            self._load_blank()
            webview.close()
        except RuntimeError:
            pass

        try:
            sip.delete(webview)
        except RuntimeError:
            pass
        self._webview = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
