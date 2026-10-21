"""Global SQL confirmation policy, independent of connection and profile state."""

from __future__ import annotations

import json
from pathlib import Path

from .data_tools import atomic_destination
from .paths import state_root

FILE_NAME = "sql_safety_settings.json"


def settings_path():
    return state_root() / FILE_NAME


def settings_get(path=None):
    file = Path(path) if path is not None else settings_path()
    if not file.is_file():
        return {"confirm_destructive_sql": True}
    if file.stat().st_size > 4096:
        raise ValueError("SQL safety settings exceed 4 KiB")
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("confirm_destructive_sql"), bool):
        raise ValueError("confirm_destructive_sql must be a boolean")
    return {"confirm_destructive_sql": value["confirm_destructive_sql"]}


def settings_set(params, path=None):
    value = params.get("confirm_destructive_sql") if isinstance(params, dict) else None
    if not isinstance(value, bool):
        raise ValueError("confirm_destructive_sql must be a boolean")
    file = Path(path) if path is not None else settings_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(file) as temporary:
        temporary.write_text(json.dumps({"confirm_destructive_sql": value}), encoding="utf-8")
    return {"confirm_destructive_sql": value}
