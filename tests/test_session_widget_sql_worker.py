"""Regression tests for SessionWidget SQL worker lifecycle."""

import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QWidget

from src.ui.components.session_widget import SessionWidget, SessionSqlWorker
from src.ui.main_window._sessions import SessionsMixin


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _session_stub():
    session = MagicMock()
    session.session_id = "test-session"
    session.is_connected = True
    session.connection_name = "conn"
    session.connector = MagicMock()
    session.blocks = []
    session.code = ""
    session.namespace = {}
    session.database_context = ""
    session.notification_config = None
    session.register_thread = MagicMock()
    session.unregister_thread = MagicMock()
    session.start_execution = MagicMock()
    session.finish_execution = MagicMock()
    session.set_variable = MagicMock()
    return session


def _widget_without_ui(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)
    widget = SessionWidget(_session_stub())
    qtbot.addWidget(widget)
    return widget


def test_sql_worker_initialized_to_none(qtbot, monkeypatch):
    widget = _widget_without_ui(qtbot, monkeypatch)
    assert widget._sql_worker is None


def test_disconnect_previous_sql_worker_when_never_started(qtbot, monkeypatch):
    """Path after async database switch: no prior worker must not raise."""
    widget = _widget_without_ui(qtbot, monkeypatch)
    widget._disconnect_previous_sql_worker()
    assert widget._sql_worker is None


def test_sql_worker_guard_uses_getattr_not_direct_access():
    """Direct access raised AttributeError before __init__ set _sql_worker."""
    bare = object()
    assert getattr(bare, "_sql_worker", None) is None
    with pytest.raises(AttributeError):
        _ = bare._sql_worker  # noqa: B018


class _ThreadHost(QWidget, SessionsMixin):
  """Minimal MainWindow stand-in for background-thread adoption tests."""


class _BlockingConnector:
    db_type = "mssql"

    def __init__(self):
        self._release = threading.Event()

    def execute_query(self, query, parameters=None):
        self._release.wait(timeout=30)
        return None

    def release(self):
        self._release.set()


def test_cleanup_orphans_sql_thread_without_destroy_while_running(qtbot, monkeypatch):
    """Closing a tab while SQL runs must not destroy the QThread object."""
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    host = _ThreadHost()
    qtbot.addWidget(host)

    widget = SessionWidget(_session_stub())
    host.setFixedSize(200, 200)
    widget.setParent(host)
    qtbot.addWidget(widget)

    thread = QThread()
    connector = _BlockingConnector()
    worker = SessionSqlWorker(connector, "SELECT 1")
    worker.moveToThread(thread)
    widget._sql_thread = thread
    widget._sql_worker = worker
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    widget._register_background_thread(thread, worker)
    thread.start()

    qtbot.waitUntil(lambda: thread.isRunning(), timeout=2000)

    from PyQt6 import sip

    widget.cleanup()
    QApplication.processEvents()

    assert not sip.isdeleted(thread)
    assert thread.isRunning() or id(thread) in getattr(host, "_adopted_connection_threads", {})

    connector.release()
    stop_qthread = __import__(
        "src.utils.qt_threading", fromlist=["stop_qthread"]
    ).stop_qthread
    stop_qthread(thread, worker, wait_ms=5000, force_terminate=True)
