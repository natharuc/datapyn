"""
Workspace manager - saves and restores application state
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class WorkspaceManager:
    """Manages workspace state (tabs, connections, code, geometry)"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path.home() / ".datapyn" / "workspace.json"

        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Store current workspace file path (when user opens/saves a specific file)
        self.current_file_path: Optional[Path] = None

    def save_workspace(
        self,
        tabs: List[Dict[str, Any]],
        active_tab: int,
        active_connection: str = None,
        window_geometry: Dict = None,
        splitter_sizes: List[int] = None,
        dock_visible: bool = True,
        file_path: str = None,
    ):
        """
        Salva estado do workspace

        Args:
            tabs: Lista de dicts com {'code': str, 'connection': str, 'title': str}
            active_tab: Active tab index
            active_connection: Active connection name
            window_geometry: Dict com x, y, width, height, maximized
            splitter_sizes: Lista com tamanhos do splitter [editor, results]
            dock_visible: Whether connections dock is visible
            file_path: Path to save file (if None, uses current_file_path or default config_path)
        """
        workspace = {
            "tabs": tabs,
            "active_tab": active_tab,
            "active_connection": active_connection,
            "window_geometry": window_geometry,
            "splitter_sizes": splitter_sizes,
            "dock_visible": dock_visible,
        }

        # Determinar onde salvar
        if file_path:
            save_path = Path(file_path)
            self.current_file_path = save_path
        elif self.current_file_path:
            save_path = self.current_file_path
        else:
            save_path = self.config_path

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(workspace, f, indent=2, ensure_ascii=False)

    def load_workspace(self, file_path: str = None) -> Dict[str, Any]:
        """
        Load workspace state

        Args:
            file_path: File path to load (if None, uses default config_path)

        Returns:
            Dict with 'tabs', 'active_tab', 'active_connection', 'window_geometry', etc
        """
        default = {
            "tabs": [{"code": "", "connection": None, "title": "Script 1"}],
            "active_tab": 0,
            "active_connection": None,
            "window_geometry": None,
            "splitter_sizes": None,
            "dock_visible": True,
        }

        # Determinar de onde carregar
        if file_path:
            load_path = Path(file_path)
            self.current_file_path = load_path
        else:
            load_path = self.config_path

        if not load_path.exists():
            return default

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                workspace = json.load(f)

            # Basic validation
            if "tabs" not in workspace or not workspace["tabs"]:
                workspace["tabs"] = default["tabs"]

            if "active_tab" not in workspace:
                workspace["active_tab"] = 0

            # Garantir que os novos campos existam
            workspace.setdefault("window_geometry", None)
            workspace.setdefault("splitter_sizes", None)
            workspace.setdefault("dock_visible", True)

            return workspace

        except Exception as e:
            print(f"Error loading workspace: {e}")
            return default

    def clear_workspace(self):
        """Limpa workspace salvo"""
        if self.config_path.exists():
            self.config_path.unlink()
