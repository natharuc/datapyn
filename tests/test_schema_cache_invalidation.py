from types import SimpleNamespace
from unittest.mock import MagicMock

from src.database.block_connector_pool import BlockConnectorPool
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
    def get_connection_config(self, group: str, name: str = ""):
        """Match ConnectionManager: legacy single-name lookup when name is omitted."""
        if not name:
            name = group
            group = ""
        if name == "Conn":
            return {"db_type": "sqlserver", "group": group}
        return None


class _DummyEditor:
    def __init__(self):
        self._sql_schema = {"database": "old"}
        self._database_context = ""
        self._blocks = []
        self.set_sql_schema = MagicMock(side_effect=self._store_sql_schema)
        self.set_database_context = MagicMock(side_effect=self._store_database_context)

    def _store_sql_schema(self, schema):
        self._sql_schema = schema or {}

    def _store_database_context(self, context):
        self._database_context = context or ""

    def get_blocks(self):
        return list(self._blocks)


class _DummyBlock:
    def __init__(self, connection_name=None, language="sql"):
        self._connection_name = connection_name
        self._language = language
        self._sql_schema = {}
        self.set_sql_schema = MagicMock()
        self.set_database_context = MagicMock()
        self.db_panel = MagicMock()
        self._database_name = ""

    def get_connection_name(self):
        return self._connection_name

    def get_language(self):
        return self._language

    def get_sql_schema(self):
        return dict(self._sql_schema)

    def uses_tab_default_database(self) -> bool:
        return not self._database_name

    def get_database_name(self):
        return self._database_name or None


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


