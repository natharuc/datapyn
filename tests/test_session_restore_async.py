from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.session import Session
from src.core.session_manager import SessionManager
from src.ui.main_window._sessions import SessionsMixin


class _DummySessionsHost(SessionsMixin):
    def __init__(self):
        self._pending_session_reconnects = []
        self._pending_legacy_active_connection = None
        self._restored_session_reconnects_active = False
        self._session_widgets = {}
        self._is_closing = False
        self._current_widget = None
        self.connection_manager = MagicMock()
        self.connection_manager.get_connection_ref_by_name.return_value = None

    def _get_current_session_widget(self):
        return self._current_widget


def test_session_initialize_skips_reconnect_when_disabled():
    session = Session(session_id="s1", title="Script 1")
    session._connection_name = "analytics"

    manager = MagicMock()
    manager.get_connection.return_value = None

    session.initialize(manager, reconnect=False)

    manager.get_connection.assert_called_once_with("", "analytics")
    manager.create_connection.assert_not_called()
    assert session.connection_name == "analytics"
    assert not session.is_connected


def test_session_connect_rejects_disconnected_connector():
    session = Session(session_id="s1", title="Script 1")
    manager = MagicMock()
    manager.get_connection_config.return_value = {
        "db_type": "sqlserver",
        "host": "host",
        "port": 1433,
        "database": "master",
    }
    connector = MagicMock()
    connector.connect.return_value = False
    connector.is_connected.return_value = False

    with (
        patch("src.database.connection_manager.ConnectionManager", return_value=manager),
        patch("src.database.database_connector.DatabaseConnector", return_value=connector),
    ):
        assert session.connect("Prod", "Conn") is False

    assert session.connector is None
    assert session.connection_name is None


def test_session_manager_load_sessions_preserves_connections_without_reconnect(tmp_path):
    manager = SessionManager(workspace_path=tmp_path)
    manager._sessions_file.write_text(
        '{\n'
        '  "version": 1,\n'
        '  "focused_session": "s1",\n'
        '  "session_order": ["s1"],\n'
        '  "sessions": {\n'
        '    "s1": {\n'
        '      "session_id": "s1",\n'
        '      "title": "Script 1",\n'
        '      "connection_name": "analytics",\n'
        '      "database_context": "",\n'
        '      "code": "",\n'
        '      "blocks": [],\n'
        '      "notification_config": null\n'
        '    }\n'
        '  }\n'
        '}',
        encoding="utf-8",
    )

    connection_manager = MagicMock()
    connection_manager.get_connection.return_value = None
    manager.load_sessions(connection_manager)

    connection_manager.create_connection.assert_not_called()
    restored = manager.focused_session
    assert restored is not None
    assert restored.connection_name == "analytics"
    assert not restored.is_connected


def test_restored_connections_are_dispatched_only_after_async_queue_starts(monkeypatch):
    host = _DummySessionsHost()
    widget = MagicMock()
    widget._is_closing = False
    widget.session = SimpleNamespace(session_id="s1", is_connected=False, connection_name="analytics")
    host._session_widgets["s1"] = widget
    monkeypatch.setattr(
        "src.ui.main_window._sessions.widget_is_valid",
        lambda candidate: candidate is widget,
    )

    scheduled = []
    monkeypatch.setattr("src.ui.main_window._sessions.QTimer.singleShot", lambda delay, callback: scheduled.append((delay, callback)))

    host._queue_restored_session_connection("s1", "analytics")

    assert widget.connect_to_database.call_count == 0

    host._start_restored_session_reconnects()

    assert widget.connect_to_database.call_count == 0
    assert scheduled

    _, callback = scheduled.pop(0)
    callback()

    widget.connect_to_database.assert_called_once_with("", "analytics")


