"""Real profile files, isolation, archival and clone ID remapping in temp preview dirs."""

import json
from pathlib import Path
import sys

import pandas as pd
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from datapyn_runtime import profiles
from datapyn_runtime.session_store import DATABASE_NAME
from datapyn_runtime import variable_snapshot as snapshot
from datapyn_runtime.kernel import ResultStore


@pytest.fixture
def root(tmp_path, monkeypatch):
    profiles.close_stores()
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "preview"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "preview"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "cache"))
    yield tmp_path / "preview"
    profiles.close_stores()


def draft():
    return {"documents": [{"title": "My analysis", "filePath": "C:/data/my.dpw", "modified": True,
                           "document": {"version": "1.0", "blocks": [{"code": "SELECT 1", "language": "sql", "connection_id": "connection"}],
                                        "desktop": {"connection_id": "connection"}, "custom": {"unknown": True}}}],
            "activeIndex": 0, "preferences": {"editorFontSize": 13}, "shortcuts": {"run": "F9"}, "layout": {"leftWidth": 255}, "unknown": 42}


def test_default_profile_keeps_existing_preview_root(root):
    root.mkdir()
    (root / "connections.json").write_text('{"version":1,"groups":[],"connections":[]}')
    listed = profiles.list_profiles()
    assert listed["active_id"] == "default"
    assert listed["profiles"][0]["path"] == str(root.resolve())
    assert (root / "connections.json").exists()


def test_create_select_state_remain_isolated_and_unknown_fields_survive(root):
    profiles.save({"state": draft()})
    second = profiles.create({"name": "Second"})
    assert profiles.select({"profile_id": second["id"]})["state"] is None
    modified = draft()
    modified["preferences"] = {"editorFontSize": 20}
    profiles.save({"state": modified})
    old = profiles.select({"profile_id": "default"})["state"]
    assert old["preferences"]["editorFontSize"] == 13
    assert old["unknown"] == 42
    assert old["documents"][0]["document"]["custom"] == {"unknown": True}


def test_archive_preserves_files_and_can_be_restored(root):
    profile = profiles.create({"name": "Recoverable"})
    profiles.save({"profile_id": profile["id"], "state": draft()})
    profiles.archive({"profile_id": profile["id"]})
    assert len(profiles.list_profiles()["profiles"]) == 1
    assert Path(profile["path"], DATABASE_NAME).exists()
    profiles.archive({"profile_id": profile["id"]}, restore=True)
    assert profiles.state({"profile_id": profile["id"]})["state"]["unknown"] == 42


def test_default_and_active_profiles_cannot_be_archived(root):
    with pytest.raises(ValueError):
        profiles.archive({"profile_id": "default"})
    profile = profiles.create({"name": "Active"})
    profiles.select({"profile_id": profile["id"]})
    with pytest.raises(ValueError):
        profiles.archive({"profile_id": profile["id"]})


@pytest.mark.parametrize("identifier", ["../outside", "C:/Windows", "", ".", "a/b", "not-a-uuid"])
def test_profile_identifiers_never_escape_preview(root, identifier):
    if identifier == "":
        # Empty means the current profile for read APIs; explicit create cannot choose an ID.
        assert profiles.profile_path(identifier) == root.resolve()
    else:
        with pytest.raises((ValueError, KeyError)):
            profiles.profile_path(identifier)


def test_profile_names_are_case_insensitive_and_unique(root):
    profile = profiles.create({"name": "Production"})
    with pytest.raises(ValueError):
        profiles.create({"name": " production "})
    profiles.rename({"profile_id": profile["id"], "name": "PRODUCTION"})


def test_clone_remaps_catalog_ids_document_refs_without_reading_credentials(root, monkeypatch):
    profiles.list_profiles()
    catalog = {"version": 1, "groups": [{"id": "group", "name": "Servers", "parent_id": None}],
               "connections": [{"id": "connection", "name": "DB", "group_id": "group", "has_password": True,
                                "config": {"db_type": "sqlite", "database": ":memory:"}}]}
    (root / "connections.json").write_text(json.dumps(catalog))
    profiles.save({"state": draft()})
    class RefuseSecrets:
        def get(self, *args):
            raise AssertionError("Clone without include_credentials must not read credentials")
    import datapyn_runtime.connection_catalog
    monkeypatch.setattr(datapyn_runtime.connection_catalog, "CredentialStore", RefuseSecrets)
    clone = profiles.clone({"profile_id": "default", "name": "Cloned", "include_credentials": False})
    copied = json.loads(Path(clone["path"], "connections.json").read_text())
    identifier = copied["connections"][0]["id"]
    assert identifier != "connection"
    assert copied["groups"][0]["id"] != "group"
    assert copied["connections"][0]["group_id"] == copied["groups"][0]["id"]
    assert copied["connections"][0]["has_password"] is False
    state = profiles.state({"profile_id": clone["id"]})["state"]
    assert state["documents"][0]["document"]["blocks"][0]["connection_id"] == identifier
    assert state["documents"][0]["document"]["desktop"]["connection_id"] == identifier
    assert json.loads((root / "connections.json").read_text()) == catalog


