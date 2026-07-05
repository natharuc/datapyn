"""Integration test: a connector that raises must reach _on_sql_finished."""

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


class TestSqlWorkerErrorDelivery:
    def test_connector_error_reaches_on_sql_finished(self, main_window, qtbot):
        sw = main_window._get_current_session_widget()

        connector = MagicMock()
        connector.is_connected.return_value = True
        connector.db_type = "mysql"
        connector.is_query_busy.return_value = False
        connector._cancelled = False
        connector.request_cancel = MagicMock()
        connector.connection_params = {}
        connector.execute_query.side_effect = Exception(
            "(pymysql.err.OperationalError) (1054, \"Unknown column 'Cancelad' in 'WHERE'\")"
        )

        captured = []

        def _capture(df, err):
            captured.append((df, err))

        with (
            patch("src.ui.components.session_widget.get_connector_database_context", return_value=""),
            patch.object(sw, "_on_sql_finished", side_effect=_capture),
        ):
            sw._execute_sql_with_connector(
                connector,
                "select * from atendimentoas where id = 12565 and Cancelad = true",
                "block1",
                "Test Connection",
                None,
                None,
            )
            qtbot.waitUntil(lambda: len(captured) == 1, timeout=8000)

        df, err = captured[0]
        assert df is None
        assert err and "Cancelad" in err
        assert err != "__CANCELLED__"
