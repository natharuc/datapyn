"""
Session - Represents an independent work session

Each editor tab is a session that contains:
- Its own database connection
- Its own Python namespace (variables)
- Execution state
- Its own threads
"""

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from typing import Optional, Dict, Any
from datetime import datetime
import traceback
import sys
import logging
from io import StringIO

from src.language import S
from src.core.connection_ref import ConnectionRef, resolve_by_name_only

logger = logging.getLogger(__name__)


class Session(QObject):
    """
    Represents an independent work session.

    Each session has its own:
    - Database connection
    - Python namespace (variables)
    - Execution state
    - Workers/Threads
    """

    # Signals to notify state changes
    connection_changed = pyqtSignal(str)  # connection_name ou ''
    status_changed = pyqtSignal(str)  # status text
    execution_started = pyqtSignal(str)  # mode (sql, python, cross)
    execution_finished = pyqtSignal(bool, str)  # success, message
    variables_changed = pyqtSignal(dict)  # namespace

    def __init__(self, session_id: str, title: str = None):
        super().__init__()

        self.session_id = session_id
        self.title = title or S.session.default_title
        self.created_at = datetime.now()

        # Connection reference (not the object itself)
        self._connection_group: Optional[str] = None
        self._connection_name: Optional[str] = None
        self._connector = None
        self._database_context: str = ""

        # Python namespace for variables
        self._namespace: Dict[str, Any] = {}

        # State
        self._is_executing = False
        self._last_status = S.session.status_ready
        self._code = ""  # Compatibility
        self._blocks: list = []  # Lista de blocos [{language, code}]
        self._shared_parameters: list = []
        self._shared_parameters_enabled: bool = True
        self.notification_config: Optional[Dict[str, Any]] = None
        self.result_view_state: Dict[str, Any] = {}
        self.pynia: Dict[str, Any] = {}

        # Workers ativos (threads)
        self._active_threads: list = []

    # === PROPRIEDADES ===

    @property
    def connection_name(self) -> Optional[str]:
        return self._connection_name

    @property
    def connection_group(self) -> Optional[str]:
        return self._connection_group

    @property
    def connection_ref(self) -> Optional[ConnectionRef]:
        if not self._connection_name:
            return None
        return ConnectionRef(group=self._connection_group or "", name=self._connection_name)

    @property
    def connection_display(self) -> str:
        ref = self.connection_ref
        return ref.display() if ref else ""

    @property
    def connector(self):
        return self._connector

    @property
    def database_context(self) -> str:
        return self._database_context

    @database_context.setter
    def database_context(self, value: str):
        self._database_context = str(value or "")

    @property
    def is_connected(self) -> bool:
        connector = self._connector
        if connector is None or getattr(connector, "_abandoned", False) is True:
            return False
        is_connected = getattr(connector, "is_connected", False)
        try:
            return bool(is_connected() if callable(is_connected) else is_connected)
        except Exception:
            return False

    @property
    def namespace(self) -> Dict[str, Any]:
        return self._namespace

    def effective_namespace(self) -> Dict[str, Any]:
        """Runtime namespace plus active connection metadata (db_host, db_username, …)."""
        variables = dict(self._namespace)
        self.enrich_connection_variables(variables)
        return variables

    def enrich_connection_variables(self, variables: Dict[str, Any]) -> None:
        """Add db_* entries from the active connector (same as the Variables panel)."""
        connector = self._connector
        conn_name = self._connection_name
        if not connector or not conn_name:
            return

        try:
            if getattr(connector, "engine", None) is not None:
                variables["db_engine"] = connector.engine

            if getattr(connector, "db_type", None):
                variables["db_type"] = connector.db_type

            variables["db_connection_name"] = conn_name

            if getattr(connector, "engine", None) is not None:
                try:
                    variables["db_connection_string"] = str(connector.engine.url)
                except Exception:
                    pass

            params = getattr(connector, "connection_params", None) or {}
            if "host" in params:
                variables["db_host"] = params["host"]
            if "port" in params:
                variables["db_port"] = params["port"]
            if "database" in params:
                variables["db_database"] = params["database"]
            if "username" in params:
                variables["db_username"] = params["username"]
        except Exception:
            pass

    @property
    def is_executing(self) -> bool:
        return self._is_executing

    @property
    def code(self) -> str:
        return self._code

    @code.setter
    def code(self, value: str):
        self._code = value

    @property
    def blocks(self) -> list:
        """List of blocks [{language, code}]"""
        return self._blocks

    @blocks.setter
    def blocks(self, value: list):
        self._blocks = value

    @property
    def shared_parameters(self) -> list:
        return self._shared_parameters

    @shared_parameters.setter
    def shared_parameters(self, value: list):
        self._shared_parameters = value if isinstance(value, list) else []

    @property
    def shared_parameters_enabled(self) -> bool:
        return self._shared_parameters_enabled

    @shared_parameters_enabled.setter
    def shared_parameters_enabled(self, value: bool):
        self._shared_parameters_enabled = bool(value)

    # === CONNECTION ===

    def _connector_database_context(self, connector) -> str:
        get_context = getattr(connector, "get_current_database_context", None)
        if callable(get_context):
            try:
                return str(get_context() or "")
            except Exception:
                return ""

        get_database = getattr(connector, "get_current_database", None)
        if callable(get_database):
            try:
                return str(get_database() or "")
            except Exception:
                return ""

        return ""

    def _apply_saved_database_context(self, connector):
        if not connector:
            return

        target_context = str(self._database_context or "").strip()
        if not target_context:
            return

        current_context = self._connector_database_context(connector)
        if current_context and current_context.lower() == target_context.lower():
            return

        try:
            connector.change_database(target_context)
        except Exception as exc:
            logger.warning(
                "Failed to restore database context '%s': %s",
                target_context,
                exc,
            )

    def set_connection(self, connection_name: str, connector, connection_group: str = ""):
        """Sets the connection for this session"""
        self._connection_group = connection_group or None
        self._connection_name = connection_name
        self._connector = connector
        self._database_context = self._connector_database_context(connector)
        display = ConnectionRef(group=connection_group or "", name=connection_name).display()
        self.connection_changed.emit(connection_name)
        self.status_changed.emit(S.session.status_connected_to.format(name=display))

    def connect(self, group_or_name: str, name: str = "", password: str = "") -> bool:
        """
        Connects the session to a database using ConnectionManager.

        Args:
            group_or_name: Group name, or connection name when called legacy-style
            name: Connection name when group is provided
            password: Password (if required)

        Returns:
            True if connected successfully
        """
        try:
            from src.database.connection_manager import ConnectionManager
            from src.database.database_connector import DatabaseConnector

            if self._connector:
                self.clear_connection()

            manager = ConnectionManager()
            if name:
                group = group_or_name or ""
                config = manager.get_connection_config(group, name)
                ref = ConnectionRef(group=group, name=name)
            else:
                ref = resolve_by_name_only(manager, group_or_name)
                if ref is None:
                    logger.error(f"Connection '{group_or_name}' not found")
                    return False
                config = manager.get_connection_config(ref.group, ref.name)

            if not config:
                logger.error(f"Connection not found")
                return False

            connector = DatabaseConnector()
            pwd = password if password else config.get("password", "")

            connector.connect(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=config.get("username", ""),
                password=pwd,
                use_windows_auth=config.get("use_windows_auth", False),
                sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
                schema=config.get("schema") or config.get("databricks_schema") or "",
            )

            is_connected = getattr(connector, "is_connected", False)
            if callable(is_connected):
                is_connected = is_connected()
            if is_connected:
                self._apply_saved_database_context(connector)
                self.set_connection(ref.name, connector, ref.group)
                return True
            return False

        except Exception as e:
            import traceback

            logger.error(f"Connection failed: {e}")
            traceback.print_exc()
            return False

    def disconnect(self):
        """Disconnects the database from this session"""
        if self._connector and self._connector.is_connected:
            try:
                self._connector.disconnect()
            except Exception:
                pass
        self.clear_connection()

    def sleep(self):
        """Release the underlying DB connection but remember the connection name.

        The idle reaper calls this instead of ``disconnect()`` so the session can
        auto-reconnect transparently on the next query: the SQL execute path sees
        ``connection_name`` still set plus ``connector is None`` and triggers the
        ``BlockAutoConnectWorker`` reconnect (a brief "connecting" status, no error).

        Unlike ``disconnect()``/``clear_connection()`` this does NOT emit
        ``connection_changed("")`` or the "disconnected" status, so the UI keeps
        showing the session as connected -- the reconnect is invisible to the
        user, which is the desired "transparent" behaviour.
        """
        if self._connector and self._connector.is_connected:
            try:
                self._connector.disconnect()
            except Exception:
                pass
        # Drop the live connector but keep _connection_name so the next query
        # knows which connection to restore. _database_context is preserved too.
        self._connector = None

    def clear_connection(self):
        """Removes the connection from this session"""
        self._connection_group = None
        self._connection_name = None
        self._connector = None
        self._database_context = ""
        self.connection_changed.emit("")
        self.status_changed.emit(S.session.status_disconnected)

    # === NAMESPACE (VARIABLES) ===

    def set_variable(self, name: str, value: Any):
        """Sets a variable in the namespace"""
        self._namespace[name] = value
        self.variables_changed.emit(self._namespace)

    def get_variable(self, name: str) -> Any:
        """Gets a variable from the namespace"""
        return self._namespace.get(name)

    def clear_namespace(self):
        """Clears all variables"""
        self._namespace.clear()
        self.variables_changed.emit(self._namespace)

    def update_namespace(self, variables: Dict[str, Any]):
        """Updates multiple variables"""
        self._namespace.update(variables)
        self.variables_changed.emit(self._namespace)

    def restore_dataframe_variables(self, variables: Dict[str, Any]) -> None:
        """Restore persisted DataFrame variables into the session namespace."""
        if not variables:
            return
        self._namespace.update(variables)
        self.variables_changed.emit(self._namespace)

    # === EXECUTION ===

    def start_execution(self, mode: str):
        """Marks execution start"""
        self._is_executing = True
        self.execution_started.emit(mode)

    def finish_execution(self, success: bool, message: str):
        """Marks execution end"""
        self._is_executing = False
        self._last_status = message
        self.execution_finished.emit(success, message)
        self.status_changed.emit(message)

    # === THREAD MANAGEMENT ===

    def register_thread(self, thread: QThread):
        """Registers an active thread"""
        self._active_threads.append(thread)

    def unregister_thread(self, thread: QThread):
        """Removes a thread from the list"""
        if thread in self._active_threads:
            self._active_threads.remove(thread)

    def stop_all_threads(self):
        """Stops all active threads"""
        for thread in self._active_threads[:]:
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)
            self._active_threads.remove(thread)

    # === SERIALIZAÇÃO ===

    def serialize(self) -> Dict[str, Any]:
        """Serializes the session for persistence"""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "connection_group": self._connection_group,
            "connection_name": self._connection_name,
            "database_context": self._database_context,
            "code": self._code,  # Compatibility
            "blocks": self._blocks,  # New: list of blocks
            "shared_parameters": self._shared_parameters,
            "shared_parameters_enabled": self._shared_parameters_enabled,
            "notification_config": self.notification_config,
            "result_view_state": self.result_view_state,
            "created_at": self.created_at.isoformat(),
            "file_path": getattr(self, "file_path", None),  # Original file path
            "original_file_type": getattr(self, "original_file_type", None),  # File type (sql/py/dpw)
            "pynia": getattr(self, "pynia", None) or {},
            # Don't serialize namespace (may have non-serializable objects)
            # Don't serialize connector (needs to reconnect)
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "Session":
        """Creates a session from serialized data"""
        session = cls(session_id=data.get("session_id", ""), title=data.get("title", "Script"))
        session._connection_group = data.get("connection_group")
        session._connection_name = data.get("connection_name")
        session._database_context = data.get("database_context", "") or ""
        session._code = data.get("code", "")
        session._blocks = data.get("blocks", [])
        session._shared_parameters = data.get("shared_parameters", []) or []
        session._shared_parameters_enabled = bool(data.get("shared_parameters_enabled", True))
        session.notification_config = data.get("notification_config")
        result_view_state = data.get("result_view_state", {})
        session.result_view_state = result_view_state if isinstance(result_view_state, dict) else {}
        session.file_path = data.get("file_path")  # Restore file path
        session.original_file_type = data.get("original_file_type")  # Restore file type
        session.pynia = data.get("pynia") or {}
        if data.get("created_at"):
            try:
                session.created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass
        return session

    def initialize(self, connection_manager=None, reconnect: bool = True):
        """
        Initializes the session after deserialization.
        Reconnects to the database if necessary.
        """
        if self._connection_name and connection_manager:
            ref = self.connection_ref
            if ref is None:
                return
            if not ref.group:
                resolved = resolve_by_name_only(connection_manager, ref.name)
                if resolved is not None:
                    ref = resolved

            connector = connection_manager.get_connection(ref.group, ref.name)
            if connector and connector.is_connected():
                self._connection_group = ref.group or None
                self._connection_name = ref.name
                self._apply_saved_database_context(connector)
                self._connector = connector
                self.connection_changed.emit(self._connection_name)
            elif reconnect:
                try:
                    config = connection_manager.get_connection_config(ref.group, ref.name)
                    if config:
                        connector = connection_manager.create_connection(
                            ref,
                            config["db_type"],
                            config["host"],
                            config["port"],
                            config["database"],
                            config.get("username", ""),
                            config.get("password", ""),
                            use_windows_auth=config.get("use_windows_auth", False),
                            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                            trust_server_certificate=config.get("trust_server_certificate", False),
                            http_path=config.get("http_path", ""),
                        )
                        if connector:
                            self._connection_group = ref.group or None
                            self._connection_name = ref.name
                            self._apply_saved_database_context(connector)
                            self._connector = connector
                            self.connection_changed.emit(self._connection_name)
                except Exception as e:
                    logger.error(
                        f"Error reconnecting session '{self.title}' to '{ref.display()}': {e}"
                    )
                    self._connection_group = None
                    self._connection_name = None

    # === CLEANUP ===

    def cleanup(self):
        """Cleans up session resources safely"""
        try:
            self.stop_all_threads()
        except Exception:
            pass  # Ignore errors during cleanup

        try:
            self._namespace.clear()
        except Exception:
            pass  # Ignore errors during cleanup
        # Don't disconnect the database here (may be shared)

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass  # Prevent crashes during object destruction
