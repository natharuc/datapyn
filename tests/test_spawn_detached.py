"""Tests for detached GUI subprocess launch (no cmd.exe flash)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only spawn flags")
def test_spawn_detached_uses_pythonw_and_no_cmd(tmp_path):
    from src.services.windows_installer import _gui_subprocess_executable, _spawn_detached

    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_bytes(b"MZ")
    python = tmp_path / "python.exe"
    python.write_bytes(b"MZ")

    assert _gui_subprocess_executable(str(python)) == str(pythonw)

    with patch("src.services.windows_installer.subprocess.Popen") as mock_popen:
        _spawn_detached([str(python), "main.py", "--apply-update"], tmp_path)
        mock_popen.assert_called_once()
        command = mock_popen.call_args[0][0]
        assert command[0] == str(pythonw)
        assert command[0] != "cmd.exe"
        kwargs = mock_popen.call_args[1]
        assert kwargs.get("creationflags", 0) & getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
