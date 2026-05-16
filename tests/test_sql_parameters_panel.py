import pytest
from unittest.mock import patch
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QComboBox, QDateEdit, QDialog, QSpinBox

import src.editors.sql_parameters_panel as sql_parameters_panel_module
from src.editors.sql_parameters_panel import MultiSelectMenuButton, SqlParameterRow, SqlParameterSettingsDialog
from src.language import S


def _param(name, value="", sql_type="text", input_kind="value", options=None, label="", default_value=""):
    return {
        "id": f"sqlparam:{name.lower()}",
        "name": name,
        "label": label,
        "order": 0,
        "sql_type": sql_type,
        "input_kind": input_kind,
        "value": value,
        "default_value": default_value,
        "required": True,
        "options": options or [],
        "multi_select": input_kind == "multi_choice",
    }


class TestSqlParameterRow:
    def test_row_shows_configured_label_and_token(self, qtbot):
        row = SqlParameterRow(_param("productId", value="12", sql_type="integer", label="Product ID"))
        qtbot.addWidget(row)

        assert row.display_label.text() == "Product ID"
        assert not row.display_label.isHidden()
        assert row.token_label.text() == "@productId"
        assert row.required_toggle.text() == S.sql_parameters.required_inline

    def test_integer_value_uses_spinbox(self, qtbot):
        row = SqlParameterRow(_param("quantity", value="12", sql_type="integer"))
        qtbot.addWidget(row)

        assert isinstance(row.input_widget, QSpinBox)
        assert row.to_parameter()["value"] == 12

        row.input_widget.setValue(25)
        assert row.to_parameter()["value"] == 25

    def test_date_value_uses_date_edit(self, qtbot):
        row = SqlParameterRow(_param("invoiceDate", value="2026-05-16", sql_type="date"))
        qtbot.addWidget(row)

        assert isinstance(row.input_widget, QDateEdit)
        assert row.to_parameter()["value"] == "2026-05-16"

        row.input_widget.setDate(QDate(2026, 5, 20))
        assert row.to_parameter()["value"] == "2026-05-20"

    def test_empty_date_has_no_implicit_default(self, qtbot):
        row = SqlParameterRow(_param("invoiceDate", value="", sql_type="date"))
        qtbot.addWidget(row)

        assert isinstance(row.input_widget, QDateEdit)
        assert row.input_widget.date() != QDate.currentDate()
        assert row.to_parameter()["value"] == ""
        assert row.to_parameter()["default_value"] == ""

    def test_choice_input_uses_combobox(self, qtbot):
        row = SqlParameterRow(_param("status", value="I", input_kind="choice", options=["A", "I"]))
        qtbot.addWidget(row)

        assert isinstance(row.input_widget, QComboBox)
        assert row.input_widget.currentData() == "I"

        row.input_widget.setCurrentIndex(1)
        assert row.to_parameter()["value"] == "A"

    def test_multi_choice_uses_menu_button(self, qtbot):
        row = SqlParameterRow(
            _param("status", value=["A"], input_kind="multi_choice", options=["A", "I", "P"])
        )
        qtbot.addWidget(row)

        assert isinstance(row.input_widget, MultiSelectMenuButton)
        row.input_widget.set_value(["A", "P"])

        assert row.to_parameter()["value"] == ["A", "P"]

    def test_configuration_button_opens_settings(self, qtbot):
        with patch.object(SqlParameterRow, "_open_settings_dialog") as mock_open:
            row = SqlParameterRow(_param("status", value="A"))
            qtbot.addWidget(row)

            row.configure_btn.click()

            assert mock_open.call_count == 1

    def test_required_label_is_clickable_and_updates_parameter(self, qtbot):
        row = SqlParameterRow(_param("status", value="A", label="Status"))
        qtbot.addWidget(row)

        assert row.required_toggle.text() == S.sql_parameters.required_inline
        assert row.required_toggle.toolTip() == S.sql_parameters.tooltip_toggle_required
        assert row.display_label.text() == "Status"

        row.required_toggle.click()

        assert row.to_parameter()["required"] is False
        assert row.required_toggle.text() == S.sql_parameters.optional_inline
        assert row.display_label.text() == "Status"

    def test_row_type_change_clears_incompatible_value_and_default(self, qtbot):
        row = SqlParameterRow(_param("invoiceDate", value="2026-05-16", sql_type="date", default_value="today"))
        qtbot.addWidget(row)

        class FakeDialog:
            def __init__(self, parameter, parent=None):
                self._parameter = dict(parameter)

            def exec(self):
                return int(QDialog.DialogCode.Accepted)

            def parameter(self):
                updated = dict(self._parameter)
                updated["sql_type"] = "integer"
                updated["input_kind"] = "value"
                updated["default_value"] = "today"
                updated["type_source"] = "manual"
                return updated

        with patch.object(sql_parameters_panel_module, "SqlParameterSettingsDialog", FakeDialog):
            row._open_settings_dialog()

        assert isinstance(row.input_widget, QSpinBox)
        assert row.to_parameter()["sql_type"] == "integer"
        assert row.to_parameter()["value"] == ""
        assert row.to_parameter()["default_value"] == ""


class TestSqlParameterSettingsDialog:
    def test_settings_dialog_removes_minmax_buttons(self, qtbot):
        dialog = SqlParameterSettingsDialog(_param("status"))
        qtbot.addWidget(dialog)

        assert not bool(dialog.windowFlags() & Qt.WindowType.WindowMinMaxButtonsHint)

    def test_settings_dialog_clears_individual_minimize_and_maximize_hints(self, qtbot):
        dialog = SqlParameterSettingsDialog(_param("status"))
        qtbot.addWidget(dialog)

        assert not bool(dialog.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint)
        assert not bool(dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)

    def test_settings_dialog_keeps_close_button_when_customizing_title_bar(self, qtbot):
        dialog = SqlParameterSettingsDialog(_param("status"))
        qtbot.addWidget(dialog)

        assert bool(dialog.windowFlags() & Qt.WindowType.CustomizeWindowHint)
        assert bool(dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint)

    def test_settings_dialog_text_defaults_support_custom_and_presets(self, qtbot):
        dialog = SqlParameterSettingsDialog(_param("status", sql_type="text"))
        qtbot.addWidget(dialog)

        assert not dialog.default_null_check.isHidden()
        assert not dialog.default_empty_check.isHidden()

        dialog.default_null_check.setChecked(True)
        assert dialog.parameter()["default_value"] == "null"

        dialog.default_value_edit.setText("ativo")
        parameter = dialog.parameter()
        assert parameter["default_value"] == "ativo"
        assert dialog.default_null_check.isChecked() is False

    def test_settings_dialog_type_change_clears_invalid_default(self, qtbot):
        dialog = SqlParameterSettingsDialog(_param("invoiceDate", sql_type="date", default_value="today"))
        qtbot.addWidget(dialog)

        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("integer"))

        assert dialog.default_today_check.isHidden()
        assert dialog.parameter()["default_value"] == ""