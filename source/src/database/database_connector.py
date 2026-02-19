"""
Database connector with support for multiple DBMS
"""

from typing import Optional, Dict, Any, List, Union
import pandas as pd
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
import logging
import pyodbc
import json
import os
from pathlib import Path


logger = logging.getLogger(__name__)


def _get_oauth_token_cache_path(host: str) -> Path:
    """Get path for OAuth token cache file.
    
    Tokens are stored per-host in the user's app config directory.
    """
    # Use a safe filename derived from the host
    safe_host = host.replace(".", "_").replace(":", "_").replace("/", "_")
    config_dir = Path.home() / ".datapyn" / "oauth_cache"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / f"databricks_{safe_host}.json"


class DatabricksOAuthTokenCache:
    """Persists OAuth tokens to disk for Databricks connections.
    
    This allows OAuth to cache the token and only prompt for browser
    authentication when the token expires.
    """
    
    def __init__(self, file_path: Path):
        self._file_path = file_path
    
    def persist(self, hostname: str, token):
        """Save the OAuth token to disk."""
        try:
            data = {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
            }
            self._file_path.write_text(json.dumps(data), encoding="utf-8")
            logger.debug(f"OAuth token persisted to {self._file_path}")
        except Exception as e:
            logger.warning(f"Failed to persist OAuth token: {e}")
    
    def read(self, hostname: str):
        """Read the cached OAuth token from disk."""
        try:
            if self._file_path.exists():
                data = json.loads(self._file_path.read_text(encoding="utf-8"))
                # Import here to avoid import errors when databricks is not installed
                from databricks.sql.experimental.oauth_persistence import OAuthToken
                return OAuthToken(
                    access_token=data.get("access_token", ""),
                    refresh_token=data.get("refresh_token", ""),
                )
        except Exception as e:
            logger.warning(f"Failed to read cached OAuth token: {e}")
        return None


