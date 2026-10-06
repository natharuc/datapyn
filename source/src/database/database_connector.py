"""
Database connector with support for multiple DBMS
"""

from typing import Optional, Dict, Any, List, Union, Callable, TypedDict
from numbers import Integral
import pandas as pd
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
import logging
import pyodbc
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

from src.utils.sql_parameter_service import (
    prepare_databricks_sql,
    prepare_generic_sql,
    prepare_sqlserver_batch,
)
from src.language import S
from src.database.namespace import format_context, parse_context
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


class OperationCancelled(Exception):
    """Raised when a running query was cancelled by the user."""


class SqlCommandResult(TypedDict):
    statement_index: int
    command: str
    rows_affected: Optional[int]


# Fetch rows from DB cursors in bounded chunks.
# the GIL for the whole result set, starving the Qt UI thread even though the
# query runs in a worker thread. Chunking adds explicit yield points so the
# UI keeps painting while large results stream into memory.
FETCH_CHUNK_ROWS = 5_000
DATAFRAME_BUILD_CHUNK_ROWS = 25_000


def _gil_yield() -> None:
    """Give the UI thread a chance to run between CPU-heavy chunks."""
    time.sleep(0.001)


def fetch_rows_chunked(
    cursor,
    chunk_size: int = FETCH_CHUNK_ROWS,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> list:
    """fetchall() replacement that yields the GIL between chunks.

    When ``is_cancelled`` becomes true, accumulated rows are dropped and
    ``OperationCancelled`` is raised so the worker does not keep a giant
    result set after the user hits Cancel.
    """
    rows: list = []
    while True:
        if is_cancelled and is_cancelled():
            rows.clear()
            raise OperationCancelled()
        chunk = cursor.fetchmany(chunk_size)
        if not chunk:
            break
        rows.extend(chunk)
        if is_cancelled and is_cancelled():
            rows.clear()
            raise OperationCancelled()
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
    """Keep Tauri's encrypted MSAL cache separate from legacy and other profiles."""
    explicit_workspace = os.environ.get("DATAPYN_WORKSPACE_PATH")
    if explicit_workspace:
        import hashlib

        workspace = os.path.normcase(str(Path(explicit_workspace).expanduser().resolve()))
        workspace_key = hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:24]
        host_key = hashlib.sha256(str(host).strip().casefold().encode("utf-8")).hexdigest()[:24]
        return f"datapyn_tauri_sqlserver_{workspace_key}_{host_key}"
    # The PyQt application has no explicit headless workspace. Preserve its
    # existing MSAL name so this distribution never migrates or replaces it.
    safe_host = host.replace(".", "_").replace(":", "_").replace("/", "_")
    return f"datapyn_sqlserver_{safe_host}"


def _get_sqlserver_auth_record_path(host: str) -> Path:
    """Get the persisted AuthenticationRecord path for a SQL Server host."""
    config_dir = _get_oauth_cache_dir()
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
        logger.warning("Failed to read SQL Server auth record (%s)", type(exc).__name__)
        return None


