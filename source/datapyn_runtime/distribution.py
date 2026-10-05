"""Offline contract for the Python integrations shipped with the desktop.

Importing this module is cheap. Verification is an explicit packaging check,
never a connection attempt or part of typing/editor startup.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import ssl
import sys


# Include metadata as well as Python modules: SQLAlchemy discovers the
# Databricks dialect through distribution entry points, and authentication
# libraries use their distribution versions at runtime.
PACKAGED_DISTRIBUTIONS = (
    "SQLAlchemy", "pyodbc", "pymssql", "psycopg2-binary", "PyMySQL",
    "mysql-connector-python", "databricks-sql-connector", "databricks-sqlalchemy",
    "azure-identity", "azure-core", "msal", "msal-extensions", "cryptography",
    "keyring", "requests", "certifi", "pandas", "numpy", "polars", "pyarrow",
    "openpyxl", "fastexcel", "matplotlib", "plotly", "jedi", "sqlparse", "sqlglot", "jinja2",
)

DRIVER_IMPORTS = (
    "pyodbc", "pymssql", "psycopg2", "pymysql", "mysql.connector",
    "databricks.sql", "databricks.sqlalchemy", "databricks.sql.experimental.oauth_persistence",
    "azure.identity", "msal", "msal_extensions", "keyring",
)

DATABASE_DIALECTS = {
    "sqlserver": "mssql.pyodbc", "mysql": "mysql.pymysql", "mariadb": "mysql.pymysql",
    "postgresql": "postgresql.psycopg2", "databricks": "databricks", "sqlite": "sqlite",
}

DATABASE_AUTH_MODES = {
    "sqlserver": ["sql", "windows", "entra_mfa"],
    "mysql": ["password"], "mariadb": ["password"], "postgresql": ["password"],
    "databricks": ["pat", "oauth"], "sqlite": ["local"],
}


def verify_runtime_distribution() -> dict:
    """Fail on absent bundled integrations; report system prerequisites separately.

    This intentionally imports every supported driver and loads its SQLAlchemy
    dialect/DBAPI without opening an engine connection or authenticating.
    """
    errors = []
    versions = {}
    for name in PACKAGED_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except Exception as error:
            errors.append(f"{name} metadata: {error}")
    for name in DRIVER_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as error:
            errors.append(f"{name} import: {error}")

    databases = {}
    from sqlalchemy.dialects import registry
    for name, dialect_name in DATABASE_DIALECTS.items():
        try:
            dialect = registry.load(dialect_name)
            dbapi = dialect.import_dbapi()
            from sqlalchemy import create_engine
            from src.database.database_connector import DatabaseConnector
            if name == "sqlite":
                uri, options = "sqlite://", {}
            else:
                # Construct pools and dialects, but never checkout/connect.
                uri, options = DatabaseConnector()._build_connection_string(
                    name, "offline.example", 443 if name == "databricks" else 5432,
                    "sample", "example", "test-only", driver="ODBC Driver 18 for SQL Server",
                    http_path="/sql/offline",
                )
            engine = create_engine(uri, connect_args=options)
            engine.dispose()
            databases[name] = {"dialect": dialect_name, "dbapi": dbapi.__name__,
                               "authentication": list(DATABASE_AUTH_MODES[name])}
        except Exception as error:
            errors.append(f"{name} dialect/DBAPI: {error}")

    frozen = bool(getattr(sys, "frozen", False))
    tools = {}
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for name in ("uv", "ruff"):
        bundled = root / f"{name}{'.exe' if sys.platform == 'win32' else ''}"
        resolved = str(bundled) if frozen and bundled.is_file() else (None if frozen else shutil.which(name))
        tools[name] = bool(resolved and os.access(resolved, os.X_OK))
        if not tools[name]:
            errors.append(f"{name}: {'bundled executable' if frozen else 'build executable'} missing")

    try:
        import certifi
        # TLS/OAuth must resolve the packaged CA file as well as Python imports.
        ssl.create_default_context(cafile=certifi.where())
    except Exception as error:
        errors.append(f"TLS CA bundle: {error}")

    if errors:
        raise RuntimeError("Desktop runtime distribution is incomplete:\n" + "\n".join(errors))

    import pyodbc
    try:
        odbc_drivers = [name for name in pyodbc.drivers() if "sql server" in name.lower()]
    except Exception:
        odbc_drivers = []
    return {"frozen": frozen, "platform": sys.platform, "python_version": sys.version.split()[0],
            "databases": databases, "packages": versions, "tools": tools,
            "tls_ca_bundle": True,
            "sqlserver_odbc": {"available": bool(odbc_drivers), "drivers": odbc_drivers,
                               "system_dependency": True}}