class DatabaseConnector:
    """Class to manage connections with different databases"""

    SUPPORTED_DATABASES = {
        "sqlserver": "SQL Server",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "postgresql": "PostgreSQL",
        "databricks": "Databricks",
    }

    def __init__(self):
        self.engine: Optional[Engine] = None
        self.connection_params: Dict[str, Any] = {}
        self.db_type: str = ""
        self._active_raw_conn = None  # Reference for cancellation
        self._active_cursor = None  # Cursor reference for cancellation
        self._cancelled = False  # Cancellation flag

    def connect(
        self, db_type: str, host: str, port: int, database: str, username: str = "", password: str = "", **kwargs
    ) -> bool:
        """
        Connect to database

        Args:
            db_type: Database type (sqlserver, mysql, mariadb, postgresql)
            host: Server address
            port: Server port
            database: Database name
            username: User (optional for Windows Auth)
            password: Password (optional for Windows Auth)
            **kwargs: Additional parameters (use_windows_auth=True for SQL Server)

        Returns:
            bool: True if connected successfully
        """
        try:
            connection_string, connect_args = self._build_connection_string(
                db_type, host, port, database, username, password, **kwargs
            )

            self.engine = create_engine(connection_string, pool_pre_ping=True, connect_args=connect_args)

            # Register pool event to ensure every connection
            # pulled from pool uses correct database (solves problem
            # with USE <db> that only affects one pool connection)
            if db_type == "sqlserver":
                connector_ref = self

                @event.listens_for(self.engine, "checkout")
                def on_checkout(dbapi_conn, connection_record, connection_proxy):
                    current_db = connector_ref.connection_params.get("database", "")
                    if current_db:
                        try:
                            cursor = dbapi_conn.cursor()
                            cursor.execute(f"USE [{current_db}]")
                            cursor.close()
                        except Exception:
                            pass  # Silence - USE in batch will catch error

            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self.db_type = db_type
            self.connection_params = {"host": host, "port": port, "database": database, "username": username}

            logger.info(f"Connected to {self.SUPPORTED_DATABASES[db_type]}: {host}/{database}")
            return True

        except Exception as e:
            logger.error(f"Database connection error: {str(e)}")
            raise

    def _get_available_odbc_driver(self) -> str:
        """
        Detect SQL Server ODBC driver installed on the system.
        Returns the most recent available driver in priority order.

        Returns:
            str: Name of ODBC driver found

        Raises:
            RuntimeError: If no compatible driver is found
        """
        # Priority order: most recent drivers first
        preferred_drivers = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13.1 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "ODBC Driver 11 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server Native Client 10.0",
            "SQL Server",  # Old driver, last option
        ]

        try:
            available_drivers = pyodbc.drivers()
            logger.info(f"Available ODBC drivers: {available_drivers}")

            for driver in preferred_drivers:
                if driver in available_drivers:
                    logger.info(f"Selected ODBC driver: {driver}")
                    return driver

            # If no preferred driver found, try using any with "SQL Server"
            for driver in available_drivers:
                if "SQL Server" in driver:
                    logger.warning(f"Using alternative driver: {driver}")
                    return driver

        except Exception as e:
            logger.error(f"Error listing ODBC drivers: {e}")

        raise RuntimeError(
            "No SQL Server ODBC driver found.\n"
            "Install 'ODBC Driver 18 for SQL Server' at:\n"
            "https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
        )

    def _build_connection_string(
        self, db_type: str, host: str, port: int, database: str, username: str, password: str, **kwargs
    ) -> tuple:
        """Build connection string based on database type.
        
        Returns:
            tuple: (connection_string, connect_args_dict)
        """
        from urllib.parse import quote_plus

        if db_type == "sqlserver":
            # Auto-detect driver or use specified one
            driver = kwargs.get("driver")
            if not driver:
                driver = self._get_available_odbc_driver()

            use_windows_auth = kwargs.get("use_windows_auth", False)
            trust_cert = kwargs.get("trust_server_certificate", False)

            # Detect LocalDB - uses named pipes, not TCP/IP
            is_localdb = "(localdb)" in host.lower()

            if is_localdb:
                # LocalDB format: SERVER=(localdb)\InstanceName (no port)
                # LocalDB always uses Windows Authentication
                server_part = f"SERVER={host}"
                use_windows_auth = True
            else:
                # Standard SQL Server format: SERVER=host,port
                server_part = f"SERVER={host},{port}"

            # Use direct ODBC connection string
            if use_windows_auth:
                # Windows Authentication
                odbc_string = (
                    f"DRIVER={{{driver}}};"
                    f"{server_part};"
                    f"DATABASE={database};"
                    f"Trusted_Connection=yes"
                )
            else:
                # SQL Server Authentication
                odbc_string = (
                    f"DRIVER={{{driver}}};"
                    f"{server_part};"
                    f"DATABASE={database};"
                    f"UID={username};"
                    f"PWD={password}"
                )

            # Adicionar TrustServerCertificate se solicitado
            if trust_cert:
                odbc_string += ";TrustServerCertificate=yes"

            return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_string)}", {}

        elif db_type == "mysql":
            # URL encode username and password for special characters
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"mysql+pymysql://{user_encoded}:{pass_encoded}@{host}:{port}/{database}?charset=utf8mb4", {}

        elif db_type == "mariadb":
            # URL encode username and password for special characters
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"mariadb+mariadbconnector://{user_encoded}:{pass_encoded}@{host}:{port}/{database}", {}

        elif db_type == "postgresql":
            # URL encode username and password for special characters
            # Important for Azure PostgreSQL where user is "user@server"
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"postgresql+psycopg2://{user_encoded}:{pass_encoded}@{host}:{port}/{database}", {}

        elif db_type == "databricks":
            # Databricks SQL Warehouse connection
            # Uses databricks-sql-connector with SQLAlchemy dialect
            http_path = kwargs.get("http_path", "")
            access_token = password
            connect_args = {}
            
            if access_token:
                # Use PAT (Personal Access Token) - no OAuth browser flow
                token_encoded = quote_plus(access_token)
                # Format: databricks://token:<access_token>@<host>:443
                # Using 'token' as username tells the driver to use PAT authentication
                conn_str = f"databricks://token:{token_encoded}@{host}:{port}"
            else:
                # Use OAuth with token cache - will open browser only on first time or when token expires
                # Empty username/password triggers OAuth flow
                conn_str = f"databricks://@{host}:{port}"
                
                # Setup OAuth token persistence for caching
                cache_path = _get_oauth_token_cache_path(host)
                oauth_cache = DatabricksOAuthTokenCache(cache_path)
                connect_args["auth_type"] = "databricks-oauth"
                connect_args["experimental_oauth_persistence"] = oauth_cache
                logger.info(f"Using OAuth with token cache at: {cache_path}")
            
            # Add query parameters
            params = []
            if http_path:
                params.append(f"http_path={quote_plus(http_path)}")
            if database:
                params.append(f"catalog={quote_plus(database)}")
                params.append("schema=default")
            if params:
                conn_str += "?" + "&".join(params)
            return conn_str, connect_args

        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def execute_query(self, query: str) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        """
        Execute SQL query and return DataFrame or list of DataFrames

        Supports multiple SQL commands. For queries with multiple SELECTs,
        returns a list of DataFrames (one for each SELECT).

        Args:
            query: SQL query to execute (can contain multiple commands)

        Returns:
            Union[pd.DataFrame, List[pd.DataFrame]]: Query result or list of results
        """
        if not self.engine:
            raise ConnectionError("No active database connection")

        try:
            # Detect USE command to update current database
            import re

            use_match = re.search(r"\bUSE\s+[\[`]?(\w+)[\]`]?\s*;?\s*$", query.strip(), re.IGNORECASE | re.MULTILINE)
            if use_match:
                new_db = use_match.group(1)
                logger.info(f"Detected USE command {new_db}")
                # Update current database
                self.connection_params["database"] = new_db

            # Remove GO commands (SQL Server)
            query_clean = query.replace("GO\n", "\n").replace("GO ", " ")

            # For SQL Server, execute as batch and capture results
            if self.db_type == "sqlserver":
                return self._execute_mssql_batch(query_clean)

            # For other databases, use legacy logic
            return self._execute_generic_query(query_clean)

        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            raise

    def cancel_query(self):
        """Cancel running query.

        Works for SQL Server (pyodbc) and PostgreSQL (psycopg2).
        For MySQL/MariaDB, interrupts via flag.
        """
        self._cancelled = True

        try:
            if self.db_type == "sqlserver":
                # pyodbc: cancel() is a Cursor method, not Connection
                cursor = self._active_cursor
                if cursor is not None:
                    cursor.cancel()
                    logger.info("SQL Server query cancelled via cursor.cancel()")
                else:
                    logger.warning("Cancel requested but cursor not available")
            elif self.db_type == "postgresql":
                # psycopg2: cancel() sends cancel request to server
                raw_conn = self._active_raw_conn
                if raw_conn is not None and hasattr(raw_conn, "cancel"):
                    raw_conn.cancel()
                    logger.info("PostgreSQL query cancelled via connection.cancel()")
            else:
                # MySQL/MariaDB: no native cancel in driver,
                # but _cancelled flag will interrupt processing
                logger.info(f"Cancel requested for {self.db_type} (via flag)")
        except Exception as e:
            logger.warning(f"Error cancelling query: {e}")

    def _execute_mssql_batch(self, query: str) -> pd.DataFrame:
        """Execute SQL Server batch and return last result"""
        import pyodbc

        self._cancelled = False
        last_error = None  # Declare BEFORE try to be accessible in finally
        cursor = None
        raw_conn = None

        try:
            # Use raw pyodbc connection to access nextset()
            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn  # Expose for cancellation
            cursor = raw_conn.cursor()
            self._active_cursor = cursor  # Expose cursor for cancellation

            # CRITICAL: Ensure this pool connection is in the correct database.
            # SQLAlchemy pool can return any connection, and a previous USE
            # command may have been executed in another pool connection.
            current_db = self.connection_params.get("database", "")
            if current_db:
                try:
                    cursor.execute(f"USE [{current_db}]")
                    # Consume possible result set from USE
                    while cursor.nextset():
                        pass
                except Exception as e:
                    logger.warning(f"Failed to set database [{current_db}]: {e}")

            # Execute complete query
            cursor.execute(query)

            # Capture all result sets
            dataframes = []
            result_set_count = 0

            # Process all result sets in a loop
            while True:
                result_set_count += 1

                try:
                    if cursor.description:  # Has columns (is a SELECT)
                        # Preserve original column case
                        columns = [col[0] for col in cursor.description]
                        rows = cursor.fetchall()
                        logger.info(f"Result set {result_set_count}: {len(rows)} rows, columns: {columns}")
                        if rows:
                            df = pd.DataFrame.from_records(rows, columns=columns)
                            dataframes.append(df)
                    else:
                        logger.info(f"Result set {result_set_count}: no description (doesn't return data)")
                except pyodbc.Error as e:
                    last_error = str(e)
                    logger.error(f"PYODBC error in result set {result_set_count}: {last_error}")
                    break  # Stop on error
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"GENERIC error in result set {result_set_count}: {last_error}")
                    break  # Stop on error

                # Try next result set
                try:
                    logger.info(f"Trying nextset after result set {result_set_count}...")
                    has_next = cursor.nextset()
                    logger.info(f"nextset returned: {has_next}")

                    # CRITICAL: pyodbc DOESN'T throw exception in nextset() when there's an error!
                    # The error stays in cursor.messages - we need to check BEFORE continuing
                    if hasattr(cursor, "messages") and cursor.messages:
                        logger.info(f"Messages after nextset: {cursor.messages}")
                        for msg in cursor.messages:
                            # Messages are tuples: (sql_state, message)
                            if len(msg) >= 2:
                                sql_state = msg[0]
                                error_msg = msg[1]
                                logger.info(f"SQL State: {sql_state}, Message: {error_msg}")

                                # SQL error states start with class 01-99 (except 01 which is warning)
                                # 42S02 = Invalid object name
                                # 42000 = Syntax error
                                if sql_state and sql_state != "01000":  # 01000 is informational
                                    last_error = error_msg
                                    logger.error(f"SQL ERROR detected in messages: {last_error}")
                                    break

                    if last_error:
                        break  # Stop if error found in messages

                    if not has_next:
                        break
                except pyodbc.Error as e:
                    # Error trying next result set - could be SQL error
                    last_error = str(e)
                    logger.error(f"PYODBC error processing nextset: {last_error}")
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"GENERIC error processing nextset: {last_error}")
                    break

            # If there was an error, throw exception to report to user
            if last_error:
                raise Exception(last_error)

            # Commit
            raw_conn.commit()

            logger.info(f"Total result sets: {result_set_count}, DataFrames captured: {len(dataframes)}")

            # If captured multiple results, return list of DataFrames
            if len(dataframes) > 1:
                logger.info(f"Returning list with {len(dataframes)} DataFrames")
                return dataframes

            # If captured single result, return directly
            if dataframes:
                logger.info(f"Returning single DataFrame with {len(dataframes[0])} rows")
                return dataframes[0]

            # No results - return success message
            rows_affected = cursor.rowcount
            if rows_affected >= 0:
                msg = f"Command executed successfully. {rows_affected} row(s) affected."
            else:
                msg = "Command executed successfully."

            logger.info(msg)
            return pd.DataFrame({"Result": [msg]})

        except Exception as e:
            logger.error(f"Error executing SQL Server batch: {str(e)}")
            raise  # Re-throw error for user to see

        finally:
            self._active_raw_conn = None  # Clear reference
            self._active_cursor = None  # Clear cursor reference
            # Close cursor and connection
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

            if raw_conn:
                try:
                    raw_conn.close()
                except:
                    pass

    def _execute_generic_query(self, query: str) -> pd.DataFrame:
        """Execute generic query for non-MSSQL databases"""
        # Split by semicolon to detect multiple commands
        commands = [cmd.strip() for cmd in query.split(";") if cmd.strip()]

        if len(commands) > 1:
            # Multiple commands - execute all and capture SELECT results
            dataframes = []

            with self.engine.connect() as conn:
                for cmd in commands:
                    cmd_upper = cmd.strip().upper()

                    if cmd_upper.startswith("SELECT") or cmd_upper.startswith("SHOW"):
                        # Is SELECT - capture result
                        try:
                            df = pd.read_sql(cmd, self.engine)
                            logger.info(f"SELECT executed: {len(df)} rows returned")
                            dataframes.append(df)
                        except Exception as e:
                            logger.error(f"Error executing SELECT: {str(e)}")
                            raise
                    else:
                        # Not SELECT - execute as statement
                        conn.execute(text(cmd))

                conn.commit()

            # If captured multiple results, return list of DataFrames
            if len(dataframes) > 1:
                logger.info(f"Returning list with {len(dataframes)} DataFrames")
                return dataframes

            # If captured single result, return directly
            if dataframes:
                logger.info(f"Returning single DataFrame with {len(dataframes[0])} rows")
                return dataframes[0]

            # No SELECT executed - return success message
            msg = "Commands executed successfully."
            logger.info(msg)
            return pd.DataFrame({"Result": [msg]})
        else:
            # Single command - try to fetch results
            try:
                df = pd.read_sql(query, self.engine)
                logger.info(f"Query executed successfully. Rows returned: {len(df)}")
                return df
            except:
                # Doesn't return data - execute as statement
                with self.engine.connect() as conn:
                    result = conn.execute(text(query))
                    conn.commit()
                    rows_affected = result.rowcount

                    if rows_affected >= 0:
                        msg = f"Command executed successfully. {rows_affected} row(s) affected."
                    else:
                        msg = "Command executed successfully."

                    logger.info(msg)
                    return pd.DataFrame({"Result": [msg]})

    def execute_statement(self, statement: str) -> int:
        """
        Execute SQL statement (INSERT, UPDATE, DELETE, etc)

        Args:
            statement: SQL statement to execute

        Returns:
            int: Number of affected rows
        """
        if not self.engine:
            raise ConnectionError("No active database connection")

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(statement))
                conn.commit()
                rows_affected = result.rowcount
                logger.info(f"Statement executed. Affected rows: {rows_affected}")
                return rows_affected
        except Exception as e:
            logger.error(f"Error executing statement: {str(e)}")
            raise

    def change_database(self, database: str) -> bool:
        """
        Change current database

        Args:
            database: New database name (or catalog.schema for Databricks)

        Returns:
            bool: True if changed successfully
        """
        if not self.engine:
            raise ConnectionError("No active database connection")

        try:
            use_command = self._build_use_command(database)
            with self.engine.connect() as conn:
                # For Databricks, may have multiple commands separated by ;
                if self.db_type == "databricks" and ";" in use_command:
                    for cmd in use_command.split(";"):
                        cmd = cmd.strip()
                        if cmd:
                            conn.execute(text(cmd))
                else:
                    conn.execute(text(use_command))
                conn.commit()

            # Update internal params
            self.connection_params["database"] = database
            logger.info(f"Database changed to: {database}")
            return True

        except Exception as e:
            logger.error(f"Error changing database: {str(e)}")
            raise

    def _build_use_command(self, database: str) -> str:
        """Build the USE command with correct syntax for the current database type.

        Args:
            database: Database name (or catalog.schema for Databricks)

        Returns:
            str: USE command with correct quoting for the DB type
        """
        if self.db_type == "sqlserver":
            return f"USE [{database}]"
        elif self.db_type in ("mysql", "mariadb"):
            return f"USE `{database}`"
        elif self.db_type == "postgresql":
            # PostgreSQL does not support USE command for database switching
            # (that requires a new connection). This changes the schema search path
            # within the current database, which is the closest equivalent.
            return f'SET search_path TO "{database}"'
        elif self.db_type == "databricks":
            # Databricks uses 3-level namespace: catalog.schema.table
            # Support explicit CATALOG: or SCHEMA: prefix from UI
            if database.startswith("CATALOG:"):
                catalog_name = database[8:]  # Remove "CATALOG:" prefix
                return f"USE CATALOG `{catalog_name}`"
            elif database.startswith("SCHEMA:"):
                schema_name = database[7:]  # Remove "SCHEMA:" prefix
                return f"USE SCHEMA `{schema_name}`"
            # If database contains a dot, it's catalog.schema format
            elif "." in database:
                parts = database.split(".", 1)
                return f"USE CATALOG `{parts[0]}`; USE SCHEMA `{parts[1]}`"
            else:
                # Assume it's a schema name in the current catalog
                # (most common use case when user types USE <name>)
                return f"USE SCHEMA `{database}`"
        else:
            return f"USE {database}"

    def get_current_database(self) -> str:
        """Return current database name"""
        return self.connection_params.get("database", "")

    def disconnect(self):
        """Disconnect from database"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            logger.info("Disconnected from database")

    def is_connected(self) -> bool:
        """Check if there is an active connection (quick check, no I/O).

        Only checks if engine exists. disconnect() sets engine=None.
        DOES NOT do SELECT 1 on main thread to avoid blocking UI.
        """
        return self.engine is not None

    def ping(self) -> bool:
        """Test real connection with SELECT 1. Use only in background thread."""
        if not self.engine:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def get_tables(self) -> pd.DataFrame:
        """Return list of database tables"""
        if not self.engine:
            raise ConnectionError("No active database connection")

        queries = {
            "sqlserver": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            "mysql": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            "mariadb": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            "postgresql": """
                SELECT schemaname as TABLE_SCHEMA, tablename as TABLE_NAME, 'BASE TABLE' as TABLE_TYPE
                FROM pg_tables
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schemaname, tablename
            """,
        }

        query = queries.get(self.db_type, queries["postgresql"])
        return self.execute_query(query)
