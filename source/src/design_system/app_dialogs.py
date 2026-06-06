"""
Unified application dialogs — single entry point for the whole app.

Kinds: Success, Warning, Information, Danger (+ confirmations and progress).
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.design_system.button import GhostButton, PrimaryButton, SecondaryButton
from src.design_system.frameless_dialog import install_frameless_shell
from src.design_system.message_box import (
    _BaseMessageDialog,
    ask_confirm,
    ask_yes_no,
)
from src.design_system.tokens import TYPOGRAPHY, get_colors
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class DialogKind(Enum):
    SUCCESS = "success"
    WARNING = "warning"
    INFORMATION = "information"
    DANGER = "danger"


_KIND_ICONS = {
    DialogKind.SUCCESS: "mdi.check-circle-outline",
    DialogKind.WARNING: "mdi.alert-outline",
    DialogKind.INFORMATION: "mdi.information-outline",
    DialogKind.DANGER: "mdi.alert-circle-outline",
}


def _flat_icon(name: str, size: int = 32) -> QLabel:
    colors = get_colors()
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    if HAS_QTAWESOME:
        label.setPixmap(qta.icon(name, color=colors.text_tertiary).pixmap(size, size))
    return label


def show_message(
    parent: Optional[QWidget],
    kind: DialogKind,
    title: str,
    message: str,
) -> None:
    """Single OK — use instead of QMessageBox.information/warning/critical."""
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name=_KIND_ICONS[kind],
        min_height=180,
    )
    ok_btn = PrimaryButton(S.dialogs.btn_ok, size="sm")
    ok_btn.clicked.connect(dlg.accept)
    dlg._add_footer_buttons(ok_btn)
    dlg.exec()


def show_success(parent: Optional[QWidget], title: str, message: str) -> None:
    show_message(parent, DialogKind.SUCCESS, title, message)


def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    show_message(parent, DialogKind.WARNING, title, message)


def show_information(parent: Optional[QWidget], title: str, message: str) -> None:
    show_message(parent, DialogKind.INFORMATION, title, message)


def show_danger(parent: Optional[QWidget], title: str, message: str) -> None:
    show_message(parent, DialogKind.DANGER, title, message)


def confirm_yes_no(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    default_yes: bool = False,
) -> bool:
    """Yes / No confirmation (frameless)."""
    return ask_yes_no(parent, title, message, default_yes=default_yes)


def confirm_ok_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    destructive: bool = False,
    confirm_label: str | None = None,
    cancel_label: str | None = None,
) -> bool:
    """OK / Cancel — cancel is ghost on the left, confirm on the right."""
    return ask_confirm(
        parent,
        title,
        message,
        confirm_label=confirm_label or S.dialogs.btn_ok,
        cancel_label=cancel_label or S.dialogs.btn_cancel,
        destructive=destructive,
    )


class FramelessProgressDialog(QDialog):
    """Indeterminate progress with optional cancel (connection test, etc.)."""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        *,
        cancel_text: str | None = None,
        on_cancel: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._on_cancel = on_cancel
        colors = get_colors()

        layout = install_frameless_shell(
            self,
            title,
            min_width=360,
            min_height=160,
            content_margins=(20, 14, 20, 16),
            content_spacing=12,
        )

        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: {TYPOGRAPHY.text_base}px;"
        )
        layout.addWidget(lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        layout.addWidget(self._bar)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = GhostButton(cancel_text or S.dialogs.btn_cancel, size="sm")
        cancel_btn.clicked.connect(self._handle_cancel)
        footer.addWidget(cancel_btn)
        layout.addLayout(footer)

    def _handle_cancel(self) -> None:
        if self._on_cancel:
            self._on_cancel()
        self.reject()

    def set_message(self, text: str) -> None:
        for child in self.findChildren(QLabel):
            if child.objectName() != "framelessTitle":
                child.setText(text)
                break


def show_periodic_execution_dialog(
    parent: Optional[QWidget],
    *,
    default_seconds: int = 30,
) -> int | None:
    """Return chosen interval in seconds, or None if cancelled."""
    dialog = QDialog(parent)
    colors = get_colors()
    presets = (5, 10, 20, 30, 40, 50, 60)

    layout = install_frameless_shell(
        dialog,
        S.toolbar.run_timer_title,
        min_width=380,
        min_height=220,
        content_margins=(20, 14, 20, 16),
        content_spacing=12,
    )

    layout.addWidget(QLabel(S.toolbar.run_timer_label))

    spin = QSpinBox()
    spin.setRange(1, 86400)
    spin.setValue(default_seconds if default_seconds > 0 else 30)
    spin.setSuffix("s")
    spin.selectAll()
    spin.setStyleSheet(f"""
        QSpinBox {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: 6px;
            padding: 6px 10px;
            min-height: 28px;
        }}
        QSpinBox:focus {{ border-color: {colors.interactive_primary}; }}
    """)
    layout.addWidget(spin)

    preset_row = QHBoxLayout()
    preset_row.setSpacing(6)
    chosen = {"value": None}

    def accept_preset(seconds: int) -> None:
        chosen["value"] = seconds
        dialog.accept()

    for sec in presets:
        btn = SecondaryButton(f"{sec}s", size="sm")
        btn.setFixedWidth(44)
        btn.clicked.connect(lambda _c=False, s=sec: accept_preset(s))
        preset_row.addWidget(btn)
    preset_row.addStretch()
    layout.addLayout(preset_row)

    footer = QHBoxLayout()
    cancel_btn = GhostButton(S.dialogs.btn_cancel, size="sm")
    start_btn = PrimaryButton(S.toolbar.run_timer_start, size="sm")
    cancel_btn.clicked.connect(dialog.reject)
    start_btn.clicked.connect(dialog.accept)
    footer.addWidget(cancel_btn)
    footer.addStretch()
    footer.addWidget(start_btn)
    layout.addLayout(footer)

    line_edit = spin.lineEdit()

    class _SelectAllOnFocus(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() == QEvent.Type.FocusIn:
                obj.selectAll()
            return False

    _select_filter = _SelectAllOnFocus(dialog)
    line_edit.installEventFilter(_select_filter)
    line_edit.selectAll()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    if chosen["value"] is not None:
        return chosen["value"]
    return spin.value()
