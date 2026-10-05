from __future__ import annotations

import importlib.metadata
from pathlib import Path
import socket
import sys

import pytest

from datapyn_runtime import distribution
from src.database.database_connector import DatabaseConnector


def test_native_password_backend_is_loadable_without_reading_credentials(monkeypatch):
    import importlib
    backend_module, backend_class = {
        'win32': ('keyring.backends.Windows', 'WinVaultKeyring'),
        'linux': ('keyring.backends.SecretService', 'Keyring'),
        'darwin': ('keyring.backends.macOS', 'Keyring'),
    }[sys.platform]
    backend = getattr(importlib.import_module(backend_module), backend_class)
    def forbidden(*args, **kwargs):
        pytest.fail('Packaging checks must not read or write user credentials')
    for method in ('get_password', 'set_password', 'delete_password'):
        monkeypatch.setattr(backend, method, forbidden)
    assert backend() is not None
    if sys.platform == 'linux':
        importlib.import_module('secretstorage')
        importlib.import_module('jeepney')
        assert all(importlib.metadata.version(name) for name in ('SecretStorage', 'jeepney'))


def test_distribution_loads_every_legacy_driver_and_dialect_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Distribution verification must not open database/network connections")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    report = distribution.verify_runtime_distribution()
    assert set(report["databases"]) == set(DatabaseConnector.SUPPORTED_DATABASES) | {"sqlite"}
    assert report["databases"]["databricks"]["dbapi"] == "databricks.sql"
    assert report["databases"]["mariadb"]["dbapi"] == "pymysql"
    assert report["databases"]["sqlserver"]["authentication"] == ["sql", "windows", "entra_mfa"]
    assert report["databases"]["databricks"]["authentication"] == ["pat", "oauth"]
    assert all(report["packages"].values())
    assert report["tls_ca_bundle"] is True


def test_missing_distribution_metadata_fails_before_packaging(monkeypatch):
    original = importlib.metadata.version
    def without_databricks(name):
        if name == "databricks-sqlalchemy":
            raise importlib.metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(importlib.metadata, "version", without_databricks)
    with pytest.raises(RuntimeError, match="databricks-sqlalchemy metadata"):
        distribution.verify_runtime_distribution()


def test_missing_dialect_cannot_pass_on_driver_import_alone(monkeypatch):
    from sqlalchemy.dialects import registry
    original = registry.load
    def unavailable(name):
        if name == "databricks":
            raise RuntimeError("Entry point not included")
        return original(name)
    monkeypatch.setattr(registry, "load", unavailable)
    with pytest.raises(RuntimeError, match="databricks dialect/DBAPI: Entry point not included"):
        distribution.verify_runtime_distribution()


def test_missing_native_odbc_is_reported_as_machine_prerequisite(monkeypatch):
    import pyodbc
    monkeypatch.setattr(pyodbc, "drivers", lambda: [])
    report = distribution.verify_runtime_distribution()
    assert report["sqlserver_odbc"] == {"available": False, "drivers": [], "system_dependency": True}
    assert "sqlserver" in report["databases"]


def test_missing_tls_ca_file_cannot_pass_on_imports_alone(monkeypatch, tmp_path):
    import certifi
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "absent-ca.pem"))
    with pytest.raises(RuntimeError, match="TLS CA bundle"):
        distribution.verify_runtime_distribution()


def test_frozen_runtime_requires_its_own_tools_even_when_path_has_them(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(distribution.shutil, "which", lambda name: "/external/" + name)
    with pytest.raises(RuntimeError, match="uv: bundled executable missing"):
        distribution.verify_runtime_distribution()
    suffix = ".exe" if sys.platform == "win32" else ""
    for name in ("uv", "ruff"):
        tool = tmp_path / (name + suffix)
        tool.write_text("bundled tool", encoding="utf-8")
        tool.chmod(0o755)
    report = distribution.verify_runtime_distribution()
    assert report["frozen"] is True
    assert report["tools"] == {"uv": True, "ruff": True}


@pytest.mark.parametrize("db_type", ["sqlserver", "mysql", "mariadb", "postgresql", "databricks"])
def test_production_dialects_build_engines_offline(db_type, monkeypatch, tmp_path):
    """Cover dynamically discovered dialect initialization and DBAPI binaries."""
    from sqlalchemy import create_engine
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    connector = DatabaseConnector()
    uri, args = connector._build_connection_string(
        db_type, "offline.example", 443 if db_type == "databricks" else 5432,
        "sample", "example", "test-only", driver="ODBC Driver 18 for SQL Server", http_path="/sql/offline",
    )
    engine = create_engine(uri, connect_args=args)
    try:
        assert engine.dialect.name == ("mysql" if db_type == "mariadb" else "mssql" if db_type == "sqlserver" else db_type)
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("auth", ["sql", "windows", "entra_mfa"])
def test_sqlserver_authentication_options_remain_available_offline(auth):
    from urllib.parse import unquote_plus
    uri, args = DatabaseConnector()._build_connection_string(
        "sqlserver", "offline.example", 1433, "sample", "example", "test-only",
        driver="ODBC Driver 18 for SQL Server", sqlserver_auth_mode=auth,
    )
    text = unquote_plus(uri)
    assert args == {}
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in text
    if auth == "windows":
        assert "Trusted_Connection=yes" in text and "PWD=" not in text
    elif auth == "entra_mfa":
        assert "Encrypt=yes" in text and "PWD=" not in text and "UID=" not in text
    else:
        assert "UID=example;PWD=test-only" in text


def test_databricks_oauth_factory_requires_no_qt_or_browser_until_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    uri, args = DatabaseConnector()._build_connection_string(
        "databricks", "offline.example", 443, "sample", "", "", http_path="/sql/offline",
    )
    assert "databricks://@offline.example:443" in uri
    assert args["auth_type"] == "databricks-oauth"
    assert Path(args["experimental_oauth_persistence"]._file_path).is_relative_to(tmp_path)
