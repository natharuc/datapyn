"""Global exception interceptor — the app never closes on an unhandled error.

Installs three safety nets so a Python/Qt exception surfaces a formatted
crash dialog (with an optional "report to GitHub" action) instead of
terminating the process:

1. ``sys.excepthook`` — unhandled exceptions on the main (UI) thread that
   escape the Qt event loop (e.g. raised at module top-level or after
   ``app.exec()`` returns).
2. ``threading.excepthook`` — unhandled exceptions on worker threads
   (``QThread.run`` bodies, ``concurrent.futures``, etc.).
3. ``QApplication.notify`` override — exceptions raised inside Qt event
   dispatch (slots, timers, signal emissions). These are the most common
   PyQt crash source and are NOT caught by ``sys.excepthook``.

Every handler logs the full traceback (to ``datapyn.log`` and a rotating
``crashes.log``), computes a stable signature, and schedules the crash
dialog on the UI thread. Nothing here ever calls ``sys.exit``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import threading
import traceback
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal

logger = logging.getLogger(__name__)

_CRASH_LOG_NAME = "crashes.log"
_CRASH_LOG_MAX_BYTES = 512 * 1024  # 512 KB
_CRASH_LOG_BACKUP = 3

_installed = False
_reentry_guard = threading.Lock()
_pending_dialog_scheduled = False
_app_ref: Optional[object] = None
_dispatcher: Optional["_CrashDispatcher"] = None


class _CrashDispatcher(QObject):
    """Lives on the UI thread (parented to the QApplication) so a cross-thread
    ``emit()`` is marshalled to the UI thread by Qt via QueuedConnection.

    This mirrors the ``_signal_dispatch`` pattern used in
    ``copilot_lsp_client.py`` / ``session_widget.py``: never call into Qt
    widgets directly from a worker thread — always hop through a signal.
    """

    dispatch = pyqtSignal(str, str)  # traceback_text, signature

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.dispatch.connect(self._on_dispatch, Qt.ConnectionType.QueuedConnection)

    def _on_dispatch(self, traceback_text: str, signature: str) -> None:
        global _pending_dialog_scheduled
        try:
            from PyQt6.QtWidgets import QApplication

            app_obj = QApplication.instance()
            if app_obj is None:
                return
            from src.ui.dialogs.crash_report_dialog import CrashReportDialog

            parent = app_obj.activeWindow()
            dialog = CrashReportDialog(
                traceback_text=traceback_text,
                signature=signature,
                version=_app_version(),
                parent=parent,
            )
            dialog.exec()
        except Exception as exc:
            logger.debug("Crash dialog itself failed: %s", exc)
        finally:
            with _reentry_guard:
                _pending_dialog_scheduled = False


def _crash_log_path() -> str:
    """Return the path to the rotating crash log (next to datapyn.log)."""
    try:
        from src.core.workspace_service import get_workspace_service

        ws = get_workspace_service()
        base = ws.get_workspace_path()
    except Exception:
        base = os.getcwd()
    return os.path.join(str(base or os.getcwd()), _CRASH_LOG_NAME)


def _rotating_crash_logger() -> logging.Logger:
    """Return a dedicated rotating logger for crashes (created once)."""
    crash_logger = logging.getLogger("datapyn.crash")
    if crash_logger.handlers:
        return crash_logger
    try:
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            _crash_log_path(),
            maxBytes=_CRASH_LOG_MAX_BYTES,
            backupCount=_CRASH_LOG_BACKUP,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        crash_logger.addHandler(handler)
        crash_logger.setLevel(logging.ERROR)
        crash_logger.propagate = False
    except Exception as exc:
        logger.debug("Could not attach crash log handler: %s", exc)
    return crash_logger


def _normalize_traceback(text: str) -> str:
    """Strip memory addresses and line numbers for a stable signature.

    File paths are kept (so we know which module), but volatile line numbers
    and hex addresses are removed so the same bug maps to the same signature
    across runs/edits.
    """
    if not text:
        return ""
    cleaned = re.sub(r", line \d+, in ", ", in ", text)
    cleaned = re.sub(r"0x[0-9A-Fa-f]+", "0xADDR", cleaned)
    cleaned = re.sub(r"<[^>]*object at 0xADDR>", "<OBJ>", cleaned)
    return cleaned


def _signature(traceback_text: str) -> str:
    """Return a short stable signature for the given traceback."""
    normalized = _normalize_traceback(traceback_text)
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()[:12]


def _app_version() -> str:
    try:
        from src.ui.splash_screen import _get_version

        return _get_version() or "unknown"
    except Exception:
        return "unknown"


def _format_report(exc_type, exc_value, exc_tb) -> str:
    """Return the full traceback string for an exception triple."""
    try:
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:
        return f"{exc_type.__name__ if exc_type else 'Exception'}: {exc_value}"


def _format_thread_report(args) -> str:
    """Return a traceback string from a threading.ExceptHookArgs-like object."""
    try:
        return "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    except Exception:
        return f"{getattr(args.exc_type, '__name__', 'Exception')}: {args.exc_value}"


def _is_benign_databricks_telemetry_shutdown(
    args,
    traceback_text: str,
) -> bool:
    """Identify only the connector's known telemetry shutdown race."""
    exc_type = getattr(args, "exc_type", None)
    if (
        getattr(exc_type, "__module__", "") != "databricks.sql.exc"
        or getattr(exc_type, "__name__", "") != "RequestError"
    ):
        return False
    if "HTTP client is closing or has been closed" not in str(
        getattr(args, "exc_value", "")
    ):
        return False
    return "_flush_worker" in traceback_text and "telemetry_client" in traceback_text


