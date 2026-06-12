"""
ConnectionsMixin - Connection management, OE interaction, quick connect.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread
from src.design_system.message_box import show_error, show_info, show_warning
from src.database.database_connector import get_connector_database_context
from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog
from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog
from src.language import S

logger = logging.getLogger(__name__)


class ConnectionsMixin:
    """Handles database connections, OE interaction, connection dialogs."""

    def _start_database_switch_worker(self, connector, database_name: str, *, on_success, on_error=None):
        """Switch the active database in a background thread."""
        from src.workers import DatabaseSwitchWorker

        thread = QThread(self)
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.switch_success.connect(on_success)
        if on_error:
            worker.error.connect(on_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        thread.start()
        return thread, worker

    def _on_object_explorer_insert_text(self, text: str):
        """Inserts text in the block that was focused before clicking on OE"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_last_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(text)
                # Refoca o editor apos inserir
                if hasattr(block.editor, "setFocus"):
                    block.editor.setFocus()

    def _on_object_explorer_query(self, query: str):
        """Inserts query in the block that was focused before clicking on OE"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_last_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(query)
                if hasattr(block.editor, "setFocus"):
                    block.editor.setFocus()

    def _on_object_explorer_database_switch(self, database_name: str):
        """Switches database/catalog. Respects per-block connections:
        if the focused block has its own connection, switch only that block's db.
        Otherwise, switches the session-level connection.
        """
        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "session"):
            return

        session = current_widget.session

        # Determine if focused block has a per-block connection
        focused_block = None
        block_conn = None
        if hasattr(current_widget, "editor"):
            focused_block = current_widget.editor.get_last_focused_block()
            if focused_block and hasattr(focused_block, "get_connection_name"):
                block_conn = focused_block.get_connection_name()

        if block_conn:
            # Per-block connection: switch DB only for this block
            connector = self.connection_manager.get_connection(block_conn)
            connection_name = block_conn
        else:
            # Session connection
            connector = getattr(session, "connector", None)
            connection_name = getattr(session, "connection_name", "") or ""

        if not connector or not connector.is_connected():
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        self.statusBar().showMessage(S.status.switching_database.format(name=database_name), 10000)

        from src.workers import DatabaseSwitchWorker

        thread = QThread()
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        if block_conn and focused_block:
            # Per-block: only update this block's database, not the whole session
            worker.switch_success.connect(
                lambda db, b=focused_block, cn=block_conn, conn=connector: self._on_block_database_switch_success(
                    db, cn, conn, b, current_widget
                )
            )
        else:
            worker.switch_success.connect(
                lambda db: self._on_database_switch_success(db, connection_name, connector, current_widget)
            )
        worker.error.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        thread.start()

    def _on_block_database_switch_success(self, database_name: str, connection_name: str,
                                           connector, block, widget):
        """Callback when database switch completes for a per-block connection.
        
        Only updates the specific block's database panel and refreshes the OE.
        Does NOT touch the session-level connection or other blocks.
        """
        display_name = get_connector_database_context(connector) or database_name
        if display_name.startswith("CATALOG:"):
            display_name = display_name[8:]
        elif display_name.startswith("SCHEMA:"):
            display_name = display_name[7:]

        self.statusBar().showMessage(S.status.database_changed.format(name=display_name), 5000)

        # Update only this block's database panel
        if block and hasattr(block, "db_panel"):
            block._database_name = display_name
            block.db_panel.set_database(display_name)

        # Get session_id for per-session cache
        sid = ""
        if widget and hasattr(widget, "session"):
            sid = widget.session.session_id

        # Invalidate cache and reload OE for this block's connection (per-session)
        self._clear_sql_autocomplete_for_connection(widget, connection_name)
        self._schema_service.invalidate_cache(connection_name, session_id=sid)
        
        # Reset OE tracking so reload is not skipped
        if hasattr(self, "_oe_current_connection") and sid:
            self._oe_current_connection.pop(sid, None)
        
        if connector and connector.is_connected():
            self._load_schema_with_loading(connector, connection_name, session_id=sid)

    def _on_database_switch_success(self, database_name, connection_name, connector, widget):
        """Callback when database switch completes successfully.

        Propagates the database change to: connection panel, status bar,
        tab color, schema cache, object explorer, and ALL blocks.
        """
        # Clean up prefixed names from Databricks (CATALOG:xxx, SCHEMA:xxx)
        display_name = get_connector_database_context(connector) or database_name
        if display_name.startswith("CATALOG:"):
            display_name = display_name[8:]
        elif display_name.startswith("SCHEMA:"):
            display_name = display_name[7:]

        self.statusBar().showMessage(S.status.database_changed.format(name=display_name), 5000)

        # Get session_id for per-session cache
        sid = ""
        if widget and hasattr(widget, "session"):
            sid = widget.session.session_id

        # --- Schema reload (invalidate since database changed) ---
        self._clear_sql_autocomplete_for_connection(widget, connection_name)
        self._schema_service.invalidate_cache(connection_name, session_id=sid)
        
        # Reset OE tracking so next schema load updates the explorer
        if hasattr(self, "_oe_current_connection") and sid:
            self._oe_current_connection.pop(sid, None)
        
        # Note: connection_changed signal will trigger _on_session_connection_changed which loads schema

        if hasattr(widget, "connection_changed"):
            widget.connection_changed.emit(connection_name, display_name)

        # --- Update connection panel ---
        config = self.connection_manager.get_connection_config(connection_name)
        if config:
            host = config.get("host", "localhost")
            db_type = config.get("db_type", "")
            self.connection_panel.set_active_connection(
                connection_name, host=host, database=display_name, db_type=db_type
            )

            # --- Tab color ---
            color = config.get("color", "#007ACC") or "#007ACC"
            for i in range(self.session_tabs.count()):
                tab_widget = self.session_tabs.widget(i)
                if tab_widget == widget:
                    self.session_tabs.set_tab_connection_color(i, color)
                    break

        # --- Highlight connection in list ---
        for i in range(self.connections_list.count()):
            item = self.connections_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == connection_name:
                self.connections_list.setCurrentItem(item)
                break

        # --- Status bar ---
        self.action_label.setText(S.status.connected_to.format(name=connection_name, db=display_name))

        # --- Update tab-default blocks' database panel (not per-block overrides) ---
        if hasattr(widget, "editor"):
            for block in widget.editor.get_blocks():
                if hasattr(block, "db_panel"):
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn and block.uses_tab_default_database():
                        block._database_name = display_name
                        block.db_panel.set_database(display_name)

    def _get_effective_connector_info(self):
        """Return (connector, connection_name) for the effective connection.

        If the focused block has a per-block connection, returns that
        connector.  Otherwise falls back to the session connector.
        Returns (None, "") when no connection is available.
        """
        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "session"):
            return None, ""
        session = current_widget.session

        # Check focused block for per-block connection
        if hasattr(current_widget, "editor"):
            block = current_widget.editor.get_last_focused_block()
            if block and hasattr(block, "get_connection_name"):
                block_conn = block.get_connection_name()
                if block_conn:
                    connector = self.connection_manager.get_connection(block_conn)
                    if connector and connector.is_connected():
                        return connector, block_conn

        # Fall back to session connection
        connector = getattr(session, "connector", None)
        connection_name = getattr(session, "connection_name", "") or ""
        return connector, connection_name

    def _on_object_explorer_refresh(self):
        """Object Explorer refresh - reloads schema from effective connection.
        
        Respects per-block connections: if the focused block has its own
        connection, refresh uses that connector instead of the session's.
        """
        connector, connection_name = self._get_effective_connector_info()
        if not connector or not connector.is_connected():
            return

        # Get session_id for per-session cache
        sid = self._get_active_session_id() or ""

        self._schema_service.invalidate_cache(connection_name, session_id=sid)
        self._load_schema_with_loading(connector, connection_name, session_id=sid)

    def _quick_connect(self, connection_name: str):
        """
        Conecta a um banco de dados.
        - If there is no tab: creates a new tab
        - If current tab is connecting: creates a new tab
        - If current tab is available: switches the connection of that tab
        Connection happens in background (does not block the application).
        """
        # Get current tab
        current_widget = self._get_current_session_widget()

        # If there is no tab or current tab is connecting, create a new one
        # (without inheriting the previous connection - we connect explicitly below)
        if not current_widget or current_widget.is_connecting():
            self._new_session(inherit_connection=False)
            current_widget = self._get_current_session_widget()

        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return

        # Get config (metadata only, not connection)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")

        # DELEGATE to tab - it manages connection in background
        # Returns True immediately (asynchronous)
        current_widget.connect_to_database(connection_name, password)

        # Update status (tab will show loading internally)
        self.action_label.setText(S.status.connecting_to.format(name=connection_name))

    def _connect_new_tab(self, connection_name: str):
        """
        Connects to a database ALWAYS creating a new tab.
        Used when CTRL+double-click or 'Connect in New Tab' in menu.
        """
        # Always create new tab WITHOUT inheriting the previous connection:
        # the deferred inherited auto-connect would race with (and override)
        # the explicit connection requested below.
        self._new_session(inherit_connection=False)
        current_widget = self._get_current_session_widget()

        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return

        # Get config (metadata only, not connection)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")

        # DELEGATE to tab - it manages connection in background
        current_widget.connect_to_database(connection_name, password)

        # Update status
        self.action_label.setText(S.status.connecting_to_new_tab.format(name=connection_name))

    def _manage_connections(self):
        """Opens the connection management dialog"""
        dialog = ConnectionsManagerDialog(self.connection_manager, theme_manager=self.theme_manager, parent=self)
        dialog.connection_selected.connect(self._connect_from_manager)
        dialog.exec()
        # Update list after closing dialog
        self._refresh_connections_list()

    def _connect_from_manager(self, name: str, config: dict):
        """Connects from the connection manager - same behavior as the side panel"""
        self._quick_connect(name)

    def _new_connection(self):
        """Opens dialog for new connection"""
        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            name, config = dialog.get_result()

            # Save connection
            self.connection_manager.save_connection_config(
                name,
                config["db_type"],
                config["host"],
                config["port"],
                config["database"],
                config.get("username", ""),
                config.get("save_password", False),
                config.get("password", ""),
                config.get("group", ""),
                config.get("use_windows_auth", False),
                config.get("color", ""),
                config.get("trust_server_certificate", True),
                config.get("http_path", ""),
                config.get("sqlserver_auth_mode", ""),
            )

            self._update_connection_status()
            self._refresh_connections_list()
            self._log_info(S.status.connection_created.format(name=name))
            self.action_label.setText(S.status.connection_created.format(name=name))

    def _edit_connection(self, connection_name: str):
        """Opens dialog to edit a specific connection"""
        # Get connection config
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        dialog = ConnectionEditDialog(
            connection_name=connection_name,
            config=config,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            name, new_config = dialog.get_result()

            # Se mudou o nome, deletar antiga
            if name != connection_name:
                self.connection_manager.delete_connection_config(connection_name)

            # Save connection
            self.connection_manager.save_connection_config(
                name,
                new_config["db_type"],
                new_config["host"],
                new_config["port"],
                new_config["database"],
                new_config.get("username", ""),
                new_config.get("save_password", False),
                new_config.get("password", ""),
                new_config.get("group", ""),
                new_config.get("use_windows_auth", False),
                new_config.get("color", ""),
                new_config.get("trust_server_certificate", True),
                new_config.get("http_path", ""),
                new_config.get("sqlserver_auth_mode", ""),
            )

            self._update_connection_status()
            self._refresh_connections_list()
            self._log_info(S.status.connection_updated.format(name=name))
            self.action_label.setText(S.status.connection_updated.format(name=name))

    def _show_warning(self, title: str, message: str):
        """Shows warning using the frameless dialog style."""
        show_warning(self, title, message)

    def _show_error(self, title: str, message: str):
        """Shows error using the frameless dialog style."""
        show_error(self, title, message)

    def _show_info(self, title: str, message: str):
        """Shows information with icon"""
        show_info(self, title, message)

    def _disconnect(self):
        """Disconnects the current session"""
        session = self.session_manager.focused_session
        if session and session.is_connected:
            # Clear session connection
            session.clear_connection()
            self._update_connection_status()
            self.action_label.setText(S.status.disconnected)

    def _update_connection_status(self):
        """Updates the connection status of the current session"""
        session = self.session_manager.focused_session

        if session and session.is_connected:
            conn_name = session.connection_name
            connector = session.connector

            # Get connection config
            config = self.connection_manager.get_connection_config(conn_name)
            host = config.get("host", "localhost") if config else "localhost"
            db = config.get("database", "") if config else ""
            db_type = config.get("db_type", "") if config else ""

            # === PAINEL LATERAL ===
            self.connection_panel.set_active_connection(conn_name, host=host, database=db, db_type=db_type)

            # Highlight active connection in list
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == conn_name:
                    self.connections_list.setCurrentItem(item)
                    break

            # === STATUSBAR ===
            self.main_statusbar.set_connection(conn_name, db_type)
            
            # Use configured connection color (or default blue)
            status_color = config.get("color", "#007acc") if config else "#007acc"
            if not status_color:
                status_color = "#007acc"
            self.statusbar.setStyleSheet(f"QStatusBar {{ background-color: {status_color}; color: white; }}")
        else:
            # === PAINEL LATERAL ===
            self.connection_panel.set_disconnected()
            self.connections_list.clearSelection()

            # === STATUSBAR ===
            self.main_statusbar.set_connection(None)
            # Barra de status cinza escuro quando desconectado
            self.statusbar.setStyleSheet("QStatusBar { background-color: #3e3e42; color: white; }}")
