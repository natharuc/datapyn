"""Side dock wrapper with a visible resize grip on the inner edge."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QMainWindow, QWidget

from src.design_system.tokens import (
    SIDE_DOCK_GRIP_HIT_WIDTH,
    SIDE_DOCK_MAX_WIDTH,
    SIDE_DOCK_MIN_WIDTH,
    get_colors,
)


def column_docks_for_horizontal_resize(main_window: QMainWindow, dock: QDockWidget) -> list[QDockWidget]:
    """Return every visible dock in the same side column (required by resizeDocks)."""
    area = main_window.dockWidgetArea(dock)
    if area not in (
        Qt.DockWidgetArea.LeftDockWidgetArea,
        Qt.DockWidgetArea.RightDockWidgetArea,
    ):
        return [dock]

    siblings = [
        candidate
        for candidate in main_window.findChildren(QDockWidget)
        if not candidate.isFloating()
        and candidate.isVisible()
        and main_window.dockWidgetArea(candidate) == area
    ]
    return siblings or [dock]


class _ResizeGrip(QFrame):
    """Draggable strip that resizes the parent dock column."""

    def __init__(self, host: "SideDockFrame", *, inner_edge: str, parent=None):
        super().__init__(parent)
        self._host = host
        self._inner_edge = inner_edge
        self.setObjectName("sideDockResizeGrip")
        self.setFixedWidth(SIDE_DOCK_GRIP_HIT_WIDTH)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._apply_style(hovered=False)

    def _apply_style(self, *, hovered: bool) -> None:
        colors = get_colors()
        line = colors.interactive_primary if hovered else colors.border_default
        border_prop = "border-left" if self._inner_edge == "left" else "border-right"
        self.setStyleSheet(
            f"""
            QFrame#sideDockResizeGrip {{
                background: transparent;
                {border_prop}: 2px solid {line};
                border-top: none;
                border-bottom: none;
                margin: 0px;
            }}
            """
        )

    def enterEvent(self, event):
        self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._host._resizing:
            self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._host._begin_resize(int(event.globalPosition().x()))
            event.accept()
            return
        super().mousePressEvent(event)


class _GlobalResizeFilter(QObject):
    """Track mouse moves/releases anywhere while a dock column is being resized."""

    def __init__(self, frame: "SideDockFrame"):
        super().__init__(frame)
        self._frame = frame

    def eventFilter(self, obj, event):
        if not self._frame._resizing:
            return False
        if event.type() == QEvent.Type.MouseMove:
            self._frame._update_resize(int(event.globalPosition().x()))
            return True
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._frame._end_resize()
            return True
        return False


class SideDockFrame(QWidget):
    """Wrap dock content and expose a visible resize grip toward the central area."""

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self._content = content
        self._dock = None
        self._main_window: QMainWindow | None = None
        self._grip: _ResizeGrip | None = None
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._grip_on_left = False
        self._resizing = False
        self._drag_start_x = 0
        self._dock_start_width = 0
        self._global_filter = _GlobalResizeFilter(self)
        self._place_grip(left=False)

    def bind(self, dock, main_window: QMainWindow) -> None:
        self._dock = dock
        self._main_window = main_window
        if self._main_window is not None:
            self._main_window.installEventFilter(self._global_filter)
        self.refresh_grip_side()

    def refresh_grip_side(self) -> None:
        if self._main_window is None or self._dock is None:
            return
        area = self._main_window.dockWidgetArea(self._dock)
        self._place_grip(left=area == Qt.DockWidgetArea.RightDockWidgetArea)

    def _place_grip(self, *, left: bool) -> None:
        if left == self._grip_on_left and self._grip is not None and self._layout.indexOf(self._grip) >= 0:
            return
        self._grip_on_left = left
        inner_edge = "left" if left else "right"
        if self._grip is None:
            self._grip = _ResizeGrip(self, inner_edge=inner_edge, parent=self)
        else:
            self._grip._inner_edge = inner_edge
            self._grip._apply_style(hovered=False)
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(self)
        if left:
            self._layout.addWidget(self._grip, 0)
            self._layout.addWidget(self._content, 1)
        else:
            self._layout.addWidget(self._content, 1)
            self._layout.addWidget(self._grip, 0)

    def _begin_resize(self, global_x: int) -> None:
        if self._dock is None or self._main_window is None:
            return
        self._resizing = True
        self._drag_start_x = global_x
        self._dock_start_width = max(self._dock.width(), SIDE_DOCK_MIN_WIDTH)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        if self._grip is not None:
            self._grip._apply_style(hovered=True)

    def _update_resize(self, global_x: int) -> None:
        if not self._resizing or self._dock is None or self._main_window is None:
            return
        delta = global_x - self._drag_start_x
        area = self._main_window.dockWidgetArea(self._dock)
        if area == Qt.DockWidgetArea.RightDockWidgetArea:
            new_width = self._dock_start_width - delta
        else:
            new_width = self._dock_start_width + delta
        new_width = max(SIDE_DOCK_MIN_WIDTH, min(SIDE_DOCK_MAX_WIDTH, new_width))
        docks = column_docks_for_horizontal_resize(self._main_window, self._dock)
        sizes = [new_width] * len(docks)
        try:
            self._main_window.resizeDocks(
                docks,
                sizes,
                Qt.Orientation.Horizontal,
            )
        except Exception:
            pass

    def _end_resize(self) -> None:
        if not self._resizing:
            return
        self._resizing = False
        self.unsetCursor()
        if self._grip is not None:
            self._grip._apply_style(hovered=False)


class _DockLocationWatcher(QObject):
    """Refresh grip side when the user moves a dock between areas."""

    def __init__(self, frame: SideDockFrame, dock):
        super().__init__(dock)
        self._frame = frame
        dock.dockLocationChanged.connect(self._on_location_changed)

    def _on_location_changed(self, _area) -> None:
        self._frame.refresh_grip_side()


def mount_side_dock(dock, main_window: QMainWindow, content: QWidget) -> SideDockFrame:
    """Wrap dock content with a resize grip and mount it on the dock."""
    existing = dock.widget()
    if isinstance(existing, SideDockFrame):
        existing._content = content
        if existing.layout() and existing.layout().indexOf(content) < 0:
            existing.layout().addWidget(content, 1)
        existing.bind(dock, main_window)
        return existing

    frame = SideDockFrame(content)
    frame.bind(dock, main_window)
    dock.setWidget(frame)
    watcher = _DockLocationWatcher(frame, dock)
    frame._location_watcher = watcher  # keep alive
    return frame
