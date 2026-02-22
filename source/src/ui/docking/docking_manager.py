"""
DockingManager - Docking system manager

Coordinates entire system: indicators, positioning,
settings persistence, etc.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QApplication, QMainWindow
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QCursor
from typing import Dict, List, Optional, Any
import json
import logging

from .dockable_widget import DockableWidget, DockPosition
from .dock_indicators import DockIndicators, DockPreview

logger = logging.getLogger(__name__)


class DockingManager(QObject):
    """Central docking system manager"""

    # Signals
    layout_changed = pyqtSignal()  # When layout changes

    def __init__(self, main_window: QMainWindow):
        super().__init__()

        self.main_window = main_window
        self.dockable_widgets: Dict[str, DockableWidget] = {}
        self.layout_areas: Dict[str, QWidget] = {}  # area -> container

        # Visual components
        self.indicators = DockIndicators()
        self.preview = DockPreview()

        # Drag state
        self.is_dragging = False
        self.drag_widget = None
        self.drag_title = ""

        # Timer to update indicators
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_drag_state)
        self.update_timer.setSingleShot(False)

        self._setup_layout_areas()
        self._setup_event_filters()

    def _setup_layout_areas(self):
        """Configure main layout areas"""
        central_widget = QWidget()
        self.main_window.setCentralWidget(central_widget)

        # Main layout with splitters
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Main horizontal splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Areas: Left, Center, Right
        self.left_area = QWidget()
        self.left_area.setMinimumWidth(200)
        self.left_area.setVisible(False)  # Initially hidden

        # Central area with vertical splitter
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)

        self.top_area = QWidget()
        self.top_area.setMinimumHeight(150)
        self.top_area.setVisible(False)

        self.center_area = QWidget()  # Main area (editors)

        self.bottom_area = QWidget()
        self.bottom_area.setMinimumHeight(150)
        self.bottom_area.setVisible(False)

        self.center_splitter.addWidget(self.top_area)
        self.center_splitter.addWidget(self.center_area)
        self.center_splitter.addWidget(self.bottom_area)

        self.right_area = QWidget()
        self.right_area.setMinimumWidth(200)
        self.right_area.setVisible(False)

        # Add to main splitter
        self.main_splitter.addWidget(self.left_area)
        self.main_splitter.addWidget(self.center_splitter)
        self.main_splitter.addWidget(self.right_area)

        # Initial proportions
        self.main_splitter.setSizes([0, 800, 0])  # Center expanded
        self.center_splitter.setSizes([0, 600, 0])  # Center expanded

        # Map areas
        self.layout_areas = {
            "left": self.left_area,
            "right": self.right_area,
            "top": self.top_area,
            "bottom": self.bottom_area,
            "center": self.center_area,
        }

        # Layouts for each area
        for area_name, area_widget in self.layout_areas.items():
            if area_name != "center":  # Center is managed externally
                layout = QVBoxLayout(area_widget)
                layout.setContentsMargins(2, 2, 2, 2)

    def _setup_event_filters(self):
        """Configure event filters for global drag"""
        self.main_window.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

    def register_dockable(self, name: str, widget: DockableWidget):
        """Register a dockable widget"""
        self.dockable_widgets[name] = widget

        # Connect signals
        widget.tab_detached.connect(self._on_tab_detached)
        widget.tab_dropped.connect(self._on_tab_dropped)

    def create_dockable_panel(self, name: str, title: str = "", show_header: bool = False) -> DockableWidget:
        """Create a new dockable panel"""
        panel = DockableWidget(title or name, show_header=show_header)
        self.register_dockable(name, panel)
        return panel

    def dock_widget(self, widget: DockableWidget, position: str, show: bool = True):
        """Dock a widget in a specific position"""
        if position not in self.layout_areas:
            return

        area = self.layout_areas[position]
        area.layout().addWidget(widget)

        if show:
            area.setVisible(True)
            self._adjust_splitter_sizes()

    def _adjust_splitter_sizes(self):
        """Adjust splitter sizes based on visible areas"""
        # Splitter horizontal
        left_size = 250 if self.left_area.isVisible() else 0
        right_size = 250 if self.right_area.isVisible() else 0
        center_size = max(400, self.main_window.width() - left_size - right_size)

        self.main_splitter.setSizes([left_size, center_size, right_size])

        # Splitter vertical
        top_size = 200 if self.top_area.isVisible() else 0
        bottom_size = 200 if self.bottom_area.isVisible() else 0
        center_v_size = max(300, self.main_window.height() - top_size - bottom_size)

        self.center_splitter.setSizes([top_size, center_v_size, bottom_size])

    def _on_tab_detached(self, title: str, widget: QWidget):
        """When a tab is detached"""
        self.drag_title = title
        self.drag_widget = widget
        self.is_dragging = True

        print(f"DEBUG: Tab detached - {title}")

        # Show indicators
        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)
        if target_widget:
            self.indicators.show_at_widget(target_widget, cursor_pos)

        # Start timer to update state
        self.update_timer.start(50)  # 20 FPS

    def _on_tab_dropped(self, title: str, widget: QWidget, position: int, pos: QPoint):
        """When a tab is dropped"""
        # Find widget under cursor
        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)

        # Check if dropped on existing dockable panel
        target_panel = self._find_target_dockable_panel(target_widget)

        self._finish_drag()

        # Convert int back to DockPosition
        dock_position = DockPosition(position)

        if target_panel and dock_position == DockPosition.CENTER:
            # Add directly to existing panel as new tab
            target_panel.add_tab(widget, title)
        else:
            # Process drop based on position
            target_area = self._position_to_area(dock_position)
            if target_area:
                self._create_or_add_to_panel(title, widget, target_area, target_panel)

    def _find_target_dockable_panel(self, widget: QWidget) -> Optional[DockableWidget]:
        """Find dockable panel closest to widget"""
        if not widget:
            return None

        # Traverse hierarchy upward looking for DockableWidget
        current = widget
        while current:
            if isinstance(current, DockableWidget):
                return current
            current = current.parent()

        return None

    def _update_drag_state(self):
        """Update state during drag"""
        if not self.is_dragging:
            self.update_timer.stop()
            return

        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)

        # Find dockable panel under cursor
        target_panel = self._find_target_dockable_panel(target_widget)

        if target_panel:
            # Show panel-specific indicators
            self.indicators.show_at_widget(target_panel, cursor_pos)
            highlighted_position = self.indicators.update_highlight(cursor_pos)

            if highlighted_position:
                preview_rect = self._calculate_preview_rect_for_panel(highlighted_position, target_panel)
                if preview_rect.isValid():
                    self.preview.show_preview(preview_rect)
                else:
                    self.preview.hide_preview()
            else:
                self.preview.hide_preview()
        else:
            # Fallback to general areas
            if target_widget:
                self.indicators.show_at_widget(target_widget, cursor_pos)
                highlighted_position = self.indicators.update_highlight(cursor_pos)

                if highlighted_position:
                    preview_rect = self._calculate_preview_rect(highlighted_position, cursor_pos)
                    if preview_rect.isValid():
                        self.preview.show_preview(preview_rect)
                    else:
                        self.preview.hide_preview()
                else:
                    self.preview.hide_preview()
            else:
                self.indicators.hide_indicators()
                self.preview.hide_preview()

    def _calculate_preview_rect_for_panel(self, position: DockPosition, panel: DockableWidget) -> QRect:
        """Calculate preview rectangle for a specific panel"""
        if not panel.isVisible():
            return QRect()

        panel_rect = panel.geometry()
        global_rect = QRect(panel.mapToGlobal(panel_rect.topLeft()), panel_rect.size())

        if position == DockPosition.CENTER:
            # Tab - highlight tabs area
            tab_height = 30
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), tab_height)
        elif position == DockPosition.LEFT:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width() // 2, global_rect.height())
        elif position == DockPosition.RIGHT:
            return QRect(
                global_rect.x() + global_rect.width() // 2,
                global_rect.y(),
                global_rect.width() // 2,
                global_rect.height(),
            )
        elif position == DockPosition.TOP:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), global_rect.height() // 2)
        elif position == DockPosition.BOTTOM:
            return QRect(
                global_rect.x(),
                global_rect.y() + global_rect.height() // 2,
                global_rect.width(),
                global_rect.height() // 2,
            )

        return QRect()

    def _calculate_preview_rect(self, position: DockPosition, cursor_pos: QPoint) -> QRect:
        """Calculate preview rectangle based on position"""
        # Find widget under cursor
        widget = QApplication.widgetAt(cursor_pos)
        if not widget:
            return QRect()

        # Find closest dockable area
        for area_name, area_widget in self.layout_areas.items():
            if area_widget.isAncestorOf(widget) or area_widget == widget:
                return self._get_preview_rect_for_area(position, area_widget)

        return QRect()

    def _get_preview_rect_for_area(self, position: DockPosition, area_widget: QWidget) -> QRect:
        """Calculate preview rectangle for a specific area"""
        if not area_widget.isVisible():
            return QRect()

        rect = area_widget.geometry()
        global_rect = QRect(area_widget.mapToGlobal(rect.topLeft()), rect.size())

        # Adjust based on position
        margin = 20

        if position == DockPosition.LEFT:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width() // 2, global_rect.height())
        elif position == DockPosition.RIGHT:
            return QRect(
                global_rect.x() + global_rect.width() // 2,
                global_rect.y(),
                global_rect.width() // 2,
                global_rect.height(),
            )
        elif position == DockPosition.TOP:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), global_rect.height() // 2)
        elif position == DockPosition.BOTTOM:
            return QRect(
                global_rect.x(),
                global_rect.y() + global_rect.height() // 2,
                global_rect.width(),
                global_rect.height() // 2,
            )
        elif position == DockPosition.CENTER:
            return global_rect.adjusted(margin, margin, -margin, -margin)

        return QRect()

    def _position_to_area(self, position: DockPosition) -> Optional[str]:
        """Convert DockPosition to area name"""
        mapping = {
            DockPosition.LEFT: "left",
            DockPosition.RIGHT: "right",
            DockPosition.TOP: "top",
            DockPosition.BOTTOM: "bottom",
            DockPosition.CENTER: "center",
        }
        return mapping.get(position)

    def _create_or_add_to_panel(self, title: str, widget: QWidget, area_name: str, target_panel: DockableWidget = None):
        """Create panel or add to existing panel"""
        area = self.layout_areas[area_name]

        # If target panel specified, add directly to it
        if target_panel:
            target_panel.add_tab(widget, title)
            return target_panel

        # Look for existing panel in area
        existing_panel = None
        for i in range(area.layout().count()):
            item = area.layout().itemAt(i)
            if item and isinstance(item.widget(), DockableWidget):
                existing_panel = item.widget()
                break

        if existing_panel:
            # Add as new tab
            existing_panel.add_tab(widget, title)
            return existing_panel
        else:
            # Create new panel
            new_panel = DockableWidget(title, show_header=False)
            new_panel.add_tab(widget, title)
            self.dock_widget(new_panel, area_name)
            return new_panel

    def _finish_drag(self):
        """Finish drag operation"""
        self.is_dragging = False
        self.drag_widget = None
        self.drag_title = ""

        # Hide indicators and preview
        self.indicators.hide_indicators()
        self.preview.hide_preview()

        # Stop timer
        self.update_timer.stop()

        # Emit layout change signal
        self.layout_changed.emit()

    def save_layout(self) -> Dict[str, Any]:
        """Save current layout configuration"""
        layout_config = {
            "version": "1.0",
            "areas": {},
            "splitter_sizes": {"main": self.main_splitter.sizes(), "center": self.center_splitter.sizes()},
            "panels": {},
        }

        # Save configuration of each area
        for area_name, area_widget in self.layout_areas.items():
            if area_widget.isVisible() and area_widget.layout().count() > 0:
                panels_in_area = []
                for i in range(area_widget.layout().count()):
                    item = area_widget.layout().itemAt(i)
                    if item and isinstance(item.widget(), DockableWidget):
                        panel = item.widget()
                        panel_config = {"title": panel.title, "visible": panel.isVisible(), "tabs": []}

                        # Save tab configuration
                        for j in range(panel.tab_widget.count()):
                            tab_title = panel.tab_widget.tabText(j)
                            tab_widget = panel.tab_widget.widget(j)
                            panel_config["tabs"].append(
                                {
                                    "title": tab_title,
                                    "widget_class": tab_widget.__class__.__name__,
                                    "current": j == panel.tab_widget.currentIndex(),
                                }
                            )

                        panels_in_area.append(panel_config)

                if panels_in_area:
                    layout_config["areas"][area_name] = {"visible": True, "panels": panels_in_area}

        # Save references to registered panels
        for name, widget in self.dockable_widgets.items():
            layout_config["panels"][name] = {"title": widget.title, "visible": widget.isVisible()}

        return layout_config

    def load_layout(self, config: Dict[str, Any]):
        """Load layout configuration"""
        if not config or config.get("version") != "1.0":
            return False

        try:
            # Restore splitter sizes
            if "splitter_sizes" in config:
                sizes = config["splitter_sizes"]
                if "main" in sizes and len(sizes["main"]) == 3:
                    self.main_splitter.setSizes(sizes["main"])
                if "center" in sizes and len(sizes["center"]) == 3:
                    self.center_splitter.setSizes(sizes["center"])

            # Restore area visibility
            for area_name, area_config in config.get("areas", {}).items():
                if area_name in self.layout_areas:
                    area_widget = self.layout_areas[area_name]
                    area_widget.setVisible(area_config.get("visible", False))

            return True

        except Exception as e:
            logger.error(f"Error loading layout: {e}")
            return False

    def get_default_layout(self) -> Dict[str, Any]:
        """Return default layout configuration"""
        return {
            "version": "1.0",
            "areas": {"bottom": {"visible": True}, "right": {"visible": True}},
            "splitter_sizes": {
                "main": [0, 800, 250],  # left, center, right
                "center": [0, 600, 200],  # top, center, bottom
            },
            "panels": {},
        }

    def restore_default_layout(self):
        """Restore default layout"""
        default_config = self.get_default_layout()
        self.load_layout(default_config)

        # Force size adjustment
        self._adjust_splitter_sizes()

    def eventFilter(self, obj, event):
        """Event filter to capture global drags"""
        # Fast path: ignore events when not dragging
        if not getattr(self, "is_dragging", False):
            return False

        evt_type = event.type()
        if evt_type == event.Type.MouseButtonRelease or evt_type == event.Type.Drop:
            if hasattr(event, "button") and event.button() == Qt.MouseButton.LeftButton:
                # Drop outside valid area - create floating panel
                if self.drag_widget and self.drag_title:
                    self._create_floating_panel()
                self._finish_drag()
                return True

        return False

    def _create_floating_panel(self):
        """Create floating panel when drop is outside valid area"""
        if not self.drag_widget or not self.drag_title:
            return

        print(f"DEBUG: Creating floating panel for {self.drag_title}")

        # Create new panel
        new_panel = DockableWidget(self.drag_title, show_header=True)
        new_panel.add_tab(self.drag_widget, self.drag_title)

        # Make floating
        new_panel.setParent(None)
        new_panel.setWindowFlags(Qt.WindowType.Window)

        # Position near cursor
        cursor_pos = QCursor.pos()
        new_panel.move(cursor_pos.x() - 100, cursor_pos.y() - 50)
        new_panel.resize(400, 300)
        new_panel.show()

        # Register panel
        panel_name = f"floating_{len(self.dockable_widgets)}"
        self.register_dockable(panel_name, new_panel)

        print(f"DEBUG: Floating panel created - {self.drag_title}")

    def cleanup(self):
        """Cleanup resources before destruction."""
        if hasattr(self, 'update_timer') and self.update_timer:
            self.update_timer.stop()
