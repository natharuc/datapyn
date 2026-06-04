from types import SimpleNamespace
from unittest.mock import MagicMock

from src.database.database_connector import DatabaseConnector
from src.services.schema_service import SchemaService
from src.ui.main_window._execution import ExecutionMixin
from src.ui.main_window._schema import SchemaMixin
from src.ui.main_window._sessions import SessionsMixin


class _DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message: str, timeout: int = 0):
        self.messages.append((message, timeout))


class _DummyDock:
    def __init__(self):
        self.show_calls = 0

    def show(self):
        self.show_calls += 1


class _DummyConnectionManager:
    def get_connection_config(self, connection_name: str):
        if connection_name == "Conn":
            return {"db_type": "sqlserver"}
        return None


class _DummyEditor:
    def __init__(self):
        self.set_sql_schema = MagicMock()
        self.set_database_context = MagicMock()
        self._sql_schema = {"database": "old"}
        self._blocks = []

    def get_blocks(self):
        return list(self._blocks)


class _DummyBlock:
    def __init__(self, connection_name=None, language="sql"):
        self._connection_name = connection_name
        self._language = language
        self.set_sql_schema = MagicMock()
        self.db_panel = MagicMock()
        self._database_name = ""

    def get_connection_name(self):
        return self._connection_name

    def get_language(self):
        return self._language


class _DummyWidget:
    def __init__(self, session_id: str, connection_name: str):
        self.session = SimpleNamespace(session_id=session_id, connection_name=connection_name)
        self.editor = _DummyEditor()
        self.connection_changed = SimpleNamespace(emit=MagicMock())


class _DummyConnectionListItem:
    def __init__(self, connection_name: str):
        self._connection_name = connection_name

    def data(self, _role):
        return self._connection_name


class _DummyConnectionsList:
    def __init__(self, connection_names: list[str]):
        self._items = [_DummyConnectionListItem(connection_name) for connection_name in connection_names]
        self.selected_item = None

    def count(self):
        return len(self._items)

    def item(self, index: int):
        return self._items[index]

    def setCurrentItem(self, item):
        self.selected_item = item


class _DummySessionTabs:
    def __init__(self, widgets: list):
        self._widgets = list(widgets)
        self.colors = []

    def count(self):
        return len(self._widgets)

    def widget(self, index: int):
        return self._widgets[index]

    def set_tab_connection_color(self, index: int, color: str):
        self.colors.append((index, color))


class _DummySessionMainWindow(SchemaMixin, SessionsMixin):
    def __init__(self, widget, focused_session, explorer=None):
        self.connection_manager = _DummyConnectionManager()
        self._session_widgets = {widget.session.session_id: widget}
        self._session_explorers = {widget.session.session_id: explorer or MagicMock()}
        self.object_explorer_dock = _DummyDock()
        self._status_bar = _DummyStatusBar()
        self.connection_panel = MagicMock()
        self.connections_list = _DummyConnectionsList([focused_session.connection_name])
        self.action_label = MagicMock()
        self.session_manager = SimpleNamespace(focused_session=focused_session)
        self.session_tabs = _DummySessionTabs([widget])
        self._schema_service = MagicMock()
        self._load_schema_with_loading = MagicMock()

    def _log_info(self, _message: str):
        return None

    def statusBar(self):
        return self._status_bar

    def _get_current_session_widget(self):
        return next(iter(self._session_widgets.values()))


class _DummyExecutionMainWindow(ExecutionMixin):
    def __init__(self, session, widget):
        self.session_manager = SimpleNamespace(focused_session=session)
        self._schema_service = MagicMock()
        self._start_execution_timer = MagicMock()
        self._stop_execution_timer = MagicMock()
        self._update_connection_status = MagicMock()
        self._clear_sql_autocomplete_for_connection = MagicMock()
        self._get_current_session_widget = MagicMock(return_value=widget)
        self._log_info = MagicMock()
        self._show_warning = MagicMock()
        self.action_label = MagicMock()

    def _start_database_switch_worker(self, connector, database_name, *, on_success, on_error=None):
        connector.change_database(database_name)
        on_success(database_name)


