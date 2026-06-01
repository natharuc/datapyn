"""Tests for Copilot CLI runtime discovery and update helpers."""

from unittest.mock import MagicMock, patch

import pytest


class TestCopilotCliManager:
    def test_parse_copilot_cli_version(self):
        from src.services.copilot.copilot_cli_manager import parse_copilot_cli_version

        assert parse_copilot_cli_version("GitHub Copilot CLI 1.0.56.") == (1, 0, 56)
        assert parse_copilot_cli_version("GitHub Copilot CLI 0.0.411.") == (0, 0, 411)

    def test_compare_versions(self):
        from src.services.copilot.copilot_cli_manager import compare_versions

        assert compare_versions((1, 0, 56), (1, 0, 55)) == 1
        assert compare_versions((1, 0, 56), (1, 0, 56)) == 0
        assert compare_versions((0, 0, 411), (1, 0, 0)) == -1

    def test_detect_cli_source(self):
        from src.services.copilot.copilot_cli_manager import detect_cli_source

        assert detect_cli_source(r"C:\Users\me\AppData\Roaming\npm\copilot.cmd") == "npm"
        assert detect_cli_source(r"C:\Users\me\AppData\Local\Programs\Cursor\User\globalStorage\github.copilot-chat\copilot.exe") == "cursor"

    @patch("src.services.copilot.copilot_cli_manager.urlopen")
    def test_fetch_latest_npm_version(self, mock_urlopen):
        from src.services.copilot.copilot_cli_manager import fetch_latest_npm_version

        response = MagicMock()
        response.read.return_value = b'{"version":"1.0.57"}'
        response.__enter__.return_value = response
        mock_urlopen.return_value = response

        assert fetch_latest_npm_version() == "1.0.57"

    @patch("src.services.copilot.copilot_cli_manager.fetch_latest_npm_version", return_value="1.0.57")
    @patch("src.services.copilot.copilot_cli_manager.get_active_cli_info")
    def test_build_cli_status_marks_update_available(self, mock_active, _mock_latest):
        from src.services.copilot.copilot_cli_manager import build_cli_status

        mock_active.return_value = {
            "installed": True,
            "path": r"C:\npm\copilot.cmd",
            "version": "1.0.56",
            "version_tuple": [1, 0, 56],
            "source": "npm",
            "source_label": "npm global",
        }

        status = build_cli_status(check_latest=True)

        assert status["update_available"] is True
        assert status["cli_update_available"] is True
        assert status["latest_version"] == "1.0.57"

    def test_merge_usage_with_runtime(self):
        from src.services.copilot.copilot_cli_manager import merge_usage_with_runtime

        payload = merge_usage_with_runtime(
            {"available": True, "used": 3, "total": 300},
            username="octocat",
            cli_status={"version": "1.0.56", "source_label": "npm global"},
        )

        assert payload["username"] == "octocat"
        assert payload["cli"]["version"] == "1.0.56"
        assert payload["sdk"]["version"] is not None or payload["sdk"]["version"] == ""

    @patch("src.services.copilot.copilot_cli_manager.shutil.which", return_value=r"C:\Program Files\nodejs\npm.cmd")
    @patch("src.services.copilot.copilot_cli_manager.subprocess.run")
    @patch("src.services.copilot.copilot_cli_manager.get_active_cli_info")
    @patch("src.services.copilot.copilot_cli_manager.build_cli_status")
    def test_update_copilot_cli_runs_npm(self, mock_build, mock_active, mock_run, _mock_which):
        from src.services.copilot.copilot_cli_manager import update_copilot_cli

        mock_active.return_value = {"installed": True, "version": "1.0.56"}
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        mock_build.return_value = {"version": "1.0.57"}

        success, message = update_copilot_cli()

        assert success is True
        assert "1.0.57" in message
        args = mock_run.call_args.args[0]
        assert "npm" in args[0].lower() or args[0].endswith("npm.cmd")
        assert "@github/copilot@latest" in args

    @patch("src.services.copilot.copilot_cli_manager.update_copilot_sdk", return_value=(True, "sdk ok", True))
    @patch("src.services.copilot.copilot_cli_manager.update_copilot_cli", return_value=(True, "cli ok"))
    @patch("src.services.copilot.copilot_cli_manager.build_cli_status")
    def test_update_copilot_runtime_updates_both(self, mock_status, mock_cli, mock_sdk):
        from src.services.copilot.copilot_cli_manager import update_copilot_runtime

        mock_status.return_value = {
            "installed": True,
            "can_update_cli": True,
            "can_update_sdk": True,
            "cli_update_available": True,
            "sdk_update_available": True,
            "update_available": True,
            "npm_available": True,
        }

        success, message, restart = update_copilot_runtime()

        assert success is True
        assert restart is True
        mock_cli.assert_called_once()
        mock_sdk.assert_called_once()
