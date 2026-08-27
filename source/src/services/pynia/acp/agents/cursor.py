"""Cursor ACP adapter."""

from __future__ import annotations

from typing import Optional

from ..agent import IAcpAgentListener
from .base import StdioAcpAgent


class CursorAcpAgent(StdioAcpAgent):
    """Cursor often omits model/reasoning config; do not invent IDs."""

    _exposes_models = False
    _exposes_reasoning = False

    def __init__(self, listener: Optional[IAcpAgentListener] = None, **kwargs):
        super().__init__("cursor", listener, **kwargs)
