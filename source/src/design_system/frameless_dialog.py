"""
Frameless modal dialogs with custom title bar (close only, no min/max).

Chrome colors match the installer / frameless dark (#0c111b). Dialog content
uses design-system tokens (get_colors) for forms, inputs, and panels.
"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.design_system.tokens import (
    CHROME_ACCENT,
    CHROME_BG,
    CHROME_BORDER,
    CHROME_MUTED,
    CHROME_TEXT,
    get_colors,
    get_dialog_base_stylesheet,
    RADIUS,
)

CHROME_CYAN = "#33c2ff"


def frameless_shell_stylesheet() -> str:
    """Styles for the outer shell only (not form content)."""
    return f"""
        QDialog {{
            background: transparent;
        }}
        QFrame#framelessShell {{
            background: {CHROME_BG};
            border: 1px solid {CHROME_BORDER};
            border-radius: {RADIUS.radius_md}px;
        }}
        QWidget#framelessBody {{
            background: transparent;
        }}
        QLabel#framelessTitle {{
            color: {CHROME_TEXT};
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton#framelessClose {{
            background: transparent;
            color: {CHROME_MUTED};
            border: none;
            border-radius: 6px;
            font-size: 16px;
            min-width: 28px;
            max-width: 28px;
            padding: 0;
        }}
        QPushButton#framelessClose:hover {{
            background: rgba(239, 68, 68, 0.12);
            color: #f87171;
        }}
        QSizeGrip {{
            background: transparent;
            width: 14px;
            height: 14px;
        }}
    """


def frameless_body_stylesheet(extra: str = "") -> str:
    """Styles for widgets inside the dialog body (design-system dark)."""
    from src.design_system.tokens import get_section_panel_stylesheet

    return get_dialog_base_stylesheet() + get_section_panel_stylesheet() + extra


class DialogTitleBar(QWidget):
    """Draggable title bar with an optional close button."""

    def __init__(self, dialog: QDialog, title: str, *, show_close: bool = True):
        super().__init__(dialog)
        self._dialog = dialog
        self._drag_pos: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 8, 8)
        row.setSpacing(8)

        label = QLabel(title)
        label.setObjectName("framelessTitle")
        row.addWidget(label, 1)

        if show_close:
            close_btn = QPushButton("×")
            close_btn.setObjectName("framelessClose")
            close_btn.setFixedSize(28, 28)
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.clicked.connect(dialog.reject)
            row.addWidget(close_btn)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None


def install_frameless_shell(
    dialog: QDialog,
    title: str,
    *,
    min_width: int | None = None,
    min_height: int | None = None,
    outer_margins: tuple[int, int, int, int] = (14, 14, 14, 14),
    content_margins: tuple[int, int, int, int] = (20, 16, 20, 20),
    content_spacing: int = 12,
    show_close: bool = True,
    resizable: bool = True,
    body_stylesheet_extra: str = "",
) -> QVBoxLayout:
    """
    Configure a QDialog as frameless and return the inner content layout.

    Sets ``dialog._frameless_body`` to the content host widget for optional tweaks.
    """
    dialog.setWindowFlags(
        Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    dialog.setModal(True)

    if min_width is not None and min_height is not None:
        dialog.setMinimumSize(min_width, min_height)
    else:
        if min_width is not None:
            dialog.setMinimumWidth(min_width)
        if min_height is not None:
            dialog.setMinimumHeight(min_height)

    dialog.setStyleSheet(frameless_shell_stylesheet())

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(*outer_margins)
    outer.setSpacing(0)

    shell = QFrame()
    shell.setObjectName("framelessShell")
    shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    shell_layout = QVBoxLayout(shell)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    shell_layout.addWidget(DialogTitleBar(dialog, title, show_close=show_close))

    accent = QFrame()
    accent.setFixedHeight(2)
    accent.setStyleSheet(
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {CHROME_ACCENT}, stop:0.5 {CHROME_CYAN}, stop:1 {CHROME_ACCENT}); border: none;"
    )
    shell_layout.addWidget(accent)

    body = QWidget()
    body.setObjectName("framelessBody")
    body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    body.setStyleSheet(frameless_body_stylesheet(body_stylesheet_extra))
    content_layout = QVBoxLayout(body)
    content_layout.setContentsMargins(*content_margins)
    content_layout.setSpacing(content_spacing)
    shell_layout.addWidget(body, 1)

    if resizable:
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(shell)
        grip.setFixedSize(14, 14)
        grip_row.addWidget(grip)
        shell_layout.addLayout(grip_row)

    outer.addWidget(shell, 1)

    dialog._frameless_body = body  # type: ignore[attr-defined]
    dialog._frameless_shell = shell  # type: ignore[attr-defined]
    return content_layout


def widget_is_valid(widget) -> bool:
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except Exception:
        return False
