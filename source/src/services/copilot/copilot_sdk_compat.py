"""Compatibility patches for the GitHub Copilot Python SDK."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)
_PATCHED = False


def coerce_sdk_timestamp(value: Any) -> int:
    """Normalize ping/event timestamps from newer Copilot CLI responses."""
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, bool):
        raise ValueError(f"invalid timestamp: {value!r}")
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if not text:
        raise ValueError("timestamp is required")
    if text.isdigit():
        return int(text)

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _patch_model_billing(sdk_client: Any) -> None:
    model_billing = getattr(sdk_client, "ModelBilling", None)
    if model_billing is None:
        return

    original_from_dict = model_billing.from_dict

    def from_dict_compat(obj: Any):
        if isinstance(obj, dict) and obj.get("multiplier") is None:
            patched = dict(obj)
            patched["multiplier"] = 1.0
            return original_from_dict(patched)
        return original_from_dict(obj)

    model_billing.from_dict = staticmethod(from_dict_compat)
    logger.debug("Applied Copilot SDK ModelBilling compatibility patch")


def _patch_ping_response(sdk_client: Any) -> None:
    ping_response = getattr(sdk_client, "PingResponse", None)
    if ping_response is None:
        return

    original_from_dict = ping_response.from_dict

    def from_dict_compat(obj: Any):
        if not isinstance(obj, dict):
            return original_from_dict(obj)

        message = obj.get("message")
        timestamp = obj.get("timestamp")
        protocol_version = obj.get("protocolVersion")
        if message is None or timestamp is None or protocol_version is None:
            return original_from_dict(obj)

        try:
            return ping_response(
                str(message),
                coerce_sdk_timestamp(timestamp),
                int(protocol_version),
            )
        except (TypeError, ValueError):
            return original_from_dict(obj)

    ping_response.from_dict = staticmethod(from_dict_compat)
    logger.debug("Applied Copilot SDK PingResponse compatibility patch")


def apply_sdk_compat_patches() -> None:
    """Patch SDK parsing for newer Copilot CLI wire formats."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        from copilot import client as sdk_client
    except ImportError:
        return

    _patch_model_billing(sdk_client)
    _patch_ping_response(sdk_client)
    _PATCHED = True


def is_runtime_update_error(message: str) -> bool:
    """Return True when auth/init failed due to outdated Copilot runtime."""
    text = str(message or "").lower()
    markers = (
        "modelbilling",
        "missing required field 'multiplier'",
        "missing required field \"multiplier\"",
        "pingresponse",
        "invalid literal for int()",
        "protocol version mismatch",
        "github-copilot-sdk",
        "copilot cli",
        "cannot find github copilot cli",
    )
    return any(marker in text for marker in markers)
