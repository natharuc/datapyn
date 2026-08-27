"""Protocol-level tests for the shared ACP session service."""

from __future__ import annotations

import sys
from pathlib import Path

from src.services.pynia.acp.client import AcpClient
from src.services.pynia.acp.protocol import initialize_params
from src.services.pynia.acp.service import AcpSessionService
from src.services.pynia.acp.session_config import merge_config_snapshot, normalize_config
from tests.helpers.acp_payloads import (
    CLAUDE_SESSION_NEW,
    CODEX_SESSION_NEW,
    COPILOT_SESSION_NEW,
    CURSOR_SESSION_NEW,
    SET_CONFIG_CURRENT_ONLY,
)

FAKE_AGENT = str(Path(__file__).parent / "helpers" / "fake_acp_agent.py")


def test_initialize_params_advertise_config_options():
    params = initialize_params("1.2.3")
    assert params["protocolVersion"] == 1
    assert params["clientInfo"]["name"] == "DataPyn"
    assert params["clientCapabilities"]["session"]["configOptions"] == {"boolean": {}}


def test_claude_payload_shows_llm_hides_reasoning():
    cfg = normalize_config(CLAUDE_SESSION_NEW)
    assert cfg.model["hidden"] is False
    assert {item["value"] for item in cfg.model["values"]} == {"sonnet", "opus"}
    assert cfg.model["current"] == "sonnet"
    assert cfg.reasoning["hidden"] is True
    selectors = cfg.to_selectors()
    assert all(item["value"] != "bypassPermissions" for item in selectors["model"]["values"])
    assert all(item["value"] != "default" for item in selectors["model"]["values"])


def test_claude_models_field_alone():
    cfg = normalize_config(
        {
            "sessionId": "s",
            "models": CLAUDE_SESSION_NEW["models"],
        }
    )
    assert cfg.model["hidden"] is False
    assert cfg.model["current"] == "sonnet"
    assert cfg.reasoning["hidden"] is True


def test_copilot_and_codex_show_llm_and_reasoning():
    copilot = normalize_config(COPILOT_SESSION_NEW)
    assert copilot.model["hidden"] is False
    assert copilot.reasoning["hidden"] is False
    assert copilot.reasoning["current"] == "medium"
    assert {item["value"] for item in copilot.reasoning["values"]} == {"low", "medium", "high"}
    codex = normalize_config(CODEX_SESSION_NEW)
    assert codex.model["hidden"] is False
    assert codex.reasoning["hidden"] is False
    assert "o3" in {item["value"] for item in codex.model["values"]}


def test_cursor_empty_config_hides_chips():
    cfg = normalize_config(CURSOR_SESSION_NEW)
    assert cfg.model["hidden"] is True
    assert cfg.model["values"] == []
    assert cfg.reasoning["hidden"] is True


def test_merge_keeps_lists_when_set_returns_current_only():
    merged = merge_config_snapshot(COPILOT_SESSION_NEW, SET_CONFIG_CURRENT_ONLY)
    cfg = normalize_config(merged)
    assert cfg.model["current"] == "opus"
    assert {item["value"] for item in cfg.model["values"]} == {"gpt-5", "gpt-4.1"}
    assert cfg.reasoning["current"] == "high"
    assert {item["value"] for item in cfg.reasoning["values"]} == {"low", "medium", "high"}
    assert cfg.model["hidden"] is False
    assert cfg.reasoning["hidden"] is False


def test_prompt_has_where_why_and_tools():
    from src.services.pynia.acp.turn_context import format_acp_prompt, format_acp_prompt_parts

    ctx = {
        "tab_id": "tab-9",
        "tab_name": "sales",
        "connection_name": "prod",
        "focused_block": "query1",
        "execution_state": {"active_result": {"columns": ["mes"], "rows": 3}},
    }
    parts = format_acp_prompt_parts("cria um grafico", ctx)
    assert "WHY YOU WERE CALLED" in parts[0]["text"]
    assert "cria um grafico" in parts[0]["text"]
    assert "THIS TURN" in parts[0]["text"]
    assert "CURRENT TAB JSON" in parts[1]["text"]
    assert "sales" in parts[1]["text"]
    assert "datapyn_chart" in parts[2]["text"]
    assert "datapyn_run" in parts[2]["text"]
    text = format_acp_prompt("cria um grafico", ctx)
    assert "WHERE YOU ARE" in text or "CURRENT TAB JSON" in text
    assert "datapyn_chart" in text


def test_service_connect_populates_config_before_prompt(qapp, tmp_path):
    client = AcpClient("claude")
    svc = AcpSessionService()
    try:
        client.start(sys.executable, [FAKE_AGENT], cwd=str(tmp_path))
        session_id, cfg = svc.connect(client, str(tmp_path), mcp_servers=[])
        assert session_id
        assert cfg.session_id == session_id
        assert cfg.model["hidden"] is False
        assert cfg.model["values"]
        assert cfg.reasoning["hidden"] is False
        assert cfg.reasoning["values"]
        result = svc.prompt(client, session_id, "ping pong", timeout=10)
        assert result.get("stopReason") == "end_turn"
    finally:
        client.stop()
