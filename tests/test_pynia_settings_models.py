"""Per-provider chat model persistence in PyniaSettings."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.pynia.settings import PyniaSettingsManager


@pytest.fixture
def settings_manager(monkeypatch):
    PyniaSettingsManager._instance = None
    mgr = PyniaSettingsManager()
    store: dict = {}

    def get_value(key, default=None):
        return store.get(key, default)

    def set_value(key, value):
        store[key] = value

    def remove_value(key):
        store.pop(key, None)

    mock_qsettings = MagicMock()
    mock_qsettings.value.side_effect = get_value
    mock_qsettings.setValue.side_effect = set_value
    mock_qsettings.remove.side_effect = remove_value

    workspace = MagicMock(current_workspace="test-ws")
    workspace.get_workspace_settings.return_value = mock_qsettings
    monkeypatch.setattr(
        "src.core.workspace_service.get_workspace_service",
        lambda: workspace,
    )
    return mgr, store


def test_selected_model_is_stored_per_provider(settings_manager):
    mgr, store = settings_manager
    mgr.set_active_provider("openai")
    mgr.set_selected_model("gpt-4o", "openai")
    mgr.set_active_provider("anthropic")
    mgr.set_selected_model("claude-sonnet-4-20250514", "anthropic")

    assert mgr.selected_model("openai") == "gpt-4o"
    assert mgr.selected_model("anthropic") == "claude-sonnet-4-20250514"


def test_selected_model_uses_legacy_key_for_active_provider(settings_manager):
    mgr, store = settings_manager
    store["selected_model"] = "gpt-4.1"
    store["active_provider"] = "openai"

    assert mgr.selected_model("openai") == "gpt-4.1"
    assert store.get("openai/selected_model") == "gpt-4.1"


def test_completion_model_falls_back_to_chat_model(settings_manager):
    """With no explicit autocomplete model, completion reuses the chat model
    (so it never depends on a hardcoded, possibly-retired default)."""
    mgr, _store = settings_manager
    mgr.set_selected_model("gpt-4.1", "openai")

    assert mgr.completion_model_override("openai") == ""
    assert mgr.completion_model("openai") == "gpt-4.1"


def test_completion_model_uses_explicit_override(settings_manager):
    mgr, _store = settings_manager
    mgr.set_selected_model("gpt-4.1", "openai")
    mgr.set_completion_model("openai", "gpt-4.1-mini")

    assert mgr.completion_model_override("openai") == "gpt-4.1-mini"
    assert mgr.completion_model("openai") == "gpt-4.1-mini"


def test_completion_model_is_per_provider(settings_manager):
    mgr, _store = settings_manager
    mgr.set_completion_model("openai", "gpt-4.1-nano")
    mgr.set_completion_model("anthropic", "claude-3-5-haiku-latest")

    assert mgr.completion_model("openai") == "gpt-4.1-nano"
    assert mgr.completion_model("anthropic") == "claude-3-5-haiku-latest"


def test_copilot_selected_model_syncs_with_copilot_settings(settings_manager, monkeypatch):
    mgr, _store = settings_manager
    copilot_settings = MagicMock()
    copilot_settings.chat_selected_model = "claude-sonnet-4"
    monkeypatch.setattr(
        "src.services.copilot.copilot_settings.get_copilot_settings",
        lambda: copilot_settings,
    )

    assert mgr.selected_model("copilot") == "claude-sonnet-4"
    mgr.set_selected_model("gpt-4o", "copilot")
    copilot_settings.set_chat_selected_model.assert_called_once_with("gpt-4o")
