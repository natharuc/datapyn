"""Tests for Pynia provider usage/limit payloads."""

from src.services.pynia.usage import build_pynia_usage_payload, _token_usage_snapshot


def test_openai_limits_payload():
    snap = _token_usage_snapshot("openai", "gpt-4o", [{"id": "gpt-4o", "multiplier": 1.0}])
    assert snap["provider_id"] == "openai"
    assert snap["show_runtime"] is False
    assert snap["show_subscription"] is False
    assert "limits_summary" in snap
    assert snap["limits_url"]


def test_copilot_merges_runtime_flag():
    payload = build_pynia_usage_payload(
        "copilot",
        model="gpt-4o",
        usage_snapshot={"available": True, "used": 1, "total": 10},
        username="dev",
    )
    assert payload["show_runtime"] is True
    assert payload["show_subscription"] is True
    assert payload["show_account_switch"] is True
