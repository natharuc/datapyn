"""
Toast notification widget - in-app notification system.

Custom notification "toast" that appears in the bottom-right corner
of the main window. Does NOT depend on OS desktop notifications.

Features:
- Slides in from the right edge
- Auto-dismisses after a configurable timeout
- Click to dismiss or focus the originating tab
- Optional sound feedback
- Stacks multiple notifications vertically
- Themed to match the app's dark theme
"""

import logging
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton,
    QGraphicsOpacityEffect, QApplication,
)

logger = logging.getLogger(__name__)

# Try to import QSoundEffect for audio feedback
try:
    from PyQt6.QtMultimedia import QSoundEffect
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False
    logger.debug("QtMultimedia not available - toast sounds disabled")


# Sound constants
_SOUND_SUCCESS = "success"
_SOUND_ERROR = "error"

# Module-level manager instance (set by ToastManager.setup)
_manager: Optional["ToastManager"] = None


class ToastNotification(QWidget):
    """
    A single toast notification widget.

    Appears in the bottom-right corner, auto-dismisses, and stacks.
    """

    clicked = pyqtSignal()
    closed = pyqtSignal(object)  # emits self when dismissed

    # Duration in ms
    DURATION_DEFAULT = 4000
    DURATION_ERROR = 6000
    SLIDE_DURATION = 300
    FADE_DURATION = 250

    # Size
    WIDTH = 340
    MIN_HEIGHT = 60
    MARGIN = 12  # margin from window edges

    def __init__(
        self,
        title: str,
        message: str,
        success: bool = True,
        duration: int = 0,
        parent: QWidget = None,
        on_click=None,
    ):
        # Top-level window (no parent) so it shows above everything,
        # even when the main window is minimized or unfocused.
        super().__init__(None)
        self._on_click = on_click
        self._duration = duration or (self.DURATION_DEFAULT if success else self.DURATION_ERROR)
        self._success = success

        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # SplashScreen type: top-level, frameless, always on top -- like a splash.
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._build_ui(title, message, success)
        self._setup_animation()

    def _build_ui(self, title: str, message: str, success: bool):
        """Build the toast UI."""
        # Colors
        bg = "#1e8a3e" if success else "#c0392b"
        bg_hover = "#22a347" if success else "#d44637"
        border_color = "#27ae60" if success else "#e74c3c"
        icon_char = "\u2713" if success else "\u2717"  # checkmark / cross

        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {bg};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            ToastNotification:hover {{
                background-color: {bg_hover};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)

        # Icon
        icon_label = QLabel(icon_char)
        icon_label.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        icon_label.setStyleSheet("color: white; background: transparent; border: none;")
        icon_label.setFixedWidth(24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Text area
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white; background: transparent; border: none;")
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)

        msg_label = QLabel(message)
        msg_label.setFont(QFont("Inter", 9))
        msg_label.setStyleSheet("color: rgba(255,255,255,220); background: transparent; border: none;")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)

        layout.addLayout(text_layout, 1)

        # Close button
        close_btn = QPushButton("\u00d7")  # multiplication sign
        close_btn.setFixedSize(20, 20)
        close_btn.setFont(QFont("Inter", 12))
        close_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,180);
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                color: white;
                background: rgba(255,255,255,30);
            }
        """)
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

    def _setup_animation(self):
        """Prepare slide-in and auto-dismiss timer."""
        # Opacity effect for fade out
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._fade_out)

    def show_at(self, x: int, y: int):
        """Show the toast sliding in from the right."""
        # Start position (off-screen to the right)
        start_x = x + self.WIDTH + 20
        self.move(start_x, y)
        self.show()
        self.raise_()

        # On Windows, ensure the window is actually brought forward
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        except Exception:
            pass

        # Slide in
        self._slide_anim = QPropertyAnimation(self, b"pos")
        self._slide_anim.setDuration(self.SLIDE_DURATION)
        self._slide_anim.setStartValue(QPoint(start_x, y))
        self._slide_anim.setEndValue(QPoint(x, y))
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.start()

        # Start auto-dismiss
        self._dismiss_timer.start(self._duration)

    def _fade_out(self):
        """Fade out then close."""
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_anim.setDuration(self.FADE_DURATION)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade_anim.finished.connect(self._close_final)
        self._fade_anim.start()

    def _close_final(self):
        """Final close after animation."""
        self.closed.emit(self)
        self.close()
        self.deleteLater()

    def _dismiss(self):
        """User clicked close or the toast body."""
        self._dismiss_timer.stop()
        self._fade_out()

    def mousePressEvent(self, event):
        """Click on toast: dismiss and run callback."""
        if self._on_click:
            self._on_click()
        self._dismiss()

    def enterEvent(self, event):
        """Pause auto-dismiss on hover."""
        self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Resume auto-dismiss on leave."""
        self._dismiss_timer.start(1500)
        super().leaveEvent(event)


