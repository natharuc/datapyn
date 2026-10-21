"""An old installation is protected until the user explicitly disables SQL confirmation."""

import json
from pathlib import Path

import pytest

from datapyn_runtime import sql_safety_settings as settings


def test_missing_setting_is_enabled_without_creating_state(tmp_path):
    path = tmp_path / settings.FILE_NAME
    assert settings.settings_get(path) == {"confirm_destructive_sql": True}
    assert not path.exists()


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_policy_persists_and_is_read_by_a_fresh_consumer(tmp_path, enabled):
    path = tmp_path / "global" / settings.FILE_NAME
    assert settings.settings_set({"confirm_destructive_sql": enabled}, path) == {"confirm_destructive_sql": enabled}
    assert settings.settings_get(Path(str(path))) == {"confirm_destructive_sql": enabled}
    assert json.loads(path.read_text(encoding="utf-8")) == {"confirm_destructive_sql": enabled}


def test_policy_path_is_global_and_does_not_follow_workspace_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "global"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile-a"))
    path = settings.settings_path()
    settings.settings_set({"confirm_destructive_sql": False})
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile-b"))
    assert settings.settings_path() == path
    assert settings.settings_get() == {"confirm_destructive_sql": False}
    assert not (tmp_path / "profile-a").exists() and not (tmp_path / "profile-b").exists()


@pytest.mark.parametrize("value", [None, "false", "true", 0, 1, [], {}])
def test_disable_requires_an_actual_boolean_without_overwriting_saved_policy(tmp_path, value):
    path = tmp_path / settings.FILE_NAME
    settings.settings_set({"confirm_destructive_sql": True}, path)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="boolean"):
        settings.settings_set({"confirm_destructive_sql": value}, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("raw", ["{", "[]", "{}", '{"confirm_destructive_sql":"false"}', '{"confirm_destructive_sql":0}'])
def test_corrupt_or_loosely_typed_setting_never_silently_disables_protection(tmp_path, raw):
    path = tmp_path / settings.FILE_NAME
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        settings.settings_get(path)
    assert path.read_text(encoding="utf-8") == raw


def test_oversized_setting_is_rejected_before_parsing(tmp_path):
    path = tmp_path / settings.FILE_NAME
    path.write_text('{"confirm_destructive_sql":false,"extra":"' + "x" * 4096 + '"}', encoding="utf-8")
    with pytest.raises(ValueError, match="4 KiB"):
        settings.settings_get(path)


def test_failed_disk_write_keeps_the_previous_policy(tmp_path, monkeypatch):
    path = tmp_path / settings.FILE_NAME
    settings.settings_set({"confirm_destructive_sql": True}, path)
    original = path.read_bytes()
    real_write = Path.write_text

    def fail_write(destination, *args, **kwargs):
        if destination.parent == tmp_path and destination != path:
            raise OSError("fixture disk full")
        return real_write(destination, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(OSError, match="disk full"):
        settings.settings_set({"confirm_destructive_sql": False}, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
