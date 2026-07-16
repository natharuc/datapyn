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
import struct
import threading
import time
from pathlib import Path

from src.utils.sql_parameter_service import (
    prepare_databricks_sql,
    prepare_generic_sql,
    prepare_sqlserver_batch,
)
from src.language import S
from src.database.query_stream_exporter import (
    ExportFormat,
    StreamExportResult,
    iter_rows_chunked,
    make_result_path,
    stream_arrow_to_file,
    stream_result_set_to_file,
    STREAM_EXPORT_CHUNK_ROWS,
)


logger = logging.getLogger(__name__)


class QueryBusyError(ConnectionError):
    """Raised when a second query starts while another is still running."""


# Fetch rows from DB cursors in bounded chunks. Long fetchall() calls hold
# the GIL for the whole result set, starving the Qt UI thread even though the
# query runs in a worker thread. Chunking adds explicit yield points so the
# UI keeps painting while large results stream into memory.
FETCH_CHUNK_ROWS = 5_000
DATAFRAME_BUILD_CHUNK_ROWS = 25_000


def _gil_yield() -> None:
    """Give the UI thread a chance to run between CPU-heavy chunks."""
    time.sleep(0.001)


def fetch_rows_chunked(cursor, chunk_size: int = FETCH_CHUNK_ROWS) -> list:
    """fetchall() replacement that yields the GIL between chunks."""
    rows: list = []
    while True:
        chunk = cursor.fetchmany(chunk_size)
        if not chunk:
            break
        rows.extend(chunk)
        _gil_yield()
    return rows


def records_to_dataframe(rows: list, columns: list) -> pd.DataFrame:
    """Build a DataFrame from DBAPI rows without monopolizing the GIL.

    Large object-row conversions in a single from_records call freeze the UI
    thread; building in slices keeps each GIL-held stretch short.
    """
    if not rows:
        return pd.DataFrame(columns=columns)

    if len(rows) <= DATAFRAME_BUILD_CHUNK_ROWS:
        return pd.DataFrame.from_records(rows, columns=columns)

    parts: list = []
    for start in range(0, len(rows), DATAFRAME_BUILD_CHUNK_ROWS):
        part_rows = rows[start : start + DATAFRAME_BUILD_CHUNK_ROWS]
        parts.append(pd.DataFrame.from_records(part_rows, columns=columns))
        _gil_yield()

    result = pd.concat(parts, ignore_index=True, copy=False)
    return result


def _safe_exception_text(error: BaseException) -> str:
    try:
        return str(error)
    except UnicodeDecodeError as decode_error:
        return str(decode_error)
    except Exception:
        try:
            return repr(error)
        except Exception:
            return error.__class__.__name__


def _is_unicode_decode_error(error: BaseException) -> bool:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, UnicodeDecodeError):
            return True
        text_value = _safe_exception_text(current).lower()
        if "codec can't decode byte" in text_value and ("utf-8" in text_value or "utf8" in text_value):
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


def _is_direct_unicode_decode_error(error: BaseException) -> bool:
    if isinstance(error, UnicodeDecodeError):
        return True
    text_value = _safe_exception_text(error).lower()
    return "codec can't decode byte" in text_value and ("utf-8" in text_value or "utf8" in text_value)


def _format_sql_error_for_user(error: BaseException, db_type: str = "", query: str = "") -> str:
    error_text = _safe_exception_text(error)
    if str(db_type or "").lower() == "postgresql" and _is_postgresql_undefined_relation_error(error_text):
        hint = _postgresql_identifier_case_hint(query)
        if hint and hint not in error_text:
            return f"{error_text}\n\n{hint}"
    return error_text


def _is_postgresql_undefined_relation_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return (
        "undefinedtable" in lowered
        or "relation" in lowered and "does not exist" in lowered
        or "relação" in lowered and "não existe" in lowered
        or "relacao" in lowered and "nao existe" in lowered
    )


def _postgresql_identifier_case_hint(query: str) -> str:
    import re

    quoted_identifiers = set(re.findall(r'"([^"]+)"', query or ""))
    candidates = re.findall(
        r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        query or "",
        flags=re.IGNORECASE,
    )
    has_mixed_case_identifier = any(
        any(char.isupper() for char in part)
        for candidate in candidates
        for part in candidate.split(".")
        if part not in quoted_identifiers
    )
    if not has_mixed_case_identifier:
        return ""
    return S.workers.postgres_identifier_case_hint


SQLSERVER_AUTH_SQL_PASSWORD = "sql_password"
SQLSERVER_AUTH_WINDOWS = "windows"
SQLSERVER_AUTH_ENTRA_MFA = "entra_mfa"
SQL_COPT_SS_ACCESS_TOKEN = 1256
SQLSERVER_ENTRA_SCOPE = "https://database.windows.net/.default"
AZURE_SQL_HOST_SUFFIXES = (
    ".database.windows.net",
    ".database.usgovcloudapi.net",
    ".database.cloudapi.de",
    ".database.chinacloudapi.cn",
)


def normalize_sqlserver_auth_mode(auth_mode: str = "", use_windows_auth: bool = False) -> str:
    """Normalize SQL Server auth modes while keeping backward compatibility."""
    normalized = str(auth_mode or "").strip().lower()

    aliases = {
        "sql": SQLSERVER_AUTH_SQL_PASSWORD,
        "sql_password": SQLSERVER_AUTH_SQL_PASSWORD,
        "sqlserver": SQLSERVER_AUTH_SQL_PASSWORD,
        "windows": SQLSERVER_AUTH_WINDOWS,
        "windows_auth": SQLSERVER_AUTH_WINDOWS,
        "trusted_connection": SQLSERVER_AUTH_WINDOWS,
        "mfa": SQLSERVER_AUTH_ENTRA_MFA,
        "entra_mfa": SQLSERVER_AUTH_ENTRA_MFA,
        "aad_interactive": SQLSERVER_AUTH_ENTRA_MFA,
        "active_directory_interactive": SQLSERVER_AUTH_ENTRA_MFA,
        "azure_ad_mfa": SQLSERVER_AUTH_ENTRA_MFA,
    }

    if normalized:
        return aliases.get(normalized, SQLSERVER_AUTH_SQL_PASSWORD)

    if use_windows_auth:
        return SQLSERVER_AUTH_WINDOWS

    return SQLSERVER_AUTH_SQL_PASSWORD


def _get_sqlserver_entra_cache_name(host: str) -> str:
    """Build a stable cache name for SQL Server Entra tokens."""
    safe_host = host.replace(".", "_").replace(":", "_").replace("/", "_")
    return f"datapyn_sqlserver_{safe_host}"


def _get_sqlserver_auth_record_path(host: str) -> Path:
    """Get the persisted AuthenticationRecord path for a SQL Server host."""
    from src.core.workspace_service import get_workspace_service

    config_dir = get_workspace_service().get_config_dir("oauth_cache")
    return config_dir / f"{_get_sqlserver_entra_cache_name(host)}_auth_record.json"


