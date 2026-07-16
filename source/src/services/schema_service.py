"""
SchemaService - Background service to load and cache database structure.

Uses information_schema to load tables, columns, types and keys.
Provides data for SQL autocomplete in Monaco Editor.

Thread-safe: each load uses its own thread with safe cleanup.
Errors are silenced - user can force reload manually.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt6 import sip
from typing import Dict, List, Optional
import logging
import traceback

logger = logging.getLogger(__name__)

from src.language import S
from src.services.entity_metadata_service import build_display_data_type

SCHEMA_BUSY_SENTINEL = object()
SCHEMA_LAZY_MINIMAL = "minimal"
SCHEMA_LAZY_AUTOCOMPLETE = "autocomplete"
SCHEMA_LAZY_FULL = "full"


def is_schema_busy_result(result) -> bool:
    return result is SCHEMA_BUSY_SENTINEL


def _sql_literal(value: str) -> str:
    return str(value or "").replace("'", "''")


def _quote_databricks_identifier(value: str) -> str:
    return f"`{str(value or '').replace('`', '``')}`"


def _quote_sqlserver_identifier(value: str) -> str:
    return f"[{str(value or '').replace(']', ']]')}]"


def _databricks_relation_key(catalog: str, schema: str, table: str) -> str:
    return ".".join(part for part in (catalog, schema, table) if part)


def _row_value(row, *names: str, default=""):
    for name in names:
        try:
            value = row.get(name)
        except Exception:
            value = None
        if value is not None:
            return value

    try:
        lowered = {str(key).lower(): key for key in row.index}
        for name in names:
            key = lowered.get(name.lower())
            if key is not None:
                return row.get(key, default)
    except Exception:
        pass

    return default


class SchemaWorker(QObject):
    """Worker that loads database schema in background thread"""

    finished = pyqtSignal(dict)  # {tables: [...], columns: {...}}
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # progress message
    completed = pyqtSignal()

    def __init__(self, connector, lazy_mode: str = SCHEMA_LAZY_MINIMAL):
        super().__init__()
        self.connector = connector
        self._lazy_mode = lazy_mode or SCHEMA_LAZY_MINIMAL
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
            schema = {
                "tables": [],
                "columns": {},
                "database": "",
                "current_schema": "",
                "current_context": "",
                "databases": [],
                "db_type": "",
                "routines": [],
                "lazy": self._lazy_mode != SCHEMA_LAZY_FULL,
            }

            if self._cancelled:
                return

            # Get current database
            try:
                db_type = getattr(self.connector, "db_type", "").lower()
                schema["db_type"] = db_type
                if db_type == "databricks":
                    # For Databricks, use get_current_catalog which has proper fallback
                    db_name = self.connector.get_current_catalog() if hasattr(self.connector, "get_current_catalog") else ""
                    current_schema = self.connector.get_current_schema() if hasattr(self.connector, "get_current_schema") else ""
                    current_context = (
                        self.connector.get_current_database_context()
                        if hasattr(self.connector, "get_current_database_context")
                        else ""
                    )
                    schema["current_schema"] = current_schema or ""
                    schema["current_context"] = current_context or ""
                    logger.info(f"[SchemaService] Databricks current_catalog: '{db_name}'")
                else:
                    db_name = self.connector.get_current_database()
                    schema["current_context"] = db_name or ""
                schema["database"] = db_name or ""
            except Exception:
                schema["database"] = ""

            if self._cancelled:
                return

            load_databases = self._lazy_mode == SCHEMA_LAZY_FULL
            load_metadata = self._lazy_mode in (SCHEMA_LAZY_FULL, SCHEMA_LAZY_AUTOCOMPLETE)

            # Get list of all server databases (full schema / OE expand only)
            if load_databases:
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
            if load_metadata:
                try:
                    tables_query = self._get_tables_query()
                    df = self.connector.execute_query(tables_query)
                    db_type = getattr(self.connector, "db_type", "").lower()
                    if df is not None and len(df) > 0:
                        for _, row in df.iterrows():
                            if self._cancelled:
                                return
                            table_name = str(_row_value(row, "table_name", "TABLE_NAME", default=row.iloc[0]))
                            table_schema = str(_row_value(row, "table_schema", "TABLE_SCHEMA", default=""))
                            table_catalog = str(_row_value(row, "table_catalog", "TABLE_CATALOG", default=""))
                            # Build unique key for column matching: schema.table for multi-schema DBs
                            if db_type == "databricks":
                                table_catalog = table_catalog or schema.get("database", "")
                                table_key = _databricks_relation_key(table_catalog, table_schema, table_name)
                                if table_catalog and table_schema:
                                    schema.setdefault("catalog_schemas", {}).setdefault(table_catalog, [])
                                    if table_schema not in schema["catalog_schemas"][table_catalog]:
                                        schema["catalog_schemas"][table_catalog].append(table_schema)
                            else:
                                table_key = f"{table_schema}.{table_name}" if table_schema else table_name
                            table_info = {
                                "name": table_name,
                                "key": table_key,
                                "schema": table_schema,
                                "catalog": table_catalog,
                                "type": str(_row_value(row, "table_type", "TABLE_TYPE", default="TABLE")),
                            }
                            schema["tables"].append(table_info)
                except Exception as e:
                    logger.debug(f"Error loading tables: {e}")

            if self._cancelled:
                return

            # Get columns of all tables
            if load_metadata:
                try:
                    columns_query = self._get_columns_query()
                    df = self.connector.execute_query(columns_query)
                    if df is not None and len(df) > 0:
                        for _, row in df.iterrows():
                            if self._cancelled:
                                return
                            table_name = str(_row_value(row, "table_name", "TABLE_NAME", default=row.iloc[0]))
                            # Use schema.table_name as key to match table keys
                            table_schema = str(_row_value(row, "table_schema", "TABLE_SCHEMA", default=""))
                            table_catalog = str(_row_value(row, "table_catalog", "TABLE_CATALOG", default=""))
                            row_db_type = schema.get("db_type", "")
                            if row_db_type == "databricks":
                                table_catalog = table_catalog or schema.get("database", "")
                                table_name = _databricks_relation_key(table_catalog, table_schema, table_name)
                            elif table_schema:
                                table_name = f"{table_schema}.{table_name}"
                            col_info = {
                                "name": str(_row_value(row, "column_name", "COLUMN_NAME", default="")),
                                "type": str(_row_value(row, "data_type", "DATA_TYPE", default="")),
                                "display_type": build_display_data_type(row, row_db_type),
                                "nullable": str(_row_value(row, "is_nullable", "IS_NULLABLE", default="YES")),
                            }
                            if table_name not in schema["columns"]:
                                schema["columns"][table_name] = []
                            schema["columns"][table_name].append(col_info)
                except Exception as e:
                    logger.debug(f"Error loading columns: {e}")

            if self._cancelled:
                return

            # Get stored procedures and functions
            if load_metadata:
                try:
                    routines_query = self._get_routines_query()
                    if routines_query:
                        df = self.connector.execute_query(routines_query)
                        if df is not None and len(df) > 0:
                            for _, row in df.iterrows():
                                if self._cancelled:
                                    return
                                routine_name = str(row.get("routine_name", row.iloc[0]))
                                routine_schema = str(row.get("routine_schema", "")) if "routine_schema" in df.columns else ""
                                routine_type = str(row.get("routine_type", "PROCEDURE")) if "routine_type" in df.columns else "PROCEDURE"
                                schema["routines"].append({
                                    "name": routine_name,
                                    "schema": routine_schema,
                                    "type": routine_type.upper(),
                                })
                except Exception as e:
                    logger.debug(f"Error loading routines: {e}")

            if self._cancelled:
                return

            self.progress.emit(
                f"Schema loaded: {len(schema['tables'])} tables, "
                f"{sum(len(v) for v in schema['columns'].values())} columns, "
                f"{len(schema['routines'])} routines"
            )
            self.finished.emit(schema)

        except Exception as e:
            # Silence errors - don't interrupt user
            logger.warning(f"Error loading schema: {e}")
            try:
                self.error.emit(str(e))
            except RuntimeError:
                pass  # Qt object may have been deleted
        finally:
            try:
                self.completed.emit()
            except RuntimeError:
                pass

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
                SELECT table_catalog, table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema')
                ORDER BY table_catalog, table_schema, table_name
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
                       CHARACTER_MAXIMUM_LENGTH as character_maximum_length,
                       NUMERIC_PRECISION as numeric_precision,
                       NUMERIC_SCALE as numeric_scale,
                       DATETIME_PRECISION as datetime_precision,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
        elif db_type == "postgresql":
            return """
                SELECT table_schema, table_name, column_name, data_type, udt_name,
                       character_maximum_length, numeric_precision, numeric_scale,
                       datetime_precision, is_nullable, ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name, ordinal_position
            """
        elif db_type == "databricks":
            # Databricks: Use information_schema from current catalog
            # Include table_schema to differentiate same-named tables in different schemas
            return """
              SELECT table_catalog, table_schema, table_name, column_name, data_type,
                  full_data_type as display_type, is_nullable, ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema')
              ORDER BY table_catalog, table_schema, table_name, ordinal_position
            """
        else:
            # MySQL, MariaDB
            return """
                SELECT TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       CHARACTER_MAXIMUM_LENGTH as character_maximum_length,
                       NUMERIC_PRECISION as numeric_precision,
                       NUMERIC_SCALE as numeric_scale,
                       DATETIME_PRECISION as datetime_precision,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """

    def _get_routines_query(self) -> str | None:
        """Query to get stored procedures and functions."""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return """
                SELECT ROUTINE_SCHEMA as routine_schema,
                       ROUTINE_NAME as routine_name,
                       ROUTINE_TYPE as routine_type
                FROM INFORMATION_SCHEMA.ROUTINES
                ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
            """
        elif db_type == "postgresql":
            return """
                SELECT routine_schema, routine_name, routine_type
                FROM information_schema.routines
                WHERE routine_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY routine_schema, routine_name
            """
        elif db_type in ("mysql", "mariadb"):
            return """
                SELECT ROUTINE_SCHEMA as routine_schema,
                       ROUTINE_NAME as routine_name,
                       ROUTINE_TYPE as routine_type
                FROM INFORMATION_SCHEMA.ROUTINES
                WHERE ROUTINE_SCHEMA = DATABASE()
                ORDER BY ROUTINE_NAME
            """
        # Databricks and others don't have a standard routines view
        return None


class SchemaService(QObject):
    """
    Service that manages database schema cache.

    Loads schema in background when connection is established.
    Emits signal with loaded schema to update autocomplete.

    Thread-safe: keeps reference to active threads to avoid
    "QThread: Destroyed while thread is still running".
    """

    schema_loaded = pyqtSignal(dict, str, str, str)  # schema, connection_name, session_id, block_key
    schema_error = pyqtSignal(str)
    loading_progress = pyqtSignal(str)
    databases_loaded = pyqtSignal(str, str, list)  # connection_name, session_id, databases
    
    # Lazy loading signals (thread-safe communication)
    schemas_loaded = pyqtSignal(str, list)  # catalog_name, schemas_list
    tables_loaded = pyqtSignal(str, str, object)  # catalog_name, schema_name, tables_list|busy
    columns_loaded = pyqtSignal(str, str, str, object)  # catalog_name, schema_name, table_name, columns|busy

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_threads: list = []  # active threads to keep reference
        self._shutting_down = False
        # Cache per session: key = "session_id:connection_name" for isolation
        # Each tab can have its own database context (USE CATALOG, etc.)
        self._cache: Dict[str, dict] = {}

    def _cache_key(
        self, connection_name: str, session_id: str = "", block_key: str = ""
    ) -> str:
        """Build cache key (optional per-session and per-block isolation)."""
        key = f"{session_id}:{connection_name}" if session_id else connection_name
        if block_key:
            key = f"{key}:{block_key}"
        return key

    def load_schema(
        self,
        connector,
        connection_name: str = "",
        session_id: str = "",
        block_key: str = "",
        *,
        lazy: bool = True,
        lazy_mode: str | None = None,
    ):
        """
        Start loading schema in background.

        Thread-safe: cancels previous worker but lets thread finish naturally.

        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name (for cache)
            session_id: Session ID for per-session cache isolation
            lazy: When True (default), only load current database context
            lazy_mode: ``minimal`` | ``autocomplete`` | ``full`` (overrides lazy)
        """
        if self._shutting_down:
            return

        mode = lazy_mode or (SCHEMA_LAZY_MINIMAL if lazy else SCHEMA_LAZY_FULL)

        # Cancel previous workers (won't emit signals)
        self._cancel_pending_workers()

        # Check cache (per-session / per-block key)
        cache_key = self._cache_key(connection_name, session_id, block_key)
        if connection_name and cache_key in self._cache:
            cached = self._cache[cache_key]
            if mode == SCHEMA_LAZY_FULL or (
                mode == SCHEMA_LAZY_AUTOCOMPLETE
                and cached.get("tables")
            ):
                QTimer.singleShot(
                    0,
                    lambda c=cached, cn=connection_name, sid=session_id, bk=block_key: self.schema_loaded.emit(
                        c, cn, sid, bk
                    ),
                )
                return

        try:
            # Create worker and thread (parented to service — never deleteLater QThread)
            thread = QThread(self)
            worker = SchemaWorker(connector, lazy_mode=mode)
            worker.moveToThread(thread)

            # Connect signals
            thread.started.connect(worker.run)
            def handle_finished(schema, service=self, bk=block_key):
                if sip.isdeleted(service) or service._shutting_down:
                    return
                service._on_finished(schema, connection_name, session_id, bk)

            def cleanup_thread(service=self, active_thread=thread, active_worker=worker):
                if sip.isdeleted(service):
                    return
                service._cleanup_thread(active_thread, active_worker)

            def handle_error(error, service=self):
                if sip.isdeleted(service) or service._shutting_down:
                    return
                service._on_error(error)

            def handle_progress(message, service=self):
                if sip.isdeleted(service) or service._shutting_down:
                    return
                service.loading_progress.emit(message)

            worker.finished.connect(handle_finished)
            worker.error.connect(handle_error)
            worker.progress.connect(handle_progress)

            # Safe cleanup: worker and thread are deleted after completion
            worker.completed.connect(thread.quit)
            worker.completed.connect(worker.deleteLater)
            thread.finished.connect(cleanup_thread)

            # Keep reference to avoid garbage collection
            self._active_threads.append((thread, worker))

            thread.start()
        except Exception as e:
            logger.warning(f"Error starting schema load: {e}")

    def _on_finished(
        self,
        schema: dict,
        connection_name: str,
        session_id: str = "",
        block_key: str = "",
    ):
        """Schema loaded successfully"""
        if self._shutting_down:
            return

        try:
            if connection_name:
                cache_key = self._cache_key(connection_name, session_id, block_key)
                self._cache[cache_key] = schema
            self.schema_loaded.emit(schema, connection_name, session_id, block_key)
        except RuntimeError:
            pass  # Qt object may have been deleted

    def _on_error(self, error: str):
        """Error loading schema - silence to not disturb user"""
        if self._shutting_down:
            return

        logger.warning(f"Error loading schema: {error}")
        try:
            self.schema_error.emit(error)
        except RuntimeError:
            pass

    def get_cached_schema(
        self,
        connection_name: str,
        session_id: str = "",
        block_key: str = "",
    ) -> Optional[dict]:
        """Return cached schema or None."""
        cache_key = self._cache_key(connection_name, session_id, block_key)
        return self._cache.get(cache_key)

    def invalidate_cache(
        self,
        connection_name: str = "",
        session_id: str = "",
        block_key: str = "",
    ):
        """Invalidate cache for one connection/session/block or all."""
        if connection_name and (session_id or block_key):
            cache_key = self._cache_key(connection_name, session_id, block_key)
            self._cache.pop(cache_key, None)
            if not block_key and session_id:
                # Also drop per-block entries for this session connection
                prefix = f"{session_id}:{connection_name}:"
                for key in [k for k in self._cache if k.startswith(prefix)]:
                    self._cache.pop(key, None)
        elif connection_name and session_id:
            cache_key = self._cache_key(connection_name, session_id)
            self._cache.pop(cache_key, None)
        elif connection_name:
            keys_to_remove = [
                key for key in self._cache
                if key == connection_name or key.endswith(f":{connection_name}")
            ]
            for key in keys_to_remove:
                self._cache.pop(key, None)
        elif session_id:
            # Clear all caches for this session
            keys_to_remove = [k for k in self._cache if k.startswith(f"{session_id}:")]
            for k in keys_to_remove:
                self._cache.pop(k, None)
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
        """Remove finished thread from active list; worker only (thread is parented)."""
        try:
            self._active_threads = [
                (t, w) for t, w in self._active_threads if t is not thread
            ]
            if worker:
                worker.deleteLater()
        except RuntimeError:
            pass

    def cleanup(self):
        """Clean up resources - wait for threads to finish with timeout"""
        self._shutting_down = True

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

    def load_databases(self, connector, connection_name: str, session_id: str = ""):
        """Load server database/catalog list on demand (Object Explorer expand)."""

        def _run():
            try:
                worker = SchemaWorker(connector, lazy_mode=SCHEMA_LAZY_FULL)
                query = worker._get_databases_query()
                df = connector.execute_query(query)
                if df is None or len(df) == 0:
                    return []
                return [str(row.iloc[0]) for _, row in df.iterrows()]
            except Exception as exc:
                logger.warning("Error loading database list: %s", exc)
                return []

        self._run_in_thread_with_signal(
            _run,
            lambda result: self.databases_loaded.emit(
                connection_name, session_id, result or []
            ),
        )

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
                    query = f"SHOW SCHEMAS IN {_quote_databricks_identifier(catalog_name)}"
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
            from src.database.database_connector import QueryBusyError

            try:
                db_type = getattr(connector, "db_type", "").lower()
                tables = []
                namespace_name = str(catalog_name or "")
                schema_literal = _sql_literal(schema_name)
                
                if db_type == "databricks":
                    catalog_ident = _quote_databricks_identifier(catalog_name)
                    schema_ident = _quote_databricks_identifier(schema_name)

                    # Query the target catalog directly instead of changing connection context.
                    try:
                        query = f"""
                            SELECT table_name, table_type
                            FROM {catalog_ident}.information_schema.tables
                            WHERE table_schema = '{schema_literal}'
                            ORDER BY table_name
                        """
                        df = connector.execute_query(query)
                    except Exception as info_err:
                        logger.debug(f"Cannot query information_schema for {catalog_name}.{schema_name}: {info_err}")
                        try:
                            query = f"SHOW TABLES IN {catalog_ident}.{schema_ident}"
                            df = connector.execute_query(query)
                        except Exception as tbl_err:
                            logger.debug(f"Cannot list tables in {catalog_name}.{schema_name}: {tbl_err}")
                            return []
                    
                    if df is not None and len(df) > 0:
                        for _, row in df.iterrows():
                            # SHOW TABLES returns: database, tableName, isTemporary
                            table_name = str(_row_value(row, "table_name", "tableName", "TABLE_NAME", default=row.iloc[1] if len(row) > 1 else row.iloc[0]))
                            table_type = str(_row_value(row, "table_type", "TABLE_TYPE", default="TABLE"))
                            tables.append({
                                "name": table_name,
                                "schema": schema_name,
                                "catalog": catalog_name,
                                "key": _databricks_relation_key(catalog_name, schema_name, table_name),
                                "type": table_type or "TABLE",
                            })
                elif db_type in ("mssql", "sqlserver"):
                    query_source = "INFORMATION_SCHEMA.TABLES"
                    if namespace_name:
                        query_source = f"{_quote_sqlserver_identifier(namespace_name)}.INFORMATION_SCHEMA.TABLES"

                    query = f"""
                        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                        FROM {query_source}
                    """
                    if schema_name:
                        query += f"\n                        WHERE TABLE_SCHEMA = '{schema_literal}'"
                    query += "\n                        ORDER BY TABLE_SCHEMA, TABLE_NAME\n                    "
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            table_schema = str(row.get("TABLE_SCHEMA", row.get("table_schema", row.iloc[0] if len(row) > 0 else "")))
                            tables.append({
                                "name": str(row.get("TABLE_NAME", row.get("table_name", row.iloc[1] if len(row) > 1 else row.iloc[0]))),
                                "schema": table_schema,
                                "database": namespace_name,
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
                elif db_type in ("mysql", "mariadb"):
                    target_database = namespace_name or schema_name
                    database_literal = _sql_literal(target_database)
                    query = f"""
                        SELECT TABLE_NAME, TABLE_TYPE
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = '{database_literal}'
                        ORDER BY TABLE_NAME
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            tables.append({
                                "name": str(row.get("TABLE_NAME", row.iloc[0])),
                                "schema": target_database,
                                "database": target_database,
                                "type": str(row.get("TABLE_TYPE", "TABLE")),
                            })
                else:
                    return []

                return tables
            except QueryBusyError as e:
                logger.debug(
                    "Deferred table metadata load (connection busy) for %s.%s: %s",
                    catalog_name,
                    schema_name,
                    e,
                )
                return SCHEMA_BUSY_SENTINEL
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
            from src.database.database_connector import QueryBusyError

            try:
                db_type = getattr(connector, "db_type", "").lower()
                columns = []
                namespace_name = str(_catalog_name or "")
                schema_literal = _sql_literal(_schema_name)
                table_literal = _sql_literal(_table_name)
                
                if db_type == "databricks":
                    catalog_ident = _quote_databricks_identifier(_catalog_name)
                    schema_ident = _quote_databricks_identifier(_schema_name)
                    table_ident = _quote_databricks_identifier(_table_name)

                    # Query the target catalog directly instead of changing connection context.
                    try:
                        query = f"""
                            SELECT column_name, data_type, full_data_type as display_type,
                                   is_nullable, ordinal_position
                            FROM {catalog_ident}.information_schema.columns
                            WHERE table_schema = '{schema_literal}'
                              AND table_name = '{table_literal}'
                            ORDER BY ordinal_position
                        """
                        df = connector.execute_query(query)
                    except Exception as info_err:
                        logger.debug(f"Cannot query columns for {_catalog_name}.{_schema_name}.{_table_name}: {info_err}")
                        try:
                            query = f"DESCRIBE TABLE {catalog_ident}.{schema_ident}.{table_ident}"
                            df = connector.execute_query(query)
                        except Exception as desc_err:
                            logger.debug(f"Cannot describe {_catalog_name}.{_schema_name}.{_table_name}: {desc_err}")
                            return []
                    
                    if df is not None:
                        for idx, row in df.iterrows():
                            col_name = str(_row_value(row, "column_name", "col_name", "COLUMN_NAME", default=row.iloc[0]))
                            # Skip metadata rows (start with # or empty)
                            if not col_name or col_name.startswith("#"):
                                continue
                            columns.append({
                                "name": col_name,
                                "type": str(_row_value(row, "data_type", "DATA_TYPE", default=row.iloc[1] if len(row) > 1 else "")),
                                "display_type": build_display_data_type(row, db_type),
                                "nullable": str(_row_value(row, "is_nullable", "IS_NULLABLE", default="YES")),
                            })
                elif db_type in ("mssql", "sqlserver"):
                    query_source = "INFORMATION_SCHEMA.COLUMNS"
                    if namespace_name:
                        query_source = f"{_quote_sqlserver_identifier(namespace_name)}.INFORMATION_SCHEMA.COLUMNS"
                    query = f"""
                        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                               NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION,
                               IS_NULLABLE
                        FROM {query_source}
                        WHERE TABLE_SCHEMA = '{schema_literal}' AND TABLE_NAME = '{table_literal}'
                        ORDER BY ORDINAL_POSITION
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            columns.append({
                                "name": str(row.get("COLUMN_NAME", row.iloc[0])),
                                "type": str(row.get("DATA_TYPE", "")),
                                "display_type": build_display_data_type(row, db_type),
                                "nullable": str(row.get("IS_NULLABLE", "YES")),
                            })
                elif db_type == "postgresql":
                    query = f"""
                        SELECT column_name, data_type, udt_name,
                               character_maximum_length, numeric_precision,
                               numeric_scale, datetime_precision, is_nullable
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
                                "display_type": build_display_data_type(row, db_type),
                                "nullable": str(row.get("is_nullable", "YES")),
                            })
                elif db_type in ("mysql", "mariadb"):
                    target_database = namespace_name or _schema_name
                    database_literal = _sql_literal(target_database)
                    query = f"""
                        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                               NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION,
                               IS_NULLABLE
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = '{database_literal}' AND TABLE_NAME = '{table_literal}'
                        ORDER BY ORDINAL_POSITION
                    """
                    df = connector.execute_query(query)
                    if df is not None:
                        for _, row in df.iterrows():
                            columns.append({
                                "name": str(row.get("COLUMN_NAME", row.iloc[0])),
                                "type": str(row.get("DATA_TYPE", "")),
                                "display_type": build_display_data_type(row, db_type),
                                "nullable": str(row.get("IS_NULLABLE", "YES")),
                            })
                else:
                    return []

                return columns
            except QueryBusyError as e:
                logger.debug(
                    "Deferred column metadata load (connection busy) for %s: %s",
                    _table_name,
                    e,
                )
                return SCHEMA_BUSY_SENTINEL
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
        thread = QThread(self)

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
        
        def safe_callback(result):
            if sip.isdeleted(self) or self._shutting_down:
                return
            try:
                callback(result)
            except RuntimeError:
                pass

        def cleanup_thread():
            if sip.isdeleted(self):
                return
            self._cleanup_thread(thread, worker)

        worker = Worker(func)
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.result_ready.connect(safe_callback)
        worker.finished.connect(thread.quit)
        thread.finished.connect(cleanup_thread)
        
        self._active_threads.append((thread, worker))
        thread.start()

    def update_cached_schema(self, connection_name: str, schema: dict, session_id: str = ""):
        """Replace cached schema for a connection/session after lazy metadata loads."""
        if not connection_name or not isinstance(schema, dict):
            return
        cache_key = self._cache_key(connection_name, session_id)
        self._cache[cache_key] = schema
