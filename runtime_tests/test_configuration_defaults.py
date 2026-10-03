from copy import deepcopy
import json
import sys

import pytest

from datapyn_runtime.configurations import ConfigurationTransfer
from datapyn_runtime.configuration_defaults import load_defaults
from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.desktop_services import PackageService
from datapyn_runtime.legacy_settings import ini_string_list, patch_ini
from test_connection_catalog import Secrets
from test_configuration_compatibility import create_native_ini, write_json, temporary_keyring
from test_pynia_runtime import Harness, FAKE


@pytest.fixture
def transfer(tmp_path, monkeypatch, temporary_keyring):
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path / "application"))
    workspace = tmp_path / "workspace"
    package_service = PackageService(lambda message: None)
    catalog = ConnectionCatalog(workspace / "connections.json", Secrets())
    return ConfigurationTransfer(workspace, catalog, package_service)


@pytest.mark.parametrize("urls", [[], ["https://private.invalid/simple"], ["https://private.invalid/simple", "https://other.invalid/a,b"],
                                  ["https://example.invalid/ação", "https://other.invalid/a,b"]])
def test_actual_qt_string_lists_and_singleton_variants_read_without_qt_runtime(tmp_path, urls):
    from PyQt6.QtCore import QSettings
    path = tmp_path / "PackageManager.ini"
    create_native_ini(path, {"extra_index_urls": urls})
    assert ini_string_list(path.read_bytes(), "extra_index_urls") == urls
    assert ini_string_list(path.read_bytes(), "missing") is None
    other = tmp_path / "patched.ini"
    other.write_bytes(patch_ini(b"[General]\nkeep=fixture\n", {"extra_index_urls": urls}))
    value = QSettings(str(other), QSettings.Format.IniFormat).value("extra_index_urls", [])
    # The real legacy reader accepts both scalar and list representations.
    assert ([value] if isinstance(value, str) else value or []) == urls


def test_opaque_variants_are_not_inflated_into_objects():
    with pytest.raises(ValueError):
        ini_string_list(b"[General]\nextra_index_urls=@Variant(\\0\\0\\0\\x8\\0\\0\\0\\x0)\n", "extra_index_urls")


def legacy_folder(path):
    path.mkdir()
    create_native_ini(path / "CSVExport.ini", {"delimiter": "|", "decimal": ",", "encoding": "cp1252", "header": False, "open_folder": False,
                                             "vendor/unknown": "preserve"})
    create_native_ini(path / "ExportSettings.ini", {"copy_separator": ";", "null_display": "NULL", "open_folder": False})
    create_native_ini(path / "PyniaSettings.ini", {"default_agent_id": "claude", "model_id": "auto", "thought_level": "auto",
        "agent_prefs/claude/model_id": "sonnet", "agent_prefs/claude/thought_level": "low"})
    create_native_ini(path / "PackageManager.ini", {"extra_index_urls": ["https://one.invalid/simple", "https://two.invalid/simple"]})


def test_defaults_apply_and_export_current_values_into_actual_legacy_ini(transfer, tmp_path):
    from PyQt6.QtCore import QSettings
    source = tmp_path / "legacy"
    legacy_folder(source)
    preview = transfer.inspect({"path": str(source)})
    assert preview["defaults"]["export_settings"] == {"delimiter": "|", "decimal": ",", "encoding": "cp1252", "include_header": False, "open_folder": False}
    assert preview["defaults"]["copy_separator"] == ";" and preview["defaults"]["copy_null_display"] == "NULL"
    imported = transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    persisted = transfer.dispatch("configurations.defaults.get", {})["defaults"]
    assert persisted == imported["defaults"] == load_defaults(transfer.workspace)
    assert [source["url"] for source in transfer.package_service.sources()] == ["https://one.invalid/simple", "https://two.invalid/simple"]
    current = deepcopy(persisted)
    current["export_settings"].update(delimiter=",", include_header=True)
    current.update(copy_separator="\t", copy_null_display="None", export_open_folder=True)
    current["pynia"]["agent_prefs"]["claude"]["model_id"] = "auto"
    output = tmp_path / "exported"
    transfer.export_folder({"path": str(output), "defaults": current})
    qt_csv = QSettings(str(output / "CSVExport.ini"), QSettings.Format.IniFormat)
    assert qt_csv.value("delimiter") == "," and qt_csv.value("header", type=bool) is True
    assert qt_csv.value("vendor/unknown") == "preserve"
    qt_copy = QSettings(str(output / "ExportSettings.ini"), QSettings.Format.IniFormat)
    assert qt_copy.value("copy_separator") == "\t" and qt_copy.value("null_display") == "None"
    assert qt_copy.value("open_folder", type=bool) is True
    qt_pynia = QSettings(str(output / "PyniaSettings.ini"), QSettings.Format.IniFormat)
    assert qt_pynia.value("agent_prefs/claude/model_id") == "auto"
    assert ini_string_list((output / "PackageManager.ini").read_bytes(), "extra_index_urls") == ["https://one.invalid/simple", "https://two.invalid/simple"]
    assert "configuration_defaults.json" not in {file.name for file in output.iterdir()}


