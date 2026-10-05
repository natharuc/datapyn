"""Storage identity must stay independent of PyQt and of the preview build."""

from pathlib import Path

import pytest

from datapyn_runtime import paths, profiles, variable_snapshot, notifications
from datapyn_runtime.connection_catalog import ConnectionCatalog, CredentialStore


@pytest.mark.parametrize("platform,environment,expected", [
    ("win32", "LOCALAPPDATA", "app.datapyn.tauri"),
    ("linux", "XDG_DATA_HOME", "app.datapyn.tauri"),
])
def test_platform_data_directory(monkeypatch, tmp_path, platform, environment, expected):
    monkeypatch.delenv("DATAPYN_RUNTIME_STATE_PATH", raising=False)
    monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setenv(environment, str(tmp_path))
    assert paths.state_root() == tmp_path / expected
    assert paths.workspace_root() == paths.state_root()
    assert ".datapyn" not in paths.state_root().parts


def test_macos_native_directories(monkeypatch, tmp_path):
    monkeypatch.delenv("DATAPYN_RUNTIME_STATE_PATH", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.state_root() == tmp_path / "Library" / "Application Support" / paths.APP_ID
    assert paths.cache_root() == tmp_path / "Library" / "Caches" / paths.APP_ID / "cache"


def test_workspace_and_snapshot_overrides_are_shared(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state" / "profiles" / "test"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    assert profiles.base_path() == tmp_path / "state"
    workspace = paths.workspace_root()
    assert ConnectionCatalog().path == workspace / "connections.json"
    assert notifications._workspace() == workspace
    assert variable_snapshot._workspace() == workspace
    assert variable_snapshot._root() == profiles._snapshot_root(workspace)
    assert CredentialStore.service == "DataPyn.Tauri.Connections"
    assert notifications._secret_service().startswith("DataPyn.Tauri.notifications.")
