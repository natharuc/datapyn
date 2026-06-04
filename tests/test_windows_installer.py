"""Tests for Windows ZIP-based installer helpers."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.windows_installer import (
    compare_versions,
    find_windows_zip_asset,
    install_from_zip,
    is_newer_version,
    normalize_version,
    read_installed_version,
    write_installed_version,
)


class TestVersionHelpers:
    def test_normalize_version_strips_v_prefix(self):
        assert normalize_version("v1.2.3") == "1.2.3"

    def test_is_newer_version(self):
        assert is_newer_version("1.2.0", "1.1.9") is True
        assert is_newer_version("1.0.0", "1.0.0") is False
        assert compare_versions("2.0.0", "1.9.9") == 1


class TestReleaseAssets:
    def test_find_windows_zip_asset(self):
        assets = [
            {"name": "notes.md", "browser_download_url": "http://x"},
            {"name": "DataPyn-1.2.3-windows.zip", "browser_download_url": "http://zip"},
        ]
        found = find_windows_zip_asset(assets)
        assert found is not None
        assert found.name.endswith("-windows.zip")


class TestZipInstall:
    def test_install_from_zip_creates_exe_and_manifest(self, tmp_path, monkeypatch):
        install_dir = tmp_path / "DataPyn"
        zip_path = tmp_path / "pkg.zip"

        staging = tmp_path / "stage" / "DataPyn"
        staging.mkdir(parents=True)
        (staging / "DataPyn.exe").write_bytes(b"MZ")

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(staging / "DataPyn.exe", "DataPyn/DataPyn.exe")

        monkeypatch.setattr(
            "src.services.windows_installer.create_shortcuts",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "src.services.windows_installer.register_uninstall",
            lambda *_args, **_kwargs: None,
        )

        exe = install_from_zip(zip_path, install_dir, "1.2.3")
        assert exe.name == "DataPyn.exe"
        assert (install_dir / "installed.json").is_file()
        payload = json.loads((install_dir / "installed.json").read_text(encoding="utf-8"))
        assert payload["version"] == "1.2.3"

    def test_read_installed_version_from_manifest(self, tmp_path):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        write_installed_version(install_dir, "9.8.7")
        assert read_installed_version(install_dir) == "9.8.7"
