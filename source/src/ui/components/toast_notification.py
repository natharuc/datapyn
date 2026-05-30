"""
Toast notification widget - in-app notification system.

Modern card-style toasts stacked in the bottom-right corner.
Does NOT depend on OS desktop notifications.
"""

import logging
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QUrl,
    pyqtSignal, QRect, QElapsedTimer,
)
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton,
    QGraphicsOpacityEffect, QApplication, QFrame,
)

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtMultimedia import QSoundEffect
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False
    logger.debug("QtMultimedia not available - toast sounds disabled")


_manager: Optional["ToastManager"] = None


class _ToastProgressBar(QWidget):
    """Thin progress strip showing remaining display time."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._progress = 1.0
        self.setFixedHeight(3)

    def set_progress(self, value: float):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(255, 255, 255, 25)
        painter.fillRect(self.rect(), bg)
        if self._progress <= 0:
            return
        fill_w = int(self.width() * self._progress)
        painter.fillRect(QRect(0, 0, fill_w, self.height()), QColor(self._color))


class ToastNotification(QWidget):
    """A single toast notification widget."""

    clicked = pyqtSignal()
    closed = pyqtSignal(object)

    DURATION_DEFAULT = 4500
    DURATION_ERROR = 6500
    SLIDE_DURATION = 280
    FADE_DURATION = 220

    WIDTH = 360
    MIN_HEIGHT = 72
    MARGIN = 16

    def __init__(
        self,
        title: str,
        message: str,
        success: bool = True,
        duration: int = 0,
        parent: QWidget = None,
        on_click=None,
        color: str = None,
    ):
        super().__init__(None)
        self._on_click = on_click
        self._duration = duration or (self.DURATION_DEFAULT if success else self.DURATION_ERROR)
        self._success = success
        self._accent = color or ("#22c55e" if success else "#ef4444")

        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._build_ui(title, message)
        self._setup_animation()

    def _build_ui(self, title: str, message: str):
        shell = QFrame(self)
        shell.setObjectName("toastShell")
        shell.setStyleSheet("""
            QFrame#toastShell {
                background-color: #1f1f23;
                border: 1px solid #3f3f46;
                border-radius: 10px;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(14, 12, 10, 10)
        body.setSpacing(12)

        accent = QFrame()
        accent.setFixedSize(4, 40)
        accent.setStyleSheet(f"background-color: {self._accent}; border-radius: 2px;")
        body.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

        icon_wrap = QLabel("\u2713" if self._success else "\u2717")
        icon_wrap.setFixedSize(28, 28)
        icon_wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_wrap.setStyleSheet(
            f"color: {self._accent}; background: rgba(255,255,255,12);"
            "border-radius: 14px; font-size: 14px; font-weight: 700;"
        )
        body.addWidget(icon_wrap, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #f4f4f5; background: transparent; border: none;")
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)

        msg_label = QLabel(message)
        msg_label.setFont(QFont("Segoe UI", 9))
        msg_label.setStyleSheet("color: #a1a1aa; background: transparent; border: none;")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)
        body.addLayout(text_layout, 1)

        close_btn = QPushButton("\u00d7")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                color: #71717a;
                background: transparent;
                border: none;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                color: #e4e4e7;
                background: rgba(255,255,255,18);
            }
        """)
        close_btn.clicked.connect(self._dismiss)
        body.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        root.addLayout(body)

        self._progress = _ToastProgressBar(self._accent, shell)
        root.addWidget(self._progress)

    def _setup_animation(self):
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._fade_out)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(40)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_elapsed = QElapsedTimer()

    def _tick_progress(self):
        if not self._progress_elapsed.isValid():
            return
        remaining = max(0.0, 1.0 - (self._progress_elapsed.elapsed() / float(self._duration)))
        self._progress.set_progress(remaining)

    def show_at(self, x: int, y: int):
        start_x = x + self.WIDTH + 24
        self.move(start_x, y)
        self.show()
        self.raise_()

        try:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        except Exception:
            pass

        self._slide_anim = QPropertyAnimation(self, b"pos")
        self._slide_anim.setDuration(self.SLIDE_DURATION)
        self._slide_anim.setStartValue(QPoint(start_x, y))
        self._slide_anim.setEndValue(QPoint(x, y))
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.start()

        self._progress_elapsed.start()
        self._progress_timer.start()
        self._dismiss_timer.start(self._duration)

    def _fade_out(self):
        self._progress_timer.stop()
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_anim.setDuration(self.FADE_DURATION)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade_anim.finished.connect(self._close_final)
        self._fade_anim.start()

    def _close_final(self):
        self.closed.emit(self)
        self.close()
        self.deleteLater()

    def _dismiss(self):
        self._dismiss_timer.stop()
        self._progress_timer.stop()
        self._fade_out()

    def mousePressEvent(self, event):
        if self._on_click:
            self._on_click()
        self._dismiss()

    def enterEvent(self, event):
        self._dismiss_timer.stop()
        self._progress_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._dismiss_timer.start(1800)
        self._progress_elapsed.restart()
        self._progress_timer.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(self.rect().adjusted(2, 3, -2, -1), 10, 10)


class ToastManager:
    """Manages toast notifications for a parent window."""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._active: list[ToastNotification] = []
        self._sound_success: Optional[QSoundEffect] = None
        self._sound_error: Optional[QSoundEffect] = None
        self._setup_sounds()

    @classmethod
    def setup(cls, parent: QWidget) -> "ToastManager":
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
        color: str = None,
    ):
        if _manager is None:
            logger.debug("ToastManager not initialized - skipping notification")
            return
        _manager._show(title, message, success, on_click, sound, color)

    def _show(
        self,
        title: str,
        message: str,
        success: bool,
        on_click,
        sound: bool,
        color: str = None,
    ):
        toast = ToastNotification(
            title=title,
            message=message,
            success=success,
            on_click=on_click,
            color=color,
        )
        toast.closed.connect(self._on_toast_closed)
        self._active.append(toast)
        self._reposition_all()
        if sound:
            self._play_sound(success)

    def _on_toast_closed(self, toast: ToastNotification):
        if toast in self._active:
            self._active.remove(toast)
            self._reposition_all()

    def _reposition_all(self):
        screen = None
        if self._parent and self._parent.isVisible():
            screen = self._parent.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        geom = screen.availableGeometry()
        margin = ToastNotification.MARGIN
        y_offset = margin
        for toast in reversed(self._active):
            toast.adjustSize()
            th = max(toast.sizeHint().height(), ToastNotification.MIN_HEIGHT)
            x = geom.right() - ToastNotification.WIDTH - margin
            y = geom.bottom() - th - y_offset

            if toast.isVisible():
                anim = QPropertyAnimation(toast, b"pos")
                anim.setDuration(150)
                anim.setEndValue(QPoint(x, y))
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()
                toast._repos_anim = anim
            else:
                toast.show_at(x, y)

            y_offset += th + 8

    def _setup_sounds(self):
        if not HAS_SOUND:
            return
        try:
            import os
            self._sound_success = QSoundEffect()
            self._sound_success.setVolume(0.25)
            self._sound_error = QSoundEffect()
            self._sound_error.setVolume(0.35)
            win_media = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media")
            success_path = os.path.join(win_media, "Windows Notify System Generic.wav")
            error_path = os.path.join(win_media, "Windows Notify Calendar.wav")
            if not os.path.exists(success_path):
                success_path = os.path.join(win_media, "chimes.wav")
            if not os.path.exists(error_path):
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
        try:
            sound = self._sound_success if success else self._sound_error
            if sound and sound.isLoaded():
                sound.play()
        except Exception:
            pass
