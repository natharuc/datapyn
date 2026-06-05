"""
Toolbar principal da aplicacao
"""

from PyQt6.QtWidgets import QToolBar, QWidget, QPushButton, QSizePolicy, QComboBox
from PyQt6.QtCore import pyqtSignal, QSize, Qt
import qtawesome as qta

from src.assets.pynia_branding import load_pynia_logo

from src.language import S
from src.core.workspace_service import get_workspace_service
from src.design_system.tokens import get_colors


class MainToolbar(QToolBar):
    """Main toolbar"""

    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()
    run_timer_clicked = pyqtSignal()
    pynia_clicked = pyqtSignal()
    copilot_clicked = pyqtSignal()  # legacy alias — do not connect both to the same slot
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
        colors = get_colors()
        icon_color = colors.text_secondary
        icon_hover = colors.text_primary
        self.setStyleSheet(f"""
            QToolBar {{
                background-color: {colors.bg_secondary};
                border: none;
                border-bottom: 1px solid {colors.border_muted};
                padding: 2px 6px;
                spacing: 2px;
            }}
            QToolBar::separator {{
                background-color: {colors.border_muted};
                width: 1px;
                margin: 6px 4px;
            }}
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {colors.bg_elevated};
            }}
            QPushButton {{
                background-color: transparent;
                color: {icon_color};
                border: none;
                padding: 5px 10px;
                font-size: 12px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_elevated};
                color: {icon_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        self._icon_color = icon_color
        self._icon_hover = icon_hover

    def _setup_buttons(self):
        """Buttons with uniform icons"""
        # New Tab
        self.btn_new_tab = QPushButton(S.toolbar.new_tab)
        self.btn_new_tab.setIcon(qta.icon("mdi.tab-plus", color=self._icon_color))
        self.btn_new_tab.clicked.connect(self.new_tab_clicked.emit)
        self.addWidget(self.btn_new_tab)

        self.addSeparator()

        # Connection
        self.btn_new_conn = QPushButton(S.toolbar.connection)
        self.btn_new_conn.setIcon(qta.icon("mdi.database-plus", color=self._icon_color))
        self.btn_new_conn.clicked.connect(self.new_connection_clicked.emit)
        self.addWidget(self.btn_new_conn)

        self.addSeparator()

        # Run
        self.btn_run = QPushButton(S.toolbar.run)
        self.btn_run.setIcon(qta.icon("mdi.play", color=self._icon_color))
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.addWidget(self.btn_run)

        # Run Timer (repeat execution at interval)
        self.btn_run_timer = QPushButton()
        self.btn_run_timer.setIcon(qta.icon("mdi.timer", color=self._icon_color))
        self.btn_run_timer.setToolTip(S.toolbar.run_timer)
        self.btn_run_timer.clicked.connect(self.run_timer_clicked.emit)
        self.addWidget(self.btn_run_timer)

        self.addSeparator()

        # Workspace selector
        self._setup_workspace_selector()

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        # Pynia button (right side) - icon only
        self.btn_pynia = QPushButton()
        self.btn_copilot = self.btn_pynia  # backward compat
        pynia_icon = load_pynia_logo(18)
        if pynia_icon:
            self.btn_pynia.setIcon(pynia_icon)
        else:
            self.btn_pynia.setIcon(qta.icon("mdi.robot", color="#9cdcfe"))
        self.btn_pynia.setIconSize(QSize(18, 18))
        pynia_tip = getattr(S.dock, "copilot", "Pynia") if hasattr(S, "dock") else "Pynia"
        self.btn_pynia.setToolTip(pynia_tip)
        self.btn_pynia.setStyleSheet(f"""
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
        self.btn_pynia.clicked.connect(self._on_pynia_button_clicked)
        self.addWidget(self.btn_pynia)

    def _on_pynia_button_clicked(self):
        """Emit a single click signal (avoid double-toggle if both signals were wired)."""
        self.pynia_clicked.emit()

    def _setup_workspace_selector(self):
        """Setup workspace dropdown selector."""
        from src.design_system.tokens import apply_combobox_style

        self.workspace_combo = QComboBox()
        self.workspace_combo.setFixedWidth(140)
        self.workspace_combo.setToolTip("Workspace")
        apply_combobox_style(self.workspace_combo, variant="toolbar")
        
        self._refresh_workspace_combo()
        self.workspace_combo.currentIndexChanged.connect(self._on_workspace_selected)
        self.addWidget(self.workspace_combo)
        
        # Config button to open workspace settings
        self.workspace_config_btn = QPushButton()
        self.workspace_config_btn.setIcon(qta.icon("fa5s.cog", color=self._icon_color))
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

    def set_timer_running(self, running: bool, interval_secs: int = 0):
        """Update the timer button appearance based on running state."""
        if running:
            self.btn_run_timer.setIcon(qta.icon("mdi.timer-off", color="#f44336"))
            self.btn_run_timer.setToolTip(S.toolbar.run_timer_stop)
            self.btn_run_timer.setStyleSheet("""
                QPushButton {
                    background-color: rgba(244, 67, 54, 0.15);
                    color: #f44336;
                    padding: 4px 8px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(244, 67, 54, 0.30);
                }
            """)
        else:
            self.btn_run_timer.setIcon(qta.icon("mdi.timer", color=self._icon_color))
            self.btn_run_timer.setToolTip(S.toolbar.run_timer)
            self.btn_run_timer.setStyleSheet("")

    def apply_theme(self):
        pass