class _DummyMainWindow(SchemaMixin):
    def __init__(self, widget, explorer):
        self.connection_manager = _DummyConnectionManager()
        self._session_widgets = {widget.session.session_id: widget}
        self._session_explorers = {widget.session.session_id: explorer}
        self.object_explorer_dock = _DummyDock()
        self._status_bar = _DummyStatusBar()
        self._schema_service = MagicMock()
        self.switched_sessions = []

    def _log_info(self, _message: str):
        return None

    def statusBar(self):
        return self._status_bar

    def _build_schema_context(self, schema: dict, connection_name: str):
        return f"{connection_name}:{schema.get('database', '')}"

    def _get_session_explorer(self, session_id: str):
        return self._session_explorers[session_id]

    def _get_current_session_widget(self):
        return next(iter(self._session_widgets.values()))

    def _switch_session_explorer(self, session_id: str):
        self.switched_sessions.append(session_id)


def test_invalidate_cache_by_connection_clears_all_session_entries(qapp):
    service = SchemaService()
    service._cache = {
        "sid-1:Conn": {"database": "db1"},
        "sid-2:Conn": {"database": "db2"},
        "sid-1:Other": {"database": "other"},
        "Conn": {"database": "legacy"},
    }

    service.invalidate_cache("Conn")

    assert "sid-1:Conn" not in service._cache
    assert "sid-2:Conn" not in service._cache
    assert "Conn" not in service._cache
    assert service._cache["sid-1:Other"] == {"database": "other"}


