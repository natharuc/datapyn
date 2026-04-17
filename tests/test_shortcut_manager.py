"""
Testes do ShortcutManager
"""

import pytest
import json
from pathlib import Path


class TestShortcutManager:
    """Testes do gerenciador de atalhos"""

    def test_default_shortcuts_exist(self, shortcut_manager):
        """Deve ter atalhos padrão definidos"""
        shortcuts = shortcut_manager.get_all_shortcuts()

        assert "execute_sql" in shortcuts
        assert "execute_all" in shortcuts
        assert "save_file" in shortcuts
        assert "open_file" in shortcuts
        assert "new_tab" in shortcuts

    def test_default_shortcut_values(self, shortcut_manager):
        """Atalhos padrão devem ter valores corretos"""
        assert shortcut_manager.get_shortcut("execute_sql") == "F5"
        assert shortcut_manager.get_shortcut("execute_all") == "Ctrl+F5"
        assert shortcut_manager.get_shortcut("new_tab") == "Ctrl+T"

    def test_set_shortcut(self, shortcut_manager):
        """Deve permitir alterar atalho"""
        shortcut_manager.set_shortcut("execute_sql", "F6")

        assert shortcut_manager.get_shortcut("execute_sql") == "F6"

    def test_save_and_load_shortcuts(self, shortcut_manager, temp_dir):
        """Deve persistir atalhos em arquivo"""
        # Alterar atalho
        shortcut_manager.set_shortcut("execute_sql", "F7")

        # Criar novo manager (simulando reinício)
        from core.shortcut_manager import ShortcutManager

        new_manager = ShortcutManager(str(shortcut_manager.config_path))

        # Verificar que carregou
        assert new_manager.get_shortcut("execute_sql") == "F7"

    def test_reset_to_defaults(self, shortcut_manager):
        """Deve restaurar atalhos padrão"""
        # Alterar atalho
        shortcut_manager.set_shortcut("execute_sql", "F99")

        # Resetar
        shortcut_manager.reset_to_defaults()

        # Verificar que voltou ao padrão
        assert shortcut_manager.get_shortcut("execute_sql") == "F5"

    def test_get_nonexistent_shortcut_returns_empty(self, shortcut_manager):
        """Atalho inexistente deve retornar string vazia"""
        result = shortcut_manager.get_shortcut("nonexistent_action")

        assert result == ""

    def test_config_file_created(self, shortcut_manager, temp_dir):
        """Arquivo de config deve ser criado ao salvar"""
        shortcut_manager.set_shortcut("test", "F1")

        assert shortcut_manager.config_path.exists()

    def test_config_file_is_valid_json(self, shortcut_manager, temp_dir):
        """Arquivo de config deve ser JSON válido"""
        shortcut_manager.set_shortcut("test", "F1")

        with open(shortcut_manager.config_path, "r") as f:
            data = json.load(f)

        assert "shortcuts" in data


