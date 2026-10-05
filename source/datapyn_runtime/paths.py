"""Tauri-owned storage locations, independent from the PyQt application."""

from __future__ import annotations

import os
from pathlib import Path
import sys

APP_ID = "app.datapyn.tauri"


def state_root():
    explicit = os.environ.get("DATAPYN_RUNTIME_STATE_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return (base / APP_ID).expanduser().resolve()


def workspace_root():
    explicit = os.environ.get("DATAPYN_WORKSPACE_PATH")
    return Path(explicit).expanduser().resolve() if explicit else state_root()


def cache_root():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return (base / APP_ID / "cache").expanduser().resolve()


def snapshot_root():
    explicit = os.environ.get("DATAPYN_SNAPSHOT_ROOT")
    return Path(explicit).expanduser().resolve() if explicit else cache_root() / "session_snapshots"
