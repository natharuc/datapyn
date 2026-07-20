"""Tests for cross-database schema sync throttling and busy-connection guards."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ui.main_window._schema import SchemaMixin


class _DummyEditor:
    def get_blocks(self):
        return []


class _DummyWidget:
    def __init__(self, session_id: str, sql_text: str = "SELECT * FROM other_db.t"):
        self.session = SimpleNamespace(
            session_id=session_id,
            connection_name="Conn",
            connector=None,
        )
        self.editor = _DummyEditor()
        self._sql_text = sql_text

    def get_blocks(self):
        return []


class _ThrottleHost(SchemaMixin):
    def __init__(self, widget, *, connector=None):
        self._session_widgets = {widget.session.session_id: widget}
        self._session_explorers = {widget.session.session_id: MagicMock(_current_schema={"database": "main"})}
        self.connection_manager = MagicMock()
        self.connection_manager.get_connection_config.return_value = {"db_type": "mysql"}
        self._schema_service = MagicMock()
        widget.session.connector = connector or MagicMock()
        widget.session.connector.is_connected = True
        self._pending_oe_table_requests = {}
        self._pending_oe_column_requests = {}


def test_sync_skips_when_connector_busy(qapp):
    widget = _DummyWidget("sess-1")
    connector = MagicMock()
    connector.is_connected = True
    connector.is_query_busy = MagicMock(return_value=True)
    host = _ThrottleHost(widget, connector=connector)

    with patch(
        "src.ui.main_window._schema.collect_sql_text_from_widget",
        return_value="SELECT * FROM other_db.orders",
    ), patch(
        "src.ui.main_window._schema.extract_referenced_catalogs",
        return_value={"other_db"},
    ):
        host._sync_cross_database_schema_for_widget(widget)

    host._schema_service.load_columns_for_table.assert_not_called()
    host._schema_service.load_tables_for_schema.assert_not_called()


def test_sync_skips_unchanged_sql_hash(qapp):
    widget = _DummyWidget("sess-1")
    connector = MagicMock()
    connector.is_connected = True
    connector.is_query_busy = MagicMock(return_value=False)
    host = _ThrottleHost(widget, connector=connector)
    sql = "SELECT * FROM other_db.orders"

    with patch(
        "src.ui.main_window._schema.collect_sql_text_from_widget",
        return_value=sql,
    ), patch(
        "src.ui.main_window._schema.extract_referenced_catalogs",
        return_value={"other_db"},
    ), patch(
        "src.ui.main_window._schema.extract_referenced_table_refs",
        return_value=[],
    ):
        host._sync_cross_database_schema_for_widget(widget)
        host._sync_cross_database_schema_for_widget(widget)

    host._schema_service.load_tables_for_schema.assert_called_once()


def test_columns_busy_result_sets_cooldown(qapp):
    from src.services.schema_service import SCHEMA_BUSY_SENTINEL

    widget = _DummyWidget("sess-1")
    host = _ThrottleHost(widget)
    host._pending_oe_column_requests = {("other_db", "dbo", "orders"): "sess-1"}
    key = host._schema_busy_cooldown_key_columns("other_db", "dbo", "orders")

    host._on_columns_loaded("other_db", "dbo", "orders", SCHEMA_BUSY_SENTINEL)

    assert host._is_schema_request_on_cooldown(key)
