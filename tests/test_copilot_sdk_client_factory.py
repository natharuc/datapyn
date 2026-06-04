"""Tests for Copilot SDK client construction compatibility."""

from src.services.copilot.copilot_client_sdk import _create_sdk_client


def test_create_sdk_client_falls_back_when_config_rejected(monkeypatch):
    class StrictClient:
        def __init__(self, config=None):
            if config is not None:
                raise TypeError("CopilotClient.__init__() takes 1 positional argument but 2 were given")

    monkeypatch.setattr(
        "src.services.copilot.copilot_client_sdk._get_sdk_options",
        lambda: object(),
    )
    client = _create_sdk_client(StrictClient)
    assert isinstance(client, StrictClient)


def test_create_sdk_client_without_options(monkeypatch):
    class FlexibleClient:
        def __init__(self, config=None):
            self.config = config

    monkeypatch.setattr(
        "src.services.copilot.copilot_client_sdk._get_sdk_options",
        lambda: None,
    )
    client = _create_sdk_client(FlexibleClient)
    assert client.config is None
