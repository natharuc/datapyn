"""
Testes de integração do fluxo completo
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd


class TestCrossSyntaxFlow:
    """Testes de integração do fluxo cross-syntax"""

    def test_complete_cross_syntax_execution(self, mixed_executor, mock_db_connector, sample_dataframe):
        """Fluxo completo: código com {{ SQL }} deve criar variáveis"""
        # Setup
        mock_db_connector.is_connected.return_value = True
        mock_db_connector.execute_query.return_value = sample_dataframe

        # Código com sintaxe cross
        code = """
clientes = {{SELECT * FROM cliente}}
total = len(clientes)
print(f"Total: {total}")
"""
        namespace = {}

        # Execute
        result = mixed_executor.parse_and_execute(code, namespace)

        # Verify
        assert "clientes" in namespace
        assert isinstance(namespace["clientes"], pd.DataFrame)
        assert namespace["total"] == 3
        assert "Total: 3" in result["output"]

    def test_multiple_queries_in_one_execution(self, mixed_executor, mock_db_connector, sample_dataframe):
        """Múltiplas queries em uma execução"""
        mock_db_connector.is_connected.return_value = True
        mock_db_connector.execute_query.return_value = sample_dataframe

        code = """
df1 = {{SELECT * FROM tabela1}}
df2 = {{SELECT * FROM tabela2}}
df3 = {{SELECT * FROM tabela3}}
"""
        namespace = {}

        result = mixed_executor.parse_and_execute(code, namespace)

        assert "df1" in namespace
        assert "df2" in namespace
        assert "df3" in namespace
        assert result["queries_executed"] == 3


class TestWorkspaceFlow:
    """Testes de integração do fluxo de workspace"""

    def test_save_and_restore_workspace(self, workspace_manager):
        """Salvar e restaurar workspace completo"""
        # Setup inicial
        tabs = [
            {"code": "SELECT * FROM users", "connection": "conn1", "title": "Query 1"},
            {"code": 'print("hello")', "connection": None, "title": "Python"},
            {"code": "df = {{SELECT 1}}", "connection": "conn2", "title": "Mixed"},
        ]

        # Save
        workspace_manager.save_workspace(tabs, active_tab=1, active_connection="conn1")

        # Restore
        loaded = workspace_manager.load_workspace()

        # Verify
        assert len(loaded["tabs"]) == 3
        assert loaded["active_tab"] == 1
        assert loaded["active_connection"] == "conn1"

        # Verify content preserved
        assert loaded["tabs"][0]["code"] == "SELECT * FROM users"
        assert loaded["tabs"][1]["code"] == 'print("hello")'
        assert loaded["tabs"][2]["code"] == "df = {{SELECT 1}}"


class TestConnectionFlow:
    """Testes de integração do fluxo de conexões"""

    def test_connection_lifecycle(self, connection_manager):
        """Ciclo de vida completo de conexão"""
        # Create
        connection_manager.save_connection_config(
            name="Test DB",
            db_type="mssql",
            host="localhost",
            port=1433,
            database="testdb",
            username="user",
            group="Development",
        )

        # Verify created
        config = connection_manager.get_connection_config("Test DB")
        assert config is not None
        assert config["host"] == "localhost"

        # Mark as used
        connection_manager.mark_connection_used("Test DB")

        # Verify timestamp
        config = connection_manager.get_connection_config("Test DB")
        assert config["last_used"] is not None

        # Update
        connection_manager.update_connection_config(
            old_name="Test DB",
            new_name="Test DB Renamed",
            db_type="mssql",
            host="newhost",
            port=1433,
            database="testdb",
            username="user",
        )

        # Verify updated
        assert connection_manager.get_connection_config("Test DB") is None
        new_config = connection_manager.get_connection_config("Test DB Renamed")
        assert new_config["host"] == "newhost"

        # Delete
        connection_manager.delete_connection_config("Test DB Renamed")
        assert connection_manager.get_connection_config("Test DB Renamed") is None


class TestShortcutFlow:
    """Testes de integração do fluxo de atalhos"""

    def test_shortcut_customization_flow(self, shortcut_manager, temp_dir):
        """Fluxo de customização de atalhos"""
        from core.shortcut_manager import ShortcutManager

        # Get defaults
        default_sql = shortcut_manager.get_shortcut("execute_sql")
        assert default_sql == "F5"

        # Customize
        shortcut_manager.set_shortcut("execute_sql", "F9")
        shortcut_manager.set_shortcut("execute_python", "Ctrl+Enter")

        # Create new manager (simulates app restart)
        new_manager = ShortcutManager(str(shortcut_manager.config_path))

        # Verify persistence
        assert new_manager.get_shortcut("execute_sql") == "F9"
        assert new_manager.get_shortcut("execute_python") == "Ctrl+Enter"

        # Reset
        new_manager.reset_to_defaults()

        # Verify reset
        assert new_manager.get_shortcut("execute_sql") == "F5"


class TestResultsFlow:
    """Testes de integração do fluxo de resultados"""

    def test_results_namespace_integration(self, results_manager, sample_dataframe):
        """Integração de resultados com namespace"""
        # Add results
        name1 = results_manager.add_result(sample_dataframe, "SELECT 1")
        name2 = results_manager.add_result(sample_dataframe, "SELECT 2")

        # Get namespace
        ns = results_manager.get_namespace()

        # Should have results + pandas + numpy
        assert "df1" in ns
        assert "df2" in ns
        assert "pd" in ns
        assert "np" in ns

        # df should point to last result
        assert ns["df"] is results_manager.last_result

        # Clear and verify
        results_manager.clear_all()
        ns = results_manager.get_namespace()

        assert "df1" not in ns
        assert "df2" not in ns
