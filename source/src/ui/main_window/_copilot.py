"""
CopilotMixin — Pynia ACP output wiring and editor autocomplete attachment.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class CopilotMixin:
    """Wires Pynia ACP activity to the output panel and editors."""

    def _update_editors_pynia_client(self):
        """Attach Pynia ACP host to all session editors for inline autocomplete."""
        host = getattr(self, "_pynia_host", None)
        if not host:
            return
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if hasattr(widget, "editor") and hasattr(widget.editor, "set_pynia_client"):
                widget.editor.set_pynia_client(host)
                if hasattr(widget, "session") and hasattr(widget.editor, "set_pynia_tab_id"):
                    widget.editor.set_pynia_tab_id(widget.session.session_id)

    def _connect_copilot_to_output(self):
        """Connect Pynia ACP activity to the output panel."""
        host = getattr(self, "_pynia_host", None)
        if not host:
            return
        if not hasattr(self, "_copilot_output_panel") or not self._copilot_output_panel:
            return
        output = self._copilot_output_panel
        host.tool_event.connect(
            lambda _tab, payload: output.log_tool_call(
                str(payload.get("title") or payload.get("sessionUpdate") or "tool"),
                payload,
            )
        )
        host.turn_error.connect(lambda _tab, err: output.log_error(err))
        if getattr(host, "mcp", None):
            host.mcp.tool_executed.connect(
                lambda _tab, name, result: output.log_tool_result(name, result)
            )
        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            self._copilot_chat_panel.thinking_started.connect(output.log_thinking)

    def _on_insert_code_from_chat(self, code: str):
        """Insert code from Pynia chat into the active editor's focused block."""
        widget = self._get_current_session_widget()
        if not widget or not hasattr(widget, "editor"):
            return

        editor = widget.editor
        block = editor.get_last_focused_block()
        if not block:
            editor.add_block()
            block = editor.get_last_focused_block()
            if not block:
                return

        inner = getattr(block, "editor", None)
        if inner and hasattr(inner, "insert_text_at_cursor"):
            inner.insert_text_at_cursor(code)
        elif inner and hasattr(inner, "set_text"):
            existing = inner.get_text() if hasattr(inner, "get_text") else ""
            inner.set_text(existing + code)
        elif hasattr(block, "set_code"):
            existing = block.get_code() if hasattr(block, "get_code") else ""
            block.set_code(existing + code)
        logger.debug("[Autocomplete] %s", message)
        panel = getattr(self, "_copilot_output_panel", None)
        if panel is not None and hasattr(panel, "append_log"):
            try:
                panel.append_log(message, level)
            except Exception:
                pass
