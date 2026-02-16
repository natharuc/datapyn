"""
SchemaService - Background service to load and cache database structure.

Uses information_schema to load tables, columns, types and keys.
Provides data for SQL autocomplete in Monaco Editor.

Thread-safe: each load uses its own thread with safe cleanup.
Errors are silenced - user can force reload manually.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from typing import Dict, List, Optional
import logging
import traceback

logger = logging.getLogger(__name__)

from src.language import S


class SchemaWorker(QObject):
    """Worker that loads database schema in background thread"""

    finished = pyqtSignal(dict)  # {tables: [...], columns: {...}}
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # progress message

    def __init__(self, connector):
        super().__init__()
        self.connector = connector
        self._cancelled = False

    def cancel(self):
        """Mark worker as cancelled"""
        self._cancelled = True

    def run(self):
        """Load complete schema from database via information_schema.

        Silences individual errors - returns partial schema if something fails.
        """
        try:
            self.progress.emit(S.schema_service.loading)
            schema = {"tables": [], "columns": {}, "database": "", "databases": []}

            if self._cancelled:
                return

            # Get current database
            try:
                db_name = self.connector.get_current_database()
                schema["database"] = db_name or ""
            except Exception:
                schema["database"] = ""

            if self._cancelled:
                return

            # Get list of all server databases
            try:
                databases_query = self._get_databases_query()
                df = self.connector.execute_query(databases_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        db = str(row.iloc[0])
                        schema["databases"].append(db)
            except Exception as e:
                logger.debug(f"Error loading database list: {e}")

            if self._cancelled:
                return

            # Get tables and views
            try:
                tables_query = self._get_tables_query()
                df = self.connector.execute_query(tables_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        if self._cancelled:
                            return
                        table_info = {
                            "name": str(row.get("table_name", row.iloc[0])),
                            "schema": str(row.get("table_schema", "")) if "table_schema" in df.columns else "",
                            "type": str(row.get("table_type", "TABLE")) if "table_type" in df.columns else "TABLE",
                        }
                        schema["tables"].append(table_info)
            except Exception as e:
                logger.debug(f"Error loading tables: {e}")

            if self._cancelled:
                return

            # Get columns of all tables
            try:
                columns_query = self._get_columns_query()
                df = self.connector.execute_query(columns_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        if self._cancelled:
                            return
                        table_name = str(row.get("table_name", row.iloc[0]))
                        col_info = {
                            "name": str(row.get("column_name", row.iloc[1])),
                            "type": str(row.get("data_type", "")) if "data_type" in df.columns else "",
                            "nullable": str(row.get("is_nullable", "YES")) if "is_nullable" in df.columns else "YES",
                        }
                        if table_name not in schema["columns"]:
                            schema["columns"][table_name] = []
                        schema["columns"][table_name].append(col_info)
            except Exception as e:
                logger.debug(f"Error loading columns: {e}")

            if self._cancelled:
                return

            self.progress.emit(
                f"Schema loaded: {len(schema['tables'])} tables, "
                f"{sum(len(v) for v in schema['columns'].values())} columns"
            )
            self.finished.emit(schema)

        except Exception as e:
            # Silence errors - don't interrupt user
            logger.warning(f"Error loading schema: {e}")
            try:
                self.error.emit(str(e))
            except RuntimeError:
                pass  # Qt object may have been deleted

    def _get_databases_query(self) -> str:
        """Query to get list of all server databases"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name"
        elif db_type == "postgresql":
            return "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
        else:
            # MySQL, MariaDB
            return "SHOW DATABASES"

    def _get_tables_query(self) -> str:
        """Query to get tables - compatible with all DBMS"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return """
                SELECT TABLE_SCHEMA as table_schema,
                       TABLE_NAME as table_name,
                       TABLE_TYPE as table_type
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        elif db_type == "postgresql":
            return """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """
        else:
            # MySQL, MariaDB and others
            return """
                SELECT TABLE_SCHEMA as table_schema,
                       TABLE_NAME as table_name,
                       TABLE_TYPE as table_type
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """

    def _get_columns_query(self) -> str:
        """Query to get columns - compatible with all DBMS"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return """
                SELECT TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """
        elif db_type == "postgresql":
            return """
                SELECT table_name, column_name, data_type, is_nullable,
                       ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_name, ordinal_position
            """
        else:
            # MySQL, MariaDB
            return """
                SELECT TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """


class SchemaService(QObject):
    """
    Service that manages database schema cache.

    Loads schema in background when connection is established.
    Emits signal with loaded schema to update autocomplete.

    Thread-safe: keeps reference to active threads to avoid
    "QThread: Destroyed while thread is still running".
    """

    schema_loaded = pyqtSignal(dict, str)  # Emits complete schema + connection_name
    schema_error = pyqtSignal(str)
    loading_progress = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_threads: list = []  # active threads to keep reference
        self._cache: Dict[str, dict] = {}  # connection_name -> schema

    def load_schema(self, connector, connection_name: str = ""):
        """
        Start loading schema in background.

        Thread-safe: cancels previous worker but lets thread finish naturally.

        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name (for cache)
        """
        # Cancel previous workers (won't emit signals)
        self._cancel_pending_workers()

        # Check cache
        if connection_name and connection_name in self._cache:
            self.schema_loaded.emit(self._cache[connection_name], connection_name)
            return

        try:
            # Create worker and thread
            thread = QThread()
            worker = SchemaWorker(connector)
            worker.moveToThread(thread)

            # Connect signals
            thread.started.connect(worker.run)
            worker.finished.connect(lambda schema: self._on_finished(schema, connection_name))
            worker.error.connect(self._on_error)
            worker.progress.connect(self.loading_progress.emit)

            # Safe cleanup: worker and thread are deleted after completion
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            thread.finished.connect(lambda: self._cleanup_thread(thread, worker))

            # Keep reference to avoid garbage collection
            self._active_threads.append((thread, worker))

            thread.start()
        except Exception as e:
            logger.warning(f"Error starting schema load: {e}")

    def _on_finished(self, schema: dict, connection_name: str):
        """Schema loaded successfully"""
        try:
            if connection_name:
                self._cache[connection_name] = schema
            self.schema_loaded.emit(schema, connection_name)
        except RuntimeError:
            pass  # Qt object may have been deleted

    def _on_error(self, error: str):
        """Error loading schema - silence to not disturb user"""
        logger.warning(f"Error loading schema: {error}")
        try:
            self.schema_error.emit(error)
        except RuntimeError:
            pass

    def get_cached_schema(self, connection_name: str) -> Optional[dict]:
        """Return cached schema or None"""
        return self._cache.get(connection_name)

    def invalidate_cache(self, connection_name: str = ""):
        """Invalidate cache for one connection or all"""
        if connection_name:
            self._cache.pop(connection_name, None)
        else:
            self._cache.clear()

    def _cancel_pending_workers(self):
        """Cancel pending workers (mark as cancelled)"""
        for thread, worker in self._active_threads:
            try:
                if worker:
                    worker.cancel()
            except RuntimeError:
                pass

    def _cleanup_thread(self, thread, worker):
        """Remove finished thread from active list and schedule deleteLater"""
        try:
            self._active_threads = [
                (t, w) for t, w in self._active_threads if t is not thread
            ]
            if worker:
                worker.deleteLater()
            if thread:
                thread.deleteLater()
        except RuntimeError:
            pass

    def cleanup(self):
        """Clean up resources - wait for threads to finish with timeout"""
        # Cancel all workers
        for thread, worker in self._active_threads:
            try:
                if worker:
                    worker.cancel()
            except RuntimeError:
                pass

        # Wait for threads to finish
        for thread, worker in self._active_threads:
            try:
                if thread and thread.isRunning():
                    thread.quit()
                    thread.wait(2000)  # 2s timeout
            except RuntimeError:
                pass

        self._active_threads.clear()
        self._cache.clear()
