"""
SchemaMixin - Schema loading, Object Explorer updates, variable panel interactions.
"""

from __future__ import annotations

import logging
import weakref

import pandas as pd
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import QMessageBox

from src.language import S

logger = logging.getLogger(__name__)


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

        self._schema_service.load_schemas_for_catalog(
            connector, connection_name, catalog_name
        )

    def _on_schemas_loaded(self, catalog_name: str, schemas: list):
        """Callback when schemas are loaded for a catalog."""
        sid = self._get_active_session_id()
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

        self._schema_service.load_tables_for_schema(
            connector, connection_name, catalog_name, schema_name
        )

    def _on_tables_loaded(self, catalog_name: str, schema_name: str, tables: list):
        """Callback when tables are loaded for a schema."""
        sid = self._get_active_session_id()
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

        self._schema_service.load_columns_for_table(
            connector, connection_name, catalog_name, schema_name, table_name
        )

    def _on_columns_loaded(self, catalog_name: str, schema_name: str, table_name: str, columns: list):
        """Callback when columns are loaded for a table."""
        sid = self._get_active_session_id()
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_columns_to_table(catalog_name, schema_name, table_name, columns)

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

    def _on_schema_loaded(self, schema: dict, connection_name: str, session_id: str = ""):
        """Callback when database schema is loaded by SchemaService.

        Distribui o schema para os blocos SQL que usam
        a conexao correspondente.
        Se connection_name e a conexao da sessao, aplica aos blocos sem conexao customizada.
        Se connection_name e uma conexao de bloco especifico, aplica so a esse bloco.
        
        Args:
            schema: Loaded schema dict
            connection_name: Connection name
            session_id: Session ID that requested the schema (for isolation)
        """
        # Guard against invalid data (e.g., Mock objects in tests)
        if not isinstance(schema, dict) or not isinstance(connection_name, str):
            return
        
        tables_total = len(schema.get('tables', []))
        cols_total = sum(len(v) for v in schema.get('columns', {}).values())
        self._log_info(
            S.log.schema_loaded.format(name=connection_name, tables=tables_total, cols=cols_total)
        )

        # Feedback na statusbar
        tables_count = len(schema.get("tables", []))
        cols_count = sum(len(v) for v in schema.get("columns", {}).values())
        self.statusBar().showMessage(
            S.status.schema_loaded.format(name=connection_name, tables=tables_count, cols=cols_count), 5000
        )

        # Enviar schema para blocos que usam esta conexao
        # Get db_type early for special handling (e.g., Databricks)
        db_type = ""
        conn_config = self.connection_manager.get_connection_config(connection_name)
        if conn_config:
            db_type = conn_config.get("db_type", "")

        # Build available databases list - for Databricks use catalog.schema format
        all_databases = schema.get("databases", [])
        if db_type == "databricks":
            current_catalog = schema.get("database", "")
            tables = schema.get("tables", [])
            schemas_set = set()
            for t in tables:
                table_schema = t.get("schema", "")
                if table_schema:
                    schemas_set.add(table_schema)
            if current_catalog and schemas_set:
                all_databases = sorted([f"{current_catalog}.{s}" for s in schemas_set])

        # Determine which session requested this schema (use signal param OR fallback to tracking dict)
        requesting_sid = session_id
        if not requesting_sid and hasattr(self, "_pending_schema_sessions"):
            requesting_sid = self._pending_schema_sessions.get(connection_name)

        for widget in self._session_widgets.values():
            if not (hasattr(widget, "editor") and widget.editor):
                continue

            # Verificar se esta conexao e a conexao da sessao
            session_conn = ""
            sid = ""
            if hasattr(widget, "session") and widget.session:
                session_conn = getattr(widget.session, "connection_name", "") or ""
                sid = widget.session.session_id

            # Only update session that REQUESTED the schema (sessions are isolated)
            if requesting_sid and sid != requesting_sid:
                continue

            # If this is the session's connection, cache schema in BlockEditor
            # BlockEditor will apply to all SQL blocks and handle language changes
            if session_conn == connection_name:
                if hasattr(widget.editor, "set_sql_schema"):
                    widget.editor.set_sql_schema(schema)
            
            # Also handle per-block custom connections
            for block in widget.editor.get_blocks():
                # Only apply SQL schema to SQL blocks
                block_lang = block.get_language() if hasattr(block, "get_language") else ""
                if block_lang != "sql":
                    continue

                block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None

                # Block with custom connection: only apply if same connection
                if block_conn and block_conn == connection_name:
                    if hasattr(block.editor, "set_sql_schema"):
                        block.editor.set_sql_schema(schema)
                    if hasattr(block, "set_available_databases"):
                        block.set_available_databases(all_databases)
                elif not block_conn and session_conn == connection_name:
                    # Block without custom connection uses session - set available databases
                    if hasattr(block, "set_available_databases"):
                        block.set_available_databases(all_databases)
        
        # Build text context from schema for Copilot completions
        schema_context = self._build_schema_context(schema, connection_name)
        
        # Propagate schema context only to the session that REQUESTED this schema
        if requesting_sid:
            widget = self._session_widgets.get(requesting_sid)
            if widget and hasattr(widget, "editor"):
                widget.editor.set_database_context(schema_context)

        # Update Object Explorer for the session that REQUESTED this schema
        # (not all sessions - each session has its own OE state)
        if hasattr(self, "_session_explorers"):
            # Find which session requested this schema load
            requesting_sid = None
            if hasattr(self, "_pending_schema_sessions"):
                requesting_sid = self._pending_schema_sessions.pop(connection_name, None)

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
                    self._apply_schema_to_block(pending_block, schema, db_type=db_type)
                    # Also update OE if this block is focused
                    self._update_oe_for_block_connection(pending_block, connection_name, schema)

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
            table_cols = columns.get(table_name, [])
            col_names = [c.get("name", "") for c in table_cols[:10]]  # First 10 cols
            if len(table_cols) > 10:
                col_names.append(f"... +{len(table_cols) - 10} more")
            lines.append(f"  {table_name}: {', '.join(col_names)}")
        
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
            self._apply_schema_to_block(block, cached, db_type=db_type)
            # Update OE if this is the focused block
            self._update_oe_for_block_connection(block, connection_name, cached)
            return

        # Need to load schema in background
        self._load_schema_for_block(block, connection_name)

    def _apply_schema_to_block(self, block, schema: dict, db_type: str = ""):
        """Apply schema to a specific block's editor.
        
        Args:
            block: The CodeBlock to update
            schema: Schema dict with tables, columns, databases
            db_type: Database type (e.g., 'databricks') for special handling
        """
        if not block:
            return
        if hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
            block.editor.set_sql_schema(schema)
        if hasattr(block, "set_available_databases"):
            all_databases = schema.get("databases", [])
            
            # For Databricks, build catalog.schema combos from tables
            if db_type == "databricks":
                current_catalog = schema.get("database", "")
                tables = schema.get("tables", [])
                # Extract unique schemas from tables
                schemas_set = set()
                for t in tables:
                    table_schema = t.get("schema", "")
                    if table_schema:
                        schemas_set.add(table_schema)
                # Build catalog.schema list
                if current_catalog and schemas_set:
                    all_databases = sorted([f"{current_catalog}.{s}" for s in schemas_set])
                    
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
            worker = BlockConnectionWorker(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=config.get("username", ""),
                password=config.get("password", ""),
                use_windows_auth=config.get("use_windows_auth", False),
                trust_server_certificate=config.get("trust_server_certificate", False),
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
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: self._remove_worker_thread(thread))

            self._worker_threads.append((thread, worker))
            thread.start()
        except Exception as e:
            self._log_info(f"Error loading schema for block ({connection_name}): {e}")

    def _on_block_database_changed(self, block, database_name: str):
        """Callback when a block's database is changed.

        Switches the database of the block's connection (or session connection)
        and reloads schema for the new database to update IntelliSense.
        """
        if not database_name:
            return

        current_widget = self._get_current_session_widget()
        session = current_widget.session if current_widget and hasattr(current_widget, "session") else None

        # Determine which connector to use (block-specific or session)
        block_conn_name = block.get_connection_name() if hasattr(block, "get_connection_name") else None

        if block_conn_name:
            # Block has its own connection - need to switch database and reload schema
            # Do this in background to avoid blocking UI
            self._switch_block_database_background(block, block_conn_name, database_name)
            return

        # Block uses session connection
        if not session:
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        connector = getattr(session, "connector", None)
        if not connector or not self._connector_is_connected(connector):
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        # Switch database in background (uses Object Explorer method which handles
        # schema reload, UI updates, etc.)
        self._on_object_explorer_database_switch(database_name)

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

    def _switch_block_database_background(self, block, connection_name: str, database_name: str):
        """Switch database for a block with custom connection (in background)."""
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
        worker = BlockConnectionWorker(
            db_type=config["db_type"],
            host=config["host"],
            port=config["port"],
            database=database_name,  # Use the new database!
            username=config.get("username", ""),
            password=config.get("password", ""),
            use_windows_auth=config.get("use_windows_auth", False),
            trust_server_certificate=config.get("trust_server_certificate", False),
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
        worker.error.connect(
            lambda msg: self.statusBar().showMessage(f"Error: {msg[:50]}", 5000)
        )
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        thread.start()

    def _on_insert_variable_in_editor(self, var_name: str):
        """Inserts variable name in the focused editor of the active session"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(var_name)

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

        # Enviar para todos os blocos Python da sessao ativa
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor") and current_widget.editor:
            # Collect import lines from all blocks to share as global context
            import_lines = []
            blocks_code_context_parts = []
            
            for block in current_widget.editor.get_blocks():
                block_name = block.get_block_name() if hasattr(block, 'get_block_name') else ""
                block_lang = block.get_language()
                block_code = block.get_code()
                
                if block_lang == "python":
                    for line in block_code.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("import ") or stripped.startswith("from "):
                            import_lines.append(stripped)
                
                # Build context for other blocks (SQL blocks create DataFrames)
                if block_lang == "sql" and block_name:
                    # Show that this SQL block produces a DataFrame with block_name
                    blocks_code_context_parts.append(
                        f"# Block '{block_name}' (SQL) creates DataFrame `{block_name}`:\n"
                        f"# {block_code.strip()[:200]}"
                    )
            
            global_imports = "\n".join(dict.fromkeys(import_lines))  # deduplicate preserving order
            blocks_code_context = "\n\n".join(blocks_code_context_parts)

            for block in current_widget.editor.get_blocks():
                # Only pass Python namespace to Python blocks
                block_lang = block.get_language() if hasattr(block, "get_language") else ""
                if block_lang != "python":
                    continue
                    
                # Pass namespace to completion service via block
                if hasattr(block, "set_python_namespace"):
                    block.set_python_namespace(ns_types)
                elif hasattr(block, "editor") and hasattr(block.editor, "set_python_namespace"):
                    block.editor.set_python_namespace(ns_types)
                
                # Pass blocks code context for Python completions
                if hasattr(block, "set_blocks_code_context"):
                    block.set_blocks_code_context(blocks_code_context)
                
                if hasattr(block, "editor") and hasattr(block.editor, "set_global_imports"):
                    block.editor.set_global_imports(global_imports)
