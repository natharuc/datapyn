"""Claude Code ACP adapter."""

from __future__ import annotations

from typing import Optional

from ..agent import IAcpAgentListener
from .base import StdioAcpAgent


class ClaudeAcpAgent(StdioAcpAgent):
    """Claude lists LLMs via session models; reasoning is usually absent."""

    _exposes_models = True
    _exposes_reasoning = False

    def __init__(self, listener: Optional[IAcpAgentListener] = None, **kwargs):
        super().__init__("claude", listener, **kwargs)
