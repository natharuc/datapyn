"""
SchemaMixin - Schema loading, Object Explorer updates, variable panel interactions.
"""

from __future__ import annotations

import logging
import weakref

import pandas as pd
from PyQt6.QtCore import Qt, QThread, QTimer
from src.language import S
from src.services.cross_database_schema import (
    collect_sql_text_from_widget,
    extract_referenced_catalogs,
    extract_referenced_table_refs,
    prepare_editor_sql_schema,
    schema_has_columns_for_table,
)

logger = logging.getLogger(__name__)

_EDITOR_REF_FROM_SQL = object()
_EDITOR_REF_ALL_LAZY = object()


class SchemaMixin:
    """Handles schema loading, OE updates, block schema, variable panel."""

    @staticmethod
    def _connector_is_connected(connector) -> bool:
        """Check if a connector is connected, handling both method and property forms."""
        ic = getattr(connector, "is_connected", None)
        if ic is None:
            return False
        return ic() if callable(ic) else bool(ic)

    def _on_oe_schemas_requested(self, catalog_name: str):
        """Load schemas for a Databricks catalog (lazy loading)."""
        connector, connection_name = self._get_effective_connector_info()
        if not connector or not self._connector_is_connected(connector):
            return

        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if sid:
            self._pending_oe_schema_requests = getattr(self, "_pending_oe_schema_requests", {})
            self._pending_oe_schema_requests[catalog_name] = sid

        self._schema_service.load_schemas_for_catalog(
            connector, connection_name, catalog_name
        )

    def _on_schemas_loaded(self, catalog_name: str, schemas: list):
        """Callback when schemas are loaded for a catalog."""
        pending = getattr(self, "_pending_oe_schema_requests", {})
        sid = pending.pop(catalog_name, None)
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_schemas_to_catalog(catalog_name, schemas)

    def _on_oe_tables_requested(self, catalog_name: str, schema_name: str):
        """Load tables for a schema (lazy loading)."""
        connector, connection_name = self._get_effective_connector_info()
        if not connector or not self._connector_is_connected(connector):
            return

        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if sid:
            self._pending_oe_table_requests = getattr(self, "_pending_oe_table_requests", {})
            self._pending_oe_table_requests[(catalog_name, schema_name)] = sid

        self._schema_service.load_tables_for_schema(
            connector, connection_name, catalog_name, schema_name
        )

    def _on_tables_loaded(self, catalog_name: str, schema_name: str, tables: list):
        """Callback when tables are loaded for a schema."""
        pending = getattr(self, "_pending_oe_table_requests", {})
        sid = pending.pop((catalog_name, schema_name), None)
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_tables_to_schema(catalog_name, schema_name, tables)

    def _on_oe_columns_requested(self, catalog_name: str, schema_name: str, table_name: str):
        """Load columns for a table (lazy loading)."""
        connector, connection_name = self._get_effective_connector_info()
        if not connector or not self._connector_is_connected(connector):
            return

        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if sid:
            self._pending_oe_column_requests = getattr(self, "_pending_oe_column_requests", {})
            self._pending_oe_column_requests[(catalog_name, schema_name, table_name)] = sid

        self._schema_service.load_columns_for_table(
            connector, connection_name, catalog_name, schema_name, table_name
        )

    def _on_columns_loaded(self, catalog_name: str, schema_name: str, table_name: str, columns: list):
        """Callback when columns are loaded for a table."""
        pending = getattr(self, "_pending_oe_column_requests", {})
        sid = pending.pop((catalog_name, schema_name, table_name), None)
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_columns_to_table(catalog_name, schema_name, table_name, columns)

    def _clear_pending_object_explorer_requests(self, session_id: str):
        """Drop stale lazy-load requests for a session after a full schema refresh."""
        if not session_id:
            return

        for attr_name in (
            "_pending_oe_schema_requests",
            "_pending_oe_table_requests",
            "_pending_oe_column_requests",
        ):
            pending = getattr(self, attr_name, None)
            if not isinstance(pending, dict):
                continue

            stale_keys = [key for key, pending_session_id in pending.items() if pending_session_id == session_id]
            for key in stale_keys:
                pending.pop(key, None)

    def _session_id_for_object_explorer_sender(self) -> str:
        sender = self.sender()
        if not sender or not hasattr(self, "_session_explorers"):
            return ""
        for session_id, explorer in self._session_explorers.items():
            if explorer is sender:
                return session_id
        return ""

    def _on_object_explorer_schema_changed(self, session_id: str, schema: dict):
        """Refresh editor autocomplete when Object Explorer lazy metadata changes."""
        if not session_id or not isinstance(schema, dict):
            return

        explorer = self._session_explorers.get(session_id) if hasattr(self, "_session_explorers") else None
        if not explorer:
            return

        connection_name = getattr(explorer, "_current_connection", "") or ""
        if not connection_name:
            return

        db_type = getattr(explorer, "_db_type", "") or self._get_connection_db_type(connection_name)
        editor_schema = self._editor_schema_for_session(
            schema,
            session_id=session_id,
            db_type=db_type,
            referenced_mode=_EDITOR_REF_ALL_LAZY,
        )
        self._schema_service.update_cached_schema(connection_name, editor_schema, session_id=session_id)
        self._apply_schema_to_session_blocks(
            session_id,
            connection_name,
            schema,
            db_type=db_type,
            referenced_mode=_EDITOR_REF_ALL_LAZY,
        )

    def _collect_session_sql_text(self, session_id: str) -> str:
        widget = self._session_widgets.get(session_id) if hasattr(self, "_session_widgets") else None
        if not widget:
            return ""
        return collect_sql_text_from_widget(widget)

    def _editor_schema_for_session(
        self,
        schema: dict,
        *,
        session_id: str,
        db_type: str,
        referenced_mode=_EDITOR_REF_FROM_SQL,
    ) -> dict:
        if referenced_mode is _EDITOR_REF_FROM_SQL:
            sql_text = self._collect_session_sql_text(session_id) if session_id else ""
            referenced_catalogs = extract_referenced_catalogs(
                sql_text,
                current_database=str(schema.get("database", "") or ""),
                db_type=db_type,
            )
        elif referenced_mode is _EDITOR_REF_ALL_LAZY:
            referenced_catalogs = None
        else:
            referenced_catalogs = referenced_mode
        return prepare_editor_sql_schema(
            schema,
            db_type=db_type,
            referenced_catalogs=referenced_catalogs,
        )

    def _session_widget_is_alive(self, widget) -> bool:
        if widget is None:
            return False
        try:
            from PyQt6 import sip
            if sip.isdeleted(widget):
                return False
        except Exception:
            pass
        session = getattr(widget, "session", None)
        session_id = getattr(session, "session_id", None) if session else None
        if not session_id:
            return False
        widgets = getattr(self, "_session_widgets", None)
        if isinstance(widgets, dict) and session_id not in widgets:
            return False
        tabs = getattr(self, "session_tabs", None)
        if tabs is not None:
            try:
                for index in range(tabs.count()):
                    if tabs.widget(index) is widget:
                        return True
                return False
            except RuntimeError:
                return False
        return True

    def _schedule_cross_database_schema_sync(self, widget) -> None:
        """Debounce lazy metadata loads for databases referenced in SQL text."""
        if not self._session_widget_is_alive(widget):
            return
        if not widget or not hasattr(widget, "session") or not widget.session:
            return

        session_id = widget.session.session_id
        timers = getattr(self, "_cross_db_schema_timers", None)
        if timers is None:
            timers = {}
            self._cross_db_schema_timers = timers

        existing = timers.pop(session_id, None)
        if existing is not None:
            try:
                existing.stop()
            except RuntimeError:
                pass

        timer = QTimer(self)
        timer.setSingleShot(True)

        def run_sync(sid=session_id, w=widget):
            timers.pop(sid, None)
            if not self._session_widget_is_alive(w):
                return
            self._sync_cross_database_schema_for_widget(w)

        timer.timeout.connect(run_sync)
        timers[session_id] = timer
        timer.start(400)

    def _sync_cross_database_schema_for_widget(self, widget) -> None:
        if not self._session_widget_is_alive(widget):
            return
        session = getattr(widget, "session", None)
        if not session:
            return

        session_id = session.session_id
        connection_name = getattr(session, "connection_name", "") or ""
        if not connection_name:
            return

        connector = getattr(session, "connector", None)
        if not connector or not self._connector_is_connected(connector):
            get_connection = getattr(self.connection_manager, "get_connection", None)
            if callable(get_connection):
                connector = get_connection(connection_name)
        if not connector or not self._connector_is_connected(connector):
            return

        db_type = ""
        config = self.connection_manager.get_connection_config(connection_name)
        if config:
            db_type = config.get("db_type", "")

        sql_text = collect_sql_text_from_widget(widget)
        if not sql_text.strip():
            return

        explorer = self._session_explorers.get(session_id) if hasattr(self, "_session_explorers") else None
        oe_schema = getattr(explorer, "_current_schema", None) if explorer else None
        cached = self._schema_service.get_cached_schema(connection_name, session_id=session_id)
        base_schema = oe_schema if isinstance(oe_schema, dict) else cached

        current_database = ""
        if isinstance(base_schema, dict):
            current_database = str(base_schema.get("database", "") or "")

        referenced_catalogs = extract_referenced_catalogs(
            sql_text,
            current_database=current_database,
            db_type=db_type,
        )
        if not referenced_catalogs:
            return

        loaded_catalogs = set()
        if isinstance(base_schema, dict):
            for table in base_schema.get("tables", []) or []:
                if isinstance(table, dict):
                    db_name = str(table.get("database", "") or table.get("catalog", "") or "")
                    if db_name:
                        loaded_catalogs.add(db_name.lower())

        server_databases = set()
        if isinstance(base_schema, dict):
            server_databases = {
                str(name).lower() for name in (base_schema.get("databases", []) or []) if name
            }

        table_requests = getattr(self, "_pending_oe_table_requests", None)
        if table_requests is None:
            table_requests = {}
            self._pending_oe_table_requests = table_requests

        for catalog_name in sorted(referenced_catalogs):
            catalog_lower = catalog_name.lower()
            if catalog_lower == (current_database or "").lower():
                continue
            if server_databases and catalog_lower not in server_databases:
                continue
            if catalog_lower in loaded_catalogs:
                continue

            request_key = (catalog_name, "")
            if table_requests.get(request_key) == session_id:
                continue
            table_requests[request_key] = session_id
            self._schema_service.load_tables_for_schema(
                connector,
                connection_name,
                catalog_name,
                "",
            )

        column_requests = getattr(self, "_pending_oe_column_requests", None)
        if column_requests is None:
            column_requests = {}
            self._pending_oe_column_requests = column_requests

        for catalog_name, schema_name, table_name in extract_referenced_table_refs(
            sql_text,
            current_database=current_database,
            db_type=db_type,
        ):
            if not table_name:
                continue
            if catalog_name and catalog_name.lower() == (current_database or "").lower():
                continue
            if isinstance(base_schema, dict) and schema_has_columns_for_table(
                base_schema, catalog_name, schema_name, table_name
            ):
                continue

            request_key = (catalog_name, schema_name, table_name)
            if column_requests.get(request_key) == session_id:
                continue
            column_requests[request_key] = session_id
            self._schema_service.load_columns_for_table(
                connector,
                connection_name,
                catalog_name,
                schema_name,
                table_name,
            )

    def _block_schema_database(self, block) -> str:
        """Current database label on a block's autocomplete schema, if any."""
        if hasattr(block, "get_sql_schema"):
            schema = block.get_sql_schema()
        else:
            schema = getattr(block, "_sql_schema", None) or {}
        if not isinstance(schema, dict):
            return ""
        return schema.get("database", "") or ""

    def _should_apply_session_schema_to_block(self, block, editor_schema: dict) -> bool:
        """Skip session-wide schema when the block already targets another database."""
        if not block or not isinstance(editor_schema, dict):
            return False
        incoming_db = editor_schema.get("database", "") or ""
        block_db = self._block_schema_database(block)
        if block_db and incoming_db and block_db != incoming_db:
            return False
        return True

    def _clear_sql_autocomplete_for_connection(self, widget, connection_name: str):
        """Clear Monaco SQL autocomplete for blocks affected by a database switch."""
        if not widget or not connection_name or not hasattr(widget, "editor") or not widget.editor:
            return

        editor = widget.editor
        session_conn = ""
        if hasattr(widget, "session") and widget.session:
            session_conn = getattr(widget.session, "connection_name", "") or ""

        if session_conn == connection_name:
            if hasattr(editor, "set_sql_schema"):
                editor.set_sql_schema({})
            elif hasattr(editor, "_sql_schema"):
                editor._sql_schema = {}
            if hasattr(editor, "set_database_context"):
                editor.set_database_context("")

        get_blocks = getattr(editor, "get_blocks", None)
        blocks = get_blocks() if callable(get_blocks) else []
        for block in blocks:
            block_lang = block.get_language() if hasattr(block, "get_language") else ""
            if block_lang != "sql":
                continue

            block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
            should_clear = block_conn == connection_name if block_conn else session_conn == connection_name
            if not should_clear:
                continue

            if hasattr(block, "set_sql_schema"):
                block.set_sql_schema({})
            elif hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema({})

    def _get_connection_db_type(self, connection_name: str) -> str:
        config = self.connection_manager.get_connection_config(connection_name) if connection_name else None
        return config.get("db_type", "") if config else ""

    def _available_databases_from_schema(self, schema: dict, db_type: str = "") -> list:
        all_databases = list(schema.get("databases", []) or [])
        if db_type != "databricks":
            return all_databases

        values = set(all_databases)
        catalog_schemas = schema.get("catalog_schemas", {}) or {}
        for catalog, schemas in catalog_schemas.items():
            for schema_name in schemas or []:
                if catalog and schema_name:
                    values.add(f"{catalog}.{schema_name}")

        current_catalog = schema.get("database", "")
        for table in schema.get("tables", []) or []:
            catalog = table.get("catalog") or current_catalog
            schema_name = table.get("schema", "")
            if catalog and schema_name:
                values.add(f"{catalog}.{schema_name}")

        return sorted(value for value in values if value)

    def _apply_schema_to_session_blocks(
        self,
        session_id: str,
        connection_name: str,
        schema: dict,
        db_type: str = "",
        *,
        referenced_mode=_EDITOR_REF_FROM_SQL,
    ):
        widget = self._session_widgets.get(session_id)
        if not widget or not hasattr(widget, "editor") or not widget.editor:
            return

        session_conn = ""
        if hasattr(widget, "session") and widget.session:
            session_conn = getattr(widget.session, "connection_name", "") or ""

        available_databases = self._available_databases_from_schema(schema, db_type)

        editor_schema = self._editor_schema_for_session(
            schema,
            session_id=session_id,
            db_type=db_type,
            referenced_mode=referenced_mode,
        )

        schema_context = self._build_schema_context(editor_schema, connection_name)
        if session_conn == connection_name:
            if hasattr(widget.editor, "set_sql_schema"):
                widget.editor.set_sql_schema(editor_schema)
            if hasattr(widget.editor, "set_database_context"):
                widget.editor.set_database_context(schema_context)

        for block in widget.editor.get_blocks():
            block_lang = block.get_language() if hasattr(block, "get_language") else ""
            if block_lang != "sql":
                continue

            block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
            uses_connection = (block_conn == connection_name) or (not block_conn and session_conn == connection_name)
            if not uses_connection:
                continue
            if not self._should_apply_session_schema_to_block(block, editor_schema):
                continue

            self._apply_schema_to_block(
                block,
                editor_schema,
                db_type=db_type,
                connection_name=connection_name,
            )

    def _load_schema_with_loading(self, connector, connection_name: str, session_id: str = ""):
        """Load schema and show loading indicator in Object Explorer.
        
        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name
            session_id: Session ID for per-session cache (optional, defaults to active)
        """
        # Get or CREATE the explorer for the current session (important: _get_session_explorer creates if needed)
        sid = session_id or self._get_active_session_id()
        if sid:
            explorer = self._get_session_explorer(sid)
            explorer.set_loading(True, S.object_explorer.loading)
            self._switch_session_explorer(sid)

            # Track which session requested this schema load
            # (so _on_schema_loaded only updates this session's OE)
            if not hasattr(self, "_pending_schema_sessions"):
                self._pending_schema_sessions = {}  # connection_name -> session_id
            self._pending_schema_sessions[connection_name] = sid

        # Show Object Explorer dock if hidden (so user sees the loading)
        if hasattr(self, 'object_explorer_dock') and not self.object_explorer_dock.isVisible():
            self.object_explorer_dock.show()
            # Update menu checkmark
            if hasattr(self, 'object_explorer_action'):
                self.object_explorer_action.setChecked(True)

        self._schema_service.load_schema(connector, connection_name, session_id=sid or "")

    def _reload_schema(self):
        """Reloads the SQL schema from the focused block connection (or session).

        Usa a conexao do bloco focado se ele tiver conexao customizada,
        caso contrario usa a conexao da sessao ativa.
        """
        widget = self._get_current_session_widget()
        if not widget:
            self.statusBar().showMessage(S.status.no_active_session, 3000)
            return

        # Determine connection: focused block or session
        connection_name = None
        connector = None

        focused_block = widget.editor.get_focused_block()
        if focused_block:
            block_conn = focused_block.get_connection_name()
            if block_conn:
                connection_name = block_conn

        if not connection_name:
            # Use session connection
            if widget.session.is_connected and widget.session.connection_name:
                connection_name = widget.session.connection_name
                connector = widget.session.connector

        if not connection_name:
            self.statusBar().showMessage(S.status.no_active_connection_reload, 3000)
            return

        # Get session_id for per-session cache
        sid = widget.session.session_id if hasattr(widget, "session") else ""

        # Invalidate cache and reload (per-session)
        self._schema_service.invalidate_cache(connection_name, session_id=sid)
        self.statusBar().showMessage(S.status.reloading_schema.format(name=connection_name), 5000)

        if connector and self._connector_is_connected(connector):
            self._load_schema_with_loading(connector, connection_name, session_id=sid)
        else:
            # Need to get connector from ConnectionManager
            from src.database.connection_manager import ConnectionManager
            manager = ConnectionManager()
            conn = manager.connections.get(connection_name)
            if conn and self._connector_is_connected(conn):
                self._load_schema_with_loading(conn, connection_name, session_id=sid)
            else:
                self.statusBar().showMessage(S.status.connection_not_active.format(name=connection_name), 3000)

    def _on_schema_loaded(
        self,
        schema: dict,
        connection_name: str,
        session_id: str = "",
        block_key: str = "",
    ):
        """Callback when database schema is loaded by SchemaService.

        Distribui o schema para os blocos SQL que usam
        a conexao correspondente.
        Se connection_name e a conexao da sessao, aplica aos blocos sem conexao customizada.
        Se connection_name e uma conexao de bloco especifico, aplica so a esse bloco.
        
        Args:
            schema: Loaded schema dict
            connection_name: Connection name
            session_id: Session ID that requested the schema (for isolation)
            block_key: Isolated SQL block id (per-block database context)
        """
        # Guard against invalid data (e.g., Mock objects in tests)
        if not isinstance(schema, dict) or not isinstance(connection_name, str):
            return

        schema_label = (
            schema.get("database")
            or schema.get("current_context")
            or connection_name
        )
        tables_total = len(schema.get("tables", []))
        cols_total = sum(len(v) for v in schema.get("columns", {}).values())
        self._log_info(
            S.log.schema_loaded.format(name=schema_label, tables=tables_total, cols=cols_total)
        )

        tables_count = len(schema.get("tables", []))
        cols_count = sum(len(v) for v in schema.get("columns", {}).values())
        self.statusBar().showMessage(
            S.status.schema_loaded.format(name=schema_label, tables=tables_count, cols=cols_count),
            5000,
        )

        db_type = ""
        conn_config = self.connection_manager.get_connection_config(connection_name)
        if conn_config:
            db_type = conn_config.get("db_type", "")

        pending_sid = ""
        if hasattr(self, "_pending_schema_sessions"):
            pending_sid = self._pending_schema_sessions.get(connection_name, "") or ""

        requesting_sid = session_id or pending_sid
        self._clear_pending_object_explorer_requests(requesting_sid)

        if block_key:
            target_block = self._find_block_by_key(block_key, requesting_sid)
            if target_block is not None:
                self._apply_schema_to_block(
                    target_block,
                    schema,
                    db_type=db_type,
                    connection_name=connection_name,
                )
                self._update_oe_for_block_connection(target_block, connection_name, schema)
            return

        # Defer heavy Monaco/schema propagation to the next event-loop tick
        QTimer.singleShot(
            0,
            lambda s=schema, cn=connection_name, db=db_type, rs=requesting_sid: self._apply_loaded_schema_to_blocks(
                s, cn, db_type=db, requesting_sid=rs,
            ),
        )

        # Update Object Explorer for the session that REQUESTED this schema
        # (not all sessions - each session has its own OE state)
        if hasattr(self, "_session_explorers"):
            if pending_sid and requesting_sid == pending_sid and hasattr(self, "_pending_schema_sessions"):
                self._pending_schema_sessions.pop(connection_name, None)

            if requesting_sid:
                # Only update the requesting session's OE
                explorer = self._get_session_explorer(requesting_sid)
                explorer.set_schema(schema, connection_name, db_type=db_type)
                
                # Update OE tracking for this session
                if not hasattr(self, "_oe_current_connection"):
                    self._oe_current_connection = {}
                self._oe_current_connection[requesting_sid] = connection_name
            
            # Ensure we're showing the active session's OE
            current_widget = self._get_current_session_widget()
            if current_widget and hasattr(current_widget, "session"):
                active_sid = current_widget.session.session_id
                self._switch_session_explorer(active_sid)
                # Show dock if the active session requested this schema
                if requesting_sid == active_sid:
                    self.object_explorer_dock.show()

        # Check if any block was waiting for this schema (per-block connection)
        if hasattr(self, "_pending_block_schemas"):
            pending_refs = self._pending_block_schemas.pop(connection_name, [])
            if not isinstance(pending_refs, list):
                pending_refs = [pending_refs]  # backward compat
            for ref in pending_refs:
                # Dereference weakref; skip if block was garbage-collected
                pending_block = ref() if callable(ref) else ref
                if pending_block:
                    self._apply_schema_to_block(
                        pending_block,
                        schema,
                        db_type=db_type,
                        connection_name=connection_name,
                    )
                    # Also update OE if this block is focused
                    self._update_oe_for_block_connection(pending_block, connection_name, schema)

    def _apply_loaded_schema_to_blocks(
        self,
        schema: dict,
        connection_name: str,
        *,
        db_type: str = "",
        requesting_sid: str = "",
    ):
        """Apply loaded schema to SQL blocks without blocking the schema_loaded handler."""
        all_databases = self._available_databases_from_schema(schema, db_type)

        for widget in self._session_widgets.values():
            if not (hasattr(widget, "editor") and widget.editor):
                continue

            session_conn = ""
            sid = ""
            if hasattr(widget, "session") and widget.session:
                session_conn = getattr(widget.session, "connection_name", "") or ""
                sid = widget.session.session_id

            if requesting_sid and sid != requesting_sid:
                continue

            editor_schema = self._editor_schema_for_session(
                schema,
                session_id=sid,
                db_type=db_type,
            )
            schema_context = self._build_schema_context(editor_schema, connection_name)

            if session_conn == connection_name:
                if hasattr(widget.editor, "set_sql_schema"):
                    widget.editor.set_sql_schema(editor_schema)
                if hasattr(widget.editor, "set_database_context"):
                    widget.editor.set_database_context(schema_context)

            for block in widget.editor.get_blocks():
                block_lang = block.get_language() if hasattr(block, "get_language") else ""
                if block_lang != "sql":
                    continue

                block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None

                uses_connection = (block_conn == connection_name) or (
                    not block_conn and session_conn == connection_name
                )
                if not uses_connection:
                    continue
                if not self._should_apply_session_schema_to_block(block, editor_schema):
                    continue

                self._apply_schema_to_block(
                    block,
                    editor_schema,
                    db_type=db_type,
                    connection_name=connection_name,
                )

        if requesting_sid and hasattr(self.connection_manager, "get_connection"):
            widget = self._session_widgets.get(requesting_sid)
            if widget:
                QTimer.singleShot(0, lambda w=widget: self._sync_cross_database_schema_for_widget(w))

    def _build_schema_context(self, schema: dict, connection_name: str) -> str:
        """Build text context from schema for Copilot inline completions.
        
        Returns a compact representation of tables and columns that fits
        within token limits while providing useful context.
        """
        tables = schema.get("tables", [])
        columns = schema.get("columns", {})
        db_name = schema.get("database", connection_name)
        
        lines = [f"Database: {db_name}", f"Tables ({len(tables)}):"]
        
        for table in tables[:30]:  # Limit to first 30 tables
            table_name = table.get("name", "")
            table_schema = table.get("schema", "")
            table_catalog = table.get("catalog", "")
            table_key = table.get("key", "")
            fallback_key = f"{table_schema}.{table_name}" if table_schema else table_name
            full_key = ".".join(part for part in (table_catalog, table_schema, table_name) if part)
            table_cols = columns.get(table_key, []) or columns.get(full_key, []) or columns.get(fallback_key, []) or columns.get(table_name, [])
            col_names = [c.get("name", "") for c in table_cols[:10]]  # First 10 cols
            if len(table_cols) > 10:
                col_names.append(f"... +{len(table_cols) - 10} more")
            display_name = full_key or fallback_key or table_name
            lines.append(f"  {display_name}: {', '.join(col_names)}")
        
        if len(tables) > 30:
            lines.append(f"  ... +{len(tables) - 30} more tables")
        
        return "\n".join(lines)

    def _on_schema_error(self, error_msg: str):
        """Handle schema loading error — show feedback in OE panel."""
        sid = self._get_active_session_id()
        if sid and hasattr(self, "_session_explorers"):
            explorer = self._session_explorers.get(sid)
            if explorer:
                explorer.set_error(S.object_explorer.schema_error)
        self.statusBar().showMessage(f"Schema: {error_msg}", 5000)

    def _update_oe_for_session(self, widget):
        """Update Object Explorer to show the effective connection for a session/tab.

        Called when switching tabs. Determines the effective connection
        (focused block's connection or session connection) and updates OE.
        """
        if not widget or not hasattr(widget, "session"):
            return

        session = widget.session
        sid = session.session_id

        # Determine effective connection: focused block's or session's
        effective_conn = ""
        if hasattr(widget, "editor"):
            block = widget.editor.get_last_focused_block()
            if block and hasattr(block, "get_connection_name"):
                block_conn = block.get_connection_name()
                if block_conn:
                    effective_conn = block_conn

        if not effective_conn:
            effective_conn = getattr(session, "connection_name", "") or ""

        if not effective_conn:
            # No connection - clear OE or show empty
            explorer = self._get_session_explorer(sid)
            explorer.clear()
            return

        # Check if OE is already showing this connection
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}

        current_oe_conn = self._oe_current_connection.get(sid)
        if current_oe_conn == effective_conn:
            return  # Already showing correct schema

        # Update tracking
        self._oe_current_connection[sid] = effective_conn

        # Try cache first (per-session cache)
        cached = self._schema_service.get_cached_schema(effective_conn, session_id=sid)
        if cached:
            db_type = ""
            config = self.connection_manager.get_connection_config(effective_conn)
            if config:
                db_type = config.get("db_type", "")

            explorer = self._get_session_explorer(sid)
            explorer.set_schema(cached, effective_conn, db_type=db_type)
            return

        # Need to load schema - get connector from session (NOT shared cache!)
        connector = getattr(session, "connector", None)
        if not connector or not self._connector_is_connected(connector):
            # Fallback to connection_manager for per-block connections
            connector = self.connection_manager.get_connection(effective_conn)
        if connector and self._connector_is_connected(connector):
            self._load_schema_with_loading(connector, effective_conn, session_id=sid)

    def _on_block_focused(self, block, widget):
        """Called when a block gains focus. Updates Object Explorer to show the
        schema for the block's connection (or session connection if block has none).

        This makes the OE follow the 'focused connection' — per-block or per-session.
        """
        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            try:
                self._copilot_chat_panel.notify_block_focused(block)
            except Exception:
                pass
        if not block or not widget:
            return

        session = getattr(widget, "session", None)
        if not session:
            return

        sid = session.session_id

        # Determine which connection name to show
        block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        session_conn = getattr(session, "connection_name", "") or ""

        # The effective connection for this block
        effective_conn = block_conn or session_conn
        if not effective_conn:
            return

        # Track what the OE is currently showing for this session to avoid unnecessary reloads
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}  # session_id -> connection_name

        current_oe_conn = self._oe_current_connection.get(sid)
        if current_oe_conn == effective_conn:
            return  # Already showing the right schema

        # Update tracking
        self._oe_current_connection[sid] = effective_conn

        # Try to get schema from cache first (per-session cache)
        cached = self._schema_service.get_cached_schema(effective_conn, session_id=sid)
        if cached:
            # Get db_type for proper SQL quoting
            db_type = ""
            config = self.connection_manager.get_connection_config(effective_conn)
            if config:
                db_type = config.get("db_type", "")

            explorer = self._get_session_explorer(sid)
            explorer.set_schema(cached, effective_conn, db_type=db_type)
            return

        # If not cached and it's a block-specific connection, load it
        if block_conn:
            self._load_schema_for_block(block, block_conn)

    def _on_block_connection_changed(self, block, connection_name: str):
        """Callback when an individual block connection changes.

        Loads schema from new connection and applies to block (in background).
        Also updates Object Explorer if this block is focused.
        This works independently of the session connection - the block can have
        its own connection even if the session is not connected.
        """
        if not connection_name:
            return

        # Try to get session_id from current widget for per-session cache
        sid = ""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "session"):
            sid = current_widget.session.session_id

        # Check cache first - if available, apply immediately (per-session cache)
        cached = self._schema_service.get_cached_schema(connection_name, session_id=sid)
        if cached:
            # Get db_type for special handling (e.g., Databricks catalog.schema)
            db_type = ""
            config = self.connection_manager.get_connection_config(connection_name)
            if config:
                db_type = config.get("db_type", "")
            self._apply_schema_to_block(
                block,
                cached,
                db_type=db_type,
                connection_name=connection_name,
            )
            # Update OE if this is the focused block
            self._update_oe_for_block_connection(block, connection_name, cached)
            return

        # Need to load schema in background
        self._load_schema_for_block(block, connection_name)

    def _apply_schema_to_block(
        self,
        block,
        schema: dict,
        db_type: str = "",
        connection_name: str = "",
    ):
        """Apply schema to a single block's Monaco autocomplete (isolated per block).

        Args:
            block: The CodeBlock to update
            schema: Schema dict with tables, columns, databases
            db_type: Database type (e.g., 'databricks') for special handling
            connection_name: Connection name for inline-completion context text
        """
        if not block:
            return
        if db_type and isinstance(schema, dict):
            schema = {**schema, "db_type": db_type or schema.get("db_type", "")}
        if hasattr(block, "set_sql_schema"):
            block.set_sql_schema(schema)
        elif hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
            block.editor.set_sql_schema(schema)
        if connection_name and hasattr(block, "set_database_context"):
            block.set_database_context(self._build_schema_context(schema, connection_name))
        if hasattr(block, "set_available_databases"):
            all_databases = self._available_databases_from_schema(schema, db_type)
            block.set_available_databases(all_databases)

    def _update_oe_for_block_connection(self, block, connection_name: str, schema: dict):
        """Update Object Explorer if the given block is currently focused.

        Called when a block's connection changes or when schema loads for a block.
        """
        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "editor"):
            return

        focused = current_widget.editor.get_focused_block()
        if focused is not block:
            return  # Only update OE if this block is focused

        session = current_widget.session
        sid = getattr(session, "session_id", None)
        if not sid:
            return

        db_type = ""
        config = self.connection_manager.get_connection_config(connection_name)
        if config:
            db_type = config.get("db_type", "")

        explorer = self._get_session_explorer(sid)
        explorer.set_schema(schema, connection_name, db_type=db_type)

        # Update tracking
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}
        self._oe_current_connection[sid] = connection_name

    def _load_schema_for_block(self, block, connection_name: str):
        """Load schema in background and apply to specific block when ready."""
        try:
            from src.database.connection_manager import ConnectionManager
            from src.workers import BlockConnectionWorker

            manager = ConnectionManager()
            config = manager.get_connection_config(connection_name)
            if not config:
                self._log_info(f"Connection config not found: {connection_name}")
                return

            self.statusBar().showMessage(
                f"Loading schema for {connection_name}...", 5000
            )

            # Get session_id for per-session cache
            sid = self._get_active_session_id() or ""

            thread = QThread()
            database_name = block.get_database_name() if hasattr(block, "get_database_name") else ""
            connect_database = database_name or config["database"]
            database_context = ""
            if config["db_type"] == "databricks":
                connect_database = config["database"]
                database_context = database_name or ""

            worker = BlockConnectionWorker(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=connect_database,
                username=config.get("username", ""),
                password=config.get("password", ""),
                use_windows_auth=config.get("use_windows_auth", False),
                sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
                database_context=database_context,
            )
            worker.moveToThread(thread)

            # When connection is ready, load schema (also in background via SchemaService)
            def on_connection_ready(connector, session_id=sid):
                # SchemaService.load_schema already runs in background (per-session)
                self._schema_service.load_schema(connector, connection_name, session_id=session_id)
                # Store block reference to apply schema when loaded (support multiple blocks)
                if not hasattr(self, "_pending_block_schemas"):
                    self._pending_block_schemas = {}  # conn_name -> [weakref.ref(block)]
                if connection_name not in self._pending_block_schemas:
                    self._pending_block_schemas[connection_name] = []
                self._pending_block_schemas[connection_name].append(weakref.ref(block))

            thread.started.connect(worker.run)
            worker.connection_ready.connect(on_connection_ready)
            worker.error.connect(
                lambda msg: self._log_info(f"Error connecting for block schema ({connection_name}): {msg}")
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(lambda: self._remove_worker_thread(thread))

            self._worker_threads.append((thread, worker))
            self._adopt_background_thread(thread, worker)
            thread.start()
        except Exception as e:
            self._log_info(f"Error loading schema for block ({connection_name}): {e}")

    def _find_block_by_key(self, block_key: str, session_id: str = "") -> object | None:
        if not block_key:
            return None
        widgets = []
        if session_id and session_id in getattr(self, "_session_widgets", {}):
            widgets = [self._session_widgets[session_id]]
        else:
            widgets = list(getattr(self, "_session_widgets", {}).values())
        for widget in widgets:
            editor = getattr(widget, "editor", None)
            if editor is None:
                continue
            for candidate in editor.get_blocks():
                if getattr(candidate, "get_block_key", lambda: "")() == block_key:
                    return candidate
        return None

    def _load_schema_for_block_connector(
        self,
        block,
        connector,
        connection_name: str,
        session_id: str = "",
    ) -> None:
        """Reload IntelliSense schema from a block's isolated connector."""
        if not block or not connector or not connection_name:
            return
        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        sid = session_id or self._get_active_session_id() or ""

        if sid:
            explorer = self._get_session_explorer(sid)
            explorer.set_loading(True, S.object_explorer.loading)
            self._switch_session_explorer(sid)
            if not hasattr(self, "_pending_schema_sessions"):
                self._pending_schema_sessions = {}
            self._pending_schema_sessions[connection_name] = sid

        self._schema_service.invalidate_cache(
            connection_name, session_id=sid, block_key=block_key
        )
        self._schema_service.load_schema(
            connector,
            connection_name,
            session_id=sid,
            block_key=block_key,
        )

    def _on_block_database_changed(self, block, database_name: str):
        """Callback when a block's database is changed.

        Switches the database of the block's connection (or session connection)
        and reloads schema for the new database to update IntelliSense.
        """
        if not database_name or block is None:
            return

        current_widget = self._get_current_session_widget()
        session = current_widget.session if current_widget and hasattr(current_widget, "session") else None

        block_conn_name = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        connection_name = block_conn_name or (
            getattr(session, "connection_name", "") if session else ""
        )
        if not connection_name:
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        try:
            self._switch_block_database_background(
                block,
                connection_name,
                database_name,
                session_widget=current_widget,
            )
        except Exception as exc:
            logger.warning("Block database change failed: %s", exc)
            self.statusBar().showMessage(str(exc)[:80], 5000)
            if current_widget is not None and hasattr(current_widget, "append_output"):
                current_widget.append_output(f"[Connection] {exc}", error=True)

    def _on_completion_log(self, message: str, level: str):
        """Handle autocomplete/completion log messages.
        
        Forwards to Copilot output panel so users can see what's happening.
        """
        if not hasattr(self, "_copilot_output_panel") or not self._copilot_output_panel:
            return
        
        output = self._copilot_output_panel
        if level == "error":
            output.log_error(message)
        elif level == "debug":
            # Only log debug when panel is visible (avoid spam)
            if hasattr(self, "copilot_output_dock") and self.copilot_output_dock.isVisible():
                output.log_info(message)
        else:
            output.log_info(message)

    def _on_cursor_position_changed(self, line: int, column: int):
        """Handle cursor position change from editor (updates statusbar)."""
        if hasattr(self, "main_statusbar"):
            self.main_statusbar.set_cursor_position(line, column)

    def _switch_block_database_background(
        self,
        block,
        connection_name: str,
        database_name: str,
        session_widget=None,
    ):
        """Switch database for a block connection in background (never blocks UI)."""
        from src.database.connection_manager import ConnectionManager
        from src.workers import BlockConnectionWorker

        manager = ConnectionManager()
        config = manager.get_connection_config(connection_name)
        if not config:
            self._log_info(f"Connection config not found: {connection_name}")
            return

        self.statusBar().showMessage(
            f"Switching to database {database_name}...", 5000
        )

        # Get session_id for per-session cache
        sid = self._get_active_session_id() or ""

        # Create connection with the NEW database
        thread = QThread()
        connect_database = database_name
        database_context = ""
        if config["db_type"] == "databricks":
            connect_database = config["database"]
            database_context = database_name

        worker = BlockConnectionWorker(
            db_type=config["db_type"],
            host=config["host"],
            port=config["port"],
            database=connect_database,
            username=config.get("username", ""),
            password=config.get("password", ""),
            use_windows_auth=config.get("use_windows_auth", False),
            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
            trust_server_certificate=config.get("trust_server_certificate", False),
            http_path=config.get("http_path", ""),
            database_context=database_context,
        )
        worker.moveToThread(thread)

        def on_connection_ready(connector, session_id=sid):
            # Invalidate old cache and load new schema (per-session)
            self._schema_service.invalidate_cache(connection_name, session_id=session_id)
            self._schema_service.load_schema(connector, connection_name, session_id=session_id)
            # Store block reference to apply schema when loaded (support multiple blocks)
            if not hasattr(self, "_pending_block_schemas"):
                self._pending_block_schemas = {}
            if connection_name not in self._pending_block_schemas:
                self._pending_block_schemas[connection_name] = []
            self._pending_block_schemas[connection_name].append(weakref.ref(block))
            self.statusBar().showMessage(
                S.status.database_changed.format(name=database_name), 3000
            )

        thread.started.connect(worker.run)
        worker.connection_ready.connect(on_connection_ready)
        def _on_block_db_error(msg: str, widget=session_widget):
            short = (msg or "Connection failed")[:120]
            self.statusBar().showMessage(f"Error: {short[:50]}", 5000)
            if widget is not None and hasattr(widget, "append_output"):
                widget.append_output(short, error=True)

        worker.error.connect(_on_block_db_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        self._adopt_background_thread(thread, worker)
        thread.start()

    def _on_insert_variable_in_editor(self, var_name: str):
        """Inserts variable name in the focused editor of the active session"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            editor = current_widget.editor
            block = (
                editor.get_last_focused_block()
                if hasattr(editor, "get_last_focused_block")
                else editor.get_focused_block()
            )
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(var_name)
                block.editor.setFocus()

    def _on_delete_variable(self, var_name: str):
        """Removes variable from the active session namespace"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "session"):
            ns = current_widget.session.namespace
            if var_name in ns:
                del ns[var_name]
                current_widget.session.variables_changed.emit(ns)

    def _on_show_variable_in_results(self, var_name: str, value):
        """Displays a DataFrame or Series in the active session's Results panel"""
        import pandas as pd

        if isinstance(value, pd.Series):
            df = value.to_frame(name=var_name)
        elif isinstance(value, pd.DataFrame):
            df = value
        else:
            return

        current_widget = self._get_current_session_widget()
        if not current_widget:
            return

        session_id = current_widget.session.session_id
        info = self._session_panel_indices.get(session_id)
        viewer = info["results"] if info else None

        if viewer:
            viewer.display_dataframe(df, var_name)
            self.show_panel("results")

    def _push_python_namespace(self, namespace: dict):
        """Sends updated Python namespace to code editors.

        Chamado apos execucao Python para alimentar autocomplete.
        """
        # Construir mapa varName -> typeName
        ns_types = {}
        for key, value in namespace.items():
            if key.startswith("_"):
                continue
            # Pular modulos internos e funcoes builtin
            type_name = type(value).__name__
            if type_name in ("module",):
                ns_types[key] = "module"
            elif type_name in ("function", "builtin_function_or_method"):
                ns_types[key] = "function"
            elif type_name == "type":
                ns_types[key] = "class"
            else:
                ns_types[key] = type_name

        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor") and hasattr(
            current_widget.editor, "refresh_completion_context"
        ):
            current_widget.editor.refresh_completion_context()
