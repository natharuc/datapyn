"""
Gerenciador de temas da aplicação
"""
import json
from pathlib import Path
from typing import Dict, Any, List
from PyQt6.QtGui import QColor


# Definição dos temas disponíveis
THEMES = {
    'dark': {
        'name': 'Dark (VS Code)',
        'editor': {
            'background': '#1e1e1e',
            'foreground': '#d4d4d4',
            'caret': '#ffffff',
            'caret_line': '#2a2a2a',
            'selection': '#264f78',
            'margin_bg': '#1e1e1e',
            'margin_fg': '#858585',
            'brace_match': '#3e3e42',
        },
        'sql': {
            'keyword': '#569cd6',
            'string': '#ce9178',
            'number': '#b5cea8',
            'comment': '#6a9955',
            'operator': '#4ec9b0',
        },
        'python': {
            'keyword': '#569cd6',
            'string': '#ce9178',
            'number': '#b5cea8',
            'comment': '#6a9955',
            'classname': '#4ec9b0',
            'function': '#dcdcaa',
            'identifier': '#9cdcfe',
        },
        'app': {
            'background': '#1e1e1e',
            'foreground': '#cccccc',
            'accent': '#007acc',
            'border': '#3e3e42',
        }
    },
    'light': {
        'name': 'Light',
        'editor': {
            'background': '#ffffff',
            'foreground': '#000000',
            'caret': '#000000',
            'caret_line': '#f0f0f0',
            'selection': '#add6ff',
            'margin_bg': '#f5f5f5',
            'margin_fg': '#237893',
            'brace_match': '#e0e0e0',
        },
        'sql': {
            'keyword': '#0000ff',
            'string': '#a31515',
            'number': '#098658',
            'comment': '#008000',
            'operator': '#000000',
        },
        'python': {
            'keyword': '#0000ff',
            'string': '#a31515',
            'number': '#098658',
            'comment': '#008000',
            'classname': '#267f99',
            'function': '#795e26',
            'identifier': '#001080',
        },
        'app': {
            'background': '#f3f3f3',
            'foreground': '#333333',
            'accent': '#007acc',
            'border': '#cccccc',
        }
    },
    'monokai': {
        'name': 'Monokai',
        'editor': {
            'background': '#272822',
            'foreground': '#f8f8f2',
            'caret': '#f8f8f0',
            'caret_line': '#3e3d32',
            'selection': '#49483e',
            'margin_bg': '#272822',
            'margin_fg': '#90908a',
            'brace_match': '#49483e',
        },
        'sql': {
            'keyword': '#f92672',
            'string': '#e6db74',
            'number': '#ae81ff',
            'comment': '#75715e',
            'operator': '#f8f8f2',
        },
        'python': {
            'keyword': '#f92672',
            'string': '#e6db74',
            'number': '#ae81ff',
            'comment': '#75715e',
            'classname': '#a6e22e',
            'function': '#a6e22e',
            'identifier': '#f8f8f2',
        },
        'app': {
            'background': '#272822',
            'foreground': '#f8f8f2',
            'accent': '#a6e22e',
            'border': '#49483e',
        }
    },
    'dracula': {
        'name': 'Dracula',
        'editor': {
            'background': '#282a36',
            'foreground': '#f8f8f2',
            'caret': '#f8f8f2',
            'caret_line': '#44475a',
            'selection': '#44475a',
            'margin_bg': '#282a36',
            'margin_fg': '#6272a4',
            'brace_match': '#44475a',
        },
        'sql': {
            'keyword': '#ff79c6',
            'string': '#f1fa8c',
            'number': '#bd93f9',
            'comment': '#6272a4',
            'operator': '#ff79c6',
        },
        'python': {
            'keyword': '#ff79c6',
            'string': '#f1fa8c',
            'number': '#bd93f9',
            'comment': '#6272a4',
            'classname': '#8be9fd',
            'function': '#50fa7b',
            'identifier': '#f8f8f2',
        },
        'app': {
            'background': '#282a36',
            'foreground': '#f8f8f2',
            'accent': '#bd93f9',
            'border': '#44475a',
        }
    },
    'solarized_dark': {
        'name': 'Solarized Dark',
        'editor': {
            'background': '#002b36',
            'foreground': '#839496',
            'caret': '#839496',
            'caret_line': '#073642',
            'selection': '#073642',
            'margin_bg': '#002b36',
            'margin_fg': '#586e75',
            'brace_match': '#073642',
        },
        'sql': {
            'keyword': '#268bd2',
            'string': '#2aa198',
            'number': '#d33682',
            'comment': '#586e75',
            'operator': '#839496',
        },
        'python': {
            'keyword': '#268bd2',
            'string': '#2aa198',
            'number': '#d33682',
            'comment': '#586e75',
            'classname': '#b58900',
            'function': '#268bd2',
            'identifier': '#839496',
        },
        'app': {
            'background': '#002b36',
            'foreground': '#839496',
            'accent': '#268bd2',
            'border': '#073642',
        }
    },
    'nord': {
        'name': 'Nord',
        'editor': {
            'background': '#2e3440',
            'foreground': '#d8dee9',
            'caret': '#d8dee9',
            'caret_line': '#3b4252',
            'selection': '#434c5e',
            'margin_bg': '#2e3440',
            'margin_fg': '#4c566a',
            'brace_match': '#434c5e',
        },
        'sql': {
            'keyword': '#81a1c1',
            'string': '#a3be8c',
            'number': '#b48ead',
            'comment': '#616e88',
            'operator': '#81a1c1',
        },
        'python': {
            'keyword': '#81a1c1',
            'string': '#a3be8c',
            'number': '#b48ead',
            'comment': '#616e88',
            'classname': '#8fbcbb',
            'function': '#88c0d0',
            'identifier': '#d8dee9',
        },
        'app': {
            'background': '#2e3440',
            'foreground': '#d8dee9',
            'accent': '#88c0d0',
            'border': '#3b4252',
        }
    },
}


