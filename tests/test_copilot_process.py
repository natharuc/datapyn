"""Tests for hidden subprocess helpers used by Copilot CLI discovery."""

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


def test_apply_sdk_compat_installs_subprocess_patch_first(monkeypatch):
    from src.services.copilot import copilot_sdk_compat as compat

    compat._PATCHED = False
    order = []
    monkeypatch.setattr(
        "src.services.copilot.copilot_process.install_hidden_subprocess_patch",
        lambda: order.append("hidden"),
    )
    monkeypatch.setattr(compat, "_patch_model_billing", lambda _client: order.append("billing"))
    monkeypatch.setattr(compat, "_patch_ping_response", lambda _client: order.append("ping"))

    fake_client = type(sys)("copilot.client")
    monkeypatch.setitem(sys.modules, "copilot", type(sys)("copilot"))
    monkeypatch.setitem(sys.modules, "copilot.client", fake_client)

    compat.apply_sdk_compat_patches()
    assert order[0] == "hidden"
    assert "billing" in order


def test_invalidate_copilot_cli_cache_clears_discovery():
    from src.services.copilot import copilot_client_sdk as sdk

    sdk._CLI_DISCOVERY_CACHE = ("C:\\copilot.exe", (1, 2, 3))
    sdk.invalidate_copilot_cli_cache()
    assert sdk._CLI_DISCOVERY_CACHE is None


def test_verify_cli_works_delegates_to_version_read(monkeypatch):
    from src.services.copilot.copilot_client_sdk import _verify_cli_works

    calls = []

    def fake_read(path):
        calls.append(path)
        return (1, 0, 0) if path.endswith("good.exe") else (0, 0, 0)

    monkeypatch.setattr(
        "src.services.copilot.copilot_client_sdk._read_copilot_cli_version",
        fake_read,
    )
    assert _verify_cli_works("good.exe") is True
    assert _verify_cli_works("bad.exe") is False
    assert calls == ["good.exe", "bad.exe"]
