"""Unit tests for IAcpAgent against the fake ACP stdio agent."""

from __future__ import annotations

import sys
from pathlib import Path

from src.services.pynia.acp.agent import IAcpAgent
from src.services.pynia.acp.agents.factory import create_acp_agent
from src.services.pynia.acp.agents.claude import ClaudeAcpAgent
from src.services.pynia.acp.agents.codex import CodexAcpAgent
from src.services.pynia.acp.agents.copilot import CopilotAcpAgent
from src.services.pynia.acp.agents.cursor import CursorAcpAgent
from tests.helpers.acp_listener import RecordingAcpListener

FAKE_AGENT = str(Path(__file__).parent / "helpers" / "fake_acp_agent.py")
FAKE_LAUNCH = (sys.executable, [FAKE_AGENT])


class _MemSettings:
    def __init__(self):
        self._models: dict[str, str] = {}
        self._thoughts: dict[str, str] = {}

    def agent_model_id(self, agent_id: str) -> str:
        return self._models.get(agent_id, "")

    def set_agent_model_id(self, agent_id: str, value: str) -> None:
        self._models[agent_id] = value

    def agent_thought_level(self, agent_id: str) -> str:
        return self._thoughts.get(agent_id, "")

    def set_agent_thought_level(self, agent_id: str, value: str) -> None:
        self._thoughts[agent_id] = value


def _agent(agent_id: str, listener=None, tmp_path=None, **kwargs) -> IAcpAgent:
    return create_acp_agent(
        agent_id,
        listener or RecordingAcpListener(),
        cwd=str(tmp_path) if tmp_path is not None else None,
        launch=FAKE_LAUNCH,
        **kwargs,
    )


def test_factory_returns_typed_adapters():
    assert isinstance(create_acp_agent("claude"), ClaudeAcpAgent)
    assert isinstance(create_acp_agent("cursor"), CursorAcpAgent)
    assert isinstance(create_acp_agent("copilot"), CopilotAcpAgent)
    assert isinstance(create_acp_agent("codex"), CodexAcpAgent)


def test_factory_unknown_agent():
    import pytest

    with pytest.raises(RuntimeError, match="Unknown agent"):
        create_acp_agent("nope")


def test_grant_lists_models_and_reasoning(qapp, tmp_path):
    listener = RecordingAcpListener()
    agent = _agent("copilot", listener, tmp_path)
    try:
        result = agent.grant_configuration(install=False)
        assert result.ok is True
        assert result.status == "ready"
        assert agent.is_ready
        ids = {item.id for item in agent.list_models()}
        assert ids == {"auto", "sonnet"}
        thought = {item.id for item in agent.list_reasoning()}
        assert thought == {"auto", "off", "low", "medium", "high"}
        assert listener.config_events >= 1
        selectors = agent.composer_config()
        assert selectors["model"]["hidden"] is False
        assert selectors["reasoning"]["hidden"] is False
    finally:
        agent.close()


def test_send_message_invokes_receive(qapp, tmp_path):
    listener = RecordingAcpListener()
    agent = _agent("claude", listener, tmp_path)
    try:
        assert agent.grant_configuration(install=False).ok
        result = agent.send_message("Reply with the single word: pong", timeout=10)
        assert result.get("stopReason") == "end_turn"
        qapp.processEvents()
        assert "pong" in "".join(listener.messages)
    finally:
        agent.close()


def test_thinking_and_action_callbacks(qapp, tmp_path):
    listener = RecordingAcpListener()
    agent = _agent("claude", listener, tmp_path)
    try:
        assert agent.grant_configuration(install=False).ok
        agent.send_message("please think then ask-permission pong", timeout=10)
        qapp.processEvents()
        assert "hmm" in listener.thinking
        assert listener.actions
        assert listener.actions[0].summary
        assert "pong" in "".join(listener.messages)
    finally:
        agent.close()


def test_set_model_persists_and_pushes(qapp, tmp_path, monkeypatch):
    settings = _MemSettings()
    monkeypatch.setattr("src.services.pynia.settings.get_pynia_settings", lambda: settings)
    listener = RecordingAcpListener()
    agent = _agent("claude", listener, tmp_path)
    try:
        assert agent.grant_configuration(install=False).ok
        agent.set_model("sonnet")
        assert settings.agent_model_id("claude") == "sonnet"
        assert agent.current_model == "sonnet"
        agent.set_reasoning("high")
        assert settings.agent_thought_level("claude") == "high"
        assert agent.current_reasoning == "high"
    finally:
        agent.close()


def test_grant_reports_missing_install(monkeypatch):
    from src.services.pynia.acp.installer import ProbeResult

    monkeypatch.setattr(
        "src.services.pynia.acp.agents.base.probe_agent",
        lambda _id: ProbeResult("cursor", "not_installed", None, "npm install …"),
    )
    monkeypatch.setattr(
        "src.services.pynia.acp.agents.base.install_command",
        lambda _spec: "curl https://cursor.com/install -fsS | bash",
    )
    agent = create_acp_agent("cursor")
    result = agent.grant_configuration(install=False)
    assert result.ok is False
    assert result.status == "not_installed"
    assert result.steps
    assert any(step.command for step in result.steps)


def test_cursor_does_not_require_models():
    agent = create_acp_agent("cursor")
    assert agent.exposes_models is False
    assert agent.exposes_reasoning is False
    claude = create_acp_agent("claude")
    assert claude.exposes_models is True
    assert claude.exposes_reasoning is False
    copilot = create_acp_agent("copilot")
    assert copilot.exposes_models is True
    assert copilot.exposes_reasoning is True


def test_live_report_includes_rerun_command():
    from src.services.pynia.acp.agent import FixStep, GrantResult, LIVE_TEST_COMMAND
    from tests.helpers.acp_live_report import LiveAgentOutcome, format_live_report

    report = format_live_report(
        [
            LiveAgentOutcome(
                agent_id="claude",
                grant=GrantResult(ok=True, agent_id="claude", status="ready"),
                ping="pong",
            ),
            LiveAgentOutcome(
                agent_id="copilot",
                grant=GrantResult(
                    ok=False,
                    agent_id="copilot",
                    status="not_authenticated",
                    detail="login required",
                    steps=[FixStep("Authenticate the CLI", "copilot /login")],
                ),
            ),
        ]
    )
    assert "claude" in report
    assert "copilot" in report
    assert "copilot /login" in report
    assert LIVE_TEST_COMMAND in report
