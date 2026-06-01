"""
Copilot CLI discovery, version checks, and updates for DataPyn.

DataPyn uses the GitHub Copilot SDK, which shells out to the Copilot CLI.
This module reports which CLI binary is active and can update it via npm.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_NPM_LATEST_URL = "https://registry.npmjs.org/@github/copilot/latest"
_PYPI_SDK_URL = "https://pypi.org/pypi/github-copilot-sdk/json"
_SDK_PACKAGE = "github-copilot-sdk"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

# Progress phase keys consumed by the WebView usage panel (mapped to i18n).
PHASE_CHECKING = "checking"
PHASE_DOWNLOADING_CLI = "downloading_cli"
PHASE_INSTALLING_CLI = "installing_cli"
PHASE_DOWNLOADING_SDK = "downloading_sdk"
PHASE_INSTALLING_SDK = "installing_sdk"
PHASE_COMPLETE = "complete"


def parse_copilot_cli_version(text: str) -> Tuple[int, int, int]:
    """Parse 'GitHub Copilot CLI 1.0.56.' into (1, 0, 56)."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def format_version(version: Tuple[int, int, int]) -> str:
    if not version or version == (0, 0, 0):
        return ""
    return f"{version[0]}.{version[1]}.{version[2]}"


def version_tuple_from_string(text: str) -> Tuple[int, int, int]:
    return parse_copilot_cli_version(text or "")


def compare_versions(left: Tuple[int, int, int], right: Tuple[int, int, int]) -> int:
    if left == right:
        return 0
    return 1 if left > right else -1


def get_sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("github-copilot-sdk")
    except Exception:
        return ""


def _cli_env() -> dict:
    return {**os.environ, "ELECTRON_RUN_AS_NODE": ""}


def read_cli_version(cli_path: str, *, no_auto_update: bool = True) -> Tuple[int, int, int]:
    """Return semver tuple for a Copilot CLI binary."""
    if not cli_path:
        return (0, 0, 0)
    args = [cli_path]
    if no_auto_update:
        args.append("--no-auto-update")
    args.append("--version")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=12,
            env=_cli_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or "Cannot find" in output:
            return (0, 0, 0)
        return parse_copilot_cli_version(output)
    except Exception:
        return (0, 0, 0)


def detect_cli_source(cli_path: str) -> str:
    if not cli_path:
        return "unknown"
    normalized = str(Path(cli_path)).replace("\\", "/").lower()
    if "_meipass" in normalized or "/copilot/bin/" in normalized:
        return "bundled"
    if "/microsoft/winget/packages/github.copilot" in normalized:
        return "winget"
    if "/npm/" in normalized:
        return "npm"
    if "code - insiders" in normalized or "/code/user/globalstorage/github.copilot-chat" in normalized:
        return "vscode"
    if "/cursor/user/globalstorage/github.copilot-chat" in normalized:
        return "cursor"
    if "/.copilot/" in normalized:
        return "user"
    return "path"


def _source_label(source: str) -> str:
    labels = {
        "npm": "npm global",
        "winget": "WinGet",
        "vscode": "VS Code",
        "cursor": "Cursor",
        "bundled": "DataPyn bundle",
        "user": "user install",
        "path": "PATH",
        "unknown": "unknown",
    }
    return labels.get(source, source)


