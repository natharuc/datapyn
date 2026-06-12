"""Build connector picker payloads for the Pynia chat account switch UI."""

from __future__ import annotations

from typing import Any, Dict, List

from src.services.pynia.labels import pynia_label
from src.services.pynia.settings import get_pynia_settings
from src.services.pynia.types import ProviderId


def _provider_label(provider_id: ProviderId) -> str:
    keys = {
        "openai": "provider_openai",
        "openrouter": "provider_openrouter",
        "anthropic": "provider_anthropic",
        "copilot": "provider_copilot",
    }
    return pynia_label(keys.get(provider_id, "title"), provider_id)


def _ready_subtitle(provider_id: ProviderId, ready: bool) -> str:
    if ready:
        username = get_pynia_settings().username(provider_id)
        if username and username != provider_id:
            return username
        return pynia_label("account_ready", "Ready to switch")
    return pynia_label("account_needs_login", "Sign in required")


def build_connector_picker_payload() -> Dict[str, Any]:
    """List connectors (and Copilot GitHub accounts) for the switch UI."""
    settings = get_pynia_settings()
    active_provider: ProviderId = settings.active_provider
    active_label = _provider_label(active_provider)
    connectors: List[Dict[str, Any]] = []
    github_accounts: List[Dict[str, Any]] = []

    for pid in ("openrouter", "openai", "anthropic"):
        ready = settings.is_authenticated(pid)
        label = _provider_label(pid)
        connectors.append(
            {
                "username": pid,
                "provider_id": pid,
                "display_name": label,
                "subtitle": _ready_subtitle(pid, ready),
                "provider_label": label,
                "ready": ready,
                "kind": "provider",
            }
        )

    from src.services.copilot import get_copilot_auth_service

    copilot_label = _provider_label("copilot")
    gh_payload = get_copilot_auth_service().build_account_picker_payload()
    gh_accounts = gh_payload.get("accounts") if isinstance(gh_payload, dict) else []
    if gh_accounts:
        for item in gh_accounts:
            if not isinstance(item, dict):
                continue
            username = str(item.get("username") or "").strip()
            if not username:
                continue
            ready = bool(item.get("ready"))
            github_accounts.append(
                {
                    "username": username,
                    "provider_id": "copilot",
                    "display_name": f"@{username}",
                    "subtitle": _ready_subtitle("copilot", ready),
                    "provider_label": copilot_label,
                    "ready": ready,
                    "kind": "copilot_account",
                }
            )
    else:
        ready = settings.is_authenticated("copilot")
        connectors.append(
            {
                "username": "copilot",
                "provider_id": "copilot",
                "display_name": copilot_label,
                "subtitle": _ready_subtitle("copilot", ready),
                "provider_label": copilot_label,
                "ready": ready,
                "kind": "provider",
            }
        )

    # Flat list for legacy consumers; sections drive the WebView layout.
    accounts = connectors + github_accounts

    current = active_provider
    if active_provider == "copilot":
        from src.services.copilot.copilot_settings import get_copilot_settings

        gh_user = get_copilot_settings().chat_username
        if gh_user:
            current = gh_user

    return {
        "current": current,
        "active_provider": active_provider,
        "active_provider_label": active_label,
        "accounts": accounts,
        "sections": [
            {
                "id": "connectors",
                "title": pynia_label("connector_picker_section_connectors", "AI connectors"),
                "accounts": connectors,
            },
            {
                "id": "github",
                "title": pynia_label("connector_picker_section_github", "GitHub Copilot accounts"),
                "accounts": github_accounts,
            },
        ],
    }
