"""Thread-affinity tests for session variable restore."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QWidget

from src.ui.components.session_widget import SessionWidget


class _RestoreHost(QWidget):
    """Minimal QWidget stand-in for SessionWidget restore path."""

    _persisted_variables_loaded = pyqtSignal(object)
    _restore_dispatch = pyqtSignal(object)

    def __init__(self, session_id: str = "s1", parent=None):
        super().__init__(parent)
        self.session = MagicMock(session_id=session_id)
        self._restore_dispatch.connect(
            self._emit_persisted_variables_loaded,
            Qt.ConnectionType.QueuedConnection,
        )

    def _emit_persisted_variables_loaded(self, variables: object) -> None:
        self._persisted_variables_loaded.emit(variables)


def test_persisted_variables_loaded_emits_on_main_thread(qtbot):
    host = _RestoreHost()
    qtbot.addWidget(host)

    main_thread = QThread.currentThread()
    emit_threads: list = []
    host._persisted_variables_loaded.connect(
        lambda _v: emit_threads.append(QThread.currentThread())
    )
    spy = QSignalSpy(host._persisted_variables_loaded)

    with (
        patch(
            "src.core.session_result_storage.is_session_result_restore_enabled",
            return_value=True,
        ),
        patch(
            "src.core.session_result_storage.has_persisted_snapshot",
            return_value=True,
        ),
        patch(
            "src.core.session_result_storage.SessionResultStorage.load",
            return_value={"df": 1},
        ),
    ):
        SessionWidget._restore_variables_from_disk(host, require_enabled=True)

    qtbot.waitUntil(lambda: len(spy) >= 1, timeout=3000)

    assert len(spy) >= 1
    assert emit_threads
    assert emit_threads[0] == main_thread
