"""
Tests for WorkspaceService - workspace/profile management system.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QSettings


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def temp_workspace(temp_dir):
    """Create a temp workspace folder."""
    workspace = temp_dir / "test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def workspace_service():
    """
    Get the WorkspaceService singleton.
    """
    from src.core.workspace_service import get_workspace_service
    return get_workspace_service()


@pytest.fixture
def clean_workspace_list():
    """
    Save and restore workspace list around tests.
    Returns the settings object for direct manipulation.
    """
    settings = QSettings("DataPyn", "Workspaces")
    
    # Save original values
    original_list = settings.value("workspace_list", []) or []
    
    yield settings
    
    # Restore original values after test
    settings.setValue("workspace_list", original_list)


# ==============================================================================
# TEST SINGLETON BEHAVIOR
# ==============================================================================


class TestWorkspaceServiceSingleton:
    """Tests for singleton pattern."""
    
    def test_singleton_returns_same_instance(self, workspace_service):
        """get_workspace_service should always return the same instance."""
        from src.core.workspace_service import get_workspace_service
        
        service1 = get_workspace_service()
        service2 = get_workspace_service()
        
        assert service1 is service2
        assert service1 is workspace_service
    
    def test_direct_instantiation_creates_new_instance(self, workspace_service):
        """Direct WorkspaceService() calls create new instances - use get_workspace_service()."""
        from src.core.workspace_service import WorkspaceService
        
        # Note: With module-level singleton, direct instantiation creates new instances.
        # This is intentional - users should use get_workspace_service() for singleton behavior.
        ws1 = WorkspaceService()
        ws2 = WorkspaceService()
        
        # They are different instances (direct instantiation doesn't use singleton)
        assert ws1 is not ws2
        
        # But get_workspace_service() always returns the same singleton
        assert workspace_service is not ws1
        assert workspace_service is not ws2


# ==============================================================================
# TEST WORKSPACE PROPERTIES
# ==============================================================================


class TestWorkspaceProperties:
    """Tests for workspace properties."""
    
    def test_current_workspace_is_path(self, workspace_service):
        """current_workspace should be a Path object."""
        assert isinstance(workspace_service.current_workspace, Path)
    
    def test_current_workspace_name_is_string(self, workspace_service):
        """current_workspace_name should be a string."""
        assert isinstance(workspace_service.current_workspace_name, str)
        assert len(workspace_service.current_workspace_name) > 0
    
    def test_is_default_workspace_returns_bool(self, workspace_service):
        """is_default_workspace should return a boolean."""
        assert isinstance(workspace_service.is_default_workspace, bool)
    
    def test_workspace_folder_exists(self, workspace_service):
        """Workspace folder should exist."""
        assert workspace_service.current_workspace.exists()
        assert workspace_service.current_workspace.is_dir()


# ==============================================================================
# TEST CONFIG PATH HELPERS
# ==============================================================================


class TestConfigPathHelpers:
    """Tests for get_config_path and get_config_dir."""
    
    def test_get_config_path_returns_path_in_workspace(self, workspace_service):
        """get_config_path should return path in workspace folder."""
        config_path = workspace_service.get_config_path("connections.json")
        
        assert config_path.parent == workspace_service.current_workspace
        assert config_path.name == "connections.json"
    
    def test_get_config_path_different_files(self, workspace_service):
        """get_config_path should work for different file names."""
        paths = [
            workspace_service.get_config_path("connections.json"),
            workspace_service.get_config_path("workspace.json"),
            workspace_service.get_config_path("sessions.json"),
        ]
        
        # All should be different
        assert len(set(paths)) == 3
    
    def test_get_config_dir_creates_directory(self, workspace_service, temp_dir):
        """get_config_dir should create the directory if it doesn't exist."""
        # Use a unique dir name to avoid conflicts with other tests
        unique_name = f"test_dir_{id(temp_dir)}"
        dir_path = workspace_service.get_config_dir(unique_name)
        
        assert dir_path.parent == workspace_service.current_workspace
        assert dir_path.name == unique_name
        assert dir_path.exists()
        assert dir_path.is_dir()
        
        # Cleanup
        dir_path.rmdir()
    
    def test_get_config_dir_returns_existing(self, workspace_service, temp_dir):
        """get_config_dir should work for existing directories."""
        unique_name = f"test_existing_{id(temp_dir)}"
        
        # Create first
        dir1 = workspace_service.get_config_dir(unique_name)
        
        # Call again
        dir2 = workspace_service.get_config_dir(unique_name)
        
        assert dir1 == dir2
        assert dir1.exists()
        
        # Cleanup
        dir1.rmdir()


# ==============================================================================
# TEST WORKSPACE MANAGEMENT
# ==============================================================================


