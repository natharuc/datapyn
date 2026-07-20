"""Shared/global parameter delimiter settings (QSettings-backed)."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

DEFAULT_SHARED_PARAMETER_DELIMITER = "{{name}}"

# Legacy preset keys migrated to template patterns.
_LEGACY_PRESET_TO_TEMPLATE: dict[str, str] = {
    "double_brace": "{{name}}",
    "double_colon": "::name::",
    "single_brace": "{name}",
}


def parse_delimiter_template(template: str) -> tuple[str, str] | None:
    """Split *template* on ``name`` into (open, close) tokens, or None if invalid."""
    if template.count("name") != 1:
        return None
    open_t, close_t = template.split("name", 1)
    if not open_t or not close_t:
        return None
    return open_t, close_t


def _resolve_stored_delimiter(value: str) -> str:
    """Normalize a stored delimiter value (legacy presets, empty strings)."""
    value = (value or "").strip()
    if not value:
        return DEFAULT_SHARED_PARAMETER_DELIMITER
    return _LEGACY_PRESET_TO_TEMPLATE.get(value, value)


def get_shared_parameter_delimiter() -> str:
    """Return the configured shared parameter delimiter template (e.g. ``{{name}}``)."""
    stored = QSettings("DataPyn", "DataPyn").value(
        "parameters/shared_delimiter",
        DEFAULT_SHARED_PARAMETER_DELIMITER,
        type=str,
    )
    return _resolve_stored_delimiter(stored)


def get_shared_parameter_delimiter_tokens() -> tuple[str, str]:
    """Return the (open, close) tokens for the configured delimiter template."""
    tokens = parse_delimiter_template(get_shared_parameter_delimiter())
    if tokens is None:
        fallback = parse_delimiter_template(DEFAULT_SHARED_PARAMETER_DELIMITER)
        assert fallback is not None
        return fallback
    return tokens


def set_shared_parameter_delimiter(template: str) -> None:
    """Persist the shared parameter delimiter template."""
    resolved = _resolve_stored_delimiter(template)
    QSettings("DataPyn", "DataPyn").setValue("parameters/shared_delimiter", resolved)
