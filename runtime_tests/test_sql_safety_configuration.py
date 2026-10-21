"""SQL confirmation policy is portable, global and independent of old settings."""

from datapyn_runtime.sql_safety_settings import settings_get, settings_set
from test_configuration_compatibility import transfer  # noqa: F401


def test_configuration_roundtrip_persists_explicit_sql_protection(transfer, tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    assert settings_get() == {"confirm_destructive_sql": True}
    output = tmp_path / "portable"
    transfer.export_folder({"path": str(output), "preferences": {"confirmDestructiveSql": False}})
    preview = transfer.inspect({"path": str(output)})
    assert preview["preferences"]["confirmDestructiveSql"] is False
    transfer.import_folder({"path": str(output), "preview_token": preview["preview_token"]})
    assert settings_get() == {"confirm_destructive_sql": False}


def test_importing_old_settings_cannot_silently_change_sql_policy(transfer, tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    settings_set({"confirm_destructive_sql": False})
    output = tmp_path / "portable"
    transfer.export_folder({"path": str(output), "preferences": {"theme": "light"}})
    preview = transfer.inspect({"path": str(output)})
    transfer.import_folder({"path": str(output), "preview_token": preview["preview_token"]})
    assert settings_get() == {"confirm_destructive_sql": False}
