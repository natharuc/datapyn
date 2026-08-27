"""Build the IAcpAgent implementation for a catalog agent id."""

from __future__ import annotations

from typing import Optional

from ..agent import IAcpAgent, IAcpAgentListener
from .claude import ClaudeAcpAgent
from .codex import CodexAcpAgent
from .copilot import CopilotAcpAgent
from .cursor import CursorAcpAgent

_AGENTS = {
    "claude": ClaudeAcpAgent,
    "cursor": CursorAcpAgent,
    "copilot": CopilotAcpAgent,
    "codex": CodexAcpAgent,
}


def create_acp_agent(
    agent_id: str,
    listener: Optional[IAcpAgentListener] = None,
    **kwargs,
) -> IAcpAgent:
    cls = _AGENTS.get(agent_id)
    if cls is None:
        raise RuntimeError(f"Unknown agent: {agent_id}")
    return cls(listener, **kwargs)