def test_on_schema_loaded_updates_requesting_explorer_from_explicit_session_id(qapp, qtbot):
    schema = {"database": "db2", "tables": [{"name": "venda", "schema": "dbo"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    main_window._on_schema_loaded(schema, "Conn", session_id="sid-1")

    qtbot.waitUntil(lambda: widget.editor.set_sql_schema.call_count > 0, timeout=5000)
    widget.editor.set_sql_schema.assert_called_once_with(schema)
    widget.editor.set_database_context.assert_called_once_with("Conn:db2")
    explorer.set_schema.assert_called_once_with(schema, "Conn", db_type="sqlserver")
    assert main_window.switched_sessions == ["sid-1"]
    assert main_window.object_explorer_dock.show_calls == 1


def test_on_schema_loaded_falls_back_to_pending_session_for_explorer_update(qapp):
    schema = {"database": "db2", "tables": [{"name": "venda", "schema": "dbo"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    main_window._pending_schema_sessions = {"Conn": "sid-1"}

    main_window._on_schema_loaded(schema, "Conn", session_id="")

    explorer.set_schema.assert_called_once_with(schema, "Conn", db_type="sqlserver")
    assert "Conn" not in main_window._pending_schema_sessions


def test_clear_sql_autocomplete_for_session_connection_resets_only_matching_blocks(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    session_block = _DummyBlock(connection_name=None)
    other_connection_block = _DummyBlock(connection_name="Other")
    widget.editor._blocks = [session_block, other_connection_block]

    main_window._clear_sql_autocomplete_for_connection(widget, "Conn")

    assert widget.editor._sql_schema == {}
    widget.editor.set_database_context.assert_called_once_with("")
    session_block.set_sql_schema.assert_called_once_with({})
    other_connection_block.set_sql_schema.assert_not_called()


def test_clear_sql_autocomplete_for_block_connection_only_resets_matching_block(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    session_block = _DummyBlock(connection_name=None)
    target_block = _DummyBlock(connection_name="BlockConn")
    other_block = _DummyBlock(connection_name="Other")
    widget.editor._blocks = [session_block, target_block, other_block]

    main_window._clear_sql_autocomplete_for_connection(widget, "BlockConn")

    assert widget.editor._sql_schema == {"database": "old"}
    widget.editor.set_database_context.assert_not_called()
    session_block.set_sql_schema.assert_not_called()
    target_block.set_sql_schema.assert_called_once_with({})
    other_block.set_sql_schema.assert_not_called()


def test_on_schema_loaded_clears_stale_pending_object_explorer_requests(qapp):
    schema = {"database": "db2", "tables": [{"name": "venda", "schema": "dbo"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    main_window._pending_oe_schema_requests = {"catalog-old": "sid-1", "catalog-keep": "sid-2"}
    main_window._pending_oe_table_requests = {("gecon", "dbo"): "sid-1", ("other", "dbo"): "sid-2"}
    main_window._pending_oe_column_requests = {
        ("gecon", "dbo", "pessoa"): "sid-1",
        ("other", "dbo", "venda"): "sid-2",
    }

    main_window._on_schema_loaded(schema, "Conn", session_id="sid-1")

    assert main_window._pending_oe_schema_requests == {"catalog-keep": "sid-2"}
    assert main_window._pending_oe_table_requests == {("other", "dbo"): "sid-2"}
    assert main_window._pending_oe_column_requests == {("other", "dbo", "venda"): "sid-2"}


def test_on_tables_loaded_ignores_stale_result_without_pending_request(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    main_window._on_tables_loaded("gecon", "dbo", [{"name": "pessoa"}])

    explorer.add_tables_to_schema.assert_not_called()


def test_on_columns_loaded_ignores_stale_result_without_pending_request(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    main_window._on_columns_loaded("gecon", "dbo", "pessoa", [{"name": "id"}])

    explorer.add_columns_to_table.assert_not_called()


def test_on_tables_loaded_routes_only_matching_pending_request(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    main_window._pending_oe_table_requests = {("controleproducao", "dbo"): "sid-1"}

    main_window._on_tables_loaded("controleproducao", "dbo", [{"name": "venda"}])

    explorer.add_tables_to_schema.assert_called_once_with(
        "controleproducao", "dbo", [{"name": "venda"}]
    )
    assert main_window._pending_oe_table_requests == {}


def test_on_session_connection_changed_clears_autocomplete_before_schema_reload(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    connector = DatabaseConnector()
    connector.db_type = "sqlserver"
    connector.is_connected = MagicMock(return_value=True)
    focused_session = widget.session
    focused_session.connector = connector
    focused_session.database_context = ""
    session_block = _DummyBlock(connection_name=None)
    widget.editor._blocks = [session_block]
    main_window = _DummySessionMainWindow(widget, focused_session)

    main_window._on_session_connection_changed(focused_session, "Conn", "newdb")

    assert widget.editor._sql_schema == {}
    widget.editor.set_database_context.assert_called_once_with("")
    session_block.set_sql_schema.assert_called_once_with({})
    main_window._schema_service.invalidate_cache.assert_called_once_with("Conn", session_id="sid-1")
    main_window._load_schema_with_loading.assert_called_once_with(connector, "Conn", session_id="sid-1")
    session_block.db_panel.set_database.assert_called_once_with("newdb")


def test_on_session_connection_changed_ignores_unfocused_session(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    connector = DatabaseConnector()
    connector.db_type = "sqlserver"
    connector.is_connected = MagicMock(return_value=True)
    session = widget.session
    session.connector = connector
    other_session = SimpleNamespace(session_id="sid-2", connection_name="Conn")
    main_window = _DummySessionMainWindow(widget, other_session)

    main_window._on_session_connection_changed(session, "Conn", "newdb")

    widget.editor.set_database_context.assert_not_called()
    main_window._schema_service.invalidate_cache.assert_not_called()
    main_window._load_schema_with_loading.assert_not_called()


def test_execute_sql_use_command_clears_autocomplete_before_emitting_change(qapp):
    connector = MagicMock()
    connector.db_type = "sqlserver"
    session = SimpleNamespace(
        is_connected=True,
        connector=connector,
        connection_name="Conn",
        session_id="sid-1",
        database_context="",
    )
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyExecutionMainWindow(session, widget)

    from unittest.mock import patch

    with patch("src.ui.main_window._execution.get_connector_database_context", return_value="newdb"):
        main_window._execute_sql("USE newdb")

    connector.change_database.assert_called_once_with("newdb")
    main_window._clear_sql_autocomplete_for_connection.assert_called_once_with(widget, "Conn")
    main_window._schema_service.invalidate_cache.assert_called_once_with("Conn", session_id="sid-1")
    widget.connection_changed.emit.assert_called_once_with("Conn", "newdb")


def test_editor_schema_for_session_drops_unreferenced_cross_database_tables(qapp):
    from src.services.cross_database_schema import prepare_editor_sql_schema

    schema = {
        "database": "db2",
        "db_type": "sqlserver",
        "tables": [
            {"name": "current_users", "schema": "dbo", "database": "db2", "key": "db2.dbo.current_users"},
            {"name": "legacy_orders", "schema": "dbo", "database": "db1", "key": "db1.dbo.legacy_orders"},
        ],
        "columns": {
            "db2.dbo.current_users": [{"name": "id", "type": "int"}],
            "dbo.current_users": [{"name": "id", "type": "int"}],
            "db2.current_users": [{"name": "id", "type": "int"}],
            "current_users": [{"name": "id", "type": "int"}],
            "db1.dbo.legacy_orders": [{"name": "legacy_id", "type": "int"}],
            "db1.legacy_orders": [{"name": "legacy_id", "type": "int"}],
            "legacy_orders": [{"name": "legacy_id", "type": "int"}],
        },
    }

    filtered = prepare_editor_sql_schema(
        schema,
        db_type="sqlserver",
        referenced_catalogs=set(),
    )

    assert [table["name"] for table in filtered["tables"]] == ["current_users"]
    assert set(filtered["columns"].keys()) == {
        "db2.dbo.current_users",
        "dbo.current_users",
        "db2.current_users",
        "current_users",
    }


def test_prepare_editor_sql_schema_keeps_unscoped_schema_unchanged(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    schema = {
        "database": "db2",
        "db_type": "sqlserver",
        "tables": [
            {"name": "users", "schema": "dbo", "key": "dbo.users"},
        ],
        "columns": {
            "dbo.users": [{"name": "id", "type": "int"}],
            "users": [{"name": "id", "type": "int"}],
        },
    }

    from src.services.cross_database_schema import prepare_editor_sql_schema

    filtered = prepare_editor_sql_schema(schema, db_type="sqlserver", referenced_catalogs=set())

    assert filtered is schema


def test_object_explorer_schema_changed_keeps_lazy_loaded_cross_database_tables(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    explorer._current_connection = "Conn"
    explorer._db_type = "sqlserver"
    main_window = _DummyMainWindow(widget, explorer)

    schema = {
        "database": "db2",
        "db_type": "sqlserver",
        "tables": [
            {"name": "current_users", "schema": "dbo", "database": "db2", "key": "db2.dbo.current_users"},
            {"name": "legacy_orders", "schema": "dbo", "database": "db1", "key": "db1.dbo.legacy_orders"},
        ],
        "columns": {
            "db2.dbo.current_users": [{"name": "id", "type": "int"}],
            "db1.dbo.legacy_orders": [{"name": "legacy_id", "type": "int"}],
        },
    }

    main_window._on_object_explorer_schema_changed("sid-1", schema)

    cached_schema = main_window._schema_service.update_cached_schema.call_args.args[1]
    assert {table["name"] for table in cached_schema["tables"]} == {"current_users", "legacy_orders"}
    widget.editor.set_sql_schema.assert_called_once_with(cached_schema)
