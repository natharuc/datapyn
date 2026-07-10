"""
Frameless message / confirmation dialogs with flat icons (replaces QMessageBox chrome).
"""

from __future__ import annotations

from typing import Literal, Optional, Union, overload

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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


def _normalize_dialog_parent(parent: Optional[QWidget]) -> Optional[QWidget]:
    """Accept only real QWidget parents (test harnesses may pass plain objects)."""
    if parent is None:
        return None
    if isinstance(parent, QWidget):
        return parent
    return None


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
        super().__init__(_normalize_dialog_parent(parent))
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

        self._content_layout = content
        self._body_layout.addLayout(content)

    def _add_footer_buttons(self, *buttons) -> None:
        self._footer_layout.addStretch()
        for btn in buttons:
            self._footer_layout.addWidget(btn)

    def _set_footer_actions(self, left_btn, right_btn) -> None:
        """Cancel/secondary on the left, primary on the right."""
        self._footer_layout.addWidget(left_btn)
        self._footer_layout.addStretch()
        self._footer_layout.addWidget(right_btn)

    def _insert_above_footer(self, widget: QWidget) -> None:
        """Insert a widget directly above the footer button row."""
        footer_index = self._content_layout.count() - 1
        self._content_layout.insertWidget(footer_index, widget)


def _repeat_checkbox_style() -> str:
    colors = get_colors()
    return f"""
        QCheckBox {{
            color: {colors.text_secondary};
            font-size: 11px;
            font-weight: normal;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid {colors.border_default};
            border-radius: 3px;
            background-color: {colors.bg_secondary};
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors.interactive_primary};
            border-color: {colors.interactive_primary};
        }}
        QCheckBox::indicator:hover {{
            border-color: {colors.interactive_primary};
        }}
    """


def _add_repeat_checkbox(dlg: _BaseMessageDialog, label: str) -> QCheckBox:
    checkbox = QCheckBox(label)
    checkbox.setStyleSheet(_repeat_checkbox_style())
    dlg._insert_above_footer(checkbox)
    return checkbox


@overload
def ask_save_discard_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    repeat_checkbox_label: None = None,
) -> SaveDiscardCancel: ...


@overload
def ask_save_discard_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    repeat_checkbox_label: str,
) -> tuple[SaveDiscardCancel, bool]: ...


def ask_save_discard_cancel(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    repeat_checkbox_label: Optional[str] = None,
) -> Union[SaveDiscardCancel, tuple[SaveDiscardCancel, bool]]:
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

    repeat_checkbox = None
    if repeat_checkbox_label:
        repeat_checkbox = _add_repeat_checkbox(dlg, repeat_checkbox_label)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        if repeat_checkbox is not None:
            return "cancel", repeat_checkbox.isChecked()
        return "cancel"
    if repeat_checkbox is not None:
        return result, repeat_checkbox.isChecked()
    return result


@overload
def ask_yes_no(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    default_yes: bool = False,
    repeat_checkbox_label: None = None,
) -> bool: ...


@overload
def ask_yes_no(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    default_yes: bool = False,
    repeat_checkbox_label: str,
) -> tuple[bool, bool]: ...


def ask_yes_no(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    default_yes: bool = False,
    repeat_checkbox_label: Optional[str] = None,
) -> Union[bool, tuple[bool, bool]]:
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

    dlg._set_footer_actions(no_btn, yes_btn)

    for key in ("Y", "S"):
        QShortcut(QKeySequence(key), dlg, activated=yes_btn.click)
    QShortcut(QKeySequence("N"), dlg, activated=no_btn.click)

    repeat_checkbox = None
    if repeat_checkbox_label:
        repeat_checkbox = _add_repeat_checkbox(dlg, repeat_checkbox_label)

    dlg.exec()
    if repeat_checkbox is not None:
        return accepted["value"], repeat_checkbox.isChecked()
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
    from src.design_system.app_dialogs import show_information

    show_information(parent, title, message)


def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    """Single OK — warning (replaces QMessageBox.warning)."""
    from src.design_system.app_dialogs import show_warning as _show_warning

    _show_warning(parent, title, message)


def show_error(parent: Optional[QWidget], title: str, message: str) -> None:
    """Single OK — error (replaces QMessageBox.critical)."""
    from src.design_system.app_dialogs import show_danger

    show_danger(parent, title, message)


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
    dlg._set_footer_actions(cancel_btn, ok_btn)
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