class TestWorkspaceManagement:
    """Tests for add, remove, list, switch workspace operations."""
    
    def test_list_workspaces_includes_default(self, workspace_service):
        """list_workspaces should include default workspace."""
        workspaces = workspace_service.list_workspaces()
        
        assert len(workspaces) >= 1
        # First should be Default
        assert workspaces[0][0] == "Default"
    
    def test_add_workspace(self, workspace_service, temp_workspace, clean_workspace_list):
        """add_workspace should add a new workspace to the list."""
        result = workspace_service.add_workspace(temp_workspace)
        
        assert result is True
        
        workspaces = workspace_service.list_workspaces()
        workspace_paths = [ws[1] for ws in workspaces]
        assert temp_workspace.resolve() in [p.resolve() if hasattr(p, 'resolve') else Path(p).resolve() for p in workspace_paths]
        
        # Cleanup
        workspace_service.remove_workspace(temp_workspace)
    
    def test_add_workspace_creates_folder(self, workspace_service, temp_dir, clean_workspace_list):
        """add_workspace should create folder if it doesn't exist."""
        new_workspace = temp_dir / "new_folder_to_create"
        assert not new_workspace.exists()
        
        result = workspace_service.add_workspace(new_workspace)
        
        assert result is True
        assert new_workspace.exists()
        
        # Cleanup
        workspace_service.remove_workspace(new_workspace)
        new_workspace.rmdir()
    
    def test_add_default_workspace_fails(self, workspace_service):
        """Cannot add default workspace path again."""
        from src.core.workspace_service import DEFAULT_WORKSPACE_PATH
        
        result = workspace_service.add_workspace(DEFAULT_WORKSPACE_PATH)
        
        assert result is False
    
    def test_add_workspace_duplicate(self, workspace_service, temp_workspace, clean_workspace_list):
        """Adding same workspace twice should not duplicate."""
        workspace_service.add_workspace(temp_workspace)
        workspace_service.add_workspace(temp_workspace)
        
        workspaces = workspace_service.list_workspaces()
        # Count occurrences of this path
        count = sum(1 for _, path in workspaces if Path(path).resolve() == temp_workspace.resolve())
        assert count == 1
        
        # Cleanup
        workspace_service.remove_workspace(temp_workspace)
    
    def test_remove_workspace(self, workspace_service, temp_workspace, clean_workspace_list):
        """remove_workspace should remove from list but keep files."""
        workspace_service.add_workspace(temp_workspace)
        
        result = workspace_service.remove_workspace(temp_workspace)
        
        assert result is True
        
        workspaces = workspace_service.list_workspaces()
        workspace_paths = [Path(ws[1]).resolve() for ws in workspaces]
        assert temp_workspace.resolve() not in workspace_paths
        
        # Folder should still exist
        assert temp_workspace.exists()
    
    def test_remove_default_workspace_fails(self, workspace_service):
        """Cannot remove default workspace."""
        from src.core.workspace_service import DEFAULT_WORKSPACE_PATH
        
        result = workspace_service.remove_workspace(DEFAULT_WORKSPACE_PATH)
        
        assert result is False
    
    def test_remove_nonexistent_workspace(self, workspace_service, temp_dir):
        """Removing non-listed workspace should return False."""
        fake_workspace = temp_dir / "never_added"
        
        result = workspace_service.remove_workspace(fake_workspace)
        
        assert result is False


# ==============================================================================
# TEST SWITCH WORKSPACE
# ==============================================================================


class TestSwitchWorkspace:
    """Tests for workspace switching."""
    
    def test_switch_workspace_emits_signal(self, workspace_service, temp_workspace, clean_workspace_list):
        """switch_workspace should emit signal."""
        # Connect to signal
        signal_received = []
        workspace_service.workspace_changed.connect(
            lambda path: signal_received.append(path)
        )
        
        result = workspace_service.switch_workspace(temp_workspace)
        
        assert result is True
        assert len(signal_received) == 1
        assert signal_received[0] == str(temp_workspace.resolve())
        
        # Cleanup - switch back to current workspace won't work since it thinks we're already there
        # Just restore settings directly
        clean_workspace_list.remove("current_workspace")
    
    def test_switch_to_same_workspace_returns_false(self, workspace_service):
        """Switching to current workspace should return False."""
        current = workspace_service.current_workspace
        
        result = workspace_service.switch_workspace(current)
        
        assert result is False


# ==============================================================================
# TEST QSETTINGS HELPERS
# ==============================================================================


class TestQSettingsHelpers:
    """Tests for workspace-scoped QSettings."""
    
    def test_get_workspace_settings_returns_qsettings(self, workspace_service):
        """get_workspace_settings should return QSettings instance."""
        settings = workspace_service.get_workspace_settings("TestApp")
        
        assert isinstance(settings, QSettings)
    
    def test_get_workspace_settings_uses_ini_format(self, workspace_service):
        """Workspace settings should use INI file in workspace folder."""
        settings = workspace_service.get_workspace_settings("MyTestSettings")
        
        # The QSettings path should have .ini extension and be in workspace
        assert ".ini" in settings.fileName()
        assert "MyTestSettings" in settings.fileName()


# ==============================================================================
# TEST CONVENIENCE FUNCTIONS
# ==============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_workspace_path(self, workspace_service):
        """get_workspace_path should return current workspace path."""
        from src.core.workspace_service import get_workspace_path
        
        path = get_workspace_path()
        
        assert path == workspace_service.current_workspace
    
    def test_get_config_path_function(self, workspace_service):
        """get_config_path function should return config file path."""
        from src.core.workspace_service import get_config_path
        
        path = get_config_path("test.json")
        
        expected = workspace_service.current_workspace / "test.json"
        assert path == expected
