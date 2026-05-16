from types import SimpleNamespace
from unittest.mock import MagicMock

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

    def _get_current_session_widget(self):
        return self._current_widget


def test_session_initialize_skips_reconnect_when_disabled():
    session = Session(session_id="s1", title="Script 1")
    session._connection_name = "analytics"

    manager = MagicMock()
    manager.get_connection.return_value = None

    session.initialize(manager, reconnect=False)

    manager.get_connection.assert_called_once_with("analytics")
    manager.create_connection.assert_not_called()
    assert session.connection_name == "analytics"
    assert not session.is_connected


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
    widget.session = SimpleNamespace(session_id="s1", is_connected=False, connection_name="analytics")
    host._session_widgets["s1"] = widget

    scheduled = []
    monkeypatch.setattr("src.ui.main_window._sessions.QTimer.singleShot", lambda delay, callback: scheduled.append((delay, callback)))

    host._queue_restored_session_connection("s1", "analytics")

    assert widget.connect_to_database.call_count == 0

    host._start_restored_session_reconnects()

    assert widget.connect_to_database.call_count == 0
    assert scheduled

    _, callback = scheduled.pop(0)
    callback()

    widget.connect_to_database.assert_called_once_with("analytics")


def test_legacy_workspace_connection_is_queued_for_focused_session(monkeypatch):
    host = _DummySessionsHost()
    widget = MagicMock()
    widget.session = SimpleNamespace(session_id="s1", is_connected=False, connection_name="")
    host._current_widget = widget
    host._session_widgets["s1"] = widget

    scheduled = []
    monkeypatch.setattr("src.ui.main_window._sessions.QTimer.singleShot", lambda delay, callback: scheduled.append((delay, callback)))

    host._reconnect_saved_connection("analytics")

    assert host._pending_session_reconnects == [("s1", "analytics")]
    assert widget.connect_to_database.call_count == 0
    assert scheduled

    _, callback = scheduled.pop(0)
    callback()

    widget.connect_to_database.assert_called_once_with("analytics")