"""
Application State - Centralized state management

Implements a pattern similar to Redux/Zustand:
- Centralized state
- Changes via actions
- Observers notified automatically
- Single source of truth

Manages:
- Active connections
- Python variable namespace
- Open sessions
- Settings
- Theme
"""

from PyQt6.QtCore import QObject, pyqtSignal
from typing import Any, Dict, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd


@dataclass
class ConnectionState:
    """Connection state"""

    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    is_connected: bool = False
    last_query: Optional[str] = None
    last_query_time: Optional[datetime] = None


@dataclass
class SessionState:
    """Session state (code tab)"""

    session_id: str
    title: str
    code: str = ""
    language: str = "sql"  # 'sql', 'python', 'mixed'
    is_modified: bool = False
    file_path: Optional[str] = None
    last_execution_time: Optional[datetime] = None


@dataclass
class ApplicationConfig:
    """Application settings"""

    theme: str = "dark"
    font_size: int = 14
    auto_save: bool = True
    show_line_numbers: bool = True
    word_wrap: bool = False
    tab_size: int = 4


class ApplicationState(QObject):
    """
    Global application state

    Singleton that centralizes all state.
    Emits signals when state changes.

    Example:
        state = ApplicationState.instance()
        state.connection_changed.connect(self.on_connection_changed)
        state.set_active_connection("my_db")
    """

    # Signals
    connection_changed = pyqtSignal(str)  # connection_name
    connection_added = pyqtSignal(str)  # connection_name
    connection_removed = pyqtSignal(str)  # connection_name

    session_changed = pyqtSignal(str)  # session_id
    session_added = pyqtSignal(str)  # session_id
    session_removed = pyqtSignal(str)  # session_id
    active_session_changed = pyqtSignal(str)  # session_id

    variable_changed = pyqtSignal(str, object)  # (name, value)
    variable_added = pyqtSignal(str)  # name
    variable_removed = pyqtSignal(str)  # name

    config_changed = pyqtSignal(str, object)  # (key, value)
    theme_changed = pyqtSignal(str)  # theme_name

    _instance: Optional["ApplicationState"] = None

    @classmethod
    def instance(cls) -> "ApplicationState":
        """Return singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()

        # State
        self._connections: Dict[str, ConnectionState] = {}
        self._active_connection: Optional[str] = None

        self._sessions: Dict[str, SessionState] = {}
        self._active_session: Optional[str] = None

        self._namespace: Dict[str, Any] = {}

        self._config = ApplicationConfig()

    # =========================================================================
    # Connections
    # =========================================================================

    def add_connection(self, name: str, db_type: str, host: str, port: int, database: str, username: str = ""):
        """Add new connection to state"""
        conn = ConnectionState(
            name=name, db_type=db_type, host=host, port=port, database=database, username=username, is_connected=True
        )
        self._connections[name] = conn
        self.connection_added.emit(name)

        # If it's the first connection, make it active
        if self._active_connection is None:
            self.set_active_connection(name)

    def remove_connection(self, name: str):
        """Remove connection from state"""
        if name in self._connections:
            del self._connections[name]
            self.connection_removed.emit(name)

            # If it was active, clear
            if self._active_connection == name:
                self._active_connection = None
                self.connection_changed.emit("")

    def set_active_connection(self, name: str):
        """Set active connection"""
        if name in self._connections or name == "":
            self._active_connection = name if name else None
            self.connection_changed.emit(name)

    def get_active_connection(self) -> Optional[ConnectionState]:
        """Return active connection"""
        if self._active_connection:
            return self._connections.get(self._active_connection)
        return None

    def get_connection(self, name: str) -> Optional[ConnectionState]:
        """Return connection by name"""
        return self._connections.get(name)

    def get_all_connections(self) -> List[ConnectionState]:
        """Return all connections"""
        return list(self._connections.values())

    def update_connection_status(self, name: str, is_connected: bool):
        """Update connection status"""
        if name in self._connections:
            self._connections[name].is_connected = is_connected
            self.connection_changed.emit(name)

    # =========================================================================
    # Sessions
    # =========================================================================

    def add_session(self, session_id: str, title: str, language: str = "sql") -> SessionState:
        """Add new session"""
        session = SessionState(session_id=session_id, title=title, language=language)
        self._sessions[session_id] = session
        self.session_added.emit(session_id)

        # If it's the first session, make it active
        if self._active_session is None:
            self.set_active_session(session_id)

        return session

    def remove_session(self, session_id: str):
        """Remove session"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self.session_removed.emit(session_id)

            # If it was active, clear
            if self._active_session == session_id:
                self._active_session = None
                self.active_session_changed.emit("")

    def set_active_session(self, session_id: str):
        """Set active session"""
        if session_id in self._sessions or session_id == "":
            self._active_session = session_id if session_id else None
            self.active_session_changed.emit(session_id)

    def get_active_session(self) -> Optional[SessionState]:
        """Return active session"""
        if self._active_session:
            return self._sessions.get(self._active_session)
        return None

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Return session by ID"""
        return self._sessions.get(session_id)

    def get_all_sessions(self) -> List[SessionState]:
        """Return all sessions"""
        return list(self._sessions.values())

    def update_session_code(self, session_id: str, code: str):
        """Update session code"""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.code = code
            session.is_modified = True
            self.session_changed.emit(session_id)

    def mark_session_saved(self, session_id: str, file_path: str = None):
        """Mark session as saved"""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.is_modified = False
            if file_path:
                session.file_path = file_path
            self.session_changed.emit(session_id)

    # =========================================================================
    # Variables (Python Namespace)
    # =========================================================================

    def set_variable(self, name: str, value: Any):
        """Set variable in namespace"""
        is_new = name not in self._namespace
        self._namespace[name] = value

        if is_new:
            self.variable_added.emit(name)
        else:
            self.variable_changed.emit(name, value)

    def get_variable(self, name: str, default=None) -> Any:
        """Return variable from namespace"""
        return self._namespace.get(name, default)

    def remove_variable(self, name: str):
        """Remove variable from namespace"""
        if name in self._namespace:
            del self._namespace[name]
            self.variable_removed.emit(name)

    def get_all_variables(self) -> Dict[str, Any]:
        """Return all variables"""
        return self._namespace.copy()

    def get_namespace(self) -> Dict[str, Any]:
        """Return complete namespace (direct reference)"""
        return self._namespace

    def clear_namespace(self):
        """Clear namespace (keep builtins)"""
        user_vars = [k for k in self._namespace.keys() if not k.startswith("__")]
        for var in user_vars:
            self.remove_variable(var)

    # =========================================================================
    # Configuration
    # =========================================================================

    def get_config(self) -> ApplicationConfig:
        """Return configuration"""
        return self._config

    def set_config_value(self, key: str, value: Any):
        """Set configuration value"""
        if hasattr(self._config, key):
            setattr(self._config, key, value)
            self.config_changed.emit(key, value)

            # Theme has special signal
            if key == "theme":
                self.theme_changed.emit(value)

    def get_theme(self) -> str:
        """Return active theme"""
        return self._config.theme

    def set_theme(self, theme: str):
        """Set theme"""
        self.set_config_value("theme", theme)

    # =========================================================================
    # Utilities
    # =========================================================================

    def reset(self):
        """Reset all state (useful for tests)"""
        self._connections.clear()
        self._active_connection = None
        self._sessions.clear()
        self._active_session = None
        self._namespace.clear()
        self._config = ApplicationConfig()
