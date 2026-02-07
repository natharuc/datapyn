"""
Testes do WorkspaceManager
"""

import pytest
import json
from pathlib import Path


class TestWorkspaceManager:
    """Testes do gerenciador de workspace"""

    def test_load_empty_workspace_returns_default(self, workspace_manager):
        """Workspace vazio deve retornar default com uma aba"""
        workspace = workspace_manager.load_workspace()

        assert "tabs" in workspace
        assert len(workspace["tabs"]) >= 1
        assert "active_tab" in workspace
        assert workspace["active_tab"] == 0

    def test_save_workspace(self, workspace_manager):
        """Deve salvar workspace corretamente"""
        tabs = [
            {"code": "SELECT * FROM users", "connection": None, "title": "Script 1"},
            {"code": 'print("hello")', "connection": None, "title": "Script 2"},
        ]

        workspace_manager.save_workspace(tabs, 1, "my_connection")

        # Verificar arquivo
        assert workspace_manager.config_path.exists()

    def test_load_saved_workspace(self, workspace_manager):
        """Deve carregar workspace salvo"""
        tabs = [
            {"code": "SELECT 1", "connection": None, "title": "Test"},
        ]
        workspace_manager.save_workspace(tabs, 0, "conn1")

        loaded = workspace_manager.load_workspace()

        assert len(loaded["tabs"]) == 1
        assert loaded["tabs"][0]["code"] == "SELECT 1"
        assert loaded["tabs"][0]["title"] == "Test"
        assert loaded["active_tab"] == 0
        assert loaded["active_connection"] == "conn1"

    def test_preserve_code_content(self, workspace_manager):
        """Deve preservar conteúdo do código com caracteres especiais"""
        code = '''SELECT * FROM users
WHERE name = 'O''Brien'
AND status = "active"'''

        tabs = [{"code": code, "connection": None, "title": "Script"}]
        workspace_manager.save_workspace(tabs, 0, None)

        loaded = workspace_manager.load_workspace()

        assert loaded["tabs"][0]["code"] == code

    def test_multiple_tabs(self, workspace_manager):
        """Deve suportar múltiplas abas"""
        tabs = [{"code": f"code_{i}", "connection": None, "title": f"Tab {i}"} for i in range(10)]

        workspace_manager.save_workspace(tabs, 5, None)
        loaded = workspace_manager.load_workspace()

        assert len(loaded["tabs"]) == 10
        assert loaded["active_tab"] == 5

    def test_clear_workspace(self, workspace_manager):
        """Deve limpar workspace"""
        tabs = [{"code": "test", "connection": None, "title": "Test"}]
        workspace_manager.save_workspace(tabs, 0, None)

        workspace_manager.clear_workspace()

        assert not workspace_manager.config_path.exists()

    def test_clear_nonexistent_workspace(self, workspace_manager):
        """Limpar workspace inexistente não deve dar erro"""
        workspace_manager.clear_workspace()  # Não deve lançar exceção


class TestWorkspaceManagerEdgeCases:
    """Testes de casos de borda"""

    def test_corrupted_file_returns_default(self, workspace_manager):
        """Arquivo corrompido deve retornar default"""
        workspace_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(workspace_manager.config_path, "w") as f:
            f.write("not valid json")

        workspace = workspace_manager.load_workspace()

        assert len(workspace["tabs"]) >= 1

    def test_missing_tabs_key_returns_default(self, workspace_manager):
        """Workspace sem 'tabs' deve ter default"""
        workspace_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(workspace_manager.config_path, "w") as f:
            json.dump({"active_tab": 0}, f)

        workspace = workspace_manager.load_workspace()

        assert len(workspace["tabs"]) >= 1

    def test_empty_tabs_array_returns_default(self, workspace_manager):
        """Workspace com tabs vazio deve ter default"""
        workspace_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(workspace_manager.config_path, "w") as f:
            json.dump({"tabs": [], "active_tab": 0}, f)

        workspace = workspace_manager.load_workspace()

        assert len(workspace["tabs"]) >= 1

    def test_unicode_content(self, workspace_manager):
        """Deve suportar conteúdo unicode"""
        code = 'SELECT * FROM 用户 WHERE 名前 = "日本語"'

        tabs = [{"code": code, "connection": None, "title": "脚本"}]
        workspace_manager.save_workspace(tabs, 0, None)

        loaded = workspace_manager.load_workspace()

        assert loaded["tabs"][0]["code"] == code
        assert loaded["tabs"][0]["title"] == "脚本"
