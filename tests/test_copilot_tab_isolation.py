"""
Tests for Copilot per-tab isolation (session pinning in MCP tools).
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.copilot.mcp_tools import MCPToolRegistry


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow"""
    from src.ui.main_window import MainWindow
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


class TestMCPToolSessionPinning:
    """Tests that MCP tools target the pinned session, not the visually active tab."""

    def test_pinned_session_returns_correct_widget(self, main_window):
        """When pinned, _get_active_session_widget returns the pinned tab's widget."""
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)

        # Create tab A
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_a = main_window._get_current_session_widget()
        session_a_id = widget_a.session.session_id

        # Create tab B (becomes active)
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_b = main_window._get_current_session_widget()

        # Without pinning: returns current tab (B)
        result = registry._get_active_session_widget()
        assert result is widget_b

        # Pin to tab A
        registry.pin_session(session_a_id)

        # With pinning: returns tab A even though tab B is active
        result = registry._get_active_session_widget()
        assert result is widget_a

        # Unpin
        registry.unpin_session()

        # Without pinning: returns current tab (B) again
        result = registry._get_active_session_widget()
        assert result is widget_b

    def test_pin_survives_tab_switch(self, main_window):
        """Pinned session stays correct after user switches tabs."""
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)

        # Create tab A and B
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_a = main_window._get_current_session_widget()
        session_a_id = widget_a.session.session_id
        idx_a = main_window.session_tabs.currentIndex()

        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)

        # Pin to A, switch to B visually
        registry.pin_session(session_a_id)
        main_window.session_tabs.setCurrentIndex(idx_a)
        QApplication.processEvents()

        # Still returns A's widget
        result = registry._get_active_session_widget()
        assert result is widget_a

        registry.unpin_session()

    def test_unpin_falls_back_to_current(self, main_window):
        """After unpin, _get_active_session_widget returns the visually active tab."""
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)

        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_a = main_window._get_current_session_widget()
        session_a_id = widget_a.session.session_id

        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget_b = main_window._get_current_session_widget()

        registry.pin_session(session_a_id)
        registry.unpin_session()

        # Should return widget_b (the active tab)
        result = registry._get_active_session_widget()
        assert result is widget_b

    def test_pin_invalid_session_falls_back(self, main_window):
        """Pinning a non-existent session_id falls back to current tab."""
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)

        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
        widget = main_window._get_current_session_widget()

        registry.pin_session("nonexistent-session-id")

        # Should fall back to current tab
        result = registry._get_active_session_widget()
        assert result is widget

        registry.unpin_session()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
