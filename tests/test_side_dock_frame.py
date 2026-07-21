"""Tests for the side dock resize grip wrapper."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow

from src.ui.components.side_dock_frame import column_docks_for_horizontal_resize, mount_side_dock


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


def test_column_docks_for_horizontal_resize_includes_visible_siblings(qapp):
    window = QMainWindow()
    top = QDockWidget("Variables", window)
    bottom = QDockWidget("Explorer", window)
    mount_side_dock(top, window, QLabel("vars"))
    mount_side_dock(bottom, window, QLabel("tree"))
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, top)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, bottom)
    window.show()
    qapp.processEvents()

    column = column_docks_for_horizontal_resize(window, bottom)
    assert top in column
    assert bottom in column

    bottom.hide()
    qapp.processEvents()
    assert column_docks_for_horizontal_resize(window, top) == [top]

    window.close()
