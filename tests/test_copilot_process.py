"""Tests for hidden subprocess helpers used by ACP agent spawn."""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only flags")
def test_apply_hidden_flags_sets_create_no_window():
    from src.services.copilot.copilot_process import _apply_hidden_flags

    kwargs = _apply_hidden_flags({})
    assert kwargs.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
    assert kwargs.get("startupinfo") is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only flags")
def test_run_hidden_sets_create_no_window_on_windows():
    from src.services.copilot.copilot_process import run_hidden

    with patch("src.services.copilot.copilot_process.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_hidden(["echo", "ok"], text=True, timeout=1)
        _, kwargs = mock_run.call_args
        assert kwargs.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
        assert kwargs.get("startupinfo") is not None
