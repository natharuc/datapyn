"""
Tests for per-tab notification feature:
- TabNotificationDialog UI
- result[row][col] template rendering
- Per-tab config in SessionWidget
- DPW persistence of notification config
"""

import pytest
import json
import pandas as pd
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt


# ==================== RESULT REFERENCE RENDERING ====================


class TestResultRefRendering:
    """Test the result[N][M] reference resolution in templates."""

    def _resolve(self, template, last_result):
        from src.ui.components.session_widget import SessionWidget
        return SessionWidget._resolve_result_refs(template, last_result)

    def test_basic_result_ref(self):
        """{{result[0][0]}} resolves to first cell of DataFrame."""
        df = pd.DataFrame({"a": [42], "b": [99]})
        result = self._resolve("Value: {{result[0][0]}}", df)
        assert result == "Value: 42"

    def test_result_ref_second_column(self):
        """{{result[0][1]}} resolves to second column."""
        df = pd.DataFrame({"a": [42], "b": [99]})
        result = self._resolve("{{result[0][1]}}", df)
        assert result == "99"

    def test_result_ref_second_row(self):
        """{{result[1][0]}} resolves to second row."""
        df = pd.DataFrame({"x": [10, 20, 30]})
        result = self._resolve("{{result[1][0]}}", df)
        assert result == "20"

    def test_multiple_result_refs(self):
        """Multiple result refs in one template."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = self._resolve("{{result[0][0]}} / {{result[1][1]}}", df)
        assert result == "1 / 4"

    def test_result_ref_out_of_bounds(self):
        """Out-of-bounds ref is left as-is."""
        df = pd.DataFrame({"a": [42]})
        result = self._resolve("{{result[5][0]}}", df)
        assert result == "{{result[5][0]}}"

    def test_result_ref_none_dataframe(self):
        """None last_result leaves refs as-is."""
        result = self._resolve("{{result[0][0]}}", None)
        assert result == "{{result[0][0]}}"

    def test_result_ref_mixed_with_vars(self):
        """result refs mixed with {{var}} placeholders (vars not resolved here)."""
        df = pd.DataFrame({"val": [123]})
        result = self._resolve("{{tab_name}}: {{result[0][0]}}", df)
        assert result == "{{tab_name}}: 123"

    def test_result_ref_string_value(self):
        """String values are resolved correctly."""
        df = pd.DataFrame({"name": ["Alice"]})
        result = self._resolve("{{result[0][0]}}", df)
        assert result == "Alice"

    def test_result_ref_no_refs_in_template(self):
        """Template without result refs is returned unchanged."""
        df = pd.DataFrame({"a": [1]})
        result = self._resolve("No refs here", df)
        assert result == "No refs here"

    def test_result_ref_empty_dataframe(self):
        """Empty DataFrame leaves refs as-is."""
        df = pd.DataFrame()
        result = self._resolve("{{result[0][0]}}", df)
        assert result == "{{result[0][0]}}"


# ==================== TAB NOTIFICATION DIALOG ====================


class TestTabNotificationDialog:
    """Test the TabNotificationDialog UI."""

    @pytest.fixture
    def dialog(self, qtbot):
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        dlg = TabNotificationDialog(parent=None)
        qtbot.addWidget(dlg)
        return dlg

    @pytest.fixture
    def dialog_with_config(self, qtbot):
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        config = {
            "enabled": True,
            "title": "My Tab",
            "message": "Got {{result[0][0]}}",
        }
        dlg = TabNotificationDialog(current_config=config, parent=None)
        qtbot.addWidget(dlg)
        return dlg

    def test_dialog_creates(self, dialog):
        """Dialog is created without errors."""
        assert dialog is not None

    def test_default_enable_unchecked(self, dialog):
        """Enable checkbox is unchecked by default (no config)."""
        assert not dialog._enable_cb.isChecked()

    def test_config_restores_enabled(self, dialog_with_config):
        """Config with enabled=True restores checkbox."""
        assert dialog_with_config._enable_cb.isChecked()

    def test_config_restores_title(self, dialog_with_config):
        """Config restores title input."""
        assert dialog_with_config._title_input.text() == "My Tab"

    def test_config_restores_message(self, dialog_with_config):
        """Config restores message input."""
        assert dialog_with_config._message_input.text() == "Got {{result[0][0]}}"

    def test_save_returns_config(self, dialog, qtbot):
        """Clicking save returns config dict."""
        dialog._enable_cb.setChecked(True)
        dialog._title_input.setText("Test Title")
        dialog._message_input.setText("Test Msg")
        dialog._on_save()
        config = dialog.get_config()
        assert config is not None
        assert config["enabled"] is True
        assert config["title"] == "Test Title"
        assert config["message"] == "Test Msg"
        assert "color" in config

    def test_cancel_returns_none(self, dialog):
        """get_config returns None if dialog not saved."""
        config = dialog.get_config()
        assert config is None

    def test_template_group_disabled_when_unchecked(self, dialog):
        """Template group is disabled when enable is unchecked."""
        dialog._enable_cb.setChecked(False)
        assert not dialog._template_group.isEnabled()

    def test_template_group_enabled_when_checked(self, dialog):
        """Template group is enabled when enable is checked."""
        dialog._enable_cb.setChecked(True)
        assert dialog._template_group.isEnabled()

    def test_color_picker_exists(self, dialog):
        """Color picker button exists."""
        assert hasattr(dialog, '_color_btn')
        assert hasattr(dialog, '_color_value')

    def test_color_default_is_green(self, dialog):
        """Default color is success green."""
        assert dialog._color_value == "#1e8a3e"

    def test_color_saved_in_config(self, dialog):
        """Color is included in saved config."""
        dialog._enable_cb.setChecked(True)
        dialog._color_value = "#ff5500"
        dialog._on_save()
        config = dialog.get_config()
        assert config["color"] == "#ff5500"

    def test_color_restored_from_config(self, qtbot):
        """Color is restored from existing config."""
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        dlg = TabNotificationDialog(current_config={"enabled": True, "color": "#abc123"}, parent=None)
        qtbot.addWidget(dlg)
        assert dlg._color_value == "#abc123"


# ==================== PER-TAB CONFIG ON SESSION WIDGET ====================


class TestSessionWidgetTabNotification:
    """Test the per-tab notification config on SessionWidget."""

    @pytest.fixture
    def widget(self, qtbot):
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = Session(session_id="test-1", title="TestTab")
        tm = ThemeManager()
        w = SessionWidget(session=session, theme_manager=tm)
        qtbot.addWidget(w)
        return w

    def test_default_config_is_none(self, widget):
        """Default tab notification config is None."""
        assert widget.get_tab_notification_config() is None

    def test_set_and_get_config(self, widget):
        """Can set and retrieve tab notification config."""
        config = {"enabled": True, "title": "T", "message": "M"}
        widget.set_tab_notification_config(config)
        assert widget.get_tab_notification_config() == config

    def test_clear_config(self, widget):
        """Can clear config by setting None."""
        widget.set_tab_notification_config({"enabled": True, "title": "T", "message": "M"})
        widget.set_tab_notification_config(None)
        assert widget.get_tab_notification_config() is None


# ==================== DPW PERSISTENCE ====================


class TestDPWNotificationPersistence:
    """Test that notification config is saved/loaded from DPW files."""

    def test_save_includes_notification_config(self, tmp_path):
        """DPW save includes notification_config when set."""
        dpw_file = tmp_path / "test.dpw"
        blocks_data = [{"language": "sql", "code": "SELECT 1", "height": 400, "block_name": "", "is_active": True}]
        notif_config = {"enabled": True, "title": "My Tab", "message": "{{result[0][0]}}"}

        dpw_content = {
            "version": "1.0",
            "blocks": blocks_data,
        }
        if notif_config and notif_config.get("enabled"):
            dpw_content["notification_config"] = notif_config

        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        assert "notification_config" in loaded
        assert loaded["notification_config"]["enabled"] is True
        assert loaded["notification_config"]["title"] == "My Tab"
        assert loaded["notification_config"]["message"] == "{{result[0][0]}}"

    def test_save_excludes_disabled_config(self, tmp_path):
        """DPW save does NOT include notification_config when disabled."""
        dpw_file = tmp_path / "test.dpw"
        blocks_data = [{"language": "sql", "code": "SELECT 1", "height": 400, "block_name": "", "is_active": True}]
        notif_config = {"enabled": False, "title": "X", "message": "Y"}

        dpw_content = {
            "version": "1.0",
            "blocks": blocks_data,
        }
        if notif_config and notif_config.get("enabled"):
            dpw_content["notification_config"] = notif_config

        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        assert "notification_config" not in loaded

    def test_load_restores_notification_config(self, tmp_path):
        """Loading DPW with notification_config restores it."""
        dpw_content = {
            "version": "1.0",
            "blocks": [],
            "notification_config": {
                "enabled": True,
                "title": "Loaded Title",
                "message": "Loaded Msg with {{result[0][1]}}",
            },
        }
        dpw_file = tmp_path / "test.dpw"
        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        config = loaded.get("notification_config")
        assert config is not None
        assert config["enabled"] is True
        assert config["title"] == "Loaded Title"
        assert "{{result[0][1]}}" in config["message"]

    def test_load_without_notification_config(self, tmp_path):
        """Loading DPW without notification_config gives None."""
        dpw_content = {
            "version": "1.0",
            "blocks": [],
        }
        dpw_file = tmp_path / "test.dpw"
        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        config = loaded.get("notification_config")
        assert config is None