class ToastManager:
    """
    Manages toast notifications for a parent window.

    Usage:
        ToastManager.setup(main_window)
        ToastManager.notify("SQL Query", "Complete! 42 rows", success=True)
    """

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._active: list[ToastNotification] = []
        self._sound_success: Optional[QSoundEffect] = None
        self._sound_error: Optional[QSoundEffect] = None
        self._setup_sounds()

    @classmethod
    def setup(cls, parent: QWidget) -> "ToastManager":
        """Initialize the global toast manager for the main window."""
        global _manager
        _manager = cls(parent)
        return _manager

    @classmethod
    def notify(
        cls,
        title: str,
        message: str,
        success: bool = True,
        on_click=None,
        sound: bool = True,
    ):
        """
        Show a toast notification.

        Args:
            title: Notification title (bold).
            message: Notification body text.
            success: True for green/success, False for red/error.
            on_click: Optional callback when user clicks the toast.
            sound: Whether to play a notification sound.
        """
        if _manager is None:
            logger.debug("ToastManager not initialized - skipping notification")
            return

        _manager._show(title, message, success, on_click, sound)

    def _show(
        self,
        title: str,
        message: str,
        success: bool,
        on_click,
        sound: bool,
    ):
        """Internal: create and show a toast."""
        toast = ToastNotification(
            title=title,
            message=message,
            success=success,
            parent=self._parent,
            on_click=on_click,
        )
        toast.closed.connect(self._on_toast_closed)

        self._active.append(toast)
        self._reposition_all()

        # Play sound
        if sound:
            self._play_sound(success)

    def _on_toast_closed(self, toast: ToastNotification):
        """Remove toast from active list and reposition remaining."""
        if toast in self._active:
            self._active.remove(toast)
            self._reposition_all()

    def _reposition_all(self):
        """Position all active toasts stacked from bottom-right of the screen."""
        screen = None
        if self._parent and self._parent.isVisible():
            screen = self._parent.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        # Use availableGeometry to respect the taskbar
        geom = screen.availableGeometry()
        margin = ToastNotification.MARGIN

        # Calculate positions bottom-up
        y_offset = margin
        for toast in reversed(self._active):
            toast.adjustSize()
            th = toast.sizeHint().height()
            x = geom.right() - ToastNotification.WIDTH - margin
            y = geom.bottom() - th - y_offset

            if toast.isVisible():
                # Animate reposition
                anim = QPropertyAnimation(toast, b"pos")
                anim.setDuration(150)
                anim.setEndValue(QPoint(x, y))
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()
                # Keep reference so it doesn't get GC'd
                toast._repos_anim = anim
            else:
                toast.show_at(x, y)

            y_offset += th + 6  # 6px gap between toasts

    def _setup_sounds(self):
        """Prepare notification sounds using QSoundEffect."""
        if not HAS_SOUND:
            return

        try:
            self._sound_success = QSoundEffect()
            self._sound_success.setVolume(0.3)

            self._sound_error = QSoundEffect()
            self._sound_error.setVolume(0.4)

            # Use Windows system sounds if available
            import os
            win_media = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media")

            success_path = os.path.join(win_media, "chimes.wav")
            error_path = os.path.join(win_media, "chord.wav")

            if os.path.exists(success_path):
                self._sound_success.setSource(QUrl.fromLocalFile(success_path))
            else:
                self._sound_success = None

            if os.path.exists(error_path):
                self._sound_error.setSource(QUrl.fromLocalFile(error_path))
            else:
                self._sound_error = None

        except Exception as e:
            logger.debug(f"Could not setup notification sounds: {e}")
            self._sound_success = None
            self._sound_error = None

    def _play_sound(self, success: bool):
        """Play the appropriate notification sound."""
        try:
            sound = self._sound_success if success else self._sound_error
            if sound and sound.isLoaded():
                sound.play()
        except Exception:
            pass
