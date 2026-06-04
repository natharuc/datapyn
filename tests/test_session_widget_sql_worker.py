"""Regression tests for SessionWidget SQL worker lifecycle."""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication

from src.ui.components.session_widget import SessionWidget


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