class ThemeManager:
    """Gerencia temas da aplicação"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path.home() / '.datapyn' / 'theme.json'
        
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_theme = self._load_theme()
    
    def _load_theme(self) -> str:
        """Carrega tema salvo ou retorna padrão"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    theme = data.get('theme', 'dark')
                    if theme in THEMES:
                        return theme
            except:
                pass
        return 'dark'
    
    def save_theme(self, theme_name: str):
        """Salva tema escolhido"""
        if theme_name in THEMES:
            self.current_theme = theme_name
            with open(self.config_path, 'w') as f:
                json.dump({'theme': theme_name}, f)
    
    def get_current_theme(self) -> Dict[str, Any]:
        """Retorna configuração do tema atual"""
        return THEMES.get(self.current_theme, THEMES['dark'])
    
    def get_theme_name(self) -> str:
        """Retorna nome do tema atual"""
        return self.current_theme
    
    def get_available_themes(self) -> List[tuple]:
        """Retorna lista de temas disponíveis [(id, nome), ...]"""
        return [(theme_id, theme['name']) for theme_id, theme in THEMES.items()]
    
    def get_editor_colors(self) -> Dict[str, QColor]:
        """Retorna cores do editor como QColor"""
        theme = self.get_current_theme()
        colors = theme['editor']
        return {k: QColor(v) for k, v in colors.items()}
    
    def get_sql_colors(self) -> Dict[str, QColor]:
        """Retorna cores SQL como QColor"""
        theme = self.get_current_theme()
        colors = theme['sql']
        return {k: QColor(v) for k, v in colors.items()}
    
    def get_python_colors(self) -> Dict[str, QColor]:
        """Retorna cores Python como QColor"""
        theme = self.get_current_theme()
        colors = theme['python']
        return {k: QColor(v) for k, v in colors.items()}
    
    def get_app_colors(self) -> Dict[str, str]:
        """Retorna cores da aplicação"""
        theme = self.get_current_theme()
        return theme['app']
    
    def get_dialog_stylesheet(self) -> str:
        """Retorna stylesheet para dialogs"""
        c = self.get_app_colors()
        return f"""
            QDialog {{
                background-color: {c['background']};
                color: {c['foreground']};
            }}
            QLabel {{
                color: {c['foreground']};
            }}
            QLineEdit {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                padding: 8px;
                border-radius: 3px;
            }}
            QLineEdit:focus {{
                border-color: {c['accent']};
            }}
            QTextEdit {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
            }}
            QComboBox {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                padding: 8px;
                border-radius: 3px;
            }}
            QComboBox:hover {{
                border-color: {c['accent']};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['background']};
                color: {c['foreground']};
                selection-background-color: {c['accent']};
            }}
            QCheckBox {{
                color: {c['foreground']};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {c['border']};
                background-color: {c['background']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {c['accent']};
                border: 1px solid {c['accent']};
            }}
            QSpinBox {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                padding: 5px;
            }}
            QPushButton {{
                background-color: {c['accent']};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 3px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {c['accent']};
                opacity: 0.8;
            }}
            QPushButton#btnCancel {{
                background-color: {c['border']};
                color: {c['foreground']};
            }}
            QPushButton#btnReset {{
                background-color: #c5534d;
            }}
            QTableWidget {{
                background-color: {c['background']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                gridline-color: {c['border']};
            }}
            QTableWidget::item:selected {{
                background-color: {c['accent']};
            }}
            QHeaderView::section {{
                background-color: {c['border']};
                color: {c['foreground']};
                padding: 5px;
                border: 1px solid {c['border']};
                font-weight: bold;
            }}
            QTableView {{
                background-color: {c['background']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                gridline-color: {c['border']};
            }}
            QTableView::item:selected {{
                background-color: {c['accent']};
            }}
            QGroupBox {{
                color: {c['accent']};
                font-weight: bold;
                border: 1px solid {c['border']};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QListWidget {{
                background-color: {c['background']};
                border: 1px solid {c['border']};
                color: {c['foreground']};
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {c['border']};
            }}
            QListWidget::item:hover {{
                background-color: {c['border']};
            }}
            QListWidget::item:selected {{
                background-color: {c['accent']};
                color: white;
            }}
            QScrollBar:vertical {{
                background-color: {c['background']};
                width: 12px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {c['border']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QTreeWidget {{
                background-color: {c['background']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
            }}
            QTreeWidget::item:selected {{
                background-color: {c['accent']};
            }}
            QToolBar {{
                background-color: {c['border']};
                border-bottom: 1px solid {c['border']};
                spacing: 5px;
                padding: 5px;
            }}
        """
    
    def get_table_colors(self) -> Dict[str, str]:
        """Retorna cores para tabelas"""
        c = self.get_app_colors()
        editor = self.get_current_theme().get('editor', {})
        # Calcular cor alternativa para linhas
        row_even = c['background']
        row_odd = editor.get('caret_line', c['border'])
        return {
            'background': c['background'],
            'foreground': c['foreground'],
            'text': c['foreground'],
            'row_even': row_even,
            'row_odd': row_odd,
            'row_alt': c['border'],
            'header_bg': c['border'],
            'header_fg': c['foreground'],
            'header_text': c['foreground'],
            'selection': c['accent'],
            'grid': c['border'],
        }
