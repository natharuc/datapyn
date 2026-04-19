"""
Tests for connection import/export dialog and logic.
"""

import json
import pytest


class TestExportConnections:
    """Tests for exporting connections to JSON without passwords."""

    def test_export_empty(self, connection_manager):
        """Export with no connections returns empty dict."""
        from ui.dialogs.connection_import_export_dialog import export_connections

        result = export_connections(connection_manager)
        assert result == {"connections": {}}

    def test_export_strips_password(self, connection_manager):
        """Exported connections must NOT contain password field."""
        from ui.dialogs.connection_import_export_dialog import export_connections

        connection_manager.save_connection_config(
            name="Prod",
            db_type="sqlserver",
            host="prod-server",
            port=1433,
            database="app_db",
            username="admin",
            save_password=True,
            password="super-secret-123",
            color="#ff0000",
        )

        result = export_connections(connection_manager)
        conn = result["connections"]["Prod"]

        assert "password" not in conn
        assert conn["db_type"] == "sqlserver"
        assert conn["host"] == "prod-server"
        assert conn["color"] == "#ff0000"
        assert conn["username"] == "admin"

    def test_export_preserves_metadata(self, connection_manager):
        """Export keeps name, color, type, group, host, port, database."""
        from ui.dialogs.connection_import_export_dialog import export_connections

        connection_manager.create_group("Backend", color="#00ff00")
        connection_manager.save_connection_config(
            name="DevDB",
            db_type="postgresql",
            host="localhost",
            port=5432,
            database="dev",
            username="dev_user",
            group="Backend",
            color="#abcdef",
            trust_server_certificate=True,
        )

        result = export_connections(connection_manager)

        assert "groups" in result
        assert "Backend" in result["groups"]
        assert result["groups"]["Backend"]["color"] == "#00ff00"

        conn = result["connections"]["DevDB"]
        assert conn["db_type"] == "postgresql"
        assert conn["host"] == "localhost"
        assert conn["port"] == 5432
        assert conn["database"] == "dev"
        assert conn["username"] == "dev_user"
        assert conn["group"] == "Backend"
        assert conn["color"] == "#abcdef"
        assert conn["trust_server_certificate"] is True

    def test_export_multiple_connections(self, connection_manager):
        """Export all connections."""
        from ui.dialogs.connection_import_export_dialog import export_connections

        for i in range(3):
            connection_manager.save_connection_config(
                name=f"conn_{i}",
                db_type="mysql",
                host=f"host{i}",
                port=3306,
                database=f"db{i}",
            )

        result = export_connections(connection_manager)
        assert len(result["connections"]) == 3
        assert all(f"conn_{i}" in result["connections"] for i in range(3))


class TestValidateImportJson:
    """Tests for JSON validation before import."""

    def test_valid_json(self):
        """Valid JSON with required fields passes validation."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        text = json.dumps({
            "connections": {
                "MyConn": {
                    "db_type": "sqlserver",
                    "host": "localhost",
                    "port": 1433,
                    "database": "testdb",
                }
            }
        })
        data, error = validate_import_json(text)
        assert error is None
        assert data is not None
        assert "MyConn" in data["connections"]

    def test_invalid_json_syntax(self):
        """Malformed JSON is rejected."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        data, error = validate_import_json("{not valid json}")
        assert data is None
        assert error is not None

    def test_missing_connections_key(self):
        """JSON without 'connections' key is rejected."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        data, error = validate_import_json(json.dumps({"groups": {}}))
        assert data is None
        assert error is not None

    def test_connections_not_object(self):
        """'connections' as list instead of object is rejected."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        data, error = validate_import_json(json.dumps({"connections": []}))
        assert data is None
        assert error is not None

    def test_missing_required_field(self):
        """Connection missing db_type is rejected."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        text = json.dumps({
            "connections": {
                "Bad": {"host": "localhost", "port": 1433, "database": "db"}
            }
        })
        data, error = validate_import_json(text)
        assert data is None
        assert "db_type" in error

    def test_valid_with_groups(self):
        """JSON with connections and groups passes."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        text = json.dumps({
            "connections": {
                "A": {"db_type": "mysql", "host": "h", "port": 3306, "database": "d"}
            },
            "groups": {
                "Prod": {"color": "#ff0000"}
            },
        })
        data, error = validate_import_json(text)
        assert error is None
        assert "Prod" in data["groups"]

    def test_groups_not_object(self):
        """'groups' as string is rejected."""
        from ui.dialogs.connection_import_export_dialog import validate_import_json

        text = json.dumps({
            "connections": {
                "A": {"db_type": "mysql", "host": "h", "port": 3306, "database": "d"}
            },
            "groups": "not-a-dict",
        })
        data, error = validate_import_json(text)
        assert data is None
        assert error is not None


