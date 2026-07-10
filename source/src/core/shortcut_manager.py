"""
Configurable keyboard shortcut manager
"""

from typing import Dict, Callable
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ShortcutManager:
    """Manages configurable keyboard shortcuts"""

    DEFAULT_SHORTCUTS = {
        # Execution
        "execute_sql": "F5",
        "execute_all": "Ctrl+F5",
        "execute_block_advance": "Shift+Return",
        "clear_results": "Ctrl+Shift+L",
        # Arquivo
        "open_file": "Ctrl+O",
        "save_file": "Ctrl+S",
        "save_as": "Ctrl+Shift+S",
        "export_script": "Ctrl+Shift+E",
        # Sessions
        "new_tab": "Ctrl+T",
        "new_session": "Ctrl+N",
        "close_tab": "Ctrl+W",
        "add_block": "Ctrl+Shift+B",
        # Edicao
        "find": "Ctrl+F",
        "replace": "Ctrl+H",
        "format_code": "Ctrl+Shift+F",
        "show_entity_info": "Alt+F1",
        # Autocompletar
        "force_autocomplete": "Ctrl+.",
        # Conexoes
        "manage_connections": "Ctrl+Shift+M",
        "new_connection": "Ctrl+Shift+D",
        # Schema
        "reload_schema": "Ctrl+Shift+T",
        # Ferramentas
        "settings": "Ctrl+,",
        # Results grid
        "copy_with_headers": "Ctrl+Shift+C",
        # View / Layout
        "exit_app": "Ctrl+Q",
        "restore_view": "Ctrl+Shift+R",
        "reset_layout": "Ctrl+Shift+Alt+R",
        # Editor (atalhos internos do QScintilla)
        "editor_newline": "",
        "editor_duplicate_line": "Ctrl+D",
        "editor_cut_line": "Ctrl+L",
        "editor_transpose_line": "",
        "editor_lowercase": "Ctrl+U",
        "editor_uppercase": "Ctrl+Shift+U",
        "editor_delete_line": "Ctrl+Shift+K",
    }

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Use WorkspaceService for default path (supports workspace switching)
            from src.core.workspace_service import get_workspace_service
            config_path = get_workspace_service().get_config_path("shortcuts.json")

        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.shortcuts: Dict[str, str] = self._load_shortcuts()
        self.active_shortcuts: Dict[str, QShortcut] = {}

    def _load_shortcuts(self) -> Dict[str, str]:
        """Loads shortcuts from configuration file.

        Merges saved shortcuts with defaults so that newly added
        shortcuts are always available even when the user has an
        existing configuration file.
        """
        merged = self.DEFAULT_SHORTCUTS.copy()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved = data.get("shortcuts", data) if isinstance(data, dict) else {}
                    merged.update(saved)
            except Exception:
                pass
        return merged

    def save_shortcuts(self):
        """Save shortcuts to config file"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"shortcuts": self.shortcuts}, f, indent=2)

    def get_shortcut(self, action: str) -> str:
        """Return shortcut for an action"""
        return self.shortcuts.get(action, "")

    def set_shortcut(self, action: str, key_sequence: str):
        """Sets a new shortcut for an action"""
        self.shortcuts[action] = key_sequence
        self.save_shortcuts()

    def update_shortcuts(self, updates: Dict[str, str]) -> None:
        """Apply multiple shortcut changes with a single disk write."""
        if not updates:
            return
        self.shortcuts.update(updates)
        self.save_shortcuts()

    def reset_to_defaults(self):
        """Reset all shortcuts to default"""
        self.shortcuts = self.DEFAULT_SHORTCUTS.copy()
        self.save_shortcuts()

    def register_shortcut(self, parent: QWidget, action: str, callback: Callable):
        """Registra um atalho com callback"""
        key_sequence = self.get_shortcut(action)
        if key_sequence:
            shortcut = QShortcut(QKeySequence(key_sequence), parent)
            shortcut.activated.connect(callback)
            self.active_shortcuts[action] = shortcut

    def get_all_shortcuts(self) -> Dict[str, str]:
        """Retorna todos os atalhos configurados"""
        return self.shortcuts.copy()

    def detect_duplicates(self) -> Dict[str, list]:
        """Detect duplicate shortcuts and log them.
        
        Returns:
            Dict mapping shortcut key to list of action names using it
        """
        shortcut_to_actions: Dict[str, list] = {}
        for action, shortcut in self.shortcuts.items():
            if not shortcut:
                continue
            # Normalize the shortcut for comparison
            normalized = QKeySequence(shortcut).toString()
            if normalized not in shortcut_to_actions:
                shortcut_to_actions[normalized] = []
            shortcut_to_actions[normalized].append(action)
        
        # Filter to only duplicates
        duplicates = {k: v for k, v in shortcut_to_actions.items() if len(v) > 1}
        
        if duplicates:
            for shortcut, actions in duplicates.items():
                logger.warning(
                    f"Duplicate shortcut detected: {shortcut} is used by: {', '.join(actions)}"
                )
        
        return duplicates
