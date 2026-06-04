"""
Tests for per-tab periodic execution timer.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.main_window import MainWindow


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    max_wait = 10000
    interval = 100
    for _ in range(max_wait // interval):
        QApplication.processEvents()
        QTest.qWait(50)
        if not hasattr(window, "_sessions_to_load") or not window._sessions_to_load:
            break
        QTest.qWait(interval)
    QApplication.processEvents()
    QTest.qWait(100)
    return window


class TestPerTabPeriodicTimer:
    """Tests that periodic execution is per-tab, not global."""

    def test_start_periodic_sets_active(self, main_window):
        """Starting periodic on a tab sets the active flag."""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)

        widget = main_window._get_current_session_widget()
        assert not widget.is_periodic_active

        widget.start_periodic(10)
        assert widget.is_periodic_active
        assert widget.periodic_interval == 10

        widget.stop_periodic()
        assert not widget.is_periodic_active

    def test_periodic_is_per_tab(self, main_window):
        """Periodic timer on tab A does NOT affect tab B."""
        # Create tab A
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_a = main_window._get_current_session_widget()

        # Create tab B
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_b = main_window._get_current_session_widget()

        # Start periodic on tab A only
        widget_a.start_periodic(15)

        # Tab A should be active, tab B should not
        assert widget_a.is_periodic_active
        assert not widget_b.is_periodic_active

        # Cleanup
        widget_a.stop_periodic()

    def test_close_tab_stops_periodic(self, main_window):
        """Closing a tab with active periodic should stop the timer."""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget = main_window._get_current_session_widget()

        widget.start_periodic(5)
        assert widget.is_periodic_active

        # Close the tab - cleanup should stop the timer
        idx = main_window.session_tabs.currentIndex()
        main_window._close_session_tab(idx)
        QApplication.processEvents()

        # Timer should have been stopped during cleanup
        assert not widget._periodic_active

    def test_periodic_changed_signal_emitted(self, main_window):
        """periodic_changed signal is emitted when starting/stopping."""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget = main_window._get_current_session_widget()

        signals_received = []
        widget.periodic_changed.connect(lambda active: signals_received.append(active))

        widget.start_periodic(10)
        assert signals_received == [True]

        widget.stop_periodic()
        assert signals_received == [True, False]

    def test_tab_timer_icon_shown(self, main_window):
        """Timer glyph is painted on the tab bar when periodic starts."""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget = main_window._get_current_session_widget()
        tab_index = main_window.session_tabs.indexOf(widget)
        assert tab_index >= 0
        tab_bar = main_window.session_tabs.tabBar()

        assert tab_index not in tab_bar._timer_tab_indices

        widget.start_periodic(20)
        QApplication.processEvents()
        QTest.qWait(50)
        QApplication.processEvents()

        assert tab_index in tab_bar._timer_tab_indices

        # Stop periodic
        widget.stop_periodic()
        QApplication.processEvents()

        assert tab_index not in tab_bar._timer_tab_indices


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
