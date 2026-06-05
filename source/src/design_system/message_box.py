"""
Frameless message / confirmation dialogs with flat icons (replaces QMessageBox chrome).
"""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.design_system.button import GhostButton, PrimaryButton, SecondaryButton
from src.design_system.frameless_dialog import install_frameless_shell
from src.design_system.tokens import TYPOGRAPHY, get_colors
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


SaveDiscardCancel = Literal["save", "discard", "cancel"]
YesNoCancel = Literal["yes", "no", "cancel"]
WorkspaceSwitchAction = Literal["restart", "new_instance", "cancel"]


def _flat_icon(name: str, size: int = 32) -> QLabel:
    """Monochrome icon — same tone as body text, no accent colors."""
    colors = get_colors()
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    if HAS_QTAWESOME:
        label.setPixmap(
            qta.icon(name, color=colors.text_tertiary).pixmap(size, size)
        )
    return label


class _BaseMessageDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        *,
        icon_name: Optional[str] = None,
        min_width: int = 420,
        min_height: int = 200,
    ):
        super().__init__(parent)
        colors = get_colors()
        self._body_layout = install_frameless_shell(
            self,
            title,
            min_width=min_width,
            min_height=min_height,
            content_margins=(20, 16, 20, 12),
            content_spacing=0,
        )

        content = QVBoxLayout()
        content.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(14)
        if icon_name:
            row.addWidget(_flat_icon(icon_name))
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: {TYPOGRAPHY.text_base}px;"
            f" line-height: 1.45;"
        )
        row.addWidget(msg, 1)
        content.addLayout(row)

        content.addStretch(1)
        self._footer_layout = QHBoxLayout()
        self._footer_layout.setSpacing(8)
        self._footer_layout.setContentsMargins(0, 8, 0, 0)
        content.addLayout(self._footer_layout)

        self._body_layout.addLayout(content)

    def _add_footer_buttons(self, *buttons) -> None:
        self._footer_layout.addStretch()
        for btn in buttons:
            self._footer_layout.addWidget(btn)


def ask_save_discard_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
) -> SaveDiscardCancel:
    """Unsaved changes — Save / Don't Save / Cancel."""
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        min_width=440,
        min_height=200,
    )
    result: SaveDiscardCancel = "cancel"

    def pick(value: SaveDiscardCancel):
        nonlocal result
        result = value
        dlg.accept()

    cancel_btn = GhostButton(
        getattr(S.dialogs, "cancel_btn", "Cancel"), size="sm"
    )
    cancel_btn.clicked.connect(dlg.reject)

    discard_btn = SecondaryButton(S.dialogs.dont_save_btn, size="sm")
    discard_btn.clicked.connect(lambda: pick("discard"))

    save_btn = PrimaryButton(S.dialogs.save_btn, size="sm")
    save_btn.setDefault(True)
    save_btn.clicked.connect(lambda: pick("save"))

    dlg._add_footer_buttons(cancel_btn, discard_btn, save_btn)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return "cancel"
    return result


def ask_yes_no(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    default_yes: bool = False,
) -> bool:
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.help-circle-outline",
        min_height=180,
    )
    accepted = {"value": False}

    yes_btn = PrimaryButton(getattr(S.dialogs, "yes_btn", "Yes"), size="sm")
    no_btn = SecondaryButton(getattr(S.dialogs, "no_btn", "No"), size="sm")

    def _yes():
        accepted["value"] = True
        dlg.accept()

    yes_btn.clicked.connect(_yes)
    no_btn.clicked.connect(dlg.reject)
    if default_yes:
        yes_btn.setDefault(True)
    else:
        no_btn.setDefault(True)

    dlg._add_footer_buttons(no_btn, yes_btn)
    dlg.exec()
    return accepted["value"]


def ask_yes_no_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
) -> YesNoCancel:
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.help-circle-outline",
        min_height=180,
    )
    choice: YesNoCancel = "cancel"

    def pick(v: YesNoCancel):
        nonlocal choice
        choice = v
        dlg.accept()

    cancel_btn = GhostButton(
        getattr(S.dialogs, "cancel_btn", "Cancel"), size="sm"
    )
    cancel_btn.clicked.connect(dlg.reject)
    no_btn = SecondaryButton(getattr(S.dialogs, "no_btn", "No"), size="sm")
    yes_btn = PrimaryButton(getattr(S.dialogs, "yes_btn", "Yes"), size="sm")
    no_btn.clicked.connect(lambda: pick("no"))
    yes_btn.clicked.connect(lambda: pick("yes"))

    dlg._add_footer_buttons(cancel_btn, no_btn, yes_btn)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return "cancel"
    return choice


