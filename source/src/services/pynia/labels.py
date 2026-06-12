"""Pynia UI label helper with copilot-section fallback."""

from __future__ import annotations

from src.language import S


def pynia_label(key: str, default: str = "") -> str:
    """Resolve a chat label from ``pynia`` then legacy ``copilot`` i18n sections."""
    if hasattr(S, "pynia"):
        value = getattr(S.pynia, key, None)
        if isinstance(value, str) and value and value != f"[{key}]" and not (
            value.startswith("[") and value.endswith("]")
        ):
            return value
    if hasattr(S, "copilot"):
        legacy = getattr(S.copilot, key, None)
        if isinstance(legacy, str) and legacy and legacy != f"[{key}]" and not (
            legacy.startswith("[") and legacy.endswith("]")
        ):
            return legacy
    return default or key
