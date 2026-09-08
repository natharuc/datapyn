"""Pynia ACP host — per-tab chats, agent lock, MCP, Qt signals."""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .agent import ActionRequest, IAcpAgent, QuestionRequest
from .agents.factory import create_acp_agent
from .binding import TabChatState
from .catalog import default_cwd, get_agent
from .mcp_host import PyniaMcpHost
from .permission import (
    HTTP_PROBE_REJECT_MESSAGE,
    allow_option_id,
    permission_should_ask,
    permission_should_reject,
    reject_option_id,
)
from .pool import AcpProcessPool
from .session_config import composer_selectors
from .turn_context import collect_tab_context, format_acp_prompt_parts

logger = logging.getLogger(__name__)


class _TabListener:
    """Forwards IAcpAgent callbacks to the host for one DataPyn tab."""

    def __init__(self, host: "PyniaAcpHost", tab_id: str):
        self._host = host
        self._tab_id = tab_id

    def on_receive_message(self, text: str) -> None:
        self._host._on_agent_message(self._tab_id, text)

    def on_thinking(self, text: str) -> None:
        self._host._record_thinking(self._tab_id, text)
        self._host.thinking.emit(self._tab_id, text)

    def on_action(self, request: ActionRequest) -> None:
        self._host._handle_action(self._tab_id, request)

    def on_questions(self, request: QuestionRequest) -> None:
        self._host._handle_questions(self._tab_id, request)

    def on_tool_event(self, payload: dict[str, Any]) -> None:
        self._host._emit_tool(self._tab_id, payload)

    def on_config_changed(self) -> None:
        self._host._emit_config(self._tab_id)


