"""
WorkspaceService - Centralized workspace/profile management.

Workspaces allow users to have completely separate configurations:
- Connections, sessions, shortcuts, editor state
- Each workspace is a folder containing config files
- Default workspace: ~/.datapyn/
- Custom workspaces: any user-selected folder

Usage:
    from src.core.workspace_service import get_workspace_service
    
    ws = get_workspace_service()
    config_path = ws.get_config_path("connections.json")
"""

import logging
from pathlib import Path
from typing import List, Tuple, Optional

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

logger = logging.getLogger(__name__)


# Default workspace location
DEFAULT_WORKSPACE_PATH = Path.home() / ".datapyn"
DEFAULT_WORKSPACE_NAME = "Default"

# Module-level singleton instance
_workspace_service_instance: Optional["WorkspaceService"] = None


class WorkspaceService(QObject):
    """Centralized service for workspace/profile management."""
    
    # Emitted when workspace changes (requires app restart)
    workspace_changed = pyqtSignal(str)  # path
    # Emitted when a workspace is added to the list
    workspace_added = pyqtSignal(str)  # path
    # Emitted when a workspace is removed from the list
    workspace_removed = pyqtSignal(str)  # path
    
    def __init__(self):
        super().__init__()
        
        # Global settings for workspace list (not per-workspace)
        self._global_settings = QSettings("DataPyn", "Workspaces")
        
        # Load current workspace from settings
        saved_path = self._global_settings.value("current_workspace", "")
        if saved_path and Path(saved_path).exists():
            self._current_workspace = Path(saved_path)
        else:
            self._current_workspace = DEFAULT_WORKSPACE_PATH
        
        # Ensure workspace folder exists
        self._current_workspace.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"WorkspaceService initialized: {self._current_workspace}")
    
    # ========================
    # WORKSPACE PROPERTIES
    # ========================
    
    @property
    def current_workspace(self) -> Path:
        """Get the current workspace folder path."""
        return self._current_workspace
    
    @property
    def current_workspace_name(self) -> str:
        """Get human-readable name for current workspace."""
        if self._current_workspace == DEFAULT_WORKSPACE_PATH:
            return DEFAULT_WORKSPACE_NAME
        return self._current_workspace.name
    
    @property
    def is_default_workspace(self) -> bool:
        """Check if current workspace is the default."""
        return self._current_workspace == DEFAULT_WORKSPACE_PATH
    
    # ========================
    # CONFIG PATH HELPERS
    # ========================
    
    def get_config_path(self, filename: str) -> Path:
        """
        Get the full path for a config file in the current workspace.
        
        Args:
            filename: Config file name (e.g., "connections.json", "workspace.json")
        
        Returns:
            Full path within the current workspace folder
        """
        return self._current_workspace / filename
    
    def get_config_dir(self, dirname: str) -> Path:
        """
        Get a subdirectory path in the current workspace.
        Creates the directory if it doesn't exist.
        
        Args:
            dirname: Directory name (e.g., "oauth_cache")
        
        Returns:
            Full path to subdirectory
        """
        dir_path = self._current_workspace / dirname
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path
    
    # ========================
    # WORKSPACE MANAGEMENT
    # ========================
    
    def list_workspaces(self) -> List[Tuple[str, Path]]:
        """
        Get list of known workspaces.
        
        Returns:
            List of (name, path) tuples. Default workspace is always first.
        """
        workspaces = [(DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_PATH)]
        
        # Load saved workspaces
        saved_list = self._global_settings.value("workspace_list", [])
        if saved_list:
            for path_str in saved_list:
                path = Path(path_str)
                if path.exists() and path != DEFAULT_WORKSPACE_PATH:
                    workspaces.append((path.name, path))
        
        return workspaces
    
    def add_workspace(self, path: Path) -> bool:
        """
        Add a new workspace folder to the list.
        
        Args:
            path: Folder path to add as workspace
        
        Returns:
            True if added successfully
        """
        path = Path(path).resolve()
        
        if path == DEFAULT_WORKSPACE_PATH:
            logger.warning("Cannot add default workspace path")
            return False
        
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Cannot create workspace folder: {e}")
                return False
        
        # Add to saved list
        saved_list = self._global_settings.value("workspace_list", []) or []
        path_str = str(path)
        if path_str not in saved_list:
            saved_list.append(path_str)
            self._global_settings.setValue("workspace_list", saved_list)
            logger.info(f"Added workspace: {path}")
            self.workspace_added.emit(path_str)
        
        return True
    
    def remove_workspace(self, path: Path) -> bool:
        """
        Remove a workspace from the list (doesn't delete files).
        
        Args:
            path: Workspace path to remove
        
        Returns:
            True if removed
        """
        path = Path(path).resolve()
        
        if path == DEFAULT_WORKSPACE_PATH:
            logger.warning("Cannot remove default workspace")
            return False
        
        saved_list = self._global_settings.value("workspace_list", []) or []
        path_str = str(path)
        if path_str in saved_list:
            saved_list.remove(path_str)
            self._global_settings.setValue("workspace_list", saved_list)
            logger.info(f"Removed workspace: {path}")
            self.workspace_removed.emit(path_str)
            return True
        
        return False
    
    def switch_workspace(self, path: Path) -> bool:
        """
        Switch to a different workspace.
        
        Updates the current workspace immediately and saves the setting.
        For use with --workspace command line argument in new instances.
        
        Args:
            path: Target workspace path
        
        Returns:
            True if switch was successful
        """
        path = Path(path).resolve()
        
        if path == self._current_workspace:
            logger.debug("Already in this workspace")
            return False
        
        if path == DEFAULT_WORKSPACE_PATH:
            # Clear setting to use default
            self._global_settings.remove("current_workspace")
        else:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            self._global_settings.setValue("current_workspace", str(path))
        
        # Update current workspace immediately (for new instances with --workspace)
        self._current_workspace = path
        
        logger.info(f"Workspace switched to: {path}")
        self.workspace_changed.emit(str(path))
        return True
    
    # ========================
    # QSETTINGS HELPERS
    # ========================
    
    def get_workspace_settings(self, app_name: str) -> QSettings:
        """
        Get QSettings scoped to the current workspace.

        Uses INI file format stored in workspace folder for isolation.

        Args:
            app_name: Settings category name (e.g., "CopilotSettings", "MainWindow")

        Returns:
            QSettings instance for this workspace
        """
        ini_path = self.get_config_path(f"{app_name}.ini")
        return QSettings(str(ini_path), QSettings.Format.IniFormat)


def qsettings_alive(obj: Optional[QSettings]) -> bool:
    """True when a cached QSettings' underlying C++ instance is still usable.

    Settings singletons cache a QSettings for the whole process. When the
    QApplication is torn down and recreated (e.g. between test files) the C++
    object is destroyed while the Python wrapper survives — any access then
    raises ``RuntimeError: wrapped C/C++ object ... has been deleted``. A
    functional probe catches this (sip.isdeleted does not always flag it).
    """
    if obj is None:
        return False
    try:
        obj.value("__alive_probe__")
        return True
    except RuntimeError:
        return False


def get_workspace_service() -> WorkspaceService:
    """Get the singleton WorkspaceService instance."""
    global _workspace_service_instance
    if _workspace_service_instance is None:
        _workspace_service_instance = WorkspaceService()
    return _workspace_service_instance


def get_workspace_path() -> Path:
    """Convenience function to get current workspace path."""
    return get_workspace_service().current_workspace


def get_config_path(filename: str) -> Path:
    """Convenience function to get config file path in current workspace."""
    return get_workspace_service().get_config_path(filename)
