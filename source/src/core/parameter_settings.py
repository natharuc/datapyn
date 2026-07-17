"""Shared/global parameter delimiter settings (QSettings-backed)."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

# Wrapped-symmetric delimiter presets: (open_token, close_token).
SHARED_PARAMETER_DELIMITERS: dict[str, tuple[str, str]] = {
    "double_brace": ("{{", "}}"),
    "double_colon": ("::", "::"),
    "single_brace": ("{", "}"),
}

DEFAULT_SHARED_PARAMETER_DELIMITER = "double_brace"


def get_shared_parameter_delimiter() -> str:
    """Return the configured shared parameter delimiter preset key."""
    key = QSettings("DataPyn", "DataPyn").value(
        "parameters/shared_delimiter",
        DEFAULT_SHARED_PARAMETER_DELIMITER,
        type=str,
    )
    if key not in SHARED_PARAMETER_DELIMITERS:
        return DEFAULT_SHARED_PARAMETER_DELIMITER
    return key


def get_shared_parameter_delimiter_tokens() -> tuple[str, str]:
    """Return the (open, close) tokens for the configured delimiter preset."""
    return SHARED_PARAMETER_DELIMITERS.get(
        get_shared_parameter_delimiter(),
        SHARED_PARAMETER_DELIMITERS[DEFAULT_SHARED_PARAMETER_DELIMITER],
    )


def set_shared_parameter_delimiter(key: str) -> None:
    """Persist the shared parameter delimiter preset key."""
    if key not in SHARED_PARAMETER_DELIMITERS:
        key = DEFAULT_SHARED_PARAMETER_DELIMITER
    QSettings("DataPyn", "DataPyn").setValue("parameters/shared_delimiter", key)