def show_info(parent: Optional[QWidget], title: str, message: str) -> None:
    """Single OK — informational (replaces QMessageBox.information)."""
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.information-outline",
        min_height=180,
    )
    ok_btn = PrimaryButton(getattr(S.dialogs, "btn_ok", "OK"), size="sm")
    ok_btn.clicked.connect(dlg.accept)
    dlg._add_footer_buttons(ok_btn)
    dlg.exec()


def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    """Single OK — warning (replaces QMessageBox.warning)."""
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.alert-outline",
        min_height=180,
    )
    ok_btn = PrimaryButton(getattr(S.dialogs, "btn_ok", "OK"), size="sm")
    ok_btn.clicked.connect(dlg.accept)
    dlg._add_footer_buttons(ok_btn)
    dlg.exec()


def show_error(parent: Optional[QWidget], title: str, message: str) -> None:
    """Single OK — error (replaces QMessageBox.critical)."""
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.alert-circle-outline",
        min_height=180,
    )
    ok_btn = PrimaryButton(getattr(S.dialogs, "btn_ok", "OK"), size="sm")
    ok_btn.clicked.connect(dlg.accept)
    dlg._add_footer_buttons(ok_btn)
    dlg.exec()


def ask_confirm(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    confirm_label: str = "OK",
    cancel_label: str = "Cancel",
    destructive: bool = False,
) -> bool:
    icon = "mdi.alert-circle-outline" if destructive else "mdi.information-outline"
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name=icon,
        min_height=180,
    )
    cancel_btn = GhostButton(cancel_label, size="sm")
    cancel_btn.clicked.connect(dlg.reject)
    ok_btn = SecondaryButton(confirm_label, size="sm") if destructive else PrimaryButton(
        confirm_label, size="sm"
    )
    ok_btn.clicked.connect(dlg.accept)
    dlg._add_footer_buttons(cancel_btn, ok_btn)
    return dlg.exec() == QDialog.DialogCode.Accepted


def ask_quit_application(parent: Optional[QWidget]) -> bool:
    """Frameless confirmation before closing the application."""
    title = getattr(
        S.dialogs, "quit_confirm_title", getattr(S.dialogs, "close_confirm_title", "")
    )
    message = getattr(
        S.dialogs,
        "quit_confirm_message",
        getattr(S.dialogs, "close_confirm_msg", ""),
    )
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        icon_name="mdi.exit-to-app",
        min_width=440,
        min_height=200,
    )
    accepted = {"value": False}

    stay_btn = SecondaryButton(
        getattr(S.dialogs, "stay_btn", getattr(S.dialogs, "no_btn", "Stay")),
        size="sm",
    )
    quit_btn = PrimaryButton(
        getattr(S.dialogs, "quit_btn", getattr(S.dialogs, "yes_btn", "Quit")),
        size="sm",
    )
    stay_btn.setDefault(True)
    stay_btn.clicked.connect(dlg.reject)

    def _quit():
        accepted["value"] = True
        dlg.accept()

    quit_btn.clicked.connect(_quit)
    dlg._add_footer_buttons(stay_btn, quit_btn)
    dlg.exec()
    return accepted["value"]


def ask_workspace_switch(parent: Optional[QWidget]) -> WorkspaceSwitchAction:
    """Frameless dialog — how to open a different workspace."""
    title = getattr(S.settings, "workspace_switch_title", "Switch Workspace")
    message = getattr(
        S.settings,
        "workspace_switch_message",
        "Choose how you want to open the selected workspace:",
    )
    dlg = _BaseMessageDialog(
        parent,
        title,
        message,
        min_width=480,
        min_height=168,
    )
    choice: WorkspaceSwitchAction = "cancel"

    def pick(action: WorkspaceSwitchAction) -> None:
        nonlocal choice
        choice = action
        dlg.accept()

    cancel_btn = GhostButton(
        getattr(S.general, "cancel", getattr(S.dialogs, "cancel_btn", "Cancel")),
        size="sm",
    )
    cancel_btn.clicked.connect(dlg.reject)

    new_instance_btn = SecondaryButton(
        getattr(S.settings, "workspace_switch_new_instance", "Open New Instance"),
        size="sm",
    )
    new_instance_btn.setToolTip(
        getattr(S.settings, "workspace_switch_new_instance_tooltip", "")
    )
    new_instance_btn.clicked.connect(lambda: pick("new_instance"))

    restart_btn = PrimaryButton(
        getattr(S.settings, "workspace_switch_restart", "Restart Current App"),
        size="sm",
    )
    restart_btn.setToolTip(
        getattr(S.settings, "workspace_switch_restart_tooltip", "")
    )
    restart_btn.clicked.connect(lambda: pick("restart"))

    dlg._add_footer_buttons(cancel_btn, new_instance_btn, restart_btn)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return "cancel"
    return choice
