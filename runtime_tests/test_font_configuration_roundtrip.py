"""Fractional font sizes stay portable while the legacy INI keeps integer fields."""

import json

from datapyn_runtime.configurations import ConfigurationTransfer
from datapyn_runtime.connection_catalog import ConnectionCatalog
from datapyn_runtime.legacy_settings import preferences_from_ini
from test_connection_catalog import Secrets
from test_configuration_compatibility import transfer  # noqa: F401


def test_fractional_fonts_survive_transfer_with_integer_qt_projection(transfer, tmp_path):
    from PyQt6.QtCore import QSettings

    preferences = {"uiFontSize": 12.2, "editorFontSize": 17.6, "gridFontSize": 11.8}
    output = tmp_path / "portable"
    transfer.export_folder({"path": str(output), "preferences": preferences})
    portable = json.loads((output / "tauri-settings.json").read_text(encoding="utf-8"))
    assert portable["preferences"] == preferences
    legacy = QSettings(str(output / "DataPyn.ini"), QSettings.Format.IniFormat)
    assert legacy.value("editor/code_font_size", type=int) == 18
    assert legacy.value("results/grid_font_size", type=int) == 12
    assert preferences_from_ini((output / "DataPyn.ini").read_bytes()) == {
        "editorFontSize": 18, "gridFontSize": 12,
    }
    other = ConfigurationTransfer(tmp_path / "other", ConnectionCatalog(tmp_path / "other" / "connections.json", Secrets()))
    preview = other.inspect({"path": str(output)})
    assert preview["preferences"] == preferences
    restored = other.import_folder({"path": str(output), "preview_token": preview["preview_token"]})
    assert restored["preferences"] == preferences


def test_fractional_font_transfer_normalizes_to_the_same_tenth_as_the_editor(transfer, tmp_path):
    output = tmp_path / "portable"
    transfer.export_folder({"path": str(output), "preferences": {"editorFontSize": 13.25}})
    portable = json.loads((output / "tauri-settings.json").read_text(encoding="utf-8"))
    assert portable["preferences"]["editorFontSize"] == 13.3
