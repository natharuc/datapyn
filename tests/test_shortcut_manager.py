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
        
        assert 'execute_sql' in shortcuts
        assert 'execute_python' in shortcuts
        assert 'execute_cross_syntax' in shortcuts
        assert 'save_file' in shortcuts
        assert 'open_file' in shortcuts
    
    def test_default_shortcut_values(self, shortcut_manager):
        """Atalhos padrão devem ter valores corretos"""
        assert shortcut_manager.get_shortcut('execute_sql') == 'F5'
        assert shortcut_manager.get_shortcut('execute_python') == 'Shift+Return'
        assert shortcut_manager.get_shortcut('execute_cross_syntax') == 'Ctrl+Shift+F5'
    
    def test_set_shortcut(self, shortcut_manager):
        """Deve permitir alterar atalho"""
        shortcut_manager.set_shortcut('execute_sql', 'F6')
        
        assert shortcut_manager.get_shortcut('execute_sql') == 'F6'
    
    def test_save_and_load_shortcuts(self, shortcut_manager, temp_dir):
        """Deve persistir atalhos em arquivo"""
        # Alterar atalho
        shortcut_manager.set_shortcut('execute_sql', 'F7')
        
        # Criar novo manager (simulando reinício)
        from core.shortcut_manager import ShortcutManager
        new_manager = ShortcutManager(str(shortcut_manager.config_path))
        
        # Verificar que carregou
        assert new_manager.get_shortcut('execute_sql') == 'F7'
    
    def test_reset_to_defaults(self, shortcut_manager):
        """Deve restaurar atalhos padrão"""
        # Alterar atalho
        shortcut_manager.set_shortcut('execute_sql', 'F99')
        
        # Resetar
        shortcut_manager.reset_to_defaults()
        
        # Verificar que voltou ao padrão
        assert shortcut_manager.get_shortcut('execute_sql') == 'F5'
    
    def test_get_nonexistent_shortcut_returns_empty(self, shortcut_manager):
        """Atalho inexistente deve retornar string vazia"""
        result = shortcut_manager.get_shortcut('nonexistent_action')
        
        assert result == ''
    
    def test_config_file_created(self, shortcut_manager, temp_dir):
        """Arquivo de config deve ser criado ao salvar"""
        shortcut_manager.set_shortcut('test', 'F1')
        
        assert shortcut_manager.config_path.exists()
    
    def test_config_file_is_valid_json(self, shortcut_manager, temp_dir):
        """Arquivo de config deve ser JSON válido"""
        shortcut_manager.set_shortcut('test', 'F1')
        
        with open(shortcut_manager.config_path, 'r') as f:
            data = json.load(f)
        
        assert 'shortcuts' in data


class TestShortcutManagerEdgeCases:
    """Testes de casos de borda do ShortcutManager"""
    
    def test_empty_shortcut_value(self, shortcut_manager):
        """Deve aceitar atalho vazio (desabilitado)"""
        shortcut_manager.set_shortcut('execute_sql', '')
        
        assert shortcut_manager.get_shortcut('execute_sql') == ''
    
    def test_special_characters_in_shortcut(self, shortcut_manager):
        """Deve aceitar atalhos com caracteres especiais"""
        shortcut_manager.set_shortcut('test', 'Ctrl+Shift+Alt+F12')
        
        assert shortcut_manager.get_shortcut('test') == 'Ctrl+Shift+Alt+F12'
    
    def test_corrupted_config_file(self, shortcut_manager, temp_dir):
        """Deve usar defaults se arquivo corrompido"""
        # Criar arquivo corrompido
        shortcut_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(shortcut_manager.config_path, 'w') as f:
            f.write('invalid json {{{')
        
        # Criar novo manager
        from core.shortcut_manager import ShortcutManager
        new_manager = ShortcutManager(str(shortcut_manager.config_path))
        
        # Deve ter defaults
        assert new_manager.get_shortcut('execute_sql') == 'F5'