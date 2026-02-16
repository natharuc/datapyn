"""
Connection Service - Service for database connection management

Responsibilities:
- Create/remove connections
- Test connections
- Synchronize with ApplicationState
"""

from typing import Optional, Callable
from dataclasses import dataclass

from ..workers import DatabaseConnectionWorker, execute_worker
from ..state import ApplicationState
from ..database import ConnectionManager


@dataclass
class ConnectionConfig:
    """Connection configuration"""

    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str = ""
    password: str = ""
    use_windows_auth: bool = False


class ConnectionService:
    """
    Connection management service

    Synchronizes with ApplicationState and ConnectionManager.
    Executes connections via async workers.

    Example:
        service = ConnectionService()
        config = ConnectionConfig(...)
        service.connect(
            config,
            on_success=self.handle_connected,
            on_error=self.handle_error
        )
    """

    def __init__(self):
        self.app_state = ApplicationState.instance()
        self.conn_manager = ConnectionManager()

    def connect(
        self,
        config: ConnectionConfig,
        *,
        on_success: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """
        Connect to database asynchronously

        Args:
            config: Connection configuration
            on_success: Callback on success
            on_error: Callback with error message
            on_started: Callback on start
            on_finished: Callback on finish (always)
        """
        # Create worker
        worker = DatabaseConnectionWorker(
            self.conn_manager,
            config.name,
            config.db_type,
            config.host,
            config.port,
            config.database,
            config.username,
            config.password,
            config.use_windows_auth,
        )

        # Connect callbacks
        if on_started:
            worker.started.connect(on_started)

        if on_finished:
            worker.finished.connect(on_finished)

        def handle_success():
            """Internal handler for success"""
            # Add to state
            self.app_state.add_connection(
                name=config.name,
                db_type=config.db_type,
                host=config.host,
                port=config.port,
                database=config.database,
                username=config.username,
            )

            if on_success:
                on_success()

        def handle_error(error_msg: str):
            """Internal handler for error"""
            if on_error:
                on_error(error_msg)

        worker.connection_success.connect(handle_success)
        worker.error.connect(handle_error)

        # Execute worker
        execute_worker(worker)

    def disconnect(self, conn_name: str) -> tuple[bool, str]:
        """
        Disconnect from database

        Returns:
            (success, error_message)
        """
        try:
            # Remove from manager
            self.conn_manager.remove_connection(conn_name)

            # Remove from state
            self.app_state.remove_connection(conn_name)

            return True, ""
        except Exception as e:
            return False, str(e)

    def test_connection(self, config: ConnectionConfig, *, on_result: Optional[Callable[[bool, str], None]] = None):
        """
        Test connection without saving

        Args:
            config: Connection configuration
            on_result: Callback with (success, message)
        """
        # Use temporary name
        temp_name = f"_test_{config.name}"
        temp_config = ConnectionConfig(
            name=temp_name,
            db_type=config.db_type,
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.username,
            password=config.password,
            use_windows_auth=config.use_windows_auth,
        )

        def on_success():
            # Remove test connection
            self.conn_manager.remove_connection(temp_name)
            if on_result:
                on_result(True, "Connection successful!")

        def on_error(error_msg: str):
            if on_result:
                on_result(False, error_msg)

        self.connect(temp_config, on_success=on_success, on_error=on_error)

    def get_active_connection_name(self) -> Optional[str]:
        """Return active connection name"""
        conn = self.app_state.get_active_connection()
        return conn.name if conn else None

    def set_active_connection(self, conn_name: str):
        """Set active connection"""
        self.app_state.set_active_connection(conn_name)
