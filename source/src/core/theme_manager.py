"""
Application theme manager
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from PyQt6.QtGui import QColor


# Available themes definition
THEMES = {
    "dark": {
        "name": "Dark (VS Code)",
        "editor": {
            "background": "#1e1e1e",
            "foreground": "#d4d4d4",
            "caret": "#ffffff",
            "caret_line": "#2a2a2a",
            "selection": "#264f78",
            "margin_bg": "#1e1e1e",
            "margin_fg": "#858585",
            "brace_match": "#3e3e42",
        },
        "sql": {
            "keyword": "#569cd6",
            "string": "#ce9178",
            "number": "#b5cea8",
            "comment": "#6a9955",
            "operator": "#4ec9b0",
        },
        "python": {
            "keyword": "#569cd6",
            "string": "#ce9178",
            "number": "#b5cea8",
            "comment": "#6a9955",
            "classname": "#4ec9b0",
            "function": "#dcdcaa",
            "identifier": "#9cdcfe",
        },
        "app": {
            "background": "#1e1e1e",
            "foreground": "#cccccc",
            "accent": "#3369FF",
            "border": "#3e3e42",
        },
    },
    "monokai": {
        "name": "Monokai",
        "editor": {
            "background": "#272822",
            "foreground": "#f8f8f2",
            "caret": "#f8f8f0",
            "caret_line": "#3e3d32",
            "selection": "#49483e",
            "margin_bg": "#272822",
            "margin_fg": "#90908a",
            "brace_match": "#49483e",
        },
        "sql": {
            "keyword": "#f92672",
            "string": "#e6db74",
            "number": "#ae81ff",
            "comment": "#75715e",
            "operator": "#f8f8f2",
        },
        "python": {
            "keyword": "#f92672",
            "string": "#e6db74",
            "number": "#ae81ff",
            "comment": "#75715e",
            "classname": "#a6e22e",
            "function": "#a6e22e",
            "identifier": "#f8f8f2",
        },
        "app": {
            "background": "#272822",
            "foreground": "#f8f8f2",
            "accent": "#a6e22e",
            "border": "#49483e",
        },
    },
    "dracula": {
        "name": "Dracula",
        "editor": {
            "background": "#282a36",
            "foreground": "#f8f8f2",
            "caret": "#f8f8f2",
            "caret_line": "#44475a",
            "selection": "#44475a",
            "margin_bg": "#282a36",
            "margin_fg": "#6272a4",
            "brace_match": "#44475a",
        },
        "sql": {
            "keyword": "#ff79c6",
            "string": "#f1fa8c",
            "number": "#bd93f9",
            "comment": "#6272a4",
            "operator": "#ff79c6",
        },
        "python": {
            "keyword": "#ff79c6",
            "string": "#f1fa8c",
            "number": "#bd93f9",
            "comment": "#6272a4",
            "classname": "#8be9fd",
            "function": "#50fa7b",
            "identifier": "#f8f8f2",
        },
        "app": {
            "background": "#282a36",
            "foreground": "#f8f8f2",
            "accent": "#bd93f9",
            "border": "#44475a",
        },
    },
    "solarized_dark": {
        "name": "Solarized Dark",
        "editor": {
            "background": "#002b36",
            "foreground": "#839496",
            "caret": "#839496",
            "caret_line": "#073642",
            "selection": "#073642",
            "margin_bg": "#002b36",
            "margin_fg": "#586e75",
            "brace_match": "#073642",
        },
        "sql": {
            "keyword": "#268bd2",
            "string": "#2aa198",
            "number": "#d33682",
            "comment": "#586e75",
            "operator": "#839496",
        },
        "python": {
            "keyword": "#268bd2",
            "string": "#2aa198",
            "number": "#d33682",
            "comment": "#586e75",
            "classname": "#b58900",
            "function": "#268bd2",
            "identifier": "#839496",
        },
        "app": {
            "background": "#002b36",
            "foreground": "#839496",
            "accent": "#268bd2",
            "border": "#073642",
        },
    },
    "nord": {
        "name": "Nord",
        "editor": {
            "background": "#2e3440",
            "foreground": "#d8dee9",
            "caret": "#d8dee9",
            "caret_line": "#3b4252",
            "selection": "#434c5e",
            "margin_bg": "#2e3440",
            "margin_fg": "#4c566a",
            "brace_match": "#434c5e",
        },
        "sql": {
            "keyword": "#81a1c1",
            "string": "#a3be8c",
            "number": "#b48ead",
            "comment": "#616e88",
            "operator": "#81a1c1",
        },
        "python": {
            "keyword": "#81a1c1",
            "string": "#a3be8c",
            "number": "#b48ead",
            "comment": "#616e88",
            "classname": "#8fbcbb",
            "function": "#88c0d0",
            "identifier": "#d8dee9",
        },
        "app": {
            "background": "#2e3440",
            "foreground": "#d8dee9",
            "accent": "#88c0d0",
            "border": "#3b4252",
        },
    },
}


class ThemeManager:
    """Manages application themes"""

    def __init__(self, config_path: str = None, initial_theme: str = "dark"):
        # General application theme
        self.current_theme = initial_theme if initial_theme in THEMES else "dark"
        # Specific editor theme (if None, uses general theme)
        self.editor_theme = None

    def _load_theme(self) -> str:
        """Retorna tema atual"""
        return self.current_theme

    def save_theme(self, theme_name: str):
        """Define o tema atual"""
        if theme_name in THEMES:
            self.current_theme = theme_name

    def set_theme(self, theme_name: str):
        """Define o tema atual"""
        if theme_name in THEMES:
            self.current_theme = theme_name
            return True
        return False

    def set_editor_theme(self, theme_name: str):
        """Set specific theme for editors"""
        if theme_name in THEMES:
            self.editor_theme = theme_name
            return True
        return False

    def get_editor_theme_name(self) -> str:
        """Retorna nome do tema dos editores (se definido) ou tema geral"""
        return self.editor_theme or self.current_theme

    def get_current_theme(self) -> Dict[str, Any]:
        """Returns current theme configuration"""
        return THEMES.get(self.current_theme, THEMES["dark"])

    def get_theme_name(self) -> str:
        """Retorna nome do tema atual"""
        return self.current_theme

    def get_available_themes(self) -> List[tuple]:
        """Return list of available themes [(id, name), ...]"""
        return [(theme_id, theme["name"]) for theme_id, theme in THEMES.items()]

    def get_editor_colors(self) -> Dict[str, QColor]:
        """Retorna cores do editor como QColor"""
        # Usar tema específico dos editores se definido
        theme_name = self.editor_theme or self.current_theme
        theme = THEMES.get(theme_name, THEMES["dark"])
        colors = theme["editor"]
        return {k: QColor(v) for k, v in colors.items()}

    def get_sql_colors(self) -> Dict[str, QColor]:
        """Retorna cores SQL como QColor"""
        # Usar tema específico dos editores se definido
        theme_name = self.editor_theme or self.current_theme
        theme = THEMES.get(theme_name, THEMES["dark"])
        colors = theme["sql"]
        return {k: QColor(v) for k, v in colors.items()}

    def get_python_colors(self) -> Dict[str, QColor]:
        """Retorna cores Python como QColor"""
        # Usar tema específico dos editores se definido
        theme_name = self.editor_theme or self.current_theme
        theme = THEMES.get(theme_name, THEMES["dark"])
        colors = theme["python"]
        return {k: QColor(v) for k, v in colors.items()}

    def get_app_colors(self) -> Dict[str, str]:
        """Returns application colors"""
        theme = self.get_current_theme()
        return theme["app"]

    def get_dialog_stylesheet(self) -> str:
        """Retorna stylesheet para dialogs"""
        c = self.get_app_colors()
        return f"""
            QDialog {{
                background-color: {c["background"]};
                color: {c["foreground"]};
            }}
            QLabel {{
                color: {c["foreground"]};
            }}
            QLineEdit {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                padding: 10px 12px;
                border-radius: 8px;
                min-height: 20px;
            }}
            QLineEdit:focus {{
                border: 2px solid {c["accent"]};
            }}
            QLineEdit:hover {{
                border-color: {c["accent"]};
            }}
            QTextEdit {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
            }}
            QComboBox {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                padding: 10px 12px;
                border-radius: 8px;
                min-height: 24px;
            }}
            QComboBox:hover {{
                border-color: {c["accent"]};
            }}
            QComboBox:focus {{
                border: 2px solid {c["accent"]};
            }}
            QComboBox::drop-down {{
                border: none;
                border-radius: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c["background"]};
                color: {c["foreground"]};
                selection-background-color: {c["accent"]};
                border-radius: 8px;
                padding: 4px;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 8px;
                border-radius: 6px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {c["border"]};
            }}
            QCheckBox {{
                color: {c["foreground"]};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 2px solid {c["border"]};
                background-color: {c["background"]};
                border-radius: 4px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {c["accent"]};
                border: 2px solid {c["accent"]};
                border-radius: 4px;
            }}
            QCheckBox::indicator:unchecked:hover {{
                border-color: {c["accent"]};
            }}
            QSpinBox {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                padding: 8px 10px;
                border-radius: 8px;
                min-height: 20px;
            }}
            QSpinBox:hover {{
                border-color: {c["accent"]};
            }}
            QSpinBox:focus {{
                border: 2px solid {c["accent"]};
            }}
            QPushButton {{
                background-color: {c["accent"]};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                font-weight: 600;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background-color: {c["accent"]};
                opacity: 0.9;
            }}
            QPushButton:pressed {{
                background-color: {c["accent"]};
            }}
            QPushButton#btnCancel {{
                background-color: {c["border"]};
                color: {c["foreground"]};
            }}
            QPushButton#btnCancel:hover {{
                background-color: {c["foreground"]};
                color: {c["background"]};
            }}
            QPushButton#btnReset {{
                background-color: #ef4444;
            }}
            QPushButton#btnReset:hover {{
                background-color: #f87171;
            }}
            QTableWidget {{
                background-color: {c["background"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                gridline-color: {c["border"]};
            }}
            QTableWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QTableWidget::item:selected {{
                background-color: {c["accent"]};
            }}
            QHeaderView::section {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                padding: 8px 10px;
                border: none;
                border-right: 1px solid {c["background"]};
                border-bottom: 1px solid {c["background"]};
                font-weight: 600;
            }}
            QTableView {{
                background-color: {c["background"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                gridline-color: {c["border"]};
            }}
            QTableView::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QTableView::item:selected {{
                background-color: {c["accent"]};
            }}
            QGroupBox {{
                color: {c["foreground"]};
                font-weight: 600;
                border: 1px solid {c["border"]};
                border-radius: 12px;
                margin-top: 16px;
                padding: 16px;
                padding-top: 24px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
            }}
            QListWidget {{
                background-color: {c["background"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
                color: {c["foreground"]};
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 6px;
                margin: 2px 0;
            }}
            QListWidget::item:hover {{
                background-color: {c["border"]};
            }}
            QListWidget::item:selected {{
                background-color: {c["accent"]};
                color: white;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::handle:vertical:pressed {{
                background: rgba(128, 128, 128, 0.7);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-width: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: rgba(128, 128, 128, 0.7);
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            QScrollBar::corner {{
                background: transparent;
            }}
            QTreeWidget {{
                background-color: {c["background"]};
                color: {c["foreground"]};
                border: 1px solid {c["border"]};
                border-radius: 8px;
            }}
            QTreeWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QTreeWidget::item:hover {{
                background-color: {c["border"]};
            }}
            QTreeWidget::item:selected {{
                background-color: {c["accent"]};
            }}
            QTreeWidget QLineEdit {{
                background-color: {c["border"]};
                color: {c["foreground"]};
                border: 2px solid {c["accent"]};
                border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: {c["accent"]};
                selection-color: white;
            }}
            QToolBar {{
                background-color: {c["background"]};
                border: none;
                border-bottom: 1px solid {c["border"]};
                spacing: 8px;
                padding: 8px;
            }}
            QToolBar QToolButton {{
                border-radius: 6px;
                padding: 6px;
            }}
            QToolBar QToolButton:hover {{
                background-color: {c["border"]};
            }}
            QFrame[frameShape="StyledPanel"] {{
                background-color: {c["background"]};
                border: 1px solid {c["border"]};
                border-radius: 12px;
                padding: 12px;
            }}
        """

    def get_table_colors(self) -> Dict[str, str]:
        """Retorna cores para tabelas"""
        c = self.get_app_colors()
        editor = self.get_current_theme().get("editor", {})
        # Calcular cor alternativa para linhas
        row_even = c["background"]
        row_odd = editor.get("caret_line", c["border"])
        return {
            "background": c["background"],
            "foreground": c["foreground"],
            "text": c["foreground"],
            "row_even": row_even,
            "row_odd": row_odd,
            "row_alt": c["border"],
            "header_bg": c["border"],
            "header_fg": c["foreground"],
            "header_text": c["foreground"],
            "selection": c["accent"],
            "grid": c["border"],
        }
