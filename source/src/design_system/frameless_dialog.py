"""
Frameless modal dialogs with custom title bar (close only, no min/max).

Chrome colors match the installer / frameless dark (#0c111b). Dialog content
uses design-system tokens (get_colors) for forms, inputs, and panels.
"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, Qt, QPoint, QRectF, QTimer
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath
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
_SHELL_SHADOW_PAD = 20
_SHELL_CORNER_RADIUS = float(RADIUS.radius_md)


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


class _FramelessShadowHost(QWidget):
    """Paints a soft rounded shadow; child shell stays inside the padded area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event):  # noqa: N802
        if self.width() < 4 or self.height() < 4:
            return
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = QRectF(self.rect()).adjusted(
            _SHELL_SHADOW_PAD,
            _SHELL_SHADOW_PAD,
            -_SHELL_SHADOW_PAD,
            -_SHELL_SHADOW_PAD,
        )
        radius = _SHELL_CORNER_RADIUS
        for spread, alpha in ((16, 22), (11, 18), (7, 14), (4, 10)):
            shadow_rect = inner.adjusted(-spread, -spread + 2, spread, spread + 4)
            path = QPainterPath()
            path.addRoundedRect(shadow_rect, radius + spread * 0.35, radius + spread * 0.35)
            painter.fillPath(path, QColor(0, 0, 0, alpha))
        painter.end()


class _ModalBackdrop(QWidget):
    """Dim the parent window while a modal dialog is open."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        colors = get_colors()
        self.setObjectName("modalBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {colors.bg_overlay};")
        self.setAutoFillBackground(True)
        self._sync_geometry()

    def _sync_geometry(self) -> None:
        host = self.parentWidget()
        if host is not None:
            self.setGeometry(host.rect())

    def showEvent(self, event):
        self._sync_geometry()
        super().showEvent(event)


class _ModalBackdropController(QObject):
    """Show/hide a dim overlay on the dialog host window."""

    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._dialog = dialog
        self._backdrop: _ModalBackdrop | None = None
        self._host: QWidget | None = None

    def _resolve_host(self) -> QWidget | None:
        host = self._dialog.parentWidget()
        while host is not None and not host.isWindow():
            host = host.parentWidget()
        if host is None or host is self._dialog:
            host = self._dialog.window()
        if host is self._dialog:
            from PyQt6.QtWidgets import QApplication

            active = QApplication.activeWindow()
            if active is not None and active is not self._dialog:
                host = active
            else:
                return None
        return host

    def show(self) -> None:
        if not widget_is_valid(self._dialog) or not self._dialog.isVisible():
            return
        host = self._resolve_host()
        if host is None or not widget_is_valid(host):
            return
        self._host = host
        if self._backdrop is None:
            self._backdrop = _ModalBackdrop(host)
            host.installEventFilter(self)
        if not widget_is_valid(self._backdrop):
            self._backdrop = _ModalBackdrop(host)
        self._backdrop._sync_geometry()
        self._backdrop.show()
        self._backdrop.raise_()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def hide(self) -> None:
        if self._host is not None:
            self._host.removeEventFilter(self)
            self._host = None
        if self._backdrop is not None:
            self._backdrop.hide()
            self._backdrop.deleteLater()
            self._backdrop = None

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._host and event.type() == QEvent.Type.Resize:
            if self._backdrop is not None:
                self._backdrop._sync_geometry()
        return False


class _DialogBackdropFilter(QObject):
    """Event filter that toggles the dim overlay when the dialog opens/closes."""

    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._controller = _ModalBackdropController(dialog)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._controller.show)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.parent():
            if event.type() == QEvent.Type.Show:
                self._show_timer.start(0)
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self._show_timer.stop()
                self._controller.hide()
        return False


def attach_modal_backdrop(dialog: QDialog) -> _DialogBackdropFilter:
    """Dim the parent window while ``dialog`` is visible."""
    filt = _DialogBackdropFilter(dialog)
    dialog.installEventFilter(filt)
    dialog._modal_backdrop_filter = filt  # type: ignore[attr-defined]
    return filt


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
        Qt.WindowType.Dialog
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.Window
        | Qt.WindowType.NoDropShadowWindowHint
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

    shadow_pad = _SHELL_SHADOW_PAD
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    shadow_host = _FramelessShadowHost()
    shadow_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    shadow_layout = QVBoxLayout(shadow_host)
    shadow_layout.setContentsMargins(shadow_pad, shadow_pad, shadow_pad, shadow_pad)
    shadow_layout.setSpacing(0)

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

    shadow_layout.addWidget(shell, 1)
    outer.addWidget(shadow_host, 1)

    dialog._frameless_body = body  # type: ignore[attr-defined]
    dialog._frameless_shell = shell  # type: ignore[attr-defined]
    dialog._frameless_shadow_host = shadow_host  # type: ignore[attr-defined]
    attach_modal_backdrop(dialog)
    return content_layout


def widget_is_valid(widget) -> bool:
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except Exception:
        return False
