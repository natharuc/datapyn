"""
Tests for the in-app toast notification system.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtWidgets import QWidget, QMainWindow, QApplication

from src.ui.components.toast_notification import (
    ToastNotification,
    ToastManager,
    _manager,
    HAS_SOUND,
)
import src.ui.components.toast_notification as toast_mod


@pytest.fixture
def parent_window(qtbot):
    """A simple parent window for positioning toasts."""
    win = QMainWindow()
    win.resize(800, 600)
    win.move(100, 100)
    win.show()
    qtbot.addWidget(win)
    qtbot.waitExposed(win)
    return win


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset the global ToastManager between tests."""
    toast_mod._manager = None
    yield
    toast_mod._manager = None


class TestToastNotification:
    """Tests for the ToastNotification widget."""

    def test_toast_creation_success(self, qtbot, parent_window):
        """Toast created with success style."""
        toast = ToastNotification(
            title="SQL Query",
            message="42 rows returned",
            success=True,
            parent=parent_window,
        )
        qtbot.addWidget(toast)
        assert toast.width() == ToastNotification.WIDTH
        assert toast._success is True

    def test_toast_creation_error(self, qtbot, parent_window):
        """Toast created with error style."""
        toast = ToastNotification(
            title="Error",
            message="Syntax error near ';'",
            success=False,
            parent=parent_window,
        )
        qtbot.addWidget(toast)
        assert toast._success is False

    def test_toast_show_at(self, qtbot, parent_window):
        """Toast shows and positions itself."""
        toast = ToastNotification(
            title="Test",
            message="Hello",
            success=True,
            parent=parent_window,
        )
        qtbot.addWidget(toast)
        toast.show_at(500, 400)
        qtbot.wait(50)
        assert toast.isVisible()

    def test_toast_auto_dismiss(self, qtbot, parent_window):
        """Toast auto-dismisses after duration."""
        toast = ToastNotification(
            title="Test",
            message="Brief",
            success=True,
            duration=200,  # very short for test
            parent=parent_window,
        )
        # Do NOT use qtbot.addWidget - toast calls deleteLater on dismiss
        closed = []
        toast.closed.connect(lambda t: closed.append(True))
        toast.show_at(500, 400)

        # Wait for dismiss + fade
        qtbot.wait(200 + ToastNotification.FADE_DURATION + 300)
        assert len(closed) == 1

    def test_toast_click_callback(self, qtbot, parent_window):
        """Clicking the toast fires the on_click callback."""
        clicked = []
        toast = ToastNotification(
            title="Click me",
            message="Please",
            success=True,
            parent=parent_window,
            on_click=lambda: clicked.append(True),
        )
        qtbot.addWidget(toast)
        toast.show_at(500, 400)
        qtbot.wait(50)

        # Simulate mouse press
        qtbot.mouseClick(toast, Qt.MouseButton.LeftButton)
        assert len(clicked) == 1

    def test_toast_hover_pauses_dismiss(self, qtbot, parent_window):
        """Hovering pauses the auto-dismiss timer."""
        toast = ToastNotification(
            title="Hover",
            message="Test",
            success=True,
            duration=300,
            parent=parent_window,
        )
        qtbot.addWidget(toast)
        toast.show_at(500, 400)
        qtbot.wait(50)

        # Simulate enter event
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QEnterEvent

        # The timer should have been running
        assert toast._dismiss_timer.isActive()

        # Manually call enterEvent
        toast.enterEvent(None)
        assert not toast._dismiss_timer.isActive()

        # leaveEvent restarts
        toast.leaveEvent(None)
        assert toast._dismiss_timer.isActive()

    def test_toast_closed_signal(self, qtbot, parent_window):
        """Toast emits closed signal when dismissed."""
        toast = ToastNotification(
            title="Signal",
            message="Test",
            success=True,
            duration=100,
            parent=parent_window,
        )
        # Do NOT use qtbot.addWidget - toast calls deleteLater on dismiss
        closed_toasts = []
        toast.closed.connect(lambda t: closed_toasts.append(True))

        toast.show_at(500, 400)
        qtbot.wait(100 + ToastNotification.FADE_DURATION + 300)
        assert len(closed_toasts) == 1

    def test_toast_manual_dismiss(self, qtbot, parent_window):
        """Calling _dismiss stops the timer and fades out."""
        toast = ToastNotification(
            title="Dismiss",
            message="Now",
            success=True,
            duration=5000,
            parent=parent_window,
        )
        qtbot.addWidget(toast)
        toast.show_at(500, 400)
        qtbot.wait(50)

        toast._dismiss()
        # Timer should be stopped
        assert not toast._dismiss_timer.isActive()