def fetch_latest_sdk_version(timeout: float = 10.0) -> Optional[str]:
    """Return the latest github-copilot-sdk version from PyPI."""
    try:
        request = Request(_PYPI_SDK_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        version = (payload.get("info") or {}).get("version")
        return str(version) if version else None
    except Exception as exc:
        logger.info("Could not fetch latest Copilot SDK version: %s", exc)
        return None


def can_update_sdk() -> bool:
    """Return True when DataPyn can upgrade the Python SDK in this environment."""
    if getattr(sys, "frozen", False):
        return False
    return bool(sys.executable)


def fetch_latest_npm_version(timeout: float = 10.0) -> Optional[str]:
    """Return the latest @github/copilot version from the npm registry."""
    try:
        request = Request(_NPM_LATEST_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        version = payload.get("version")
        return str(version) if version else None
    except Exception as exc:
        logger.info("Could not fetch latest Copilot CLI version: %s", exc)
        return None


def get_active_cli_info() -> Dict[str, Any]:
    """Return metadata for the newest working Copilot CLI DataPyn would use."""
    from .copilot_client_sdk import _pick_newest_copilot_cli

    cli_path, version = _pick_newest_copilot_cli()
    source = detect_cli_source(cli_path)
    return {
        "installed": bool(cli_path and version != (0, 0, 0)),
        "path": cli_path or "",
        "version": format_version(version),
        "version_tuple": list(version),
        "source": source,
        "source_label": _source_label(source),
    }


def build_cli_status(*, check_latest: bool = True) -> Dict[str, Any]:
    """Build CLI + SDK status payload for the usage panel."""
    info = get_active_cli_info()
    sdk_version = get_sdk_version()
    latest_cli = fetch_latest_npm_version() if check_latest else info.get("latest_version")
    latest_sdk = fetch_latest_sdk_version() if check_latest else info.get("latest_sdk_version")
    current_tuple = tuple(info.get("version_tuple") or (0, 0, 0))
    latest_cli_tuple = version_tuple_from_string(latest_cli or "")
    latest_sdk_tuple = version_tuple_from_string(latest_sdk or "")
    current_sdk_tuple = version_tuple_from_string(sdk_version or "")
    cli_update_available = bool(
        info.get("installed")
        and latest_cli_tuple != (0, 0, 0)
        and compare_versions(current_tuple, latest_cli_tuple) < 0
    )
    sdk_update_available = bool(
        latest_sdk_tuple != (0, 0, 0)
        and current_sdk_tuple != (0, 0, 0)
        and compare_versions(current_sdk_tuple, latest_sdk_tuple) < 0
    )
    npm_available = bool(shutil.which("npm"))
    sdk_updatable = can_update_sdk()
    can_update_cli = bool(
        info.get("installed")
        and info.get("source") != "bundled"
        and npm_available
        and cli_update_available
    )
    can_update_sdk_flag = bool(sdk_updatable and sdk_update_available)
    return {
        **info,
        "sdk_version": sdk_version,
        "latest_version": latest_cli or "",
        "latest_sdk_version": latest_sdk or "",
        "update_available": cli_update_available or sdk_update_available,
        "cli_update_available": cli_update_available,
        "sdk_update_available": sdk_update_available,
        "can_update": can_update_cli or can_update_sdk_flag,
        "can_update_cli": can_update_cli,
        "can_update_sdk": can_update_sdk_flag,
        "npm_available": npm_available,
    }


def merge_usage_with_runtime(
    usage_snapshot: Dict[str, Any],
    *,
    username: str = "",
    cli_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach account and runtime metadata to a usage snapshot."""
    payload = dict(usage_snapshot or {})
    payload["username"] = username or payload.get("username") or ""
    payload["subscription_url"] = payload.get("subscription_url") or "https://github.com/settings/copilot"
    if cli_status:
        payload["cli"] = dict(cli_status)
        payload["sdk"] = {"version": cli_status.get("sdk_version") or get_sdk_version()}
    else:
        payload["cli"] = {}
        payload["sdk"] = {"version": get_sdk_version()}
    return payload


def update_copilot_sdk(
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, bool]:
    """
    Update github-copilot-sdk via pip.

    Returns (success, message, requires_restart).
    """
    emit = progress or (lambda _message: None)
    if not can_update_sdk():
        return False, "SDK updates require a non-bundled DataPyn install.", False

    emit(PHASE_DOWNLOADING_SDK)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", _SDK_PACKAGE],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "Copilot SDK update timed out.", False
    except Exception as exc:
        return False, str(exc), False

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        detail = output.splitlines()[-1] if output else f"exit code {result.returncode}"
        return False, detail, False

    emit(PHASE_INSTALLING_SDK)
    version = get_sdk_version() or "latest"
    emit(PHASE_COMPLETE)
    return True, f"Copilot SDK updated to {version}. Restart DataPyn to apply.", True


def update_copilot_cli(
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Update the Copilot CLI via npm.

    Returns (success, message).
    """
    emit = progress or (lambda _message: None)
    npm_path = shutil.which("npm")
    if not npm_path:
        return False, "npm was not found on PATH. Install Node.js 22+ to update Copilot CLI."

    info = get_active_cli_info()
    emit(PHASE_DOWNLOADING_CLI)
    if not info.get("installed"):
        emit(PHASE_INSTALLING_CLI)

    env = os.environ.copy()
    env.setdefault("npm_config_ignore_scripts", "false")

    try:
        result = subprocess.run(
            [npm_path, "install", "-g", "@github/copilot@latest"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "Copilot CLI update timed out."
    except Exception as exc:
        return False, str(exc)

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        detail = output.splitlines()[-1] if output else f"exit code {result.returncode}"
        return False, detail

    emit(PHASE_INSTALLING_CLI)
    refreshed = build_cli_status(check_latest=False)
    version = refreshed.get("version") or "latest"
    emit(PHASE_COMPLETE)
    return True, f"Copilot CLI updated to {version}."


def update_copilot_runtime(
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, bool]:
    """
    Update Copilot CLI (npm) and Python SDK (pip) when newer versions exist.

    Returns (success, message, requires_restart).
    """
    emit = progress or (lambda _message: None)
    messages: list[str] = []
    requires_restart = False
    errors: list[str] = []

    emit(PHASE_CHECKING)
    status = build_cli_status(check_latest=True)

    if not status.get("update_available"):
        return False, "Copilot runtime is already up to date.", False

    if status.get("can_update_cli"):
        ok, message = update_copilot_cli(progress=emit)
        if ok:
            messages.append(message)
        else:
            errors.append(message)

    if status.get("can_update_sdk"):
        ok, message, restart = update_copilot_sdk(progress=emit)
        if ok:
            requires_restart = requires_restart or restart
            messages.append(message)
        else:
            errors.append(message)

    if messages and errors:
        return True, " ".join(messages + [f"Warning: {err}" for err in errors]), requires_restart
    if messages:
        emit(PHASE_COMPLETE)
        return True, " ".join(messages), requires_restart
    if errors:
        return False, errors[0], False
    return False, "No Copilot runtime updates are available.", False
