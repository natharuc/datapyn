"""
Toolbar principal da aplicacao
"""

import os
import re

from PyQt6.QtWidgets import QToolBar, QWidget, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, QSize, Qt, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
import qtawesome as qta

from src.language import S

# Default color for all toolbar icons (consistent)
_ICON_COLOR = "#b0b0b0"
_ICON_HOVER = "#ffffff"


def _load_copilot_icon(color: str, size: int = 20) -> QIcon:
    """Load Copilot SVG icon with custom color."""
    try:
        # Get path relative to this file (ui/components -> ui -> src -> assets/icons)
        components_dir = os.path.dirname(os.path.abspath(__file__))
        ui_dir = os.path.dirname(components_dir)
        src_dir = os.path.dirname(ui_dir)
        svg_path = os.path.join(src_dir, "assets", "icons", "copilot_icon.svg")

        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        # Replace all fill colors
        svg_content = re.sub(r"fill\s*:\s*#[0-9a-fA-F]{3,6}", f"fill:{color}", svg_content)
        svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)

        svg_bytes = QByteArray(svg_content.encode("utf-8"))
        renderer = QSvgRenderer(svg_bytes)

        if not renderer.isValid():
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)
    except Exception:
        return None


class MainToolbar(QToolBar):
    """Main toolbar"""

    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()
    copilot_clicked = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__("Main", parent)
        self.theme_manager = theme_manager
        self.setMovable(False)
        self.setIconSize(QSize(16, 16))
        self._setup_style()
        self._setup_buttons()

    def _setup_style(self):
        """Configure toolbar style"""
        self.setStyleSheet(f"""
            QToolBar {{
                background-color: #252526;
                border: none;
                border-bottom: 1px solid #3e3e42;
                padding: 2px 6px;
                spacing: 2px;
            }}
            QToolBar::separator {{
                background-color: #3e3e42;
                width: 1px;
                margin: 6px 4px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {_ICON_COLOR};
                border: none;
                padding: 5px 10px;
                font-size: 12px;
                border-radius: 0px;
            }}
            QPushButton:hover {{
                background-color: #37373d;
                color: {_ICON_HOVER};
            }}
            QPushButton:pressed {{
                background-color: #2d2d30;
            }}
        """)

    def _setup_buttons(self):
        """Buttons with uniform icons"""
        # New Tab
        self.btn_new_tab = QPushButton(S.toolbar.new_tab)
        self.btn_new_tab.setIcon(qta.icon("mdi.tab-plus", color=_ICON_COLOR))
        self.btn_new_tab.clicked.connect(self.new_tab_clicked.emit)
        self.addWidget(self.btn_new_tab)

        self.addSeparator()

        # Connection
        self.btn_new_conn = QPushButton(S.toolbar.connection)
        self.btn_new_conn.setIcon(qta.icon("mdi.database-plus", color=_ICON_COLOR))
        self.btn_new_conn.clicked.connect(self.new_connection_clicked.emit)
        self.addWidget(self.btn_new_conn)

        self.addSeparator()

        # Run
        self.btn_run = QPushButton(S.toolbar.run)
        self.btn_run.setIcon(qta.icon("mdi.play", color=_ICON_COLOR))
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.addWidget(self.btn_run)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        # Copilot button (right side) - icon only
        self.btn_copilot = QPushButton()
        copilot_icon = _load_copilot_icon("#9cdcfe", size=18)
        if copilot_icon:
            self.btn_copilot.setIcon(copilot_icon)
        else:
            self.btn_copilot.setIcon(qta.icon("mdi.robot", color="#9cdcfe"))
        self.btn_copilot.setIconSize(QSize(18, 18))
        self.btn_copilot.setToolTip("Copilot")
        self.btn_copilot.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(86, 156, 214, 0.1);
                padding: 6px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(86, 156, 214, 0.25);
            }}
            QPushButton:pressed {{
                background-color: rgba(86, 156, 214, 0.35);
            }}
        """)
        self.btn_copilot.clicked.connect(self.copilot_clicked.emit)
        self.addWidget(self.btn_copilot)

    def apply_theme(self):
        pass
