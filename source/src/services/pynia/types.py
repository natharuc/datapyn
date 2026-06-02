"""Pynia provider identifiers and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProviderId = Literal["openai", "openrouter", "anthropic", "copilot"]


@dataclass(frozen=True)
class ProviderInfo:
    id: ProviderId
    label_key: str
    auth_kind: Literal["api_token", "device_mfa"]
    default_base_url: str
    default_model: str


PROVIDERS: dict[ProviderId, ProviderInfo] = {
    "openai": ProviderInfo(
        id="openai",
        label_key="pynia.provider_openai",
        auth_kind="api_token",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
    ),
    "openrouter": ProviderInfo(
        id="openrouter",
        label_key="pynia.provider_openrouter",
        auth_kind="api_token",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o",
    ),
    "anthropic": ProviderInfo(
        id="anthropic",
        label_key="pynia.provider_anthropic",
        auth_kind="api_token",
        default_base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-20250514",
    ),
    "copilot": ProviderInfo(
        id="copilot",
        label_key="pynia.provider_copilot",
        auth_kind="device_mfa",
        default_base_url="",
        default_model="gpt-4o",
    ),
}

DEFAULT_PROVIDER: ProviderId = "copilot"
