"""Tests for non-blocking SQL query cancellation."""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.database.database_connector import DatabaseConnector
from src.ui.components.session_widget import SessionSqlWorker, SessionWidget


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_request_cancel_sets_flag_only():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector._active_raw_conn = MagicMock()

    connector.request_cancel()

    assert connector._cancelled is True
    connector._active_raw_conn.cancel.assert_not_called()


def test_interrupt_query_calls_driver_not_flag():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    raw_conn = MagicMock()
    connector._active_raw_conn = raw_conn
    connector._cancelled = False

    connector.interrupt_query()

    raw_conn.cancel.assert_called_once()
    assert connector._cancelled is False


def test_cancel_query_sets_flag_and_interrupts():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    raw_conn = MagicMock()
    connector._active_raw_conn = raw_conn

    connector.cancel_query()

    assert connector._cancelled is True
    raw_conn.cancel.assert_called_once()


def test_session_sql_worker_interrupt_delegates_to_connector():
    connector = MagicMock()
    worker = SessionSqlWorker(connector, "SELECT 1")

    worker.interrupt_query()

    connector.interrupt_query.assert_called_once()


def test_request_sql_cancel_interrupt_queues_worker_slot(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.is_connected = True
    session.connection_name = "c1"
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

    widget = SessionWidget(session)
    qtbot.addWidget(widget)

    connector = MagicMock()
    worker = SessionSqlWorker(connector, "SELECT 1")
    thread = MagicMock()
    thread.isRunning.return_value = True

    widget._sql_thread = thread
    widget._sql_worker = worker

    with patch(
        "src.ui.components.session_widget.QMetaObject.invokeMethod",
    ) as invoke_method:
        widget._request_sql_cancel_interrupt()

    connector.request_cancel.assert_called_once()
    invoke_method.assert_called_once_with(
        worker,
        "interrupt_query",
        Qt.ConnectionType.QueuedConnection,
    )


def test_on_cancel_execution_does_not_call_cancel_query_on_main_thread(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.is_connected = True
    session.connection_name = "c1"
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

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    widget.append_output = MagicMock()
    widget._show_output = MagicMock()

    thread = MagicMock()
    thread.isRunning.return_value = True
    widget._sql_thread = thread
    widget._sql_worker = SessionSqlWorker(MagicMock(), "SELECT 1")

    with patch.object(widget, "_request_sql_cancel_interrupt") as request_cancel:
        widget._on_cancel_execution()

    request_cancel.assert_called_once()
    widget._sql_worker.connector.cancel_query.assert_not_called()
