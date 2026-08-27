"""Pynia tools must reuse the live tab session instead of reconnecting."""

from unittest.mock import MagicMock

from src.services.copilot.mcp_tools import MCPToolRegistry, _find_session_widget
from src.services.pynia.tools.dispatch import PyniaToolDispatcher


class _Shape:
    shape = (10, 3)


def _live_registry(connection_name="ESIM"):
    connector = MagicMock()
    connector.is_connected = True
    connector.execute_query = MagicMock(return_value="ok-rows")

    session = MagicMock()
    session.session_id = "tab-1"
    session.connection_name = connection_name
    session.connection_group = ""
    session.is_connected = True
    session.connector = connector
    session.namespace = {"df": _Shape(), "_skip": 1}

    widget = MagicMock()
    widget.session = session
    widget.connect_to_database = MagicMock()
    widget.namespace = session.namespace

    mw = MagicMock()
    mw._session_widgets = {"tab-1": widget}
    mw.session_tabs = None
    mw._connect_new_tab = MagicMock()
    mw.connection_manager = MagicMock()
    mw.connection_manager.connections = {}
    mw.connection_manager.get_connection.return_value = None
    mw.connection_manager.get_connection_config.return_value = {
        "db_type": "sqlserver",
        "host": "h",
        "database": "ESIM",
    }
    mw.connection_manager.saved_configs = {
        "connections": {
            "": {
                "ESIM": {"db_type": "sqlserver", "host": "h", "database": "ESIM"},
            }
        }
    }

    registry = MCPToolRegistry.__new__(MCPToolRegistry)
    registry._main_window = mw
    registry._pinned_session_id = "tab-1"
    return registry, mw, widget, session, connector


def test_get_connector_uses_session_when_manager_pool_is_empty():
    registry, mw, _widget, _session, connector = _live_registry()
    got, err = registry._get_connector()
    assert err is None
    assert got is connector
    mw.connection_manager.get_connection.assert_not_called()


def test_get_connector_does_not_construct_throwaway_manager():
    from unittest.mock import patch

    registry, _mw, _widget, _session, connector = _live_registry()
    with patch("src.database.ConnectionManager") as ctor:
        got, err = registry._get_connector("ESIM")
    assert err is None
    assert got is connector
    ctor.assert_not_called()


def test_silent_query_runs_on_tab_connector():
    registry, _mw, _widget, _session, connector = _live_registry()
    result = registry._run_silent_query({"query": "SELECT 1"})
    assert "error" not in result
    connector.execute_query.assert_called_once_with("SELECT 1")


def test_get_connector_refuses_other_name_while_tab_is_connected():
    registry, _mw, _widget, _session, _connector = _live_registry()
    got, err = registry._get_connector("OTHER")
    assert got is None
    assert "connected to 'ESIM'" in err
    assert "switch" in err.lower()


def test_connect_is_noop_when_already_connected():
    registry, _mw, widget, _session, _connector = _live_registry()
    result = registry._connect_database({"connection_name": "ESIM"})
    text = result["content"][0]["text"]
    assert "Already connected" in text
    assert "datapyn_query" in text
    widget.connect_to_database.assert_not_called()


def test_open_is_noop_when_already_connected_and_does_not_create_tab():
    registry, mw, widget, _session, _connector = _live_registry()
    result = registry._open_connection({"connection_name": "ESIM"})
    text = result["content"][0]["text"]
    assert "Already connected" in text
    widget.connect_to_database.assert_not_called()
    mw._connect_new_tab.assert_not_called()


def test_open_does_not_create_tab_when_connected_to_another_name():
    registry, mw, widget, _session, _connector = _live_registry()
    result = registry._open_connection({"connection_name": "OTHER"})
    text = result["content"][0]["text"]
    assert "already connected to 'ESIM'" in text
    assert "switch" in text.lower()
    widget.connect_to_database.assert_not_called()
    mw._connect_new_tab.assert_not_called()


def test_open_connects_current_tab_when_not_connected():
    registry, mw, widget, session, _connector = _live_registry()
    session.is_connected = False
    result = registry._open_connection({"connection_name": "ESIM"})
    widget.connect_to_database.assert_called_once()
    mw._connect_new_tab.assert_not_called()
    assert "Connecting this tab" in result["content"][0]["text"]


def test_list_connections_nested_and_marks_active():
    registry, _mw, _widget, _session, _connector = _live_registry()
    result = registry._list_connections({})
    text = result["content"][0]["text"]
    assert "ACTIVE on this tab: ESIM (connected=true)" in text
    assert "Do not call operation=connect or open" in text
    assert "ESIM (sqlserver): h/ESIM" in text


def test_dispatch_connect_maps_to_legacy_connect_database():
    legacy = MagicMock()
    legacy.execute.return_value = {"content": [{"type": "text", "text": "ok"}]}
    legacy._get_block_editor.return_value = None
    dispatcher = PyniaToolDispatcher(legacy)
    dispatcher.dispatch("datapyn_database", {"operation": "open", "connection_name": "ESIM"})
    legacy.execute.assert_called_with("open_connection", {"connection_name": "ESIM"})


def test_pin_finds_widget_by_session_id_when_dict_key_misses():
    widget = MagicMock()
    session = MagicMock()
    session.session_id = "tab-1"
    widget.session = session
    mw = MagicMock()
    mw._session_widgets = {"other-key": widget}
    mw.session_tabs = None

    assert _find_session_widget(mw, "tab-1") is widget

    registry = MCPToolRegistry.__new__(MCPToolRegistry)
    registry._main_window = mw
    registry._pinned_session_id = "tab-1"
    assert registry._get_active_session_widget() is widget