def _write_sqlserver_auth_record(host: str, authentication_record) -> None:
    """Persist the AuthenticationRecord for later silent token reuse."""
    record_path = _get_sqlserver_auth_record_path(host)
    try:
        record_path.write_text(authentication_record.serialize(), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to persist SQL Server auth record (%s)", type(exc).__name__)


def _is_azure_sql_host(host: str) -> bool:
    """Return True when the host is an Azure SQL Database endpoint."""
    normalized = str(host or "").strip().lower()
    return normalized.endswith(AZURE_SQL_HOST_SUFFIXES)


def _build_sqlserver_access_token_struct(access_token: str) -> bytes:
    """Pack an access token in the ODBC ACCESSTOKEN structure format."""
    token_bytes = str(access_token or "").encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def _create_sqlserver_tauri_linux_persistence(path: Path, name: str):
    """Persist MSAL tokens in Secret Service without a PyGObject dependency."""
    from keyring.backends.SecretService import Keyring
    from msal_extensions.persistence import BasePersistence, FilePersistence, PersistenceNotFound

    class SecretServicePersistence(BasePersistence):
        is_encrypted = True

        def __init__(self):
            self._signal = FilePersistence(str(path))
            # Explicit backend: never select a user-configured plaintext keyring
            # or silently fall back when the native secret service is unavailable.
            self._keyring = Keyring()
            self._service_name = "DataPyn.Tauri.SQLServer"
            self._account_name = name

        def save(self, content):
            self._keyring.set_password(self._service_name, self._account_name, content)
            self._signal.touch()

        def load(self):
            content = self._keyring.get_password(self._service_name, self._account_name)
            if content is None:
                raise PersistenceNotFound(message="SQL Server Entra token cache is not initialized")
            return content

        def time_last_modified(self):
            return self._signal.time_last_modified()

        def get_location(self):
            return self._signal.get_location()

    return SecretServicePersistence()


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

    if sys.platform in {"darwin", "linux"} and os.environ.get("DATAPYN_WORKSPACE_PATH"):
        # Azure Identity's macOS persistence uses one fixed service/account
        # pair even when options.name differs. Isolate the actual Keychain item,
        # not only its signal file, without changing the SDK's global factory.
        # On Linux, use the bundled Secret Service backend instead of the SDK's
        # PyGObject-based persistence, retaining encrypted storage and MSAL locks.
        class TauriBrowserCredential(InteractiveBrowserCredential):
            def _initialize_cache(self, is_cae: bool = False):
                import msal_extensions

                suffix = "cae" if is_cae else "nocae"
                name = f"{self._cache_options.name}_{suffix}"
                path = _get_oauth_cache_dir() / f"{name}.signal"
                if sys.platform == "darwin":
                    persistence = msal_extensions.KeychainPersistence(
                        str(path), "DataPyn.Tauri.SQLServer", name,
                    )
                else:
                    persistence = _create_sqlserver_tauri_linux_persistence(path, name)
                cache = msal_extensions.PersistedTokenCache(persistence)
                if is_cae:
                    self._cae_cache = cache
                else:
                    self._cache = cache
                return cache

        return TauriBrowserCredential(**kwargs)
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
    return format_context(catalog, schema)


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


def get_connector_switch_chip_value(connector) -> str:
    """Value shown on the SQL-block switch chip.

    PostgreSQL: schema (search_path). Other engines: database/catalog context.
    """
    if connector is None:
        return ""
    db_type = str(getattr(connector, "db_type", "") or "").lower()
    if db_type == "postgresql":
        getter = getattr(connector, "get_current_schema", None)
        if callable(getter):
            try:
                return str(getter() or "").strip() or "public"
            except Exception:
                return "public"
        return "public"
    return get_connector_database_context(connector)


def _get_oauth_cache_dir() -> Path:
    """Use explicit workspace settings in headless kernels and Qt in the legacy UI."""
    explicit_workspace = os.environ.get("DATAPYN_WORKSPACE_PATH")
    if explicit_workspace:
        config_dir = Path(explicit_workspace) / "oauth_cache"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    from src.core.workspace_service import get_workspace_service

    return get_workspace_service().get_config_dir("oauth_cache")


def _get_oauth_token_cache_path(host: str) -> Path:
    """Get path for OAuth token cache file.
    
    Tokens are stored per-host in the user's workspace config directory.
    """
    # Use a safe filename derived from the host
    safe_host = host.replace(".", "_").replace(":", "_").replace("/", "_")
    config_dir = _get_oauth_cache_dir()
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
            logger.debug("Databricks OAuth token cache persisted")
        except Exception as e:
            logger.warning("Failed to persist OAuth token (%s)", type(e).__name__)
    
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
            logger.warning("Failed to read cached OAuth token (%s)", type(e).__name__)
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
        self._abandoned = False
        self._active_mysql_thread_id: Optional[int] = None
        self._connection_config: Dict[str, Any] = {}
        self._sqlserver_mfa_credential = None
        self._last_command_results: list[SqlCommandResult] = []
        self.command_result_callback: Optional[Callable[[SqlCommandResult], None]] = None

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

            if db_type == "postgresql":
                initial_schema = (str(kwargs["schema"] or "") if kwargs.get("postgresql_search_path") is not None and "schema" in kwargs
                                  else str(kwargs.get("schema") or kwargs.get("postgresql_schema") or "public").strip() or "public")
                self.connection_params = {
                    "host": host,
                    "port": port,
                    "database": database,
                    "username": username,
                    "postgresql_schema": initial_schema,
                }
                if kwargs.get("postgresql_search_path") is not None:
                    self.connection_params.update(schema=initial_schema, postgresql_search_path=kwargs["postgresql_search_path"])
            self._register_engine_checkout_hooks(db_type)

            if db_type == "sqlserver" and sqlserver_auth_mode == SQLSERVER_AUTH_ENTRA_MFA:
                credential = sqlserver_mfa_credential

                @event.listens_for(self.engine, "do_connect")
                def on_do_connect(dialect, connection_record, cargs, cparams):
                    token = credential.get_token(SQLSERVER_ENTRA_SCOPE)
                    attrs_before = dict(cparams.get("attrs_before") or {})
                    attrs_before[SQL_COPT_SS_ACCESS_TOKEN] = _build_sqlserver_access_token_struct(token.token)
                    cparams["attrs_before"] = attrs_before

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
                        logger.info("Deleted stale Databricks OAuth cache")
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
                            self._register_engine_checkout_hooks(db_type)
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
            existing_pg_schema = str(self.connection_params.get("postgresql_schema") or "").strip()
            self.connection_params = {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "sqlserver_supports_use": not _is_azure_sql_host(host) if db_type == "sqlserver" else True,
            }
            if db_type == "postgresql":
                self.connection_params["postgresql_schema"] = existing_pg_schema or (
                    str(kwargs.get("schema") or kwargs.get("postgresql_schema") or "public").strip()
                    or "public"
                )
                if kwargs.get("postgresql_search_path") is not None:
                    self.connection_params.update(postgresql_search_path=kwargs["postgresql_search_path"],
                                                  postgresql_schema=str(kwargs.get("schema") or ""), schema=str(kwargs.get("schema") or ""))
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
                initial_schema = str(
                    kwargs.get("schema") or kwargs.get("databricks_schema") or "default"
                ).strip() or "default"
                if database:
                    self.connection_params["databricks_catalog"] = database
                    self.connection_params["databricks_schema"] = initial_schema
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
                        logger.warning("Could not query Databricks current catalog/schema (%s)", type(e).__name__)
                        self.connection_params["databricks_catalog"] = ""
                        self.connection_params["databricks_schema"] = "default"

            # PostgreSQL schema is applied on every pool checkout (search_path).
            if db_type == "postgresql" and not self.connection_params.get("postgresql_schema"):
                self.connection_params["postgresql_schema"] = (
                    str(kwargs.get("schema") or kwargs.get("postgresql_schema") or "public").strip()
                    or "public"
                )

            if db_type == "postgresql" and kwargs.get("postgresql_search_path") is not None:
                raw_conn = self.engine.raw_connection()
                try:
                    self._context_probe_required = True
                    self._reconcile_execution_context(raw_conn)
                finally:
                    raw_conn.close()

            logger.info(f"Connected to {self.SUPPORTED_DATABASES[db_type]}: {host}/{database}")
            return True

        except Exception as e:
            # Driver/SDK error messages can contain connection strings or tokens.
            logger.error(
                "Database connection error (%s; host=%s; database=%s): %s",
                db_type, host, database, type(e).__name__,
            )
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

        elif db_type in ("mysql", "mariadb"):
            # MariaDB uses PyMySQL (mysql dialect) — the C mariadb connector is not a runtime dep.
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"mysql+pymysql://{user_encoded}:{pass_encoded}@{host}:{port}/{database}?charset=utf8mb4", {}

        elif db_type == "postgresql":
            # URL encode username and password for special characters
            # Important for Azure PostgreSQL where user is "user@server"
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            connect_args = {}
            client_encoding = str(kwargs.get("postgresql_client_encoding", "") or "").strip()
            if client_encoding:
                connect_args["client_encoding"] = client_encoding
            initial_schema = str(
                kwargs.get("schema") or kwargs.get("postgresql_schema") or "public"
            ).strip() or "public"
            # New backends pick this up; pooled checkouts also SET search_path
            # because pool_size > 1 (same issue as SQL Server USE).
            search_path = (str(kwargs["postgresql_search_path"]) if kwargs.get("postgresql_search_path") is not None
                           else DatabaseConnector._postgresql_search_path_value(initial_schema))
            if kwargs.get("postgresql_search_path") is not None:
                # libpq options use backslash to preserve whitespace/backslashes.
                search_path = "".join("\\" + char if char.isspace() or char == "\\" else char for char in search_path)
            existing_options = str(connect_args.get("options") or "").strip()
            search_option = f"-csearch_path={search_path}"
            connect_args["options"] = (
                f"{existing_options} {search_option}".strip() if existing_options else search_option
            )
            return f"postgresql+psycopg2://{user_encoded}:{pass_encoded}@{host}:{port}/{database}", connect_args

        elif db_type == "databricks":
            # Databricks SQL Warehouse connection
            # Uses databricks-sql-connector with SQLAlchemy dialect
            http_path = kwargs.get("http_path", "")
            access_token = password
            # Telemetry runs in a background thread and can race with
            # SQLAlchemy/HTTP client shutdown (especially during OAuth
            # reconnects). DataPyn already has its own application logging.
            connect_args = {"enable_telemetry": False}
            
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
                logger.info("Using Databricks OAuth authentication with a persistent token cache")
            
            # Add query parameters
            params = []
            if http_path:
                params.append(f"http_path={quote_plus(http_path)}")
            if database:
                params.append(f"catalog={quote_plus(database)}")
                initial_schema = str(
                    kwargs.get("schema") or kwargs.get("databricks_schema") or "default"
                ).strip() or "default"
                params.append(f"schema={quote_plus(initial_schema)}")
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

        if getattr(self, "_abandoned", False):
            raise QueryBusyError(
                "Connection is blocked after a query failed to cancel on the server. "
                "Reconnect to continue."
            )

        if not self._query_lock.acquire(blocking=False):
            raise QueryBusyError("A query is still running on this connection")

        try:
            self._last_command_results = []
            return self._execute_query_unlocked(query, parameters=parameters)
        except OperationCancelled:
            raise
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
        frame = pd.DataFrame({"Result": [msg]})
        frame.attrs["datapyn_command_result"] = True
        frame.attrs["datapyn_command_results"] = self.get_last_command_results()
        return frame

    def get_last_command_results(self) -> list[SqlCommandResult]:
        """Snapshot of completed commands, including those before an error.

        The driver reported execution; transaction/commit behavior is unchanged.
        Consumers must not infer that a later rollback committed these changes.
        """
        return [dict(item) for item in sorted(self._last_command_results, key=lambda item: item["statement_index"])]

    def _command_label(self, statement: str) -> str:
        from datapyn_runtime.sql_context import sql_code_mask
        import re

        code = sql_code_mask(statement, self.db_type, identifiers=True).strip()
        words = re.finditer(r"[A-Za-z_]+|[()]", code)
        head = next(words, None)
        if head is None:
            return "SQL"
        label = head.group().upper()
        if label == "WITH":
            # A CTE may precede DML or SELECT; ignore commands inside its body.
            depth = 0
            for word in words:
                token = word.group().upper()
                if token == "(":
                    depth += 1
                elif token == ")":
                    depth = max(0, depth - 1)
                elif not depth and token in {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE"}:
                    return token
        return label

    def _is_data_command(self, statement: str) -> bool:
        label = self._command_label(statement)
        if label == "SELECT":
            from datapyn_runtime.sql_context import sql_code_mask
            import re

            depth = 0
            code = sql_code_mask(statement, self.db_type, identifiers=True)
            for word in re.finditer(r"[A-Za-z_]+|[()]", code):
                token = word.group().upper()
                if token == "(":
                    depth += 1
                elif token == ")":
                    depth = max(0, depth - 1)
                elif not depth and token == "INTO":
                    # SELECT INTO creates/populates a table without returning
                    # rows. Its affected count belongs in command feedback.
                    return False
                elif not depth and token == "SELECT" and self.db_type == "sqlserver":
                    if re.match(r"\s+(?:TOP\s*(?:\([^)]*\)|\d+)\s*)?@\w+\s*=", code[word.end():], re.IGNORECASE):
                        # SELECT @variable = expression updates batch state;
                        # it does not return a tabular SELECT result.
                        return False
        return label in {"SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN", "VALUES", "TABLE"}

    def _record_command_result(self, statement: str, statement_index: int, rows_affected=None, *, command: Optional[str] = None) -> None:
        count = int(rows_affected) if isinstance(rows_affected, Integral) and not isinstance(rows_affected, bool) and rows_affected >= 0 else None
        result: SqlCommandResult = {
            "statement_index": statement_index,
            "command": command or self._command_label(statement),
            "rows_affected": count,
        }
        self._last_command_results.append(result)
        callback = self.command_result_callback
        if callable(callback):
            try:
                callback(dict(result))
            except Exception as exc:
                logger.debug("Could not report SQL command completion: %s", type(exc).__name__)

    def _with_command_results(self, frames: list[pd.DataFrame], success_key="success_commands", *, query: Optional[str] = None):
        if not frames:
            if not self._last_command_results and query:
                from datapyn_runtime.sql_context import sql_statements

                statements = sql_statements(query, self.db_type)
                if statements:
                    # Successful execution may produce neither a result set
                    # nor per-statement counts (e.g. SELECT assignments). Show
                    # one confirmed execution, never claim untaken branches.
                    self._record_command_result(query, 1, command=self._command_label(statements[0]) if len(statements) == 1 else "SQL")
            return self._success_message_df(success_key)
        # Carry execution metadata once, without introducing a synthetic table
        # into mixed scripts or confusing real SELECT ... AS Result columns.
        carrier = next((frame for frame in frames if frame.attrs.get("datapyn_command_result") is not True), frames[0])
        carrier.attrs["datapyn_command_results"] = self.get_last_command_results()
        return frames[0] if len(frames) == 1 else frames

    @staticmethod
    def _cursor_has_result_set(cursor) -> bool:
        return bool(cursor.description) and len(cursor.description) > 0

    def _mssql_feedback_statements(self, batch: str) -> tuple[list[str], bool]:
        """Read metadata boundaries without changing the server's batch.

        Ordinary T-SQL permits omitted semicolons. Newline candidates are used
        only when every fragment is accepted as an independent SQL expression;
        INSERT SELECT, UNION and multiline clauses remain one unit. Control
        flow uses observed driver tokens because a branch may never execute.
        """
        from datapyn_runtime.sql_context import sql_code_mask, sql_statements
        import re

        masked = sql_code_mask(batch, "sqlserver", identifiers=True)
        if re.match(r"\s*(?:CREATE\s+(?:OR\s+ALTER\s+)?|ALTER\s+)(?:PROCEDURE|PROC|FUNCTION|TRIGGER)\b", masked, re.IGNORECASE):
            return [batch], False
        control_flow = bool(re.search(r"(?:^|[;\n])\s*(?:IF\b|WHILE\b|ELSE\b|BEGIN\b(?!\s+(?:TRAN|TRANSACTION)\b)|END\b)", masked, re.IGNORECASE))
        if control_flow:
            return [batch], True
        if self._command_label(batch) in {"EXEC", "EXECUTE"}:
            return [batch], True

        statements = []
        for statement in sql_statements(batch, "sqlserver"):
            code = sql_code_mask(statement, "sqlserver", identifiers=True)
            starts = list(re.finditer(r"(?im)^[ \t]*(?:DELETE|UPDATE|INSERT|SELECT|WITH|MERGE|CREATE|ALTER|DROP|TRUNCATE|USE|SET|DECLARE|EXEC|EXECUTE)\b", code))
            fragments = [statement[(match.start() if index else 0):(starts[index + 1].start() if index + 1 < len(starts) else len(statement))].strip() for index, match in enumerate(starts)]
            if len(fragments) > 1:
                from sqlglot import parse_one, exp
                from sqlglot.errors import ParseError

                try:
                    parsed = [parse_one(fragment, read="tsql") for fragment in fragments]
                    if all(node is not None and not isinstance(node, exp.Command) for node in parsed):
                        statements.extend(fragments)
                        continue
                except ParseError:
                    pass
            statements.append(statement)
        return statements, False

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

        if getattr(self, "_abandoned", False):
            raise QueryBusyError(
                "Connection is blocked after a query failed to cancel on the server. "
                "Reconnect to continue."
            )

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
        """Best-effort COUNT(*) over the user query. None if not countable.

        Sets ``_active_cursor`` so interrupt/cancel can stop a long warehouse COUNT.
        """
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
        prev_raw = getattr(self, "_active_raw_conn", None)
        prev_cur = getattr(self, "_active_cursor", None)
        try:
            raw = self.engine.raw_connection()
            self._active_raw_conn = raw
            cur = raw.cursor()
            self._active_cursor = cur
            if is_cancelled and is_cancelled():
                return None
            prepared = prepare_databricks_sql(count_sql, parameters) if parameters else None
            if prepared:
                cur.execute(prepared.query, prepared.params)
            else:
                cur.execute(count_sql)
            if is_cancelled and is_cancelled():
                return None
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
            return None
        except Exception as e:
            if self._cancelled or (is_cancelled and is_cancelled()):
                return None
            logger.info(f"Databricks COUNT estimation skipped: {_safe_exception_text(e)}")
            return None
        finally:
            self._active_cursor = prev_cur
            self._active_raw_conn = prev_raw
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
        self._prepare_context_tracking(query)
        use_match = self._match_use_only_command(query)
        if use_match:
            new_db = use_match.group(1)
            if self.db_type == "sqlserver" and not self._sqlserver_supports_use():
                self.change_database(new_db)
                return StreamExportResult(errors=[f"Database changed to: {new_db}"])

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
                self._reconcile_execution_context(raw_conn)
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
            # Skip blocking COUNT(*) before streaming — warehouse estimates can take
            # minutes and freeze perceived UX. Progress stays indeterminate until rows flow.
            # on_total is kept for API compatibility but not used for a pre-stream COUNT.

            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn
            cursor = raw_conn.cursor()
            self._active_cursor = cursor

            from datapyn_runtime.sql_context import sql_statements
            for statement in sql_statements(query, "databricks"):
                if parameters:
                    prepared = prepare_databricks_sql(statement, parameters)
                    cursor.execute(prepared.query, prepared.params)
                else:
                    cursor.execute(statement)
                if self._cancelled or (is_cancelled and is_cancelled()):
                    result.cancelled = True
                    return result
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    if not self._stream_write_result_set(
                        columns, cursor, base_path=base_path,
                        export_format=export_format, file_index=len(result.files) + 1,
                        result=result, csv_options=csv_options,
                        on_progress=on_progress, on_file_started=on_file_started,
                        is_cancelled=is_cancelled,
                    ):
                        break
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
                self._reconcile_execution_context(raw_conn)
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
        commands = self._execution_statements(query)
        result = StreamExportResult()
        file_index = 0
        raw_conn = None
        cursor = None

        if not commands:
            result.errors.append("No SQL commands to execute.")
            return result

        try:
            raw_conn, cursor = self._begin_cancellable_raw_query()
            for cmd in commands:
                if self._cancelled or (is_cancelled and is_cancelled()):
                    result.cancelled = True
                    break

                prepared = prepare_generic_sql(cmd, parameters) if parameters else None
                executable_sql = prepared.query if prepared else cmd
                executable_params = prepared.params if prepared else {}

                if self._requires_postgresql_autocommit(cmd):
                    self._execute_postgresql_autocommit_statement(executable_sql, executable_params)
                    continue

                if self._is_select_query(cmd):
                    self._execute_raw_statement(cursor, executable_sql, executable_params)
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
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
                        on_file_started=on_file_started,
                        is_cancelled=is_cancelled,
                    ):
                        result.cancelled = True
                        break
                else:
                    self._execute_raw_statement(cursor, executable_sql, executable_params)

            if not result.cancelled:
                try:
                    raw_conn.commit()
                except Exception:
                    pass
        except OperationCancelled:
            result.cancelled = True
        finally:
            self._end_cancellable_raw_query(raw_conn, cursor)

        if self._cancelled:
            result.cancelled = True
        return result

    def _execute_query_unlocked(
        self, query: str, parameters: Optional[List[Dict[str, Any]]] = None
    ) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        self._prepare_context_tracking(query)
        use_match = self._match_use_only_command(query)
        if use_match:
            new_db = use_match.group(1)
            logger.info(f"Detected USE command {new_db}")
            if self.db_type == "sqlserver" and not self._sqlserver_supports_use():
                self.change_database(new_db)
                self._record_command_result(query, 1)
                frame = pd.DataFrame({"Result": [f"Database changed to: {new_db}"]})
                frame.attrs["datapyn_command_result"] = True
                frame.attrs["datapyn_command_results"] = self.get_last_command_results()
                return frame

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

    def _ensure_not_cancelled(self) -> None:
        if self._cancelled:
            raise OperationCancelled()

    @staticmethod
    def _is_mysql_kill_access_denied(error: BaseException) -> bool:
        text = _safe_exception_text(error).lower()
        markers = (
            "access denied",
            "command denied",
            "kill denied",
            "er_kill_denied_error",
            "1045",
            "1095",
            "1227",
        )
        return any(marker in text for marker in markers)

    def _adapt_named_params_sql(self, sql: str, params: Optional[Dict[str, Any]]) -> tuple[str, Optional[Dict[str, Any]]]:
        if not params:
            return sql, None
        if self.db_type in ("postgresql", "mysql", "mariadb"):
            import re

            adapted = re.sub(r":(\w+)", r"%(\1)s", sql)
            return adapted, params
        return sql, params

    def _execute_raw_statement(self, cursor, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        adapted_sql, adapted_params = self._adapt_named_params_sql(sql, params)
        if adapted_params:
            cursor.execute(adapted_sql, adapted_params)
        else:
            cursor.execute(adapted_sql)

    def _cursor_to_dataframe(self, cursor) -> pd.DataFrame:
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        if not columns:
            return pd.DataFrame()
        rows = fetch_rows_chunked(cursor, is_cancelled=lambda: self._cancelled)
        return records_to_dataframe(rows, columns)

    def _capture_mysql_thread_id(self, cursor) -> None:
        if self.db_type not in ("mysql", "mariadb"):
            return
        try:
            cursor.execute("SELECT CONNECTION_ID()")
            row = cursor.fetchone()
            if row:
                self._active_mysql_thread_id = int(row[0])
        except Exception as exc:
            logger.debug("Could not read MySQL CONNECTION_ID(): %s", exc)

    def _spawn_admin_connection(self) -> tuple["DatabaseConnector", Any]:
        from src.database.block_connector_pool import connect_connector_from_config

        config = dict(getattr(self, "_connection_config", None) or {})
        if not config:
            raise ConnectionError("No connection configuration for admin connection")
        admin = connect_connector_from_config(config, password=config.get("password", ""))
        if not admin.is_connected() or admin.engine is None:
            raise ConnectionError("Failed to open admin connection for query cancel")
        return admin, admin.engine.raw_connection()

    def _kill_mysql_query(self, thread_id: int) -> None:
        admin = None
        admin_raw = None
        try:
            admin, admin_raw = self._spawn_admin_connection()
            cursor = admin_raw.cursor()
            try:
                cursor.execute(f"KILL QUERY {int(thread_id)}")
                logger.info("MySQL/MariaDB query cancelled via KILL QUERY %s", thread_id)
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        except Exception as exc:
            if self._is_mysql_kill_access_denied(exc):
                logger.debug("KILL QUERY skipped (insufficient privileges): %s", exc)
                return
            logger.warning(
                "KILL QUERY failed for thread %s: %s",
                thread_id,
                type(exc).__name__,
            )
        finally:
            if admin_raw is not None:
                try:
                    admin_raw.close()
                except Exception:
                    pass
            if admin is not None:
                try:
                    admin.disconnect()
                except Exception:
                    pass

    def _begin_cancellable_raw_query(self) -> tuple[Any, Any]:
        self._cancelled = False
        self._active_mysql_thread_id = None
        raw_conn = self.engine.raw_connection()
        self._active_raw_conn = raw_conn
        cursor = raw_conn.cursor()
        self._active_cursor = cursor
        self._capture_mysql_thread_id(cursor)
        return raw_conn, cursor

    def _end_cancellable_raw_query(self, raw_conn, cursor) -> None:
        self._active_raw_conn = None
        self._active_cursor = None
        self._active_mysql_thread_id = None
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if raw_conn is not None:
            self._reconcile_execution_context(raw_conn)
            try:
                raw_conn.close()
            except Exception:
                pass

    def _prepare_context_tracking(self, query: str) -> None:
        from datapyn_runtime.sql_context import changes_sql_context

        self._context_probe_required = changes_sql_context(query, self.db_type)

    def _reconcile_execution_context(self, raw_conn) -> None:
        """Read actual context once, on the physical connection that executed SQL.

        Parsing SQL only decides whether to probe. It cannot establish that a
        USE/SET succeeded, especially when a later statement or result set fails.
        PostgreSQL SET is transactional, so finish rollback before observing it.
        """
        if not getattr(self, "_context_probe_required", False):
            return
        self._context_probe_required = False
        queries = {
            "sqlserver": "SELECT DB_NAME(), SCHEMA_NAME()",
            "mysql": "SELECT DATABASE()",
            "mariadb": "SELECT DATABASE()",
            "databricks": "SELECT current_catalog(), current_schema()",
            "postgresql": "SELECT current_database(), current_schema(), current_setting('search_path')",
        }
        query = queries.get(self.db_type)
        if not query:
            return
        cursor = None
        try:
            if self.db_type == "postgresql":
                # A committed SET survives; SET LOCAL and an aborted transaction
                # disappear exactly as they will when this connection returns.
                raw_conn.rollback()
            cursor = raw_conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            if not row:
                return
            database = str(row[0] or "")
            previous_database = str(self.connection_params.get("database") or "")
            self.connection_params["database"] = database
            if self.db_type == "databricks":
                self.connection_params["databricks_catalog"] = database
                self.connection_params["databricks_schema"] = str(row[1] or "")
                self.connection_params["schema"] = str(row[1] or "")
            elif self.db_type == "postgresql":
                self.connection_params["postgresql_schema"] = str(row[1] or "")
                self.connection_params["schema"] = str(row[1] or "")
                self.connection_params["postgresql_search_path"] = str(row[2] or "")
            elif self.db_type in {"mysql", "mariadb"}:
                self.connection_params["schema"] = database
            elif database != previous_database:
                # The previous database's selected metadata schema may not exist
                # here. Use the login's actual default in the new database.
                self.connection_params["schema"] = str(row[1] or "")
            info = getattr(raw_conn, "info", None)
            if isinstance(info, dict) and self.db_type in {"mysql", "mariadb", "databricks"}:
                info["datapyn_namespace"] = (database, self.connection_params.get("databricks_schema", "") if self.db_type == "databricks" else "")
        except Exception as exc:
            logger.warning("Could not resolve SQL execution context: %s", exc)
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if self.db_type == "postgresql":
                try:
                    raw_conn.rollback()
                except Exception:
                    pass

    def force_disconnect(self) -> None:
        """Drop pooled connections so a stuck server-side query cannot block reuse."""
        self._active_raw_conn = None
        self._active_cursor = None
        self._active_mysql_thread_id = None
        self._cancelled = False
        self._abandoned = False
        if self.engine is not None:
            try:
                self.engine.dispose()
            except Exception as exc:
                logger.warning("Error disposing engine during force_disconnect: %s", exc)
            self.engine = None

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
            elif self.db_type in ("mysql", "mariadb"):
                thread_id = getattr(self, "_active_mysql_thread_id", None)
                if thread_id:
                    self._kill_mysql_query(thread_id)
                else:
                    logger.debug(
                        "Cancel requested for %s but no active connection id is available",
                        self.db_type,
                    )
            else:
                logger.debug("Cancel requested for %s (no driver interrupt available)", self.db_type)
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
        import re

        statement_offset = 0
        batch_commands = []
        opaque_batches = []
        for batch in batches:
            statements, opaque = self._mssql_feedback_statements(batch)
            entries = [(statement_offset + index, statement) for index, statement in enumerate(statements, start=1)]
            statement_offset += len(statements)
            batch_commands.append(entries)
            opaque_batches.append(opaque)

        try:
            if not self._sqlserver_supports_use():
                normalized_batches = []
                normalized_commands = []
                normalized_opaque = []
                for batch, entries, opaque in zip(batches, batch_commands, opaque_batches):
                    use_match = self._match_use_only_command(batch)
                    if use_match:
                        self.change_database(use_match.group(1))
                        for statement_index, statement in entries:
                            self._record_command_result(statement, statement_index)
                        continue
                    normalized_batches.append(batch)
                    normalized_commands.append(entries)
                    normalized_opaque.append(opaque)
                batches = normalized_batches
                batch_commands = normalized_commands
                opaque_batches = normalized_opaque

            if not batches:
                return self._success_message_df("success_commands")

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
                    dataframes.clear()
                    raise OperationCancelled()

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
                pending_commands = list(batch_commands[batch_idx - 1])
                opaque_batch = opaque_batches[batch_idx - 1]
                batch_feedback_start = len(self._last_command_results)
                extra_commands = 0
                batch_had_data = False
                while True:
                    completed_result = None
                    if self._cancelled:
                        dataframes.clear()
                        raise OperationCancelled()
                    try:
                        has_result = self._cursor_has_result_set(cursor)
                        rows_affected = getattr(cursor, "rowcount", None)
                        if has_result:
                            batch_had_data = True
                            columns = [col[0] for col in cursor.description]
                            rows = fetch_rows_chunked(
                                cursor, is_cancelled=lambda: self._cancelled
                            )
                            df = records_to_dataframe(rows, columns)
                            dataframes.append(df)
                            rows_affected = getattr(cursor, "rowcount", None)

                        # SQL Server runs the whole batch once (variables,
                        # temporary tables and deferred errors retain SSMS
                        # semantics). Consume driver result tokens in order.
                        candidate = None
                        for index, (_statement_index, statement) in enumerate([] if opaque_batch else pending_commands):
                            label = self._command_label(statement)
                            returns_data = self._is_data_command(statement) or label in {"EXEC", "EXECUTE"} or bool(re.search(r"\bOUTPUT\b", statement, re.IGNORECASE))
                            if has_result and returns_data:
                                candidate = index
                                break
                            if not has_result and not self._is_data_command(statement):
                                # These commands need not emit an ODBC token;
                                # a DML rowcount must not be assigned to SET/USE.
                                if isinstance(rows_affected, Integral) and rows_affected >= 0 and label in {"SET", "USE", "DECLARE", "PRINT", "BEGIN", "COMMIT", "ROLLBACK"}:
                                    continue
                                candidate = index
                                break
                        if candidate is not None:
                            for statement_index, statement in pending_commands[:candidate]:
                                if not self._is_data_command(statement):
                                    self._record_command_result(statement, statement_index)
                            statement_index, statement = pending_commands[candidate]
                            # OUTPUT can be followed by its own count token.
                            # Keep it pending when the initial count is unknown.
                            output_pending = has_result and self._command_label(statement) in {"INSERT", "UPDATE", "DELETE", "MERGE"} and not (isinstance(rows_affected, Integral) and rows_affected >= 0)
                            pending_commands = pending_commands[candidate if output_pending else candidate + 1:]
                            if not output_pending and not self._is_data_command(statement):
                                if isinstance(rows_affected, Integral) and rows_affected >= 0:
                                    self._record_command_result(statement, statement_index, rows_affected)
                                else:
                                    completed_result = (statement, statement_index)
                        elif not has_result and isinstance(rows_affected, Integral) and rows_affected >= 0 and batch_commands[batch_idx - 1]:
                            # Procedures/control flow or omitted separators can
                            # emit more rowcount tokens than parsed commands.
                            # Preserve every reported count with a neutral
                            # label rather than assigning it to IF/DECLARE.
                            base_index = batch_commands[batch_idx - 1][-1][0]
                            statement_index = base_index + extra_commands + (0 if opaque_batch else 1)
                            if not (opaque_batch and extra_commands == 0):
                                for following_index in range(batch_idx, len(batch_commands)):
                                    batch_commands[following_index] = [(index + 1, statement) for index, statement in batch_commands[following_index]]
                            self._record_command_result(batch, statement_index, rows_affected, command="SQL")
                            extra_commands += 1
                    except OperationCancelled:
                        dataframes.clear()
                        raise
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
                        if completed_result:
                            self._record_command_result(*completed_result)
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
                else:
                    # SET NOCOUNT and DDL may suppress individual rowcount
                    # tokens. Successful commands still receive feedback, with
                    # an unknown count rather than an invented zero.
                    if opaque_batch:
                        if len(self._last_command_results) == batch_feedback_start and not batch_had_data:
                            self._record_command_result(batch, batch_commands[batch_idx - 1][0][0], command="SQL")
                    else:
                        for statement_index, statement in pending_commands:
                            if not self._is_data_command(statement):
                                self._record_command_result(statement, statement_index)

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

            return self._with_command_results(dataframes, query="\nGO\n".join(batches))

        except OperationCancelled:
            raise
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
                self._reconcile_execution_context(raw_conn)
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
            
            from datapyn_runtime.sql_context import sql_statements
            frames = []
            for statement_index, statement in enumerate(sql_statements(query, "databricks"), start=1):
                if parameters:
                    prepared = prepare_databricks_sql(statement, parameters)
                    cursor.execute(prepared.query, prepared.params)
                else:
                    cursor.execute(statement)
                self._ensure_not_cancelled()
                rows_affected = getattr(cursor, "rowcount", None)
                if self._cursor_has_result_set(cursor):
                    frame = self._cursor_to_dataframe(cursor)
                    # Delta DML exposes a one-row metrics result rather than a
                    # DBAPI rowcount. Only DML-generated metrics are messages;
                    # SELECT num_affected_rows remains ordinary user data.
                    metrics = {"num_affected_rows", "num_updated_rows", "num_deleted_rows", "num_inserted_rows"}
                    if (self._command_label(statement) in {"INSERT", "UPDATE", "DELETE", "MERGE"}
                            and len(frame) == 1 and "num_affected_rows" in frame.columns
                            and set(frame.columns).issubset(metrics)):
                        rows_affected = frame["num_affected_rows"].iloc[0]
                        frame.attrs["datapyn_command_result"] = True
                    frames.append(frame)
                if not self._is_data_command(statement) or not self._cursor_has_result_set(cursor):
                    self._record_command_result(statement, statement_index, rows_affected)
            return self._with_command_results(frames, query=query)

        except OperationCancelled:
            raise
        except Exception as e:
            if self._cancelled:
                logger.info("Databricks query cancelled by user")
                raise OperationCancelled()
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
                self._reconcile_execution_context(raw_conn)
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

    def _execute_postgresql_autocommit_statement(self, statement: str, params: Optional[Dict[str, Any]] = None, *, statement_index: int = 1) -> pd.DataFrame:
        """Execute PostgreSQL DDL that must run outside a transaction block."""
        with self.engine.connect() as conn:
            autocommit_conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            result = autocommit_conn.execute(text(statement), params or {})
            rows_affected = getattr(result, "rowcount", -1)

        self._record_command_result(statement, statement_index, rows_affected)

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
    def _result_to_dataframe(
        result, is_cancelled: Optional[Callable[[], bool]] = None
    ) -> pd.DataFrame:
        """Build a DataFrame directly from the DBAPI/SQLAlchemy result rows.

        This avoids pandas SQL readers applying their own dtype inference on top
        of the values already returned by the database driver. Rows are fetched
        in chunks so the UI thread is not starved while large results stream in.
        """
        columns = list(result.keys())
        rows = fetch_rows_chunked(result, is_cancelled=is_cancelled)
        return records_to_dataframe(rows, columns)

    def _execution_statements(self, query: str) -> list:
        if self.db_type == "postgresql":
            from datapyn_runtime.sql_context import sql_statements

            return sql_statements(query, self.db_type)
        return self._split_sql_statements(query)

    def _execute_generic_query(self, query: str, parameters: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
        """Execute generic query for non-MSSQL databases using raw DBAPI for cancellation."""
        commands = self._execution_statements(query)
        if not commands:
            return self._success_message_df("no_commands")

        if len(commands) == 1:
            cmd = commands[0]
            prepared = prepare_generic_sql(cmd, parameters) if parameters else None
            executable_sql = prepared.query if prepared else cmd
            executable_params = prepared.params if prepared else {}
            if self._requires_postgresql_autocommit(cmd):
                return self._execute_postgresql_autocommit_statement(executable_sql, executable_params)

            raw_conn = None
            cursor = None
            try:
                raw_conn, cursor = self._begin_cancellable_raw_query()
                self._execute_raw_statement(cursor, executable_sql, executable_params)
                self._ensure_not_cancelled()
                is_data_command = self._is_data_command(cmd)
                if self._cursor_has_result_set(cursor):
                    df = self._cursor_to_dataframe(cursor)
                    if not is_data_command:
                        self._record_command_result(cmd, 1, getattr(cursor, "rowcount", None))
                        try:
                            raw_conn.commit()
                        except Exception:
                            pass
                    logger.info(f"Query executed successfully. Rows returned: {len(df)}")
                    return self._with_command_results([df])

                rows_affected = getattr(cursor, "rowcount", None)
                self._record_command_result(cmd, 1, rows_affected)
                try:
                    raw_conn.commit()
                except Exception:
                    pass
                if isinstance(rows_affected, int) and rows_affected >= 0:
                    return self._success_message_df("success_command_rows", rows=rows_affected)
                return self._success_message_df("success_command")
            finally:
                self._end_cancellable_raw_query(raw_conn, cursor)

        dataframes = []
        raw_conn = None
        cursor = None
        try:
            raw_conn, cursor = self._begin_cancellable_raw_query()
            for statement_index, cmd in enumerate(commands, start=1):
                self._ensure_not_cancelled()

                prepared = prepare_generic_sql(cmd, parameters) if parameters else None
                executable_sql = prepared.query if prepared else cmd
                executable_params = prepared.params if prepared else {}

                if self._requires_postgresql_autocommit(cmd):
                    self._execute_postgresql_autocommit_statement(executable_sql, executable_params, statement_index=statement_index)
                    continue

                self._execute_raw_statement(cursor, executable_sql, executable_params)
                self._ensure_not_cancelled()
                is_data_command = self._is_data_command(cmd)
                if self._cursor_has_result_set(cursor):
                    df = self._cursor_to_dataframe(cursor)
                    logger.info(f"SELECT executed: {len(df)} rows returned")
                    dataframes.append(df)
                if not is_data_command or not self._cursor_has_result_set(cursor):
                    self._record_command_result(cmd, statement_index, getattr(cursor, "rowcount", None))

            try:
                raw_conn.commit()
            except Exception:
                pass
        finally:
            self._end_cancellable_raw_query(raw_conn, cursor)

        return self._with_command_results(dataframes, "success_commands_plural", query=query)

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

        # Skip if already on the same database/schema (avoid unnecessary roundtrip)
        current_db = self.connection_params.get("database", "")
        if self.db_type == "databricks":
            parsed = parse_context(
                "databricks",
                database,
                current_catalog=self.get_current_catalog(),
                current_schema=self.get_current_schema(),
            )
            current_catalog = self.get_current_catalog()
            current_schema = self.get_current_schema()
            if parsed.schema_only:
                if parsed.schema and parsed.schema.lower() == current_schema.lower():
                    logger.debug(f"Already on schema '{parsed.schema}', skipping USE SCHEMA")
                    return True
            elif parsed.catalog_only:
                if parsed.catalog and parsed.catalog.lower() == current_catalog.lower():
                    logger.debug(f"Already on catalog '{parsed.catalog}', skipping USE CATALOG")
                    return True
            elif (
                parsed.catalog
                and parsed.schema
                and parsed.catalog.lower() == current_catalog.lower()
                and parsed.schema.lower() == current_schema.lower()
            ):
                logger.debug(
                    f"Already on '{parsed.catalog}.{parsed.schema}', skipping USE"
                )
                return True
        elif self.db_type == "postgresql":
            # PostgreSQL chip/switch value is a schema (search_path), not the database.
            target_schema = str(database or "").strip()
            real_db = str(self.connection_params.get("database") or "").strip()
            if real_db and target_schema.lower() == real_db.lower():
                logger.debug(
                    "Ignoring PostgreSQL schema switch to the database name '%s'",
                    target_schema,
                )
                return True
            current_schema = str(self.connection_params.get("postgresql_schema") or "").strip()
            if current_schema and current_schema.lower() == target_schema.lower():
                logger.debug(f"Already on schema '{database}', skipping SET search_path")
                return True
        else:
            # Other engines: simple database comparison
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
            if use_command:
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
                parsed = parse_context(
                    "databricks",
                    database,
                    current_catalog=self.get_current_catalog(),
                    current_schema=self.get_current_schema(),
                )
                if parsed.catalog:
                    self.connection_params["database"] = parsed.catalog
                    self.connection_params["databricks_catalog"] = parsed.catalog
                if parsed.schema:
                    self.connection_params["databricks_schema"] = parsed.schema
            elif self.db_type == "postgresql":
                # Keep the real database; only track schema (search_path).
                self.connection_params["postgresql_schema"] = database
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

    def _register_engine_checkout_hooks(self, db_type: str) -> None:
        """Apply database/schema context on every pooled connection.

        SQL Server ``USE`` and PostgreSQL ``SET search_path`` only affect the
        connection they run on. With pool_size > 1 the next query can check
        out a different backend and silently use the wrong database/schema.
        """
        if self.engine is None:
            return
        connector_ref = self

        def listen_checkout(handler) -> None:
            try:
                event.listens_for(self.engine, "checkout")(handler)
            except Exception:
                # Tests mock create_engine(); SQLAlchemy rejects MagicMock targets.
                return

        if db_type == "sqlserver":
            def on_sqlserver_checkout(dbapi_conn, connection_record, connection_proxy):
                if not connector_ref._sqlserver_supports_use():
                    return
                current_db = connector_ref.connection_params.get("database", "")
                if not current_db:
                    return
                try:
                    cursor = dbapi_conn.cursor()
                    cursor.execute(f"USE [{current_db}]")
                    cursor.close()
                except Exception:
                    pass
            listen_checkout(on_sqlserver_checkout)
            return
        if db_type == "postgresql":
            def on_postgresql_checkout(dbapi_conn, connection_record, connection_proxy):
                schema = (
                    str(connector_ref.connection_params.get("postgresql_schema") or "public").strip()
                    or "public"
                )
                try:
                    cursor = dbapi_conn.cursor()
                    search_path = connector_ref.connection_params.get("postgresql_search_path")
                    search_path_sql = "SET search_path TO " + (search_path or "''") if search_path is not None else DatabaseConnector._postgresql_search_path_sql(schema)
                    cursor.execute(search_path_sql)
                    cursor.close()
                except Exception:
                    pass
            listen_checkout(on_postgresql_checkout)
            return
        if db_type in {"mysql", "mariadb", "databricks"}:
            def on_namespace_checkout(dbapi_conn, connection_record, connection_proxy):
                database = str(connector_ref.connection_params.get("database") or "")
                if not database:
                    return
                schema = str(connector_ref.connection_params.get("databricks_schema") or "default") if db_type == "databricks" else ""
                desired = (database, schema)
                initial = getattr(connector_ref, "_connection_config", None) or {}
                initial_schema = str(initial.get("schema") or initial.get("databricks_schema") or "default") if db_type == "databricks" else ""
                applied = connection_record.info.setdefault("datapyn_namespace", (str(initial.get("database") or ""), initial_schema))
                if applied == desired:
                    return
                cursor = None
                try:
                    cursor = dbapi_conn.cursor()
                    quoted_database = "`" + database.replace("`", "``") + "`"
                    if db_type == "databricks":
                        cursor.execute(f"USE CATALOG {quoted_database}")
                        quoted_schema = "`" + schema.replace("`", "``") + "`"
                        cursor.execute(f"USE SCHEMA {quoted_schema}")
                    else:
                        cursor.execute(f"USE {quoted_database}")
                    connection_record.info["datapyn_namespace"] = desired
                finally:
                    if cursor is not None:
                        cursor.close()
            listen_checkout(on_namespace_checkout)

    @staticmethod
    def _postgresql_quote_ident(name: str) -> str:
        return '"' + str(name or "").replace('"', '""') + '"'

    @staticmethod
    def _postgresql_search_path_value(schema: str) -> str:
        return str(schema or "public").strip() or "public"

    @staticmethod
    def _postgresql_search_path_sql(schema: str) -> str:
        ident = DatabaseConnector._postgresql_quote_ident(
            DatabaseConnector._postgresql_search_path_value(schema)
        )
        return f"SET search_path TO {ident}"

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
            # PostgreSQL does not support USE for databases (needs a new connection).
            # This changes search_path within the current database.
            return self._postgresql_search_path_sql(database)
        elif self.db_type == "databricks":
            parsed = parse_context(
                "databricks",
                database,
                current_catalog=self.get_current_catalog(),
                current_schema=self.get_current_schema(),
            )
            if parsed.schema_only and parsed.schema:
                return f"USE SCHEMA `{parsed.schema}`"
            if parsed.catalog_only and parsed.catalog:
                return f"USE CATALOG `{parsed.catalog}`"
            if parsed.catalog and parsed.schema:
                return f"USE CATALOG `{parsed.catalog}`; USE SCHEMA `{parsed.schema}`"
            if parsed.catalog:
                return f"USE CATALOG `{parsed.catalog}`"
            if parsed.schema:
                return f"USE SCHEMA `{parsed.schema}`"
            return ""
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
        """Return current schema name (Databricks or PostgreSQL search_path)."""
        if self.db_type == "postgresql":
            if "postgresql_search_path" in self.connection_params:
                return str(self.connection_params.get("postgresql_schema") or "")
            return str(self.connection_params.get("postgresql_schema") or "public")
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
