"""Debounced, background persistence for SQL/Python session tabs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QThread, QTimer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionAutosavePayload:
    """Snapshot collected on the UI thread, written on a worker thread."""

    sessions_path: Path
    sessions_data: dict
    workspace_path: Optional[Path] = None
    workspace_data: Optional[dict] = None


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


class _SessionAutosaveWorker(QThread):
    def __init__(self, payload: SessionAutosavePayload):
        super().__init__()
        self._payload = payload

    def run(self) -> None:
        try:
            _write_json_atomic(self._payload.sessions_path, self._payload.sessions_data)
            if self._payload.workspace_path and self._payload.workspace_data is not None:
                _write_json_atomic(self._payload.workspace_path, self._payload.workspace_data)
        except Exception:
            pass


class SessionAutosaveService(QObject):
    """Save sessions.json 500ms after the user stops editing."""

    DEBOUNCE_MS = 500

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._collect_payload: Optional[Callable[[], Optional[SessionAutosavePayload]]] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DEBOUNCE_MS)
        self._timer.timeout.connect(self._on_debounced)
        self._worker: Optional[_SessionAutosaveWorker] = None
        self._queued = False

    def configure(
        self,
        collect_payload: Callable[[], Optional[SessionAutosavePayload]],
    ) -> None:
        self._collect_payload = collect_payload

    def schedule(self) -> None:
        if not self._collect_payload:
            return
        self._timer.start(self.DEBOUNCE_MS)

    def cancel_pending(self) -> None:
        """Stop debounce timer (app shutdown)."""
        self._timer.stop()
        self._queued = False

    def flush_now(self, wait_ms: int = 5000) -> None:
        """Immediate save (tab close, workspace switch). Waits for in-flight writes."""
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(wait_ms)
        self._start_write()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(wait_ms)

    def _on_debounced(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._queued = True
            return
        self._start_write()

    def _start_write(self) -> None:
        if not self._collect_payload:
            return
        try:
            payload = self._collect_payload()
        except Exception:
            return
        if payload is None:
            return

        self._queued = False
        self._worker = _SessionAutosaveWorker(payload)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if self._queued:
            self._queued = False
            self._start_write()
