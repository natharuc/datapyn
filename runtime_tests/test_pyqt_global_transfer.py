"""Actual Qt codecs, with explicit temporary paths and no native registry access."""
import importlib.util
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSettings
import pytest

spec = importlib.util.spec_from_file_location("pyqt_transfer", Path(__file__).resolve().parents[1] / "scripts/tauri/transfer_pyqt_settings.py")
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


def factory(root):
    root.mkdir(parents=True, exist_ok=True)
    return lambda name: QSettings(str(root / f"{name}.ini"), QSettings.Format.IniFormat)


def test_real_qt_global_ini_preserves_variants_unknown_keys_and_scalars(tmp_path):
    source = factory(tmp_path / "source")
    settings = source("DataPyn")
    values = {"language": "pt-BR", "editor/code_font_size": 17, "notifications/enabled": False,
              "unknown/geometry": QByteArray(b"\x00\xff\x10\"\\Qt"), "unknown/string": " áβ;=,\n@literal ",
              "unknown/list": ["one", "a,b", "\\dir"], "unknown/nested": {"future": [1, True, "á"]}}
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()
    output = tmp_path / "export"
    assert len(transfer.export_globals(output, source)) == 1
    destination = factory(tmp_path / "destination")
    assert transfer.import_globals(output, destination) == ["DataPyn"]
    received = destination("DataPyn")
    assert {key: received.value(key) for key in values} == values


def test_package_sources_preserve_metadata_but_never_passwords_or_url_credentials(tmp_path):
    source = factory(tmp_path / "source")
    settings = source("PackageManager")
    settings.setValue("sources_v2", [{"url": "https://user:synthetic-secret@example.test/simple", "username": "user", "password": "synthetic-secret", "future": True}])
    settings.sync()
    transfer.export_globals(tmp_path / "export", source)
    exported = QSettings(str(tmp_path / "export/PackageManager.ini"), QSettings.Format.IniFormat)
    assert exported.value("sources_v2") == [{"url": "https://example.test/simple", "username": "user", "future": True}]
    assert exported.value("extra_index_urls") == ["https://example.test/simple"]
    assert "synthetic-secret" not in (tmp_path / "export/PackageManager.ini").read_text()


def test_export_refuses_to_overwrite_existing_global_files(tmp_path):
    output = tmp_path / "export"
    output.mkdir()
    sentinel = output / "DataPyn.ini"
    sentinel.write_text("preserve")
    with pytest.raises(FileExistsError):
        transfer.export_globals(output, lambda _: pytest.fail("Must reject collision before reading settings"))
    assert sentinel.read_text() == "preserve"


def test_import_validates_all_ini_files_before_touching_legacy_settings(tmp_path):
    output = tmp_path / "import"
    output.mkdir()
    (output / "DataPyn.ini").write_text("[General]\nlanguage=en-US\n")
    (output / "MainWindow.ini").write_text("[unclosed\nmalformed\n")
    destination = factory(tmp_path / "destination")
    before = destination("DataPyn")
    before.setValue("language", "pt-BR")
    before.sync()
    with pytest.raises(OSError):
        transfer.import_globals(output, destination)
    assert destination("DataPyn").value("language") == "pt-BR"
