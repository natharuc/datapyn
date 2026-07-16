"""Safe QThread shutdown — avoid 'Destroyed while thread is still running'."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QThread

logger = logging.getLogger(__name__)


def qthread_is_alive(thread: Optional[QThread]) -> bool:
    """Return True if the QThread C++ object still exists."""
    if thread is None:
        return False
    try:
        thread.objectName()
        return True
    except RuntimeError:
        return False


def qthread_is_running(thread: Optional[QThread]) -> bool:
    """Return True if the thread exists and is running; never raises on deleted wrappers."""
    if not qthread_is_alive(thread):
        return False
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


def stop_qthread(
    thread: Optional[QThread],
    worker=None,
    *,
    wait_ms: int = 5000,
    force_terminate: bool = False,
) -> bool:
    """Stop a QThread. Returns True if the thread is no longer running."""
    if worker is not None and hasattr(worker, "cancel"):
        try:
            worker.cancel()
        except RuntimeError:
            pass
    if not qthread_is_alive(thread):
        return True
    try:
        thread.setParent(None)
    except RuntimeError:
        pass
    try:
        if not qthread_is_running(thread):
            return True
        if force_terminate:
            logger.warning("Forcing QThread terminate (force_terminate=True)")
            thread.terminate()
            return thread.wait(wait_ms)
        thread.quit()
        if not thread.wait(min(wait_ms, 800)):
            logger.warning("QThread did not stop after quit(); terminating as last resort")
            thread.terminate()
        return thread.wait(wait_ms)
    except RuntimeError:
        return True


def detach_qthread(
    thread: Optional[QThread],
    worker=None,
) -> None:
    """Cooperatively stop a QThread without blocking the caller (UI-safe)."""
    if worker is not None and hasattr(worker, "cancel"):
        try:
            worker.cancel()
        except RuntimeError:
            pass
    if not qthread_is_alive(thread):
        return
    try:
        if qthread_is_running(thread):
            thread.quit()
    except RuntimeError:
        pass


def kick_qthread_stop(
    thread: Optional[QThread],
    worker=None,
) -> None:
    """Request stop without blocking the UI thread (thread object must stay alive)."""
    if worker is not None and hasattr(worker, "cancel"):
        try:
            worker.cancel()
        except RuntimeError:
            pass
    if not qthread_is_alive(thread):
        return
    try:
        if not qthread_is_running(thread):
            return
        thread.quit()
        if thread.wait(300):
            return
        logger.warning("QThread did not stop after quit(); terminating as last resort")
        thread.terminate()
        thread.wait(500)
    except RuntimeError:
        pass
