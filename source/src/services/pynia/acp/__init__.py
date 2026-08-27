"""Pynia ACP host — DataPyn as an Agent Client Protocol client."""

from .agent import GrantResult, IAcpAgent
from .agents.factory import create_acp_agent
from .binding import TabChatState
from .catalog import AGENT_IDS, AgentSpec, get_agent, list_agents
from .host import PyniaAcpHost
from .pool import AcpProcessPool
from .service import AcpSessionService

__all__ = [
    "AGENT_IDS",
    "AgentSpec",
    "GrantResult",
    "IAcpAgent",
    "create_acp_agent",
    "get_agent",
    "list_agents",
    "TabChatState",
    "PyniaAcpHost",
    "AcpProcessPool",
    "AcpSessionService",
]
