"""
Testes para o ThemeManager
"""
import pytest
from src.core.theme_manager import ThemeManager, THEMES


class TestThemeManagerThemes:
    """Testes para verificar estrutura dos temas"""
    
    def test_all_themes_have_required_keys(self):
        """Verifica que todos os temas têm as chaves obrigatórias"""
        required_root_keys = ['name', 'editor', 'sql', 'python', 'app']
        
        for theme_name, theme in THEMES.items():
            for key in required_root_keys:
                assert key in theme, f"Tema '{theme_name}' não tem a chave '{key}'"
    
    def test_all_themes_editor_has_required_keys(self):
        """Verifica que todos os temas têm as chaves de editor obrigatórias"""
        required_editor_keys = ['background', 'foreground', 'caret', 'caret_line', 
                                 'selection', 'margin_bg', 'margin_fg', 'brace_match']
        
        for theme_name, theme in THEMES.items():
            editor = theme.get('editor', {})
            for key in required_editor_keys:
                assert key in editor, f"Tema '{theme_name}' editor não tem a chave '{key}'"
    
    def test_all_themes_app_has_required_keys(self):
        """Verifica que todos os temas têm as chaves de app obrigatórias"""
        required_app_keys = ['background', 'foreground', 'accent', 'border']
        
        for theme_name, theme in THEMES.items():
            app = theme.get('app', {})
            for key in required_app_keys:
                assert key in app, f"Tema '{theme_name}' app não tem a chave '{key}'"
    
    def test_all_themes_sql_has_required_keys(self):
        """Verifica que todos os temas têm as chaves SQL obrigatórias"""
        required_sql_keys = ['keyword', 'string', 'number', 'comment', 'operator']
        
        for theme_name, theme in THEMES.items():
            sql = theme.get('sql', {})
            for key in required_sql_keys:
                assert key in sql, f"Tema '{theme_name}' sql não tem a chave '{key}'"
    
    def test_all_themes_python_has_required_keys(self):
        """Verifica que todos os temas têm as chaves Python obrigatórias"""
        required_python_keys = ['keyword', 'string', 'number', 'comment', 
                                 'classname', 'function', 'identifier']
        
        for theme_name, theme in THEMES.items():
            python = theme.get('python', {})
            for key in required_python_keys:
                assert key in python, f"Tema '{theme_name}' python não tem a chave '{key}'"


class TestThemeManagerGetColors:
    """Testes para os métodos get_*_colors"""
    
    def setup_method(self):
        """Setup para cada teste"""
        self.theme_manager = ThemeManager()
    
    def test_get_editor_colors_returns_all_keys(self):
        """Verifica que get_editor_colors retorna todas as chaves necessárias"""
        required_keys = ['background', 'foreground', 'caret', 'caret_line', 
                         'selection', 'margin_bg', 'margin_fg', 'brace_match']
        
        colors = self.theme_manager.get_editor_colors()
        
        for key in required_keys:
            assert key in colors, f"get_editor_colors() não retornou a chave '{key}'"
    
    def test_get_sql_colors_returns_all_keys(self):
        """Verifica que get_sql_colors retorna todas as chaves necessárias"""
        required_keys = ['keyword', 'string', 'number', 'comment', 'operator']
        
        colors = self.theme_manager.get_sql_colors()
        
        for key in required_keys:
            assert key in colors, f"get_sql_colors() não retornou a chave '{key}'"
    
    def test_get_python_colors_returns_all_keys(self):
        """Verifica que get_python_colors retorna todas as chaves necessárias"""
        required_keys = ['keyword', 'string', 'number', 'comment', 
                         'classname', 'function', 'identifier']
        
        colors = self.theme_manager.get_python_colors()
        
        for key in required_keys:
            assert key in colors, f"get_python_colors() não retornou a chave '{key}'"
    
    def test_get_app_colors_returns_all_keys(self):
        """Verifica que get_app_colors retorna todas as chaves necessárias"""
        required_keys = ['background', 'foreground', 'accent', 'border']
        
        colors = self.theme_manager.get_app_colors()
        
        for key in required_keys:
            assert key in colors, f"get_app_colors() não retornou a chave '{key}'"
    
    def test_get_table_colors_returns_all_keys(self):
        """Verifica que get_table_colors retorna todas as chaves necessárias"""
        # Estas são as chaves usadas em results_viewer.py
        required_keys = ['row_even', 'row_odd', 'text', 'header_bg', 'header_text']
        
        colors = self.theme_manager.get_table_colors()
        
        for key in required_keys:
            assert key in colors, f"get_table_colors() não retornou a chave '{key}'"


class TestThemeManagerStylesheets:
    """Testes para os métodos que geram stylesheets"""
    
    def setup_method(self):
        """Setup para cada teste"""
        self.theme_manager = ThemeManager()
    
    def test_get_dialog_stylesheet_returns_string(self):
        """Verifica que get_dialog_stylesheet retorna uma string"""
        stylesheet = self.theme_manager.get_dialog_stylesheet()
        assert isinstance(stylesheet, str)
        assert len(stylesheet) > 0
    
    def test_get_dialog_stylesheet_contains_no_invalid_css(self):
        """Verifica que get_dialog_stylesheet não contém CSS inválido para Qt"""
        invalid_css_properties = ['filter', 'transform', 'transition', 'animation']
        
        stylesheet = self.theme_manager.get_dialog_stylesheet()
        
        for prop in invalid_css_properties:
            # Verifica se a propriedade aparece como propriedade CSS (seguida de :)
            assert f'{prop}:' not in stylesheet.lower(), \
                f"CSS contém propriedade inválida '{prop}' não suportada pelo Qt"


