"""Global execution policy; changing it never changes a database connection."""

from __future__ import annotations

import json
from pathlib import Path

from .data_tools import atomic_destination
from .paths import state_root

FILE_NAME = "transaction_settings.json"


def settings_path():
    # This setting applies across workspace profiles, unlike their catalogs.
    return state_root() / FILE_NAME


def settings_get(path=None):
    file = Path(path) if path is not None else settings_path()
    if not file.is_file():
        return {"automatic_transactions": True}
    if file.stat().st_size > 4096:
        raise ValueError("Transaction settings exceed 4 KiB")
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("automatic_transactions"), bool):
        raise ValueError("automatic_transactions must be a boolean")
    return {"automatic_transactions": value["automatic_transactions"]}


def settings_set(params, path=None):
    value = params.get("automatic_transactions")
    if not isinstance(value, bool):
        raise ValueError("automatic_transactions must be a boolean")
    file = Path(path) if path is not None else settings_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(file) as temporary:
        temporary.write_text(json.dumps({"automatic_transactions": value}), encoding="utf-8")
    return {"automatic_transactions": value}


def validate_execution_options(params):
    for field in ("automatic_transactions", "disable_automatic_transactions"):
        if field in params and not isinstance(params[field], bool):
            raise ValueError(f"{field} must be a boolean")


def context_automatic_transactions(params):
    """Read a routed snapshot or public metadata mode without storage access."""
    snapshot = params.get("_automatic_transactions_snapshot")
    if isinstance(snapshot, bool):
        return snapshot
    return params.get("automatic_transactions") is not False and params.get("disable_automatic_transactions") is not True


def editor_context_key(params):
    key = "|".join(str(params.get(name) or "") for name in ("connection_id", "database", "schema")) or "default"
    if params.get("block_id"):
        key += "|block:" + str(params["block_id"])
    if params.get("scope_inherited") is True:
        key += "|scope:inherited"
    if not context_automatic_transactions(params):
        key += "|transactions:manual"
    return key


def effective_automatic_transactions(params):
    """Capture the authoritative global option when an operation is submitted.

    A submitted snapshot may further disable automatic transactions, but it
    cannot override a global disable. A queued job retains this captured mode.
    """
    validate_execution_options(params)
    return (settings_get(params.get("_transaction_settings_path"))["automatic_transactions"]
            and params.get("automatic_transactions", True)
            and not params.get("disable_automatic_transactions", False))
