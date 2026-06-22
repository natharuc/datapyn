"""Tests for Windows ZIP-based installer helpers."""

import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.windows_installer import (
    REGISTRY_DELETE_ARG,
    _build_uninstall_command,
    _display_icon_value,
    _find_local_setup_helper,
    _replace_installation,
    _stage_updater_executable,
    _updater_runs_from_install_dir,
    compare_versions,
    detect_existing_installation,
    find_windows_zip_asset,
    install_from_zip,
    is_newer_version,
    launch_deferred_zip_update,
    launch_setup_update,
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


class TestDetectInstallation:
    def test_detect_fresh_default_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.services.windows_installer.DEFAULT_INSTALL_DIR",
            tmp_path / "DataPyn",
        )
        monkeypatch.setattr("src.services.windows_installer.get_install_dir", lambda: None)
        installed, path, version = detect_existing_installation()
        assert installed is False
        assert path == tmp_path / "DataPyn"
        assert version is None

    def test_detect_from_manifest(self, tmp_path, monkeypatch):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        write_installed_version(install_dir, "3.2.1")
        monkeypatch.setattr("src.services.windows_installer.get_install_dir", lambda: install_dir)
        installed, path, version = detect_existing_installation()
        assert installed is True
        assert path == install_dir
        assert version == "3.2.1"


class TestUninstallRegistry:
    def test_uninstall_command_removes_registry_before_folder(self, tmp_path):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        cmd = _build_uninstall_command(install_dir)
        assert f'reg delete "{REGISTRY_DELETE_ARG}"' in cmd
        assert cmd.index("reg delete") < cmd.index("rmdir")

    def test_display_icon_value(self, tmp_path):
        icon = tmp_path / "datapyn-logo.ico"
        icon.write_bytes(b"ico")
        assert _display_icon_value(icon) == f"{icon},0"

    def test_uninstall_cmd_script_removes_registry_first(self, tmp_path):
        from src.services.windows_installer import _write_uninstall_cmd

        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        script = _write_uninstall_cmd(install_dir)
        text = script.read_text(encoding="utf-8")
        assert "reg delete" in text
        assert text.index("reg delete") < text.index("rmdir")


class TestDeferredUpdate:
    def test_find_local_setup_helper(self, tmp_path):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        setup = install_dir / "DataPyn-Setup.exe"
        setup.write_bytes(b"MZ")
        assert _find_local_setup_helper(install_dir) == setup

    @patch(
        "src.services.windows_installer._run_hidden_powershell_script",
        return_value=(True, ""),
    )
    def test_launch_deferred_uses_hidden_powershell(self, mock_run, tmp_path):
        zip_path = tmp_path / "DataPyn-1.2.0-windows.zip"
        zip_path.write_bytes(b"PK")
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        setup = install_dir / "DataPyn-Setup.exe"
        setup.write_bytes(b"MZ")

        with patch(
            "src.services.windows_installer._resolve_setup_helper",
            return_value=setup,
        ):
            ok, err = launch_deferred_zip_update(zip_path, "1.2.0", install_dir)

        assert ok is True
        assert err == ""
        mock_run.assert_called_once()
        assert mock_run.call_args[0][1].startswith("datapyn-setup-update-")

    @patch(
        "src.services.windows_installer._resolve_setup_helper",
        return_value=None,
    )
    @patch(
        "src.services.windows_installer._launch_powershell_deferred_update",
        return_value=(True, ""),
    )
    def test_launch_deferred_falls_back_to_zip_apply(self, mock_ps, _mock_setup, tmp_path):
        zip_path = tmp_path / "DataPyn-1.2.0-windows.zip"
        zip_path.write_bytes(b"PK")
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()

        ok, err = launch_deferred_zip_update(zip_path, "1.2.0", install_dir)

        assert ok is True
        assert err == ""
        mock_ps.assert_called_once()


class TestStageUpdaterExecutable:
    def test_stage_updater_copies_internal_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.services.windows_installer.tempfile.gettempdir",
            lambda: str(tmp_path),
        )
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        internal = install_dir / "_internal"
        internal.mkdir()
        (internal / "python312.dll").write_bytes(b"PYDLL")
        (install_dir / "DataPyn.exe").write_bytes(b"MZ")

        staged_exe = _stage_updater_executable(install_dir / "DataPyn.exe", "1.2.0")

        assert staged_exe.name == "DataPyn.exe"
        assert staged_exe.parent.name == "DataPyn-Update-1.2.0"
        assert (staged_exe.parent / "_internal" / "python312.dll").read_bytes() == b"PYDLL"


