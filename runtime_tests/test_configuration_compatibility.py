"""Bidirectional interoperability with the actual PyQt6 readers/writers.

All QSettings files and keyring operations are confined to temporary fixtures.
No default WorkspaceService or platform QSettings constructor is invoked.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.configurations import ConfigurationTransfer
from datapyn_runtime.legacy_settings import (SHORTCUT_DEFAULTS, ini_values, patch_ini,
                                            preferences_from_ini, strip_ini_secrets)
from test_connection_catalog import Secrets


@pytest.fixture(autouse=True)
def temporary_keyring(monkeypatch):
    import keyring
    values = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: values.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: values.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: values.pop((service, name), None))


@pytest.fixture
def native_api():
    from src.language import init_language
    from src.database.connection_manager import ConnectionManager
    from src.ui.dialogs.connection_import_export_dialog import export_connections, validate_import_json, apply_import
    init_language("pt-BR")
    return ConnectionManager, export_connections, validate_import_json, apply_import


@pytest.fixture
def transfer(tmp_path):
    workspace = tmp_path / "preview"
    catalog = ConnectionCatalog(workspace / "connections.json", Secrets())
    return ConfigurationTransfer(workspace, catalog)


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def fixture_connections():
    def config(group):
        return {"db_type": "postgresql", "host": "localhost", "port": 5432, "database": "analytics", "username": "reader",
                "group": group, "schema": "public", "color": "#5a8dee", "favorite": True, "order": 4,
                "created_at": "2020-01-01T00:00:00", "last_used": "2021-01-01T00:00:00",
                "vendor": {"array": [1, "á", None], "keep": True}, "password": "fixture-password"}
    return {"connections": {"Empty": {}, "Prod": {"Same": config("Prod"), "same": config("Prod")},
                            "QA": {"Same": config("QA")}, "": {}},
            "groups": {"Prod": {"color": "#123", "parent": "", "created_at": "2019", "custom": {"x": 2}},
                       "QA": {"parent": "Prod", "color": "#456"}, "Empty": {"parent": "", "unknown": [1, 2]}},
            "plugin": {"version": 17, "unsupported": True}}


def test_native_export_tauri_import_export_native_reader_preserves_metadata(native_api, transfer, tmp_path):
    Manager, native_export, validate, apply = native_api
    original = tmp_path / "original.json"
    write_json(original, fixture_connections())
    native = Manager(config_path=original)
    public = native_export(native)
    path = tmp_path / "public.json"
    write_json(path, public)
    transfer.catalog.import_file(str(path))
    exported = tmp_path / "tauri-to-pyqt.json"
    transfer.catalog.dispatch("connections.export", {"path": str(exported)})
    document, error = validate(exported.read_text(encoding="utf-8"))
    assert error is None
    target = Manager(config_path=tmp_path / "legacy-target.json")
    assert apply(target, document) == 3
    assert {ref.name for ref in target.get_saved_connections()} == {"Same", "same"}
    assert len(target.get_saved_connections()) == 3
    for group, name, config in target.iter_saved_connections():
        assert config["host"] == "localhost" and config["port"] == 5432
        assert config["schema"] == "public" and "password" not in config
    # Direct native loader retains extensions that the old dialog's whitelist
    # intentionally discards when recreating connection objects.
    reloaded = Manager(config_path=exported)
    roundtrip = native_export(reloaded)
    assert roundtrip["groups"]["Prod"]["custom"] == {"x": 2}
    assert roundtrip["groups"]["Empty"]["unknown"] == [1, 2]
    assert roundtrip["connections"]["Empty"] == {} and roundtrip["connections"][""] == {}
    for group in ("Prod", "QA"):
        config = roundtrip["connections"][group]["Same"]
        assert config["vendor"] == public["connections"][group]["Same"]["vendor"]
        assert config["created_at"] == "2020-01-01T00:00:00" and config["last_used"] == "2021-01-01T00:00:00"
        assert config["order"] == 4 and config["favorite"] is True
    assert "fixture-password" not in exported.read_text()


def test_exact_ref_overwrite_and_top_level_unknowns_remain(native_api, transfer, tmp_path):
    path = tmp_path / "full.json"
    document = fixture_connections()
    write_json(path, document)
    transfer.catalog.import_file(str(path))
    before = {item["name"] + str(item["group_id"]): item["id"] for item in transfer.catalog.data["connections"]}
    document["groups"]["Prod"]["custom"]["x"] = 9
    document["connections"]["Prod"]["Same"]["database"] = "replacement"
    write_json(path, document)
    transfer.catalog.import_file(str(path))
    after = {item["name"] + str(item["group_id"]): item["id"] for item in transfer.catalog.data["connections"]}
    assert before == after
    result = transfer.catalog.export_document()
    assert result["connections"]["Prod"]["Same"]["database"] == "replacement"
    assert result["groups"]["Prod"]["custom"]["x"] == 9
    assert result["plugin"] == document["plugin"]
    assert transfer.catalog.credentials.values == {}


def test_native_no_group_export_is_valid_for_both_dialog_and_manager(native_api, transfer, tmp_path):
    Manager, _, validate, apply = native_api
    transfer.catalog.save_connection({"name": "db", "config": {"db_type": "postgresql", "database": "db"}})
    document = transfer.catalog.export_document()
    assert document["groups"] == {}
    parsed, error = validate(json.dumps(document))
    assert error is None
    path = tmp_path / "native.json"
    write_json(path, document)
    assert len(Manager(config_path=path).get_saved_connections()) == 1
    assert apply(Manager(config_path=tmp_path / "ui-import.json"), parsed) == 1


def test_only_empty_group_buckets_export_accepts_the_real_legacy_dialog(native_api, transfer, tmp_path):
    Manager, _, validate, apply = native_api
    transfer.catalog.import_document({"connections": {"Empty": {}, "": {}}, "groups": {"Empty": {"parent": "", "custom": "keep"}}})
    document = transfer.catalog.export_document()
    assert document["connections"] == {} and document["groups"]["Empty"]["custom"] == "keep"
    parsed, error = validate(json.dumps(document))
    assert error is None
    target = Manager(config_path=tmp_path / "target.json")
    assert apply(target, parsed) == 0 and "Empty" in target.get_groups()


def test_ambiguous_tauri_group_names_are_explicitly_not_silently_flattened(transfer):
    first = transfer.catalog.save_group({"name": "First"})
    second = transfer.catalog.save_group({"name": "Second"})
    transfer.catalog.save_group({"name": "Same", "parent_id": first["id"]})
    with pytest.raises(ValueError, match="globally unique"):
        transfer.catalog.save_group({"name": "Same", "parent_id": second["id"]})
    # Historical preview catalogs can still be loaded without losing these
    # previously allowed folders; only their public export requires a rename.
    transfer.catalog.data["groups"].append({"id": "old-duplicate", "name": "Same", "parent_id": second["id"], "order": 4})
    with pytest.raises(ValueError, match="globally unique"):
        transfer.catalog.export_document()
    assert len(transfer.catalog.export_document("tauri")["groups"]) == 4


def create_native_ini(path, values):
    from PyQt6.QtCore import QSettings
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()
    assert settings.status() == QSettings.Status.NoError
    return settings


def test_qt_ini_known_scalars_and_opaque_variants_survive_both_directions(tmp_path):
    from PyQt6.QtCore import QByteArray, QSize, QRect, QSettings
    path = tmp_path / "DataPyn.ini"
    known = {"language": "pt-BR", "editor/code_font_size": 18, "results/grid_font_size": 11,
             "grid/display_row_limit": 345, "notifications/enabled": False, "parameters/shared_delimiter": "::name::"}
    unknown = {"opaque/bytes": QByteArray(b"\x00\x01\xffhello"), "opaque/rect": QRect(4, 5, 6, 7),
               "opaque/size": QSize(120, 99), "opaque/list": ["a,b", "á", "x=y"],
               "custom/ação": "path \\ with\nquotes \";,=@ value"}
    create_native_ini(path, {**known, **unknown})
    raw = path.read_bytes()
    parsed = preferences_from_ini(raw)
    assert parsed == {"locale": "pt-BR", "editorFontSize": 18, "gridFontSize": 11, "displayRowLimit": 345,
                      "notifications": False, "sharedDelimiter": "::name::"}
    patched = patch_ini(raw, {"editor/code_font_size": 20, "notifications/success_message": "á,=;\n\\hello",
                              "new_group/boolean": True})
    other = tmp_path / "output.ini"
    other.write_bytes(patched)
    qt = QSettings(str(other), QSettings.Format.IniFormat)
    for key, value in unknown.items():
        assert qt.value(key) == value
    assert qt.value("editor/code_font_size", type=int) == 20
    assert qt.value("notifications/success_message") == "á,=;\n\\hello"
    assert qt.value("new_group/boolean", type=bool) is True
    for line in raw.splitlines(keepends=True):
        if b"code_font_size=" not in line:
            assert line in patched


def test_native_shortcut_manager_round_trip_preserves_unknown_action_and_defaults(transfer, tmp_path):
    from src.core.shortcut_manager import ShortcutManager
    assert SHORTCUT_DEFAULTS == ShortcutManager.DEFAULT_SHORTCUTS
    source = tmp_path / "native"
    source.mkdir()
    manager = ShortcutManager(source / "shortcuts.json")
    manager.update_shortcuts({"execute_sql": "Ctrl+Return", "new_tab": "", "vendor_unknown_action": "Alt+F9"})
    document = json.loads((source / "shortcuts.json").read_text())
    document["extension"] = {"revision": 5}
    write_json(source / "shortcuts.json", document)
    preview = transfer.inspect({"path": str(source)})
    assert preview["shortcuts"]["run"] == "Ctrl+Enter" and preview["shortcuts"]["newTab"] == ""
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    output = tmp_path / "out"
    transfer.export_folder({"path": str(output), "shortcuts": {**preview["shortcuts"], "run": "Alt+Enter"}})
    native = ShortcutManager(output / "shortcuts.json")
    assert native.get_shortcut("execute_sql") == "Alt+Return"
    assert native.get_shortcut("vendor_unknown_action") == "Alt+F9" and native.get_shortcut("new_tab") == ""
    assert json.loads((output / "shortcuts.json").read_text())["extension"] == {"revision": 5}


def test_folder_preview_import_export_preserves_bytes_excludes_sessions_and_credentials(transfer, tmp_path):
    from PyQt6.QtCore import QByteArray
    source = tmp_path / "native"
    source.mkdir()
    create_native_ini(source / "MainWindow.ini", {"geometry": QByteArray(b"\x00\x04\xfflayout"), "vendor/unknown": "á"})
    create_native_ini(source / "PyniaSettings.ini", {"autocomplete_enabled": "true", "default_agent_id": "copilot", "custom/keep": "yes"})
    create_native_ini(source / "DataPyn.ini", {"language": "en-US", "editor/code_font_size": 16,
        "notifications/enabled": True, "notifications/email/host": "smtp.example.invalid", "notifications/email/from": "fixture@example.invalid",
        "notifications/email/to": "one@example.invalid; two@example.invalid", "session_results/enabled": True, "session_results/max_size_mb": 75})
    (source / "vendor.ini").write_bytes(b"[General]\r\nkeep=@ByteArray(\\x0\\xff)\r\n; custom comment\r\n")
    unknown = b'[ { "path": "C:/fixture/sql.sql", "vendor": [1, 2] } ]\n'
    (source / "recent_files.json").write_bytes(unknown)
    write_json(source / "sessions.json", {"must": "not migrate"})
    write_json(source / "workspace.json", {"must": "not migrate"})
    create_native_ini(source / "NotificationSecrets.ini", {"email_password": "fixture-secret"})
    preview = transfer.inspect({"path": str(source)})
    assert preview["preferences"]["editorFontSize"] == 16 and preview["preferences"]["aiAutocomplete"] is True
    assert {"sessions.json", "workspace.json", "NotificationSecrets.ini"} <= set(preview["excluded_files"])
    assert not transfer.workspace.exists()
    imported = transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert imported["notification_settings"]["email"]["to"].startswith("one@")
    assert imported["snapshot_settings"]["max_size_mb"] == 75
    target = tmp_path / "out"
    result = transfer.export_folder({"path": str(target)})
    for name in ("MainWindow.ini", "PyniaSettings.ini", "vendor.ini", "recent_files.json"):
        assert (source / name).read_bytes() == (target / name).read_bytes()
    assert not (target / "sessions.json").exists() and not (target / "NotificationSecrets.ini").exists()
    assert result["passwords_included"] is False and any("Registry" in value for value in result["warnings"])


def test_secrets_removed_from_nested_json_and_qt_ini_and_never_read_keyring(transfer, tmp_path):
    source = tmp_path / "native"
    source.mkdir()
    create_native_ini(source / "PackageManager.ini", {"sources_v2": [{"url": "https://example.invalid", "password": "fixture-secret"}], "custom/keep": "y"})
    create_native_ini(source / "DataPyn.ini", {"notifications/email/password": "fixture-secret", "plugin/token": "fixture-secret", "language": "pt-BR"})
    write_json(source / "extra.json", {"vendor": {"password": "fixture-secret", "keep": True}})
    preview = transfer.inspect({"path": str(source)})
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    output = tmp_path / "out"
    transfer.export_folder({"path": str(output)})
    assert all(b"fixture-secret" not in file.read_bytes() for file in output.iterdir())
    assert ini_values((output / "PackageManager.ini").read_bytes())["custom/keep"] == "y"
    assert "sources_v2" not in ini_values((output / "PackageManager.ini").read_bytes())
    assert json.loads((output / "extra.json").read_text()) == {"vendor": {"keep": True}}


def test_preview_is_required_and_source_or_catalog_change_invalidates_it(transfer, tmp_path):
    source = tmp_path / "native"
    source.mkdir()
    write_json(source / "shortcuts.json", {"shortcuts": {}})
    with pytest.raises(ValueError, match="preview"):
        transfer.import_folder({"path": str(source)})
    preview = transfer.inspect({"path": str(source)})
    write_json(source / "shortcuts.json", {"shortcuts": {"execute_sql": "F8"}})
    with pytest.raises(ValueError, match="stale"):
        transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    preview = transfer.inspect({"path": str(source)})
    transfer.catalog.save_group({"name": "Changed"})
    with pytest.raises(ValueError, match="stale"):
        transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})


def test_invalid_configuration_validated_before_any_import_mutation(transfer, tmp_path):
    source = tmp_path / "native"
    source.mkdir()
    write_json(source / "connections.json", fixture_connections())
    create_native_ini(source / "DataPyn.ini", {"notifications/email/port": "bad-number"})
    before = transfer.catalog.list()
    with pytest.raises(ValueError):
        transfer.inspect({"path": str(source)})
    assert transfer.catalog.list() == before and not transfer.workspace.exists()


def test_import_write_failure_rolls_back_all_files_and_in_memory_catalog(transfer, tmp_path, monkeypatch):
    transfer.catalog.save_group({"name": "Previous"})
    transfer.archive.mkdir()
    (transfer.archive / "old.ini").write_bytes(b"[General]\nkeep=previous\n")
    source = tmp_path / "native"
    source.mkdir()
    write_json(source / "connections.json", fixture_connections())
    create_native_ini(source / "DataPyn.ini", {"notifications/enabled": False})
    preview = transfer.inspect({"path": str(source)})
    before = {str(path): path.read_bytes() for path in transfer.workspace.rglob("*") if path.is_file()}
    before_data = transfer.catalog.list()
    real_write = transfer._write
    failures = []
    def fail_once(path, raw):
        if path.name == "notifications.json" and not failures:
            failures.append(path)
            raise OSError("simulated disk failure")
        real_write(path, raw)
    monkeypatch.setattr(transfer, "_write", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    after = {str(path): path.read_bytes() for path in transfer.workspace.rglob("*") if path.is_file()}
    assert before == after and before_data == transfer.catalog.list()


def test_export_does_not_overwrite_nonempty_folder_and_frontend_only_preferences_roundtrip(transfer, tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    (target / "important").write_text("preserve")
    with pytest.raises(ValueError, match="empty"):
        transfer.export_folder({"path": str(target)})
    target = tmp_path / "portable"
    preferences = {"theme": "light", "uiFont": "Ubuntu", "gridFontSize": 12, "editorFontSize": 14, "wordWrap": True}
    transfer.export_folder({"path": str(target), "preferences": preferences})
    other = ConfigurationTransfer(tmp_path / "other", ConnectionCatalog(tmp_path / "other" / "connections.json", Secrets()))
    assert other.inspect({"path": str(target)})["preferences"] == preferences


def test_real_legacy_notification_reader_accepts_exported_ini(transfer, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    from src.services import notification_delivery_service as legacy
    source = tmp_path / "native"
    source.mkdir()
    create_native_ini(source / "DataPyn.ini", {"notifications/enabled": False, "notifications/email/host": "smtp.invalid", "notifications/email/port": 2525,
                                             "notifications/email/from": "one@invalid", "notifications/email/to": "two@invalid;three@invalid"})
    preview = transfer.inspect({"path": str(source)})
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    target = tmp_path / "output"
    transfer.export_folder({"path": str(target)})
    monkeypatch.setattr(legacy, "QSettings", lambda *args: QSettings(str(target / "DataPyn.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(legacy, "get_notification_secret", lambda name: "")
    actual = legacy.load_notification_transport_settings()
    assert actual["notifications_enabled"] is False and actual["email"]["host"] == "smtp.invalid"
    assert actual["email"]["port"] == 2525 and actual["email"]["recipients"] == ["two@invalid", "three@invalid"]


def test_real_pynia_settings_manager_can_read_exported_workspace_ini(transfer, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    from src.services.pynia.settings import PyniaSettingsManager
    from src.core import workspace_service
    source = tmp_path / "native"
    source.mkdir()
    create_native_ini(source / "PyniaSettings.ini", {"default_agent_id": "copilot", "autocomplete_enabled": "false",
                                                  "agent_prefs/copilot/model_id": "fixture-model", "agent_prefs/copilot/thought_level": "high"})
    preview = transfer.inspect({"path": str(source)})
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    target = tmp_path / "output"
    transfer.export_folder({"path": str(target), "preferences": {"aiAutocomplete": True}})
    class TemporaryWorkspace:
        current_workspace = target
        def get_workspace_settings(self, category):
            return QSettings(str(target / f"{category}.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(workspace_service, "get_workspace_service", lambda: TemporaryWorkspace())
    monkeypatch.setattr(PyniaSettingsManager, "_instance", None)
    settings = PyniaSettingsManager()
    assert settings.default_agent_id == "copilot" and settings.autocomplete_enabled is True
    assert settings.agent_model_id("copilot") == "fixture-model" and settings.agent_thought_level("copilot") == "high"


def test_crlf_unknown_bytes_remain_exact_and_secrets_are_removed():
    raw = b"[General]\r\ncustom=@Variant(\\0\\xff)\r\npassword=fixture-secret\r\n[plugin]\r\ntoken=fixture-secret\r\nunknown=@@literal\r\n"
    expected = raw.replace(b"password=fixture-secret\r\n", b"").replace(b"token=fixture-secret\r\n", b"")
    assert strip_ini_secrets(raw) == expected
    assert patch_ini(raw, {}) == expected


def test_repeated_ini_keys_all_receive_the_updated_scalar(tmp_path):
    from PyQt6.QtCore import QSettings
    raw = b"[editor]\r\ncode_font_size=13\r\nkeep=x\r\n[editor]\r\ncode_font_size=14\r\n"
    patched = patch_ini(raw, {"editor/code_font_size": 17})
    assert patched.count(b"code_font_size=17") == 2 and b"keep=x\r\n" in patched
    path = tmp_path / "DataPyn.ini"
    path.write_bytes(patched)
    qt = QSettings(str(path), QSettings.Format.IniFormat)
    assert qt.value("editor/code_font_size", type=int) == 17


def test_new_groups_always_have_a_public_export_and_names_are_case_sensitive(transfer):
    parent = transfer.catalog.save_group({"name": "Parent"})
    transfer.catalog.save_group({"name": "Reports", "parent_id": parent["id"]})
    with pytest.raises(ValueError, match="globally unique"):
        transfer.catalog.save_group({"name": "Reports"})
    transfer.catalog.save_group({"name": "reports"})
    transfer.catalog.save_connection({"name": "DB", "config": {"db_type": "postgresql", "database": "db"}})
    transfer.catalog.save_connection({"name": "db", "config": {"db_type": "postgresql", "database": "db"}})
    result = transfer.catalog.export_document()
    assert set(result["groups"]) == {"Parent", "Reports", "reports"}
    assert set(result["connections"][""]) == {"DB", "db"}


def test_stdio_configuration_transfer_busy_guard_and_runtime_stays_qt_free(tmp_path, monkeypatch):
    from test_runtime import Client
    source = tmp_path / "native"
    source.mkdir()
    write_json(source / "connections.json", fixture_connections())
    write_json(source / "shortcuts.json", {"shortcuts": {"execute_sql": "F8"}})
    create_native_ini(source / "DataPyn.ini", {"editor/code_font_size": 17})
    runtime_path = tmp_path / "runtime-state"
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(runtime_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(runtime_path))
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path / "runtime-data"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    client = Client()
    try:
        preview = client.request("configurations.inspect", {"path": str(source)})
        assert preview["preferences"]["editorFontSize"] == 17 and preview["shortcuts"]["run"] == "F8"
        client.session()
        client.request("execution.run", {"session_id": "a", "execution_id": "busy", "language": "python",
                                          "code": "import time\ntime.sleep(30)"})
        client.event("execution.started", "busy")
        blocked = client.response("configurations.import", {"path": str(source), "preview_token": preview["preview_token"]})
        assert blocked["error"]["code"] == "workspace_busy"
        client.request("execution.cancel", {"session_id": "a", "execution_id": "busy"})
        client.event("execution.finished", "busy")
        client.event("session.ready", session_id="a")
        imported = client.request("configurations.import", {"path": str(source), "preview_token": preview["preview_token"]})
        assert imported["imported_connections"] == 3
        output = tmp_path / "output"
        client.request("configurations.export", {"path": str(output), "preferences": {"editorFontSize": 19}})
        assert "groups" in json.loads((output / "connections.json").read_text(encoding="utf-8"))
        assert preferences_from_ini((output / "DataPyn.ini").read_bytes())["editorFontSize"] == 19
        done = client.execute("import sys\nassert not any(name.startswith('PyQt') for name in sys.modules)\nprint('qt-free')", execution_id="qt-free")
        assert done["status"] == "succeeded" and "qt-free" in client.output("qt-free")
        info = client.request("diagnostics.info")
        assert info["runtime"]["qt_loaded"] is False
    finally:
        client.close()
