"""
ConnectionController - Manages database connections

Extracted from MainWindow to follow Single Responsibility Principle.
Handles:
- Connecting to databases
- Connection dialogs (new, edit, manage)
- Connection status updates
- Disconnection
"""

from typing import TYPE_CHECKING, Optional
from PyQt6.QtCore import QObject, pyqtSignal
from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog
from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog
from src.language import S
from src.design_system.tokens import get_colors

import logging

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.ui.main_window import MainWindow


class ConnectionController(QObject):
    """Controller for database connection management"""
    
    # Signals
    connection_changed = pyqtSignal(str, str)  # connection_name, database
    connection_created = pyqtSignal(str)  # connection_name
    connection_updated = pyqtSignal(str)  # connection_name
    disconnected = pyqtSignal()
    
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._main = main_window
    
    @property
    def connection_manager(self):
        """Access to ConnectionManager"""
        return self._main.connection_manager
    
    @property
    def session_manager(self):
        """Access to SessionManager"""
        return self._main.session_manager
    
    @property
    def theme_manager(self):
        """Access to ThemeManager"""
        return self._main.theme_manager
    
    # =========================================================================
    # CONNECTION ACTIONS
    # =========================================================================
    
    def quick_connect(self, group: str, connection_name: str):
        """
        Connects to a database.
        - If there is no tab: creates a new tab
        - If current tab is connecting: creates a new tab
        - If current tab is available: switches the connection of that tab
        """
        current_widget = self._main._get_current_session_widget()
        
        # If no tab or current tab is connecting, create new one
        # (without inheriting the previous connection - we connect explicitly below)
        if not current_widget or current_widget.is_connecting():
            self._main._new_session(inherit_connection=False)
            current_widget = self._main._get_current_session_widget()
        
        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return
        
        # Get config
        config = self.connection_manager.get_connection_config(group, connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return
        
        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")
        
        # Delegate to widget - manages connection in background
        current_widget.connect_to_database(group, connection_name, password)
        
        # Update status
        self._main.action_label.setText(S.status.connecting_to.format(name=connection_name))
    
    def connect_new_tab(self, group: str, connection_name: str):
        """
        Connects to a database ALWAYS creating a new tab.
        Used for CTRL+double-click or 'Connect in New Tab' menu.
        """
        # Always create new tab WITHOUT inheriting the previous connection:
        # the deferred inherited auto-connect would race with (and override)
        # the explicit connection requested below.
        self._main._new_session(inherit_connection=False)
        current_widget = self._main._get_current_session_widget()
        
        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return
        
        config = self.connection_manager.get_connection_config(group, connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return
        
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")
        
        current_widget.connect_to_database(group, connection_name, password)
        self._main.action_label.setText(S.status.connecting_to_new_tab.format(name=connection_name))
    
    def disconnect(self):
        """Disconnects the current session"""
        session = self.session_manager.focused_session
        if session and session.is_connected:
            session.clear_connection()
            self.update_connection_status()
            self._main.action_label.setText(S.status.disconnected)
            self.disconnected.emit()
    
    # =========================================================================
    # CONNECTION DIALOGS
    # =========================================================================
    
    def manage_connections(self):
        """Opens the connection management dialog"""
        dialog = ConnectionsManagerDialog(
            self.connection_manager,
            theme_manager=self.theme_manager,
            parent=self._main
        )
        dialog.connection_selected.connect(self._connect_from_manager)
        dialog.exec()
        self._main._refresh_connections_list()
    
    def _connect_from_manager(self, group: str, name: str, config: dict):
        """Callback when connection is selected from manager dialog"""
        self.quick_connect(group, name)

    def new_connection(self):
        """Opens dialog for new connection"""
        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self._main,
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
                schema=config.get("schema", ""),
            )
            
            self.update_connection_status()
            self._main._refresh_connections_list()
            self._main._log_info(S.status.connection_created.format(name=name))
            self._main.action_label.setText(S.status.connection_created.format(name=name))
            self.connection_created.emit(name)
    
    def edit_connection(self, group: str, connection_name: str):
        """Opens dialog to edit a specific connection"""
        config = self.connection_manager.get_connection_config(group, connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return
        
        dialog = ConnectionEditDialog(
            connection_name=connection_name,
            config=config,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self._main,
        )
        
        if dialog.exec():
            name, new_config = dialog.get_result()
            new_group = new_config.get("group", "")

            from src.database.connection_manager import DuplicateConnectionError

            try:
                self.connection_manager.update_connection_config(
                    group,
                    connection_name,
                    name,
                    new_config["db_type"],
                    new_config["host"],
                    new_config["port"],
                    new_config["database"],
                    new_config.get("username", ""),
                    new_config.get("save_password", False),
                    new_config.get("password", ""),
                    new_group,
                    new_config.get("use_windows_auth", False),
                    new_config.get("color", ""),
                    new_config.get("trust_server_certificate", True),
                    new_config.get("http_path", ""),
                    new_config.get("sqlserver_auth_mode", ""),
                    schema=new_config.get("schema", ""),
                )
            except DuplicateConnectionError:
                self._show_warning(
                    S.dialogs.warning,
                    getattr(
                        S.connections_manager,
                        "dialog_duplicate_in_group",
                        "A connection with this name already exists in the selected group.",
                    ),
                )
                return
            
            self.update_connection_status()
            self._main._refresh_connections_list()
            self._main._log_info(S.status.connection_updated.format(name=name))
            self._main.action_label.setText(S.status.connection_updated.format(name=name))
            self.connection_updated.emit(name)
    
    # =========================================================================
    # STATUS UPDATES
    # =========================================================================
    
    def update_connection_status(self):
        """Updates the connection status of the current session"""
        colors = get_colors()
        session = self.session_manager.focused_session
        
        if session and session.is_connected:
            conn_name = session.connection_name
            conn_group = session.connection_group or ""

            # Get connection config
            config = self.connection_manager.get_connection_config(conn_group, conn_name)
            host = config.get("host", "localhost") if config else "localhost"
            db = config.get("database", "") if config else ""
            db_type = config.get("db_type", "") if config else ""
            
            # === SIDE PANEL ===
            self._main.connection_panel.set_active_connection(
                conn_name, host=host, database=db, db_type=db_type
            )
            
            # Highlight active connection in list
            conn_group = session.connection_group or ""
            self._main.connection_panel.connections_list.highlight_connection(conn_group, conn_name)
            
            # === STATUSBAR ===
            conn_display = f"{conn_name} @ {host}/{db}"
            self._main.connection_status_bar.setText(conn_display)
            self._main.connection_status_bar.setStyleSheet(f"""
                QLabel {{
                    color: {colors.text_inverse};
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }}
            """)
            
            # Use connection color
            status_color = config.get("color", colors.interactive_primary) if config else colors.interactive_primary
            if not status_color:
                status_color = colors.interactive_primary
            self._main.statusbar.setStyleSheet(f"""
                QStatusBar {{ background-color: {status_color}; color: {colors.text_inverse}; }}
            """)
            
            self.connection_changed.emit(conn_name, db)
        else:
            # Disconnected
            self._main.connection_panel.set_disconnected()
            self._main.connections_list.clearSelection()
            
            self._main.connection_status_bar.setText(S.status.disconnected)
            self._main.connection_status_bar.setStyleSheet(f"""
                QLabel {{
                    color: {colors.text_inverse};
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }}
            """)
            
            # Dark gray status bar when disconnected
            self._main.statusbar.setStyleSheet(f"""
                QStatusBar {{ background-color: {colors.bg_tertiary}; color: {colors.text_inverse}; }}
            """)
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _show_warning(self, title: str, message: str):
        """Shows warning dialog"""
        from src.design_system.message_box import show_warning

        show_warning(self._main, title, message)
