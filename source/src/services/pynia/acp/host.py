"""Pynia ACP host — per-tab chats, agent lock, MCP, Qt signals."""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from .binding import TabChatState
from .catalog import default_cwd, get_agent
from .client import AcpClient
from .mcp_host import PyniaMcpHost
from .pool import AcpProcessPool

logger = logging.getLogger(__name__)

_COMPLETION_PROMPT = (
    "You are a code completion engine. Return ONLY the ghost-text to insert "
    "at the cursor. No markdown, no explanation, no tools.\n\n{body}"
)


class PyniaAcpHost(QObject):
    """Owns ACP processes and one chat binding per DataPyn tab."""

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

    def __init__(self, mcp_registry=None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.pool = AcpProcessPool(parent=self)
        self.mcp = PyniaMcpHost(mcp_registry, parent=self) if mcp_registry is not None else None
        self._states: dict[str, TabChatState] = {}
        self._acp_to_tab: dict[str, str] = {}
        self._permission_client: dict[object, AcpClient] = {}
        self._lock = threading.Lock()
        self.pool.stderr_line.connect(self._on_stderr)

    def start(self) -> None:
        if self.mcp:
            self.mcp.start()

    def shutdown(self) -> None:
        self.pool.stop_all()
        if self.mcp:
            self.mcp.stop()

    def attach_tab(self, tab_id: str, data: Optional[dict[str, Any]] = None) -> TabChatState:
        if tab_id in self._states:
            return self._states[tab_id]
        state = TabChatState.from_dict(tab_id, data)
        self._states[tab_id] = state
        if state.acp_session_id:
            self._acp_to_tab[state.acp_session_id] = tab_id
        return state

    def detach_tab(self, tab_id: str) -> None:
        state = self._states.pop(tab_id, None)
        if not state:
            return
        if state.acp_session_id:
            self._acp_to_tab.pop(state.acp_session_id, None)
            client = self.pool.get(state.agent_id or "")
            if client:
                try:
                    client.session_close(state.acp_session_id)
                except Exception:
                    pass
            if state.agent_id:
                self.pool.release_session(state.agent_id)
        if state.completion_session_id and state.agent_id:
            client = self.pool.get(state.agent_id)
            if client:
                try:
                    client.session_close(state.completion_session_id)
                except Exception:
                    pass

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
        state.agent_id = agent_id

    def send_prompt(self, tab_id: str, text: str, agent_id: Optional[str] = None) -> None:
        state = self.state(tab_id)
        if state.busy:
            raise RuntimeError("Pynia is already working on this tab")
        chosen = agent_id or state.agent_id
        if state.locked:
            chosen = state.agent_id
        if not chosen:
            from src.services.pynia.settings import get_pynia_settings

            chosen = get_pynia_settings().default_agent_id
        if not chosen:
            raise RuntimeError("Choose an agent first")
        if state.locked and chosen != state.agent_id:
            raise RuntimeError("Agent cannot be changed after the conversation starts")
        state.busy = True
        self.busy_changed.emit(tab_id, True)
        state.append_message("user", text)
        self.messages_changed.emit(tab_id)
        threading.Thread(
            target=self._run_turn,
            args=(tab_id, chosen, text),
            daemon=True,
            name=f"pynia-turn-{tab_id}",
        ).start()

    def cancel(self, tab_id: str) -> None:
        state = self.state(tab_id)
        client = self.pool.get(state.agent_id or "")
        if client and state.acp_session_id:
            client.session_cancel(state.acp_session_id)

    def answer_permission(self, rpc_id: object, option_id: str) -> None:
        client = self._permission_client.pop(rpc_id, None)
        if not client:
            return
        client.respond(
            rpc_id,
            {"outcome": {"outcome": "selected", "optionId": option_id}},
        )

    def complete_inline(self, tab_id: str, body: str, timeout: float = 4.0) -> str:
        """Short completion prompt on a dedicated ACP session. Never mixes with chat."""
        from src.services.pynia.settings import get_pynia_settings

        if not get_pynia_settings().autocomplete_enabled:
            return ""
        state = self.state(tab_id)
        agent_id = state.agent_id or get_pynia_settings().default_agent_id
        if not agent_id:
            return ""
        cwd = default_cwd()
        client = self.pool.acquire(agent_id, cwd=cwd)
        self._wire_client(client)
        session_id = state.completion_session_id
        if not session_id:
            session_id = client.session_new(cwd, mcp_servers=[])
            state.completion_session_id = session_id
        prompt = _COMPLETION_PROMPT.format(body=body)
        chunks: list[str] = []

        def on_update(_sid: str, update: dict) -> None:
            if _sid != session_id:
                return
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content") or {}
                if content.get("type") == "text":
                    chunks.append(content.get("text") or "")
            if update.get("sessionUpdate") == "tool_call":
                try:
                    client.session_cancel(session_id)
                except Exception:
                    pass

        client.session_update.connect(on_update, Qt.ConnectionType.DirectConnection)
        try:
            client.session_prompt(session_id, prompt, timeout=timeout)
        except Exception:
            return ""
        finally:
            try:
                client.session_update.disconnect(on_update)
            except Exception:
                pass
        text = "".join(chunks).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return text

    def _run_turn(self, tab_id: str, agent_id: str, text: str) -> None:
        state = self.state(tab_id)
        try:
            cwd = default_cwd()
            client = self.pool.acquire(agent_id, cwd=cwd)
            self._wire_client(client)
            mcp_servers = []
            if self.mcp:
                mcp_servers = [self.mcp.mcp_server_config(tab_id)]
                spec = get_agent(agent_id)
                if spec and spec.mcp_via_cursor_json:
                    self.mcp.write_cursor_mcp_json(cwd, tab_id)
                self.mcp.last_prompt_tab[agent_id] = tab_id

            if not state.acp_session_id:
                state.acp_session_id = self._open_session(client, state, cwd, mcp_servers)
                self.pool.retain(agent_id)
            else:
                self._ensure_session(client, state, cwd, mcp_servers)

            state.agent_id = agent_id
            if not state.locked:
                state.locked = True
                self.agent_locked.emit(tab_id, agent_id)

            assistant = state.append_message("assistant", "")
            self.messages_changed.emit(tab_id)
            result = client.session_prompt(state.acp_session_id, text)
            stop = (result or {}).get("stopReason") or ""
            if stop == "cancelled" and not (assistant.get("content") or "").strip():
                assistant["content"] = ""
        except Exception as exc:
            logger.warning("Pynia turn failed: %s", exc)
            self.turn_error.emit(tab_id, str(exc))
            state.append_message("assistant", str(exc), error=True)
            self.messages_changed.emit(tab_id)
        finally:
            state.busy = False
            self.busy_changed.emit(tab_id, False)
            self.turn_ended.emit(tab_id)

    def _open_session(self, client: AcpClient, state: TabChatState, cwd: str, mcp_servers: list) -> str:
        session_id = client.session_new(cwd, mcp_servers=mcp_servers)
        self._acp_to_tab[session_id] = state.tab_id
        return session_id

    def _ensure_session(self, client: AcpClient, state: TabChatState, cwd: str, mcp_servers: list) -> None:
        caps = client.agent_capabilities or {}
        session_caps = caps.get("sessionCapabilities") or {}
        sid = state.acp_session_id
        if not sid:
            return
        try:
            if session_caps.get("resume") is not None:
                client.session_resume(sid, cwd, mcp_servers)
                return
            if caps.get("loadSession"):
                client.session_load(sid, cwd, mcp_servers)
                return
        except Exception as exc:
            logger.info("ACP session restore failed, creating a new one: %s", exc)
        new_id = client.session_new(cwd, mcp_servers=mcp_servers)
        self._acp_to_tab.pop(sid, None)
        self._acp_to_tab[new_id] = state.tab_id
        state.acp_session_id = new_id
        state.acp_session_recreated = True
        self.session_recreated.emit(state.tab_id)

    def _wire_client(self, client: AcpClient) -> None:
        try:
            client.session_update.disconnect(self._on_session_update)
        except TypeError:
            pass
        try:
            client.permission_request.disconnect(self._on_permission)
        except TypeError:
            pass
        client.session_update.connect(self._on_session_update)
        client.permission_request.connect(self._on_permission)

    def _on_session_update(self, acp_session_id: str, update: dict) -> None:
        tab_id = self._acp_to_tab.get(acp_session_id)
        if not tab_id:
            return
        kind = update.get("sessionUpdate") or ""
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = update.get("content") or {}
            text = content.get("text") or ""
            if not text:
                return
            if kind == "agent_thought_chunk":
                self.thinking.emit(tab_id, text)
                return
            state = self.state(tab_id)
            if state.messages and state.messages[-1].get("role") == "assistant":
                state.messages[-1]["content"] = (state.messages[-1].get("content") or "") + text
            self.chunk.emit(tab_id, text)
            return
        if kind in {"tool_call", "tool_call_update"}:
            self.tool_event.emit(tab_id, update)
            return

    def _on_permission(self, rpc_id: object, params: dict) -> None:
        acp_session_id = str((params or {}).get("sessionId") or "")
        tab_id = self._acp_to_tab.get(acp_session_id, "")
        client = None
        state = self._states.get(tab_id)
        if state and state.agent_id:
            client = self.pool.get(state.agent_id)
        if client:
            self._permission_client[rpc_id] = client
        # Auto-allow DataPyn MCP tools; ask for everything else.
        title = str((params or {}).get("toolCall") or "")
        if "datapyn_" in title:
            self.answer_permission(rpc_id, "allow-once")
            return
        self.permission_needed.emit(tab_id, rpc_id, params or {})

    def _on_stderr(self, agent_id: str, line: str) -> None:
        logger.debug("[%s] %s", agent_id, line)
