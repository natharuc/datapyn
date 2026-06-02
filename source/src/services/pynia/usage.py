"""Provider-specific usage and limit summaries for the Pynia chat UI."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.language import S

from .settings import get_provider_secret, get_pynia_settings
from .types import PROVIDERS, ProviderId

logger = logging.getLogger(__name__)


def _pynia():
    return S.pynia if hasattr(S, "pynia") else S.copilot


def _provider_label(provider_id: ProviderId) -> str:
    p = _pynia()
    keys = {
        "openai": "provider_openai",
        "openrouter": "provider_openrouter",
        "anthropic": "provider_anthropic",
        "copilot": "provider_copilot",
    }
    return getattr(p, keys.get(provider_id, "title"), provider_id)


def fetch_openrouter_credits(api_key: str) -> Dict[str, Any]:
    try:
        import requests

        resp = requests.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=12,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json().get("data") or resp.json()
        total = data.get("total_credits")
        usage = data.get("total_usage")
        if total is None and usage is None:
            return {}
        remaining = None
        if total is not None and usage is not None:
            remaining = float(total) - float(usage)
        return {
            "total_credits": total,
            "total_usage": usage,
            "remaining_credits": remaining,
        }
    except Exception as exc:
        logger.debug("OpenRouter credits fetch failed: %s", exc)
        return {}


def _token_usage_snapshot(
    provider_id: ProviderId,
    model: str,
    models: List[Dict[str, Any]],
) -> Dict[str, Any]:
    p = _pynia()
    label = _provider_label(provider_id)
    multiplier = 1.0
    for item in models:
        if item.get("id") == model:
            multiplier = item.get("multiplier", 1.0)
            break

    snapshot: Dict[str, Any] = {
        "available": False,
        "provider_id": provider_id,
        "provider_name": label,
        "multiplier": multiplier,
        "show_runtime": False,
        "show_subscription": False,
        "limits_url": "",
    }

    if provider_id == "openai":
        snapshot.update(
            {
                "limits_summary": p.limits_openai_summary,
                "limits_detail": p.limits_openai_detail,
                "limits_url": "https://platform.openai.com/usage",
            }
        )
    elif provider_id == "openrouter":
        snapshot.update(
            {
                "limits_summary": p.limits_openrouter_summary,
                "limits_detail": p.limits_openrouter_detail,
                "limits_url": "https://openrouter.ai/settings/credits",
            }
        )
        token = get_provider_secret("openrouter")
        if token:
            credits = fetch_openrouter_credits(token)
            if credits:
                snapshot["available"] = True
                remaining = credits.get("remaining_credits")
                usage = credits.get("total_usage")
                total = credits.get("total_credits")
                if remaining is not None:
                    snapshot["remaining_percentage"] = None
                    snapshot["used"] = usage
                    snapshot["total"] = total
                    snapshot["limits_summary"] = p.limits_openrouter_credits.format(
                        remaining=f"{remaining:.2f}",
                        total=f"{float(total):.2f}" if total is not None else "?",
                    )
                elif usage is not None:
                    snapshot["used"] = usage
                    snapshot["limits_summary"] = p.limits_openrouter_usage.format(usage=f"{float(usage):.2f}")
    elif provider_id == "anthropic":
        snapshot.update(
            {
                "limits_summary": p.limits_anthropic_summary,
                "limits_detail": p.limits_anthropic_detail,
                "limits_url": "https://console.anthropic.com/settings/usage",
            }
        )
    else:
        snapshot["limits_summary"] = p.limits_generic_summary.format(provider=label)
        snapshot["limits_detail"] = p.limits_generic_detail

    if multiplier and multiplier != 1.0:
        snapshot["limits_detail"] = (
            snapshot.get("limits_detail", "")
            + "\n"
            + p.limits_model_multiplier.format(multiplier=multiplier)
        ).strip()

    return snapshot


def build_pynia_usage_payload(
    provider_id: ProviderId,
    *,
    model: str = "",
    usage_snapshot: Optional[Dict[str, Any]] = None,
    models: Optional[List[Dict[str, Any]]] = None,
    username: str = "",
    cli_status: Optional[Dict[str, Any]] = None,
    updating: bool = False,
) -> Dict[str, Any]:
    """Merge provider limits with optional Copilot quota/runtime metadata."""
    p = _pynia()
    models = models or []
    model = model or get_pynia_settings().selected_model(provider_id)

    if provider_id == "copilot":
        from src.services.copilot.copilot_cli_manager import merge_usage_with_runtime

        base = dict(usage_snapshot or {})
        payload = merge_usage_with_runtime(base, username=username, cli_status=cli_status)
        payload["provider_id"] = "copilot"
        payload["provider_name"] = _provider_label("copilot")
        payload["show_runtime"] = True
        payload["show_subscription"] = True
        if payload.get("available"):
            payload.setdefault("limits_summary", p.limits_copilot_included)
        else:
            payload.setdefault("limits_summary", p.limits_copilot_unknown)
        payload["limits_detail"] = p.limits_copilot_detail
        payload["limits_url"] = "https://github.com/settings/copilot"
        payload["show_account_switch"] = True
        if updating:
            payload["updating"] = True
        return payload

    payload = _token_usage_snapshot(provider_id, model, models)
    payload["show_account_switch"] = False
    payload["username"] = username
    if updating:
        payload["updating"] = True
    return payload
