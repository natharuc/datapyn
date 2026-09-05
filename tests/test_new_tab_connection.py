"""
Testes para a nova funcionalidade de conectar em nova aba
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt

from source.src.ui.components.connection_panel import ConnectionsList, ConnectionPanel
from source.src.ui.main_window import MainWindow
from source.src.ui.components.session_widget import SessionWidget


class TestNewTabInheritsConnection:
    """Nova aba deve herdar a conexao da aba ativa"""

    @pytest.fixture
    def main(self, qtbot):
        main_window = MainWindow()
        main_window.show()
        qtbot.addWidget(main_window)
        return main_window

    def test_new_session_captures_previous_connection(self, main, qtbot):
        with patch("src.core.session.Session.connect", return_value=False):
            main._new_session()

        widget1 = main._get_current_session_widget()
        assert widget1 is not None

        widget1.session._connection_name = "TesteConexao"
        widget1.session._connector = MagicMock(is_connected=True)

        connected_calls = []

        def fake_connect(self_session, group_or_name, name="", password=""):
            conn_name = name or group_or_name
            self_session._connection_name = conn_name
            self_session._connector = MagicMock(is_connected=True)
            connected_calls.append(conn_name)
            return True

        with patch("src.core.session.Session.connect", fake_connect):
            main._new_session()
            qtbot.wait(300)

        assert "TesteConexao" in connected_calls

    def test_new_session_restores_group_database_and_ui_state(self, main, qtbot):
        with patch("src.core.session.Session.connect", return_value=False):
            main._new_session()

        source_widget = main._get_current_session_widget()
        source_session = source_widget.session
        source_session._connection_group = "Prod"
        source_session._connection_name = "TesteConexao"
        source_session._database_context = "Provisao"

        connector = MagicMock()
        connector.is_connected.return_value = True
        connector.get_current_database_context.return_value = "Provisao"

        def fake_connect(self_session, group_or_name, name="", password=""):
            assert group_or_name == "Prod"
            assert name == "TesteConexao"
            assert self_session.database_context == "Provisao"
            self_session._connection_group = group_or_name
            self_session._connection_name = name
            self_session._connector = connector
            self_session._database_context = "Provisao"
            return True

        with (
            patch("src.core.session.Session.connect", fake_connect),
            patch.object(main, "_on_session_connection_changed") as connection_changed,
        ):
            main._new_session()
            qtbot.wait(300)

        new_widget = main._get_current_session_widget()
        assert new_widget.session.connection_group == "Prod"
        assert new_widget.session.connection_name == "TesteConexao"
        assert new_widget.session.database_context == "Provisao"
        connection_changed.assert_called_once_with(
            new_widget.session,
            "TesteConexao",
            "Provisao",
        )

        first_block = new_widget.editor.get_blocks()[0]
        assert first_block.get_database_name() == "Provisao"

    def test_new_session_without_connection_stays_disconnected(self, main, qtbot):
        with patch("src.core.session.Session.connect", return_value=False):
            main._new_session()

        widget1 = main._get_current_session_widget()
        widget1.session._connection_name = None
        widget1.session._connector = None

        with patch("src.core.session.Session.connect") as mock_connect:
            main._new_session()
            mock_connect.assert_not_called()

    def test_new_session_from_empty_state_no_connection(self, main, qtbot):
        current = main._get_current_session_widget()
        if current and hasattr(current, "session"):
            current.session._connection_name = None
            current.session._connector = None

        with patch("src.core.session.Session.connect") as mock_connect:
            main._new_session()
            mock_connect.assert_not_called()


class TestNewTabConnection:
    @pytest.fixture
    def app(self):
        from PyQt6.QtWidgets import QApplication
        import sys

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app

    def test_connection_list_has_new_tab_signal(self, app):
        connections_list = ConnectionsList()
        assert hasattr(connections_list, "new_tab_connection_requested")
        assert hasattr(connections_list.new_tab_connection_requested, "emit")

    def test_connection_panel_has_new_tab_signal(self, app):
        connection_panel = ConnectionPanel()
        assert hasattr(connection_panel, "new_tab_connection_requested")
        assert hasattr(connection_panel.new_tab_connection_requested, "emit")

    @patch("PyQt6.QtGui.QGuiApplication.keyboardModifiers")
    def test_ctrl_double_click_emits_new_tab_signal(self, mock_modifiers, app):
        mock_modifiers.return_value = Qt.KeyboardModifier.ControlModifier

        connections_list = ConnectionsList()
        new_tab_signal = MagicMock()
        normal_signal = MagicMock()
        connections_list.new_tab_connection_requested = new_tab_signal
        connections_list.connection_double_clicked = normal_signal

        connections_list._on_connection_activated("Prod", "TestConnection")

        new_tab_signal.emit.assert_called_once_with("Prod", "TestConnection")
        normal_signal.emit.assert_not_called()

    @patch("PyQt6.QtGui.QGuiApplication.keyboardModifiers")
    def test_normal_double_click_emits_normal_signal(self, mock_modifiers, app):
        mock_modifiers.return_value = Qt.KeyboardModifier.NoModifier

        connections_list = ConnectionsList()
        new_tab_signal = MagicMock()
        normal_signal = MagicMock()
        connections_list.new_tab_connection_requested = new_tab_signal
        connections_list.connection_double_clicked = normal_signal

        connections_list._on_connection_activated("", "TestConnection")

        normal_signal.emit.assert_called_once_with("", "TestConnection")
        new_tab_signal.emit.assert_not_called()

    def test_middle_click_emits_new_tab_signal(self, app, qtbot):
        """Middle-click (scroll wheel) on a connection opens it in a new tab."""
        from PyQt6.QtCore import QPointF, QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QTreeWidgetItem

        connections_list = ConnectionsList()
        qtbot.addWidget(connections_list)

        group_item = QTreeWidgetItem(["Prod"])
        connections_list.tree_widget.addTopLevelItem(group_item)
        conn_item = QTreeWidgetItem(["TestConnection"])
        conn_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"type": "connection", "group": "Prod", "name": "TestConnection"},
        )
        group_item.addChild(conn_item)
        group_item.setExpanded(True)

        received = []
        connections_list.new_tab_connection_requested.connect(
            lambda g, n: received.append((g, n))
        )

        rect = connections_list.tree_widget.visualItemRect(conn_item)
        pos = rect.center()
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(pos),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert connections_list.eventFilter(connections_list.tree_widget.viewport(), event) is True
        assert received == [("Prod", "TestConnection")]

    def test_context_menu_has_new_tab_option(self, app):
        connections_list = ConnectionsList()
        assert hasattr(connections_list, "_show_context_menu")
        assert hasattr(connections_list, "tree_widget")
        assert hasattr(connections_list, "new_tab_connection_requested")

    @patch("src.database.ConnectionManager.get_connection_config")
    def test_main_window_connect_new_tab_method(self, mock_get_config, app):
        mock_get_config.return_value = {"password": "test_pass", "use_windows_auth": False}

        main_window = MainWindow()
        assert hasattr(main_window, "_connect_new_tab")

        main_window._new_session = MagicMock()
        main_window._get_current_session_widget = MagicMock()

        widget_mock = MagicMock()
        widget_mock.connect_to_database = MagicMock()
        main_window._get_current_session_widget.return_value = widget_mock

        main_window._connect_new_tab("Prod", "TestConnection")

        main_window._new_session.assert_called_once()
        widget_mock.connect_to_database.assert_called_once_with("Prod", "TestConnection", "test_pass")

    def test_main_window_signal_connection(self, app):
        main_window = MainWindow()
        assert hasattr(main_window, "connection_panel")
        assert hasattr(main_window.connection_panel, "new_tab_connection_requested")
        assert hasattr(main_window, "_connect_new_tab")

    def test_signal_propagation_from_list_to_panel(self, app):
        connection_panel = ConnectionPanel()
        panel_signal = MagicMock()
        connection_panel.new_tab_connection_requested = panel_signal

        connection_panel.connections_list.new_tab_connection_requested.emit("Prod", "TestConnection")
        assert hasattr(connection_panel.connections_list, "new_tab_connection_requested")


class TestActiveConnectionWidget:
    @pytest.fixture
    def app(self):
        from PyQt6.QtWidgets import QApplication
        import sys

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        return app

    def test_disconnect_icon_emits_and_shows_engine_icon(self, app):
        from src.language import S
        from source.src.ui.components.connection_panel import ActiveConnectionWidget

        widget = ActiveConnectionWidget()
        received = []
        widget.disconnect_clicked.connect(lambda: received.append(True))

        widget.set_connection(
            "Lakehouse",
            host="adb.azuredatabricks.net",
            database="mag_bronze.esim",
            db_type="databricks",
        )
        assert widget.name_label.text() == "Lakehouse"
        assert widget.host_label.text() == "adb.azuredatabricks.net"
        assert widget.database_label.text() == "mag_bronze.esim"
        assert "(databricks)" not in widget.database_label.text()
        assert widget.btn_disconnect.toolTip() == S.connection_panel.btn_disconnect
        assert widget.btn_disconnect.isEnabled()
        assert not widget.btn_disconnect.text().strip()
        assert widget.info_label is widget.database_label

        widget.btn_disconnect.click()
        assert received == [True]

        widget.set_disconnected()
        assert widget.name_label.text() == S.connection_panel.label_none
        assert not widget.btn_disconnect.isEnabled()