def _record_crash(traceback_text: str, signature: str, *, source: str) -> None:
    """Persist the crash to the rotating crash log and the main log."""
    header = (
        f"\n{'=' * 60}\n"
        f"CRASH [{source}] signature={signature} "
        f"version={_app_version()} pid={os.getpid()} "
        f"thread={threading.current_thread().name} "
        f"ts={datetime.now().isoformat()}\n"
        f"{'-' * 60}\n"
    )
    try:
        _rotating_crash_logger().error(header + traceback_text)
    except Exception:
        pass
    logger.error("Unhandled exception (%s, sig=%s):\n%s", source, signature, traceback_text)


def _show_crash_dialog_on_ui(traceback_text: str, signature: str) -> None:
    """Schedule the crash dialog on the UI thread (safe from any thread).

    Emits through ``_CrashDispatcher.dispatch`` (a signal connected with
    QueuedConnection and parented to the QApplication, so it has UI-thread
    affinity). Qt marshals the emission to the UI thread — no direct widget
    call from a worker thread, which is the Qt6Core crash pattern we avoid.
    """
    global _pending_dialog_scheduled
    with _reentry_guard:
        if _pending_dialog_scheduled:
            return
        _pending_dialog_scheduled = True

    dispatcher = _dispatcher
    if dispatcher is None:
        # No dispatcher yet (e.g. install never ran) — fall back to a timer
        # so we still surface something instead of silently dropping it.
        try:
            from PyQt6.QtCore import QTimer

            def _show() -> None:
                global _pending_dialog_scheduled
                try:
                    from PyQt6.QtWidgets import QApplication

                    app_obj = QApplication.instance()
                    if app_obj is None:
                        return
                    from src.ui.dialogs.crash_report_dialog import CrashReportDialog

                    parent = app_obj.activeWindow()
                    dialog = CrashReportDialog(
                        traceback_text=traceback_text,
                        signature=signature,
                        version=_app_version(),
                        parent=parent,
                    )
                    dialog.exec()
                except Exception as exc:
                    logger.debug("Crash dialog itself failed: %s", exc)
                finally:
                    with _reentry_guard:
                        _pending_dialog_scheduled = False

            QTimer.singleShot(0, _show)
        except Exception as exc:
            logger.debug("Could not schedule crash dialog: %s", exc)
        return

    try:
        dispatcher.dispatch.emit(traceback_text, signature)
    except RuntimeError as exc:
        # Dispatcher QObject destroyed (app tearing down) — drop quietly.
        logger.debug("Crash dispatcher destroyed, could not emit: %s", exc)
        with _reentry_guard:
            _pending_dialog_scheduled = False


def _handle_exception(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook replacement — never re-raises, never exits."""
    if issubclass(exc_type, KeyboardInterrupt) if exc_type else False:
        # Respect Ctrl+C as a normal exit signal.
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    traceback_text = _format_report(exc_type, exc_value, exc_tb)
    signature = _signature(traceback_text)
    _record_crash(traceback_text, signature, source="sys.excepthook")
    _show_crash_dialog_on_ui(traceback_text, signature)


def _thread_excepthook(args) -> None:
    """threading.excepthook replacement for worker threads."""
    traceback_text = _format_thread_report(args)
    if _is_benign_databricks_telemetry_shutdown(args, traceback_text):
        logger.warning(
            "Ignoring Databricks telemetry shutdown race: %s",
            args.exc_value,
        )
        return
    signature = _signature(traceback_text)
    _record_crash(traceback_text, signature, source=f"thread:{args.thread.name}")
    _show_crash_dialog_on_ui(traceback_text, signature)


def _make_notify_wrapper(original_notify):
    """Wrap QApplication.notify so Qt event-dispatch exceptions are caught."""

    def _notify(self, receiver, event):
        try:
            return original_notify(self, receiver, event)
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback_text = _format_report(exc_type, exc_value, exc_tb)
            signature = _signature(traceback_text)
            _record_crash(traceback_text, signature, source="QApplication.notify")
            _show_crash_dialog_on_ui(traceback_text, signature)
            return False

    return _notify


def install_crash_guard(app) -> None:
    """Install all global exception interceptors for the given QApplication.

    Idempotent. Must be called after ``QApplication`` is created and before
    ``app.exec()`` so import/construction errors are also caught.
    """
    global _installed, _app_ref, _dispatcher
    if _installed:
        return
    _app_ref = app

    # UI-thread dispatcher: parented to the app so it has main-thread affinity.
    # Emitting ``dispatch`` from any worker thread is marshalled to the UI thread
    # by Qt (QueuedConnection) — the crash-safe way to show the dialog.
    try:
        _dispatcher = _CrashDispatcher(app)
    except Exception as exc:
        logger.debug("Could not create crash dispatcher: %s", exc)

    sys.excepthook = _handle_exception
    try:
        threading.excepthook = _thread_excepthook
    except Exception as exc:
        logger.debug("Could not install threading.excepthook: %s", exc)

    # QApplication.notify is the chokepoint for all Qt event dispatch
    # (slots, timers, signals). Wrap it so exceptions there surface the
    # crash dialog instead of crashing the event loop.
    try:
        original_notify = type(app).notify
        type(app).notify = _make_notify_wrapper(original_notify)
    except Exception as exc:
        logger.debug("Could not wrap QApplication.notify: %s", exc)

    _installed = True
    logger.info("Crash guard installed — unhandled exceptions will surface a dialog instead of exiting.")
