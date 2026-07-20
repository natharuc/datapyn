"""
PyniaAgentClient — multi-provider agent for DataPyn chat.

Exposes the same Qt signals and methods as CopilotClient so existing UI and
tool wiring continue to work while routing to OpenAI, OpenRouter, Claude, or
GitHub Copilot connectors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QMetaObject, Qt

from src.services.copilot.copilot_models import (
    fallback_models,
    model_supports_reasoning_effort,
    normalize_reasoning_effort,
    usage_snapshot_for_model,
)
from src.services.pynia.completion import clean_completion_text
from src.services.pynia.providers.copilot_adapter import CopilotProviderAdapter
from src.services.pynia.providers.token_worker import FALLBACK_MODELS, TokenAgentWorker
from src.services.pynia.settings import get_pynia_settings, get_provider_secret, set_provider_secret
from src.services.pynia.types import DEFAULT_PROVIDER, PROVIDERS, ProviderId

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import CopilotClient, ThreadSafeToolExecutor
    from src.services.pynia.tools import PyniaToolRegistry

logger = logging.getLogger(__name__)


class PyniaAgentClient(QObject):
    """
    Unified agent client for Pynia connectors.

    Compatible with CopilotClient's public surface used by PyniaChatPanel.
    """

    auth_required = pyqtSignal(str, str)
    authenticated = pyqtSignal(str)
    auth_failed = pyqtSignal(str)
    auth_started = pyqtSignal(str)
    chat_response_chunk = pyqtSignal(str)
    chat_response_complete = pyqtSignal(str)
    chat_error = pyqtSignal(str)
    tool_called = pyqtSignal(str, dict, str)
    tool_result = pyqtSignal(str, str, str)
    agent_progress = pyqtSignal(dict)
    thinking = pyqtSignal(str)
    models_changed = pyqtSignal(list)
    usage_changed = pyqtSignal(dict)
    inline_completion_ready = pyqtSignal(str)
    gh_not_found = pyqtSignal()
    license_warning = pyqtSignal(str)
    provider_changed = pyqtSignal(str)

    def __init__(
        self,
        copilot_client: Optional["CopilotClient"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._settings = get_pynia_settings()
        self._provider_id: ProviderId = self._settings.active_provider
        self._copilot_backend = copilot_client
        self._copilot_adapter: Optional[CopilotProviderAdapter] = None
        self._tool_executor: Optional["ThreadSafeToolExecutor"] = None
        self._tool_registry: Optional["PyniaToolRegistry"] = None
        self._subagent_orchestrator: Optional[Any] = None
        self._is_authenticated = False
        self._username = ""
        self._system_message = ""
        self._available_models = self._initial_models_for_provider(self._provider_id)
        self._model = self._settings.selected_model(self._provider_id)
        self._reasoning_effort = self._settings.reasoning_effort
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)

        self._token_thread: Optional[QThread] = None
        self._token_worker: Optional[TokenAgentWorker] = None
        self._token_worker_mode = ""

        self._completion_thread: Optional[QThread] = None
        self._completion_worker: Optional[QObject] = None

        self._connect_active_provider()

    @property
    def provider_id(self) -> ProviderId:
        return self._provider_id

    @property
    def provider_label_key(self) -> str:
        return PROVIDERS[self._provider_id].label_key

    def apply_connector_from_settings(self, provider_id: ProviderId) -> None:
        """Reload credentials/models after Settings saved without switching connector."""
        if provider_id not in PROVIDERS:
            return
        if provider_id != self._provider_id:
            self.set_provider(provider_id)
            return

        if provider_id == "copilot":
            if self._copilot_backend:
                self._is_authenticated = self._copilot_backend.is_authenticated
                self._username = getattr(self._copilot_backend, "_username", "") or ""
                if self._copilot_backend.is_authenticated:
                    self._available_models = self._copilot_backend.available_models()
                    self._model = self._copilot_backend.model
        else:
            had_token = self._is_authenticated
            self._is_authenticated = bool(get_provider_secret(provider_id))
            self._username = self._settings.username(provider_id) or provider_id
            if self._is_authenticated and not had_token:
                self.authenticated.emit(self._username)
            if self._is_authenticated:
                self._available_models = self._initial_models_for_provider(provider_id)

        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
        self.models_changed.emit(self.available_models())
        self.usage_changed.emit(self._usage_snapshot)
        self.provider_changed.emit(provider_id)

    def set_provider(self, provider_id: ProviderId) -> None:
        if provider_id not in PROVIDERS:
            return
        if provider_id == self._provider_id:
            return
        self.cancel()
        if self._subagent_orchestrator:
            self._subagent_orchestrator.set_provider(provider_id)
        self._disconnect_active_provider()
        self._provider_id = provider_id
        self._settings.set_active_provider(provider_id)
        self._is_authenticated = self._settings.is_authenticated(provider_id)
        self._username = self._settings.username(provider_id)
        self._model = self._settings.selected_model(provider_id)
        self._available_models = self._initial_models_for_provider(provider_id)
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
        self._connect_active_provider()
        self.provider_changed.emit(provider_id)
        self.models_changed.emit(self._available_models)
        self.usage_changed.emit(self._usage_snapshot)

    def _initial_models_for_provider(self, provider_id: ProviderId) -> List[Dict[str, Any]]:
        cached = self._settings.cached_models(provider_id)
        if cached:
            return cached
        return [dict(m) for m in FALLBACK_MODELS.get(provider_id, fallback_models())]

    def _should_persist_models(self, provider_id: ProviderId, models: list) -> bool:
        fallback = FALLBACK_MODELS.get(provider_id, fallback_models())
        return len(models) > len(fallback)

    def _connect_active_provider(self) -> None:
        if self._provider_id == "copilot" and self._copilot_backend:
            self._copilot_adapter = CopilotProviderAdapter(self._copilot_backend, self)
            self._copilot_adapter.connect_signals(self)
            self._is_authenticated = self._copilot_backend.is_authenticated
            self._username = getattr(self._copilot_backend, "_username", "") or ""
            saved_model = self._settings.selected_model("copilot")
            if saved_model:
                self._copilot_backend.model = saved_model
                self._model = saved_model
            elif self._copilot_backend.is_authenticated:
                self._available_models = self._copilot_backend.available_models()
                self._model = self._copilot_backend.model
        else:
            self._copilot_adapter = None
            self._is_authenticated = bool(get_provider_secret(self._provider_id))

    def _disconnect_active_provider(self) -> None:
        if self._copilot_adapter:
            self._copilot_adapter.disconnect_signals(self)
            self._copilot_adapter = None
        self._cleanup_token_worker()

    @property
    def is_authenticated(self) -> bool:
        if self._provider_id == "copilot" and self._copilot_backend:
            return self._copilot_backend.is_authenticated
        return bool(get_provider_secret(self._provider_id))

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value or PROVIDERS[self._provider_id].default_model
        self._settings.set_selected_model(self._model, self._provider_id)
        if self._subagent_orchestrator:
            self._subagent_orchestrator.set_model(self._model)
        if self._provider_id == "copilot" and self._copilot_backend:
            self._copilot_backend.model = self._model
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
        self.usage_changed.emit(self._usage_snapshot)

    @property
    def reasoning_effort(self) -> str:
        return self._reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, value: str) -> None:
        self._reasoning_effort = normalize_reasoning_effort(value)
        self._settings.set_reasoning_effort(self._reasoning_effort)
        if self._provider_id == "copilot" and self._copilot_backend:
            self._copilot_backend.reasoning_effort = self._reasoning_effort

    @property
    def system_message(self) -> str:
        if self._provider_id == "copilot" and self._copilot_backend:
            return self._copilot_backend.system_message
        return self._system_message

    @system_message.setter
    def system_message(self, value: str) -> None:
        self._system_message = value
        if self._provider_id == "copilot" and self._copilot_backend:
            self._copilot_backend.system_message = value

    def model_supports_reasoning_effort(self, model_id: str = "") -> bool:
        return model_supports_reasoning_effort(self._available_models, model_id or self._model)

    def available_models(self) -> List[Dict[str, Any]]:
        if self._provider_id == "copilot" and self._copilot_backend and self._copilot_backend.is_authenticated:
            return self._copilot_backend.available_models()
        return self._available_models

    def usage_snapshot(self) -> Dict[str, Any]:
        if self._provider_id == "copilot" and self._copilot_backend:
            return self._copilot_backend.usage_snapshot()
        return dict(self._usage_snapshot)

    def set_tool_registry(self, registry: "PyniaToolRegistry", parent: QObject = None) -> None:
        from PyQt6.QtWidgets import QApplication
        from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor

        if parent is None:
            parent = QApplication.instance()
        from src.services.pynia.subagents.orchestrator import SubagentOrchestrator

        self._tool_registry = registry
        self._tool_executor = ThreadSafeToolExecutor(registry, parent=parent)
        self._subagent_orchestrator = SubagentOrchestrator(
            provider_id=self._provider_id,
            model=self._model,
            openai_tools=registry.list_tools_openai(),
            tool_executor=self._tool_executor,
            parent=parent,
        )
        registry.set_subagent_orchestrator(self._subagent_orchestrator)
        if self._provider_id == "copilot" and self._copilot_backend:
            self._copilot_backend.set_tool_registry(registry, parent=parent)

    def set_api_token(self, token: str, label: str = "") -> bool:
        if self._provider_id == "copilot":
            return False
        token = token.strip()
        label = (label or self._provider_id).strip()
        if token != get_provider_secret(self._provider_id):
            set_provider_secret(self._provider_id, token)
        if not token:
            return False
        already_authenticated = (
            self._is_authenticated
            and self._username == label
            and token == get_provider_secret(self._provider_id)
        )
        if not already_authenticated:
            self._settings.on_token_authenticated(self._provider_id, label)
        self._is_authenticated = True
        self._username = label
        if not already_authenticated:
            self.authenticated.emit(self._username)
            return True
        return False

    def start_auth(self) -> None:
        if self._provider_id == "copilot":
            if self._copilot_adapter:
                self._copilot_adapter.start_auth()
            elif self._copilot_backend:
                self._copilot_backend.start_auth()
            return

        self.auth_started.emit("Verifying API token…")
        self._start_token_worker("verify")

    def refresh_metadata(self) -> None:
        if self._provider_id == "copilot" and self._copilot_adapter:
            self._copilot_adapter.refresh_metadata()
            return
        if not get_provider_secret(self._provider_id):
            return
        from src.utils.qt_threading import qthread_is_running

        if qthread_is_running(self._token_thread):
            return
        self._start_token_worker("verify")

    def send_chat(
        self,
        messages: List[Dict[str, str]],
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if self._provider_id == "copilot":
            if self._copilot_adapter:
                self._copilot_adapter.send_chat(messages, attachments=attachments)
            elif self._copilot_backend:
                self._copilot_backend.send_chat(messages, attachments=attachments)
            return

        if not get_provider_secret(self._provider_id):
            self.chat_error.emit("Configure your API token in Settings → Pynia.")
            return

        tools = []
        if self._tool_registry:
            tools = self._tool_registry.list_tools_openai()

        self._start_token_worker(
            "chat",
            messages=messages,
            attachments=attachments,
            tools=tools,
        )

    def cancel(self) -> None:
        if self._provider_id == "copilot":
            if self._copilot_adapter:
                self._copilot_adapter.cancel()
            elif self._copilot_backend:
                self._copilot_backend.cancel()
        if self._subagent_orchestrator and hasattr(
            self._subagent_orchestrator, "cancel_active_explore"
        ):
            self._subagent_orchestrator.cancel_active_explore()
        self._cleanup_token_worker(blocking=True)

    def cancel_pending_auth(self) -> None:
        if self._provider_id == "copilot" and self._copilot_adapter:
            self._copilot_adapter.cancel_pending_auth()
        else:
            self.cancel()
            self.auth_failed.emit("Authentication cancelled")

    def reset_chat_session(self) -> None:
        if self._provider_id == "copilot" and self._copilot_adapter:
            self._copilot_adapter.reset_chat_session()

    def request_inline_completion(
        self,
        prefix: str,
        suffix: str,
        language: str,
        request_id: int = 0,
        context: str = "",
    ) -> None:
        """Pynia inline autocomplete (API connectors or Copilot connector)."""
        settings = get_pynia_settings()
        if not settings.autocomplete_enabled:
            self.inline_completion_ready.emit("")
            return

        if self._provider_id == "copilot":
            if self._copilot_backend:
                self._copilot_backend.request_inline_completion(
                    prefix, suffix, language, request_id=request_id, context=context
                )
            else:
                self.inline_completion_ready.emit("")
            return

        if not get_provider_secret(self._provider_id):
            logger.debug("[Pynia] Autocomplete skipped: no token for %s", self._provider_id)
            self.inline_completion_ready.emit("")
            return

        self._start_inline_completion_worker(
            language=language,
            prefix=prefix,
            suffix=suffix,
            context=context,
        )

    def setup_lsp_client(self, server_path: str) -> bool:
        """Deprecated: autocomplete uses Pynia API, not Copilot LSP."""
        return False

    @property
    def lsp_client(self):
        return None

    def cleanup(self) -> None:
        self.cancel()
        self._cleanup_token_worker(blocking=True)
        self._cleanup_inline_completion_worker()
        self._disconnect_active_provider()
        if self._copilot_backend and hasattr(self._copilot_backend, "cleanup"):
            self._copilot_backend.cleanup()

    def _start_inline_completion_worker(
        self,
        *,
        language: str,
        prefix: str,
        suffix: str,
        context: str = "",
    ) -> None:
        from src.services.pynia.completion import PyniaInlineCompletionWorker

        self._cleanup_inline_completion_worker()

        worker = PyniaInlineCompletionWorker()
        worker.set_request(
            self._provider_id,
            language,
            prefix,
            suffix,
            context=context,
            model=get_pynia_settings().completion_model(self._provider_id),
        )

        thread = QThread(self)
        worker.moveToThread(thread)

        def _deliver(text: str) -> None:
            cleaned = clean_completion_text(text, prefix, suffix)
            self.inline_completion_ready.emit(cleaned)

        worker.inline_complete.connect(_deliver)
        worker.error.connect(lambda _msg: self.inline_completion_ready.emit(""))
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._completion_worker = worker
        self._completion_thread = thread
        thread.start()

    def _cleanup_inline_completion_worker(self, *, blocking: bool = False) -> None:
        from src.utils.qt_threading import kick_qthread_stop, stop_qthread

        worker = self._completion_worker
        thread = self._completion_thread
        self._completion_worker = None
        self._completion_thread = None
        if blocking:
            stop_qthread(thread, worker, wait_ms=2000)
        else:
            kick_qthread_stop(thread, worker)

    def _disconnect_token_worker_signals(self, worker: TokenAgentWorker) -> None:
        for name in (
            "chunk",
            "complete",
            "error",
            "auth_ok",
            "models_ready",
            "usage_ready",
            "tool_call",
            "tool_result",
            "agent_progress",
            "finished",
        ):
            try:
                getattr(worker, name).disconnect()
            except (TypeError, RuntimeError):
                pass

    def _start_token_worker(
        self,
        mode: str,
        *,
        messages: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        # Never block the UI thread while starting chat (context build already ran).
        self._cleanup_token_worker(blocking=mode != "chat")
        self._token_worker_mode = mode
        # Worker must have no QObject parent so moveToThread succeeds (parented
        # objects cannot be moved and would run network I/O on the UI thread).
        self._token_worker = TokenAgentWorker(
            self._provider_id,
            self._tool_executor,
            self._subagent_orchestrator,
        )
        self._token_worker.set_model(self._model)
        if messages is not None:
            self._token_worker.set_messages(messages)
        if attachments is not None:
            self._token_worker.set_attachments(attachments)
        if tools is not None:
            self._token_worker.set_openai_tools(tools)

        self._token_worker.chunk.connect(self.chat_response_chunk.emit)
        self._token_worker.complete.connect(self.chat_response_complete.emit)
        self._token_worker.error.connect(self._on_token_error)
        self._token_worker.auth_ok.connect(self._on_token_auth_ok)
        self._token_worker.models_ready.connect(self._on_models_loaded)
        self._token_worker.usage_ready.connect(self._on_usage_loaded)
        self._token_worker.tool_call.connect(self.tool_called.emit)
        self._token_worker.tool_result.connect(self.tool_result.emit)
        self._token_worker.agent_progress.connect(self.agent_progress.emit)

        self._token_thread = QThread(self)
        self._token_thread.setObjectName(
            "PyniaTokenVerify" if mode == "verify" else "PyniaTokenChat"
        )
        self._token_worker.moveToThread(self._token_thread)
        if mode == "verify":
            self._token_thread.started.connect(self._token_worker.run_verify)
        else:
            self._token_thread.started.connect(self._token_worker.run_chat)
        self._token_worker.finished.connect(self._token_thread.quit)
        self._token_thread.finished.connect(self._on_token_thread_finished)
        self._token_thread.finished.connect(self._token_worker.deleteLater)
        self._token_thread.start()

    def _on_token_thread_finished(self) -> None:
        """Drop refs when a token worker thread ends (avoid deleted QThread wrappers)."""
        finished_thread = self.sender()
        if finished_thread is not self._token_thread:
            return
        self._token_worker = None
        self._token_thread = None
        self._token_worker_mode = ""

    def _cleanup_token_worker(self, *, blocking: bool = False) -> None:
        from src.utils.qt_threading import kick_qthread_stop, stop_qthread

        worker, thread = self._token_worker, self._token_thread
        self._token_worker = None
        self._token_thread = None
        self._token_worker_mode = ""
        if worker is not None:
            self._disconnect_token_worker_signals(worker)
            worker.cancel()
        if blocking:
            stop_qthread(thread, worker, wait_ms=3000)
        else:
            kick_qthread_stop(thread, worker)

    def _on_token_auth_ok(self) -> None:
        self._is_authenticated = True
        self._username = self._settings.username(self._provider_id) or self._provider_id
        self.authenticated.emit(self._username)

    def _on_token_error(self, message: str) -> None:
        if self.sender() is not self._token_worker:
            return
        if self._token_worker_mode == "chat":
            self.chat_error.emit(message)
            if "token" in message.lower() or "401" in message:
                self.auth_failed.emit(message)
            return
        if "token" in message.lower() or "401" in message:
            self.auth_failed.emit(message)
        else:
            self.chat_error.emit(message)

    def _on_models_loaded(self, models: list) -> None:
        self._available_models = models
        if self._should_persist_models(self._provider_id, models):
            self._settings.set_cached_models(self._provider_id, models)
        self.models_changed.emit(models)

    def _on_usage_loaded(self, usage: dict) -> None:
        self._usage_snapshot = usage
        self.usage_changed.emit(usage)
