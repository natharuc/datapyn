"""
Testes do ConnectionManager
"""

import pytest
import json

from src.core.connection_ref import ConnectionRef
from src.database.connection_manager import DuplicateConnectionError


class TestConnectionManager:
    """Testes do gerenciador de conexões"""

    def test_get_saved_connections_empty(self, connection_manager):
        connections = connection_manager.get_saved_connections()
        assert isinstance(connections, list)

    def test_save_connection_config(self, connection_manager):
        connection_manager.save_connection_config(
            name="Test Connection", db_type="mssql", host="localhost", port=1433, database="testdb"
        )

        refs = connection_manager.get_saved_connections()
        assert ConnectionRef(group="", name="Test Connection") in refs

    def test_get_connection_config(self, connection_manager):
        connection_manager.save_connection_config(
            name="Named Connection", db_type="mssql", host="server1", port=1433, database="db1"
        )

        config = connection_manager.get_connection_config("", "Named Connection")
        assert config is not None
        assert config["host"] == "server1"
        assert config["database"] == "db1"

    def test_delete_connection_config(self, connection_manager):
        connection_manager.save_connection_config(
            name="To Remove", db_type="mssql", host="localhost", port=1433, database="test"
        )

        connection_manager.delete_connection_config("", "To Remove")
        assert connection_manager.get_connection_config("", "To Remove") is None

    def test_update_connection_config(self, connection_manager):
        connection_manager.save_connection_config(
            name="Original", db_type="mssql", host="server1", port=1433, database="db1"
        )

        connection_manager.update_connection_config(
            "", "Original", "Original", "mssql", "server2", 1433, "db2"
        )

        config = connection_manager.get_connection_config("", "Original")
        assert config["host"] == "server2"
        assert config["database"] == "db2"

    def test_mark_connection_used(self, connection_manager):
        connection_manager.save_connection_config(
            name="Recent Connection", db_type="mssql", host="localhost", port=1433, database="test"
        )

        connection_manager.mark_connection_used("", "Recent Connection")
        config = connection_manager.get_connection_config("", "Recent Connection")
        assert config["last_used"] is not None

    def test_same_name_different_groups(self, connection_manager):
        connection_manager.save_connection_config(
            name="Server", db_type="mssql", host="prod", port=1433, database="db", group="Prod"
        )
        connection_manager.save_connection_config(
            name="Server", db_type="mssql", host="dev", port=1433, database="db", group="Dev"
        )

        assert connection_manager.get_connection_config("Prod", "Server")["host"] == "prod"
        assert connection_manager.get_connection_config("Dev", "Server")["host"] == "dev"

    def test_duplicate_in_same_group_raises(self, connection_manager):
        connection_manager.save_connection_config(
            name="Dup", db_type="mssql", host="localhost", port=1433, database="db", group="Prod"
        )
        with pytest.raises(ValueError):
            connection_manager.save_connection_config(
                name="Dup", db_type="mssql", host="other", port=1433, database="db", group="Prod"
            )
    def test_migrate_flat_format(self, connection_manager):
        flat = {
            "groups": {},
            "connections": {
                "Legacy": {
                    "db_type": "mssql",
                    "host": "localhost",
                    "port": 1433,
                    "database": "db",
                    "group": "OldGroup",
                }
            },
        }
        connection_manager.config_path.write_text(json.dumps(flat), encoding="utf-8")
        connection_manager.saved_configs = connection_manager._load_configs()

        assert connection_manager.get_connection_config("OldGroup", "Legacy") is not None


class TestConnectionManagerGroups:
    """Testes de grupos de conexões"""

    def test_create_group(self, connection_manager):
        connection_manager.create_group("Development")
        assert "Development" in connection_manager.get_groups()

    def test_add_connection_to_group(self, connection_manager):
        connection_manager.create_group("Production")
        connection_manager.save_connection_config(
            name="Prod Server",
            db_type="mssql",
            host="prod.example.com",
            port=1433,
            database="proddb",
            group="Production",
        )

        connections = connection_manager.get_connections_by_group("Production")
        assert "Prod Server" in connections

    def test_delete_group(self, connection_manager):
        connection_manager.create_group("ToDelete")
        connection_manager.delete_group("ToDelete")
        assert "ToDelete" not in connection_manager.get_groups()

    def test_rename_group(self, connection_manager):
        connection_manager.create_group("OldName")
        connection_manager.rename_group("OldName", "NewName")
        groups = connection_manager.get_groups()
        assert "OldName" not in groups
        assert "NewName" in groups

    def test_get_connections_ungrouped(self, connection_manager):
        connection_manager.save_connection_config(
            name="No Group", db_type="mssql", host="localhost", port=1433, database="test"
        )
        ungrouped = connection_manager.get_connections_by_group("")
        assert "No Group" in ungrouped


class TestConnectionManagerPersistence:
    def test_connections_persisted(self, connection_manager):
        connection_manager.save_connection_config(
            name="Persistent Connection", db_type="mssql", host="localhost", port=1433, database="test"
        )
        assert connection_manager.config_path.exists()

    def test_config_is_valid_json(self, connection_manager):
        connection_manager.save_connection_config(
            name="JSON Test", db_type="mssql", host="localhost", port=1433, database="test"
        )
        with open(connection_manager.config_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "connections" in data


class TestConnectionManagerEdgeCases:
    def test_delete_nonexistent_connection(self, connection_manager):
        connection_manager.delete_connection_config("", "NonExistent")

    def test_special_characters_in_name(self, connection_manager):
        connection_manager.save_connection_config(
            name="Prod [2024] - Primary", db_type="mssql", host="localhost", port=1433, database="test"
        )
        assert connection_manager.get_connection_config("", "Prod [2024] - Primary") is not None

    def test_unicode_in_connection(self, connection_manager):
        connection_manager.save_connection_config(
            name="Servidor 日本語", db_type="mssql", host="localhost", port=1433, database="test"
        )
        assert connection_manager.get_connection_config("", "Servidor 日本語") is not None

    def test_windows_auth_flag(self, connection_manager):
        connection_manager.save_connection_config(
            name="Windows Auth", db_type="mssql", host="localhost", port=1433, database="test", use_windows_auth=True
        )
        config = connection_manager.get_connection_config("", "Windows Auth")
        assert config["use_windows_auth"] is True

    def test_sqlserver_mfa_auth_mode_is_persisted(self, connection_manager):
        connection_manager.save_connection_config(
            name="Azure SQL MFA",
            db_type="sqlserver",
            host="server.database.windows.net",
            port=1433,
            database="test",
            username="user@tenant.com",
            sqlserver_auth_mode="entra_mfa",
        )
        config = connection_manager.get_connection_config("", "Azure SQL MFA")
        assert config["sqlserver_auth_mode"] == "entra_mfa"
        assert config["use_windows_auth"] is False

    def test_databricks_http_path(self, connection_manager):
        connection_manager.save_connection_config(
            name="Databricks Warehouse",
            db_type="databricks",
            host="adb.example.com",
            port=443,
            database="default",
            http_path="/sql/1.0/endpoints/abc",
        )
        config = connection_manager.get_connection_config("", "Databricks Warehouse")
        assert config["http_path"] == "/sql/1.0/endpoints/abc"