class TestThemeManagerSwitching:
    """Testes para troca de temas"""
    
    def setup_method(self):
        """Setup para cada teste"""
        self.theme_manager = ThemeManager()
    
    def test_save_theme_changes_current_theme(self):
        """Verifica que save_theme muda o tema atual"""
        self.theme_manager.save_theme('monokai')
        assert self.theme_manager.current_theme == 'monokai'
    
    def test_save_theme_invalid_does_not_change(self):
        """Verifica que tema inválido não muda o tema"""
        original = self.theme_manager.current_theme
        self.theme_manager.save_theme('tema_inexistente')
        assert self.theme_manager.current_theme == original
    
    def test_get_available_themes_returns_list(self):
        """Verifica que get_available_themes retorna lista"""
        themes = self.theme_manager.get_available_themes()
        assert isinstance(themes, list)
        assert len(themes) > 0
    
    def test_get_available_themes_contains_all_themes(self):
        """Verifica que get_available_themes contém todos os temas"""
        themes = self.theme_manager.get_available_themes()
        # Formato é [(id, nome), ...]
        theme_ids = [t[0] for t in themes]
        
        for theme_id in THEMES.keys():
            assert theme_id in theme_ids, f"Tema '{theme_id}' não está na lista de temas disponíveis"


class TestThemeManagerAllThemesColors:
    """Testes para verificar que todos os temas funcionam corretamente"""
    
    def test_all_themes_get_editor_colors(self):
        """Verifica get_editor_colors para todos os temas"""
        theme_manager = ThemeManager()
        required_keys = ['background', 'foreground', 'caret']
        
        for theme_id in THEMES.keys():
            theme_manager.save_theme(theme_id)
            colors = theme_manager.get_editor_colors()
            
            for key in required_keys:
                assert key in colors, f"Tema '{theme_id}': get_editor_colors() não tem '{key}'"
                assert colors[key], f"Tema '{theme_id}': get_editor_colors()['{key}'] está vazio"
    
    def test_all_themes_get_app_colors(self):
        """Verifica get_app_colors para todos os temas"""
        theme_manager = ThemeManager()
        required_keys = ['background', 'foreground', 'accent', 'border']
        
        for theme_id in THEMES.keys():
            theme_manager.save_theme(theme_id)
            colors = theme_manager.get_app_colors()
            
            for key in required_keys:
                assert key in colors, f"Tema '{theme_id}': get_app_colors() não tem '{key}'"
                assert colors[key], f"Tema '{theme_id}': get_app_colors()['{key}'] está vazio"
    
    def test_all_themes_get_table_colors(self):
        """Verifica get_table_colors para todos os temas"""
        theme_manager = ThemeManager()
        required_keys = ['row_even', 'row_odd', 'text', 'header_bg', 'header_text']
        
        for theme_id in THEMES.keys():
            theme_manager.save_theme(theme_id)
            colors = theme_manager.get_table_colors()
            
            for key in required_keys:
                assert key in colors, f"Tema '{theme_id}': get_table_colors() não tem '{key}'"
                assert colors[key], f"Tema '{theme_id}': get_table_colors()['{key}'] está vazio"
    
    def test_all_themes_get_dialog_stylesheet(self):
        """Verifica get_dialog_stylesheet para todos os temas"""
        theme_manager = ThemeManager()
        
        for theme_id in THEMES.keys():
            theme_manager.save_theme(theme_id)
            stylesheet = theme_manager.get_dialog_stylesheet()
            
            assert isinstance(stylesheet, str), f"Tema '{theme_id}': stylesheet não é string"
            assert len(stylesheet) > 100, f"Tema '{theme_id}': stylesheet muito curto"


class TestThemeManagerColorValues:
    """Testes para validar formato de cores"""
    
    def test_color_values_are_valid_hex(self):
        """Verifica que todas as cores são hexadecimais válidos"""
        import re
        from PyQt6.QtGui import QColor
        hex_pattern = re.compile(r'^#[0-9a-fA-F]{6}$')
        
        theme_manager = ThemeManager()
        
        for theme_id in THEMES.keys():
            theme_manager.save_theme(theme_id)
            
            # Verificar cores do editor (retorna QColor)
            for key, value in theme_manager.get_editor_colors().items():
                assert isinstance(value, QColor), \
                    f"Tema '{theme_id}': editor.{key} não é QColor"
            
            # Verificar cores do app (retorna strings)
            for key, value in theme_manager.get_app_colors().items():
                assert hex_pattern.match(value), \
                    f"Tema '{theme_id}': app.{key} = '{value}' não é hex válido"
            
            # Verificar cores da tabela (retorna strings)
            for key, value in theme_manager.get_table_colors().items():
                assert hex_pattern.match(value), \
                    f"Tema '{theme_id}': table.{key} = '{value}' não é hex válido"