class TestApplyImport:
    """Tests for applying imported data to ConnectionManager."""

    def test_import_creates_connections(self, connection_manager):
        """Import should create connections in the manager."""
        from ui.dialogs.connection_import_export_dialog import apply_import

        data = {
            "connections": {
                "ImportedConn": {
                    "db_type": "postgresql",
                    "host": "pg-server",
                    "port": 5432,
                    "database": "imported_db",
                    "username": "pguser",
                    "color": "#123456",
                }
            }
        }
        count = apply_import(connection_manager, data)
        assert count == 1

        config = connection_manager.get_connection_config("ImportedConn")
        assert config is not None
        assert config["db_type"] == "postgresql"
        assert config["host"] == "pg-server"
        assert config["color"] == "#123456"
        # No password should be stored
        assert "password" not in config

    def test_import_creates_groups(self, connection_manager):
        """Import should create groups."""
        from ui.dialogs.connection_import_export_dialog import apply_import

        data = {
            "connections": {
                "C1": {
                    "db_type": "mysql",
                    "host": "h",
                    "port": 3306,
                    "database": "d",
                    "group": "Staging",
                }
            },
            "groups": {
                "Staging": {"color": "#aabbcc", "parent": ""}
            },
        }
        apply_import(connection_manager, data)

        groups = connection_manager.get_groups()
        assert "Staging" in groups
        assert groups["Staging"]["color"] == "#aabbcc"

    def test_import_overwrites_existing(self, connection_manager):
        """Import replaces connections with the same name."""
        from ui.dialogs.connection_import_export_dialog import apply_import

        connection_manager.save_connection_config(
            name="Shared",
            db_type="sqlserver",
            host="old-host",
            port=1433,
            database="old_db",
        )

        data = {
            "connections": {
                "Shared": {
                    "db_type": "postgresql",
                    "host": "new-host",
                    "port": 5432,
                    "database": "new_db",
                }
            }
        }
        apply_import(connection_manager, data)

        config = connection_manager.get_connection_config("Shared")
        assert config["db_type"] == "postgresql"
        assert config["host"] == "new-host"

    def test_roundtrip_export_import(self, connection_manager):
        """Export then import should reproduce the same connections."""
        from ui.dialogs.connection_import_export_dialog import (
            export_connections,
            apply_import,
            validate_import_json,
        )

        connection_manager.create_group("Team", color="#111111")
        for name, db in [("A", "db_a"), ("B", "db_b")]:
            connection_manager.save_connection_config(
                name=name,
                db_type="mysql",
                host="server",
                port=3306,
                database=db,
                group="Team",
                color="#222222",
            )

        exported = export_connections(connection_manager)
        text = json.dumps(exported)

        data, error = validate_import_json(text)
        assert error is None

        # Import into a fresh manager
        from database.connection_manager import ConnectionManager
        import tempfile, os

        with tempfile.TemporaryDirectory() as td:
            fresh = ConnectionManager(os.path.join(td, "conn.json"))
            count = apply_import(fresh, data)
            assert count == 2
            assert fresh.get_connection_config("A")["database"] == "db_a"
            assert fresh.get_connection_config("B")["database"] == "db_b"
            assert "Team" in fresh.get_groups()
