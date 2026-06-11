"""Tests for Pynia connector picker payload."""

from src.services.pynia.connector_picker import build_connector_picker_payload


def test_build_connector_picker_lists_token_providers(monkeypatch):
    from src.services.pynia.settings import get_pynia_settings

    settings = get_pynia_settings()
    settings.set_active_provider("openrouter")

    payload = build_connector_picker_payload()

    assert payload["active_provider"] == "openrouter"
    assert payload["active_provider_label"]
    provider_entries = [a for a in payload["accounts"] if a.get("kind") == "provider"]
    ids = {entry["provider_id"] for entry in provider_entries}
    assert "openrouter" in ids
    assert "openai" in ids
    openrouter = next(item for item in provider_entries if item["provider_id"] == "openrouter")
    assert openrouter["display_name"]
    assert openrouter["display_name"] != "openrouter"
    assert not openrouter["subtitle"].startswith("[")
    assert "sections" in payload
    connector_section = next(s for s in payload["sections"] if s["id"] == "connectors")
    assert len(connector_section["accounts"]) >= 3
