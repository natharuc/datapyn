"""Physical connection hooks survive manual execution without pool resets.

MFA credentials and ODBC are fake; PostgreSQL uses only a local protocol fixture.
Neither test authenticates against an external service or reads credential caches.
"""

import struct
from types import SimpleNamespace

import pyodbc
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from src.database import database_connector as module
from src.database.database_connector import DatabaseConnector, SQL_COPT_SS_ACCESS_TOKEN, SQLSERVER_ENTRA_SCOPE
from test_transaction_driver import OdbcConnection
from test_ssh_postgres_wire import postgres_wire, database_tls_server  # noqa: F401


@pytest.fixture
def mfa_driver(monkeypatch):
    credentials, opened = [], []

    class Credential:
        def __init__(self):
            self.scopes = []
            self.closed = 0
            credentials.append(self)

        def get_token(self, scope):
            self.scopes.append(scope)
            return SimpleNamespace(token=f"fixture-token-{len(credentials)}-{len(self.scopes)}")

        def close(self):
            self.closed += 1

    def connect(*args, **kwargs):
        token = kwargs.get("attrs_before", {}).get(SQL_COPT_SS_ACCESS_TOKEN)
        if token is None:
            raise pyodbc.InterfaceError("28000", "Login failed for user ''. (18456)")
        raw = OdbcConnection(autocommit=kwargs.get("autocommit", False))
        opened.append((args, kwargs, raw))
        return raw

    monkeypatch.setattr(module, "_prepare_sqlserver_mfa_credential", lambda **kwargs: Credential())
    monkeypatch.setattr(pyodbc, "connect", connect)
    return SimpleNamespace(credentials=credentials, opened=opened)


def open_mfa(automatic_transactions):
    connector = DatabaseConnector()
    assert connector.connect("sqlserver", "fixture.database.windows.net", 1433, "sample", "hint@example.invalid", "",
                             driver="ODBC Driver 18 for SQL Server", sqlserver_auth_mode="entra_mfa",
                             automatic_transactions=automatic_transactions)
    return connector


def assert_mfa_connections(driver):
    tokens = []
    for args, kwargs, raw in driver.opened:
        packed = kwargs["attrs_before"][SQL_COPT_SS_ACCESS_TOKEN]
        length = struct.unpack("<I", packed[:4])[0]
        assert length == len(packed) - 4
        tokens.append(packed[4:].decode("utf-16-le"))
        connection_string = args[0].upper()
        for conflicting_auth in ("UID=", "PWD=", "TRUSTED_CONNECTION=", "AUTHENTICATION="):
            assert conflicting_auth not in connection_string
        assert "ENCRYPT=YES" in connection_string
    assert len(set(tokens)) == len(tokens)
    assert all(scope == SQLSERVER_ENTRA_SCOPE for credential in driver.credentials for scope in credential.scopes)
    assert sum(len(credential.scopes) for credential in driver.credentials) == len(driver.opened)


@pytest.mark.parametrize("automatic_transactions", [True, False])
def test_mfa_authenticates_every_physical_connection_in_both_transaction_modes(mfa_driver, automatic_transactions):
    connector = open_mfa(automatic_transactions)
    try:
        expected = 1 if automatic_transactions else 2
        assert len(mfa_driver.opened) == expected
        assert connector.execute_query("SELECT 1").iloc[0, 0] == 1
        if not automatic_transactions:
            raw = connector.get_manual_connection()
            assert raw is mfa_driver.opened[1][2]
            assert all(autocommit for _, autocommit in raw.commands)
            connector.execute_query("BEGIN TRANSACTION")
            connector.execute_query("SELECT 1")
            assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (1, 0, 0, 0)
            connector.execute_query("COMMIT TRANSACTION")
            assert (raw.transaction_count, raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0, 0)
        assert_mfa_connections(mfa_driver)
    finally:
        connector.disconnect()
    assert all(credential.closed == 1 for credential in mfa_driver.credentials)


def test_mfa_refreshes_tokens_for_metadata_reconnect_and_manual_database_switch(mfa_driver):
    connector = open_mfa(False)
    try:
        original = connector.get_manual_connection()
        connector.engine.dispose()
        with connector.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar() == 1
        assert connector.get_manual_connection() is original
        assert (original.commits, original.rollbacks, original.closed) == (0, 0, 0)
        connector.execute_query("USE other_database")
        assert connector.connection_params["database"] == "other_database"
        assert connector.get_manual_connection() is not original
        assert (original.commits, original.rollbacks, original.closed) == (0, 0, 1)
        assert len(mfa_driver.opened) == 5
        assert_mfa_connections(mfa_driver)
    finally:
        connector.disconnect()
    assert all(credential.closed == 1 for credential in mfa_driver.credentials)


def test_manual_factory_preserves_ordered_parameter_and_connection_override_hooks(tmp_path):
    """SSH hooks may return a DBAPI connection instead of changing parameters."""
    import sqlite3

    connector = DatabaseConnector()
    path = tmp_path / "manual-hooks.db"
    connector._execution_connection_string = "sqlite:///" + path.as_posix()
    connector.engine = create_engine(connector._execution_connection_string)
    connector.db_type = "sqlite"
    connector.automatic_transactions = False
    calls = []
    returned = []

    def global_parameters(dialect, connection_record, args, params):
        calls.append("global")
        params["timeout"] = 1

    def change_parameters(dialect, connection_record, args, params):
        calls.append("parameters")
        assert params["timeout"] == 1
        params["isolation_level"] = None

    def override_connection(dialect, connection_record, args, params):
        calls.append("override")
        assert params["isolation_level"] is None
        connection = sqlite3.connect(*args, **params)
        returned.append(connection)
        return connection

    event.listen(Engine, "do_connect", global_parameters)
    event.listen(connector.engine, "do_connect", change_parameters)
    event.listen(connector.engine, "do_connect", override_connection)
    try:
        raw = connector.get_manual_connection()
        assert calls == ["global", "parameters", "override"]
        assert raw is returned[0]
        assert raw.isolation_level is None
        assert connector.get_manual_connection() is raw
        assert calls == ["global", "parameters", "override"]
    finally:
        connector.disconnect()
        event.remove(Engine, "do_connect", global_parameters)


def test_postgresql_manual_hook_enables_native_autocommit_before_first_statement(postgres_wire):
    """Use the actual psycopg2/SQLAlchemy stack with a loopback-only endpoint."""
    connector = DatabaseConnector()
    try:
        assert connector.connect("postgresql", "127.0.0.1", postgres_wire.server_address[1], "docfis", "pg-test", "pg-secret",
                                 sslmode="require", gssencmode="disable", automatic_transactions=False)
        raw = connector.get_manual_connection()
        assert raw.autocommit is True
        assert postgres_wire.accepted_logins == 2
        assert not any(query.strip().upper() in {"BEGIN", "COMMIT", "ROLLBACK"} for query in postgres_wire.queries)
        connector.execute_query("BEGIN TRANSACTION")
        assert connector.has_pending_transaction()
        assert connector.execute_query("SELECT 1").iloc[0, 0] == 1
        assert connector.has_pending_transaction()
        connector.execute_query("COMMIT")
        assert not connector.has_pending_transaction()
        assert postgres_wire.wire_errors == []
    finally:
        connector.disconnect()
