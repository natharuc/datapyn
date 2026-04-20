"""
Per-tab notification configuration dialog.

Allows users to set custom notification templates for a specific tab.
The config lives in memory and is persisted only via DPW save/load.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QGroupBox, QWidget, QColorDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from typing import Optional, Dict, Any

from src.design_system.tokens import get_colors, RADIUS
from src.language import S


class TabNotificationDialog(QDialog):
    """Dialog for configuring per-tab notification templates."""

    def __init__(self, current_config: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._config = current_config or {}
        self._result_config: Optional[Dict[str, Any]] = None
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        title = S.tab_notification.dialog_title if hasattr(S, 'tab_notification') else "Tab Notification"
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {colors.bg_primary};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        group_style = f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """
        input_style = f"""
            QLineEdit {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {colors.interactive_primary};
            }}
        """
        checkbox_style = f"""
            QCheckBox {{
                color: {colors.text_primary};
                font-size: 12px;
                spacing: 8px;
                font-weight: normal;
            }}
        """

        # --- Enable section ---
        config_group = QGroupBox(
            S.tab_notification.section_config if hasattr(S, 'tab_notification') else "NOTIFICATION CONFIG"
        )
        config_group.setStyleSheet(group_style)
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)

        self._enable_cb = QCheckBox(
            S.tab_notification.enable_custom if hasattr(S, 'tab_notification') else "Enable custom notification for this tab"
        )
        self._enable_cb.setStyleSheet(checkbox_style)
        self._enable_cb.setChecked(self._config.get("enabled", False))
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        config_layout.addWidget(self._enable_cb)
        layout.addWidget(config_group)

        # --- Template section ---
        template_group = QGroupBox(
            S.tab_notification.section_template if hasattr(S, 'tab_notification') else "MESSAGE TEMPLATE"
        )
        template_group.setStyleSheet(group_style)
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(10)

        # Variables hint
        hint_text = (
            S.tab_notification.variables_hint if hasattr(S, 'tab_notification')
            else "Variables: {{rows}}, {{blocks}}, {{tab_name}}, {{block_name}}, {{connection}}, {{database}}, {{type}}. Use {{result[row][col]}} to access query result values (e.g. {{result[0][1]}})."
        )
        hint_label = QLabel(hint_text)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.bg_elevated};
                color: {colors.text_secondary};
                font-size: 11px;
                padding: 8px 8px 8px 12px;
                border-left: 3px solid {colors.interactive_primary};
                border-radius: 4px;
                font-weight: normal;
            }}
        """)
        template_layout.addWidget(hint_label)

        label_style = f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;"
        default_title = (
            S.tab_notification.default_title if hasattr(S, 'tab_notification') else "{{tab_name}}"
        )
        default_message = (
            S.tab_notification.default_message if hasattr(S, 'tab_notification') else "{{rows}} rows - {{result[0][0]}}"
        )

        # Title field
        title_row = QHBoxLayout()
        title_label = QLabel(S.tab_notification.label_title if hasattr(S, 'tab_notification') else "Title:")
        title_label.setStyleSheet(label_style)
        title_label.setFixedWidth(80)
        title_row.addWidget(title_label)
        self._title_input = QLineEdit()
        self._title_input.setText(self._config.get("title", default_title))
        self._title_input.setStyleSheet(input_style)
        title_row.addWidget(self._title_input)
        template_layout.addLayout(title_row)

        # Message field
        msg_row = QHBoxLayout()
        msg_label = QLabel(S.tab_notification.label_message if hasattr(S, 'tab_notification') else "Message:")
        msg_label.setStyleSheet(label_style)
        msg_label.setFixedWidth(80)
        msg_row.addWidget(msg_label)
        self._message_input = QLineEdit()
        self._message_input.setText(self._config.get("message", default_message))
        self._message_input.setStyleSheet(input_style)
        msg_row.addWidget(self._message_input)
        template_layout.addLayout(msg_row)

        # Color picker row
        color_row = QHBoxLayout()
        color_label = QLabel(
            S.tab_notification.label_color if hasattr(S, 'tab_notification') else "Color:"
        )
        color_label.setStyleSheet(label_style)
        color_label.setFixedWidth(80)
        color_row.addWidget(color_label)

        self._color_value = self._config.get("color", "#1e8a3e")
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(32, 28)
        self._color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self._color_btn)

        self._color_hex_label = QLabel(self._color_value)
        self._color_hex_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px; font-weight: normal;")
        color_row.addWidget(self._color_hex_label)
        color_row.addStretch()
        template_layout.addLayout(color_row)

        self._template_group = template_group
        layout.addWidget(template_group)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(S.tab_notification.btn_cancel if hasattr(S, 'tab_notification') else "Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 11px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton(S.tab_notification.btn_save if hasattr(S, 'tab_notification') else "Save")
        save_btn.setFixedHeight(30)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary}dd;
            }}
        """)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

        # Initial state
        self._on_enable_toggled(self._enable_cb.isChecked())

    def _on_enable_toggled(self, checked: bool):
        self._template_group.setEnabled(checked)

    def _update_color_btn(self):
        self._color_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._color_value};
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border: 1px solid rgba(255,255,255,0.6);
            }}
        """)

    def _pick_color(self):
        color = QColorDialog.getColor(
            QColor(self._color_value), self,
            S.tab_notification.color_picker_title if hasattr(S, 'tab_notification') else "Notification Color",
        )
        if color.isValid():
            self._color_value = color.name()
            self._update_color_btn()
            self._color_hex_label.setText(self._color_value)

    def _on_save(self):
        self._result_config = {
            "enabled": self._enable_cb.isChecked(),
            "title": self._title_input.text(),
            "message": self._message_input.text(),
            "color": self._color_value,
        }
        self.accept()

    def get_config(self) -> Optional[Dict[str, Any]]:
        """Returns the config dict if saved, or None if cancelled."""
        return self._result_config
