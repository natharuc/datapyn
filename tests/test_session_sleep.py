"""Session.sleep() — release the DB connection but keep the connection name.

The idle reaper calls sleep() instead of disconnect() so the next query can
auto-reconnect transparently (no "No active connection in this session" error).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.core.session import Session


class _FakeConnector:
    db_type = "mysql"
    engine = SimpleNamespace(url="mysql+pymysql://root:***@localhost:3306/seducao")
    connection_params = {
        "host": "localhost",
        "port": 3306,
        "database": "seducao",
        "username": "root",
    }

    def __init__(self) -> None:
        self.is_connected = True
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True
        self.is_connected = False


def test_sleep_releases_connector_but_keeps_connection_name():
    session = Session("s1")
    connector = _FakeConnector()
    session.set_connection("SEDUCAO", connector)

    assert session.is_connected is True
    assert session.connection_name == "SEDUCAO"

    session.sleep()

    # The live connector is gone, but the name is remembered so the execute path
    # can auto-reconnect (conn_name non-empty + connector None -> BlockAutoConnectWorker).
    assert session.is_connected is False
    assert session.connector is None
    assert session.connection_name == "SEDUCAO"
    # The underlying DB connection was actually released.
    assert connector.disconnected is True


def test_sleep_does_not_emit_disconnect_signals(qtbot):
    """sleep() must be transparent: no connection_changed('') / 'disconnected' status."""
    session = Session("s1")
    session.set_connection("SEDUCAO", _FakeConnector())

    connection_changes: list = []
    status_changes: list = []
    session.connection_changed.connect(connection_changes.append)
    session.status_changed.connect(status_changes.append)

    session.sleep()

    assert connection_changes == []  # no '' disconnect emission
    assert not any("disconnected" in (s or "").lower() for s in status_changes)


def test_sleep_preserves_database_context():
    session = Session("s1")
    session.set_connection("SEDUCAO", _FakeConnector())
    session.database_context = "seducao"

    session.sleep()

    assert session.database_context == "seducao"
    assert session.connection_name == "SEDUCAO"


def test_disconnect_still_clears_name():
    """disconnect() keeps its old behaviour (clears the name) — only sleep() preserves it."""
    session = Session("s1")
    session.set_connection("SEDUCAO", _FakeConnector())

    session.disconnect()

    assert session.is_connected is False
    assert session.connection_name is None
    assert session.connector is None


def test_idle_reaper_sleeps_session_instead_of_disconnecting(qtbot, monkeypatch):
    """The idle reaper must call session.sleep() (keep name) not disconnect() (clear name)."""
    from src.ui.components.session_widget import SessionWidget

    session = MagicMock()
    session.session_id = "reaper-sess"
    session.is_connected = True
    session.connection_name = "SEDUCAO"
    session.connector = MagicMock()
    session.blocks = []
    session.code = ""
    session.namespace = {}
    session.database_context = ""
    session.notification_config = None
    session.shared_parameters = []
    session.register_thread = MagicMock()
    session.unregister_thread = MagicMock()

    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)
    widget = SessionWidget(session)
    qtbot.addWidget(widget)

    # Force the session idle: last activity was long ago.
    import time as _time

    widget._last_db_activity_at = _time.monotonic() - 600
    widget._is_executing = False
    widget._sql_stopping = False
    widget._execution_queue = []
    widget._is_closing = False

    monkeypatch.setattr("src.core.connection_settings.get_idle_timeout_sec", lambda: 300)

    widget._on_idle_reaper_tick()

    session.sleep.assert_called_once()
    session.disconnect.assert_not_called()
    # connection_name is preserved by sleep() (MagicMock keeps the stub value).
    assert session.connection_name == "SEDUCAO"