def _read_sqlserver_auth_record(host: str):
    """Read the cached AuthenticationRecord from disk when available."""
    record_path = _get_sqlserver_auth_record_path(host)
    if not record_path.exists():
        return None

    try:
        from azure.identity import AuthenticationRecord

        return AuthenticationRecord.deserialize(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read SQL Server auth record: {exc}")
        return None


def _write_sqlserver_auth_record(host: str, authentication_record) -> None:
    """Persist the AuthenticationRecord for later silent token reuse."""
    record_path = _get_sqlserver_auth_record_path(host)
    try:
        record_path.write_text(authentication_record.serialize(), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Failed to persist SQL Server auth record: {exc}")


def _is_azure_sql_host(host: str) -> bool:
    """Return True when the host is an Azure SQL Database endpoint."""
    normalized = str(host or "").strip().lower()
    return normalized.endswith(AZURE_SQL_HOST_SUFFIXES)


def _build_sqlserver_access_token_struct(access_token: str) -> bytes:
    """Pack an access token in the ODBC ACCESSTOKEN structure format."""
    token_bytes = str(access_token or "").encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def _create_sqlserver_mfa_credential(host: str, login_hint: str = "", tenant_id: str = "", authentication_record=None):
    """Create a browser credential for SQL Server Entra MFA."""
    try:
        from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
    except ImportError as exc:
        raise RuntimeError(S.connection_edit.error_mfa_dependency_missing) from exc

    kwargs: dict[str, Any] = {
        "cache_persistence_options": TokenCachePersistenceOptions(name=_get_sqlserver_entra_cache_name(host)),
    }

    login_hint = str(login_hint or "").strip()
    tenant_id = str(tenant_id or "").strip()
    if login_hint:
        kwargs["login_hint"] = login_hint
    if tenant_id:
        kwargs["tenant_id"] = tenant_id
    if authentication_record is not None:
        kwargs["authentication_record"] = authentication_record

    return InteractiveBrowserCredential(**kwargs)


def _prepare_sqlserver_mfa_credential(host: str, login_hint: str = "", tenant_id: str = ""):
    """Create a MFA credential and persist its authentication record on first login."""
    record = _read_sqlserver_auth_record(host)
    credential = _create_sqlserver_mfa_credential(
        host=host,
        login_hint=login_hint,
        tenant_id=tenant_id,
        authentication_record=record,
    )

    if record is None:
        record = credential.authenticate(scopes=[SQLSERVER_ENTRA_SCOPE])
        _write_sqlserver_auth_record(host, record)
        credential.close()
        credential = _create_sqlserver_mfa_credential(
            host=host,
            login_hint=login_hint,
            tenant_id=tenant_id,
            authentication_record=record,
        )

    return credential


def _build_databricks_context_name(catalog: str, schema: str) -> str:
    parts = [str(part or "").strip() for part in (catalog, schema)]
    return ".".join(part for part in parts if part)


def get_connector_database_context(connector) -> str:
    """Return the current database context from a connector or compatible mock."""
    if connector is None:
        return ""

    get_context = getattr(connector, "get_current_database_context", None)
    if callable(get_context):
        try:
            value = str(get_context() or "")
        except Exception:
            value = ""
        if value:
            return value

    get_database = getattr(connector, "get_current_database", None)
    if callable(get_database):
        try:
            return str(get_database() or "")
        except Exception:
            return ""

    return ""


def _get_oauth_token_cache_path(host: str) -> Path:
    """Get path for OAuth token cache file.
    
    Tokens are stored per-host in the user's workspace config directory.
    """
    # Use a safe filename derived from the host
    safe_host = host.replace(".", "_").replace(":", "_").replace("/", "_")
    # Use WorkspaceService for path (supports workspace switching)
    from src.core.workspace_service import get_workspace_service
    config_dir = get_workspace_service().get_config_dir("oauth_cache")
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


def build_sqlalchemy_engine_kwargs(db_type: str, host: str) -> dict:
    """SQLAlchemy pool options tuned to avoid idle sleeping SPIDs on SQL Server."""
    kwargs: dict = {
        "pool_size": 2,
        "pool_timeout": 10,
        "pool_recycle": 300,
    }
    if db_type == "sqlserver" and _is_azure_sql_host(host):
        kwargs["pool_pre_ping"] = True
    return kwargs


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
        self._query_lock = threading.Lock()
        self._connection_config: Dict[str, Any] = {}
        self._sqlserver_mfa_credential = None

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
            sqlserver_auth_mode = ""
            sqlserver_mfa_credential = None
            if db_type == "sqlserver":
                sqlserver_auth_mode = normalize_sqlserver_auth_mode(
                    kwargs.get("sqlserver_auth_mode", ""),
                    kwargs.get("use_windows_auth", False),
                )
                if sqlserver_auth_mode == SQLSERVER_AUTH_ENTRA_MFA:
                    sqlserver_mfa_credential = _prepare_sqlserver_mfa_credential(
                        host=host,
                        login_hint=username,
                        tenant_id=kwargs.get("tenant_id", ""),
                    )
                    self._sqlserver_mfa_credential = sqlserver_mfa_credential

            connection_string, connect_args = self._build_connection_string(
                db_type, host, port, database, username, password, **kwargs
            )

            engine_kwargs = build_sqlalchemy_engine_kwargs(db_type, host)
            self.engine = create_engine(
                connection_string,
                connect_args=connect_args,
                **engine_kwargs,
            )

            if db_type == "sqlserver" and sqlserver_auth_mode == SQLSERVER_AUTH_ENTRA_MFA:
                credential = sqlserver_mfa_credential

                @event.listens_for(self.engine, "do_connect")
                def on_do_connect(dialect, connection_record, cargs, cparams):
                    token = credential.get_token(SQLSERVER_ENTRA_SCOPE)
                    attrs_before = dict(cparams.get("attrs_before") or {})
                    attrs_before[SQL_COPT_SS_ACCESS_TOKEN] = _build_sqlserver_access_token_struct(token.token)
                    cparams["attrs_before"] = attrs_before

            # Register pool event to ensure every connection
            # pulled from pool uses correct database (solves problem
            # with USE <db> that only affects one pool connection)
            if db_type == "sqlserver":
                connector_ref = self

                @event.listens_for(self.engine, "checkout")
                def on_checkout(dbapi_conn, connection_record, connection_proxy):
                    if not connector_ref._sqlserver_supports_use():
                        return
                    current_db = connector_ref.connection_params.get("database", "")
                    if current_db:
                        try:
                            cursor = dbapi_conn.cursor()
                            cursor.execute(f"USE [{current_db}]")
                            cursor.close()
                        except Exception:
                            pass  # Silence - USE in batch will catch error

            # Test connection
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except KeyError as e:
                # Databricks OAuth: cached refresh token expired/invalid.
                # The SDK raises KeyError('access_token') when the server
                # response to a token refresh lacks the expected field.
                # Delete stale cache and retry to trigger fresh browser OAuth.
                if db_type == "databricks" and "access_token" in _safe_exception_text(e):
                    logger.warning("Databricks OAuth token expired. Clearing cache and retrying...")
                    cache_path = _get_oauth_token_cache_path(host)
                    if cache_path.exists():
                        cache_path.unlink()
                        logger.info(f"Deleted stale OAuth cache: {cache_path}")
                    self.engine.dispose()
                    self.engine = create_engine(
                        connection_string,
                        connect_args=connect_args,
                        **build_sqlalchemy_engine_kwargs(db_type, host),
                    )
                    with self.engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                else:
                    raise
            except Exception as e:
                if db_type == "postgresql" and _is_unicode_decode_error(e) and not kwargs.get("postgresql_client_encoding"):
                    retry_error = None
                    for client_encoding in ("WIN1252", "LATIN1"):
                        retry_kwargs = dict(kwargs)
                        retry_kwargs["postgresql_client_encoding"] = client_encoding
                        retry_connection_string, retry_connect_args = self._build_connection_string(
                            db_type, host, port, database, username, password, **retry_kwargs
                        )
                        retry_engine = create_engine(
                            retry_connection_string,
                            connect_args=retry_connect_args,
                            **build_sqlalchemy_engine_kwargs(db_type, host),
                        )
                        try:
                            self.engine.dispose()
                            self.engine = retry_engine
                            with self.engine.connect() as conn:
                                conn.execute(text("SELECT 1"))
                            kwargs["postgresql_client_encoding"] = client_encoding
                            logger.info("PostgreSQL connection retried with client_encoding=%s", client_encoding)
                            retry_error = None
                            break
                        except Exception as fallback_error:
                            retry_error = fallback_error
                            retry_engine.dispose()
                            if not _is_direct_unicode_decode_error(fallback_error):
                                raise
                    if retry_error is not None:
                        raise retry_error
                else:
                    raise

            self.db_type = db_type
            self.connection_params = {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "sqlserver_supports_use": not _is_azure_sql_host(host) if db_type == "sqlserver" else True,
            }
            self._connection_config = {
                "db_type": db_type,
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password": password,
                **kwargs,
            }

            # For Databricks, initialize catalog/schema tracking
            # If user didn't specify a catalog, query Databricks for current catalog/schema
            if db_type == "databricks":
                if database:
                    self.connection_params["databricks_catalog"] = database
                    self.connection_params["databricks_schema"] = "default"
                else:
                    # Query Databricks for current catalog and schema
                    try:
                        with self.engine.connect() as conn:
                            result = conn.execute(text("SELECT current_catalog(), current_schema()"))
                            row = result.fetchone()
                            if row:
                                current_cat = str(row[0]) if row[0] else ""
                                current_sch = str(row[1]) if row[1] else "default"
                                self.connection_params["database"] = current_cat
                                self.connection_params["databricks_catalog"] = current_cat
                                self.connection_params["databricks_schema"] = current_sch
                                logger.info(f"Databricks current context: catalog='{current_cat}', schema='{current_sch}'")
                    except Exception as e:
                        logger.warning(f"Could not query Databricks current catalog/schema: {e}")
                        self.connection_params["databricks_catalog"] = ""
                        self.connection_params["databricks_schema"] = "default"

            logger.info(f"Connected to {self.SUPPORTED_DATABASES[db_type]}: {host}/{database}")
            return True

        except Exception as e:
            logger.error(f"Database connection error: {_safe_exception_text(e)}")
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

            auth_mode = normalize_sqlserver_auth_mode(
                kwargs.get("sqlserver_auth_mode", ""),
                kwargs.get("use_windows_auth", False),
            )
            trust_cert = kwargs.get("trust_server_certificate", False)

            # Detect LocalDB - uses named pipes, not TCP/IP
            is_localdb = "(localdb)" in host.lower()

            if is_localdb:
                # LocalDB format: SERVER=(localdb)\InstanceName (no port)
                # LocalDB always uses Windows Authentication
                server_part = f"SERVER={host}"
                auth_mode = SQLSERVER_AUTH_WINDOWS
            else:
                # Standard SQL Server format: SERVER=host,port
                server_part = f"SERVER={host},{port}"

            # Use direct ODBC connection string
            if auth_mode == SQLSERVER_AUTH_WINDOWS:
                # Windows Authentication
                odbc_string = (
                    f"DRIVER={{{driver}}};"
                    f"{server_part};"
                    f"DATABASE={database};"
                    f"Trusted_Connection=yes"
                )
            elif auth_mode == SQLSERVER_AUTH_ENTRA_MFA:
                # Use an app-managed browser token instead of the driver's interactive mode.
                parts = [
                    f"DRIVER={{{driver}}}",
                    server_part,
                    f"DATABASE={database}",
                    "Encrypt=yes",
                ]
                odbc_string = ";".join(parts)
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
            connect_args = {}
            client_encoding = str(kwargs.get("postgresql_client_encoding", "") or "").strip()
            if client_encoding:
                connect_args["client_encoding"] = client_encoding
            return f"postgresql+psycopg2://{user_encoded}:{pass_encoded}@{host}:{port}/{database}", connect_args

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

    @staticmethod
    def _split_sql_batches(query: str) -> list:
        """Split SQL script into batches separated by GO statements.

        GO is a batch separator used by SQL Server tools (SSMS, sqlcmd).
        It is NOT a T-SQL statement - pyodbc does not understand it.
        Each batch must be executed separately.

        Handles:
        - GO on its own line (with optional whitespace)
        - Case-insensitive (GO, go, Go)
        - GO with repeat count (GO 5) - split but count ignored
        - Windows (CRLF) and Unix (LF) line endings
        - Does NOT match GO inside identifiers (ALGO, category)

        Args:
            query: Full SQL script potentially containing GO separators

        Returns:
            List of non-empty batch strings
        """
        import re

        # Pattern: line that contains only GO (optionally followed by a number)
        # \b ensures we don't match inside words like ALGO, category
        # Must be on its own line (possibly with whitespace)
        batches = re.split(
            r"^\s*\bGO\b\s*(?:\d+)?\s*$",
            query,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        # Strip whitespace and filter empty batches
        return [b.strip() for b in batches if b.strip()]

    def is_query_busy(self) -> bool:
        """True while a worker thread holds the per-connection query lock."""
        return self._query_lock.locked()

    def execute_query(self, query: str, parameters: Optional[List[Dict[str, Any]]] = None) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        """
        Execute SQL query and return DataFrame or list of DataFrames

        Supports multiple SQL commands. For queries with multiple SELECTs,
        returns a list of DataFrames (one for each SELECT).
        For SQL Server, GO batch separators are handled correctly.

        Args:
            query: SQL query to execute (can contain multiple commands and GO separators)
            parameters: Optional custom SQL parameter definitions from a DataPyn SQL block

        Returns:
            Union[pd.DataFrame, List[pd.DataFrame]]: Query result or list of results
        """
        if not self.engine:
            raise ConnectionError("No active database connection")

        if not self._query_lock.acquire(blocking=False):
            raise QueryBusyError("A query is still running on this connection")

        try:
            return self._execute_query_unlocked(query, parameters=parameters)
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            raise
        finally:
            self._query_lock.release()

    def _success_message_df(self, key: str, **fmt) -> pd.DataFrame:
        """Build the single-row {'Result': [msg]} frame for non-result commands.

        Centralizes the success/no-commands messaging so every backend emits
        identical, localized text. ``key`` is an attribute on ``S.connector``.
        """
        template = getattr(getattr(S, "connector", None), key, None)
        if template is None:
            template = self._FALLBACK_MESSAGES.get(key, "Command executed successfully.")
        try:
            msg = template.format(**fmt) if fmt else template
        except Exception:
            msg = template
        return pd.DataFrame({"Result": [msg]})

    _FALLBACK_MESSAGES = {
        "success_commands": "Command(s) executed successfully.",
        "success_commands_plural": "Commands executed successfully.",
        "success_command_rows": "Command executed successfully. {rows} row(s) affected.",
        "success_command": "Command executed successfully.",
        "no_commands": "No SQL commands to execute.",
    }

    def stream_query_to_files(
        self,
        query: str,
        *,
        base_path: Path,
        export_format: ExportFormat,
        parameters: Optional[List[Dict[str, Any]]] = None,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
        on_total: Optional[Any] = None,
    ) -> StreamExportResult:
        """Execute query and stream result sets to files without building DataFrames."""
        if not self.engine:
            raise ConnectionError("No active database connection")

        if not self._query_lock.acquire(blocking=False):
            raise QueryBusyError("A query is still running on this connection")

        try:
            return self._stream_query_unlocked(
                query,
                base_path=Path(base_path),
                export_format=export_format,
                parameters=parameters,
                csv_options=csv_options,
                on_progress=on_progress,
                on_file_started=on_file_started,
                is_cancelled=is_cancelled,
                on_total=on_total,
            )
        finally:
            self._query_lock.release()

    def _estimate_databricks_row_count(
        self,
        query: str,
        parameters: Optional[List[Dict[str, Any]]],
        is_cancelled: Optional[Any] = None,
    ) -> Optional[int]:
        """Best-effort COUNT(*) over the user query. None if not countable."""
        if is_cancelled and is_cancelled():
            return None
        stmts = self._split_sql_statements(query)
        if len(stmts) != 1:
            return None
        stmt = stmts[0].strip().rstrip(";").strip()
        if not stmt:
            return None
        head = self._statement_head(stmt).upper()
        if not (head.startswith("SELECT") or head.startswith("WITH")):
            return None
        count_sql = f"SELECT COUNT(*) AS __dp_count FROM ({stmt}) AS __dp_count_sub"
        raw = None
        cur = None
        try:
            raw = self.engine.raw_connection()
            cur = raw.cursor()
            prepared = prepare_databricks_sql(count_sql, parameters) if parameters else None
            if prepared:
                cur.execute(prepared.query, prepared.params)
            else:
                cur.execute(count_sql)
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
            return None
        except Exception as e:
            logger.info(f"Databricks COUNT estimation skipped: {_safe_exception_text(e)}")
            return None
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if raw:
                try:
                    raw.close()
                except Exception:
                    pass

    def _stream_query_unlocked(
        self,
        query: str,
        *,
        base_path: Path,
        export_format: ExportFormat,
        parameters: Optional[List[Dict[str, Any]]] = None,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
        on_total: Optional[Any] = None,
    ) -> StreamExportResult:
        import re

        use_match = self._match_use_only_command(query)
        if use_match:
            new_db = use_match.group(1)
            if self.db_type == "sqlserver" and not self._sqlserver_supports_use():
                self.change_database(new_db)
                return StreamExportResult(errors=[f"Database changed to: {new_db}"])
            self.connection_params["database"] = new_db

        if self.db_type == "sqlserver":
            batches = self._split_sql_batches(query)
            if not batches:
                return StreamExportResult(errors=["No SQL commands to execute."])
            return self._stream_mssql_batches(
                batches,
                base_path=base_path,
                export_format=export_format,
                parameters=parameters,
                csv_options=csv_options,
                on_progress=on_progress,
                on_file_started=on_file_started,
                is_cancelled=is_cancelled,
            )

        if self.db_type == "databricks":
            return self._stream_databricks_query(
                query,
                base_path=base_path,
                export_format=export_format,
                parameters=parameters,
                csv_options=csv_options,
                on_progress=on_progress,
                on_file_started=on_file_started,
                is_cancelled=is_cancelled,
                on_total=on_total,
            )

        return self._stream_generic_query(
            query,
            base_path=base_path,
            export_format=export_format,
            parameters=parameters,
            csv_options=csv_options,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )

    def _stream_write_result_set(
        self,
        columns: list,
        row_source,
        *,
        base_path: Path,
        export_format: ExportFormat,
        file_index: int,
        result: StreamExportResult,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
    ) -> bool:
        """Write one result set; return False if cancelled."""
        path = make_result_path(base_path, file_index, export_format)
        path.parent.mkdir(parents=True, exist_ok=True)
        if on_file_started:
            try:
                on_file_started(file_index, path)
            except Exception:
                pass
        total_for_file = 0

        def on_chunk(n: int) -> None:
            nonlocal total_for_file
            total_for_file += n
            if on_progress:
                bytes_written = 0
                try:
                    bytes_written = path.stat().st_size if path.exists() else 0
                except OSError:
                    bytes_written = 0
                on_progress(file_index, total_for_file, bytes_written)

        if hasattr(row_source, "fetchmany_arrow"):
            rows_written = stream_arrow_to_file(
                row_source.fetchmany_arrow,
                path=path,
                export_format=export_format,
                columns=list(columns) if columns else None,
                is_cancelled=is_cancelled,
                on_chunk=on_chunk,
                csv_options=csv_options,
            )
        else:
            rows_written = stream_result_set_to_file(
                columns,
                iter_rows_chunked(row_source, STREAM_EXPORT_CHUNK_ROWS)
                if hasattr(row_source, "fetchmany")
                else row_source,
                path=path,
                export_format=export_format,
                is_cancelled=is_cancelled,
                on_chunk=on_chunk,
                csv_options=csv_options,
            )
        if rows_written < 0:
            result.cancelled = True
            return False
        result.files.append(path)
        result.row_counts.append(rows_written)
        result.columns_per_file.append(list(columns))
        return True

    def _stream_mssql_batches(
        self,
        batches: list,
        *,
        base_path: Path,
        export_format: ExportFormat,
        parameters: Optional[List[Dict[str, Any]]] = None,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
    ) -> StreamExportResult:
        import pyodbc

        self._cancelled = False
        cursor = None
        raw_conn = None
        result = StreamExportResult()
        file_index = 0
        errors: list[str] = []

        try:
            if not self._sqlserver_supports_use():
                normalized_batches = []
                for batch in batches:
                    use_match = self._match_use_only_command(batch)
                    if use_match:
                        self.change_database(use_match.group(1))
                        continue
                    normalized_batches.append(batch)
                batches = normalized_batches

            if not batches:
                return StreamExportResult(errors=["No SQL commands to execute."])

            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn

            current_db = self.connection_params.get("database", "")
            if current_db and self._sqlserver_supports_use():
                try:
                    init_cursor = raw_conn.cursor()
                    init_cursor.execute(f"USE [{current_db}]")
                    while init_cursor.nextset():
                        pass
                    init_cursor.close()
                except Exception as e:
                    logger.warning(f"Failed to set database [{current_db}]: {e}")

            for batch_idx, batch in enumerate(batches, start=1):
                if self._cancelled or (is_cancelled and is_cancelled()):
                    result.cancelled = True
                    break

                cursor = raw_conn.cursor()
                self._active_cursor = cursor
                batch_error = None
                try:
                    prepared = prepare_sqlserver_batch(batch, parameters) if parameters else None
                    if prepared:
                        cursor.execute(prepared.query, *prepared.params)
                    else:
                        cursor.execute(batch)
                except pyodbc.Error as e:
                    batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                    errors.append(batch_error)
                    try:
                        cursor.close()
                    except Exception:
                        pass
                    cursor = None
                    continue

                while True:
                    if self._cancelled or (is_cancelled and is_cancelled()):
                        result.cancelled = True
                        break
                    try:
                        if cursor.description:
                            columns = [col[0] for col in cursor.description]
                            file_index += 1
                            if not self._stream_write_result_set(
                                columns,
                                cursor,
                                base_path=base_path,
                                export_format=export_format,
                                file_index=file_index,
                                result=result,
                                csv_options=csv_options,
                                on_progress=on_progress,
                                is_cancelled=is_cancelled,
                            ):
                                break
                    except Exception as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break

                    try:
                        has_next = cursor.nextset()
                        if batch_error or not has_next:
                            break
                    except Exception as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break

                try:
                    cursor.close()
                except Exception:
                    pass
                cursor = None
                if batch_error:
                    errors.append(batch_error)

            raw_conn.commit()
            result.errors = errors
            return result

        except Exception as e:
            logger.error(f"Error streaming SQL Server batches: {str(e)}")
            raise
        finally:
            self._active_raw_conn = None
            self._active_cursor = None
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if raw_conn:
                try:
                    raw_conn.close()
                except Exception:
                    pass

    def _stream_databricks_query(
        self,
        query: str,
        *,
        base_path: Path,
        export_format: ExportFormat,
        parameters: Optional[List[Dict[str, Any]]] = None,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
        on_total: Optional[Any] = None,
    ) -> StreamExportResult:
        self._cancelled = False
        cursor = None
        raw_conn = None
        result = StreamExportResult()

        try:
            if on_total is not None:
                total = self._estimate_databricks_row_count(query, parameters, is_cancelled)
                if is_cancelled and is_cancelled():
                    result.cancelled = True
                    return result
                if total is not None:
                    try:
                        on_total(1, total)
                    except Exception:
                        pass

            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn
            cursor = raw_conn.cursor()
            self._active_cursor = cursor

            if parameters:
                prepared = prepare_databricks_sql(query, parameters)
                cursor.execute(prepared.query, prepared.params)
            else:
                cursor.execute(query)

            if self._cancelled or (is_cancelled and is_cancelled()):
                result.cancelled = True
                return result

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                self._stream_write_result_set(
                    columns,
                    cursor,
                    base_path=base_path,
                    export_format=export_format,
                    file_index=1,
                    result=result,
                    csv_options=csv_options,
                    on_progress=on_progress,
                    on_file_started=on_file_started,
                    is_cancelled=is_cancelled,
                )
            return result

        except Exception as e:
            if self._cancelled:
                result.cancelled = True
                return result
            raise
        finally:
            self._active_raw_conn = None
            self._active_cursor = None
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if raw_conn:
                try:
                    raw_conn.close()
                except Exception:
                    pass

    def _stream_generic_query(
        self,
        query: str,
        *,
        base_path: Path,
        export_format: ExportFormat,
        parameters: Optional[List[Dict[str, Any]]] = None,
        csv_options: dict | None = None,
        on_progress: Optional[Any] = None,
        on_file_started: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
    ) -> StreamExportResult:
        commands = self._split_sql_statements(query)
        result = StreamExportResult()
        file_index = 0

        if not commands:
            result.errors.append("No SQL commands to execute.")
            return result

        with self.engine.connect() as conn:
            for cmd in commands:
                if self._cancelled or (is_cancelled and is_cancelled()):
                    result.cancelled = True
                    break

                prepared = prepare_generic_sql(cmd, parameters) if parameters else None
                executable_sql = prepared.query if prepared else cmd
                executable_params = prepared.params if prepared else {}

                if self._requires_postgresql_autocommit(cmd):
                    conn.commit()
                    self._execute_postgresql_autocommit_statement(executable_sql, executable_params)
                    continue

                if self._is_select_query(cmd):
                    db_result = conn.execute(text(executable_sql), executable_params)
                    columns = list(db_result.keys())
                    file_index += 1
                    if not self._stream_write_result_set(
                        columns,
                        db_result,
                        base_path=base_path,
                        export_format=export_format,
                        file_index=file_index,
                        result=result,
                        csv_options=csv_options,
                        on_progress=on_progress,
                        on_file_started=on_file_started,
                        is_cancelled=is_cancelled,
                    ):
                        break
                else:
                    conn.execute(text(executable_sql), executable_params)

            conn.commit()

        return result

    def _execute_query_unlocked(
        self, query: str, parameters: Optional[List[Dict[str, Any]]] = None
    ) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        # Detect USE command to update current database
        import re

        use_match = self._match_use_only_command(query)
        if use_match:
            new_db = use_match.group(1)
            logger.info(f"Detected USE command {new_db}")
            if self.db_type == "sqlserver" and not self._sqlserver_supports_use():
                self.change_database(new_db)
                return pd.DataFrame({"Result": [f"Database changed to: {new_db}"]})
            self.connection_params["database"] = new_db

        # For SQL Server, split on GO and execute each batch separately
        if self.db_type == "sqlserver":
            batches = self._split_sql_batches(query)
            if not batches:
                return self._success_message_df("no_commands")
            return self._execute_mssql_batches(batches, parameters=parameters)

        # For Databricks, use specific method with cursor access for cancellation
        if self.db_type == "databricks":
            return self._execute_databricks_query(query, parameters=parameters)

        # For other databases, use legacy logic
        return self._execute_generic_query(query, parameters=parameters)

    def request_cancel(self) -> None:
        """Set cancellation flag (safe from any thread; does not call the driver)."""
        self._cancelled = True

    def interrupt_query(self) -> None:
        """Interrupt the driver-level query (must run on the query worker thread)."""
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
            elif self.db_type == "databricks":
                # Databricks: cancel() on cursor sends cancel to server
                cursor = self._active_cursor
                if cursor is not None and hasattr(cursor, "cancel"):
                    cursor.cancel()
                    logger.info("Databricks query cancelled via cursor.cancel()")
                else:
                    logger.warning("Cancel requested but Databricks cursor not available")
            else:
                # MySQL/MariaDB: no native cancel in driver,
                # but _cancelled flag will interrupt processing
                logger.info(f"Cancel requested for {self.db_type} (via flag)")
        except Exception as e:
            logger.warning(f"Error cancelling query: {e}")

    def cancel_query(self):
        """Cancel running query (flag + driver interrupt).

        Prefer ``request_cancel()`` from the UI thread and ``interrupt_query()``
        queued on the SQL worker thread to avoid blocking or deadlocking Qt.
        """
        self.request_cancel()
        self.interrupt_query()

    def _execute_mssql_batches(self, batches: list, parameters: Optional[List[Dict[str, Any]]] = None) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        """Execute multiple SQL Server batches on the same connection.

        Each batch (separated by GO in the original script) is executed
        as a separate cursor.execute() call. The same raw connection is
        reused so that temp tables (#tables), temp procedures, and session
        state persist across batches.

        Like SSMS, if a batch fails the remaining batches still execute.
        Errors are collected and reported together at the end.

        Args:
            batches: List of SQL batch strings (already split on GO)

        Returns:
            Union[pd.DataFrame, List[pd.DataFrame]]: Results from all batches
        """
        import pyodbc

        self._cancelled = False
        cursor = None
        raw_conn = None
        dataframes = []
        errors = []

        try:
            if not self._sqlserver_supports_use():
                normalized_batches = []
                for batch in batches:
                    use_match = self._match_use_only_command(batch)
                    if use_match:
                        self.change_database(use_match.group(1))
                        continue
                    normalized_batches.append(batch)
                batches = normalized_batches

            if not batches:
                return pd.DataFrame({"Result": ["Command(s) executed successfully."]})

            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn

            # Set database context once at the start
            current_db = self.connection_params.get("database", "")
            if current_db and self._sqlserver_supports_use():
                try:
                    init_cursor = raw_conn.cursor()
                    init_cursor.execute(f"USE [{current_db}]")
                    while init_cursor.nextset():
                        pass
                    init_cursor.close()
                except Exception as e:
                    logger.warning(f"Failed to set database [{current_db}]: {e}")

            for batch_idx, batch in enumerate(batches, start=1):
                if self._cancelled:
                    logger.info("Execution cancelled between batches")
                    break

                logger.info(f"Executing batch {batch_idx}/{len(batches)} ({len(batch)} chars)")

                cursor = raw_conn.cursor()
                self._active_cursor = cursor

                batch_error = None
                try:
                    prepared = prepare_sqlserver_batch(batch, parameters) if parameters else None
                    if prepared:
                        cursor.execute(prepared.query, *prepared.params)
                    else:
                        cursor.execute(batch)
                except pyodbc.Error as e:
                    batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                    logger.warning(batch_error)
                    errors.append(batch_error)
                    try:
                        cursor.close()
                    except Exception:
                        pass
                    cursor = None
                    continue  # Continue to next batch (like SSMS)

                # Collect all result sets from this batch
                while True:
                    try:
                        if cursor.description:
                            columns = [col[0] for col in cursor.description]
                            rows = fetch_rows_chunked(cursor)
                            df = records_to_dataframe(rows, columns)
                            dataframes.append(df)
                    except pyodbc.Error as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break
                    except Exception as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break

                    try:
                        has_next = cursor.nextset()

                        # Check cursor.messages for deferred errors
                        if hasattr(cursor, "messages") and cursor.messages:
                            for msg in cursor.messages:
                                if len(msg) >= 2:
                                    sql_state, error_msg = msg[0], msg[1]
                                    if sql_state and sql_state != "01000":
                                        batch_error = f"Batch {batch_idx}/{len(batches)}: {error_msg}"
                                        break

                        if batch_error:
                            break
                        if not has_next:
                            break
                    except pyodbc.Error as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break
                    except Exception as e:
                        batch_error = f"Batch {batch_idx}/{len(batches)}: {str(e)}"
                        break

                try:
                    cursor.close()
                except Exception:
                    pass
                cursor = None

                if batch_error:
                    logger.warning(batch_error)
                    errors.append(batch_error)
                    # Continue to next batch (like SSMS)

            # Commit after all batches (even if some failed)
            raw_conn.commit()

            logger.info(
                f"Executed {len(batches)} batch(es): "
                f"{len(dataframes)} result set(s), {len(errors)} error(s)."
            )

            # Build error summary if there were failures
            if errors:
                error_summary = "\n".join(errors)
                if dataframes:
                    # Append error info as an extra DataFrame so the user sees both results and errors
                    error_df = pd.DataFrame({"Error": errors})
                    dataframes.append(error_df)
                else:
                    raise Exception(error_summary)

            if len(dataframes) > 1:
                return dataframes
            if dataframes:
                return dataframes[0]

            return self._success_message_df("success_commands")

        except Exception as e:
            logger.error(f"Error executing SQL Server batches: {str(e)}")
            raise

        finally:
            self._active_raw_conn = None
            self._active_cursor = None
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if raw_conn:
                try:
                    raw_conn.close()
                except Exception:
                    pass

    def _execute_databricks_query(self, query: str, parameters: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
        """Execute Databricks query with cursor access for cancellation.
        
        Uses raw connection to expose cursor for cancel support.
        """
        self._cancelled = False
        cursor = None
        raw_conn = None
        
        try:
            # Get raw DBAPI connection from SQLAlchemy engine
            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn
            cursor = raw_conn.cursor()
            self._active_cursor = cursor  # Expose cursor for cancellation
            
            # Execute query
            if parameters:
                prepared = prepare_databricks_sql(query, parameters)
                cursor.execute(prepared.query, prepared.params)
            else:
                cursor.execute(query)
            
            # Check if cancelled
            if self._cancelled:
                return pd.DataFrame({"Result": ["Query cancelled"]})
            
            # Try to fetch results
            try:
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                if columns:
                    rows = fetch_rows_chunked(cursor)
                    df = records_to_dataframe(rows, columns)
                    logger.info(f"Databricks query executed: {len(df)} rows returned")
                    return df
                else:
                    # No results (DDL/DML command)
                    rows_affected = cursor.rowcount if hasattr(cursor, 'rowcount') else -1
                    if rows_affected >= 0:
                        return self._success_message_df("success_command_rows", rows=rows_affected)
                    return self._success_message_df("success_command")
            except Exception as fetch_err:
                # Query was cancelled or had no results
                if self._cancelled:
                    return pd.DataFrame({"Result": ["Query cancelled"]})
                raise
                
        except Exception as e:
            if self._cancelled:
                logger.info("Databricks query cancelled by user")
                return pd.DataFrame({"Result": ["Query cancelled"]})
            logger.error(f"Error executing Databricks query: {str(e)}")
            raise
            
        finally:
            self._active_raw_conn = None
            self._active_cursor = None
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if raw_conn:
                try:
                    raw_conn.close()
                except Exception:
                    pass

    def _is_select_query(self, query: str) -> bool:
        """Check if a query is a SELECT (returns data) vs statement (modifies data).
        
        Handles comments, whitespace, and common query patterns.
        """
        # Remove SQL comments and normalize
        import re
        # Remove single-line comments (-- comment)
        clean = re.sub(r'--.*$', '', query, flags=re.MULTILINE)
        # Remove multi-line comments (/* comment */)
        clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
        # Strip and uppercase
        clean = clean.strip().upper()
        
        # Check for SELECT-like queries
        return (
            clean.startswith("SELECT") or
            clean.startswith("SHOW") or
            clean.startswith("WITH") or
            clean.startswith("(SELECT") or
            clean.startswith("DESC") or
            clean.startswith("DESCRIBE") or
            clean.startswith("EXPLAIN")
        )

    @staticmethod
    def _statement_head(query: str) -> str:
        """Return SQL without leading comments/whitespace for command detection."""
        clean = (query or "").strip()
        while clean.startswith("--") or clean.startswith("/*"):
            if clean.startswith("--"):
                line_end = clean.find("\n")
                clean = "" if line_end == -1 else clean[line_end + 1 :].strip()
                continue
            block_end = clean.find("*/", 2)
            clean = "" if block_end == -1 else clean[block_end + 2 :].strip()
        return clean

    def _requires_postgresql_autocommit(self, statement: str) -> bool:
        """PostgreSQL commands that cannot run inside a transaction block."""
        if self.db_type != "postgresql":
            return False

        import re

        head = self._statement_head(statement).upper()
        patterns = (
            r"^CREATE\s+DATABASE\b",
            r"^DROP\s+DATABASE\b",
            r"^VACUUM\b",
            r"^ALTER\s+SYSTEM\b",
            r"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b",
            r"^DROP\s+INDEX\s+CONCURRENTLY\b",
            r"^REINDEX\s+(?:DATABASE|SYSTEM)\b",
        )
        return any(re.match(pattern, head) for pattern in patterns)

    def _execute_postgresql_autocommit_statement(self, statement: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """Execute PostgreSQL DDL that must run outside a transaction block."""
        with self.engine.connect() as conn:
            autocommit_conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            result = autocommit_conn.execute(text(statement), params or {})
            rows_affected = getattr(result, "rowcount", -1)

        if isinstance(rows_affected, int) and rows_affected >= 0:
            return self._success_message_df("success_command_rows", rows=rows_affected)
        return self._success_message_df("success_command")

    @staticmethod
    def _split_sql_statements(query: str) -> list:
        """Split SQL script into individual statements, handling DELIMITER.

        MySQL's DELIMITER directive is a client-side command that changes
        the statement terminator. The MySQL server does NOT understand it.
        This parser handles DELIMITER changes so that stored procedures,
        functions, and triggers with semicolons in their body are sent
        as a single statement to the server.

        Handles:
        - DELIMITER changes (e.g., DELIMITER $$ ... DELIMITER ;)
        - String literals (single and double quotes) - delimiters inside
          strings are ignored
        - Single-line comments (-- and #)
        - Multi-line comments (/* ... */)
        - Escaped quotes inside strings

        Args:
            query: Full SQL script, possibly containing DELIMITER directives

        Returns:
            List of non-empty SQL statements (without DELIMITER lines)
        """
        import re

        statements = []
        delimiter = ";"
        current = []
        i = 0
        text = query

        while i < len(text):
            c = text[i]

            # -- single-line comment
            if c == "-" and i + 1 < len(text) and text[i + 1] == "-":
                end = text.find("\n", i)
                if end == -1:
                    current.append(text[i:])
                    i = len(text)
                else:
                    current.append(text[i : end + 1])
                    i = end + 1
                continue

            # # single-line comment (MySQL specific)
            if c == "#":
                end = text.find("\n", i)
                if end == -1:
                    current.append(text[i:])
                    i = len(text)
                else:
                    current.append(text[i : end + 1])
                    i = end + 1
                continue

            # /* multi-line comment */
            if c == "/" and i + 1 < len(text) and text[i + 1] == "*":
                end = text.find("*/", i + 2)
                if end == -1:
                    current.append(text[i:])
                    i = len(text)
                else:
                    current.append(text[i : end + 2])
                    i = end + 2
                continue

            # String literals (single or double quotes)
            if c in ("'", '"'):
                quote = c
                j = i + 1
                while j < len(text):
                    if text[j] == "\\" :
                        j += 2  # skip escaped char
                        continue
                    if text[j] == quote:
                        if j + 1 < len(text) and text[j + 1] == quote:
                            j += 2  # escaped quote ('')
                            continue
                        break
                    j += 1
                current.append(text[i : j + 1])
                i = j + 1
                continue

            # Check for DELIMITER directive at start of line
            if c in ("D", "d"):
                # Look backwards to verify we're at start of line
                # (handle both \n and \r\n line endings)
                at_line_start = (
                    i == 0
                    or text[i - 1] == "\n"
                    or (text[i - 1] == "\r" and (i < 2 or text[i - 2] == "\n"))
                )
                if at_line_start:
                    match = re.match(
                        r"DELIMITER\s+(\S+?)\s*;?\s*(?:\r?\n|$)",
                        text[i:],
                        re.IGNORECASE,
                    )
                    if match:
                        # Flush any accumulated content as a statement
                        stmt = "".join(current).strip()
                        if stmt:
                            statements.append(stmt)
                        current = []
                        delimiter = match.group(1)
                        i += match.end()
                        continue

            # Check for current delimiter
            if text[i : i + len(delimiter)] == delimiter:
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += len(delimiter)
                continue

            current.append(c)
            i += 1

        # Flush remaining content
        stmt = "".join(current).strip()
        if stmt:
            statements.append(stmt)

        return statements

    @staticmethod
    def _result_to_dataframe(result) -> pd.DataFrame:
        """Build a DataFrame directly from the DBAPI/SQLAlchemy result rows.

        This avoids pandas SQL readers applying their own dtype inference on top
        of the values already returned by the database driver. Rows are fetched
        in chunks so the UI thread is not starved while large results stream in.
        """
        columns = list(result.keys())
        rows = fetch_rows_chunked(result)
        return records_to_dataframe(rows, columns)

    def _execute_generic_query(self, query: str, parameters: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
        """Execute generic query for non-MSSQL databases"""
        # Split statements with DELIMITER-awareness
        commands = self._split_sql_statements(query)

        if len(commands) > 1:
            # Multiple commands - execute all and capture SELECT results
            dataframes = []

            with self.engine.connect() as conn:
                for cmd in commands:
                    prepared = prepare_generic_sql(cmd, parameters) if parameters else None
                    executable_sql = prepared.query if prepared else cmd
                    executable_params = prepared.params if prepared else {}

                    if self._requires_postgresql_autocommit(cmd):
                        conn.commit()
                        result_df = self._execute_postgresql_autocommit_statement(executable_sql, executable_params)
                    elif self._is_select_query(cmd):
                        # Is SELECT - capture result
                        try:
                            result = conn.execute(text(executable_sql), executable_params)
                            df = self._result_to_dataframe(result)
                            logger.info(f"SELECT executed: {len(df)} rows returned")
                            dataframes.append(df)
                        except Exception as e:
                            logger.error(f"Error executing SELECT: {str(e)}")
                            raise
                    else:
                        # Not SELECT - execute as statement
                        conn.execute(text(executable_sql), executable_params)

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
            logger.info("Commands executed successfully.")
            return self._success_message_df("success_commands_plural")
        elif len(commands) == 1:
            # Single command - use the cleaned statement (DELIMITER stripped)
            cmd = commands[0]
            prepared = prepare_generic_sql(cmd, parameters) if parameters else None
            executable_sql = prepared.query if prepared else cmd
            executable_params = prepared.params if prepared else {}
            if self._requires_postgresql_autocommit(cmd):
                return self._execute_postgresql_autocommit_statement(executable_sql, executable_params)
            if self._is_select_query(cmd):
                # SELECT query - fetch rows directly so DB driver values are preserved
                with self.engine.connect() as conn:
                    result = conn.execute(text(executable_sql), executable_params)
                    df = self._result_to_dataframe(result)
                logger.info(f"Query executed successfully. Rows returned: {len(df)}")
                return df
            else:
                # Non-SELECT - execute as statement
                with self.engine.connect() as conn:
                    result = conn.execute(text(executable_sql), executable_params)
                    conn.commit()
                    rows_affected = result.rowcount

                    if rows_affected >= 0:
                        return self._success_message_df("success_command_rows", rows=rows_affected)
                    return self._success_message_df("success_command")
        else:
            # No commands (empty input or only DELIMITER directives)
            return self._success_message_df("no_commands")

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
            if self._requires_postgresql_autocommit(statement):
                result = self._execute_postgresql_autocommit_statement(statement)
                return 0
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

        # Skip if already on the same database (avoid unnecessary roundtrip)
        current_db = self.connection_params.get("database", "")
        if self.db_type == "databricks":
            if database.startswith("CATALOG:"):
                target = database[8:]
                if current_db.lower() == target.lower():
                    logger.debug(f"Already on catalog '{target}', skipping USE CATALOG")
                    return True
            elif database.startswith("SCHEMA:"):
                target = database[7:]
                current_schema = self.connection_params.get("databricks_schema", "")
                if current_schema.lower() == target.lower():
                    logger.debug(f"Already on schema '{target}', skipping USE SCHEMA")
                    return True
            elif "." not in database:
                # Schema-only for Databricks
                current_schema = self.connection_params.get("databricks_schema", "")
                if current_schema.lower() == database.lower():
                    logger.debug(f"Already on schema '{database}', skipping USE SCHEMA")
                    return True
        else:
            # Non-Databricks: simple database comparison
            if current_db.lower() == database.lower():
                logger.debug(f"Already on database '{database}', skipping USE")
                return True

        if self.db_type == "sqlserver" and not self._sqlserver_supports_use():
            return self._reconnect_sqlserver_database(database)

        try:
            use_command = self._build_use_command(database)
            # Log for debugging Databricks catalog/schema issues
            if self.db_type == "databricks":
                current_catalog = self.connection_params.get("databricks_catalog", self.connection_params.get("database", ""))
                current_schema = self.connection_params.get("databricks_schema", "default")
                logger.debug(f"Databricks change_database: target='{database}', current_catalog='{current_catalog}', current_schema='{current_schema}', command='{use_command}'")
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

            # Update internal params for Databricks (track catalog and schema separately)
            if self.db_type == "databricks":
                if database.startswith("CATALOG:"):
                    self.connection_params["database"] = database[8:]
                    self.connection_params["databricks_catalog"] = database[8:]
                elif database.startswith("SCHEMA:"):
                    self.connection_params["databricks_schema"] = database[7:]
                elif "." in database:
                    parts = database.split(".", 1)
                    self.connection_params["database"] = parts[0]
                    self.connection_params["databricks_catalog"] = parts[0]
                    self.connection_params["databricks_schema"] = parts[1]
                else:
                    self.connection_params["databricks_schema"] = database
            else:
                self.connection_params["database"] = database

            logger.info(f"Database changed to: {database}")
            return True

        except Exception as e:
            # For Databricks, add context about current catalog/schema
            if self.db_type == "databricks":
                current_catalog = self.connection_params.get("databricks_catalog", self.connection_params.get("database", ""))
                current_schema = self.connection_params.get("databricks_schema", "default")
                logger.error(f"Error changing database: {str(e)} (current catalog='{current_catalog}', schema='{current_schema}')")
            else:
                logger.error(f"Error changing database: {str(e)}")
            raise

    def _sqlserver_supports_use(self) -> bool:
        """Return whether the current SQL Server target supports USE statements."""
        if self.db_type != "sqlserver":
            return False
        if "sqlserver_supports_use" in self.connection_params:
            return bool(self.connection_params["sqlserver_supports_use"])
        return not _is_azure_sql_host(self.connection_params.get("host", ""))

    @staticmethod
    def _match_use_only_command(command: str):
        """Return a regex match when the command is a standalone USE statement."""
        import re

        return re.match(r"^\s*USE\s+[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$", str(command or ""), re.IGNORECASE)

    def _reconnect_sqlserver_database(self, database: str) -> bool:
        """Reconnect Azure SQL Database connections to switch databases."""
        reconnect_config = dict(self._connection_config or {})
        if not reconnect_config:
            raise RuntimeError("SQL Server reconnect configuration unavailable")

        reconnect_config["database"] = database
        self.disconnect()
        return self.connect(
            reconnect_config.pop("db_type"),
            reconnect_config.pop("host"),
            reconnect_config.pop("port"),
            reconnect_config.pop("database"),
            reconnect_config.pop("username", ""),
            reconnect_config.pop("password", ""),
            **reconnect_config,
        )

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
                # No prefix, no dot - need to determine if it's a catalog or schema
                # Heuristic: if it matches the current catalog name, it's a catalog switch
                # Otherwise, assume it's a schema within the current catalog
                current_catalog = self.connection_params.get("databricks_catalog", 
                                                             self.connection_params.get("database", ""))
                if current_catalog and database.lower() == current_catalog.lower():
                    # Already on this catalog, no action needed
                    logger.debug(f"Databricks: '{database}' matches current catalog, skipping USE")
                    return ""  # Empty command - will be skipped
                else:
                    # Try as catalog first (safer) - if fails, Databricks will error
                    # This handles the case where user specifies a catalog name directly
                    return f"USE CATALOG `{database}`"
        else:
            return f"USE {database}"

    def get_current_database(self) -> str:
        """Return current database name (or catalog for Databricks)"""
        return self.connection_params.get("database", "")

    def get_current_catalog(self) -> str:
        """Return current Databricks catalog name"""
        return self.connection_params.get("databricks_catalog", 
                                          self.connection_params.get("database", ""))

    def get_current_schema(self) -> str:
        """Return current Databricks schema name"""
        return self.connection_params.get("databricks_schema", "default")

    def get_current_database_context(self) -> str:
        """Return the current context shown to the user.

        Databricks uses the full catalog.schema context; other databases keep the
        existing single-database behavior.
        """
        if self.db_type == "databricks":
            current_catalog = self.get_current_catalog()
            current_schema = self.get_current_schema()
            context_name = _build_databricks_context_name(current_catalog, current_schema)
            return context_name or current_catalog or current_schema
        return self.get_current_database()

    def disconnect(self):
        """Disconnect from database"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            logger.info("Disconnected from database")
        if self._sqlserver_mfa_credential is not None:
            try:
                self._sqlserver_mfa_credential.close()
            except Exception:
                pass
            self._sqlserver_mfa_credential = None

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
