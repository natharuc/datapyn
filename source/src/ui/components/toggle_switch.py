"""
Toggle switch — compact pill track + sliding thumb (subtle, not full-color track).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from src.design_system.tokens import get_colors


class ToggleSwitch(QWidget):
    """Small on/off switch: neutral track, thumb moves and picks up accent when on."""

    toggled = pyqtSignal(bool)

    TRACK_WIDTH = 34
    TRACK_HEIGHT = 18
    THUMB_SIZE = 14
    THUMB_MARGIN = 2

    def __init__(self, parent=None, *, checked: bool = True):
        super().__init__(parent)
        self._checked = bool(checked)
        self._hover = False

        self.setFixedSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, animate: bool = True) -> None:
        _ = animate  # kept for API compat; instant snap feels calmer in dense UIs
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(self._checked)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event):
        colors = get_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        radius = h / 2.0

        track = QColor(colors.bg_tertiary)
        if self._hover:
            track = QColor(colors.bg_elevated)

        border = QColor(colors.border_default)
        if self._checked and self._hover:
            border = QColor(colors.interactive_primary)

        painter.setPen(QPen(border, 1))
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, w - 1, h - 1, radius, radius)

        travel = w - 2 * self.THUMB_MARGIN - self.THUMB_SIZE
        thumb_x = self.THUMB_MARGIN + (travel if self._checked else 0)
        thumb_y = (h - self.THUMB_SIZE) / 2.0

        if self._checked:
            thumb = QColor(colors.interactive_primary)
        else:
            thumb = QColor(colors.text_tertiary)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(thumb)
        painter.drawEllipse(int(thumb_x), int(thumb_y), self.THUMB_SIZE, self.THUMB_SIZE)


class LabeledToggleSwitch(QWidget):
    """Label + :class:`ToggleSwitch` on one row."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str = "", parent=None, *, checked: bool = False):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.switch = ToggleSwitch(checked=checked)
        self.label = QLabel(text)
        colors = get_colors()
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; background: transparent;"
        )

        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.switch.toggled.connect(self.toggled.emit)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool, *, animate: bool = True) -> None:
        self.switch.setChecked(checked, animate=animate)
