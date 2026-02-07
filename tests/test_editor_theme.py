"""
Testes para o sistema de tema específico dos editores
"""
import pytest
from src.core.theme_manager import ThemeManager


class TestEditorTheme:
    """Testes para tema específico dos editores"""
    
    def test_theme_manager_default_setup(self):
        """Deve criar ThemeManager com tema geral dark"""
        tm = ThemeManager()
        assert tm.get_theme_name() == 'dark'
        assert tm.get_editor_theme_name() == 'dark'  # Sem tema específico, usa o geral
    
    def test_set_editor_theme_specific(self):
        """Deve permitir definir tema específico para editores"""
        tm = ThemeManager()
        
        # Definir tema específico para editores
        result = tm.set_editor_theme('monokai')
        assert result is True
        
        # Tema geral continua dark, tema dos editores é monokai
        assert tm.get_theme_name() == 'dark'
        assert tm.get_editor_theme_name() == 'monokai'
    
    def test_editor_colors_use_specific_theme(self):
        """Cores dos editores devem usar tema específico quando definido"""
        tm = ThemeManager()
        
        # Cores iniciais (tema dark)
        dark_colors = tm.get_editor_colors()
        dark_bg = dark_colors['background']
        
        # Definir tema monokai para editores  
        tm.set_editor_theme('monokai')
        
        # Cores agora devem ser do tema monokai
        monokai_colors = tm.get_editor_colors()
        monokai_bg = monokai_colors['background']
        
        # Backgrounds devem ser diferentes
        assert dark_bg != monokai_bg
        
        # Verificar se é realmente do monokai
        # Monokai tem background #272822
        assert monokai_bg.name() == '#272822'
    
    def test_app_colors_keep_general_theme(self):
        """Cores da aplicação devem usar o tema geral sempre"""
        tm = ThemeManager()
        
        # Cores iniciais da app (tema dark)
        initial_app_colors = tm.get_app_colors()
        
        # Definir tema monokai apenas para editores
        tm.set_editor_theme('monokai')
        
        # Cores da app devem permanecer as mesmas (tema dark)
        final_app_colors = tm.get_app_colors()
        assert initial_app_colors == final_app_colors
    
    def test_invalid_editor_theme(self):
        """Deve rejeitar tema inexistente para editores"""
        tm = ThemeManager()
        result = tm.set_editor_theme('tema_inexistente')
        assert result is False
        assert tm.get_editor_theme_name() == 'dark'  # Continua com o padrão