def test_restore_sessions_keeps_cli_opened_session(tmp_path, monkeypatch):
    """Deferred restore must keep the CLI tab first and not recreate its widget."""
    host = _DummySessionsHost()
    host.session_manager = SessionManager(workspace_path=tmp_path)
    cli = host.session_manager.create_session(title="Opened.sql")
    cli_widget = MagicMock()
    host._session_widgets[cli.session_id] = cli_widget
    host.session_manager.focus_session(cli.session_id)

    host.session_manager._sessions_file.write_text(
        "{\n"
        '  "version": 1,\n'
        '  "focused_session": "s1",\n'
        '  "session_order": ["s1"],\n'
        '  "sessions": {\n'
        '    "s1": {\n'
        '      "session_id": "s1",\n'
        '      "title": "Saved",\n'
        '      "connection_name": "",\n'
        '      "database_context": "",\n'
        '      "code": "",\n'
        '      "blocks": [],\n'
        '      "notification_config": null\n'
        "    }\n"
        "  }\n"
        "}",
        encoding="utf-8",
    )

    host.connection_manager = MagicMock()
    host.connection_manager.get_connection.return_value = None
    host.workspace_manager = MagicMock()
    host.workspace_manager.load_workspace.return_value = {}
    host.session_tabs = MagicMock()
    host._show_empty_state = MagicMock()
    host._create_session_widget = MagicMock()
    host._queue_restored_session_connection = MagicMock()
    host._start_restored_session_reconnects = MagicMock()
    monkeypatch.setattr(
        "src.ui.main_window._sessions.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )

    host._restore_sessions()

    assert cli.session_id in host.session_manager._session_order
    assert host.session_manager._session_order[0] == cli.session_id
    assert host.session_manager.focused_session.session_id == cli.session_id
    assert host._session_widgets[cli.session_id] is cli_widget
    created_ids = [call.args[0].session_id for call in host._create_session_widget.call_args_list]
    assert cli.session_id not in created_ids
    assert "s1" in created_ids
    host._show_empty_state.assert_not_called()
    host.session_tabs.setCurrentIndex.assert_called()
    host._start_restored_session_reconnects.assert_called_once()


def test_restored_schema_callback_keeps_session_and_group_context(monkeypatch):
    host = _DummySessionsHost()
    widget = MagicMock()
    widget._is_closing = False
    host._session_widgets["s1"] = widget
    host._load_schema_with_loading = MagicMock()
    connector = MagicMock(name="connector")
    monkeypatch.setattr(
        "src.ui.main_window._sessions.widget_is_valid",
        lambda candidate: candidate is widget,
    )

    host._load_restored_session_schema(
        widget,
        "s1",
        connector,
        "analytics",
        "Prod",
    )

    host._load_schema_with_loading.assert_called_once_with(
        connector,
        "analytics",
        session_id="s1",
        connection_group="Prod",
    )

    host._session_widgets["s1"] = MagicMock()
    host._load_restored_session_schema(
        widget,
        "s1",
        MagicMock(name="late-connector"),
        "analytics",
        "Prod",
    )
    assert host._load_schema_with_loading.call_count == 1


def test_legacy_workspace_connection_is_queued_for_focused_session(monkeypatch):
    host = _DummySessionsHost()
    widget = MagicMock()
    widget._is_closing = False
    widget.session = SimpleNamespace(session_id="s1", is_connected=False, connection_name="")
    host._current_widget = widget
    host._session_widgets["s1"] = widget
    monkeypatch.setattr(
        "src.ui.main_window._sessions.widget_is_valid",
        lambda candidate: candidate is widget,
    )

    scheduled = []
    monkeypatch.setattr("src.ui.main_window._sessions.QTimer.singleShot", lambda delay, callback: scheduled.append((delay, callback)))

    host._reconnect_saved_connection("analytics")

    assert host._pending_session_reconnects == [("s1", "", "analytics")]
    assert widget.connect_to_database.call_count == 0
    assert scheduled

    _, callback = scheduled.pop(0)
    callback()

    widget.connect_to_database.assert_called_once_with("", "analytics")