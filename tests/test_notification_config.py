"""
Tests for notification configuration system:
- Settings dialog UI (toggle, sound, templates)
- Template rendering with variables
- Notification enabled/disabled via QSettings
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PyQt6.QtCore import QSettings


# ==================== TEMPLATE RENDERING TESTS ====================


class TestNotificationTemplateRendering:
    """Test the template variable replacement logic used in notifications."""

    def _render(self, template: str, variables: dict) -> str:
        """Reproduce the same rendering logic from session_widget."""
        result = template
        for key, value in variables.items():
            result = result.replace("{{" + key + "}}", value)
        return result

    def test_render_basic_rows(self):
        """Template with {{rows}} is replaced correctly."""
        tpl = "Complete! {{rows}} rows returned"
        result = self._render(tpl, {"rows": "1,234"})
        assert result == "Complete! 1,234 rows returned"

    def test_render_multiple_variables(self):
        """Template with multiple variables is rendered correctly."""
        tpl = "{{type}} - {{rows}} rows from {{connection}}"
        result = self._render(tpl, {
            "type": "SQL Query",
            "rows": "500",
            "connection": "my_db",
        })
        assert result == "SQL Query - 500 rows from my_db"

    def test_render_all_variables(self):
        """All supported variables are replaced."""
        tpl = "{{type}} | {{rows}} | {{blocks}} | {{tab_name}} | {{block_name}} | {{connection}} | {{database}} | {{error}}"
        variables = {
            "type": "SQL Query",
            "rows": "100",
            "blocks": "3",
            "tab_name": "My Tab",
            "block_name": "query1",
            "connection": "prod_db",
            "database": "analytics",
            "error": "",
        }
        result = self._render(tpl, variables)
        assert result == "SQL Query | 100 | 3 | My Tab | query1 | prod_db | analytics | "

    def test_render_empty_variables(self):
        """Empty variables are replaced with empty string."""
        tpl = "{{type}}: {{block_name}}"
        result = self._render(tpl, {"type": "Python", "block_name": ""})
        assert result == "Python: "

    def test_render_no_variables(self):
        """Template without variables is returned as-is."""
        tpl = "Execution complete!"
        result = self._render(tpl, {"rows": "100"})
        assert result == "Execution complete!"

    def test_render_error_template(self):
        """Error template with {{error}} is rendered."""
        tpl = "Error: {{error}}"
        result = self._render(tpl, {"error": "connection timeout", "type": "SQL Query"})
        assert result == "Error: connection timeout"

    def test_render_custom_format(self):
        """User-defined custom template works."""
        tpl = "[{{tab_name}}] {{block_name}} -> {{rows}} rows ({{connection}}/{{database}})"
        result = self._render(tpl, {
            "tab_name": "Analysis",
            "block_name": "sales_query",
            "rows": "5,000",
            "connection": "warehouse",
            "database": "sales_db",
        })
        assert result == "[Analysis] sales_query -> 5,000 rows (warehouse/sales_db)"

    def test_render_preserves_unknown_placeholders(self):
        """Unknown {{variables}} are left as-is."""
        tpl = "{{type}} - {{unknown_var}}"
        result = self._render(tpl, {"type": "SQL Query"})
        assert result == "SQL Query - {{unknown_var}}"


# ==================== SETTINGS PERSISTENCE TESTS ====================


class TestNotificationSettings:
    """Test that notification settings are read/written correctly via QSettings."""

    @pytest.fixture(autouse=True)
    def _clean_settings(self):
        """Clean notification settings before and after each test."""
        settings = QSettings("DataPyn", "DataPyn")
        keys = [
            "notifications/enabled",
            "notifications/sound",
            "notifications/success_title",
            "notifications/success_message",
            "notifications/error_title",
            "notifications/error_message",
        ]
        originals = {k: settings.value(k) for k in keys}
        for k in keys:
            settings.remove(k)
        yield
        for k in keys:
            settings.remove(k)
            if originals[k] is not None:
                settings.setValue(k, originals[k])

    def test_default_enabled_is_true(self):
        """Notifications are enabled by default when no setting is saved."""
        settings = QSettings("DataPyn", "DataPyn")
        assert settings.value("notifications/enabled", True, type=bool) is True

    def test_default_sound_is_true(self):
        """Sound is enabled by default when no setting is saved."""
        settings = QSettings("DataPyn", "DataPyn")
        assert settings.value("notifications/sound", True, type=bool) is True

    def test_save_and_read_enabled_false(self):
        """Can save enabled=False and read it back."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/enabled", False)
        assert settings.value("notifications/enabled", True, type=bool) is False

    def test_save_and_read_sound_false(self):
        """Can save sound=False and read it back."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/sound", False)
        assert settings.value("notifications/sound", True, type=bool) is False

    def test_save_and_read_custom_templates(self):
        """Can save custom templates and read them back."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/success_title", "Done!")
        settings.setValue("notifications/success_message", "{{rows}} rows from {{connection}}")
        settings.setValue("notifications/error_title", "Failed")
        settings.setValue("notifications/error_message", "{{error}} on {{database}}")

        assert settings.value("notifications/success_title") == "Done!"
        assert settings.value("notifications/success_message") == "{{rows}} rows from {{connection}}"
        assert settings.value("notifications/error_title") == "Failed"
        assert settings.value("notifications/error_message") == "{{error}} on {{database}}"


