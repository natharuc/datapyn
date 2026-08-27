"""OpenAI Codex ACP adapter."""

from __future__ import annotations

from typing import Optional

from ..agent import IAcpAgentListener
from .base import StdioAcpAgent


class CodexAcpAgent(StdioAcpAgent):
    """Codex exposes model + reasoning in configOptions."""

    _exposes_models = True
    _exposes_reasoning = True

    def __init__(self, listener: Optional[IAcpAgentListener] = None, **kwargs):
        super().__init__("codex", listener, **kwargs)
