"""
Pynia — DataPyn's multi-provider AI agent.

Connectors: OpenAI, OpenRouter, Anthropic (Claude), GitHub Copilot (device/MFA).
"""

from .agent_client import PyniaAgentClient
from .system_prompt import build_request_prompt, build_system_prompt
from .auth_service import PyniaAuthService, get_pynia_auth_service, reset_pynia_auth_service
from .settings import get_pynia_settings, get_provider_secret, set_provider_secret
from .types import DEFAULT_PROVIDER, PROVIDERS, ProviderId, ProviderInfo

__all__ = [
    "PyniaAgentClient",
    "build_system_prompt",
    "build_request_prompt",
    "PyniaAuthService",
    "get_pynia_auth_service",
    "reset_pynia_auth_service",
    "get_pynia_settings",
    "get_provider_secret",
    "set_provider_secret",
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "ProviderId",
    "ProviderInfo",
]