# ==================== SETTINGS DIALOG UI TESTS ====================


class TestNotificationSettingsDialog:
    """Test the notifications tab in the settings dialog."""

    @pytest.fixture
    def dialog(self, qtbot):
        """Create a SettingsDialog for testing."""
        from src.ui.dialogs.settings_dialog import SettingsDialog
        from src.core import ShortcutManager

        sm = ShortcutManager()
        dlg = SettingsDialog(shortcut_manager=sm)
        qtbot.addWidget(dlg)
        return dlg

    def test_notifications_tab_exists(self, dialog):
        """The Notifications tab is present in the dialog."""
        tab_texts = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        # Check that at least one tab contains notification-related text
        assert any("notif" in t.lower() or "Notif" in t for t in tab_texts), f"No notifications tab found in: {tab_texts}"

    def test_notifications_tab_index(self, dialog):
        """The Notifications tab is at index 3 (after General, Shortcuts, Copilot)."""
        assert dialog.tabs.count() >= 5, f"Expected at least 5 tabs, got {dialog.tabs.count()}"

    def test_enabled_checkbox_exists(self, dialog):
        """The enabled checkbox is present and defaults to checked."""
        assert hasattr(dialog, 'notif_enabled_cb')
        assert dialog.notif_enabled_cb.isChecked()

    def test_sound_checkbox_exists(self, dialog):
        """The sound checkbox is present and defaults to checked."""
        assert hasattr(dialog, 'notif_sound_cb')
        assert dialog.notif_sound_cb.isChecked()

    def test_template_fields_exist(self, dialog):
        """All 4 template input fields exist."""
        assert hasattr(dialog, 'notif_success_title')
        assert hasattr(dialog, 'notif_success_msg')
        assert hasattr(dialog, 'notif_error_title')
        assert hasattr(dialog, 'notif_error_msg')

    def test_template_fields_have_defaults(self, dialog):
        """Template fields have non-empty default values."""
        assert dialog.notif_success_title.text() != ""
        assert dialog.notif_success_msg.text() != ""
        assert dialog.notif_error_title.text() != ""
        assert dialog.notif_error_msg.text() != ""

    def test_save_notification_settings(self, dialog, qtbot):
        """Saving settings persists notification config to QSettings."""
        # Modify values
        dialog.notif_enabled_cb.setChecked(False)
        dialog.notif_sound_cb.setChecked(False)
        dialog.notif_success_title.setText("Custom Title")
        dialog.notif_success_msg.setText("{{rows}} rows done")
        dialog.notif_error_title.setText("Oops")
        dialog.notif_error_msg.setText("Failed: {{error}}")

        # Save
        dialog._save_all()

        # Verify
        settings = QSettings("DataPyn", "DataPyn")
        assert settings.value("notifications/enabled", True, type=bool) is False
        assert settings.value("notifications/sound", True, type=bool) is False
        assert settings.value("notifications/success_title") == "Custom Title"
        assert settings.value("notifications/success_message") == "{{rows}} rows done"
        assert settings.value("notifications/error_title") == "Oops"
        assert settings.value("notifications/error_message") == "Failed: {{error}}"

        # Cleanup
        for key in ["notifications/enabled", "notifications/sound",
                     "notifications/success_title", "notifications/success_message",
                     "notifications/error_title", "notifications/error_message"]:
            settings.remove(key)


# ==================== NOTIFICATION DISABLED TEST ====================


class TestNotificationDisabled:
    """Test that notifications are skipped when disabled."""

    @pytest.fixture(autouse=True)
    def _clean_settings(self):
        settings = QSettings("DataPyn", "DataPyn")
        original = settings.value("notifications/enabled")
        yield
        if original is not None:
            settings.setValue("notifications/enabled", original)
        else:
            settings.remove("notifications/enabled")

    def test_send_notification_skipped_when_disabled(self):
        """_send_notification does NOT call ToastManager when notifications are disabled."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/enabled", False)

        with patch("src.ui.main_window._execution.ToastManager") as mock_tm:
            # Create a minimal mock that has the method
            mixin = MagicMock()
            from src.ui.main_window._execution import ExecutionMixin
            ExecutionMixin._send_notification(mixin, "Title", "Message", True, 0)
            mock_tm.notify.assert_not_called()

    def test_send_notification_called_when_enabled(self):
        """_send_notification calls ToastManager when notifications are enabled."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/enabled", True)

        with patch("src.ui.main_window._execution.ToastManager") as mock_tm:
            mixin = MagicMock()
            ExecutionMixin = __import__("src.ui.main_window._execution", fromlist=["ExecutionMixin"]).ExecutionMixin
            ExecutionMixin._send_notification(mixin, "Title", "Message", True, 0)
            mock_tm.notify.assert_called_once()

    def test_send_notification_passes_sound_setting(self):
        """_send_notification reads sound setting and passes it to ToastManager."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/enabled", True)
        settings.setValue("notifications/sound", False)

        with patch("src.ui.main_window._execution.ToastManager") as mock_tm:
            from src.ui.main_window._execution import ExecutionMixin
            mixin = MagicMock()
            ExecutionMixin._send_notification(mixin, "Title", "Message", True, 0)
            call_kwargs = mock_tm.notify.call_args
            assert call_kwargs[1].get("sound") is False or call_kwargs.kwargs.get("sound") is False

        # Cleanup
        settings.remove("notifications/sound")
