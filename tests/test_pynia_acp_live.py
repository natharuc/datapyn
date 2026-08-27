"""Live ACP integration tests for the developer machine.

These tests spawn the real Claude / Cursor / Copilot / Codex CLIs, so they are
ignored by the default pytest run and by CI.

Run locally:

    uv run pytest tests/test_pynia_acp_live.py -q
"""

from __future__ import annotations

import os
import time

import pytest

from src.services.pynia.acp.agent import FixStep
from src.services.pynia.acp.agents.factory import create_acp_agent
from src.services.pynia.acp.catalog import AGENT_IDS
from tests.helpers.acp_listener import RecordingAcpListener
from tests.helpers.acp_live_report import LiveAgentOutcome, format_live_report

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(300),
    pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="live ACP requires local CLI authentication",
    ),
]


def _exercise(agent_id: str, tmp_path, qapp) -> LiveAgentOutcome:
    listener = RecordingAcpListener()
    agent = create_acp_agent(agent_id, listener, cwd=str(tmp_path))
    outcome = LiveAgentOutcome(agent_id=agent_id)
    try:
        grant = agent.grant_configuration(install=True)
        outcome.grant = grant
        if not grant.ok:
            return outcome
        if agent.exposes_models and not grant.models:
            outcome.error = "agent did not list any LLMs after grant_configuration"
            outcome.extra_steps.append(
                FixStep(
                    "Authenticate the CLI and confirm it exposes models, then re-run",
                    "",
                )
            )
            return outcome
        if agent.exposes_reasoning and not grant.reasoning:
            outcome.error = "agent did not list any reasoning levels after grant_configuration"
            return outcome
        listener.got_message.clear()
        agent.send_message("Reply with the single word: pong", timeout=120)
        deadline = time.time() + 15
        while time.time() < deadline and not listener.got_message.is_set():
            qapp.processEvents()
            time.sleep(0.05)
        qapp.processEvents()
        text = "".join(listener.messages).lower()
        outcome.ping = "pong" if "pong" in text else (text[:80] or "(no reply)")
        if "pong" not in text:
            outcome.error = f"expected a pong reply, got: {outcome.ping!r}"
        return outcome
    except Exception as exc:
        if outcome.grant is None:
            from src.services.pynia.acp.agent import GrantResult

            outcome.grant = GrantResult(
                ok=False,
                agent_id=agent_id,
                status="not_installed",
                detail=str(exc),
                steps=[FixStep("Fix the error above, then re-run the live tests", "")],
            )
        else:
            outcome.error = str(exc)
        return outcome
    finally:
        try:
            agent.close()
        except Exception:
            pass


def test_live_acp_agents(qapp, tmp_path):
    outcomes = [_exercise(agent_id, tmp_path, qapp) for agent_id in AGENT_IDS]
    report = format_live_report(outcomes)
    print("\n" + report)
    if any(not item.ok for item in outcomes):
        pytest.fail(report)
