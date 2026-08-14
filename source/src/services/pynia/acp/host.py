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
from .permission import (
    HTTP_PROBE_REJECT_MESSAGE,
    allow_option_id,
    permission_should_ask,
    permission_should_reject,
    reject_option_id,
)
from .pool import AcpProcessPool
from .session_config import composer_selectors, merge_config_snapshot
from .turn_context import collect_tab_context, format_acp_prompt_parts

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
    config_options_changed = pyqtSignal(str, dict)  # tab_id, selectors

    def __init__(self, mcp_registry=None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.pool = AcpProcessPool(parent=self)
        self.mcp = PyniaMcpHost(mcp_registry, parent=self) if mcp_registry is not None else None
        self._states: dict[str, TabChatState] = {}
        self._acp_to_tab: dict[str, str] = {}
        self._permission_client: dict[object, AcpClient] = {}
        self._lock = threading.Lock()
        self.pool.stderr_line.connect(self._on_stderr)
        if self.mcp:
            self.mcp.tool_executed.connect(self._on_mcp_tool_result)

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
        if state.agent_id:
            self._kick_prepare_session(tab_id, state.agent_id)
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
        self._kick_prepare_session(tab_id, agent_id)

    def _kick_prepare_session(self, tab_id: str, agent_id: str) -> None:
        state = self.state(tab_id)
        if state.config_loading and state.agent_id == agent_id:
            return
        client = self.pool.get(agent_id)
        if (
            state.agent_id == agent_id
            and state.acp_session_id
            and client
            and client.is_running
            and str((client.last_session_info or {}).get("sessionId") or "") == state.acp_session_id
        ):
            self._store_snapshot(state, client)
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
            cwd = default_cwd()
            extra_args = self._agent_extra_args(agent_id, cwd, tab_id)
            client = self.pool.acquire(agent_id, cwd=cwd, extra_args=extra_args or None)
            self._wire_client(client)
            if state.agent_id != agent_id:
                return
            mcp_servers = self._mcp_servers_for(agent_id, tab_id, cwd)
            live_id = str((client.last_session_info or {}).get("sessionId") or "")
            if state.acp_session_id and live_id == state.acp_session_id:
                self._store_snapshot(state, client)
                self._apply_saved_config(client, state)
            else:
                old = state.acp_session_id
                if old:
                    self._acp_to_tab.pop(old, None)
                    state.acp_session_recreated = True
                    self.session_recreated.emit(state.tab_id)
                session_id = self._open_session(client, state, cwd, mcp_servers)
                if state.agent_id != agent_id:
                    return
                state.acp_session_id = session_id
                self.pool.retain(agent_id)
        except Exception as exc:
            logger.warning("Pynia session prepare failed: %s", exc)
            if state.agent_id == agent_id:
                client = self.pool.get(agent_id)
                live_id = str((client.last_session_info or {}).get("sessionId") or "") if client else ""
                if state.acp_session_id != live_id:
                    state.acp_session_id = None
                self.turn_error.emit(tab_id, str(exc))
        finally:
            if state.agent_id == agent_id:
                state.config_loading = False
                state.session_ready.set()
                self._emit_config(tab_id)

    def _mcp_servers_for(self, agent_id: str, tab_id: str, cwd: str) -> list:
        if not self.mcp:
            return []
        spec = get_agent(agent_id)
        if spec and spec.mcp_via_cursor_json:
            self.mcp.write_cursor_mcp_json(cwd, tab_id)
        self.mcp.current_tab = tab_id
        self.mcp.last_prompt_tab[agent_id] = tab_id
        return [self.mcp.mcp_server_config(tab_id)]

    def set_session_config(self, tab_id: str, kind: str, value: str) -> None:
        """Persist LLM / reasoning per agent and push it to the live ACP session."""
        from src.services.pynia.settings import get_pynia_settings

        state = self.state(tab_id)
        value = str(value or "").strip()
        if not state.agent_id or not value:
            return
        selectors = composer_selectors(state.config_snapshot)
        key = "model" if kind == "model" else "reasoning"
        selector = selectors.get(key) or {}
        allowed = {item["value"] for item in selector.get("values") or []}
        if allowed and value not in allowed:
            return
        settings = get_pynia_settings()
        if kind == "model":
            settings.set_agent_model_id(state.agent_id, value)
        elif kind in {"reasoning", "thought_level"}:
            settings.set_agent_thought_level(state.agent_id, value)
        else:
            return
        if not state.acp_session_id:
            return
        threading.Thread(
            target=self._push_config,
            args=(tab_id, kind, value),
            daemon=True,
            name=f"pynia-config-{tab_id}",
        ).start()

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
        client = self.pool.acquire(agent_id, cwd=cwd, extra_args=self._agent_extra_args(agent_id, cwd) or None)
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

    def _agent_extra_args(self, agent_id: str, cwd: str, tab_id: str = "") -> list[str]:
        if agent_id != "copilot" or not self.mcp:
            return []
        try:
            cfg_path = self.mcp.write_copilot_mcp_json(cwd, tab_id)
            return ["--additional-mcp-config", f"@{cfg_path}"]
        except Exception as exc:
            logger.debug("Copilot MCP config skipped: %s", exc)
            return []

    def _run_turn(self, tab_id: str, agent_id: str, prompt: Any) -> None:
        state = self.state(tab_id)
        try:
            cwd = default_cwd()
            extra_args = self._agent_extra_args(agent_id, cwd, tab_id)
            client = self.pool.acquire(agent_id, cwd=cwd, extra_args=extra_args or None)
            self._wire_client(client)
            state.session_ready.wait(timeout=45)
            mcp_servers = self._mcp_servers_for(agent_id, tab_id, cwd)

            if not state.acp_session_id:
                state.acp_session_id = self._open_session(client, state, cwd, mcp_servers)
                self.pool.retain(agent_id)

            state.agent_id = agent_id
            if not state.locked:
                state.locked = True
                self.agent_locked.emit(tab_id, agent_id)

            assistant = state.append_message("assistant", "")
            self.messages_changed.emit(tab_id)
            if isinstance(prompt, list):
                result = client.session_prompt(state.acp_session_id, prompt=prompt)
            else:
                result = client.session_prompt(state.acp_session_id, str(prompt))
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
        state.acp_session_id = session_id
        self._store_snapshot(state, client)
        self._apply_saved_config(client, state)
        self._emit_config(state.tab_id)
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
        self._store_snapshot(state, client)
        self._apply_saved_config(client, state)
        self._emit_config(state.tab_id)
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
        if kind == "config_option_update":
            state = self.state(tab_id)
            incoming = {}
            if update.get("configOptions") is not None:
                incoming["configOptions"] = update.get("configOptions")
            if update.get("models") is not None:
                incoming["models"] = update.get("models")
            if not incoming:
                return
            state.config_snapshot = merge_config_snapshot(state.config_snapshot, incoming)
            client = self.pool.get(state.agent_id or "")
            if client:
                client.last_session_info = merge_config_snapshot(client.last_session_info, incoming)
            self._emit_config(tab_id)
            return

    def _client_for_permission(self, params: dict) -> Optional[AcpClient]:
        acp_session_id = str((params or {}).get("sessionId") or "")
        tab_id = self._acp_to_tab.get(acp_session_id, "")
        state = self._states.get(tab_id)
        if state and state.agent_id:
            client = self.pool.get(state.agent_id)
            if client:
                return client
        running = [client for client in self.pool.clients() if client.is_running]
        if len(running) == 1:
            return running[0]
        return running[0] if running else None

    def _on_permission(self, rpc_id: object, params: dict) -> None:
        acp_session_id = str((params or {}).get("sessionId") or "")
        tab_id = self._acp_to_tab.get(acp_session_id, "")
        client = self._client_for_permission(params or {})
        if client:
            self._permission_client[rpc_id] = client
        if permission_should_reject(params or {}):
            self.answer_permission(rpc_id, reject_option_id(params or {}))
            if tab_id:
                self.tool_event.emit(
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
        if not permission_should_ask(params or {}):
            self.answer_permission(rpc_id, allow_option_id(params or {}))
            return
        if not tab_id:
            logger.warning("ACP permission with no tab mapping; rejecting")
            self.answer_permission(rpc_id, "reject-once")
            return
        self.permission_needed.emit(tab_id, rpc_id, params or {})

    def _store_snapshot(self, state: TabChatState, client: AcpClient) -> None:
        state.config_snapshot = merge_config_snapshot(
            state.config_snapshot, client.last_session_info or {}
        )

    def _merge_config_result(self, state: TabChatState, client: AcpClient, result: dict) -> None:
        if not isinstance(result, dict):
            return
        merged = merge_config_snapshot(state.config_snapshot or client.last_session_info, result)
        client.last_session_info = merged
        state.config_snapshot = dict(merged)

    def _emit_config(self, tab_id: str) -> None:
        state = self.state(tab_id)
        from src.services.pynia.settings import get_pynia_settings

        settings = get_pynia_settings()
        agent_id = state.agent_id or ""
        loading = bool(state.config_loading and not (state.config_snapshot or {}).get("configOptions"))
        self.config_options_changed.emit(
            tab_id,
            composer_selectors(
                state.config_snapshot,
                model_id=settings.agent_model_id(agent_id) if agent_id else "",
                thought_level=settings.agent_thought_level(agent_id) if agent_id else "",
                loading=loading,
            ),
        )

    def _apply_saved_config(self, client: AcpClient, state: TabChatState) -> None:
        from src.services.pynia.settings import get_pynia_settings

        if not state.acp_session_id or not state.agent_id:
            return
        settings = get_pynia_settings()
        snapshot = state.config_snapshot or client.last_session_info or {}
        selectors = composer_selectors(
            snapshot,
            model_id=settings.agent_model_id(state.agent_id),
            thought_level=settings.agent_thought_level(state.agent_id),
        )
        model = selectors.get("model") or {}
        pref_model = settings.agent_model_id(state.agent_id)
        model_ids = {item["value"] for item in model.get("values") or []}
        if pref_model and pref_model in model_ids and not model.get("hidden"):
            self._set_config_option(client, state, model["id"], pref_model, kind="model")
        reasoning = composer_selectors(
            state.config_snapshot or client.last_session_info,
            thought_level=settings.agent_thought_level(state.agent_id),
        ).get("reasoning") or {}
        pref_thought = settings.agent_thought_level(state.agent_id)
        thought_ids = {item["value"] for item in reasoning.get("values") or []}
        if pref_thought and pref_thought in thought_ids and not reasoning.get("hidden"):
            self._set_config_option(client, state, reasoning["id"], pref_thought, kind="reasoning")

    def _set_config_option(
        self,
        client: AcpClient,
        state: TabChatState,
        config_id: str,
        value: str,
        *,
        kind: str,
    ) -> None:
        try:
            result = client.session_set_config_option(state.acp_session_id, config_id, value)
            self._merge_config_result(state, client, result)
            return
        except Exception as exc:
            logger.debug("ACP set_config_option failed: %s", exc)
        if kind != "model":
            return
        try:
            result = client.session_set_model(state.acp_session_id, value)
            self._merge_config_result(state, client, result)
        except Exception as exc:
            logger.debug("ACP set_model failed: %s", exc)

    def _push_config(self, tab_id: str, kind: str, value: str) -> None:
        state = self.state(tab_id)
        client = self.pool.get(state.agent_id or "")
        if not client or not state.acp_session_id or not value:
            return
        selectors = composer_selectors(state.config_snapshot or client.last_session_info)
        selector = selectors["model"] if kind == "model" else selectors["reasoning"]
        if selector.get("hidden"):
            return
        self._set_config_option(client, state, selector["id"], value, kind=kind)
        self._emit_config(tab_id)

    def _on_mcp_tool_result(self, tab_id: str, name: str, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("error"):
            return
        target = tab_id or (self.mcp.current_tab if self.mcp else "")
        if not target:
            return
        self.tool_event.emit(
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
                self.tool_event.emit(
                    tab_id,
                    {
                        "sessionUpdate": "tool_call_update",
                        "title": "DataPyn MCP",
                        "status": "failed",
                        "isError": True,
                        "content": [{"type": "text", "text": line.strip()}],
                    },
                )