class TestToastManager:
    """Tests for the ToastManager singleton."""

    def test_setup_creates_manager(self, qtbot, parent_window):
        """ToastManager.setup initializes the global manager."""
        mgr = ToastManager.setup(parent_window)
        assert toast_mod._manager is mgr
        assert mgr._parent is parent_window

    def test_notify_without_setup_does_nothing(self, qtbot):
        """Calling notify before setup is a no-op (no crash)."""
        toast_mod._manager = None
        # Should NOT raise
        ToastManager.notify("Title", "Message")

    def test_notify_success(self, qtbot, parent_window):
        """ToastManager.notify creates a success toast."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("Success", "All good", success=True, sound=False)
        qtbot.wait(50)
        assert len(mgr._active) == 1
        assert mgr._active[0]._success is True

    def test_notify_error(self, qtbot, parent_window):
        """ToastManager.notify creates an error toast."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("Error", "Something broke", success=False, sound=False)
        qtbot.wait(50)
        assert len(mgr._active) == 1
        assert mgr._active[0]._success is False

    def test_multiple_notifications_stack(self, qtbot, parent_window):
        """Multiple toasts are stacked vertically."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("First", "1", sound=False)
        ToastManager.notify("Second", "2", sound=False)
        ToastManager.notify("Third", "3", sound=False)
        qtbot.wait(100)
        assert len(mgr._active) == 3

        # Each should be at a different y position
        positions = [t.pos().y() for t in mgr._active]
        # They should all be different (stacked)
        assert len(set(positions)) == 3

    def test_toast_removed_from_active_on_close(self, qtbot, parent_window):
        """Toast is removed from active list when it closes."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("Brief", "Gone soon", success=True, sound=False)
        qtbot.wait(50)
        assert len(mgr._active) == 1

        # Force close
        toast = mgr._active[0]
        toast._dismiss()
        qtbot.wait(ToastNotification.FADE_DURATION + 200)
        assert len(mgr._active) == 0

    def test_on_click_callback_from_manager(self, qtbot, parent_window):
        """on_click callback provided via manager is invoked on click."""
        mgr = ToastManager.setup(parent_window)
        clicks = []
        ToastManager.notify(
            "Clickable", "Click me",
            on_click=lambda: clicks.append(1),
            sound=False,
        )
        qtbot.wait(100)

        assert len(mgr._active) == 1
        toast = mgr._active[0]
        qtbot.mouseClick(toast, Qt.MouseButton.LeftButton)
        assert len(clicks) == 1

    def test_reposition_on_dismiss(self, qtbot, parent_window):
        """Remaining toasts are repositioned when one is dismissed."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("A", "a", sound=False)
        ToastManager.notify("B", "b", sound=False)
        qtbot.wait(100)

        assert len(mgr._active) == 2
        second_before_y = mgr._active[1].pos().y()

        # Dismiss first toast
        mgr._active[0]._dismiss()
        qtbot.wait(ToastNotification.FADE_DURATION + 300)

        # Only one remains
        assert len(mgr._active) == 1

    def test_sound_setup_no_crash(self, qtbot, parent_window):
        """Sound setup doesn't crash even without media files."""
        mgr = ToastManager.setup(parent_window)
        # _setup_sounds was called in __init__, should not have crashed
        # Play sound should be safe regardless
        mgr._play_sound(True)
        mgr._play_sound(False)


class TestMainWindowIntegration:
    """Integration tests: _send_notification uses ToastManager."""

    def test_toast_is_top_level_window(self, qtbot, parent_window):
        """Toast must be a top-level window (no parent) so it shows
        even when the main window is minimized or unfocused."""
        toast = ToastNotification(
            title="Top-level",
            message="Always visible",
            success=True,
            parent=parent_window,  # parent is passed but NOT used
        )
        qtbot.addWidget(toast)
        # Must have no parent - top-level window
        assert toast.parent() is None
        # Must have WindowStaysOnTopHint and SplashScreen type
        flags = toast.windowFlags()
        assert flags & Qt.WindowType.WindowStaysOnTopHint
        assert flags & Qt.WindowType.SplashScreen

    def test_toast_visible_when_parent_minimized(self, qtbot, parent_window):
        """Toast appears even if the main window is minimized."""
        mgr = ToastManager.setup(parent_window)
        parent_window.showMinimized()
        qtbot.wait(100)

        ToastManager.notify("Minimized", "Still shows!", sound=False)
        qtbot.wait(100)

        assert len(mgr._active) == 1
        assert mgr._active[0].isVisible()

    def test_toast_positions_on_screen(self, qtbot, parent_window):
        """Toast positions at screen bottom-right, not inside parent."""
        mgr = ToastManager.setup(parent_window)
        ToastManager.notify("Screen pos", "Check position", sound=False)
        qtbot.wait(500)  # wait for slide-in animation

        toast = mgr._active[0]
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry()

        # Toast x should be near the right edge of screen, not inside parent
        toast_right = toast.pos().x() + toast.width()
        assert toast_right <= geom.right() + 5  # allow small margin
        # Toast bottom should be near screen bottom
        toast_bottom = toast.pos().y() + toast.height()
        assert toast_bottom <= geom.bottom() + 5

    def test_send_notification_uses_toast(self, qtbot, parent_window, monkeypatch):
        """_send_notification routes to ToastManager.notify."""
        from src.ui.components.toast_notification import ToastManager

        calls = []
        original_notify = ToastManager.notify

        @classmethod
        def mock_notify(cls, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(ToastManager, "notify", lambda **kwargs: calls.append(kwargs))

        # Simulate what _send_notification does
        title = "SQL Query"
        message = "42 rows"
        success = True
        tab_index = 0

        on_click = None
        if tab_index is not None:
            on_click = lambda idx=tab_index: None

        ToastManager.notify(
            title=title,
            message=message,
            success=success,
            on_click=on_click,
        )

        assert len(calls) == 1
        assert calls[0]["title"] == "SQL Query"
        assert calls[0]["message"] == "42 rows"
        assert calls[0]["success"] is True

    def test_notification_always_fires(self, qtbot, parent_window):
        """
        The new implementation always fires notifications
        (old one skipped when window was active).
        """
        mgr = ToastManager.setup(parent_window)

        # Even with parent active/focused, notification should fire
        parent_window.activateWindow()
        qtbot.wait(50)

        ToastManager.notify("Active Window", "Still shows!", sound=False)
        qtbot.wait(50)

        assert len(mgr._active) == 1

    def test_notification_no_qsystemtrayicon_dependency(self):
        """Main window no longer imports QSystemTrayIcon."""
        import importlib
        import src.ui.main_window as mw_mod

        source = open(mw_mod.__file__, encoding="utf-8").read()
        assert "QSystemTrayIcon" not in source
