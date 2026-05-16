from types import SimpleNamespace
from unittest.mock import MagicMock

from src.ui.docking.docking_manager import DockingManager


class _VisibleWidget:
    def __init__(self, visible: bool):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _DeletedWidget:
    def isVisible(self):
        raise RuntimeError("wrapped C/C++ object of type QWidget has been deleted")


class _MainWindow:
    def __init__(self, width: int = 1200, height: int = 900):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


def _manager_stub(**overrides):
    manager = SimpleNamespace(
        main_window=_MainWindow(),
        left_area=_VisibleWidget(True),
        right_area=_VisibleWidget(False),
        top_area=_VisibleWidget(False),
        bottom_area=_VisibleWidget(True),
        main_splitter=MagicMock(),
        center_splitter=MagicMock(),
    )
    for key, value in overrides.items():
        setattr(manager, key, value)
    manager._qt_object_is_alive = DockingManager._qt_object_is_alive
    return manager


class TestDockingManagerAdjustSplitterSizes:
    def test_adjust_splitter_sizes_sets_expected_sizes(self):
        manager = _manager_stub()

        DockingManager._adjust_splitter_sizes(manager)

        manager.main_splitter.setSizes.assert_called_once_with([250, 950, 0])
        manager.center_splitter.setSizes.assert_called_once_with([0, 700, 200])

    def test_adjust_splitter_sizes_ignores_deleted_widgets(self):
        manager = _manager_stub(left_area=_DeletedWidget())

        DockingManager._adjust_splitter_sizes(manager)

        manager.main_splitter.setSizes.assert_not_called()
        manager.center_splitter.setSizes.assert_not_called()

    def test_adjust_splitter_sizes_returns_when_required_widget_is_missing(self):
        manager = _manager_stub(left_area=None)

        DockingManager._adjust_splitter_sizes(manager)

        manager.main_splitter.setSizes.assert_not_called()
        manager.center_splitter.setSizes.assert_not_called()
