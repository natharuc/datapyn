"""Tests for non-blocking SQL query cancellation."""

import time
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from PyQt6.QtCore import QThread

from src.database.database_connector import DatabaseConnector, OperationCancelled, QueryBusyError
from src.database.block_connector_pool import BlockConnectorPool
from src.core.session import Session
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
    assert widget._sql_worker is None


def test_query_busy_raises_when_lock_held():
    connector = DatabaseConnector()
    connector.engine = MagicMock()
    connector.db_type = "postgresql"
    connector._query_lock.acquire()

    try:
        with pytest.raises(QueryBusyError):
            connector.execute_query("SELECT 1")
    finally:
        connector._query_lock.release()


def test_sql_thread_terminated_does_not_clear_new_worker(qtbot, monkeypatch):
    """Stale thread finished after re-run must not wipe the active worker."""
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    session.unregister_thread = MagicMock()

    widget = SessionWidget(session)
    qtbot.addWidget(widget)

    old_thread = QThread()
    new_thread = QThread()
    new_worker = SessionSqlWorker(MagicMock(), "SELECT 2")

    widget._sql_thread = new_thread
    widget._sql_worker = new_worker

    with patch.object(widget, "sender", return_value=old_thread):
        widget._on_sql_thread_terminated()

    assert widget._sql_thread is new_thread
    assert widget._sql_worker is new_worker


