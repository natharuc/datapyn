"""Saved MFA profiles through the test and tab routes, without Azure/SQL I/O."""

from types import SimpleNamespace

import pyodbc
import pytest

from datapyn_runtime import database, transaction_settings
from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.supervisor import Supervisor
from src.database import database_connector
from test_connection_catalog import Secrets
from test_transaction_driver import OdbcConnection


@pytest.mark.parametrize("automatic_transactions", (False, True))
def test_saved_mfa_profile_connects_after_successful_test_in_both_tab_modes(
    monkeypatch, tmp_path, automatic_transactions,
):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    transaction_settings.settings_set({"automatic_transactions": automatic_transactions})
    credentials, issued_tokens, opened = [], [], []

    class Credential:
        def __init__(self, identity):
            self.identity = identity
            self.closed = 0

        def get_token(self, scope):
            assert scope == database_connector.SQLSERVER_ENTRA_SCOPE
            token = f"fixture-token-{len(issued_tokens)}"
            issued_tokens.append(token)
            return SimpleNamespace(token=token)

        def close(self):
            self.closed += 1

    def prepare_credential(**identity):
        credential = Credential(identity)
        credentials.append(credential)
        return credential

    def connect_odbc(connection_string, **options):
        # A token connection deliberately has no SQL user/password fallback.
        for forbidden in ("UID=", "PWD=", "AUTHENTICATION=", "TRUSTED_CONNECTION="):
            assert forbidden not in connection_string.upper()
        token = (options.get("attrs_before") or {}).get(database_connector.SQL_COPT_SS_ACCESS_TOKEN)
        if token is None:
            raise pyodbc.InterfaceError("28000", "Login failed for user ''.")
        assert token == database_connector._build_sqlserver_access_token_struct(issued_tokens[-1])
        raw = OdbcConnection(options.get("autocommit", False))
        opened.append(raw)
        return raw

    monkeypatch.setattr(database_connector, "_prepare_sqlserver_mfa_credential", prepare_credential)
    monkeypatch.setattr(pyodbc, "connect", connect_odbc)
    config = {
        "db_type": "sqlserver", "host": "fixture.database.windows.net", "port": 1433,
        "database": "fixture", "username": "reader@example.invalid", "password": "",
        "sqlserver_auth_mode": "entra_mfa", "tenant_id": "fixture-tenant",
        "driver": "ODBC Driver 18 for SQL Server",
    }
    catalog = ConnectionCatalog(tmp_path / "connections.json", Secrets())
    saved = catalog.save_connection({"name": "Fixture MFA", "config": config}, save_password=False)
    # Use the real credential/catalog routing shared by both RPC handlers.
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog = catalog
    supervisor.profile_path = tmp_path
    tested = supervisor._route({"connection_id": saved["id"], "config": config})
    assert tested["_automatic_transactions_snapshot"] is automatic_transactions
    assert database.test_connection(tested)["success"]
    assert opened[0].closed == 1 and credentials[0].closed == 1

    pool = database.ConnectorPool()
    try:
        routed = supervisor._route({"connection_id": saved["id"]})
        connector = pool.activate(routed, default=True)
        assert connector.automatic_transactions is automatic_transactions
        assert pool.explorer().context() == {
            "db_type": "sqlserver", "database": "fixture", "schema": "dbo",
        }
        assert pool.default_config["sqlserver_auth_mode"] == "entra_mfa"
        assert pool.default_config["username"] == config["username"]
        assert connector.execute_query("SELECT 1").iloc[0, 0] == 1
        if not automatic_transactions:
            raw = connector.get_manual_connection()
            connector.execute_query("BEGIN TRANSACTION")
            assert connector.has_pending_transaction()
            assert (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
            connector.execute_query("ROLLBACK TRANSACTION")
            assert (raw.commits, raw.rollbacks, raw.closed) == (0, 0, 0)
        assert len(opened) == (2 if automatic_transactions else 3)
        assert len(issued_tokens) == len(opened)
        expected_identity = {"host": config["host"], "login_hint": config["username"], "tenant_id": config["tenant_id"]}
        assert [credential.identity for credential in credentials] == [expected_identity, expected_identity]
    finally:
        pool.disconnect()
    assert all(raw.closed == 1 for raw in opened)
    assert all(credential.closed == 1 for credential in credentials)
