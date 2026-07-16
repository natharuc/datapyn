"""Connection lifecycle settings (QSettings-backed)."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

DEFAULT_IDLE_TIMEOUT_SEC = 300
REAPER_INTERVAL_SEC = 60


def get_idle_timeout_sec() -> int:
    """Return idle disconnect timeout in seconds (0 disables reaper)."""
    return int(
        QSettings("DataPyn", "DataPyn").value(
            "connections/idle_timeout_sec",
            DEFAULT_IDLE_TIMEOUT_SEC,
        )
    )


def get_reaper_interval_sec() -> int:
    """Return how often the idle reaper runs (seconds)."""
    return REAPER_INTERVAL_SEC