def test_cancel_clears_sql_slot_refs(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    session.finish_execution = MagicMock()
    session.register_thread = MagicMock()
    session.unregister_thread = MagicMock()

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    widget.append_output = MagicMock()
    widget._show_output = MagicMock()

    thread = MagicMock()
    thread.isRunning.return_value = True
    worker = SessionSqlWorker(MagicMock(), "SELECT 1")
    widget._sql_thread = thread
    widget._sql_worker = worker

    with patch.object(widget, "_orphan_background_thread") as orphan:
        with patch.object(widget, "_request_sql_cancel_interrupt"):
            widget._on_cancel_execution()

    assert widget._sql_thread is None
    assert widget._sql_worker is None
    orphan.assert_called_once_with(thread, worker)


def test_cancel_defers_finish_until_query_lock_released(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    session.finish_execution = MagicMock()
    session.register_thread = MagicMock()
    session.unregister_thread = MagicMock()

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    widget.append_output = MagicMock()
    widget._show_output = MagicMock()

    connector = MagicMock()
    worker = SessionSqlWorker(connector, "SELECT 1")
    thread = MagicMock()
    thread.isRunning.return_value = True
    widget._sql_worker = worker
    widget._sql_thread = thread

    with patch.object(widget, "_release_sql_slot"):
        with patch.object(widget, "_request_sql_cancel_interrupt"):
            widget._on_cancel_execution()

    assert widget._sql_stopping is True
    session.finish_execution.assert_not_called()

    thread.isRunning.return_value = False
    widget._schedule_sql_stop_finalize()
    session.finish_execution.assert_called_once()


def test_is_execution_busy_while_sql_stopping(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget._sql_stopping = True

    assert widget.is_execution_busy() is True


def test_busy_sql_queues_rerun_instead_of_error(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    session.connection_name = "c1"

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    widget.editor.get_current_executing_block.return_value = None
    widget.editor.get_focused_block.return_value = None
    widget.editor.get_last_focused_block.return_value = None
    widget.append_output = MagicMock()
    widget._detach_stale_sql_thread = MagicMock()
    widget._schedule_sql_stop_finalize = MagicMock()

    connector = MagicMock()
    connector.is_query_busy.return_value = True

    widget._execute_sql_with_connector(
        connector,
        "SELECT 2",
        "block2",
        "c1",
        None,
    )

    assert len(widget._execution_queue) == 1
    assert widget._execution_queue[0][1] == "SELECT 2"
    assert widget._sql_stopping is True
    widget.append_output.assert_not_called()
    widget._schedule_sql_stop_finalize.assert_called_once()


def test_execution_blocked_while_sql_cancelling(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget._sql_stopping = True
    widget._sql_stop_is_cancel = True
    widget.status_changed = MagicMock()

    assert widget._reject_if_cancelling_sql() is True
    widget.status_changed.emit.assert_called_once()

    widget._on_execute_queue([("sql", "SELECT 1", None, None, None, None, None)])
    assert widget._execution_queue == []


def test_tab_spinner_clockwise_and_counter_clockwise(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    from src.ui.components.session_tabs import SessionTabs

    tabs = SessionTabs()
    qtbot.addWidget(tabs)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    widget = SessionWidget(session)
    qtbot.addWidget(widget)

    tabs.addTab(widget, "Tab 1")
    tabs.set_tab_running(0, True)
    assert tabs._running_widgets[id(widget)] == "running"

    angle_cw_before = tabs._spinner_angle_cw
    tabs._tick_spinner()
    assert tabs._spinner_angle_cw == (angle_cw_before - 30) % 360

    tabs.set_tab_cancelling(0, True)
    assert tabs._running_widgets[id(widget)] == "cancelling"

    angle_ccw_before = tabs._spinner_angle_ccw
    tabs._tick_spinner()
    assert tabs._spinner_angle_ccw == (angle_ccw_before + 30) % 360


def test_generic_execute_sets_active_raw_conn_and_cursor():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector.engine = MagicMock()

    raw_conn = MagicMock()
    cursor = MagicMock()
    cursor.description = [("value",)]
    cursor.fetchmany.side_effect = [[(1,)], []]
    raw_conn.cursor.return_value = cursor
    connector.engine.raw_connection.return_value = raw_conn

    connector._execute_generic_query("SELECT 1")

    raw_conn.cursor.assert_called_once()
    raw_conn.close.assert_called_once()
    assert connector._active_raw_conn is None
    assert connector._active_cursor is None


def test_generic_execute_raises_operation_cancelled_when_flag_set():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector.engine = MagicMock()

    raw_conn = MagicMock()
    cursor = MagicMock()

    def _mark_cancelled(*_args, **_kwargs):
        connector._cancelled = True

    cursor.execute.side_effect = _mark_cancelled
    raw_conn.cursor.return_value = cursor
    connector.engine.raw_connection.return_value = raw_conn

    with pytest.raises(OperationCancelled):
        connector._execute_generic_query("SELECT 1")


def test_interrupt_query_postgresql_uses_active_raw_conn_cancel():
    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    raw_conn = MagicMock()
    connector._active_raw_conn = raw_conn

    connector.interrupt_query()

    raw_conn.cancel.assert_called_once()


def test_interrupt_query_mysql_kill_query_fallback():
    connector = DatabaseConnector()
    connector.db_type = "mysql"
    connector._active_mysql_thread_id = 42

    admin = MagicMock()
    admin_raw = MagicMock()
    admin_cursor = MagicMock()
    admin_raw.cursor.return_value = admin_cursor

    with patch.object(connector, "_spawn_admin_connection", return_value=(admin, admin_raw)):
        connector.interrupt_query()

    admin_cursor.execute.assert_called_once_with("KILL QUERY 42")
    admin_raw.close.assert_called_once()
    admin.disconnect.assert_called_once()


def test_interrupt_query_mysql_kill_access_denied_silent(caplog):
    connector = DatabaseConnector()
    connector.db_type = "mariadb"
    connector._active_mysql_thread_id = 7

    with patch.object(
        connector,
        "_spawn_admin_connection",
        side_effect=Exception("Access denied for user"),
    ):
        with caplog.at_level("DEBUG"):
            connector.interrupt_query()

    assert not any(record.levelname == "WARNING" for record in caplog.records)


def test_execute_query_rejects_abandoned_connection():
    connector = DatabaseConnector()
    connector.engine = MagicMock()
    connector._abandoned = True

    with pytest.raises(QueryBusyError, match="blocked after a query failed to cancel"):
        connector.execute_query("SELECT 1")


def test_force_disconnect_disposes_engine():
    connector = DatabaseConnector()
    engine = MagicMock()
    connector.engine = engine
    connector._abandoned = True

    connector.force_disconnect()

    engine.dispose.assert_called_once()
    assert connector.engine is None
    assert connector._abandoned is False


def test_block_connector_pool_does_not_reuse_abandoned_connector():
    pool = BlockConnectorPool()
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector._abandoned = True
    pool.register("block-1", "", "conn-1", connector)

    assert pool.peek_connected("block-1", "", "conn-1") is None


def test_block_connector_pool_reconnects_after_abandoned_connector():
    pool = BlockConnectorPool()
    abandoned = MagicMock()
    abandoned.is_connected.return_value = True
    abandoned._abandoned = True
    replacement = MagicMock()
    replacement.is_connected.return_value = True
    pool.register("block-1", "", "conn-1", abandoned)

    with patch(
        "src.database.block_connector_pool.connect_connector_from_config",
        return_value=replacement,
    ) as connect:
        result = pool.get(
            "block-1",
            "",
            "conn-1",
            {"db_type": "sqlite", "host": "", "port": 0, "database": ""},
        )

    assert result is replacement
    connect.assert_called_once()


def test_session_is_not_connected_when_connector_is_abandoned(qapp):
    session = Session("session-1")
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector._abandoned = True
    session._connector = connector

    assert session.is_connected is False


def test_auto_connect_finished_updates_session_connector(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.connection_name = "conn-1"
    session.connection_group = ""
    session.blocks = []
    session.code = ""
    session.set_connection = MagicMock()

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    widget._execute_sql_with_connector = MagicMock()

    connector = MagicMock()
    connector.is_connected.return_value = True

    widget._on_auto_connect_finished(
        connector,
        "",
        "SELECT 1",
        None,
        None,
        None,
        None,
        None,
    )

    session.set_connection.assert_called_once_with("conn-1", connector, "")
    widget._execute_sql_with_connector.assert_called_once()


def test_cancel_timeout_discards_connector_until_thread_finishes(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""

    widget = SessionWidget(session)
    qtbot.addWidget(widget)
    widget.editor = MagicMock()
    block = MagicMock()
    block.get_block_key.return_value = "block-1"
    widget._current_execution_block = block

    connector = MagicMock()
    connector.is_connected.return_value = True
    worker = SessionSqlWorker(connector, "SELECT 1")
    thread = MagicMock()
    thread.isRunning.return_value = True
    widget._block_connector_pool.register("block-1", "", "conn-1", connector)
    widget._sql_stopping = True
    widget._sql_stopping_thread = thread
    widget._sql_stopping_worker = worker
    widget._sql_stopping_connector = connector
    widget._sql_stopping_block_key = "block-1"
    widget._sql_stop_started_at = time.time() - 1.0
    widget._SQL_STOP_TIMEOUT_SEC = 0.0

    with patch.object(widget, "_finalize_sql_stop") as finalize:
        widget._schedule_sql_stop_finalize()

    assert connector._abandoned is True
    assert widget._block_connector_pool.peek_connected("block-1", "", "conn-1") is None
    connector.force_disconnect.assert_not_called()
    finalize.assert_called_once()

    cleanup_callback = thread.finished.connect.call_args.args[0]
    cleanup_callback()
    connector.force_disconnect.assert_called_once()


def test_lock_not_released_while_thread_alive_after_cancel(qtbot, monkeypatch):
    monkeypatch.setattr(SessionWidget, "_setup_ui", lambda self: None)
    monkeypatch.setattr(SessionWidget, "_connect_signals", lambda self: None)

    session = MagicMock()
    session.session_id = "s1"
    session.blocks = []
    session.code = ""
    session.finish_execution = MagicMock()

    widget = SessionWidget(session)
    qtbot.addWidget(widget)

    connector = DatabaseConnector()
    connector._query_lock.acquire()
    thread = MagicMock()
    thread.isRunning.return_value = True

    widget._sql_stopping = True
    widget._sql_stopping_thread = thread
    widget._sql_stopping_connector = connector
    widget._sql_stop_started_at = time.time() - 1.0
    widget._SQL_STOP_TIMEOUT_SEC = 0.0

    with patch.object(widget, "_force_release_stopping_query_lock") as force_release:
        with patch.object(widget, "_finalize_sql_stop") as finalize:
            widget._schedule_sql_stop_finalize()

    assert connector._abandoned is True
    force_release.assert_not_called()
    finalize.assert_called_once()
