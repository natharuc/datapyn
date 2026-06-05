"""Safe QThread shutdown — avoid 'Destroyed while thread is still running'."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QThread


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
    if thread is None:
        return True
    try:
        thread.setParent(None)
    except RuntimeError:
        pass
    try:
        if not thread.isRunning():
            return True
        if force_terminate:
            thread.terminate()
            return thread.wait(wait_ms)
        thread.quit()
        if not thread.wait(min(wait_ms, 800)):
            thread.terminate()
        return thread.wait(wait_ms)
    except RuntimeError:
        return True


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
    if thread is None:
        return
    try:
        if not thread.isRunning():
            return
        thread.quit()
        if not thread.wait(0):
            thread.terminate()
    except RuntimeError:
        pass
