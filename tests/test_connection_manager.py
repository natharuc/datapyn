"""
Testes do ConnectionManager
"""

import pytest
import json


class TestConnectionManager:
    """Testes do gerenciador de conexões"""

    def test_get_saved_connections_empty(self, connection_manager):
        """Lista de conexões começa vazia"""
        connections = connection_manager.get_saved_connections()

        assert isinstance(connections, list)

    def test_save_connection_config(self, connection_manager):
        """Deve salvar configuração de conexão"""
        connection_manager.save_connection_config(
            name="Test Connection", db_type="mssql", host="localhost", port=1433, database="testdb"
        )

        connections = connection_manager.get_saved_connections()
        assert "Test Connection" in connections

    def test_get_connection_config(self, connection_manager):
        """Deve buscar configuração de conexão"""
        connection_manager.save_connection_config(
            name="Named Connection", db_type="mssql", host="server1", port=1433, database="db1"
        )

        config = connection_manager.get_connection_config("Named Connection")

        assert config is not None
        assert config["host"] == "server1"
        assert config["database"] == "db1"

    def test_delete_connection_config(self, connection_manager):
        """Deve remover configuração de conexão"""
        connection_manager.save_connection_config(
            name="To Remove", db_type="mssql", host="localhost", port=1433, database="test"
        )

        connection_manager.delete_connection_config("To Remove")

        config = connection_manager.get_connection_config("To Remove")
        assert config is None

    def test_update_connection_config(self, connection_manager):
        """Deve atualizar configuração existente"""
        connection_manager.save_connection_config(
            name="Original", db_type="mssql", host="server1", port=1433, database="db1"
        )

        connection_manager.update_connection_config(
            old_name="Original", new_name="Original", db_type="mssql", host="server2", port=1433, database="db2"
        )

        config = connection_manager.get_connection_config("Original")
        assert config["host"] == "server2"
        assert config["database"] == "db2"

    def test_mark_connection_used(self, connection_manager):
        """Deve marcar conexão como usada recentemente"""
        connection_manager.save_connection_config(
            name="Recent Connection", db_type="mssql", host="localhost", port=1433, database="test"
        )

        connection_manager.mark_connection_used("Recent Connection")

        config = connection_manager.get_connection_config("Recent Connection")
        assert config["last_used"] is not None


class TestConnectionManagerGroups:
    """Testes de grupos de conexões"""

    def test_create_group(self, connection_manager):
        """Deve criar grupo"""
        connection_manager.create_group("Development")

        groups = connection_manager.get_groups()
        assert "Development" in groups

    def test_add_connection_to_group(self, connection_manager):
        """Deve adicionar conexão a um grupo"""
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
        """Deve remover grupo"""
        connection_manager.create_group("ToDelete")
        connection_manager.delete_group("ToDelete")

        groups = connection_manager.get_groups()
        assert "ToDelete" not in groups

    def test_rename_group(self, connection_manager):
        """Deve renomear grupo"""
        connection_manager.create_group("OldName")
        connection_manager.rename_group("OldName", "NewName")

        groups = connection_manager.get_groups()
        assert "OldName" not in groups
        assert "NewName" in groups

    def test_get_connections_ungrouped(self, connection_manager):
        """Deve retornar conexões sem grupo"""
        connection_manager.save_connection_config(
            name="No Group", db_type="mssql", host="localhost", port=1433, database="test"
        )

        ungrouped = connection_manager.get_connections_by_group("")

        assert "No Group" in ungrouped


class TestConnectionManagerPersistence:
    """Testes de persistência de conexões"""

    def test_connections_persisted(self, connection_manager):
        """Conexões devem ser salvas em arquivo"""
        connection_manager.save_connection_config(
            name="Persistent Connection", db_type="mssql", host="localhost", port=1433, database="test"
        )

        assert connection_manager.config_path.exists()

    def test_config_is_valid_json(self, connection_manager):
        """Arquivo de config deve ser JSON válido"""
        connection_manager.save_connection_config(
            name="JSON Test", db_type="mssql", host="localhost", port=1433, database="test"
        )

        with open(connection_manager.config_path) as f:
            data = json.load(f)

        assert isinstance(data, dict)
        assert "connections" in data


class TestConnectionManagerEdgeCases:
    """Testes de casos de borda"""

    def test_delete_nonexistent_connection(self, connection_manager):
        """Remover conexão inexistente não deve dar erro"""
        # Não deve lançar exceção
        connection_manager.delete_connection_config("NonExistent")

    def test_special_characters_in_name(self, connection_manager):
        """Nomes com caracteres especiais"""
        connection_manager.save_connection_config(
            name="Prod [2024] - Primary", db_type="mssql", host="localhost", port=1433, database="test"
        )

        config = connection_manager.get_connection_config("Prod [2024] - Primary")
        assert config is not None

    def test_unicode_in_connection(self, connection_manager):
        """Conexão com unicode"""
        connection_manager.save_connection_config(
            name="Servidor 日本語", db_type="mssql", host="localhost", port=1433, database="test"
        )

        config = connection_manager.get_connection_config("Servidor 日本語")
        assert config is not None

    def test_windows_auth_flag(self, connection_manager):
        """Deve salvar flag de autenticação Windows"""
        connection_manager.save_connection_config(
            name="Windows Auth", db_type="mssql", host="localhost", port=1433, database="test", use_windows_auth=True
        )

        config = connection_manager.get_connection_config("Windows Auth")
        assert config["use_windows_auth"] is True