class PyniaAcpHost(QObject):
    """Owns one IAcpAgent conversation per DataPyn tab."""

    messages_changed = pyqtSignal(str)
    chunk = pyqtSignal(str, str)  # tab_id, text
    thinking = pyqtSignal(str, str)
    tool_event = pyqtSignal(str, dict)  # tab_id, payload
    permission_needed = pyqtSignal(str, object, dict)  # tab_id, rpc_id, params
    turn_ended = pyqtSignal(str)
    turn_error = pyqtSignal(str, str)
    busy_changed = pyqtSignal(str, bool)
    agent_locked = pyqtSignal(str, str)  # tab_id, agent_id
    session_recreated = pyqtSignal(str)
    config_options_changed = pyqtSignal(str, dict)  # tab_id, selectors

    def __init__(self, mcp_registry=None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.pool = AcpProcessPool(parent=self)
        self.mcp = PyniaMcpHost(mcp_registry, parent=self) if mcp_registry is not None else None
        self._states: dict[str, TabChatState] = {}
        self._agents: dict[str, IAcpAgent] = {}
        self._permission_tab: dict[object, str] = {}
        self._lock = threading.Lock()
        self.pool.stderr_line.connect(self._on_stderr)
        self.chunk.connect(self._append_assistant_chunk)
        if self.mcp:
            self.mcp.tool_executed.connect(self._on_mcp_tool_result)

    def start(self) -> None:
        if self.mcp:
            self.mcp.start()

    def shutdown(self) -> None:
        for tab_id in list(self._agents):
            self._close_agent(tab_id)
        self.pool.stop_all()
        if self.mcp:
            self.mcp.stop()

    def attach_tab(self, tab_id: str, data: Optional[dict[str, Any]] = None) -> TabChatState:
        if tab_id in self._states:
            return self._states[tab_id]
        state = TabChatState.from_dict(tab_id, data)
        self._states[tab_id] = state
        if state.agent_id:
            self._kick_prepare_session(tab_id, state.agent_id)
        return state

    def detach_tab(self, tab_id: str) -> None:
        self._states.pop(tab_id, None)
        self._close_agent(tab_id)

    def state(self, tab_id: str) -> TabChatState:
        if tab_id not in self._states:
            self._states[tab_id] = TabChatState(tab_id=tab_id)
        return self._states[tab_id]

    def export_state(self, tab_id: str) -> dict[str, Any]:
        return self.state(tab_id).to_dict()

    def set_agent(self, tab_id: str, agent_id: str) -> None:
        state = self.state(tab_id)
        if state.locked and state.agent_id and state.agent_id != agent_id:
            raise RuntimeError("Agent is locked for this tab")
        if get_agent(agent_id) is None:
            raise RuntimeError(f"Unknown agent: {agent_id}")
        self._kick_prepare_session(tab_id, agent_id)

    def _kick_prepare_session(self, tab_id: str, agent_id: str) -> None:
        state = self.state(tab_id)
        if state.config_loading and state.agent_id == agent_id:
            return
        existing = self._agents.get(tab_id)
        if existing is not None and existing.agent_id != agent_id:
            self._close_agent(tab_id)
            existing = None
        if (
            state.agent_id == agent_id
            and existing is not None
            and existing.agent_id == agent_id
            and existing.is_ready
        ):
            state.acp_session_id = existing.session_id
            state.config_snapshot = existing.config_snapshot
            self._emit_config(tab_id)
            return
        state.agent_id = agent_id
        state.config_snapshot = {}
        state.config_loading = True
        state.session_ready.clear()
        self._emit_config(tab_id)
        threading.Thread(
            target=self._prepare_session,
            args=(tab_id, agent_id),
            daemon=True,
            name=f"pynia-session-{tab_id}",
        ).start()

    def _prepare_session(self, tab_id: str, agent_id: str) -> None:
        state = self.state(tab_id)
        try:
            if state.agent_id != agent_id:
                return
            agent = self._ensure_agent(tab_id, agent_id)
            result = agent.grant_configuration(install=False)
            if state.agent_id != agent_id:
                return
            if not result.ok:
                state.acp_session_id = None
                self.turn_error.emit(tab_id, result.detail or result.status)
                return
            old = state.acp_session_id
            state.acp_session_id = agent.session_id
            state.config_snapshot = agent.config_snapshot
            if old and old != agent.session_id:
                state.acp_session_recreated = True
                self.session_recreated.emit(tab_id)
        except Exception as exc:
            logger.warning("Pynia session prepare failed: %s", exc)
            if state.agent_id == agent_id:
                state.acp_session_id = None
                self.turn_error.emit(tab_id, str(exc))
        finally:
            if state.agent_id == agent_id:
                state.config_loading = False
                state.session_ready.set()
                self._emit_config(tab_id)

    def _mcp_servers_for(self, agent_id: str, tab_id: str, cwd: str) -> list:
        if not self.mcp:
            logger.warning("Pynia MCP host missing — agent %s will have no datapyn_* tools", agent_id)
            return []
        spec = get_agent(agent_id)
        if spec and spec.mcp_via_cursor_json:
            ok = self.mcp.write_cursor_mcp_json(cwd, tab_id)
            if not ok:
                logger.warning(
                    "Cursor MCP config write failed for tab %s — tools may be unavailable",
                    tab_id,
                )
        self.mcp.current_tab = tab_id
        self.mcp.last_prompt_tab[agent_id] = tab_id
        if agent_id == "copilot":
            # CLI --additional-mcp-config is the sole source; session/new would duplicate.
            return []
        return [self.mcp.mcp_server_config(tab_id)]

    def set_session_config(self, tab_id: str, kind: str, value: str) -> None:
        """Persist LLM / reasoning per agent and push it to the live ACP session."""
        state = self.state(tab_id)
        value = str(value or "").strip()
        if not state.agent_id or not value:
            return
        agent = self._agents.get(tab_id)
        snapshot = state.config_snapshot
        if agent is not None:
            snapshot = agent.config_snapshot or snapshot
        selectors = composer_selectors(snapshot)
        key = "model" if kind == "model" else "reasoning"
        selector = selectors.get(key) or {}
        allowed = {item["value"] for item in selector.get("values") or []}
        if allowed and value not in allowed:
            return
        if kind == "model":
            if agent is not None:
                agent.set_model(value)
            else:
                from src.services.pynia.settings import get_pynia_settings

                get_pynia_settings().set_agent_model_id(state.agent_id, value)
        elif kind in {"reasoning", "thought_level"}:
            if agent is not None:
                agent.set_reasoning(value)
            else:
                from src.services.pynia.settings import get_pynia_settings

                get_pynia_settings().set_agent_thought_level(state.agent_id, value)
        else:
            return
        if agent is not None:
            state.config_snapshot = agent.config_snapshot
        self._emit_config(tab_id)

    def send_prompt(
        self,
        tab_id: str,
        text: str,
        agent_id: Optional[str] = None,
        attachments: Optional[list] = None,
    ) -> None:
        from src.services.pynia.acp.attachments import display_attachments, normalize_attachments

        state = self.state(tab_id)
        if state.busy:
            raise RuntimeError("Pynia is already working on this tab")
        chosen = agent_id or state.agent_id
        if state.locked:
            chosen = state.agent_id
        if not chosen:
            raise RuntimeError("Choose an agent first")
        if state.locked and chosen != state.agent_id:
            raise RuntimeError("Agent cannot be changed after the conversation starts")
        files = normalize_attachments(attachments)
        if not (text or "").strip() and not files:
            return
        state.busy = True
        state.reset_activity()
        self.busy_changed.emit(tab_id, True)
        extra: dict[str, Any] = {}
        shown = display_attachments(files)
        if shown:
            extra["attachments"] = shown
        state.append_message("user", text or "", **extra)
        self.messages_changed.emit(tab_id)
        registry = self.mcp._registry if self.mcp else None
        try:
            context = collect_tab_context(tab_id, registry=registry)
            prompt_blocks = format_acp_prompt_parts(text, context, attachments=files)
        except Exception as exc:
            logger.debug("ACP tab context failed: %s", exc)
            prompt_blocks = format_acp_prompt_parts(
                text, {"tab_id": tab_id}, attachments=files
            )
        threading.Thread(
            target=self._run_turn,
            args=(tab_id, chosen, prompt_blocks),
            daemon=True,
            name=f"pynia-turn-{tab_id}",
        ).start()

    def cancel(self, tab_id: str) -> None:
        agent = self._agents.get(tab_id)
        if agent:
            agent.cancel()

    def answer_permission(self, rpc_id: object, option_id: str) -> None:
        tab_id = self._permission_tab.pop(rpc_id, None)
        if not tab_id:
            return
        agent = self._agents.get(tab_id)
        if agent:
            agent.answer_action(rpc_id, option_id)

    def complete_inline(self, tab_id: str, body: str, timeout: float = 4.0) -> str:
        """Short completion prompt on a dedicated ACP session. Never mixes with chat."""
        from src.services.pynia.settings import get_pynia_settings

        if not get_pynia_settings().autocomplete_enabled:
            return ""
        state = self.state(tab_id)
        agent_id = state.agent_id or get_pynia_settings().default_agent_id
        if not agent_id:
            return ""
        agent = self._ensure_agent(tab_id, agent_id)
        if not agent.is_ready:
            result = agent.grant_configuration(install=False)
            if not result.ok:
                return ""
            state.acp_session_id = agent.session_id
        text = agent.complete(body, timeout=timeout)
        state.completion_session_id = agent.completion_session_id or None
        return text

    def _agent_extra_args(self, agent_id: str, cwd: str, tab_id: str = "") -> list[str]:
        if agent_id != "copilot" or not self.mcp:
            return []
        try:
            cfg_path = self.mcp.write_copilot_mcp_json(cwd, tab_id)
            return ["--additional-mcp-config", f"@{cfg_path}"]
        except Exception as exc:
            logger.warning("Copilot MCP config skipped — datapyn_* tools unavailable: %s", exc)
            return []

    def _ensure_agent(self, tab_id: str, agent_id: str):
        existing = self._agents.get(tab_id)
        if existing is not None and existing.agent_id == agent_id:
            cwd = default_cwd()
            existing.bind(
                cwd=cwd,
                extra_args=self._agent_extra_args(agent_id, cwd, tab_id),
                mcp_servers=self._mcp_servers_for(agent_id, tab_id, cwd),
            )
            return existing
        if existing is not None:
            existing.close()
        cwd = default_cwd()
        agent = create_acp_agent(
            agent_id,
            _TabListener(self, tab_id),
            pool=self.pool,
            cwd=cwd,
            extra_args=self._agent_extra_args(agent_id, cwd, tab_id) or None,
            mcp_servers=self._mcp_servers_for(agent_id, tab_id, cwd),
        )
        self._agents[tab_id] = agent
        return agent

    def _close_agent(self, tab_id: str) -> None:
        agent = self._agents.pop(tab_id, None)
        if agent is None:
            return
        try:
            agent.close()
        except Exception:
            pass

    def _run_turn(self, tab_id: str, agent_id: str, prompt: Any) -> None:
        state = self.state(tab_id)
        try:
            agent = self._ensure_agent(tab_id, agent_id)
            state.session_ready.wait(timeout=45)
            if not agent.is_ready:
                result = agent.grant_configuration(install=False)
                if not result.ok:
                    raise RuntimeError(result.detail or result.status)
            state.agent_id = agent_id
            state.acp_session_id = agent.session_id
            state.config_snapshot = agent.config_snapshot
            if not state.locked:
                state.locked = True
                self.agent_locked.emit(tab_id, agent_id)

            assistant = state.append_message("assistant", "")
            self.messages_changed.emit(tab_id)
            if isinstance(prompt, list):
                result = agent.send_message(blocks=prompt)
            else:
                result = agent.send_message(str(prompt))
            stop = (result or {}).get("stopReason") or ""
            if stop == "cancelled" and not (assistant.get("content") or "").strip():
                assistant["content"] = ""
        except Exception as exc:
            logger.warning("Pynia turn failed: %s", exc)
            self.turn_error.emit(tab_id, str(exc))
            state.append_message("assistant", str(exc), error=True)
            self.messages_changed.emit(tab_id)
        finally:
            self._seal_activity(state)
            state.busy = False
            self.busy_changed.emit(tab_id, False)
            self.turn_ended.emit(tab_id)

    def _emit_tool(self, tab_id: str, payload: dict[str, Any]) -> None:
        self._record_tool_event(tab_id, payload)
        self.tool_event.emit(tab_id, payload)

    def _record_thinking(self, tab_id: str, text: str) -> None:
        self.state(tab_id).record_thinking(text)

    def _record_tool_event(self, tab_id: str, payload: dict[str, Any]) -> None:
        from src.services.pynia.acp.activity import format_activity_tool

        card = format_activity_tool(payload)
        if card:
            self.state(tab_id).record_tool(card)

    def _seal_activity(self, state: TabChatState) -> None:
        activity = state.consume_activity()
        if not activity:
            return
        for msg in reversed(state.messages):
            if msg.get("role") == "assistant":
                msg["activity"] = activity
                return

    def _on_agent_message(self, tab_id: str, text: str) -> None:
        self.chunk.emit(tab_id, text)

    def _append_assistant_chunk(self, tab_id: str, text: str) -> None:
        state = self.state(tab_id)
        if state.messages and state.messages[-1].get("role") == "assistant":
            state.messages[-1]["content"] = (state.messages[-1].get("content") or "") + text

    def _handle_action(self, tab_id: str, request: ActionRequest) -> None:
        params = request.params or {}
        if permission_should_reject(params):
            self._reply_permission(tab_id, request.rpc_id, reject_option_id(params))
            self._emit_tool(
                tab_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "title": "Blocked HTTP probe",
                    "status": "failed",
                    "isError": True,
                    "content": [{"type": "text", "text": HTTP_PROBE_REJECT_MESSAGE}],
                },
            )
            return
        if not permission_should_ask(params):
            self._reply_permission(tab_id, request.rpc_id, allow_option_id(params))
            return
        if not tab_id:
            logger.warning("ACP permission with no tab mapping; rejecting")
            self._reply_permission(tab_id, request.rpc_id, "reject-once")
            return
        self._permission_tab[request.rpc_id] = tab_id
        self.permission_needed.emit(tab_id, request.rpc_id, params)

    def _handle_questions(self, tab_id: str, request: QuestionRequest) -> None:
        if not tab_id:
            self._reply_permission(tab_id, request.rpc_id, "reject-once")
            return
        self._permission_tab[request.rpc_id] = tab_id
        params = dict(request.params or {})
        if request.prompt and not params.get("title"):
            params["title"] = request.prompt
        self.permission_needed.emit(tab_id, request.rpc_id, params)

    def _reply_permission(self, tab_id: str, rpc_id: object, option_id: str) -> None:
        agent = self._agents.get(tab_id)
        if agent:
            agent.answer_action(rpc_id, option_id)

    def _emit_config(self, tab_id: str) -> None:
        state = self.state(tab_id)
        agent = self._agents.get(tab_id)
        if agent is not None:
            state.config_snapshot = agent.config_snapshot or state.config_snapshot
            selectors = agent.composer_config()
            if state.config_loading and not state.config_snapshot:
                from .session_config import composer_selectors as _selectors

                selectors = _selectors({}, loading=True)
            self.config_options_changed.emit(tab_id, selectors)
            return
        from src.services.pynia.settings import get_pynia_settings

        settings = get_pynia_settings()
        agent_id = state.agent_id or ""
        snap = state.config_snapshot or {}
        loading = bool(
            state.config_loading
            and not snap.get("configOptions")
            and not snap.get("models")
        )
        selectors = composer_selectors(
            snap,
            model_id=settings.agent_model_id(agent_id) if agent_id else "",
            thought_level=settings.agent_thought_level(agent_id) if agent_id else "",
            loading=loading,
        )
        self.config_options_changed.emit(tab_id, selectors)

    def _on_mcp_tool_result(self, tab_id: str, name: str, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("error"):
            return
        target = tab_id or (self.mcp.current_tab if self.mcp else "")
        if not target:
            return
        self._emit_tool(
            target,
            {
                "sessionUpdate": "tool_call_update",
                "title": name or "tool",
                "status": "failed",
                "isError": True,
                "content": [{"type": "text", "text": str(result.get("error") or "")}],
            },
        )

    def _on_stderr(self, agent_id: str, line: str) -> None:
        logger.debug("[%s] %s", agent_id, line)
        lower = (line or "").lower()
        if any(
            token in lower
            for token in ("datapyn_mcp", "mcp_stdio", "failed to start mcp", "mcp server")
        ):
            logger.warning("Pynia MCP stderr [%s]: %s", agent_id, line)
            tab_id = ""
            if self.mcp:
                tab_id = self.mcp.current_tab or next(
                    iter(self.mcp.last_prompt_tab.values()), ""
                )
            if tab_id:
                self._emit_tool(
                    tab_id,
                    {
                        "sessionUpdate": "tool_call_update",
                        "title": "DataPyn MCP",
                        "status": "failed",
                        "isError": True,
                        "content": [{"type": "text", "text": line.strip()}],
                    },
                )
