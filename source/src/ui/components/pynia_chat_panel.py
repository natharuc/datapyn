"""Pynia chat dock — one ACP conversation per DataPyn tab."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QSize, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from src.design_system.tokens import get_colors
from src.language import S
from src.services.pynia.acp.catalog import icon_data_uri, list_agents, probe_status
from src.services.pynia.acp.host import PyniaAcpHost
from src.services.pynia.settings import get_pynia_settings

logger = logging.getLogger(__name__)


class _ChatView(QWebEngineView):
    """WebEngine views report a huge sizeHint that fights QDockWidget resizing."""

    def sizeHint(self):
        return QSize(420, 520)

    def minimumSizeHint(self):
        return QSize(240, 140)


class _ChatEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        logger.info("Pynia chat JS %s:%s %s", sourceID, lineNumber, message)


class _ChatBridge(QObject):
    message_submitted = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    agent_selected = pyqtSignal(str)
    settings_requested = pyqtSignal()
    permission_answered = pyqtSignal(str, str)
    web_view_ready = pyqtSignal()

    @pyqtSlot()
    def ready(self):
        self.web_view_ready.emit()

    @pyqtSlot(str)
    def sendMessage(self, text: str):
        self.message_submitted.emit(text)

    @pyqtSlot()
    def cancel(self):
        self.cancel_requested.emit()

    @pyqtSlot(str)
    def selectAgent(self, agent_id: str):
        self.agent_selected.emit(agent_id)

    @pyqtSlot()
    def openSettings(self):
        self.settings_requested.emit()

    @pyqtSlot(str, str)
    def answerPermission(self, rpc_id: str, option_id: str):
        self.permission_answered.emit(rpc_id, option_id)


class PyniaChatPanel(QWidget):
    insert_code_requested = pyqtSignal(str)
    thinking_started = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, host: PyniaAcpHost | None = None, theme_manager=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.theme_manager = theme_manager
        self._tab_id = ""
        self._tab_name = ""
        self._webview_ready = False
        self._pending: list[str] = []
        self._setup_ui()
        if host:
            self.set_host(host)

    def set_host(self, host: PyniaAcpHost) -> None:
        self.host = host
        host.messages_changed.connect(self._on_messages_changed)
        host.chunk.connect(self._on_chunk)
        host.thinking.connect(self._on_thinking)
        host.tool_event.connect(self._on_tool)
        host.permission_needed.connect(self._on_permission)
        host.busy_changed.connect(self._on_busy)
        host.turn_error.connect(self._on_error)
        host.agent_locked.connect(lambda *_: self._refresh_header())
        host.session_recreated.connect(lambda *_: self._refresh_header())

    def set_mcp_server(self, _mcp_server) -> None:
        return

    def cleanup(self) -> None:
        return

    def submit_prompt(self, text: str) -> None:
        self._on_send(text)

    def switch_tab_context(self, tab_id: str, tab_name: str = "", pynia_data=None) -> None:
        self._tab_id = tab_id or ""
        self._tab_name = tab_name or ""
        if self.host and self._tab_id:
            self.host.attach_tab(self._tab_id, pynia_data)
        self._hydrate()

    def notify_block_focused(self, _block=None) -> None:
        return

    def focus_input(self) -> None:
        self._js("focusComposer()")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._web = _ChatView(self)
        self._web.setPage(_ChatEnginePage(self._web))
        self._web.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._web.setMinimumSize(240, 140)
        settings = self._web.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self._channel = QWebChannel(self._web.page())
        self._bridge = _ChatBridge(self)
        self._channel.registerObject("bridge", self._bridge)
        self._web.page().setWebChannel(self._channel)
        self._bridge.web_view_ready.connect(self._on_ready)
        self._bridge.message_submitted.connect(self._on_send)
        self._bridge.cancel_requested.connect(self._on_cancel)
        self._bridge.agent_selected.connect(self._on_select_agent)
        self._bridge.settings_requested.connect(self.settings_requested.emit)
        self._bridge.permission_answered.connect(self._on_permission_answer)
        layout.addWidget(self._web)
        template = self._template_path()
        if template.exists():
            self._web.setUrl(QUrl.fromLocalFile(str(template)))

    def _template_path(self) -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS) / "src" / "ui" / "components" / "pynia_chat_app.html"
        return Path(__file__).parent / "pynia_chat_app.html"

    def _js(self, code: str) -> None:
        if not self._webview_ready:
            self._pending.append(code)
            return
        self._web.page().runJavaScript(code)

    def _on_ready(self) -> None:
        self._webview_ready = True
        self._apply_theme()
        self._js(f"setLabels({json.dumps(self._labels())})")
        for code in self._pending:
            self._web.page().runJavaScript(code)
        self._pending.clear()
        self._hydrate()

    def _labels(self) -> dict:
        pynia = getattr(S, "pynia", None)
        return {
            "pick_agent": getattr(pynia, "pick_agent", "Choose an agent to start this tab's chat."),
            "open_settings": getattr(pynia, "open_settings", "Settings"),
            "thinking": getattr(pynia, "thinking", "Thinking"),
            "permission_title": getattr(pynia, "permission_title", "Allow this action?"),
            "session_recreated": getattr(pynia, "session_recreated", "Agent session was recreated. History is visible but the agent may not remember it."),
        }

    def _apply_theme(self) -> None:
        colors = get_colors()
        payload = {
            "bg_primary": colors.bg_primary,
            "bg_secondary": colors.bg_secondary,
            "bg_tertiary": colors.bg_tertiary,
            "bg_elevated": colors.bg_elevated,
            "text_primary": colors.text_primary,
            "text_secondary": colors.text_secondary,
            "text_tertiary": colors.text_tertiary,
            "border_default": colors.border_default,
            "accent": colors.interactive_primary,
            "danger": colors.danger,
        }
        self._js(f"setTheme({json.dumps(payload)})")

    def _hydrate(self) -> None:
        if not self._webview_ready:
            return
        self._refresh_header()
        state = self.host.state(self._tab_id) if self.host and self._tab_id else None
        messages = state.messages if state else []
        if state and state.agent_id:
            self._js("hidePicker()")
        else:
            self._refresh_picker()
        self._js(f"setMessages({json.dumps(messages)})")
        if state and state.agent_id:
            self._js("hidePicker()")
        if state:
            self._js(f"setBusy({json.dumps(state.busy)})")

    def _refresh_header(self) -> None:
        state = self.host.state(self._tab_id) if self.host and self._tab_id else None
        agent_id = state.agent_id if state else ""
        spec = None
        icon = ""
        if agent_id:
            from src.services.pynia.acp.catalog import get_agent

            spec = get_agent(agent_id)
            if spec:
                icon = icon_data_uri(spec)
        title = spec.label if spec else "Pynia"
        payload = {
            "title": title,
            "subtitle": self._tab_name,
            "icon": icon,
            "recreated": bool(state and state.acp_session_recreated),
            "recreated_note": self._labels()["session_recreated"],
        }
        self._js(f"setHeader({json.dumps(payload)})")

    def _refresh_picker(self) -> None:
        agents = []
        for spec in list_agents():
            status = probe_status(spec)
            agents.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "ready": status == "ready",
                    "status_label": status.replace("_", " "),
                    "icon": icon_data_uri(spec),
                }
            )
        self._js(f"setPicker({json.dumps(agents)})")

    def _on_send(self, text: str) -> None:
        if not self.host or not self._tab_id:
            return
        try:
            self.host.send_prompt(self._tab_id, text)
        except Exception as exc:
            self._js(f"appendChunk({json.dumps(str(exc))})")

    def _on_cancel(self) -> None:
        if self.host and self._tab_id:
            self.host.cancel(self._tab_id)

    def _on_select_agent(self, agent_id: str) -> None:
        if not self.host:
            self._js(f"showNotice({json.dumps('Pynia is not ready yet.')})")
            return
        if not self._tab_id:
            self._js(
                f"showNotice({json.dumps('Open a script tab before choosing an agent.')})"
            )
            return
        try:
            self.host.set_agent(self._tab_id, agent_id)
            get_pynia_settings().set_default_agent_id(agent_id)
            self._refresh_header()
            self._js("hidePicker()")
        except Exception as exc:
            logger.warning("Could not select agent: %s", exc, exc_info=True)
            self._js(f"showNotice({json.dumps(str(exc))})")

    def _on_messages_changed(self, tab_id: str) -> None:
        if tab_id != self._tab_id:
            return
        state = self.host.state(tab_id)
        self._js(f"setMessages({json.dumps(state.messages)})")

    def _on_chunk(self, tab_id: str, text: str) -> None:
        if tab_id != self._tab_id:
            return
        self._js(f"appendChunk({json.dumps(text)})")

    def _on_thinking(self, tab_id: str, text: str) -> None:
        if tab_id != self._tab_id:
            return
        self.thinking_started.emit()
        self._js(f"setThinking({json.dumps(text)})")

    def _on_tool(self, tab_id: str, payload: dict) -> None:
        if tab_id != self._tab_id:
            return
        title = payload.get("title") or payload.get("kind") or payload.get("sessionUpdate") or "tool"
        self._js(f"addTool({json.dumps({'title': str(title)})})")

    def _on_permission(self, tab_id: str, rpc_id: object, params: dict) -> None:
        if tab_id != self._tab_id:
            return
        text = str((params or {}).get("toolCall") or params or "Allow this action?")
        self._js(f"showPermission({json.dumps({'id': str(rpc_id), 'text': text})})")

    def _on_permission_answer(self, rpc_id: str, option_id: str) -> None:
        if self.host:
            self.host.answer_permission(rpc_id, option_id)

    def _on_busy(self, tab_id: str, busy: bool) -> None:
        if tab_id != self._tab_id:
            return
        self._js(f"setBusy({json.dumps(busy)})")

    def _on_error(self, tab_id: str, message: str) -> None:
        if tab_id != self._tab_id:
            return
        self._js(f"appendChunk({json.dumps(message)})")
