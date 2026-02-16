"""
Query Service - Service for SQL query execution

Responsibilities:
- Execute SQL queries via workers
- Validate queries
- Manage query history
- Handle errors consistently
"""

from typing import Optional, Callable, List
from datetime import datetime
from dataclasses import dataclass
import pandas as pd

from ..workers import SqlExecutionWorker, execute_worker
from ..state import ApplicationState


@dataclass
class QueryResult:
    """Query result"""

    dataframe: Optional[pd.DataFrame]
    query: str
    execution_time: float
    rows_affected: int
    error: Optional[str] = None
    executed_at: datetime = None

    def __post_init__(self):
        if self.executed_at is None:
            self.executed_at = datetime.now()

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def row_count(self) -> int:
        if self.dataframe is not None:
            return len(self.dataframe)
        return 0


class QueryService:
    """
    SQL query execution service

    Uses ApplicationState to get active connection.
    Executes queries via async workers.

    Example:
        service = QueryService()
        service.execute_query(
            "SELECT * FROM users",
            on_success=self.handle_result,
            on_error=self.handle_error
        )
    """

    def __init__(self):
        self.app_state = ApplicationState.instance()
        self._query_history: List[QueryResult] = []

    def execute_query(
        self,
        query: str,
        *,
        on_success: Optional[Callable[[QueryResult], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """
        Execute SQL query asynchronously

        Args:
            query: SQL to execute
            on_success: Callback with QueryResult
            on_error: Callback with error message
            on_started: Callback on start
            on_finished: Callback on finish (always)
        """
        # Validate active connection exists
        conn = self.app_state.get_active_connection()
        if not conn or not conn.is_connected:
            error_msg = "No active connection available"
            if on_error:
                on_error(error_msg)
            return

        # Create worker
        from ..database import ConnectionManager

        conn_manager = ConnectionManager()
        connector = conn_manager.get_connection(conn.name)

        if not connector:
            error_msg = f"Connection '{conn.name}' not found"
            if on_error:
                on_error(error_msg)
            return

        worker = SqlExecutionWorker(connector, query)

        # Start time
        start_time = datetime.now()

        # Connect callbacks
        if on_started:
            worker.started.connect(on_started)

        if on_finished:
            worker.finished.connect(on_finished)

        def handle_result(df: pd.DataFrame):
            """Internal handler for result"""
            execution_time = (datetime.now() - start_time).total_seconds()

            result = QueryResult(
                dataframe=df, query=query, execution_time=execution_time, rows_affected=len(df) if df is not None else 0
            )

            # Add to history
            self._query_history.append(result)

            # Update connection status
            self.app_state.update_connection_status(conn.name, True)

            if on_success:
                on_success(result)

        def handle_error(error_msg: str):
            """Internal handler for error"""
            execution_time = (datetime.now() - start_time).total_seconds()

            result = QueryResult(
                dataframe=None, query=query, execution_time=execution_time, rows_affected=0, error=error_msg
            )

            # Add to history
            self._query_history.append(result)

            if on_error:
                on_error(error_msg)

        worker.result_ready.connect(handle_result)
        worker.error.connect(handle_error)

        # Execute worker
        execute_worker(worker)

    def get_query_history(self, limit: int = 50) -> List[QueryResult]:
        """Return query history"""
        return self._query_history[-limit:]

    def clear_history(self):
        """Clear query history"""
        self._query_history.clear()

    def validate_query(self, query: str) -> tuple[bool, str]:
        """
        Validate SQL query (basic)

        Returns:
            (is_valid, error_message)
        """
        query = query.strip()

        if not query:
            return False, "Empty query"

        # Basic validations
        dangerous_keywords = ["DROP DATABASE", "DROP SCHEMA", "TRUNCATE TABLE"]
        query_upper = query.upper()

        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return False, f"Dangerous operation detected: {keyword}"

        return True, ""
