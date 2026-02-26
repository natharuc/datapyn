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
                db_type = getattr(self.connector, "db_type", "").lower()
                if db_type == "databricks":
                    # For Databricks, use get_current_catalog which has proper fallback
                    db_name = self.connector.get_current_catalog() if hasattr(self.connector, "get_current_catalog") else ""
                    logger.info(f"[SchemaService] Databricks current_catalog: '{db_name}'")
                else:
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
                db_type = getattr(self.connector, "db_type", "").lower()
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        db = str(row.iloc[0])
                        schema["databases"].append(db)
                    if db_type == "databricks":
                        logger.info(f"[SchemaService] Databricks catalogs: {schema['databases']}")
            except Exception as e:
                logger.debug(f"Error loading database list: {e}")

            if self._cancelled:
                return

            # Get tables and views
            try:
                tables_query = self._get_tables_query()
                df = self.connector.execute_query(tables_query)
                db_type = getattr(self.connector, "db_type", "").lower()
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        if self._cancelled:
                            return
                        table_name = str(row.get("table_name", row.iloc[0]))
                        table_schema = str(row.get("table_schema", "")) if "table_schema" in df.columns else ""
                        # Build unique key for column matching: schema.table for multi-schema DBs
                        table_key = f"{table_schema}.{table_name}" if table_schema else table_name
                        table_info = {
                            "name": table_name,
                            "key": table_key,
                            "schema": table_schema,
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
                        # Use schema.table_name as key to match table keys
                        if "table_schema" in df.columns:
                            table_schema = str(row.get("table_schema", ""))
                            if table_schema:
                                table_name = f"{table_schema}.{table_name}"
                        col_info = {
                            "name": str(row.get("column_name", "")),
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
            # PostgreSQL: only show the currently connected database
            # (switching databases requires a new connection)
            return "SELECT current_database()"
        elif db_type == "databricks":
            return "SHOW CATALOGS"
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
        elif db_type == "databricks":
            # Databricks: Use information_schema from current catalog
            return """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema')
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
                SELECT TABLE_SCHEMA as table_schema,
                       TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
        elif db_type == "postgresql":
            return """
                SELECT table_schema, table_name, column_name, data_type, is_nullable,
                       ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name, ordinal_position
            """
        elif db_type == "databricks":
            # Databricks: Use information_schema from current catalog
            # Include table_schema to differentiate same-named tables in different schemas
            return """
                SELECT table_schema, table_name, column_name, data_type, is_nullable,
                       ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema')
                ORDER BY table_schema, table_name, ordinal_position
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
    
    # Lazy loading signals (thread-safe communication)
    schemas_loaded = pyqtSignal(str, list)  # catalog_name, schemas_list
    tables_loaded = pyqtSignal(str, str, list)  # catalog_name, schema_name, tables_list
    columns_loaded = pyqtSignal(str, str, str, list)  # catalog_name, schema_name, table_name, columns_list

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

    # =========================================================================
    # Lazy loading methods for Object Explorer
    # =========================================================================

    def load_schemas_for_catalog(self, connector, connection_name: str, catalog_name: str):
        """Load schemas for a catalog (Databricks) in background.
        
        Results are emitted via schemas_loaded signal (thread-safe).
        
        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name
            catalog_name: Catalog name to load schemas for
        """
        def _run():
            try:
                db_type = getattr(connector, "db_type", "").lower()
                schemas = []
                if db_type == "databricks":
                    # Query schemas from catalog
                    query = f"SHOW SCHEMAS IN `{catalog_name}`"
                    df = connector.execute_query(query)
                    if df is not None and len(df) > 0:
                        for _, row in df.iterrows():
                            schema_name = str(row.iloc[0])
                            if schema_name.lower() not in ("information_schema",):
                                schemas.append(schema_name)
                return schemas
            except Exception as e:
                logger.warning(f"Error loading schemas for {catalog_name}: {e}")
                return []

        self._run_in_thread_with_signal(_run, lambda result: self.schemas_loaded.emit(catalog_name, result))

    def load_tables_for_schema(self, connector, connection_name: str, catalog_name: str, schema_name: str):
        """Load tables for a schema in background.
        
        Results are emitted via tables_loaded signal (thread-safe).
        
        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name
            catalog_name: Catalog name (empty for non-Databricks)
            schema_name: Schema name to load tables for
        """
        def _run():
            try:
                db_type = getattr(connector, "db_type", "").lower()
                tables = []
                
                if db_type == "databricks":
                    # Ensure we're in the correct catalog context before querying tables
                    try:
                        connector.execute_query(f"USE CATALOG `{catalog_name}`")
                    except Exception as cat_err:
                        # Permission denied or catalog not accessible - return empty
                        logger.debug(f"Cannot switch to catalog {catalog_name}: {cat_err}")
                        return []
                    
                    # Query tables from schema (now in correct catalog context)
                    try:
                        query = f"SHOW TABLES IN `{schema_name}`"
                        df = connector.execute_query(query)
                    except Exception as tbl_err:
                        # Schema not accessible - return empty
                        logger.debug(f"Cannot list tables in {catalog_name}.{schema_name}: {tbl_err}")
                        return []
                    
                    if df is not None and len(df) > 0:
                        for _, row in df.iterrows():
                            # SHOW TABLES returns: database, tableName, isTemporary
                            table_name = str(row.get("tableName", row.iloc[1] if len(row) > 1 else row.iloc[0]))
                            tables.append({
                                "name": table_name,
                                "schema": schema_name,
                                "type": "TABLE",
                            })
                elif db_type in ("mssql", "sqlserver"):
                    query = f"""
                        SELECT TABLE_NAME, TABLE_TYPE
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = '{schema_name}'
                        ORDER BY TABLE_NAME
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            tables.append({
                                "name": str(row.get("TABLE_NAME", row.iloc[0])),
                                "schema": schema_name,
                                "type": str(row.get("TABLE_TYPE", "TABLE")),
                            })
                elif db_type == "postgresql":
                    query = f"""
                        SELECT table_name, table_type
                        FROM information_schema.tables
                        WHERE table_schema = '{schema_name}'
                        ORDER BY table_name
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            tables.append({
                                "name": str(row.get("table_name", row.iloc[0])),
                                "schema": schema_name,
                                "type": str(row.get("table_type", "TABLE")),
                            })
                else:
                    # MySQL/MariaDB - schema = database
                    query = f"""
                        SELECT TABLE_NAME, TABLE_TYPE
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = '{schema_name}'
                        ORDER BY TABLE_NAME
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            tables.append({
                                "name": str(row.get("TABLE_NAME", row.iloc[0])),
                                "schema": schema_name,
                                "type": str(row.get("TABLE_TYPE", "TABLE")),
                            })

                return tables
            except Exception as e:
                logger.warning(f"Error loading tables for {catalog_name}.{schema_name}: {e}")
                return []

        self._run_in_thread_with_signal(_run, lambda result: self.tables_loaded.emit(catalog_name, schema_name, result))

    def load_columns_for_table(self, connector, connection_name: str, catalog_name: str, schema_name: str, table_name: str):
        """Load columns for a table in background.
        
        Results are emitted via columns_loaded signal (thread-safe).
        
        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name
            catalog_name: Catalog name (empty for non-Databricks)
            schema_name: Schema name
            table_name: Table name to load columns for
        """
        # Store table_name for closure
        _table_name = table_name
        _catalog_name = catalog_name
        _schema_name = schema_name
        
        def _run():
            try:
                db_type = getattr(connector, "db_type", "").lower()
                columns = []
                
                if db_type == "databricks":
                    # Ensure we're in the correct catalog context
                    try:
                        connector.execute_query(f"USE CATALOG `{_catalog_name}`")
                    except Exception as cat_err:
                        logger.debug(f"Cannot switch to catalog {_catalog_name}: {cat_err}")
                        return []
                    
                    # Use DESCRIBE (now in correct catalog context)
                    try:
                        query = f"DESCRIBE `{_schema_name}`.`{_table_name}`"
                        df = connector.execute_query(query)
                    except Exception as desc_err:
                        logger.debug(f"Cannot describe {_catalog_name}.{_schema_name}.{_table_name}: {desc_err}")
                        return []
                    
                    if df is not None:
                        for idx, row in df.iterrows():
                            col_name = str(row.get("col_name", row.iloc[0]))
                            # Skip metadata rows (start with # or empty)
                            if not col_name or col_name.startswith("#"):
                                continue
                            columns.append({
                                "name": col_name,
                                "type": str(row.get("data_type", row.iloc[1] if len(row) > 1 else "")),
                                "nullable": "YES",  # DESCRIBE doesn't give nullable info
                            })
                elif db_type in ("mssql", "sqlserver"):
                    query = f"""
                        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = '{_schema_name}' AND TABLE_NAME = '{_table_name}'
                        ORDER BY ORDINAL_POSITION
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            columns.append({
                                "name": str(row.get("COLUMN_NAME", row.iloc[0])),
                                "type": str(row.get("DATA_TYPE", "")),
                                "nullable": str(row.get("IS_NULLABLE", "YES")),
                            })
                elif db_type == "postgresql":
                    query = f"""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = '{_schema_name}' AND table_name = '{_table_name}'
                        ORDER BY ordinal_position
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            columns.append({
                                "name": str(row.get("column_name", row.iloc[0])),
                                "type": str(row.get("data_type", "")),
                                "nullable": str(row.get("is_nullable", "YES")),
                            })
                else:
                    # MySQL/MariaDB
                    query = f"""
                        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = '{_schema_name}' AND TABLE_NAME = '{_table_name}'
                        ORDER BY ORDINAL_POSITION
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            columns.append({
                                "name": str(row.get("COLUMN_NAME", row.iloc[0])),
                                "type": str(row.get("DATA_TYPE", "")),
                                "nullable": str(row.get("IS_NULLABLE", "YES")),
                            })

                return columns
            except Exception as e:
                logger.warning(f"Error loading columns for {_table_name}: {e}")
                return []

        self._run_in_thread_with_signal(_run, lambda result: self.columns_loaded.emit(_catalog_name, _schema_name, _table_name, result))

    def _run_in_thread_with_signal(self, func, callback):
        """Run a function in a background thread and call callback with result on main thread.
        
        Args:
            func: Function that returns a result (runs in background)
            callback: Function to call with result (runs on main thread via signal)
        """
        thread = QThread()
        
        class Worker(QObject):
            finished = pyqtSignal()
            result_ready = pyqtSignal(object)
            
            def __init__(self, fn):
                super().__init__()
                self.fn = fn
                self._cancelled = False
            
            def cancel(self):
                self._cancelled = True
            
            def run(self):
                try:
                    result = self.fn()
                    if not self._cancelled:
                        self.result_ready.emit(result)
                except Exception as e:
                    logger.warning(f"Worker error: {e}")
                    if not self._cancelled:
                        self.result_ready.emit(None)
                finally:
                    self.finished.emit()
        
        worker = Worker(func)
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.result_ready.connect(callback)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._cleanup_thread(thread, worker))
        
        self._active_threads.append((thread, worker))
        thread.start()
