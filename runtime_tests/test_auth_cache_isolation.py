from pathlib import Path

import pytest

from src.database import database_connector as connector


@pytest.mark.parametrize("workspace", [None, ""])
def test_legacy_entra_cache_name_is_unchanged_without_explicit_workspace(monkeypatch, workspace):
    if workspace is None:
        monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    else:
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", workspace)
    assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net:1433/sql") == (
        "datapyn_sqlserver_tenant_database_windows_net_1433_sql"
    )


def test_tauri_entra_cache_is_stable_and_distinct_from_legacy(monkeypatch, tmp_path):
    host = "tenant.database.windows.net"
    monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    legacy = connector._get_sqlserver_entra_cache_name(host)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile"))
    name = connector._get_sqlserver_entra_cache_name(host)
    assert name.startswith("datapyn_tauri_sqlserver_")
    assert name != legacy
    assert connector._get_sqlserver_entra_cache_name(host) == name
    assert not (tmp_path / "profile").exists(), "Computing a cache name must not create a profile"


def test_tauri_entra_profiles_have_distinct_encrypted_cache_names(monkeypatch, tmp_path):
    host = "tenant.database.windows.net"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "first"))
    first = connector._get_sqlserver_entra_cache_name(host)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "second"))
    assert connector._get_sqlserver_entra_cache_name(host) != first


def test_tauri_entra_cache_normalizes_equivalent_workspace_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", "profile")
    expected = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    for path in (tmp_path / "profile", tmp_path / "profile" / ".." / "profile"):
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(path))
        assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net") == expected


def test_tauri_entra_cache_normalizes_host_case_but_does_not_collide_after_sanitizing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    expected = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    assert connector._get_sqlserver_entra_cache_name(" TENANT.DATABASE.WINDOWS.NET ") == expected
    assert connector._get_sqlserver_entra_cache_name("tenant_database_windows_net") != expected
    assert connector._get_sqlserver_entra_cache_name("another.database.windows.net") != expected


def test_tauri_authentication_record_stays_in_its_own_profile(monkeypatch, tmp_path):
    workspace = tmp_path / "profile with spaces"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
    host = "tenant.database.windows.net:1433/sql"
    record = connector._get_sqlserver_auth_record_path(host)
    assert record.parent == workspace / "oauth_cache"
    assert record.name == connector._get_sqlserver_entra_cache_name(host) + "_auth_record.json"
    assert record.is_relative_to(workspace)
    assert not record.exists()


def test_browser_credential_receives_isolated_cache_without_authentication(monkeypatch, tmp_path):
    import azure.identity

    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    captured = {}

    def credential(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(azure.identity, "InteractiveBrowserCredential", credential)
    result = connector._create_sqlserver_mfa_credential("tenant.database.windows.net", "example", "tenant")
    assert result is not None
    assert captured["cache_persistence_options"].name == connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    assert captured["login_hint"] == "example"
    assert captured["tenant_id"] == "tenant"


def test_tauri_entra_cache_expands_home_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile"))
    absolute = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    # expanduser() uses the OS home environment; provide both OS conventions.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", "~/profile")
    assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net") == absolute
