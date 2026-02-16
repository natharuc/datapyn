"""
Workers - Background threads for heavy operations

Completely separates processing logic from UI.
Each worker emits signals with results, never manipulates UI directly.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QThread
import sys
import traceback
from io import StringIO
from typing import Any, Dict
import pandas as pd

from src.language import S


class BaseWorker(QObject):
    """
    Abstract base for workers

    Ensures all workers follow the same pattern:
    - started: Emitted when starting
    - finished: Emitted when done (always)
    - error: Emitted if there's an error
    """

    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        """Override in subclasses"""
        raise NotImplementedError


class SqlExecutionWorker(BaseWorker):
    """
    Worker for running SQL queries in background

    Signals:
        - result_ready(DataFrame): Query executed successfully
        - error(str): Execution error
    """

    result_ready = pyqtSignal(object)  # pd.DataFrame ou None

    def __init__(self, connector, query: str):
        super().__init__()
        self.connector = connector
        self.query = query

    def run(self):
        """Run SQL query"""
        self.started.emit()

        try:
            df = self.connector.execute_query(self.query)
            self.result_ready.emit(df)
        except Exception as e:
            error_msg = S.workers.error_sql.format(msg=str(e))
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class DatabaseConnectionWorker(BaseWorker):
    """
    Worker for connecting to database in background

    Signals:
        - connection_success(): Connection established
        - error(str): Connection error
    """

    connection_success = pyqtSignal()

    def __init__(
        self,
        connection_manager,
        conn_name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        password: str = "",
        use_windows_auth: bool = False,
    ):
        super().__init__()
        self.connection_manager = connection_manager
        self.conn_name = conn_name
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth

    def run(self):
        """Connect to database"""
        self.started.emit()

        try:
            self.connection_manager.create_connection(
                self.conn_name,
                self.db_type,
                self.host,
                self.port,
                self.database,
                self.username,
                self.password,
                use_windows_auth=self.use_windows_auth,
            )
            self.connection_success.emit()
        except Exception as e:
            error_msg = S.workers.error_connection.format(msg=f"{str(e)}\n{traceback.format_exc()}")
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class PythonExecutionWorker(BaseWorker):
    """REMOVED - use PythonWorker from main_window.py"""

    execution_complete = pyqtSignal(object, str, str)

    def __init__(self, code: str, namespace: dict, is_expression: bool = False):
        super().__init__()
        raise NotImplementedError("Use PythonWorker from main_window.py - centralized execution!")


class MixedSyntaxExecutionWorker(BaseWorker):
    """
    Worker for mixed syntax execution (SQL + Python)

    Runs code with {{ SQL }} pattern integrated.

    Signals:
        - execution_complete(result_dict): Execution finished
        - error(str): Execution error
    """

    execution_complete = pyqtSignal(dict)  # {output, queries_executed, result}

    def __init__(self, executor, code: str, namespace: dict):
        super().__init__()
        self.executor = executor
        self.code = code
        self.namespace = namespace

    def run(self):
        """Run mixed syntax"""
        self.started.emit()

        try:
            result = self.executor.parse_and_execute(self.code, self.namespace)
            self.execution_complete.emit(result)
        except Exception as e:
            error_msg = S.workers.error_mixed_syntax + f"\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class DataFrameOperationWorker(BaseWorker):
    """
    Generic worker for DataFrame operations

    Useful for heavy operations like:
    - Merge of large datasets
    - Complex group by
    - Expensive transformations

    Signals:
        - operation_complete(result): Operation finished
        - error(str): Operation error
    """

    operation_complete = pyqtSignal(object)  # pd.DataFrame ou outro resultado

    def __init__(self, operation_func, *args, **kwargs):
        """
        Args:
            operation_func: Function that returns a DataFrame
            *args, **kwargs: Arguments for operation_func
        """
        super().__init__()
        self.operation_func = operation_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        """Run operation"""
        self.started.emit()

        try:
            result = self.operation_func(*self.args, **self.kwargs)
            self.operation_complete.emit(result)
        except Exception as e:
            error_msg = S.workers.error_operation.format(msg=f"{str(e)}\n{traceback.format_exc()}")
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class DatabaseSwitchWorker(BaseWorker):
    """
    Worker for switching database in background

    Signals:
        - switch_success(str): Database switched successfully (database name)
        - error(str): Switch error
    """

    switch_success = pyqtSignal(str)

    def __init__(self, connector, database_name: str):
        super().__init__()
        self.connector = connector
        self.database_name = database_name

    def run(self):
        """Switch database"""
        self.started.emit()

        try:
            self.connector.change_database(self.database_name)
            self.switch_success.emit(self.database_name)
        except Exception as e:
            error_msg = S.workers.error_db_switch.format(msg=str(e))
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class BlockConnectionWorker(BaseWorker):
    """
    Worker for connecting individual block to database in background

    Signals:
        - connection_ready(object): Connector connected
        - error(str): Connection error
    """

    connection_ready = pyqtSignal(object)

    def __init__(self, db_type: str, host: str, port: int, database: str,
                 username: str = "", password: str = "",
                 use_windows_auth: bool = False,
                 trust_server_certificate: bool = False):
        super().__init__()
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth
        self.trust_server_certificate = trust_server_certificate

    def run(self):
        """Connect to database"""
        self.started.emit()

        try:
            from ..database.database_connector import DatabaseConnector

            connector = DatabaseConnector()
            connector.connect(
                db_type=self.db_type,
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                use_windows_auth=self.use_windows_auth,
                trust_server_certificate=self.trust_server_certificate,
            )

            if connector.is_connected():
                self.connection_ready.emit(connector)
            else:
                self.error.emit(S.workers.error_failed_to_connect)
        except Exception as e:
            error_msg = S.workers.error_connection.format(msg=str(e))
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


# Utility function to run workers easily
def execute_worker(worker: BaseWorker, parent_thread: QThread = None) -> QThread:
    """
    Helper to run a worker in a separate thread

    Args:
        worker: Worker instance
        parent_thread: Parent thread (optional)

    Returns:
        QThread: Created thread

    Example:
        worker = SqlExecutionWorker(connector, "SELECT * FROM users")
        worker.result_ready.connect(self.on_result)
        worker.error.connect(self.on_error)
        thread = execute_worker(worker)
    """
    thread = QThread(parent_thread)
    worker.moveToThread(thread)

    # Connect lifecycle signals
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    # Start thread
    thread.start()

    return thread