def test_on_schema_loaded_requires_explicit_session_id(qapp):
    schema = {"database": "db2", "tables": [{"name": "venda", "schema": "dbo"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    main_window._on_schema_loaded(schema, "Conn", session_id="")

    explorer.set_schema.assert_not_called()


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
    main_window._pending_oe_schema_requests = {
        ("sid-1", "catalog-old"): "sid-1",
        ("sid-2", "catalog-keep"): "sid-2",
    }
    main_window._pending_oe_table_requests = {
        ("sid-1", "gecon", "dbo"): "sid-1",
        ("sid-2", "other", "dbo"): "sid-2",
    }
    main_window._pending_oe_column_requests = {
        ("sid-1", "gecon", "dbo", "pessoa"): "sid-1",
        ("sid-2", "other", "dbo", "venda"): "sid-2",
    }

    main_window._on_schema_loaded(schema, "Conn", session_id="sid-1")

    assert main_window._pending_oe_schema_requests == {("sid-2", "catalog-keep"): "sid-2"}
    assert main_window._pending_oe_table_requests == {("sid-2", "other", "dbo"): "sid-2"}
    assert main_window._pending_oe_column_requests == {
        ("sid-2", "other", "dbo", "venda"): "sid-2",
    }


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
    main_window._pending_oe_table_requests = {
        ("sid-1", "controleproducao", "dbo"): "sid-1",
    }

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
    main_window._schema_service.invalidate_cache.assert_called_once_with(
        "Conn", session_id="sid-1", connection_group=""
    )
    main_window._load_schema_with_loading.assert_called_once_with(
        connector, "Conn", session_id="sid-1", connection_group=""
    )
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
    # Unfocused tabs still refresh schema cache (MCP / autocomplete), but skip UI updates.
    main_window._schema_service.invalidate_cache.assert_called_once_with(
        "Conn", session_id="sid-1", connection_group=""
    )
    main_window._load_schema_with_loading.assert_called_once_with(
        connector, "Conn", session_id="sid-1", connection_group=""
    )


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


def test_apply_loaded_schema_skips_blocks_on_other_databases(qapp):
    schema = {"database": "GECON", "tables": [{"name": "t1"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyMainWindow(widget, MagicMock())
    gecon_block = _DummyBlock()
    gecon_block._sql_schema = {"database": "GECON", "tables": []}
    esim_block = _DummyBlock()
    esim_block._sql_schema = {"database": "ESIM", "tables": [{"name": "esim_t"}]}
    widget.editor._blocks = [gecon_block, esim_block]

    main_window._apply_loaded_schema_to_blocks(
        schema, "Conn", db_type="sqlserver", requesting_sid="sid-1"
    )

    expected_schema = {**schema, "db_type": "sqlserver"}
    gecon_block.set_sql_schema.assert_called_once_with(expected_schema)
    gecon_block.set_database_context.assert_called_once_with("Conn:GECON")
    esim_block.set_sql_schema.assert_not_called()
    esim_block.set_database_context.assert_not_called()


def test_apply_loaded_schema_applies_to_blocks_without_schema(qapp):
    schema = {"database": "GECON", "tables": [{"name": "t1"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyMainWindow(widget, MagicMock())
    empty_block = _DummyBlock()
    widget.editor._blocks = [empty_block]

    main_window._apply_loaded_schema_to_blocks(
        schema, "Conn", db_type="sqlserver", requesting_sid="sid-1"
    )

    expected_schema = {**schema, "db_type": "sqlserver"}
    empty_block.set_sql_schema.assert_called_once_with(expected_schema)
    empty_block.set_database_context.assert_called_once_with("Conn:GECON")


def test_block_database_change_keeps_schema_and_invalidates_block_cache(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyMainWindow(widget, MagicMock())
    target_block = _DummyBlock()
    target_block.get_block_key = MagicMock(return_value="block-1")
    other_block = _DummyBlock()
    widget.editor._blocks = [target_block, other_block]
    main_window._switch_block_database_background = MagicMock()

    main_window._on_block_database_changed(target_block, "db_b")

    target_block.set_sql_schema.assert_not_called()
    target_block.set_database_context.assert_not_called()
    other_block.set_sql_schema.assert_not_called()
    main_window._schema_service.invalidate_cache.assert_called_once_with(
        "Conn",
        session_id="sid-1",
        block_key="block-1",
        connection_group="",
    )
    main_window._switch_block_database_background.assert_called_once()


def test_block_schema_result_from_previous_database_is_ignored(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)
    target_block = _DummyBlock()
    target_block.get_block_key = MagicMock(return_value="block-1")
    target_block._database_name = "db_b"
    widget.editor._blocks = [target_block]
    widget.editor.get_focused_block = MagicMock(return_value=target_block)

    stale_schema = {
        "database": "db_a",
        "connection_context": "db_a",
        "requested_context": "db_a",
        "tables": [{"name": "old_table"}],
        "columns": {},
    }
    main_window._on_schema_loaded(
        stale_schema,
        "Conn",
        session_id="sid-1",
        block_key="block-1",
    )

    target_block.set_sql_schema.assert_not_called()
    target_block.set_database_context.assert_not_called()


def test_block_schema_result_stays_in_originating_session(qapp):
    first_widget = _DummyWidget("sid-1", "Conn")
    second_widget = _DummyWidget("sid-2", "Conn")
    first_explorer = MagicMock()
    second_explorer = MagicMock()
    main_window = _DummyMainWindow(first_widget, first_explorer)
    main_window._session_widgets["sid-2"] = second_widget
    main_window._session_explorers["sid-2"] = second_explorer

    first_block = _DummyBlock()
    first_block.get_block_key = MagicMock(return_value="block-1")
    first_block._database_name = "db_a"
    second_block = _DummyBlock()
    second_block.get_block_key = MagicMock(return_value="block-2")
    second_block._database_name = "db_a"
    first_widget.editor._blocks = [first_block]
    second_widget.editor._blocks = [second_block]

    main_window._on_schema_loaded(
        {
            "database": "db_a",
            "connection_context": "db_a",
            "requested_context": "db_a",
            "tables": [{"name": "new_table"}],
            "columns": {},
        },
        "Conn",
        session_id="sid-1",
        block_key="block-1",
    )

    first_block.set_sql_schema.assert_called_once()
    second_block.set_sql_schema.assert_not_called()


def test_block_schema_result_ignores_closing_block(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyMainWindow(widget, MagicMock())
    closing_block = _DummyBlock()
    closing_block.get_block_key = MagicMock(return_value="block-1")
    closing_block._database_name = "db_a"
    closing_block._is_closing = True
    widget.editor._blocks = [closing_block]

    main_window._on_schema_loaded(
        {
            "database": "db_a",
            "connection_context": "db_a",
            "requested_context": "db_a",
            "tables": [{"name": "late_table"}],
            "columns": {},
        },
        "Conn",
        session_id="sid-1",
        block_key="block-1",
    )

    closing_block.set_sql_schema.assert_not_called()


def test_session_schema_result_from_previous_database_skips_target_block(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    main_window = _DummyMainWindow(widget, MagicMock())
    target_block = _DummyBlock()
    target_block.get_block_key = MagicMock(return_value="block-1")
    target_block._database_name = "db_b"
    widget.editor._blocks = [target_block]

    main_window._on_schema_loaded(
        {
            "database": "db_a",
            "connection_context": "db_a",
            "requested_context": "db_a",
            "tables": [{"name": "old_table"}],
            "columns": {},
        },
        "Conn",
        session_id="sid-1",
    )
    qapp.processEvents()

    target_block.set_sql_schema.assert_not_called()
    target_block.set_database_context.assert_not_called()


def test_block_database_switch_registers_connector_and_loads_target_schema(qapp, monkeypatch):
    class _Signal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback, *_args, **_kwargs):
            self._callbacks.append(callback)

        def emit(self, *args):
            for callback in list(self._callbacks):
                callback(*args)

    class _Thread:
        def __init__(self):
            self.started = _Signal()
            self.finished = _Signal()

        def start(self):
            self.started.emit()

        def quit(self):
            return None

    connector = MagicMock()
    connector.is_connected.return_value = True
    connector._abandoned = False

    class _Worker:
        def __init__(self, **_kwargs):
            self.connection_ready = _Signal()
            self.error = _Signal()
            self.finished = _Signal()

        def moveToThread(self, _thread):
            return None

        def run(self):
            self.connection_ready.emit(connector)
            self.finished.emit()

    manager = MagicMock()
    manager.get_connection_config.return_value = {
        "db_type": "sqlserver",
        "host": "host",
        "port": 1433,
        "database": "db_a",
    }
    monkeypatch.setattr("src.database.connection_manager.ConnectionManager", lambda: manager)
    monkeypatch.setattr("src.ui.main_window._schema.QThread", _Thread)
    monkeypatch.setattr("src.workers.BlockConnectionWorker", _Worker)

    widget = _DummyWidget("sid-1", "Conn")
    target_block = _DummyBlock()
    target_block.get_block_key = MagicMock(return_value="block-1")
    widget.editor._blocks = [target_block]
    widget._block_connector_pool = BlockConnectorPool()
    main_window = _DummyMainWindow(widget, MagicMock())
    main_window._worker_threads = []
    main_window._adopt_background_thread = MagicMock()
    main_window._remove_worker_thread = MagicMock()
    main_window._get_active_session_id = MagicMock(return_value="sid-1")

    main_window._on_block_database_changed(target_block, "db_b")

    assert widget._block_connector_pool.peek_connected("block-1", "", "Conn") is connector
    assert any(
        call.kwargs.get("block_key") == "block-1"
        and call.kwargs.get("lazy_mode") == "autocomplete"
        and call.kwargs.get("database_context") == "db_b"
        for call in main_window._schema_service.load_schema.call_args_list
    )


def test_block_database_switch_reuses_pool_connector_without_reconnect(qapp, monkeypatch):
    class _Signal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback, *_args, **_kwargs):
            self._callbacks.append(callback)

        def emit(self, *args):
            for callback in list(self._callbacks):
                callback(*args)

    class _Thread:
        def __init__(self):
            self.started = _Signal()
            self.finished = _Signal()

        def start(self):
            self.started.emit()

        def quit(self):
            return None

    connector = MagicMock()
    connector.is_connected.return_value = True
    connector._abandoned = False
    switch_workers = []
    reconnect_workers = []

    class _SwitchWorker:
        def __init__(self, live_connector, database_name):
            self.connector = live_connector
            self.database_name = database_name
            self.switch_success = _Signal()
            self.error = _Signal()
            self.finished = _Signal()
            switch_workers.append(self)

        def moveToThread(self, _thread):
            return None

        def run(self):
            self.connector.change_database(self.database_name)
            self.switch_success.emit(self.database_name)
            self.finished.emit()

    class _ReconnectWorker:
        def __init__(self, **_kwargs):
            reconnect_workers.append(self)
            self.connection_ready = _Signal()
            self.error = _Signal()
            self.finished = _Signal()

        def moveToThread(self, _thread):
            return None

        def run(self):
            self.finished.emit()

    manager = MagicMock()
    manager.get_connection_config.return_value = {
        "db_type": "databricks",
        "host": "host",
        "port": 443,
        "database": "hive_metastore",
    }
    monkeypatch.setattr("src.database.connection_manager.ConnectionManager", lambda: manager)
    monkeypatch.setattr("src.ui.main_window._schema.QThread", _Thread)
    monkeypatch.setattr("src.workers.DatabaseSwitchWorker", _SwitchWorker)
    monkeypatch.setattr("src.workers.BlockConnectionWorker", _ReconnectWorker)

    widget = _DummyWidget("sid-1", "Conn")
    target_block = _DummyBlock()
    target_block.get_block_key = MagicMock(return_value="block-1")
    target_block._sql_schema = {
        "db_type": "databricks",
        "databases": ["main", "mag_bronze"],
        "catalog_schemas": {"main": ["default"], "mag_bronze": ["esim"]},
    }
    widget.editor._blocks = [target_block]
    widget._block_connector_pool = BlockConnectorPool()
    widget._block_connector_pool.register("block-1", "", "Conn", connector)
    main_window = _DummyMainWindow(widget, MagicMock())
    main_window._worker_threads = []
    main_window._adopt_background_thread = MagicMock()
    main_window._remove_worker_thread = MagicMock()
    main_window._get_active_session_id = MagicMock(return_value="sid-1")

    main_window._on_block_database_changed(target_block, "mag_bronze.esim")

    assert reconnect_workers == []
    assert len(switch_workers) == 1
    connector.change_database.assert_called_once_with("mag_bronze.esim")
    assert any(
        call.kwargs.get("block_key") == "block-1"
        and call.kwargs.get("lazy_mode") == "autocomplete"
        and call.kwargs.get("database_context") == "mag_bronze.esim"
        for call in main_window._schema_service.load_schema.call_args_list
    )


def test_lazy_block_schema_does_not_use_connection_only_pending_map(qapp):
    widget = _DummyWidget("sid-1", "Conn")
    connector = MagicMock()
    connector.is_connected.return_value = True
    widget.session.connector = connector
    block = _DummyBlock()
    block.get_block_key = MagicMock(return_value="block-1")
    main_window = _DummyMainWindow(widget, MagicMock())
    main_window._schema_service.get_cached_schema.return_value = None

    main_window.request_lazy_schema_for_completion(block, widget)

    main_window._schema_service.load_schema.assert_called_once()
    assert main_window._schema_service.load_schema.call_args.kwargs["session_id"] == "sid-1"
    assert main_window._schema_service.load_schema.call_args.kwargs["block_key"] == "block-1"
    assert not getattr(main_window, "_pending_block_schemas", {})
