"""
User-like integration tests for Pynia token-worker / QThread lifecycle.

Simulates flows such as opening chat, refreshing usage/models, sending messages,
and cancelling — without leaving stale QThread wrappers that crash on isRunning().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.services.pynia.agent_client import PyniaAgentClient
from src.services.pynia.settings import set_provider_secret
from src.utils.qt_threading import qthread_is_alive, qthread_is_running


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump_events(ms: int = 150) -> None:
    app = QApplication.instance()
    if app:
        app.processEvents()
    QTest.qWait(ms)
    if app:
        app.processEvents()


class _StubTokenWorker(QObject):
    """Fast token worker for lifecycle tests (no network)."""

    chunk = pyqtSignal(str)
    complete = pyqtSignal(str)
    error = pyqtSignal(str)
    auth_ok = pyqtSignal()
    models_ready = pyqtSignal(list)
    usage_ready = pyqtSignal(dict)
    tool_call = pyqtSignal(str, dict, str)
    tool_result = pyqtSignal(str, str, str)
    agent_progress = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, provider_id, tool_executor=None, subagent_orchestrator=None, parent=None):
        super().__init__(parent)
        self._provider_id = provider_id
        self._cancelled = False
        self._delay_ms = 0

    def set_model(self, model: str) -> None:
        pass

    def set_messages(self, messages) -> None:
        pass

    def set_attachments(self, attachments) -> None:
        pass

    def set_openai_tools(self, tools) -> None:
        pass

    def cancel(self) -> None:
        self._cancelled = True

    def _emit_verify_success(self) -> None:
        if self._cancelled:
            self.finished.emit()
            return
        self.models_ready.emit(
            [
                {"id": "openai/gpt-4o", "name": "GPT-4o", "multiplier": 1.0},
                {"id": "anthropic/claude-sonnet-4.6", "name": "Claude", "multiplier": 1.0},
            ]
        )
        self.usage_ready.emit({"available": True, "used": 1, "total": 10})
        self.auth_ok.emit()
        self.finished.emit()

    def _emit_chat_success(self) -> None:
        if self._cancelled:
            self.finished.emit()
            return
        self.agent_progress.emit({"phase_key": "activity_connecting", "step_id": "connect"})
        self.chunk.emit("Hello")
        self.complete.emit("Hello")
        self.finished.emit()

    @pyqtSlot()
    def run_verify(self) -> None:
        if self._delay_ms:
            QTimer.singleShot(self._delay_ms, self._emit_verify_success)
        else:
            self._emit_verify_success()

    @pyqtSlot()
    def run_chat(self) -> None:
        if self._delay_ms:
            QTimer.singleShot(self._delay_ms, self._emit_chat_success)
        else:
            self._emit_chat_success()


class _SlowStubTokenWorker(_StubTokenWorker):
    def __init__(self, provider_id, tool_executor=None, subagent_orchestrator=None, parent=None):
        super().__init__(provider_id, tool_executor, subagent_orchestrator, parent)
        self._delay_ms = 200


@pytest.fixture
def openrouter_client(qapp, monkeypatch):
    monkeypatch.setattr("src.services.pynia.agent_client.TokenAgentWorker", _StubTokenWorker)
    set_provider_secret("openrouter", "sk-or-test")
    client = PyniaAgentClient()
    client.set_provider("openrouter")
    yield client
    try:
        client.cancel()
    finally:
        set_provider_secret("openrouter", "")


class TestQtThreadHelpers:
    def test_qthread_is_running_on_deleted_wrapper(self, qapp):
        from PyQt6.QtCore import QThread

        thread = QThread()
        thread.start()
        thread.quit()
        thread.wait(2000)
        thread.deleteLater()
        _pump_events(50)
        assert not qthread_is_alive(thread)
        assert not qthread_is_running(thread)


class TestPyniaAgentClientThreadLifecycle:
    def test_refresh_after_verify_clears_stale_thread_ref(self, openrouter_client):
        client = openrouter_client
        client.refresh_metadata()
        _pump_events(100)
        assert client._token_thread is None
        assert client._token_worker is None

        # User clicked refresh costs/models after prior verify finished (was crashing).
        client.refresh_metadata()
        _pump_events(100)
        assert not qthread_is_running(client._token_thread)

    def test_double_refresh_after_complete(self, openrouter_client):
        client = openrouter_client
        for _ in range(3):
            client.refresh_metadata()
            _pump_events(120)
        assert client._token_thread is None

    def test_refresh_while_running_is_noop(self, qapp, monkeypatch):
        monkeypatch.setattr("src.services.pynia.agent_client.TokenAgentWorker", _SlowStubTokenWorker)
        set_provider_secret("openrouter", "sk-or-slow")
        client = PyniaAgentClient()
        client.set_provider("openrouter")
        try:
            client.refresh_metadata()
            assert qthread_is_running(client._token_thread)
            client.refresh_metadata()
            client.refresh_metadata()
            _pump_events(250)
            assert client._token_thread is None
        finally:
            client.cancel()
            set_provider_secret("openrouter", "")

    def test_send_chat_then_refresh(self, openrouter_client):
        client = openrouter_client
        client.send_chat([{"role": "user", "content": "hi"}])
        _pump_events(150)
        client.refresh_metadata()
        _pump_events(150)
        assert client._token_thread is None

    def test_cancel_then_refresh(self, qapp, monkeypatch):
        monkeypatch.setattr("src.services.pynia.agent_client.TokenAgentWorker", _SlowStubTokenWorker)
        set_provider_secret("openrouter", "sk-or-slow")
        client = PyniaAgentClient()
        client.set_provider("openrouter")
        try:
            client.send_chat([{"role": "user", "content": "slow"}])
            _pump_events(30)
            client.cancel()
            _pump_events(100)
            client.refresh_metadata()
            _pump_events(250)
            assert client._token_thread is None
        finally:
            client.cancel()
            set_provider_secret("openrouter", "")


def _minimal_refresh_panel(agent_client: PyniaAgentClient):
    """Panel stub — exercises refresh handler without WebEngine (headless-safe)."""
    from src.ui.components.copilot_chat_panel import PyniaChatPanel

    panel = PyniaChatPanel.__new__(PyniaChatPanel)
    panel._usage_label = MagicMock()
    panel._sync_usage_to_webview = MagicMock()
    panel._agent_client = agent_client
    return panel


class TestPyniaChatPanelUserFlows:
    def test_panel_refresh_models_after_auto_verify(self, qapp, monkeypatch):
        """Simulate: chat opens → auto verify → user clicks refresh costs."""
        monkeypatch.setattr("src.services.pynia.agent_client.TokenAgentWorker", _StubTokenWorker)
        set_provider_secret("openrouter", "sk-or-test")
        client = PyniaAgentClient()
        client.set_provider("openrouter")
        panel = _minimal_refresh_panel(client)
        try:
            client.refresh_metadata()
            _pump_events(120)
            panel._on_refresh_models_clicked()
            _pump_events(120)
            panel._on_refresh_models_clicked()
            _pump_events(120)
            assert client._token_thread is None
        finally:
            client.cancel()
            set_provider_secret("openrouter", "")

    def test_panel_stop_during_chat_then_refresh(self, qapp, monkeypatch):
        monkeypatch.setattr("src.services.pynia.agent_client.TokenAgentWorker", _SlowStubTokenWorker)
        set_provider_secret("openrouter", "sk-or-slow")
        client = PyniaAgentClient()
        client.set_provider("openrouter")
        from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime
        from src.ui.components.copilot_chat_panel import PyniaChatPanel

        panel = PyniaChatPanel.__new__(PyniaChatPanel)
        panel._usage_label = MagicMock()
        panel._sync_usage_to_webview = MagicMock()
        panel._agent_client = client
        panel._chat_runtime = CopilotChatRuntime(parent=None)
        panel._recover_stuck_turn = MagicMock()
        try:
            client.send_chat([{"role": "user", "content": "cancel me"}])
            _pump_events(40)
            client.cancel()
            _pump_events(150)
            panel._on_refresh_models_clicked()
            _pump_events(250)
            assert client._token_thread is None
        finally:
            client.cancel()
            set_provider_secret("openrouter", "")