class TestShortcutManagerEdgeCases:
    """Testes de casos de borda do ShortcutManager"""

    def test_empty_shortcut_value(self, shortcut_manager):
        """Deve aceitar atalho vazio (desabilitado)"""
        shortcut_manager.set_shortcut("execute_sql", "")

        assert shortcut_manager.get_shortcut("execute_sql") == ""

    def test_special_characters_in_shortcut(self, shortcut_manager):
        """Deve aceitar atalhos com caracteres especiais"""
        shortcut_manager.set_shortcut("test", "Ctrl+Shift+Alt+F12")

        assert shortcut_manager.get_shortcut("test") == "Ctrl+Shift+Alt+F12"

    def test_corrupted_config_file(self, shortcut_manager, temp_dir):
        """Deve usar defaults se arquivo corrompido"""
        # Criar arquivo corrompido
        shortcut_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(shortcut_manager.config_path, "w") as f:
            f.write("invalid json {{{")

        # Criar novo manager
        from core.shortcut_manager import ShortcutManager

        new_manager = ShortcutManager(str(shortcut_manager.config_path))

        # Deve ter defaults
        assert new_manager.get_shortcut("execute_sql") == "F5"

    def test_new_defaults_merged_with_existing_config(self, shortcut_manager, temp_dir):
        """Novos atalhos padrao devem ser adicionados a configs existentes"""
        from core.shortcut_manager import ShortcutManager

        # Simular config antiga que nao tem execute_block_advance
        old_config = {
            "shortcuts": {
                "execute_sql": "F5",
                "execute_all": "Ctrl+F5",
                "save_file": "Ctrl+S",
            }
        }
        shortcut_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(shortcut_manager.config_path, "w") as f:
            json.dump(old_config, f)

        # Criar novo manager (carrega config antiga + merge com defaults)
        new_manager = ShortcutManager(str(shortcut_manager.config_path))

        # Atalhos salvos devem ser preservados
        assert new_manager.get_shortcut("execute_sql") == "F5"
        assert new_manager.get_shortcut("save_file") == "Ctrl+S"

        # Novos atalhos padrao devem estar disponiveis
        assert new_manager.get_shortcut("execute_block_advance") == "Shift+Return"

    def test_user_customized_shortcuts_preserved_on_merge(self, shortcut_manager, temp_dir):
        """Atalhos customizados pelo usuario nao devem ser sobrescritos"""
        from core.shortcut_manager import ShortcutManager

        # Simular config onde usuario mudou execute_sql de F5 para F6
        old_config = {
            "shortcuts": {
                "execute_sql": "F6",
                "execute_all": "Ctrl+Shift+F5",
            }
        }
        shortcut_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(shortcut_manager.config_path, "w") as f:
            json.dump(old_config, f)

        new_manager = ShortcutManager(str(shortcut_manager.config_path))

        # Customizacao do usuario deve prevalecer sobre defaults
        assert new_manager.get_shortcut("execute_sql") == "F6"
        assert new_manager.get_shortcut("execute_all") == "Ctrl+Shift+F5"


class TestNoDuplicateDefaults:
    """Ensures no duplicate key sequences exist in DEFAULT_SHORTCUTS."""

    def test_no_duplicate_shortcuts_in_defaults(self, shortcut_manager):
        """No two actions should share the same default shortcut."""
        from PyQt6.QtGui import QKeySequence

        shortcuts = shortcut_manager.get_all_shortcuts()
        seen = {}
        for action, key_str in shortcuts.items():
            if not key_str:
                continue
            normalized = QKeySequence(key_str).toString()
            if normalized in seen:
                pytest.fail(
                    f"Duplicate shortcut '{normalized}': "
                    f"used by '{seen[normalized]}' and '{action}'"
                )
            seen[normalized] = action

    def test_clear_results_not_ctrl_shift_c(self, shortcut_manager):
        """clear_results must not conflict with copy_with_headers."""
        clear_key = shortcut_manager.get_shortcut("clear_results")
        copy_hdr_key = shortcut_manager.get_shortcut("copy_with_headers")
        assert clear_key != copy_hdr_key, (
            f"clear_results ({clear_key}) must differ from "
            f"copy_with_headers ({copy_hdr_key})"
        )

    def test_new_actions_registered(self, shortcut_manager):
        """New configurable actions should exist in defaults."""
        shortcuts = shortcut_manager.get_all_shortcuts()
        assert "copy_with_headers" in shortcuts
        assert "exit_app" in shortcuts
        assert "restore_view" in shortcuts
        assert "reset_layout" in shortcuts

    def test_copy_with_headers_default(self, shortcut_manager):
        """copy_with_headers should default to Ctrl+Shift+C."""
        assert shortcut_manager.get_shortcut("copy_with_headers") == "Ctrl+Shift+C"

    def test_detect_duplicates_returns_empty(self, shortcut_manager):
        """detect_duplicates() should return empty dict for defaults."""
        dupes = shortcut_manager.detect_duplicates()
        assert dupes == {}, f"Found duplicates in defaults: {dupes}"
