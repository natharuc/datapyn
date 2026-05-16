"""Fixed side panel for SQL block custom parameters."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QPoint, QDate, QDateTime, QTime
from PyQt6.QtGui import QAction, QColor, QDrag, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from src.design_system.tokens import get_colors
from src.language import S
from src.utils.sql_parameter_service import (
    normalize_parameter_definition,
    resolve_parameter_default_value,
    SQL_PARAMETER_TYPES,
)


_TYPE_LABELS = {
    "text": "type_text",
    "integer": "type_integer",
    "decimal": "type_decimal",
    "boolean": "type_boolean",
    "date": "type_date",
    "datetime": "type_datetime",
    "uuid": "type_uuid",
}

_INPUT_KIND_LABELS = {
    "value": "input_value",
    "choice": "input_choice",
    "multi_choice": "input_multi_choice",
}

_INTEGER_EMPTY_VALUE = -2147483647
_DECIMAL_EMPTY_VALUE = -1000000000000.0
_EMPTY_DATE = QDate(100, 1, 1)
_EMPTY_DATETIME = QDateTime(_EMPTY_DATE, QTime(0, 0))
_DEFAULT_PRESET_LABELS = {
    "null": "default_option_null",
    "empty": "default_option_empty",
    "today": "default_option_today",
    "now": "default_option_now",
}
_DEFAULT_PLACEHOLDER_LABELS = {
    "text": "placeholder_default_text",
    "integer": "placeholder_default_integer",
    "decimal": "placeholder_default_decimal",
    "boolean": "placeholder_default_boolean",
    "date": "placeholder_default_date",
    "datetime": "placeholder_default_datetime",
    "uuid": "placeholder_default_uuid",
}


def _default_presets_for_sql_type(sql_type: str) -> tuple[str, ...]:
    if sql_type == "date":
        return ("null", "empty", "today")
    if sql_type == "datetime":
        return ("null", "empty", "now")
    if sql_type in {"text", "uuid"}:
        return ("null", "empty")
    return ("null",)


def _default_placeholder_for(sql_type: str, input_kind: str) -> str:
    if input_kind == "multi_choice":
        return S.sql_parameters.placeholder_multi_value
    return getattr(S.sql_parameters, _DEFAULT_PLACEHOLDER_LABELS.get(sql_type, "placeholder_default_text"))


def _normalize_default_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _coerce_scalar_value_for_type(value: Any, sql_type: str) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    if value in (None, ""):
        return ""

    try:
        if sql_type == "integer":
            return int(str(value).strip())
        if sql_type == "decimal":
            return float(str(value).strip())
        if sql_type == "boolean":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in {"1", "true", "yes", "y", "sim", "s"}:
                return True
            if lowered in {"0", "false", "no", "n", "nao", "não"}:
                return False
            return ""
        if sql_type == "date":
            if isinstance(value, date) and not isinstance(value, datetime):
                return value.isoformat()
            return date.fromisoformat(str(value).strip()).isoformat()
        if sql_type == "datetime":
            if isinstance(value, datetime):
                return value.replace(microsecond=0).isoformat()
            return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return ""

    return str(value).strip()


def _sanitize_parameter_value(parameter: dict[str, Any], value: Any) -> Any:
    input_kind = str(parameter.get("input_kind") or "value")
    options = [str(item) for item in parameter.get("options") or []]
    option_values = {str(item) for item in options}

    if input_kind == "multi_choice":
        if isinstance(value, (list, tuple, set)):
            values = [str(item).strip() for item in value if str(item).strip()]
        else:
            values = [item.strip() for item in str(value or "").split(",") if item.strip()]
        if option_values:
            values = [item for item in values if item in option_values]
        return values

    if input_kind == "choice":
        choice_value = "" if value in (None, "") else str(value).strip()
        if option_values and choice_value and choice_value not in option_values:
            return ""
        return choice_value

    return _coerce_scalar_value_for_type(value, str(parameter.get("sql_type") or "text"))


def _sanitize_parameter_default_value(parameter: dict[str, Any], default_value: Any) -> str:
    text_value = _normalize_default_text(default_value)
    if not text_value:
        return ""

    lowered = text_value.lower()
    if lowered in _default_presets_for_sql_type(str(parameter.get("sql_type") or "text")):
        return lowered

    sanitized = _sanitize_parameter_value(parameter, text_value)
    if sanitized in (None, ""):
        return ""
    if isinstance(sanitized, list):
        return ", ".join(str(item) for item in sanitized if str(item).strip())
    if isinstance(sanitized, bool):
        return "true" if sanitized else "false"
    return str(sanitized)


class MultiSelectMenuButton(QToolButton):
    """Compact multi-select input rendered as a popup menu."""

    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._options: list[str] = []
        self._selected: list[str] = []
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._update_text()

    def set_options(self, options: list[str]):
        normalized_options = []
        for option in options or []:
            text = str(option).strip()
            if text and text not in normalized_options:
                normalized_options.append(text)
        self._options = normalized_options
        self._menu.clear()
        for option in self._options:
            action = QAction(option, self)
            action.setCheckable(True)
            action.setChecked(option in self._selected)
            action.toggled.connect(self._on_action_toggled)
            self._menu.addAction(action)
        self._sync_selected()
        self.setEnabled(bool(self._options))
        self._update_text()

    def set_value(self, value: Any):
        if isinstance(value, (list, tuple, set)):
            selected = [str(item).strip() for item in value if str(item).strip()]
        elif str(value or "").strip():
            selected = [item.strip() for item in str(value).split(",") if item.strip()]
        else:
            selected = []
        for item in selected:
            if item not in self._options:
                self._options.append(item)
        self._selected = selected
        self.set_options(self._options)

    def value(self) -> list[str]:
        return list(self._selected)

    def _on_action_toggled(self, _checked: bool):
        self._sync_selected()
        self._update_text()
        self.selection_changed.emit(self.value())

    def _sync_selected(self):
        self._selected = [action.text() for action in self._menu.actions() if action.isChecked()]

    def _update_text(self):
        if not self._options:
            self.setText(S.sql_parameters.placeholder_configure_options)
            return
        if not self._selected:
            self.setText(S.sql_parameters.placeholder_select_multiple)
            return
        if len(self._selected) <= 2:
            self.setText(", ".join(self._selected))
            return
        self.setText(S.sql_parameters.selected_count.format(count=len(self._selected)))


class SqlParameterSettingsDialog(QDialog):
    """Advanced parameter settings kept out of the compact row UI."""

    def __init__(self, parameter: dict[str, Any], parent=None):
        super().__init__(parent)
        self._parameter = normalize_parameter_definition(parameter)
        self._loading_parameter = False
        self._updating_default_controls = False
        self._setup_ui()
        self._load_parameter()

    def _setup_ui(self):
        self.setWindowTitle(S.sql_parameters.settings_title)
        flags = self.windowFlags() | Qt.WindowType.CustomizeWindowHint
        flags |= Qt.WindowType.WindowTitleHint
        flags |= Qt.WindowType.WindowSystemMenuHint
        flags |= Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowMinimizeButtonHint
        flags &= ~Qt.WindowType.WindowMaximizeButtonHint
        flags &= ~Qt.WindowType.WindowMinMaxButtonsHint
        self.setWindowFlags(flags)
        self.setModal(True)
        self.resize(360, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.token_value = QLabel()
        root.addWidget(self._labeled(S.sql_parameters.label_token, self.token_value))

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(S.sql_parameters.placeholder_label)
        root.addWidget(self._labeled(S.sql_parameters.label_label, self.label_edit))

        self.type_combo = QComboBox()
        for type_key in SQL_PARAMETER_TYPES:
            self.type_combo.addItem(getattr(S.sql_parameters, _TYPE_LABELS[type_key]), type_key)
        self.type_combo.currentIndexChanged.connect(self._on_parameter_controls_changed)
        root.addWidget(self._labeled(S.sql_parameters.label_type, self.type_combo))

        self.input_combo = QComboBox()
        for input_key in ("value", "choice", "multi_choice"):
            self.input_combo.addItem(getattr(S.sql_parameters, _INPUT_KIND_LABELS[input_key]), input_key)
        self.input_combo.currentIndexChanged.connect(self._on_parameter_controls_changed)
        root.addWidget(self._labeled(S.sql_parameters.label_input, self.input_combo))

        self.options_edit = QLineEdit()
        self.options_edit.setPlaceholderText(S.sql_parameters.placeholder_options)
        self.options_edit.setToolTip(S.sql_parameters.tooltip_options)
        self.options_edit.textChanged.connect(self._update_default_controls)
        self.options_container = self._labeled(S.sql_parameters.label_options, self.options_edit)
        root.addWidget(self.options_container)

        self.default_value_edit = QLineEdit()
        self.default_value_edit.setToolTip(S.sql_parameters.tooltip_default_value)
        self.default_value_edit.textChanged.connect(self._on_default_text_changed)

        self.default_null_check = QCheckBox(S.sql_parameters.default_option_null)
        self.default_empty_check = QCheckBox(S.sql_parameters.default_option_empty)
        self.default_today_check = QCheckBox(S.sql_parameters.default_option_today)
        self.default_now_check = QCheckBox(S.sql_parameters.default_option_now)
        self._default_option_checks = {
            "null": self.default_null_check,
            "empty": self.default_empty_check,
            "today": self.default_today_check,
            "now": self.default_now_check,
        }
        for preset_name, checkbox in self._default_option_checks.items():
            checkbox.toggled.connect(lambda checked, preset=preset_name: self._on_default_preset_toggled(preset, checked))

        self.default_options_widget = QWidget(self)
        default_options_layout = QHBoxLayout(self.default_options_widget)
        default_options_layout.setContentsMargins(0, 0, 0, 0)
        default_options_layout.setSpacing(10)
        default_options_layout.addWidget(self.default_null_check)
        default_options_layout.addWidget(self.default_empty_check)
        default_options_layout.addWidget(self.default_today_check)
        default_options_layout.addWidget(self.default_now_check)
        default_options_layout.addStretch(1)

        self.default_value_container = QWidget(self)
        default_value_layout = QVBoxLayout(self.default_value_container)
        default_value_layout.setContentsMargins(0, 0, 0, 0)
        default_value_layout.setSpacing(6)
        default_value_layout.addWidget(self.default_value_edit)
        default_value_layout.addWidget(self.default_options_widget)
        root.addWidget(self._labeled(S.sql_parameters.label_default_value, self.default_value_container))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _labeled(self, label: str, widget: QWidget) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title = QLabel(label)
        layout.addWidget(title)
        layout.addWidget(widget)
        return container

    def _load_parameter(self):
        self._loading_parameter = True
        self.token_value.setText(f"@{self._parameter['name']}")
        self.label_edit.setText(self._parameter.get("label", ""))
        self._set_combo_value(self.type_combo, self._parameter.get("sql_type", "text"))
        self._set_combo_value(self.input_combo, self._parameter.get("input_kind", "value"))
        self.options_edit.setText(", ".join(self._parameter.get("options") or []))
        self._loading_parameter = False
        self._update_options_visibility()
        self._update_default_controls(self._parameter.get("default_value", ""))

    def _set_combo_value(self, combo: QComboBox, value: str):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_options_visibility(self):
        self.options_container.setVisible(self.input_combo.currentData() in {"choice", "multi_choice"})

    def _draft_parameter(self) -> dict[str, Any]:
        return {
            **self._parameter,
            "sql_type": self.type_combo.currentData() or "text",
            "input_kind": self.input_combo.currentData() or "value",
            "options": [item.strip() for item in self.options_edit.text().split(",") if item.strip()],
            "multi_select": (self.input_combo.currentData() or "value") == "multi_choice",
        }

    def _current_default_value(self) -> str:
        for preset_name, checkbox in self._default_option_checks.items():
            if checkbox.isChecked():
                return preset_name
        return self.default_value_edit.text().strip()

    def _on_parameter_controls_changed(self):
        self._update_options_visibility()
        self._update_default_controls()

    def _update_default_controls(self, default_value: Any = None):
        draft_parameter = self._draft_parameter()
        current_default = self._current_default_value() if default_value is None else default_value
        sanitized_default = _sanitize_parameter_default_value(draft_parameter, current_default)
        self.default_value_edit.setPlaceholderText(
            _default_placeholder_for(draft_parameter["sql_type"], draft_parameter["input_kind"])
        )

        allowed_presets = set(_default_presets_for_sql_type(draft_parameter["sql_type"]))
        self._updating_default_controls = True
        for preset_name, checkbox in self._default_option_checks.items():
            checkbox.setVisible(preset_name in allowed_presets)
            if preset_name not in allowed_presets:
                checkbox.setChecked(False)
        self._apply_default_value_to_controls(sanitized_default)
        self._updating_default_controls = False

    def _apply_default_value_to_controls(self, default_value: Any):
        text_value = _normalize_default_text(default_value)
        lowered = text_value.lower()
        for checkbox in self._default_option_checks.values():
            checkbox.setChecked(False)

        if lowered in self._default_option_checks and self._default_option_checks[lowered].isVisible():
            self._default_option_checks[lowered].setChecked(True)
            self.default_value_edit.clear()
            return

        self.default_value_edit.setText(text_value)

    def _on_default_preset_toggled(self, preset_name: str, checked: bool):
        if self._updating_default_controls or not checked:
            return

        self._updating_default_controls = True
        for other_name, checkbox in self._default_option_checks.items():
            if other_name != preset_name:
                checkbox.setChecked(False)
        self.default_value_edit.clear()
        self._updating_default_controls = False

    def _on_default_text_changed(self, text: str):
        if self._updating_default_controls or not text.strip():
            return

        self._updating_default_controls = True
        for checkbox in self._default_option_checks.values():
            checkbox.setChecked(False)
        self._updating_default_controls = False

    def parameter(self) -> dict[str, Any]:
        parameter = dict(self._parameter)
        parameter.update(
            {
                "label": self.label_edit.text().strip(),
                "sql_type": self.type_combo.currentData() or "text",
                "input_kind": self.input_combo.currentData() or "value",
                "options": [item.strip() for item in self.options_edit.text().split(",") if item.strip()],
                "multi_select": (self.input_combo.currentData() or "value") == "multi_choice",
                "type_source": "manual",
            }
        )
        parameter["default_value"] = _sanitize_parameter_default_value(parameter, self._current_default_value())
        return normalize_parameter_definition(parameter)


class SqlParameterRow(QFrame):
    """Compact row for one SQL parameter with a dynamic input widget."""

    changed = pyqtSignal(dict)
    drag_started = pyqtSignal(str)

    def __init__(self, parameter: dict[str, Any], parent=None):
        super().__init__(parent)
        self._parameter = normalize_parameter_definition(parameter)
        self._input_widget: QWidget | None = None
        self._loading = False
        self._using_default_display = False
        self._setup_ui()
        self._apply_parameter(self._parameter)

    @property
    def parameter_id(self) -> str:
        return self._parameter["id"]

    @property
    def input_widget(self) -> QWidget | None:
        return self._input_widget

    def _setup_ui(self):
        colors = get_colors()
        self.setObjectName("SqlParameterRow")
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setToolTip(S.sql_parameters.tooltip_configure)
        self.setStyleSheet(f"""
            QFrame#SqlParameterRow {{
                background: {colors.bg_tertiary};
                border: 1px solid {colors.border_default};
                border-radius: 8px;
            }}
            QFrame#SqlParameterRow:hover {{
                border-color: {colors.interactive_primary};
            }}
            QLabel {{
                color: {colors.text_secondary};
                font-size: 10px;
                background: transparent;
            }}
            QLabel#SqlParameterTitle {{
                color: {colors.text_primary};
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#SqlParameterToken {{
                color: {colors.text_tertiary};
                font-size: 9px;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QToolButton {{
                background: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 10px;
                min-height: 24px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QToolButton:focus {{
                border-color: {colors.interactive_primary};
            }}
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {colors.bg_elevated};
            }}
            QPushButton#SqlParameterRequiredToggle {{
                background: transparent;
                border: none;
                border-radius: 0;
                padding: 0;
                font-size: 10px;
                font-weight: 600;
                text-align: left;
            }}
            QPushButton#SqlParameterRequiredToggle:hover {{
                background: transparent;
            }}
            QCheckBox {{
                background: transparent;
                padding: 0;
            }}
            QCheckBox::indicator {{
                width: 13px;
                height: 13px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.drag_btn = QPushButton()
        self.drag_btn.setFixedSize(18, 18)
        self.drag_btn.setToolTip(S.sql_parameters.tooltip_drag)
        self.drag_btn.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_btn.setIcon(qta.icon("mdi.drag-vertical", color=colors.text_tertiary))
        self.drag_btn.pressed.connect(self._start_drag)
        header.addWidget(self.drag_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.configure_btn = QPushButton()
        self.configure_btn.setFixedSize(18, 18)
        self.configure_btn.setToolTip(S.sql_parameters.tooltip_configure)
        self.configure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.configure_btn.setIcon(qta.icon("mdi.cog-outline", color=colors.text_tertiary))
        self.configure_btn.clicked.connect(self._open_settings_dialog)

        self.required_toggle = QPushButton()
        self.required_toggle.setObjectName("SqlParameterRequiredToggle")
        self.required_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.required_toggle.setToolTip(S.sql_parameters.tooltip_toggle_required)
        self.required_toggle.clicked.connect(self._toggle_required)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(1)

        self.display_label = QLabel()
        self.display_label.setObjectName("SqlParameterTitle")
        title_stack.addWidget(self.display_label)

        self.token_label = QLabel()
        self.token_label.setObjectName("SqlParameterToken")
        title_stack.addWidget(self.token_label)

        header.addLayout(title_stack, 1)
        header.addWidget(self.required_toggle, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.configure_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.input_container = QWidget(self)
        self.input_layout = QVBoxLayout(self.input_container)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(0)
        root.addWidget(self.input_container)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_settings_dialog()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        configure_action = menu.addAction(S.sql_parameters.action_configure)
        selected_action = menu.exec(event.globalPos())
        if selected_action == configure_action:
            self._open_settings_dialog()

    def _apply_parameter(self, parameter: dict[str, Any], emit_change: bool = False):
        self._loading = True
        self._parameter = normalize_parameter_definition(parameter)
        self._refresh_header()
        self._rebuild_input_widget()
        self._loading = False
        if emit_change:
            self.changed.emit(self.to_parameter())

    def _refresh_header(self):
        colors = get_colors()
        label_text = str(self._parameter.get("label") or "").strip()
        self.display_label.setText(label_text)
        self.display_label.setVisible(bool(label_text))
        self.token_label.setText(f"@{self._parameter['name']}")
        is_required = bool(self._parameter.get("required", True))
        self.required_toggle.setText(
            S.sql_parameters.required_inline if is_required else S.sql_parameters.optional_inline
        )
        self.required_toggle.setStyleSheet(
            f"color: {colors.warning if is_required else colors.text_tertiary};"
        )

    def _rebuild_input_widget(self):
        while self.input_layout.count():
            item = self.input_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._input_widget = self._create_input_widget(self._parameter)
        self._connect_input_widget(self._input_widget)
        self.input_layout.addWidget(self._input_widget)

    def _create_input_widget(self, parameter: dict[str, Any]) -> QWidget:
        input_kind = parameter.get("input_kind", "value")
        options = parameter.get("options") or []

        if input_kind == "choice" and options:
            widget = QComboBox(self)
            widget.addItem(S.sql_parameters.placeholder_select_option, "")
            for option in options:
                widget.addItem(str(option), str(option))
            self._set_widget_value(widget, parameter)
            return widget

        if input_kind == "multi_choice" and options:
            widget = MultiSelectMenuButton(self)
            widget.set_options([str(option) for option in options])
            self._set_widget_value(widget, parameter)
            return widget

        sql_type = parameter.get("sql_type", "text")
        if sql_type == "integer":
            widget = QSpinBox(self)
            widget.setRange(_INTEGER_EMPTY_VALUE, 2147483647)
            widget.setSpecialValueText("")
            widget.setValue(_INTEGER_EMPTY_VALUE)
        elif sql_type == "decimal":
            widget = QDoubleSpinBox(self)
            widget.setDecimals(6)
            widget.setRange(_DECIMAL_EMPTY_VALUE, 1000000000000.0)
            widget.setSpecialValueText("")
            widget.setValue(_DECIMAL_EMPTY_VALUE)
        elif sql_type == "boolean":
            widget = QComboBox(self)
            widget.addItem(S.sql_parameters.placeholder_select_option, "")
            widget.addItem(S.sql_parameters.boolean_true, True)
            widget.addItem(S.sql_parameters.boolean_false, False)
        elif sql_type == "date":
            widget = QDateEdit(self)
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setMinimumDate(_EMPTY_DATE)
            widget.setSpecialValueText("")
            widget.setDate(_EMPTY_DATE)
        elif sql_type == "datetime":
            widget = QDateTimeEdit(self)
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            widget.setMinimumDateTime(_EMPTY_DATETIME)
            widget.setSpecialValueText("")
            widget.setDateTime(_EMPTY_DATETIME)
        else:
            widget = QLineEdit(self)
            widget.setPlaceholderText(
                S.sql_parameters.placeholder_configure_options
                if input_kind in {"choice", "multi_choice"}
                else S.sql_parameters.placeholder_value
            )

        if isinstance(widget, QAbstractSpinBox):
            widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self._set_widget_value(widget, parameter)
        return widget

    def _connect_input_widget(self, widget: QWidget):
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._emit_input_changed)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self._emit_input_changed)
        elif isinstance(widget, QDateEdit):
            widget.dateChanged.connect(self._emit_input_changed)
        elif isinstance(widget, QDateTimeEdit):
            widget.dateTimeChanged.connect(self._emit_input_changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self._emit_input_changed)
        elif isinstance(widget, MultiSelectMenuButton):
            widget.selection_changed.connect(self._emit_input_changed)

    def _set_widget_value(self, widget: QWidget, parameter: dict[str, Any]):
        value = parameter.get("value", "")
        if isinstance(value, list) and parameter.get("input_kind") != "multi_choice":
            value = value[0] if value else ""

        display_value = value
        if value in (None, "") or (isinstance(value, list) and not value):
            display_value = resolve_parameter_default_value(parameter, for_display=True)
            self._using_default_display = display_value not in (None, "") and not (
                isinstance(display_value, list) and not display_value
            )
        else:
            self._using_default_display = False

        if isinstance(widget, QLineEdit):
            widget.setText(str(display_value or ""))
            return

        if isinstance(widget, QSpinBox):
            safe_value = _coerce_scalar_value_for_type(display_value, "integer")
            widget.setValue(_INTEGER_EMPTY_VALUE if safe_value in (None, "") else int(safe_value))
            return

        if isinstance(widget, QDoubleSpinBox):
            safe_value = _coerce_scalar_value_for_type(display_value, "decimal")
            widget.setValue(_DECIMAL_EMPTY_VALUE if safe_value in (None, "") else float(safe_value))
            return

        if isinstance(widget, QComboBox):
            index = widget.findData(display_value)
            if index < 0 and display_value not in (None, ""):
                widget.addItem(str(display_value), display_value)
                index = widget.findData(display_value)
            widget.setCurrentIndex(max(index, 0))
            return

        if isinstance(widget, QDateEdit):
            if isinstance(display_value, date):
                widget.setDate(QDate(display_value.year, display_value.month, display_value.day))
                return
            qt_date = QDate.fromString(str(display_value or ""), Qt.DateFormat.ISODate)
            widget.setDate(qt_date if qt_date.isValid() else _EMPTY_DATE)
            return

        if isinstance(widget, QDateTimeEdit):
            if isinstance(display_value, datetime):
                qt_date_time = QDateTime.fromString(display_value.isoformat(), Qt.DateFormat.ISODate)
            else:
                qt_date_time = QDateTime.fromString(str(display_value or ""), Qt.DateFormat.ISODate)
            widget.setDateTime(qt_date_time if qt_date_time.isValid() else _EMPTY_DATETIME)
            return

        if isinstance(widget, MultiSelectMenuButton):
            widget.set_value(display_value)

    def _read_input_value(self) -> Any:
        widget = self._input_widget
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QSpinBox):
            return "" if widget.value() == _INTEGER_EMPTY_VALUE else int(widget.value())
        if isinstance(widget, QDoubleSpinBox):
            return "" if widget.value() == _DECIMAL_EMPTY_VALUE else float(widget.value())
        if isinstance(widget, QComboBox):
            return widget.currentData() if widget.currentData() not in (None, "") else ""
        if isinstance(widget, QDateEdit):
            return "" if widget.date() == _EMPTY_DATE else widget.date().toString(Qt.DateFormat.ISODate)
        if isinstance(widget, QDateTimeEdit):
            return "" if widget.dateTime() == _EMPTY_DATETIME else widget.dateTime().toString(Qt.DateFormat.ISODate)
        if isinstance(widget, MultiSelectMenuButton):
            return widget.value()
        return ""

    def _open_settings_dialog(self):
        current_parameter = self.to_parameter()
        dialog = SqlParameterSettingsDialog(current_parameter, self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            updated_parameter = dialog.parameter()
            updated_parameter["value"] = _sanitize_parameter_value(updated_parameter, current_parameter.get("value", ""))
            updated_parameter["default_value"] = _sanitize_parameter_default_value(
                updated_parameter,
                updated_parameter.get("default_value", ""),
            )
            self._apply_parameter(updated_parameter, emit_change=True)

    def _emit_input_changed(self, *_args):
        self._using_default_display = False
        self._emit_changed()

    def _toggle_required(self):
        if self._loading:
            return
        self._parameter["required"] = not bool(self._parameter.get("required", True))
        self._refresh_header()
        self.changed.emit(self.to_parameter())

    def _emit_changed(self, *_args):
        if self._loading:
            return
        self._parameter = self.to_parameter()
        self.changed.emit(dict(self._parameter))

    def to_parameter(self) -> dict[str, Any]:
        parameter = dict(self._parameter)
        parameter["required"] = bool(self._parameter.get("required", True))
        parameter["value"] = parameter.get("value", "") if self._using_default_display else self._read_input_value()
        return normalize_parameter_definition(parameter)

    def _start_drag(self):
        self.drag_btn.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData("application/x-sql-parameter-id", self.parameter_id.encode("utf-8"))
        drag.setMimeData(mime_data)

        pixmap = QPixmap(max(160, self.width()), max(32, self.height()))
        pixmap.fill(QColor(45, 45, 48, 220))
        painter = QPainter(pixmap)
        painter.setPen(QColor(220, 220, 220))
        painter.drawText(10, 18, self.token_label.text())
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(14, 14))
        self.drag_started.emit(self.parameter_id)
        drag.exec(Qt.DropAction.MoveAction)
        self.drag_btn.setCursor(Qt.CursorShape.OpenHandCursor)


class SqlParametersPanel(QFrame):
    """Fixed left panel shown inside SQL blocks when custom parameters exist."""

    parameters_changed = pyqtSignal(list)
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parameters: list[dict[str, Any]] = []
        self._row_widgets: dict[str, SqlParameterRow] = {}
        self._dragging_parameter_id = ""
        self._setup_ui()
        self.setAcceptDrops(True)

    def _setup_ui(self):
        colors = get_colors()
        self.setObjectName("SqlParametersPanel")
        self.setFixedWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"""
            QFrame#SqlParametersPanel {{
                background: {colors.bg_secondary};
                border-right: 1px solid {colors.border_default};
            }}
            QLabel {{
                background: transparent;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(qta.icon("mdi.variable", color=colors.info).pixmap(16, 16))
        header.addWidget(icon)
        title = QLabel(S.sql_parameters.panel_title)
        title.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: 600;")
        header.addWidget(title, 1)

        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip(S.sql_parameters.tooltip_close_panel)
        self.close_btn.setIcon(qta.icon("mdi.close", color=colors.text_tertiary))
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {colors.bg_elevated};
            }}
        """)
        self.close_btn.clicked.connect(self.close_requested.emit)
        header.addWidget(self.close_btn)
        root.addLayout(header)

        self.empty_label = QLabel(S.sql_parameters.no_parameters)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; padding: 6px 2px;")
        root.addWidget(self.empty_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.rows_container)
        root.addWidget(self.scroll, 1)

    def set_parameters(self, parameters: list[dict[str, Any]]):
        self._parameters = [normalize_parameter_definition(item, idx) for idx, item in enumerate(parameters or [])]
        self._parameters.sort(key=lambda item: int(item.get("order", 0)))
        self._rebuild_rows()

    def parameters(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._parameters]

    def _rebuild_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._row_widgets = {}
        self.empty_label.setVisible(not self._parameters)
        self.scroll.setVisible(bool(self._parameters))

        for index, parameter in enumerate(self._parameters):
            parameter = normalize_parameter_definition(parameter, index)
            parameter["order"] = index
            self._parameters[index] = parameter
            row = SqlParameterRow(parameter, self)
            row.changed.connect(self._on_row_changed)
            row.drag_started.connect(self._on_row_drag_started)
            self._row_widgets[parameter["id"]] = row
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch(1)

    def _on_row_changed(self, parameter: dict[str, Any]):
        for index, current in enumerate(self._parameters):
            if current.get("id") == parameter.get("id"):
                parameter = normalize_parameter_definition(parameter, index)
                parameter["order"] = index
                self._parameters[index] = parameter
                break
        self.parameters_changed.emit(self.parameters())

    def _on_row_drag_started(self, parameter_id: str):
        self._dragging_parameter_id = parameter_id

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-sql-parameter-id"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-sql-parameter-id"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-sql-parameter-id"):
            event.ignore()
            return
        parameter_id = event.mimeData().data("application/x-sql-parameter-id").data().decode("utf-8")
        target_index = self._index_for_drop_y(event.position().toPoint().y())
        self.move_parameter(parameter_id, target_index)
        event.acceptProposedAction()

    def _index_for_drop_y(self, y_position: int) -> int:
        for index in range(self.rows_layout.count()):
            item = self.rows_layout.itemAt(index)
            widget = item.widget()
            if not isinstance(widget, SqlParameterRow):
                continue
            if y_position < widget.geometry().center().y():
                return index
        return len(self._parameters) - 1

    def move_parameter(self, parameter_id: str, target_index: int):
        current_index = next((idx for idx, item in enumerate(self._parameters) if item.get("id") == parameter_id), -1)
        if current_index < 0:
            return
        target_index = max(0, min(target_index, len(self._parameters) - 1))
        if current_index == target_index:
            return
        item = self._parameters.pop(current_index)
        self._parameters.insert(target_index, item)
        for index, parameter in enumerate(self._parameters):
            parameter["order"] = index
        self._rebuild_rows()
        self.parameters_changed.emit(self.parameters())