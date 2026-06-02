"""Background worker for API-token providers (OpenAI, OpenRouter, Claude)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.services.copilot.copilot_models import fallback_models, normalize_models, usage_snapshot_for_model
from src.services.pynia.anthropic_agent_loop import run_anthropic_agent_turn
from src.services.pynia.agent_loop_policy import truncate_tool_result
from src.services.pynia.openai_agent_loop import fetch_openai_models, run_openai_agent_turn
from src.services.pynia.settings import get_pynia_settings, get_provider_secret
from src.services.pynia.types import PROVIDERS, ProviderId

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor
    from src.services.pynia.subagents.orchestrator import SubagentOrchestrator

logger = logging.getLogger(__name__)

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://datapyn.app",
    "X-Title": "DataPyn Pynia",
}

FALLBACK_MODELS: dict[ProviderId, list] = {
    "openai": fallback_models(),
    "openrouter": [
        {"id": "openai/gpt-4o", "name": "GPT-4o (OpenRouter)", "multiplier": 1.0},
        {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "multiplier": 1.0},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "multiplier": 1.0},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "multiplier": 1.0},
    ],
}


class TokenAgentWorker(QObject):
    """Runs token-based agent turns off the UI thread."""

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

    def __init__(
        self,
        provider_id: ProviderId,
        tool_executor: Optional["ThreadSafeToolExecutor"] = None,
        subagent_orchestrator: Optional["SubagentOrchestrator"] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._provider_id = provider_id
        self._tool_executor = tool_executor
        self._subagent_orchestrator = subagent_orchestrator
        self._cancelled = False
        self._messages: List[Dict[str, Any]] = []
        self._attachments: Optional[List[Dict[str, Any]]] = None
        self._model = PROVIDERS[provider_id].default_model
        self._openai_tools: List[Dict[str, Any]] = []

    def set_openai_tools(self, tools: List[Dict[str, Any]]) -> None:
        self._openai_tools = tools
        if self._subagent_orchestrator:
            self._subagent_orchestrator.set_openai_tools(tools)

    def set_subagent_orchestrator(self, orchestrator: "SubagentOrchestrator") -> None:
        self._subagent_orchestrator = orchestrator
        if orchestrator and self._openai_tools:
            orchestrator.set_openai_tools(self._openai_tools)

    def set_model(self, model: str) -> None:
        self._model = model or PROVIDERS[self._provider_id].default_model

    def set_messages(self, messages: List[Dict[str, Any]]) -> None:
        self._messages = messages

    def set_attachments(self, attachments: Optional[List[Dict[str, Any]]]) -> None:
        self._attachments = attachments

    def cancel(self) -> None:
        self._cancelled = True

    def _emit_progress(self, payload: dict) -> None:
        self.agent_progress.emit(payload)

    def _execute_tool(self, name: str, arguments: dict) -> str:
        if not self._tool_executor:
            return f"Error: Tools not available for {name}"
        return truncate_tool_result(self._tool_executor.execute(name, arguments))

    @pyqtSlot()
    def run_verify(self) -> None:
        """Validate API token and load models."""
        self._cancelled = False
        try:
            token = get_provider_secret(self._provider_id)
            if not token:
                self.error.emit("API token not configured. Add it in Settings → Pynia.")
                return

            settings = get_pynia_settings()
            base = settings.base_url(self._provider_id)
            models = FALLBACK_MODELS.get(self._provider_id, fallback_models())
            if self._provider_id in ("openai", "openrouter"):
                fetched = fetch_openai_models(base, token)
                if fetched:
                    models = normalize_models(fetched) or models
            self.models_ready.emit(models)
            from src.services.pynia.usage import _token_usage_snapshot

            self.usage_ready.emit(_token_usage_snapshot(self._provider_id, self._model, models))
            self.auth_ok.emit()
        except Exception as exc:
            logger.exception("Token provider verify failed")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    @pyqtSlot()
    def run_chat(self) -> None:
        self._cancelled = False
        try:
            token = get_provider_secret(self._provider_id)
            if not token:
                self.error.emit("API token not configured.")
                return

            settings = get_pynia_settings()
            is_cancelled = lambda: self._cancelled
            self._emit_progress({"phase_key": "activity_connecting", "step_id": "connect", "step_state": "active"})

            if self._provider_id == "anthropic":
                final = run_anthropic_agent_turn(
                    api_key=token,
                    model=self._model,
                    messages=self._messages,
                    tools=self._openai_tools,
                    attachments=self._attachments,
                    execute_tool=self._execute_tool,
                    tool_executor=self._tool_executor,
                    subagent_orchestrator=self._subagent_orchestrator,
                    on_chunk=self.chunk.emit,
                    on_tool_call=self.tool_call.emit,
                    on_tool_result=self.tool_result.emit,
                    is_cancelled=is_cancelled,
                    on_progress=self._emit_progress,
                )
            else:
                extra = OPENROUTER_HEADERS if self._provider_id == "openrouter" else None
                final = run_openai_agent_turn(
                    base_url=settings.base_url(self._provider_id),
                    api_key=token,
                    model=self._model,
                    messages=self._messages,
                    tools=self._openai_tools,
                    attachments=self._attachments,
                    execute_tool=self._execute_tool,
                    tool_executor=self._tool_executor,
                    subagent_orchestrator=self._subagent_orchestrator,
                    on_chunk=self.chunk.emit,
                    on_tool_call=self.tool_call.emit,
                    on_tool_result=self.tool_result.emit,
                    is_cancelled=is_cancelled,
                    extra_headers=extra,
                    on_progress=self._emit_progress,
                )
            self.complete.emit(final or "")
        except Exception as exc:
            logger.exception("Token agent chat failed")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()
