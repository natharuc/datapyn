"""IAcpAgent — the only ACP contract the rest of DataPyn should call."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .catalog import StatusKind

LIVE_TEST_COMMAND = "uv run pytest tests/test_pynia_acp_live.py -q"


@dataclass(frozen=True)
class FixStep:
    """One action the developer can run to fix a failed grant."""

    description: str
    command: str = ""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class ReasoningInfo:
    id: str
    name: str
    description: str = ""


@dataclass
class GrantResult:
    """Outcome of grant_configuration — ready, or the exact missing steps."""

    ok: bool
    agent_id: str
    status: StatusKind
    detail: str = ""
    steps: list[FixStep] = field(default_factory=list)
    models: list[ModelInfo] = field(default_factory=list)
    reasoning: list[ReasoningInfo] = field(default_factory=list)

    def rerun_step(self) -> FixStep:
        return FixStep(
            "When you finish the steps above, re-run the live ACP tests",
            LIVE_TEST_COMMAND,
        )


@dataclass
class ActionRequest:
    """Agent wants the user to allow or reject a tool/action."""

    rpc_id: object
    session_id: str
    params: dict[str, Any]
    summary: str = ""


@dataclass
class QuestionRequest:
    """Agent is asking the developer a question (elicitation / choice)."""

    rpc_id: object
    session_id: str
    prompt: str
    options: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IAcpAgentListener(Protocol):
    """Callbacks the agent invokes while a turn is running."""

    def on_receive_message(self, text: str) -> None: ...

    def on_thinking(self, text: str) -> None: ...

    def on_action(self, request: ActionRequest) -> None: ...

    def on_questions(self, request: QuestionRequest) -> None: ...

    def on_tool_event(self, payload: dict[str, Any]) -> None: ...

    def on_config_changed(self) -> None: ...


class NullAcpAgentListener:
    """No-op listener for tests and headless grant/list calls."""

    def on_receive_message(self, text: str) -> None:
        return

    def on_thinking(self, text: str) -> None:
        return

    def on_action(self, request: ActionRequest) -> None:
        return

    def on_questions(self, request: QuestionRequest) -> None:
        return

    def on_tool_event(self, payload: dict[str, Any]) -> None:
        return

    def on_config_changed(self) -> None:
        return


class IAcpAgent(ABC):
    """One conversation with one ACP CLI (Claude, Cursor, Copilot, or Codex)."""

    @property
    @abstractmethod
    def agent_id(self) -> str: ...

    @property
    @abstractmethod
    def session_id(self) -> str: ...

    @property
    @abstractmethod
    def is_ready(self) -> bool: ...

    @property
    def exposes_models(self) -> bool:
        return True

    @property
    def exposes_reasoning(self) -> bool:
        return False

    @property
    def current_model(self) -> str:
        return ""

    @property
    def current_reasoning(self) -> str:
        return ""

    @abstractmethod
    def grant_configuration(self, *, install: bool = True) -> GrantResult:
        """Probe, optionally install, handshake, and open a session."""

    @abstractmethod
    def send_message(
        self,
        text: str = "",
        attachments: Optional[list] = None,
        *,
        blocks: Optional[list[dict[str, Any]]] = None,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Send a user turn (session/prompt)."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def list_reasoning(self) -> list[ReasoningInfo]: ...

    def set_model(self, model_id: str) -> None:
        """Persist the model for this agent and push it to the live session."""
        model_id = str(model_id or "").strip()
        if not model_id:
            return
        self._persist_model(model_id)
        self._apply_model(model_id)

    def set_reasoning(self, level: str) -> None:
        """Persist the reasoning level for this agent and push it to the live session."""
        level = str(level or "").strip()
        if not level:
            return
        self._persist_reasoning(level)
        self._apply_reasoning(level)

    def _persist_model(self, model_id: str) -> None:
        from src.services.pynia.settings import get_pynia_settings

        get_pynia_settings().set_agent_model_id(self.agent_id, model_id)

    def _persist_reasoning(self, level: str) -> None:
        from src.services.pynia.settings import get_pynia_settings

        get_pynia_settings().set_agent_thought_level(self.agent_id, level)

    def _apply_model(self, model_id: str) -> None:
        return

    def _apply_reasoning(self, level: str) -> None:
        return

    @abstractmethod
    def cancel(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def answer_action(self, rpc_id: object, option_id: str) -> None: ...

    @abstractmethod
    def answer_questions(self, rpc_id: object, answers: Any) -> None: ...

    def complete(self, body: str, timeout: float = 4.0) -> str:
        """Optional ghost-text completion on a dedicated session."""
        return ""

    @property
    def completion_session_id(self) -> str:
        return ""

    def composer_config(self) -> dict[str, Any]:
        """LLM + Reasoning selectors for the chat composer."""
        return {"model": {}, "reasoning": {}}

    @property
    def config_snapshot(self) -> dict[str, Any]:
        return {}
