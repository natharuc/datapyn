"""Per-tab notification configuration dialog."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from typing import Optional, Dict, Any

from src.design_system.tokens import get_colors
from src.language import S


DEFAULT_RULE_COLOR = "#d64545"

RULE_OPERATORS = (
    ("equals", "operator_equals"),
    ("not_equals", "operator_not_equals"),
    ("contains", "operator_contains"),
    ("not_contains", "operator_not_contains"),
    ("greater_than", "operator_greater_than"),
    ("less_than", "operator_less_than"),
    ("is_empty", "operator_is_empty"),
    ("is_not_empty", "operator_is_not_empty"),
)

RULE_ACTIONS = (
    ("suppress", "action_suppress"),
    ("set_color", "action_set_color"),
)


class TabNotificationDialog(QDialog):
    """Dialog for configuring per-tab notification templates and rules."""

    def __init__(self, current_config: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._config = current_config or {}
        self._result_config: Optional[Dict[str, Any]] = None
        self._rule_rows = []
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        from src.design_system.frameless_dialog import install_frameless_shell

        title = S.tab_notification.dialog_title if hasattr(S, "tab_notification") else "Tab Notification"
        self.setWindowTitle(title)
        self.setMaximumWidth(1040)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: transparent;
            }}
        """)

        layout = install_frameless_shell(
            self,
            title,
            min_width=860,
            content_margins=(20, 16, 20, 20),
            content_spacing=16,
        )

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
            QLineEdit, QComboBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border-color: {colors.interactive_primary};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
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
        label_style = f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;"
        header_style = f"color: {colors.text_tertiary}; font-size: 10px; font-weight: bold;"
        hint_style = f"""
            QLabel {{
                background-color: {colors.bg_elevated};
                color: {colors.text_secondary};
                font-size: 11px;
                padding: 8px 8px 8px 12px;
                border-left: 3px solid {colors.interactive_primary};
                border-radius: 4px;
                font-weight: normal;
            }}
        """
        button_style = f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 11px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """

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

        template_group = QGroupBox(
            S.tab_notification.section_template if hasattr(S, 'tab_notification') else "MESSAGE TEMPLATE"
        )
        template_group.setStyleSheet(group_style)
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(10)

        hint_label = QLabel(
            S.tab_notification.variables_hint if hasattr(S, 'tab_notification')
            else "Variables: {{rows}}, {{blocks}}, {{tab_name}}, {{block_name}}, {{connection}}, {{database}}, {{type}}."
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(hint_style)
        template_layout.addWidget(hint_label)

        default_title = self._config.get(
            "title",
            S.tab_notification.default_title if hasattr(S, 'tab_notification') else "{{tab_name}}",
        )
        default_message = self._config.get(
            "message",
            S.tab_notification.default_message if hasattr(S, 'tab_notification') else "{{rows}} rows - {{result[0][0]}}",
        )

        title_row = QHBoxLayout()
        title_label = QLabel(S.tab_notification.label_title if hasattr(S, 'tab_notification') else "Title:")
        title_label.setStyleSheet(label_style)
        title_label.setFixedWidth(80)
        title_row.addWidget(title_label)
        self._title_input = QLineEdit()
        self._title_input.setText(default_title)
        self._title_input.setStyleSheet(input_style)
        title_row.addWidget(self._title_input)
        template_layout.addLayout(title_row)

        msg_row = QHBoxLayout()
        msg_label = QLabel(S.tab_notification.label_message if hasattr(S, 'tab_notification') else "Message:")
        msg_label.setStyleSheet(label_style)
        msg_label.setFixedWidth(80)
        msg_row.addWidget(msg_label)
        self._message_input = QLineEdit()
        self._message_input.setText(default_message)
        self._message_input.setStyleSheet(input_style)
        msg_row.addWidget(self._message_input)
        template_layout.addLayout(msg_row)

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

        rules_group = QGroupBox(
            S.tab_notification.section_rules if hasattr(S, 'tab_notification') else "RULES"
        )
        rules_group.setStyleSheet(group_style)
        rules_layout = QVBoxLayout(rules_group)
        rules_layout.setSpacing(10)

        rules_hint = QLabel(
            S.tab_notification.rules_hint if hasattr(S, 'tab_notification') else "Rules are evaluated in order."
        )
        rules_hint.setWordWrap(True)
        rules_hint.setStyleSheet(hint_style)
        rules_layout.addWidget(rules_hint)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        headers = [
            (S.tab_notification.rules_header_enabled, 0, 42),
            (S.tab_notification.rules_header_source, 2, 0),
            (S.tab_notification.rules_header_operator, 1, 0),
            (S.tab_notification.rules_header_compare, 2, 0),
            (S.tab_notification.rules_header_action, 1, 0),
            (S.tab_notification.rules_header_action_value, 1, 0),
            ("", 0, 76),
        ]
        for text, stretch, width in headers:
            header_label = QLabel(text)
            header_label.setStyleSheet(header_style)
            if width:
                header_label.setFixedWidth(width)
                header_row.addWidget(header_label)
            else:
                header_row.addWidget(header_label, stretch)
        rules_layout.addLayout(header_row)

        rules_scroll = QScrollArea()
        rules_scroll.setWidgetResizable(True)
        rules_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rules_scroll.setMinimumHeight(180)
        rules_scroll.setMaximumHeight(260)
        rules_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        rules_container_widget = QWidget()
        rules_scroll.setWidget(rules_container_widget)

        self._rules_container = QVBoxLayout(rules_container_widget)
        self._rules_container.setContentsMargins(0, 0, 0, 0)
        self._rules_container.setSpacing(8)
        self._rules_container.addStretch()
        rules_layout.addWidget(rules_scroll)

        add_rule_btn = QPushButton(S.tab_notification.btn_add_rule if hasattr(S, 'tab_notification') else "Add rule")
        add_rule_btn.setStyleSheet(button_style)
        add_rule_btn.clicked.connect(self._add_rule_row)
        rules_layout.addWidget(add_rule_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._rules_group = rules_group
        layout.addWidget(rules_group)

        for rule in self._config.get("rules", []):
            self._add_rule_row(rule)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(S.tab_notification.btn_cancel if hasattr(S, 'tab_notification') else "Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(button_style)
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
        self._on_enable_toggled(self._enable_cb.isChecked())

    def _on_enable_toggled(self, checked: bool):
        self._template_group.setEnabled(checked)
        self._rules_group.setEnabled(checked)

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
        if not color.isValid():
            return

        self._color_value = color.name()
        self._update_color_btn()
        self._color_hex_label.setText(self._color_value)

    def _update_rule_color_button(self, row: Dict[str, Any]):
        row["action_color_btn"].setStyleSheet(f"""
            QPushButton {{
                background-color: {row['action_value']};
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border: 1px solid rgba(255,255,255,0.6);
            }}
        """)
        row["action_color_label"].setText(row["action_value"])

    def _pick_rule_color(self, row: Dict[str, Any]):
        color = QColorDialog.getColor(
            QColor(row["action_value"]),
            self,
            S.tab_notification.rule_color_picker_title,
        )
        if not color.isValid():
            return

        row["action_value"] = color.name()
        self._update_rule_color_button(row)

    def _update_rule_value_enabled(self, row: Dict[str, Any]):
        operator = row["operator"].currentData()
        needs_value = operator not in {"is_empty", "is_not_empty"}
        row["value"].setEnabled(needs_value)
        if not needs_value:
            row["value"].clear()

    def _update_rule_action_controls(self, row: Dict[str, Any]):
        is_color_action = row["action"].currentData() == "set_color"
        row["action_color_btn"].setEnabled(is_color_action)
        row["action_color_label"].setEnabled(is_color_action)
        if is_color_action:
            self._update_rule_color_button(row)
        else:
            row["action_color_label"].setText("-")

    def _add_rule_row(self, rule: Optional[Dict[str, Any]] = None):
        colors = get_colors()
        input_style = f"""
            QLineEdit, QComboBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }}
        """
        remove_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                color: {colors.text_primary};
                border-color: {colors.interactive_primary};
            }}
        """

        normalized_rule = {
            "enabled": True,
            "left": "",
            "operator": "equals",
            "value": "",
            "action": "suppress",
            "action_value": DEFAULT_RULE_COLOR,
        }
        if isinstance(rule, dict):
            normalized_rule.update(rule)

        row_widget = QWidget(self)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        enabled_cb = QCheckBox()
        enabled_cb.setChecked(bool(normalized_rule.get("enabled", True)))
        enabled_cb.setFixedWidth(42)
        row_layout.addWidget(enabled_cb)

        left_input = QLineEdit(str(normalized_rule.get("left", "")))
        left_input.setPlaceholderText(S.tab_notification.rule_left_placeholder)
        left_input.setStyleSheet(input_style)
        row_layout.addWidget(left_input, 2)

        operator_combo = QComboBox()
        operator_combo.setStyleSheet(input_style)
        for operator_value, label_key in RULE_OPERATORS:
            operator_combo.addItem(getattr(S.tab_notification, label_key), operator_value)
        operator_index = max(operator_combo.findData(str(normalized_rule.get("operator", "equals"))), 0)
        operator_combo.setCurrentIndex(operator_index)
        row_layout.addWidget(operator_combo, 1)

        value_input = QLineEdit(str(normalized_rule.get("value", "")))
        value_input.setPlaceholderText(S.tab_notification.rule_value_placeholder)
        value_input.setStyleSheet(input_style)
        row_layout.addWidget(value_input, 2)

        action_combo = QComboBox()
        action_combo.setStyleSheet(input_style)
        for action_value, label_key in RULE_ACTIONS:
            action_combo.addItem(getattr(S.tab_notification, label_key), action_value)
        action_index = max(action_combo.findData(str(normalized_rule.get("action", "suppress"))), 0)
        action_combo.setCurrentIndex(action_index)
        row_layout.addWidget(action_combo, 1)

        action_value_widget = QWidget()
        action_value_layout = QHBoxLayout(action_value_widget)
        action_value_layout.setContentsMargins(0, 0, 0, 0)
        action_value_layout.setSpacing(6)
        action_color_btn = QPushButton()
        action_color_btn.setFixedSize(26, 24)
        action_color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        action_color_label = QLabel(str(normalized_rule.get("action_value", DEFAULT_RULE_COLOR)))
        action_color_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-weight: normal;")
        action_value_layout.addWidget(action_color_btn)
        action_value_layout.addWidget(action_color_label)
        action_value_layout.addStretch()
        row_layout.addWidget(action_value_widget, 1)

        remove_btn = QPushButton(S.tab_notification.btn_remove_rule)
        remove_btn.setFixedWidth(76)
        remove_btn.setStyleSheet(remove_style)
        remove_btn.clicked.connect(lambda _checked=False, widget=row_widget: self._remove_rule_row(widget))
        row_layout.addWidget(remove_btn)

        row = {
            "widget": row_widget,
            "enabled": enabled_cb,
            "left": left_input,
            "operator": operator_combo,
            "value": value_input,
            "action": action_combo,
            "action_value": str(normalized_rule.get("action_value", DEFAULT_RULE_COLOR)),
            "action_color_btn": action_color_btn,
            "action_color_label": action_color_label,
        }

        action_color_btn.clicked.connect(lambda _checked=False, current_row=row: self._pick_rule_color(current_row))
        operator_combo.currentIndexChanged.connect(lambda _index, current_row=row: self._update_rule_value_enabled(current_row))
        action_combo.currentIndexChanged.connect(lambda _index, current_row=row: self._update_rule_action_controls(current_row))

        self._rule_rows.append(row)
        self._rules_container.insertWidget(max(self._rules_container.count() - 1, 0), row_widget)
        self._update_rule_value_enabled(row)
        self._update_rule_action_controls(row)

    def _remove_rule_row(self, row_widget: QWidget):
        for index, row in enumerate(list(self._rule_rows)):
            if row["widget"] is not row_widget:
                continue
            self._rule_rows.pop(index)
            self._rules_container.removeWidget(row_widget)
            row_widget.deleteLater()
            break

    def _collect_rules(self) -> list[Dict[str, Any]]:
        rules = []
        for row in self._rule_rows:
            left_value = row["left"].text().strip()
            if not left_value:
                continue

            rule = {
                "enabled": row["enabled"].isChecked(),
                "left": left_value,
                "operator": row["operator"].currentData(),
                "value": row["value"].text(),
                "action": row["action"].currentData(),
            }
            if rule["action"] == "set_color":
                rule["action_value"] = row["action_value"]
            rules.append(rule)
        return rules

    def _on_save(self):
        self._result_config = {
            "enabled": self._enable_cb.isChecked(),
            "title": self._title_input.text(),
            "message": self._message_input.text(),
            "color": self._color_value,
            "rules": self._collect_rules(),
        }
        self.accept()

    def get_config(self) -> Optional[Dict[str, Any]]:
        """Returns the config dict if saved, or None if cancelled."""
        return self._result_config