def test_clone_copies_parquet_and_updates_workspace_ownership(root, monkeypatch):
    profiles.list_profiles()
    snapshot.settings_set({"settings": {"enabled": True}})
    store = ResultStore(pd, pl)
    snapshot.save({"session_id": "session-1"}, {"df": pd.DataFrame({"x": [123]})}, store)
    copied = profiles.clone({"profile_id": "default", "name": "With data"})
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", copied["path"])
    namespace = {}
    result = snapshot.restore({"session_id": "session-1"}, namespace, store)
    assert result["restored"] is True
    assert namespace["df"].iat[0, 0] == 123


def test_invalid_state_keeps_existing_draft_atomic(root):
    profiles.save({"state": draft()})
    with pytest.raises(ValueError):
        profiles.save({"state": {"documents": ["invalid"]}})
    assert profiles.state()["state"]["unknown"] == 42


def test_patch_reopen_clone_and_archive_preserve_private_editor_state(root):
    document = draft()
    document["documents"][0]["sessionId"] = "session-stable"
    document["documents"][0]["editorViewState"] = {"block-1": {"cursorState": [8, 2]}}
    saved = profiles.save({"state": document})
    edited = profiles.dispatch("workspace.profiles.patch", {"profile_id": "default", "upserts": [{"sessionId": "session-stable", "title": "Focused title"}], "metadata": {"unknown": 123}})
    assert edited["revision"] > saved["revision"] and edited["changed_payloads"] == 0
    profiles.close_stores()
    restored = profiles.state()["state"]
    assert restored["documents"][0]["title"] == "Focused title"
    assert restored["documents"][0]["editorViewState"] == document["documents"][0]["editorViewState"]
    clone = profiles.clone({"name": "SQLite clone"})
    cloned = profiles.state({"profile_id": clone["id"]})["state"]
    assert cloned["documents"] == restored["documents"] and cloned["unknown"] == 123
    assert Path(clone["path"], DATABASE_NAME).is_file() and not Path(clone["path"], "workspace_state.json").exists()
    profiles.archive({"profile_id": clone["id"]})
    profiles.archive({"profile_id": clone["id"]}, restore=True)
    assert profiles.select({"profile_id": clone["id"]})["state"]["documents"] == restored["documents"]


def test_select_corrupt_profile_keeps_previous_active_registry(root):
    profiles.save({"state": draft()})
    profile = profiles.create({"name": "Damaged"})
    Path(profile["path"], DATABASE_NAME).write_bytes(b"not SQLite")
    with pytest.raises(ValueError, match="storage"):
        profiles.select({"profile_id": profile["id"]})
    assert profiles.list_profiles()["active_id"] == "default"
    assert profiles.state()["state"]["unknown"] == 42


def test_clone_copies_sanitized_compatibility_files_and_preserves_unknown_values(root):
    profiles.list_profiles()
    configuration = root / ".pyqt-configuration"
    configuration.mkdir()
    content = b"[custom]\nunknownFlag=still-here\n"
    (configuration / "PyniaSettings.ini").write_bytes(content)
    (configuration / "unknown.json").write_text('{"unrecognized":{"nested":17}}')
    (configuration / "NotificationSecrets.ini").write_text("never copy")
    (configuration / "Workspaces.ini").write_text("never copy")
    (configuration / "notes.txt").write_text("not configuration")
    clone = profiles.clone({"name": "With settings"})
    target = Path(clone["path"]) / ".pyqt-configuration"
    assert sorted(file.name for file in target.iterdir()) == ["PyniaSettings.ini", "unknown.json"]
    assert (target / "PyniaSettings.ini").read_bytes() == content
    assert json.loads((target / "unknown.json").read_text())["unrecognized"]["nested"] == 17


def test_clone_preserves_private_configuration_defaults_without_changing_session_metadata(root):
    from datapyn_runtime.configuration_defaults import load_defaults

    profiles.save({"state": draft()})
    before = profiles.state()
    defaults = {"export_settings": {"delimiter": "|", "decimal": ",", "encoding": "cp1252", "include_header": False, "open_folder": False},
                "copy_separator": ";", "copy_null_display": "NULL", "export_open_folder": False,
                "pynia": {"default_agent_id": "codex", "model_id": "selected-model", "thought_level": "high",
                          "agent_prefs": {"codex": {"model_id": "agent-model", "thought_level": "medium"}}}}
    document = {"version": 1, "defaults": defaults, "unknown_future_field": {"preserved": "áβ"}}
    # Use the same UTF-8/indentation as the backend's canonical configuration writer.
    content = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    (root / "configuration_defaults.json").write_bytes(content)

    clone = profiles.clone({"name": "With private defaults"})
    target = Path(clone["path"])
    assert (target / "configuration_defaults.json").read_bytes() == content
    assert load_defaults(target) == defaults
    after = profiles.state()
    assert after["revision"] == before["revision"] and after["state"] == before["state"]
    assert profiles.state({"profile_id": clone["id"]})["state"]["preferences"] == before["state"]["preferences"]
