"""Crash reporter — files/updates a GitHub issue for an unhandled exception.

Strategy (per product decision):
1. If the GitHub CLI (``gh``) is available AND authenticated, search the
   repo's open issues for an existing report with the same crash signature.
   - Found → add a comment with the new occurrence (dedupe).
   - Not found → create a new issue labelled ``crash,bug``.
2. If ``gh`` is missing or not authenticated, fall back to opening the
   browser on the "new issue" page with a prefilled title/body.

The signature marker ``datapyn-crash:<sig>`` is embedded in the issue
title/body so the dedupe search is reliable.

All ``gh`` calls run off the UI thread (``CrashReporterWorker``) with a
generous timeout so the dialog stays responsive.
"""

from __future__ import annotations

import logging
import urllib.parse
import webbrowser
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

REPO = "natharuc/datapyn"
SIGNATURE_PREFIX = "datapyn-crash"
_GH_TIMEOUT = 25.0


def _gh_executable() -> str:
    try:
        from src.services.copilot.copilot_client_sdk import _gh_executable as _gh

        return _gh() or ""
    except Exception:
        import shutil

        return shutil.which("gh") or ""


def _is_gh_logged_in(gh_path: str) -> bool:
    try:
        from src.services.copilot.copilot_client_sdk import _is_gh_logged_in

        return bool(_is_gh_logged_in(gh_path))
    except Exception:
        return False


def _run_gh(args: list[str], *, timeout: float = _GH_TIMEOUT) -> tuple[int, str]:
    """Run a gh command hidden; return (returncode, combined_output)."""
    gh = _gh_executable()
    if not gh:
        return 127, "gh not found"
    try:
        from src.services.copilot.copilot_process import run_hidden

        result = run_hidden([gh, *args], text=True, timeout=timeout)
        out = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
        return int(result.returncode or 0), out
    except Exception as exc:
        return 1, str(exc)


def _find_existing_issue(signature: str) -> Optional[int]:
    """Return the issue number of an open issue matching the signature, or None."""
    marker = f"{SIGNATURE_PREFIX}:{signature}"
    code, out = _run_gh(
        [
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--search",
            marker,
            "--limit",
            "10",
            "--json",
            "number,title",
        ]
    )
    if code != 0 or not out:
        return None
    try:
        import json

        items = json.loads(out)
        for item in items:
            title = str(item.get("title", ""))
            if marker in title:
                return int(item.get("number"))
    except Exception as exc:
        logger.debug("Could not parse gh issue list: %s", exc)
    return None


def _create_issue(title: str, body: str) -> Optional[str]:
    """Create a new issue; return its URL or None."""
    code, out = _run_gh(
        [
            "issue",
            "create",
            "--repo",
            REPO,
            "--title",
            title,
            "--body",
            body,
            "--label",
            "crash,bug",
        ]
    )
    if code == 0 and out:
        return out.strip().splitlines()[-1].strip() if out.strip() else None
    return None


def _comment_issue(number: int, body: str) -> Optional[str]:
    """Add a comment to an existing issue; return the issue URL."""
    code, _out = _run_gh(
        [
            "issue",
            "comment",
            str(number),
            "--repo",
            REPO,
            "--body",
            body,
        ]
    )
    if code == 0:
        return f"https://github.com/{REPO}/issues/{number}"
    return None


def _browser_fallback(title: str, body: str) -> str:
    """Open the browser on the new-issue page with prefilled content."""
    url = (
        f"https://github.com/{REPO}/issues/new?"
        f"title={urllib.parse.quote(title)}&body={urllib.parse.quote(body)}"
    )
    try:
        webbrowser.open(url)
    except Exception as exc:
        logger.debug("webbrowser.open failed: %s", exc)
    return url


def report_crash(
    *, traceback_text: str, signature: str, summary: str
) -> tuple[Optional[str], Optional[str]]:
    """Report a crash. Returns (url, error).

    - url: the issue URL created/commented/opened, or None on failure.
    - error: an error message, or None on success.
    """
    title = f"{summary} [{SIGNATURE_PREFIX}:{signature}]"
    body = traceback_text

    gh = _gh_executable()
    if not gh or not _is_gh_logged_in(gh):
        # Browser fallback — still useful, and never fatal.
        try:
            url = _browser_fallback(title, body)
            return url, None
        except Exception as exc:
            return None, str(exc)

    existing = _find_existing_issue(signature)
    if existing:
        occurrence_body = (
            f"New occurrence of crash `{SIGNATURE_PREFIX}:{signature}`.\n\n"
            f"{body}"
        )
        url = _comment_issue(existing, occurrence_body)
        if url:
            return url, None
        # Comment failed — fall through to create.

    url = _create_issue(title, body)
    if url:
        return url, None

    # gh present + authed but create failed — try browser as last resort.
    try:
        url = _browser_fallback(title, body)
        return url, None
    except Exception as exc:
        return None, str(exc)


class CrashReporterWorker(QObject):
    """Runs ``report_crash`` off the UI thread."""

    finished = pyqtSignal(str, str)  # (url, error)

    def __init__(self, *, traceback_text: str, signature: str, summary: str) -> None:
        super().__init__()
        self._traceback = traceback_text
        self._signature = signature
        self._summary = summary

    def run(self) -> None:  # pragma: no cover - thread body
        try:
            url, error = report_crash(
                traceback_text=self._traceback,
                signature=self._signature,
                summary=self._summary,
            )
            self.finished.emit(url or "", error or "")
        except Exception as exc:
            self.finished.emit("", str(exc))