def test_package_sources_preserve_existing_ids_credentials_and_strip_embedded_passwords(transfer, tmp_path):
    write_json(transfer.package_service.config, {"sources": [{"id": "existing", "url": "https://one.invalid/simple", "username": "reader", "has_password": True}]})
    source = tmp_path / "legacy"
    source.mkdir()
    create_native_ini(source / "PackageManager.ini", {"extra_index_urls": ["https://reader:fixture-password@one.invalid/simple"]})
    preview = transfer.inspect({"path": str(source)})
    assert "fixture-password" not in json.dumps(preview)
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert transfer.package_service.sources() == [{"id": "existing", "url": "https://one.invalid/simple", "username": "reader", "has_password": True}]
    assert b"fixture-password" not in (transfer.archive / "PackageManager.ini").read_bytes()
    assert "fixture-password" not in transfer.package_service.config.read_text()


def test_no_package_url_key_does_not_clear_existing_sources(transfer, tmp_path):
    original = {"sources": [{"id": "existing", "url": "https://one.invalid/simple", "username": "", "has_password": False}]}
    write_json(transfer.package_service.config, original)
    source = tmp_path / "legacy"
    source.mkdir()
    create_native_ini(source / "PackageManager.ini", {"custom/extension": "opaque"})
    preview = transfer.inspect({"path": str(source)})
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert json.loads(transfer.package_service.config.read_text()) == original


def test_package_and_profile_defaults_roll_back_together(transfer, tmp_path, monkeypatch):
    source = tmp_path / "legacy"
    legacy_folder(source)
    write_json(transfer.package_service.config, {"sources": [{"id": "old", "url": "https://old.invalid/simple"}]})
    write_json(transfer.workspace / "configuration_defaults.json", {"defaults": {"copy_separator": ","}})
    transfer.catalog.save_group({"name": "Old"})
    preview = transfer.inspect({"path": str(source)})
    original_sources = transfer.package_service.config.read_bytes()
    original_defaults = (transfer.workspace / "configuration_defaults.json").read_bytes()
    original_catalog = transfer.catalog.list()
    write = transfer._write
    failed = []
    def fail_once(path, raw):
        if path == transfer.catalog.path and not failed:
            failed.append(path)
            raise OSError("fixture commit failure")
        write(path, raw)
    monkeypatch.setattr(transfer, "_write", fail_once)
    with pytest.raises(OSError, match="commit failure"):
        transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert transfer.package_service.config.read_bytes() == original_sources
    assert (transfer.workspace / "configuration_defaults.json").read_bytes() == original_defaults
    assert transfer.catalog.list() == original_catalog


def test_partial_csv_import_changes_only_present_fields_and_invalid_import_does_not_reset(transfer, tmp_path):
    original = {"delimiter": "|", "decimal": ",", "encoding": "cp1252", "include_header": True, "open_folder": False}
    write_json(transfer.workspace / "configuration_defaults.json", {"defaults": {"export_settings": original, "copy_separator": ";"}})
    source = tmp_path / "partial"
    source.mkdir()
    create_native_ini(source / "CSVExport.ini", {"header": False})
    preview = transfer.inspect({"path": str(source)})
    assert preview["defaults"] == {"export_settings": {"include_header": False}}
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    defaults = load_defaults(transfer.workspace)
    assert defaults["export_settings"] == {**original, "include_header": False}
    assert defaults["copy_separator"] == ";"
    (source / "CSVExport.ini").unlink()
    create_native_ini(source / "CSVExport.ini", {"delimiter": "invalid-multicharacter"})
    before = (transfer.workspace / "configuration_defaults.json").read_bytes()
    with pytest.raises(ValueError, match="delimiter"):
        transfer.inspect({"path": str(source)})
    assert (transfer.workspace / "configuration_defaults.json").read_bytes() == before