class TestLaunchSetupUpdate:
    @patch("src.services.windows_installer._is_frozen_runtime", return_value=True)
    @patch("src.services.windows_installer._spawn_detached")
    @patch("src.services.windows_installer._stage_updater_executable")
    def test_launch_setup_update_spawns_detached(
        self, mock_stage, mock_spawn, _mock_frozen, tmp_path
    ):
        zip_path = tmp_path / "DataPyn-1.2.0-windows.zip"
        zip_path.write_bytes(b"PK")
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        app_exe = install_dir / "DataPyn.exe"
        app_exe.write_bytes(b"MZ")
        staged = tmp_path / "DataPyn-Update-1.2.0" / "DataPyn.exe"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"MZ")
        mock_stage.return_value = staged

        ok, err = launch_setup_update(zip_path, "1.2.0", install_dir)

        assert ok is True
        assert err == ""
        mock_stage.assert_called_once_with(app_exe, "1.2.0")
        mock_spawn.assert_called_once()
        command, cwd = mock_spawn.call_args[0]
        assert command[0] == str(staged)
        assert command[1] == "--apply-update"
        assert command[2] == str(zip_path)
        assert "--parent-pid" in command
        assert cwd == staged.parent

    @patch("src.services.windows_installer._is_frozen_runtime", return_value=False)
    @patch("src.services.windows_installer._spawn_detached")
    def test_launch_setup_update_uses_source_main_in_dev(
        self, mock_spawn, _mock_frozen, tmp_path
    ):
        zip_path = tmp_path / "DataPyn-1.2.0-windows.zip"
        zip_path.write_bytes(b"PK")
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        (install_dir / "DataPyn.exe").write_bytes(b"MZ")

        ok, err = launch_setup_update(zip_path, "1.2.0", install_dir)

        assert ok is True
        assert err == ""
        mock_spawn.assert_called_once()
        command, cwd = mock_spawn.call_args[0]
        assert command[0] == sys.executable
        assert command[2] == "--apply-update"
        assert command[3] == str(zip_path)
        assert "--parent-pid" in command
        assert cwd.name == "source"


class TestReplaceInstallation:
    def test_updater_runs_from_install_dir(self, tmp_path, monkeypatch):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        fake_exe = install_dir / "DataPyn-Setup.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        assert _updater_runs_from_install_dir(install_dir) is True

    @patch("src.services.windows_installer.sys.platform", "win32")
    @patch("src.services.windows_installer.wait_for_datapyn_exit", return_value=True)
    @patch("src.services.windows_installer._robocopy_mirror")
    @patch("src.services.windows_installer._updater_runs_from_install_dir", return_value=True)
    def test_replace_uses_in_place_when_updater_inside_install_dir(
        self, _mock_inside, mock_robocopy, _mock_wait, tmp_path
    ):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        (install_dir / "DataPyn.exe").write_bytes(b"OLD")
        staging_dir = tmp_path / "DataPyn.staging"
        staging_dir.mkdir()
        (staging_dir / "DataPyn.exe").write_bytes(b"NEW")
        backup_dir = tmp_path / "DataPyn.old"

        _replace_installation(install_dir, staging_dir, backup_dir)

        mock_robocopy.assert_called_once_with(staging_dir, install_dir)
        assert not staging_dir.exists()
        assert (install_dir / "DataPyn.exe").read_bytes() == b"OLD"

    @patch("src.services.windows_installer.wait_for_datapyn_exit", return_value=True)
    @patch("src.services.windows_installer._updater_runs_from_install_dir", return_value=False)
    def test_replace_renames_when_possible(self, _mock_inside, _mock_wait, tmp_path):
        install_dir = tmp_path / "DataPyn"
        install_dir.mkdir()
        (install_dir / "DataPyn.exe").write_bytes(b"OLD")
        staging_dir = tmp_path / "DataPyn.staging"
        staging_dir.mkdir()
        (staging_dir / "DataPyn.exe").write_bytes(b"NEW")
        backup_dir = tmp_path / "DataPyn.old"

        _replace_installation(install_dir, staging_dir, backup_dir)

        assert not backup_dir.exists()
        assert install_dir.is_dir()
        assert (install_dir / "DataPyn.exe").read_bytes() == b"NEW"
        assert not staging_dir.exists()


class TestWaitForDatapynExit:
    @patch("src.services.windows_installer._datapyn_process_pids", return_value=[])
    def test_wait_returns_when_no_other_instances(self, _mock_pids):
        from src.services.windows_installer import wait_for_datapyn_exit

        assert wait_for_datapyn_exit(timeout_sec=1, exclude_pid=12345) is True

    @patch("time.monotonic", side_effect=[0.0, 0.0, 2.0])
    @patch("time.sleep")
    @patch("src.services.windows_installer._datapyn_process_pids", return_value=[99])
    def test_wait_times_out_when_other_instance_stays(self, _mock_pids, _sleep, _mono):
        from src.services.windows_installer import wait_for_datapyn_exit

        assert wait_for_datapyn_exit(timeout_sec=1, exclude_pid=12345) is False


class TestWaitForProcessExit:
    @patch("src.services.windows_installer._process_is_running", return_value=False)
    def test_wait_returns_when_process_gone(self, _mock_running):
        from src.services.windows_installer import wait_for_process_exit

        assert wait_for_process_exit(12345, timeout_sec=1) is True

    @patch("time.monotonic", side_effect=[0.0, 0.0, 2.0])
    @patch("time.sleep")
    @patch("src.services.windows_installer._process_is_running", return_value=True)
    def test_wait_times_out_when_process_stays(self, _mock_running, _sleep, _mono):
        from src.services.windows_installer import wait_for_process_exit

        assert wait_for_process_exit(12345, timeout_sec=1) is False

    def test_wait_returns_true_for_invalid_pid(self):
        from src.services.windows_installer import wait_for_process_exit

        assert wait_for_process_exit(0, timeout_sec=1) is True


class TestParseApplyUpdateArgv:
    def test_parse_parent_pid(self):
        from src.services.in_app_update import parse_apply_update_argv

        args = parse_apply_update_argv(
            [
                "main.py",
                "--apply-update",
                "/tmp/pkg.zip",
                "--version",
                "1.2.0",
                "--dir",
                "C:/DataPyn",
                "--parent-pid",
                "4242",
            ]
        )
        assert args is not None
        assert args.parent_pid == 4242
        assert args.zip_path == "/tmp/pkg.zip"
