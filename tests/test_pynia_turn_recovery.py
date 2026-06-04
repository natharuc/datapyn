"""Tests for Pynia chat turn recovery when errors leave the UI wedged."""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from src.services.pynia.agent_client import PyniaAgentClient


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_token_chat_error_emits_chat_error_not_only_auth(qapp):
    client = PyniaAgentClient(copilot_client=None)
    client._provider_id = "openai"
    client._token_worker_mode = "chat"
    errors = []
    client.chat_error.connect(errors.append)
    auth = []
    client.auth_failed.connect(auth.append)

    client._on_token_error("Invalid API token (401)")

    assert errors == ["Invalid API token (401)"]
    assert auth == ["Invalid API token (401)"]


def test_token_verify_error_uses_auth_failed_only(qapp):
    client = PyniaAgentClient(copilot_client=None)
    client._provider_id = "openai"
    client._token_worker_mode = "verify"
    errors = []
    client.chat_error.connect(errors.append)
    auth = []
    client.auth_failed.connect(auth.append)

    client._on_token_error("Invalid API token (401)")

    assert not errors
    assert auth == ["Invalid API token (401)"]


def test_recover_stuck_turn_clears_active_runtime(qapp):
    from src.ui.components.copilot_chat_panel import PyniaChatPanel

    with patch.object(PyniaChatPanel, "_setup_ui"), patch.object(PyniaChatPanel, "_connect_signals"):
        panel = PyniaChatPanel()
    panel._agent_client = MagicMock()
    panel._mcp_server = None
    panel._run_chat_js = MagicMock()
    panel._hide_thinking_indicator = MagicMock()
    panel._active_block_editor = MagicMock(return_value=None)

    panel._chat_runtime.start_turn("hello")
    assert panel._chat_runtime.is_active

    panel._recover_stuck_turn("boom")

    assert not panel._chat_runtime.is_active
    assert panel._chat_runtime.last_turn.get("state") == "error"
    panel._agent_client.cancel.assert_called_once()
