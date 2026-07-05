"""Tests for SQL error surfacing and grid clearing in SessionWidget."""

import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(autouse=True)
def mock_all_dialogs():
    with (
        patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch.object(QMessageBox, "about", return_value=None),
    ):
        yield


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    from src.ui.main_window import MainWindow

    with (
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

        window = MainWindow()
        qtbot.addWidget(window)
        if not window._get_current_session_widget():
            window._new_session()
            qtbot.wait(100)
        yield window

        window.close()


def _seed_execution_context(sw):
    sw._current_query = "SELECT * FROM atendimentoas WHERE Cancelad = true"
    sw._current_block_index = 0
    sw._current_block_name = "block1"
    sw._current_connection_name_exec = "Test Connection"
    sw._current_database_name_exec = "test_db"
    sw._execution_start_time = 0.0
    sw._sql_stopping = False
    sw._cancel_requested = False


class TestSqlErrorSurfacing:
    def test_error_clears_grid_and_shows_output(self, main_window, qtbot):
        sw = main_window._get_current_session_widget()
        _seed_execution_context(sw)

        viewer = MagicMock()
        with (
            patch.object(sw, "_get_own_panels", return_value={"results": viewer}),
            patch.object(sw, "_show_output") as mock_show_output,
            patch.object(sw, "_log_entry") as mock_log_entry,
        ):
            sw._on_sql_finished(None, "Table 'test_db.atendimentoas' doesn't exist")

        mock_show_output.assert_called_once()
        viewer.clear.assert_called_once()
        mock_log_entry.assert_called_once()
        args, _ = mock_log_entry.call_args
        assert args[0].level == "error"

    def test_none_df_with_empty_error_synthesizes_error(self, main_window, qtbot):
        sw = main_window._get_current_session_widget()
        _seed_execution_context(sw)

        viewer = MagicMock()
        with (
            patch.object(sw, "_get_own_panels", return_value={"results": viewer}),
            patch.object(sw, "_show_output") as mock_show_output,
            patch.object(sw, "_log_entry") as mock_log_entry,
        ):
            sw._on_sql_finished(None, "")

        # Defensive guard: must NOT take the success path that leaves the grid stale.
        mock_show_output.assert_called_once()
        viewer.clear.assert_called_once()
        args, _ = mock_log_entry.call_args
        assert args[0].level == "error"
