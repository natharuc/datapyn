"""Side dock wrapper with a visible resize grip on the inner edge."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from src.design_system.tokens import (
    SIDE_DOCK_MAX_WIDTH,
    SIDE_DOCK_MIN_WIDTH,
    get_colors,
)


class _ResizeGrip(QFrame):
  """Thin draggable strip that resizes the parent dock."""

  def __init__(self, host: "SideDockFrame", parent=None):
    super().__init__(parent)
    self._host = host
    self.setObjectName("sideDockResizeGrip")
    self.setFixedWidth(6)
    self.setCursor(Qt.CursorShape.SizeHorCursor)
    self._apply_style(hovered=False)

  def _apply_style(self, *, hovered: bool) -> None:
    colors = get_colors()
    bg = colors.interactive_primary if hovered else colors.border_strong
    self.setStyleSheet(
      f"QFrame#sideDockResizeGrip {{ background-color: {bg}; border: none; margin: 0px; }}"
    )

  def enterEvent(self, event):
    self._apply_style(hovered=True)
    super().enterEvent(event)

  def leaveEvent(self, event):
    self._apply_style(hovered=False)
    super().leaveEvent(event)

  def mousePressEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
      self._host._begin_resize(int(event.globalPosition().x()))
      event.accept()
      return
    super().mousePressEvent(event)

  def mouseMoveEvent(self, event):
    if self._host._resizing:
      self._host._update_resize(int(event.globalPosition().x()))
      event.accept()
      return
    super().mouseMoveEvent(event)

  def mouseReleaseEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
      self._host._end_resize()
      event.accept()
      return
    super().mouseReleaseEvent(event)


class SideDockFrame(QWidget):
  """Wrap dock content and expose a visible resize grip toward the central area."""

  def __init__(self, content: QWidget, parent=None):
    super().__init__(parent)
    self._content = content
    self._dock = None
    self._main_window: QMainWindow | None = None
    self._grip = _ResizeGrip(self, self)
    self._layout = QHBoxLayout(self)
    self._layout.setContentsMargins(0, 0, 0, 0)
    self._layout.setSpacing(0)
    self._grip_on_left = False
    self._resizing = False
    self._drag_start_x = 0
    self._dock_start_width = 0
    self._place_grip(left=False)

  def bind(self, dock, main_window: QMainWindow) -> None:
    self._dock = dock
    self._main_window = main_window
    self.refresh_grip_side()

  def refresh_grip_side(self) -> None:
    if self._main_window is None or self._dock is None:
      return
    area = self._main_window.dockWidgetArea(self._dock)
    self._place_grip(left=area == Qt.DockWidgetArea.RightDockWidgetArea)

  def _place_grip(self, *, left: bool) -> None:
    if left == self._grip_on_left and self._layout.indexOf(self._grip) >= 0:
      return
    self._grip_on_left = left
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
    try:
      self._main_window.resizeDocks(
        [self._dock],
        [new_width],
        Qt.Orientation.Horizontal,
      )
    except Exception:
      pass

  def _end_resize(self) -> None:
    self._resizing = False


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
