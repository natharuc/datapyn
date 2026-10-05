"""Authentication logs must not disclose credentials, SDK payloads or cache paths."""

import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import quote_plus

import pytest

from src.database import database_connector as connector


PASSWORD = "private-password-7:+/@"
ACCESS_TOKEN = "private-access-token-7"
REFRESH_TOKEN = "private-refresh-token-7"
DRIVER = "ODBC Driver 18 for SQL Server"


def assert_private_logs(caplog, *private_values):
    for value in (PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN, *private_values):
        assert value not in caplog.text
        assert quote_plus(value) not in caplog.text


@pytest.mark.parametrize("db_type", ["sqlserver", "postgresql", "mysql", "mariadb", "databricks"])
def test_connection_failure_logs_metadata_without_driver_credentials(monkeypatch, caplog, db_type):
    """Run the actual URL builder and a driver failure that echoes its auth payload."""
    caplog.set_level(logging.DEBUG, logger=connector.__name__)
    captured = {}

    def create_engine(url, **kwargs):
        captured["url"] = url
        raise RuntimeError(f"Cannot connect: {url}; access_token={ACCESS_TOKEN}; refresh_token={REFRESH_TOKEN}")

    monkeypatch.setattr(connector, "create_engine", create_engine)
    database = connector.DatabaseConnector()
    with pytest.raises(RuntimeError):
        database.connect(db_type, "db.example", 1433, "analytics", "private-login", PASSWORD, driver=DRIVER)

    assert quote_plus(PASSWORD) in captured["url"], "The test must exercise the credential-bearing driver URL"
    assert_private_logs(caplog, captured["url"], "private-login")
    assert db_type in caplog.text and "db.example" in caplog.text and "analytics" in caplog.text
    assert "RuntimeError" in caplog.text


def test_databricks_oauth_retry_logs_status_without_cache_location(monkeypatch, tmp_path, caplog):
    """Exercise cache creation, persistence, expiry deletion and real connect retry."""
    caplog.set_level(logging.DEBUG, logger=connector.__name__)
    workspace = tmp_path / "private-workspace-location"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
    host = "warehouse.example"
    cache_path = connector._get_oauth_token_cache_path(host)
    cache = connector.DatabricksOAuthTokenCache(cache_path)
    cache.persist(host, SimpleNamespace(access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN))
    assert json.loads(cache_path.read_text()) == {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN}

    expired = MagicMock()
    expired.connect.return_value.__enter__.side_effect = KeyError("access_token")
    refreshed = MagicMock()
    engine_factory = MagicMock(side_effect=[expired, refreshed])
    monkeypatch.setattr(connector, "create_engine", engine_factory)
    database = connector.DatabaseConnector()
    assert database.connect("databricks", host, 443, "analytics", http_path="/sql/warehouse")

    assert engine_factory.call_count == 2
    expired.dispose.assert_called_once()
    assert not cache_path.exists()
    assert_private_logs(caplog, str(workspace), str(cache_path), "private-workspace-location")
    assert "Using Databricks OAuth authentication" in caplog.text
    assert "Deleted stale Databricks OAuth cache" in caplog.text
    assert host in caplog.text and "analytics" in caplog.text


@pytest.mark.parametrize("operation", ["persist", "read"])
def test_databricks_cache_failure_does_not_log_sdk_or_file_error_payload(monkeypatch, tmp_path, caplog, operation):
    caplog.set_level(logging.DEBUG, logger=connector.__name__)
    path = tmp_path / "private-cache-location.json"
    path.write_text("{}")
    cache = connector.DatabricksOAuthTokenCache(path)

    def fail(*args, **kwargs):
        raise RuntimeError(f"{path}: access_token={ACCESS_TOKEN}; refresh_token={REFRESH_TOKEN}")

    if operation == "persist":
        monkeypatch.setattr(type(path), "write_text", fail)
        cache.persist("warehouse.example", SimpleNamespace(access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN))
    else:
        monkeypatch.setattr(type(path), "read_text", fail)
        assert cache.read("warehouse.example") is None

    assert_private_logs(caplog, str(path))
    assert "RuntimeError" in caplog.text
    assert f"Failed to {operation}" in caplog.text


@pytest.mark.parametrize("operation", ["write", "read"])
def test_sqlserver_auth_record_failures_do_not_log_serialized_credentials(monkeypatch, tmp_path, caplog, operation):
    caplog.set_level(logging.DEBUG, logger=connector.__name__)
    path = tmp_path / "private-auth-record.json"
    path.write_text("serialized authentication record")
    monkeypatch.setattr(connector, "_get_sqlserver_auth_record_path", lambda host: path)

    def fail(*args, **kwargs):
        raise ValueError(f"{path}: access_token={ACCESS_TOKEN}; password={PASSWORD}")

    if operation == "write":
        connector._write_sqlserver_auth_record("db.example", SimpleNamespace(serialize=fail))
    else:
        monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(AuthenticationRecord=SimpleNamespace(deserialize=fail)))
        assert connector._read_sqlserver_auth_record("db.example") is None

    assert_private_logs(caplog, str(path))
    assert "SQL Server auth record" in caplog.text and "ValueError" in caplog.text
