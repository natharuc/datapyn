"""Tests for SessionWidget._reveal_in_folder (Qt-native open)."""

import os

import pytest


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    from unittest.mock import MagicMock, patch

    from PyQt6.QtWidgets import QApplication, QMessageBox

    with (
        patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch.object(QMessageBox, "about", return_value=None),
        patch("src.ui.main_window.ConnectionManager") as MockConnManager,
        patch("src.ui.main_window._main.ConnectionManager") as MockMainConnManager,
        patch("src.core.session_manager.Path.home", return_value=tmp_path),
    ):
        mock_conn_manager = MockConnManager.return_value
        MockMainConnManager.return_value = mock_conn_manager
        mock_conn_manager.get_saved_connections.return_value = ["Test Connection"]
        mock_conn_manager.get_connection_config.return_value = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "database": "test_db",
            "username": "test_user",
            "use_windows_auth": False,
        }
        mock_conn_manager.get_connections_by_group.return_value = {
            "Test Connection": {"db_type": "mysql", "group": "Desenvolvimento"}
        }
        mock_conn_manager.get_groups.return_value = {"Desenvolvimento": {"color": "#007acc"}}
        mock_conn_manager.active_connection = None
        mock_conn_manager.get_active_connection.return_value = None
        mock_conn_manager.get_connection.return_value = None
        mock_conn_manager.mark_connection_used = MagicMock()
        mock_conn_manager.create_connection = MagicMock()

        from src.ui.main_window import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)
        if not window._get_current_session_widget():
            window._new_session()
            qtbot.wait(100)
        yield window

        window.close()


class TestRevealInFolder:
    def test_uses_qdesktopservices_to_open_folder(self, main_window, qtbot, tmp_path):
        from unittest.mock import patch

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        sw = main_window._get_current_session_widget()
        file_path = tmp_path / "block1.csv"
        file_path.write_bytes(b"")

        captured = []

        def _open(url):
            captured.append(url)
            return True

        with patch.object(QDesktopServices, "openUrl", side_effect=_open):
            sw._reveal_in_folder(str(file_path))

        assert len(captured) == 1
        expected_folder = QUrl.fromLocalFile(str(tmp_path))
        assert captured[0].toLocalFile() == expected_folder.toLocalFile()

    def test_falls_back_to_subprocess_when_qdesktopservices_fails(self, main_window, qtbot, tmp_path):
        from unittest.mock import patch

        from PyQt6.QtGui import QDesktopServices

        sw = main_window._get_current_session_widget()
        file_path = tmp_path / "block1.csv"
        file_path.write_bytes(b"")

        with (
            patch.object(QDesktopServices, "openUrl", return_value=False),
            patch("subprocess.Popen") as mock_popen,
        ):
            sw._reveal_in_folder(str(file_path))

        mock_popen.assert_called_once()
