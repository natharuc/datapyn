"""Offline contract for the Python integrations shipped with the desktop.

Importing this module is cheap. Verification is an explicit packaging check,
never a connection attempt or part of typing/editor startup.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from datetime import datetime, timezone
from decimal import Decimal
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
    "azure-identity", "azure-core", "azure-cosmos", "pymongo", "dnspython", "msal", "msal-extensions", "cryptography",
    "keyring", "paramiko", "bcrypt", "PyNaCl", "requests", "certifi", "pandas", "numpy", "polars", "pyarrow",
    "openpyxl", "fastexcel", "matplotlib", "plotly", "jedi", "sqlparse", "sqlglot", "jinja2",
    "python-tds", "sqlalchemy-pytds", "pyspnego", "pyOpenSSL",
) + (("sspilib",) if sys.platform == "win32" else ("gssapi", "krb5"))

DRIVER_IMPORTS = (
    "pyodbc", "pymssql", "psycopg2", "pymysql", "mysql.connector",
    "databricks.sql", "databricks.sqlalchemy", "databricks.sql.experimental.oauth_persistence",
    "azure.identity", "azure.cosmos", "pymongo", "bson", "dns.resolver", "msal", "msal_extensions", "keyring", "paramiko",
    "pytds", "sqlalchemy_pytds", "spnego", "OpenSSL",
) + (("sspilib",) if sys.platform == "win32" else ("gssapi", "krb5"))

DATABASE_DIALECTS = {
    "sqlserver": "mssql.pyodbc", "mysql": "mysql.pymysql", "mariadb": "mysql.pymysql",
    "postgresql": "postgresql.psycopg2", "databricks": "databricks", "sqlite": "sqlite",
}

DATABASE_AUTH_MODES = {
    "sqlserver": ["sql", *(["windows"] if sys.platform == "win32" else []), "ntlm", "kerberos", "entra_mfa"],
    "mysql": ["password"], "mariadb": ["password"], "postgresql": ["password"],
    "databricks": ["pat", "oauth"], "sqlite": ["local"],
    "elasticsearch": ["basic", "api_key"], "cosmosdb": ["key", "entra", "password"],
    "mongodb": ["password"],
}


def _document_clients() -> dict:
    """Exercise bundled HTTP/BSON/DNS code without credentials or network I/O."""
    import requests
    from azure.cosmos import ContainerProxy, CosmosClient, DatabaseProxy
    from bson import BSON, Decimal128, ObjectId
    from bson.codec_options import CodecOptions
    import dns.name
    import dns.rdata
    from pymongo import MongoClient

    with requests.Session() as session:
        assert callable(session.post)
    # CosmosClient construction fetches the account properties. Check its
    # public query interfaces without instantiating a client or asking Azure
    # Identity to resolve credentials in the build user's environment.
    assert all(callable(method) for method in (
        CosmosClient.get_database_client, CosmosClient.list_databases,
        DatabaseProxy.get_container_client, DatabaseProxy.list_containers,
        ContainerProxy.query_items,
    ))
    sample = {"_id": ObjectId("000000000000000000000001"), "amount": Decimal128(Decimal("123.40")),
              "at": datetime(2026, 1, 1, tzinfo=timezone.utc), "payload": b"\x00\xff"}
    assert BSON(BSON.encode(sample)).decode(codec_options=CodecOptions(tz_aware=True)) == sample
    assert dns.name.from_text("_mongodb._tcp.offline.example.").to_text() == "_mongodb._tcp.offline.example."
    srv = dns.rdata.from_text("IN", "SRV", "0 0 27017 node.offline.example.")
    txt = dns.rdata.from_text("IN", "TXT", '"authSource=admin"')
    assert srv.port == 27017 and srv.target.to_text() == "node.offline.example."
    assert txt.strings == (b"authSource=admin",)
    # A normal (not +srv) URI plus connect=False prevents both DNS discovery
    # and socket/monitor startup. This still validates PyMongo's option parser
    # and database/collection proxy initialization in the frozen artifact.
    with MongoClient("mongodb://offline.example:27017", connect=False, retryReads=False, retryWrites=False) as client:
        assert client["distribution"]["sample"].full_name == "distribution.sample"
    return {
        "elasticsearch": {"client": "requests.Session", "authentication": list(DATABASE_AUTH_MODES["elasticsearch"])},
        "cosmosdb": {"client": "azure.cosmos.CosmosClient", "authentication": list(DATABASE_AUTH_MODES["cosmosdb"]),
                     "api_clients": {"nosql": "azure.cosmos.CosmosClient", "mongodb": "pymongo.MongoClient"}},
        "mongodb": {"client": "pymongo.MongoClient", "authentication": list(DATABASE_AUTH_MODES["mongodb"]),
                    "dns_srv": True, "bson_types": True},
    }


def verify_runtime_distribution() -> dict:
    """Fail on absent bundled integrations; report system prerequisites separately.

    Imports every supported integration, loads relational dialects/DBAPIs and
    verifies document SDKs without opening connections or authenticating.
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

    try:
        databases.update(_document_clients())
    except Exception as error:
        errors.append(f"Document database clients: {error}")

    network_authentication = {}
    for mode in ("ntlm", "kerberos"):
        try:
            # Force the string-registered adapter and its native TLS libraries
            # to load in the frozen kernel, without credentials or network I/O.
            from src.database.sqlserver_network_auth import _tls_context
            uri, options = DatabaseConnector()._build_connection_string(
                "sqlserver", "offline.example", 1433, "sample",
                "OFFLINE\\example" if mode == "ntlm" else "example@OFFLINE",
                "test-only", sqlserver_auth_mode=mode,
            )
            engine = create_engine(uri, connect_args=options)
            try:
                assert engine.dialect.driver == "datapyn_tds"
                _tls_context(options["cafile"], "offline.example", False)
                network_authentication[mode] = engine.dialect.import_dbapi().__name__
            finally:
                engine.dispose()
        except Exception as error:
            errors.append(f"SQL Server {mode} adapter/TLS: {error}")

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
            "sqlserver_network_authentication": network_authentication,
            "sqlserver_odbc": {"available": bool(odbc_drivers), "drivers": odbc_drivers,
                               "system_dependency": True}}