def test_partial_clipboard_notification_and_snapshot_preserve_unrelated_settings(transfer, tmp_path):
    from datapyn_runtime.notifications import DEFAULTS
    previous = deepcopy(DEFAULTS)
    previous["email"].update(host="smtp.fixture.invalid", port=2525, username="reader", to="fixture@invalid")
    previous.update(enabled=False, success_title="custom", sound=False)
    write_json(transfer.workspace / "notifications.json", previous)
    write_json(transfer.workspace / "snapshot_settings.json", {"enabled": False, "restore_on_startup": False, "max_size_mb": 75})
    write_json(transfer.workspace / "configuration_defaults.json", {"defaults": {"copy_separator": ";", "copy_null_display": "NULL", "export_open_folder": False}})
    source = tmp_path / "partial"
    source.mkdir()
    create_native_ini(source / "ExportSettings.ini", {"null_display": "None"})
    create_native_ini(source / "DataPyn.ini", {"notifications/sound": True, "session_results/enabled": True})
    preview = transfer.inspect({"path": str(source)})
    assert preview["defaults"] == {"copy_null_display": "None"}
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert load_defaults(transfer.workspace) == {"copy_separator": ";", "copy_null_display": "None", "export_open_folder": False}
    notification = json.loads((transfer.workspace / "notifications.json").read_text(encoding="utf-8"))
    assert notification == {**previous, "sound": True}
    assert json.loads((transfer.workspace / "snapshot_settings.json").read_text()) == {"enabled": True, "restore_on_startup": False, "max_size_mb": 75}


def test_pynia_defaults_prepare_only_new_real_acp_conversation(tmp_path, monkeypatch):
    harness = Harness(tmp_path, monkeypatch)
    try:
        # The general fake resets unrelated options on each set_config request.
        # This owned fixture persists both selections like a real ACP session.
        persistent_agent = tmp_path / "persistent_acp.py"
        persistent_agent.write_text(FAKE.read_text(encoding="utf-8").replace("item = dict(option)", "item = option"), encoding="utf-8")
        harness.runtime.pynia.launch_resolver = lambda spec: (sys.executable, [str(persistent_agent)])
        defaults = {"default_agent_id": "claude", "agent_prefs": {"claude": {"model_id": "sonnet", "thought_level": "low"}}}
        write_json(harness.runtime.profile_path / "configuration_defaults.json", {"defaults": {"pynia": defaults}})
        initial = harness.request("pynia.state", {"session_id": "a"})
        assert initial["agent_id"] == "claude" and initial["fresh_conversation"] is True
        harness.request("pynia.select_agent", {"session_id": "a", "agent_id": "claude"})
        harness.wait(lambda message: message.get("event") == "pynia.state" and message["payload"]["state"].get("defaults_applied"))
        prepared = harness.request("pynia.state", {"session_id": "a"})
        assert prepared["selectors"]["model"]["current"] == "sonnet"
        assert prepared["selectors"]["reasoning"]["current"] == "low" and prepared["fresh_conversation"] is False
        # A later settings import cannot reconfigure this existing conversation.
        write_json(harness.runtime.profile_path / "configuration_defaults.json", {"defaults": {"pynia": {"default_agent_id": "claude", "model_id": "auto"}}})
        unchanged = harness.request("pynia.state", {"session_id": "a", "defaults": {"default_agent_id": "codex", "model_id": "auto"}})
        assert unchanged["agent_id"] == "claude" and unchanged["selectors"]["model"]["current"] == "sonnet"
        original = harness.runtime.pynia.conversations.pop("a")
        harness.runtime.pynia._stop_client(original)
        old = harness.request("pynia.state", {"session_id": "a", "defaults": {"default_agent_id": "codex", "model_id": "auto"}})
        assert old["agent_id"] == "claude" and old["fresh_conversation"] is False
        assert old["selectors"]["model"]["current"] == "sonnet"
    finally:
        harness.runtime.close()


def test_unsupported_default_model_is_not_sent_and_restored_chat_is_not_changed(tmp_path, monkeypatch):
    harness = Harness(tmp_path, monkeypatch)
    try:
        harness.request("pynia.state", {"session_id": "a", "defaults": {"default_agent_id": "claude", "model_id": "not-advertised"}})
        harness.request("pynia.select_agent", {"session_id": "a", "agent_id": "claude"})
        harness.wait(lambda message: message.get("event") == "pynia.state" and message["payload"]["state"].get("defaults_applied"))
        state = harness.request("pynia.state", {"session_id": "a"})
        assert state["selectors"]["model"]["current"] == "auto"
        original = harness.runtime.pynia.conversations.pop("a")
        harness.runtime.pynia._stop_client(original)
        # Durable prepared state is restored, not treated as a new chat.
        restored = harness.request("pynia.state", {"session_id": "a", "defaults": {"default_agent_id": "codex", "model_id": "sonnet"}})
        assert restored["agent_id"] == "claude" and restored["fresh_conversation"] is False
        assert restored["selectors"]["model"]["current"] == "auto"
    finally:
        harness.runtime.close()
