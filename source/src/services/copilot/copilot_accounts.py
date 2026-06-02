"""GitHub account discovery and switching for Copilot Chat."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from .copilot_process import run_hidden

_DEFAULT_HOST = "github.com"


def _gh_executable() -> str:
    import shutil

    return shutil.which("gh") or ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_gh_accounts(hostname: str = _DEFAULT_HOST) -> List[Dict[str, Any]]:
    """Return GitHub CLI accounts for a host."""
    gh_path = _gh_executable()
    if not gh_path:
        return []

    try:
        result = run_hidden(
            [gh_path, "auth", "status", "-h", hostname, "--json", "hosts"],
            text=True,
            timeout=15,
        )
    except Exception as exc:
        logger.info("Could not read gh auth status: %s", exc)
        return []

    if result.returncode != 0 and not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        logger.info("Invalid gh auth status JSON")
        return []

    hosts = payload.get("hosts") if isinstance(payload, dict) else {}
    entries = hosts.get(hostname) if isinstance(hosts, dict) else []
    if not isinstance(entries, list):
        return []

    accounts: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        login = str(entry.get("login") or "").strip()
        if not login:
            continue
        state = str(entry.get("state") or "").strip().lower()
        accounts.append({
            "username": login,
            "login": login,
            "active": bool(entry.get("active")),
            "ready": state == "success",
            "state": state or "unknown",
            "source": "gh",
        })
    return accounts


def get_active_gh_login(hostname: str = _DEFAULT_HOST) -> str:
    for account in list_gh_accounts(hostname):
        if account.get("active"):
            return str(account.get("username") or "")
    return ""


def switch_gh_account(username: str, hostname: str = _DEFAULT_HOST) -> Tuple[bool, str]:
    """Switch the active GitHub CLI account."""
    gh_path = _gh_executable()
    login = str(username or "").strip()
    if not gh_path:
        return False, "GitHub CLI is not installed."
    if not login:
        return False, "Account username is required."

    try:
        result = run_hidden(
            [gh_path, "auth", "switch", "-h", hostname, "-u", login],
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out while switching GitHub account."
    except Exception as exc:
        return False, str(exc)

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        detail = output.splitlines()[-1] if output else f"exit code {result.returncode}"
        return False, detail
    return True, f"Switched to @{login}"


def build_account_picker_payload(
    known_accounts: List[Dict[str, Any]],
    *,
    current_username: str = "",
    gh_accounts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Merge DataPyn account history with gh CLI sessions."""
    gh_accounts = gh_accounts if gh_accounts is not None else list_gh_accounts()
    merged: Dict[str, Dict[str, Any]] = {}

    for item in known_accounts or []:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        if not username:
            continue
        merged[username] = {
            "username": username,
            "ready": False,
            "active": False,
            "last_used": item.get("last_used") or "",
            "source": "datapyn",
        }

    for gh in gh_accounts:
        username = str(gh.get("username") or "").strip()
        if not username:
            continue
        entry = merged.get(username, {
            "username": username,
            "ready": False,
            "active": False,
            "last_used": "",
            "source": "gh",
        })
        entry["ready"] = bool(gh.get("ready"))
        entry["active"] = bool(gh.get("active"))
        if entry.get("source") == "datapyn":
            entry["source"] = "datapyn+gh"
        else:
            entry["source"] = "gh"
        merged[username] = entry

    current = str(current_username or "").strip() or get_active_gh_login()
    accounts = list(merged.values())
    accounts.sort(key=lambda item: str(item.get("last_used") or ""), reverse=True)
    accounts.sort(
        key=lambda item: (
            0 if item.get("username") == current else 1,
            0 if item.get("ready") else 1,
        )
    )

    return {
        "current": current,
        "accounts": accounts,
        "gh_available": bool(_gh_executable()),
    }


def normalize_known_accounts(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        if not username or username in seen:
            continue
        seen.add(username)
        normalized.append({
            "username": username,
            "last_used": str(item.get("last_used") or ""),
            "added_at": str(item.get("added_at") or item.get("last_used") or _now_iso()),
        })
    return normalized
