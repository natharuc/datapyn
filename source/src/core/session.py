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
from io import StringIO

from src.language import S


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
        self._connection_name: Optional[str] = None
        self._connector = None

        # Python namespace for variables
        self._namespace: Dict[str, Any] = {}

        # State
        self._is_executing = False
        self._last_status = S.session.status_ready
        self._code = ""  # Compatibility
        self._blocks: list = []  # Lista de blocos [{language, code}]

        # Workers ativos (threads)
        self._active_threads: list = []

    # === PROPRIEDADES ===

    @property
    def connection_name(self) -> Optional[str]:
        return self._connection_name

    @property
    def connector(self):
        return self._connector

    @property
    def is_connected(self) -> bool:
        return self._connector is not None and self._connector.is_connected

    @property
    def namespace(self) -> Dict[str, Any]:
        return self._namespace

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

    # === CONNECTION ===

    def set_connection(self, connection_name: str, connector):
        """Sets the connection for this session"""
        self._connection_name = connection_name
        self._connector = connector
        self.connection_changed.emit(connection_name)
        self.status_changed.emit(S.session.status_connected_to.format(name=connection_name))

    def connect(self, connection_name: str, password: str = "") -> bool:
        """
        Connects the session to a database using ConnectionManager

        Args:
            connection_name: Connection name
            password: Password (if required)

        Returns:
            True if connected successfully
        """
        try:
            from src.database.connection_manager import ConnectionManager
            from src.database.database_connector import DatabaseConnector

            # Disconnect current connection if it exists
            if self._connector:
                self.clear_connection()

            # Get configuration
            manager = ConnectionManager()
            config = manager.get_connection_config(connection_name)

            if not config:
                print(f"[ERROR] Connection '{connection_name}' not found")
                return False

            # Create new connection
            connector = DatabaseConnector()

            # Use provided password or saved one
            pwd = password if password else config.get("password", "")

            # Connect
            connector.connect(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=config.get("username", ""),
                password=pwd,
                use_windows_auth=config.get("use_windows_auth", False),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
            )

            if connector.is_connected:
                self.set_connection(connection_name, connector)
                return True
            else:
                return False

        except Exception as e:
            import traceback

            print(f"[ERROR] Connection failed: {str(e)}")
            traceback.print_exc()
            return False

    def disconnect(self):
        """Disconnects the database from this session"""
        if self._connector and self._connector.is_connected:
            try:
                self._connector.disconnect()
            except:
                pass
        self.clear_connection()

    def clear_connection(self):
        """Removes the connection from this session"""
        self._connection_name = None
        self._connector = None
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
            "connection_name": self._connection_name,
            "code": self._code,  # Compatibility
            "blocks": self._blocks,  # New: list of blocks
            "created_at": self.created_at.isoformat(),
            "file_path": getattr(self, "file_path", None),  # Original file path
            "original_file_type": getattr(self, "original_file_type", None),  # File type (sql/py/dpw)
            # Don't serialize namespace (may have non-serializable objects)
            # Don't serialize connector (needs to reconnect)
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "Session":
        """Creates a session from serialized data"""
        session = cls(session_id=data.get("session_id", ""), title=data.get("title", "Script"))
        session._connection_name = data.get("connection_name")
        session._code = data.get("code", "")
        session._blocks = data.get("blocks", [])
        session.file_path = data.get("file_path")  # Restore file path
        session.original_file_type = data.get("original_file_type")  # Restore file type
        if data.get("created_at"):
            try:
                session.created_at = datetime.fromisoformat(data["created_at"])
            except:
                pass
        return session

    def initialize(self, connection_manager=None):
        """
        Initializes the session after deserialization.
        Reconnects to the database if necessary.
        """
        if self._connection_name and connection_manager:
            # First try to get existing connection
            connector = connection_manager.get_connection(self._connection_name)
            if connector and connector.is_connected():
                self._connector = connector
                self.connection_changed.emit(self._connection_name)
            else:
                # Try to reconnect automatically
                try:
                    config = connection_manager.get_connection_config(self._connection_name)
                    if config:
                        connector = connection_manager.create_connection(
                            self._connection_name,
                            config["db_type"],
                            config["host"],
                            config["port"],
                            config["database"],
                            config.get("username", ""),
                            config.get("password", ""),
                            use_windows_auth=config.get("use_windows_auth", False),
                            trust_server_certificate=config.get("trust_server_certificate", False),
                            http_path=config.get("http_path", ""),
                        )
                        if connector:
                            self._connector = connector
                            self.connection_changed.emit(self._connection_name)
                except Exception as e:
                    print(f"Error reconnecting session '{self.title}' to '{self._connection_name}': {e}")
                    # Clear connection if it fails
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
