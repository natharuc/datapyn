"""Windows-safe subprocess helpers for Copilot CLI discovery and tooling."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NO_WINDOW = CREATE_NO_WINDOW if sys.platform == "win32" else 0

_SUBPROCESS_PATCHED = False
_ORIGINAL_POPEN = None
_ORIGINAL_RUN = None


def hidden_startupinfo() -> Optional[Any]:
    """Return STARTUPINFO that hides console windows on Windows."""
    if sys.platform != "win32":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def _apply_hidden_flags(kwargs: dict) -> dict:
    """Merge CREATE_NO_WINDOW + hidden STARTUPINFO into subprocess kwargs."""
    merged = dict(kwargs)
    if sys.platform != "win32":
        return merged
    merged["creationflags"] = merged.get("creationflags", 0) | _CREATE_NO_WINDOW
    merged.setdefault("startupinfo", hidden_startupinfo())
    return merged


def install_hidden_subprocess_patch() -> None:
    """Ensure all subprocess.run/Popen calls hide consoles on Windows.

    The GitHub Copilot SDK spawns the CLI via subprocess; older SDK releases
    did not pass CREATE_NO_WINDOW. Patching the stdlib subprocess module keeps
    quota/model refresh and chat RPCs from flashing CMD windows in GUI builds.
    """
    global _SUBPROCESS_PATCHED, _ORIGINAL_POPEN, _ORIGINAL_RUN
    if _SUBPROCESS_PATCHED or sys.platform != "win32":
        return

    _ORIGINAL_POPEN = subprocess.Popen
    _ORIGINAL_RUN = subprocess.run

    def patched_popen(*args, **kwargs):
        return _ORIGINAL_POPEN(*args, **_apply_hidden_flags(kwargs))

    def patched_run(*args, **kwargs):
        return _ORIGINAL_RUN(*args, **_apply_hidden_flags(kwargs))

    subprocess.Popen = patched_popen  # type: ignore[assignment]
    subprocess.run = patched_run  # type: ignore[assignment]
    _SUBPROCESS_PATCHED = True
    logger.debug("Installed hidden subprocess patch for Copilot on Windows")


def run_hidden(
    args,
    *,
    capture_output: bool = True,
    text: bool = False,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
    **kwargs,
):
    """subprocess.run without flashing console windows on Windows."""
    run_kwargs = dict(kwargs)
    if capture_output:
        run_kwargs.setdefault("stdout", subprocess.PIPE)
        run_kwargs.setdefault("stderr", subprocess.PIPE)
    if text:
        run_kwargs["text"] = True
    if env is not None:
        run_kwargs["env"] = env
    return subprocess.run(args, timeout=timeout, **_apply_hidden_flags(run_kwargs))


def popen_hidden(args, **kwargs):
    """subprocess.Popen without flashing console windows on Windows."""
    return subprocess.Popen(args, **_apply_hidden_flags(kwargs))


def configure_hidden_qprocess(process) -> None:
    """Hide console windows for PyQt6 QProcess on Windows."""
    if sys.platform != "win32":
        return

    def _modifier(args):
        args.setCreationFlags(args.creationFlags() | CREATE_NO_WINDOW)

    if hasattr(process, "setCreateProcessArgumentsModifier"):
        process.setCreateProcessArgumentsModifier(_modifier)
