"""
Toolbar principal da aplicacao
"""

from PyQt6.QtWidgets import QToolBar, QWidget, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, QSize
import qtawesome as qta

from src.language import S

# Default color for all toolbar icons (consistent)
_ICON_COLOR = "#b0b0b0"
_ICON_HOVER = "#ffffff"


class MainToolbar(QToolBar):
    """Main toolbar"""

    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()

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
                border-radius: 3px;
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

    def apply_theme(self):
        pass
