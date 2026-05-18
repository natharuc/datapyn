from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services.schema_service import SchemaService
from src.ui.main_window._schema import SchemaMixin


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

    def get_connection_name(self):
        return self._connection_name

    def get_language(self):
        return self._language


class _DummyWidget:
    def __init__(self, session_id: str, connection_name: str):
        self.session = SimpleNamespace(session_id=session_id, connection_name=connection_name)
        self.editor = _DummyEditor()


class _DummyMainWindow(SchemaMixin):
    def __init__(self, widget, explorer):
        self.connection_manager = _DummyConnectionManager()
        self._session_widgets = {widget.session.session_id: widget}
        self._session_explorers = {widget.session.session_id: explorer}
        self.object_explorer_dock = _DummyDock()
        self._status_bar = _DummyStatusBar()
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


def test_on_schema_loaded_updates_requesting_explorer_from_explicit_session_id(qapp):
    schema = {"database": "db2", "tables": [{"name": "venda", "schema": "dbo"}], "columns": {}}
    widget = _DummyWidget("sid-1", "Conn")
    explorer = MagicMock()
    main_window = _DummyMainWindow(widget, explorer)

    main_window._on_schema_loaded(schema, "Conn", session_id="sid-1")

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