"""
DockingMainWindow - Main window with integrated docking system

This class extends QMainWindow to provide
Visual Studio-style docking capabilities.
"""

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget, QApplication
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QAction, QKeySequence
from typing import Dict, Optional, Any

from .docking_manager import DockingManager
from .dockable_widget import DockableWidget


class DockingMainWindow(QMainWindow):
    """Main window with integrated docking system"""

    # Signals
    panel_visibility_changed = pyqtSignal(str, bool)  # name, visible
    layout_restored = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Settings
        self.settings = QSettings("DataPyn", "DockingLayout")

        # Docking system
        self.docking_manager = DockingManager(self)

        # Registered panels
        self.panels: Dict[str, DockableWidget] = {}

        # Default central area (editors)
        self.central_content = QWidget()

        # Timer to save layout automatically
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self._auto_save_layout)
        self.auto_save_timer.setSingleShot(True)

    def finish_docking_setup(self):
        """Finish docking configuration - called by child class"""
        self._setup_menu_actions()
        self._connect_signals()

    def _setup_ui(self):
        """Configure base interface"""
        self.setWindowTitle("DataPyn - Docking System")
        self.resize(1200, 800)

        # Central area will be managed externally
        # (editors, etc.)
        self.set_central_content(self.central_content)

        # Load saved layout
        self.restore_layout()

    def _setup_menu_actions(self):
        """Configure menu actions for panels"""
        # View menu to control panels
        view_menu = self.menuBar().addMenu("&View")

        # Action to reset layout
        # Note: Child classes (MainWindow) may define their own reset action with shortcut
        reset_action = QAction("&Reset Layout", self)
        reset_action.triggered.connect(self.reset_layout)
        view_menu.addAction(reset_action)

        view_menu.addSeparator()

        # Submenu for panels
        self.panels_menu = view_menu.addMenu("&Panels")

    def _connect_signals(self):
        """Connect signals"""
        self.docking_manager.layout_changed.connect(self._on_layout_changed)

    def _on_layout_changed(self):
        """Called when layout changes"""
        # Schedule automatic save
        self.auto_save_timer.start(2000)  # Save after 2s inactivity

    def _auto_save_layout(self):
        """Save layout automatically"""
        self.save_layout()

    def set_central_content(self, widget: QWidget):
        """Set central area content"""
        if widget:
            # Remove from previous layout if needed
            if widget.parent():
                widget.setParent(None)

            # Add to central area
            central_area = self.docking_manager.layout_areas["center"]

            # Clear previous layout
            layout = central_area.layout()
            if layout:
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None)
            else:
                layout = QVBoxLayout(central_area)
                layout.setContentsMargins(0, 0, 0, 0)

            layout.addWidget(widget)
            self.central_content = widget

    def add_dockable_panel(
        self,
        name: str,
        widget: QWidget,
        title: str = "",
        position: str = "bottom",
        visible: bool = True,
        show_header: bool = False,
    ) -> DockableWidget:
        """
        Add a dockable panel

        Args:
            name: Unique panel name
            widget: Panel content widget
            title: Panel title (uses name if empty)
            position: Initial position ('left', 'right', 'top', 'bottom')
            visible: Whether to show initially
            show_header: Whether to show header with title and controls
        """
        if name in self.panels:
            # Panel already exists, just add as tab
            existing_panel = self.panels[name]
            existing_panel.add_tab(widget, title or name)
            return existing_panel

        # Create new dockable panel
        panel = self.docking_manager.create_dockable_panel(name, title or name, show_header)
        panel.add_tab(widget, title or name)

        # Register and dock
        self.panels[name] = panel

        if visible:
            self.docking_manager.dock_widget(panel, position, show=True)

        # Add to menu
        self._add_panel_menu_action(name, panel)

        return panel

    def _add_panel_menu_action(self, name: str, panel: DockableWidget):
        """Add panel action to menu"""
        action = QAction(f"&{panel.title}", self)
        action.setCheckable(True)
        action.setChecked(panel.isVisible())

        # Connect toggle
        def toggle_panel():
            if panel.isVisible():
                panel.hide()
            else:
                panel.show()
            action.setChecked(panel.isVisible())
            self.panel_visibility_changed.emit(name, panel.isVisible())

        action.triggered.connect(toggle_panel)
        self.panels_menu.addAction(action)

        # Update action when visibility changes
        def update_action():
            action.setChecked(panel.isVisible())

        panel.visibilityChanged.connect(update_action)

    def get_panel(self, name: str) -> Optional[DockableWidget]:
        """Get panel by name"""
        return self.panels.get(name)

    def show_panel(self, name: str):
        """Show specific panel"""
        panel = self.panels.get(name)
        if panel:
            panel.show()
            panel.raise_()
            self.panel_visibility_changed.emit(name, True)

    def hide_panel(self, name: str):
        """Hide specific panel"""
        panel = self.panels.get(name)
        if panel:
            panel.hide()
            self.panel_visibility_changed.emit(name, False)

    def toggle_panel(self, name: str):
        """Toggle panel visibility"""
        panel = self.panels.get(name)
        if panel:
            if panel.isVisible():
                self.hide_panel(name)
            else:
                self.show_panel(name)

    def reset_layout(self):
        """Reset layout to default configuration"""
        # Hide all panels
        for panel in self.panels.values():
            panel.hide()

        # Hide areas
        for area in self.docking_manager.layout_areas.values():
            if area != self.docking_manager.center_area:
                area.setVisible(False)

        # Readjust splitters
        self.docking_manager._adjust_splitter_sizes()

        # Save the reset
        self.save_layout()

    def save_layout(self):
        """Save current layout"""
        config = self.docking_manager.save_layout()

        # Add window settings
        config["window"] = {
            "geometry": self.saveGeometry().data().hex(),
            "state": self.saveState().data().hex() if hasattr(self, "saveState") else None,
        }

        # Save panel visibility
        config["panels_visibility"] = {}
        for name, panel in self.panels.items():
            config["panels_visibility"][name] = panel.isVisible()

        # Save to settings
        self.settings.setValue("layout", config)
        self.settings.sync()

    def restore_layout(self):
        """Restore saved layout"""
        config = self.settings.value("layout", {})

        if not config:
            return

        # Restore window settings
        if "window" in config:
            window_config = config["window"]
            if "geometry" in window_config and window_config["geometry"]:
                try:
                    geometry = bytes.fromhex(window_config["geometry"])
                    self.restoreGeometry(geometry)
                except:
                    pass

            if "state" in window_config and window_config["state"]:
                try:
                    state = bytes.fromhex(window_config["state"])
                    if hasattr(self, "restoreState"):
                        self.restoreState(state)
                except:
                    pass

        # Restore docking manager layout
        self.docking_manager.load_layout(config)

        # Restore panel visibility
        if "panels_visibility" in config:
            visibility = config["panels_visibility"]
            for name, is_visible in visibility.items():
                if name in self.panels:
                    panel = self.panels[name]
                    panel.setVisible(is_visible)

        self.layout_restored.emit()

    def closeEvent(self, event):
        """Save layout on close"""
        self.save_layout()
        super().closeEvent(event)

    def showEvent(self, event):
        """Event when showing window"""
        super().showEvent(event)
        # Force splitter readjustment
        QTimer.singleShot(100, self.docking_manager._adjust_splitter_sizes)

    def resizeEvent(self, event):
        """Resize event"""
        super().resizeEvent(event)
        # Readjust splitters when resizing
        if hasattr(self, "docking_manager"):
            QTimer.singleShot(10, self.docking_manager._adjust_splitter_sizes)
