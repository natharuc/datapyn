"""Tests for SQL Server authentication modes in ConnectionEditDialog."""

from database.database_connector import (
    SQLSERVER_AUTH_ENTRA_MFA,
    SQLSERVER_AUTH_SQL_PASSWORD,
    SQLSERVER_AUTH_WINDOWS,
)
from ui.dialogs.connection_edit_dialog import ConnectionEditDialog, _format_connection_test_error


class TestConnectionEditDialog:
    """UI regression tests for SQL Server auth mode selection."""

    def test_new_dialog_defaults_to_sql_password_auth(self, qtbot):
        """New SQL Server dialogs should default to username/password auth."""
        dialog = ConnectionEditDialog(connection_name=None, config=None, groups={})
        qtbot.addWidget(dialog)

        assert dialog.cmb_type.currentData() == "sqlserver"
        assert dialog.cmb_sqlserver_auth.currentData() == SQLSERVER_AUTH_SQL_PASSWORD
        assert dialog.chk_save_password.isEnabled() is True

    def test_dialog_loads_legacy_windows_auth_config(self, qtbot):
        """Legacy use_windows_auth configs should map to the new combo."""
        dialog = ConnectionEditDialog(
            connection_name="Legacy SQL",
            config={
                "db_type": "sqlserver",
                "host": "localhost",
                "port": 1433,
                "database": "master",
                "use_windows_auth": True,
            },
            groups={},
        )
        qtbot.addWidget(dialog)

        assert dialog.cmb_sqlserver_auth.currentData() == SQLSERVER_AUTH_WINDOWS

        _, config = dialog.get_result()
        assert config["sqlserver_auth_mode"] == SQLSERVER_AUTH_WINDOWS
        assert config["use_windows_auth"] is True

    def test_dialog_returns_mfa_mode_without_saving_password(self, qtbot):
        """MFA mode should disable password persistence and persist the auth mode."""
        dialog = ConnectionEditDialog(connection_name=None, config=None, groups={})
        qtbot.addWidget(dialog)

        dialog.txt_name.setText("Azure SQL MFA")
        dialog.txt_host.setText("server.database.windows.net")
        dialog.txt_database.setText("app")
        dialog.txt_password.setText("should-not-be-saved")
        dialog.chk_save_password.setChecked(True)

        index = dialog.cmb_sqlserver_auth.findData(SQLSERVER_AUTH_ENTRA_MFA)
        dialog.cmb_sqlserver_auth.setCurrentIndex(index)

        assert dialog.txt_password.isEnabled() is False
        assert dialog.chk_save_password.isEnabled() is False
        assert dialog.chk_save_password.isChecked() is False

        _, config = dialog.get_result()
        assert config["sqlserver_auth_mode"] == SQLSERVER_AUTH_ENTRA_MFA
        assert config["use_windows_auth"] is False
        assert "password" not in config

    def test_dialog_allows_blank_username_for_mfa(self, qtbot):
        """MFA should allow an empty username and use it only as an optional login hint."""
        dialog = ConnectionEditDialog(connection_name=None, config=None, groups={})
        qtbot.addWidget(dialog)

        dialog.txt_name.setText("Azure SQL MFA")
        dialog.txt_host.setText("server.database.windows.net")
        index = dialog.cmb_sqlserver_auth.findData(SQLSERVER_AUTH_ENTRA_MFA)
        dialog.cmb_sqlserver_auth.setCurrentIndex(index)

        dialog._on_save()

        assert dialog.result() == dialog.DialogCode.Accepted

        _, config = dialog.get_result()
        assert config["username"] == ""
        assert config["sqlserver_auth_mode"] == SQLSERVER_AUTH_ENTRA_MFA

    def test_dialog_mfa_placeholder_marks_username_as_optional_hint(self, qtbot):
        """MFA placeholder should communicate that username is only a login hint."""
        dialog = ConnectionEditDialog(connection_name=None, config=None, groups={})
        qtbot.addWidget(dialog)

        index = dialog.cmb_sqlserver_auth.findData(SQLSERVER_AUTH_ENTRA_MFA)
        dialog.cmb_sqlserver_auth.setCurrentIndex(index)

        assert "Optional" in dialog.txt_username.placeholderText()

    def test_postgresql_utf8_decode_error_gets_actionable_message(self):
        """PostgreSQL driver encoding errors should not be shown as raw codec noise only."""
        error = UnicodeDecodeError("utf-8", b"conex\xe7ao", 5, 6, "invalid continuation byte")

        message = _format_connection_test_error(error)

        assert "PostgreSQL" in message
        assert "host" in message.lower()
        assert "codec can't decode" not in message

    def test_nested_postgresql_utf8_decode_error_gets_actionable_message(self):
        """Nested driver messages containing the codec failure should be normalized too."""
        error = RuntimeError("'utf-8' codec can't decode byte 0xe7 in position 78: invalid continuation byte")

        message = _format_connection_test_error(error)

        assert "PostgreSQL" in message
        assert "codec can't decode" not in message

    def test_regular_connection_test_error_is_unchanged(self):
        """Normal connection errors should preserve the driver message."""
        message = _format_connection_test_error(RuntimeError("password authentication failed"))

        assert message == "password authentication failed"

    def test_connection_test_error_handles_exception_str_decode_failure(self):
        """Even exception __str__ decode failures should become a clean PostgreSQL message."""
        class BrokenError(Exception):
            def __str__(self):
                raise UnicodeDecodeError("utf-8", b"conex\xe7ao", 5, 6, "invalid continuation byte")

        message = _format_connection_test_error(BrokenError())

        assert "PostgreSQL" in message
        assert "codec can't decode" not in message
