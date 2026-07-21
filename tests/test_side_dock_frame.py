"""Tests for the side dock resize grip wrapper."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow

from src.ui.components.side_dock_frame import SideDockFrame, mount_side_dock


def test_side_dock_frame_places_grip_on_inner_edge(qapp):
    window = QMainWindow()
    dock = QDockWidget("Explorer", window)
    content = QLabel("tree")
    frame = mount_side_dock(dock, window, content)
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    window.show()
    qapp.processEvents()

  # Left dock: grip sits on the right, toward the editor.
    assert frame._layout.indexOf(frame._grip) > frame._layout.indexOf(content)

    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    frame.refresh_grip_side()
    qapp.processEvents()

  # Right dock: grip moves to the left edge.
    assert frame._layout.indexOf(frame._grip) < frame._layout.indexOf(content)

    window.close()
