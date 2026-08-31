"""Canonical main-window dock layout defaults."""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class _LayoutHost(QMainWindow):
    """Minimal host that uses LayoutMixin dock helpers without full MainWindow."""

    def __init__(self):
        super().__init__()
        from src.ui.main_window._layout import LayoutMixin

        # Bind mixin methods onto this instance
        for name in (
            "_managed_docks",
            "_arrange_default_docks",
            "_saved_layout_version",
        ):
            setattr(self, name, getattr(LayoutMixin, name).__get__(self, _LayoutHost))

        self.connections_dock = QDockWidget("Connections", self)
        self.connections_dock.setObjectName("ConnectionsDock")
        self.object_explorer_dock = QDockWidget("Object Explorer", self)
        self.object_explorer_dock.setObjectName("ObjectExplorerDock")
        self.results_dock = QDockWidget("Results", self)
        self.results_dock.setObjectName("ResultsDock")
        self.summarize_dock = QDockWidget("Summarize", self)
        self.summarize_dock.setObjectName("SummarizeDock")
        self.output_dock = QDockWidget("Output", self)
        self.output_dock.setObjectName("OutputDock")
        self.copilot_output_dock = QDockWidget("Pynia Output", self)
        self.copilot_output_dock.setObjectName("CopilotOutputDock")
        self.variables_dock = QDockWidget("Variables", self)
        self.variables_dock.setObjectName("VariablesDock")
        self.copilot_dock = QDockWidget("Pynia", self)
        self.copilot_dock.setObjectName("PyniaDock")

        for dock in self._managed_docks():
            dock.setWidget(QLabel(dock.windowTitle()))
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)


def test_arrange_default_docks_groups_areas(qapp):
    host = _LayoutHost()
    host._arrange_default_docks()

    left = Qt.DockWidgetArea.LeftDockWidgetArea
    bottom = Qt.DockWidgetArea.BottomDockWidgetArea
    right = Qt.DockWidgetArea.RightDockWidgetArea

    assert host.dockWidgetArea(host.connections_dock) == left
    assert host.dockWidgetArea(host.object_explorer_dock) == left
    assert host.dockWidgetArea(host.results_dock) == bottom
    assert host.dockWidgetArea(host.summarize_dock) == bottom
    assert host.dockWidgetArea(host.output_dock) == bottom
    assert host.dockWidgetArea(host.copilot_output_dock) == bottom
    assert host.dockWidgetArea(host.variables_dock) == right
    assert host.dockWidgetArea(host.copilot_dock) == right


def test_layout_version_constant_and_settings_parse(qapp):
    from src.ui.main_window._layout import LayoutMixin, _DOCK_LAYOUT_VERSION

    assert _DOCK_LAYOUT_VERSION >= 4
    host = MagicMock()
    settings = QSettings("DataPyn", "DockLayoutTest")
    settings.clear()
    settings.setValue("layoutVersion", "3")
    assert LayoutMixin._saved_layout_version(host, settings) == 3
    settings.clear()
