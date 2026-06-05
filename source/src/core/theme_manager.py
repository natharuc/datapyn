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
            "background": "#121a2b",
            "foreground": "#eef2f7",
            "caret": "#ffffff",
            "caret_line": "#161f30",
            "selection": "rgba(51, 105, 255, 0.35)",
            "margin_bg": "#121a2b",
            "margin_fg": "#5c6d85",
            "brace_match": "#1e2a42",
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
            "background": "#0c111b",
            "foreground": "#eef2f7",
            "accent": "#3369ff",
            "border": "rgba(148, 163, 184, 0.18)",
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
        """Dialog stylesheet — design-system blue dark (single source of truth)."""
        from src.design_system.tokens import get_dialog_base_stylesheet

        return get_dialog_base_stylesheet()

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
