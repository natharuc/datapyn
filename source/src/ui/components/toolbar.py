"""
Toolbar principal da aplicacao
"""

import os
import re

from PyQt6.QtWidgets import QToolBar, QWidget, QPushButton, QSizePolicy, QComboBox
from PyQt6.QtCore import pyqtSignal, QSize, Qt, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
import qtawesome as qta

from src.language import S
from src.core.workspace_service import get_workspace_service

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
    workspace_switch_requested = pyqtSignal(str)  # path
    workspace_settings_requested = pyqtSignal()  # open settings on workspace tab

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
                border-radius: 8px;
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

        self.addSeparator()

        # Workspace selector
        self._setup_workspace_selector()

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

    def _setup_workspace_selector(self):
        """Setup workspace dropdown selector."""
        self.workspace_combo = QComboBox()
        self.workspace_combo.setFixedWidth(140)
        self.workspace_combo.setToolTip("Workspace")
        self.workspace_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: #2d2d30;
                color: {_ICON_COLOR};
                border: 1px solid #3e3e42;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox:hover {{
                border-color: #007acc;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {_ICON_COLOR};
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #2d2d30;
                color: {_ICON_COLOR};
                border: 1px solid #3e3e42;
                selection-background-color: #007acc;
            }}
        """)
        
        self._refresh_workspace_combo()
        self.workspace_combo.currentIndexChanged.connect(self._on_workspace_selected)
        self.addWidget(self.workspace_combo)
        
        # Config button to open workspace settings
        self.workspace_config_btn = QPushButton()
        self.workspace_config_btn.setIcon(qta.icon("fa5s.cog", color=_ICON_COLOR))
        self.workspace_config_btn.setToolTip("Workspace settings")
        self.workspace_config_btn.setFixedSize(24, 24)
        self.workspace_config_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
            }}
        """)
        self.workspace_config_btn.clicked.connect(self.workspace_settings_requested.emit)
        self.addWidget(self.workspace_config_btn)
        
        # Connect to workspace service signals for auto-refresh
        ws_service = get_workspace_service()
        ws_service.workspace_added.connect(self._refresh_workspace_combo)
        ws_service.workspace_removed.connect(self._refresh_workspace_combo)
    
    def _refresh_workspace_combo(self, *args):
        """Refresh workspace combo box items."""
        ws_service = get_workspace_service()
        workspaces = ws_service.list_workspaces()
        current = ws_service.current_workspace
        
        self.workspace_combo.blockSignals(True)
        self.workspace_combo.clear()
        
        current_index = 0
        for i, (name, path) in enumerate(workspaces):
            self.workspace_combo.addItem(name, str(path))
            if path == current:
                current_index = i
        
        self.workspace_combo.setCurrentIndex(current_index)
        self.workspace_combo.blockSignals(False)
    
    def _on_workspace_selected(self, index: int):
        """Handle workspace selection change."""
        if index < 0:
            return
        path = self.workspace_combo.itemData(index)
        if path:
            self.workspace_switch_requested.emit(path)

    def apply_theme(self):
        pass
