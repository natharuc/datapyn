"""
CopilotMixin - LSP client setup, authentication, Copilot status, output wiring.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread

from src.language import S

logger = logging.getLogger(__name__)


class CopilotMixin:
    """Handles Copilot LSP setup, authentication, status display, output wiring."""

    def _setup_lsp_client(self):
        """Setup the Copilot LSP client for fast inline completions."""
        from src.services.copilot import CopilotLSPClient, get_copilot_server_path

        server_path = get_copilot_server_path()
        if not server_path:
            logging.info("[MAIN] LSP server not available")
            return False

        logging.info(f"[MAIN] Setting up LSP client with server: {server_path}")

        self._lsp_client = CopilotLSPClient(str(server_path), self)
        self._lsp_client.authenticated.connect(self._on_lsp_authenticated)
        self._lsp_client.log_message.connect(self._on_completion_log)

        self._start_lsp_process_async(str(server_path))
        return True

    def _start_lsp_process_async(self, server_path: str):
        from src.workers import LSPProcessWorker

        thread = QThread(self)
        worker = LSPProcessWorker(server_path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.process_ready.connect(
            lambda process: self._on_lsp_process_ready(process, thread)
        )
        worker.error.connect(self._on_lsp_process_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        thread.start()

    def _on_lsp_process_ready(self, process, thread):
        if not getattr(self, "_lsp_client", None):
            return
        if self._lsp_client.attach_process(process):
            self._lsp_client.initialize()
            logging.info("[MAIN] LSP client started and initializing")
            if hasattr(self, "_copilot_auth_service") and self._copilot_auth_service:
                self._copilot_auth_service.set_lsp_client(self._lsp_client)
            self._update_editors_lsp_client()
        else:
            logging.warning("[MAIN] Failed to attach LSP process")
            self._lsp_client = None

    def _on_lsp_process_error(self, message: str):
        logging.warning("[MAIN] Failed to start LSP client: %s", message)
        self._lsp_client = None

    def _setup_copilot_auth_service(self):
        """Initialize Pynia chat auth and Copilot LSP auth services."""
        from src.services.copilot import get_copilot_auth_service
        from src.services.pynia import get_pynia_auth_service
        import logging
        
        self._copilot_auth_service = get_copilot_auth_service()
        self._pynia_auth_service = get_pynia_auth_service()
        
        # Chat agent: Pynia multi-provider client
        if hasattr(self, "_pynia_agent") and self._pynia_agent:
            self._pynia_auth_service.set_agent_client(self._pynia_agent)
        elif hasattr(self, "_copilot_client") and self._copilot_client:
            self._copilot_auth_service.set_chat_client(self._copilot_client)
        
        if hasattr(self, "_lsp_client") and self._lsp_client:
            self._copilot_auth_service.set_lsp_client(self._lsp_client)
        
        # Connect auth service signals for UI updates
        auth_chat = self._pynia_auth_service if getattr(self, "_pynia_auth_service", None) else self._copilot_auth_service
        auth_chat.chat_authenticated.connect(self._on_auth_service_chat_authenticated)
        self._copilot_auth_service.lsp_authenticated.connect(self._on_auth_service_lsp_authenticated)
        auth_chat.chat_auth_required.connect(self._on_lsp_auth_required)
        self._copilot_auth_service.lsp_auth_required.connect(self._on_lsp_auth_required)
        
        # Chat panel starts auto-auth when the WebView is ready (shows signing-in state)
        
        logging.info("[MAIN] Copilot auth service initialized")

    def _on_auth_service_chat_authenticated(self, username: str):
        """Handle Chat authentication via auth service."""
        import logging
        logging.info(f"[MAIN] Chat authenticated via auth service: {username}")
        # Update chat panel if needed
        if hasattr(self, "_copilot_chat_panel"):
            self._copilot_chat_panel._on_authenticated(username)

    def _on_auth_service_lsp_authenticated(self, username: str):
        """Handle LSP authentication via auth service."""
        import logging
        logging.info(f"[MAIN] LSP authenticated via auth service: {username}")
        self._update_editors_lsp_client()

    def _on_lsp_auth_required(self, user_code: str, verification_uri: str):
        """Handle LSP authentication request."""
        import logging
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        
        logging.info(f"[LSP Auth] Device code: {user_code} - Verify at: {verification_uri}")
        
        # Copy code to clipboard
        QApplication.clipboard().setText(user_code)
        
        # Open browser
        QDesktopServices.openUrl(QUrl(verification_uri))
        
        # Log to output panel
        if hasattr(self, "_output_panel") and self._output_panel:
            self._output_panel.append_styled_text(
                f"\n[Copilot LSP] Authentication required!\n"
                f"Code: {user_code} (copied to clipboard)\n"
                f"Open: {verification_uri}\n",
                "yellow"
            )
        
        # Show in Copilot panel if visible
        if hasattr(self, "_copilot_chat_panel"):
            self._copilot_chat_panel._on_auth_required(user_code, verification_uri)

    def _on_lsp_authenticated(self, username: str):
        """Handle LSP authentication success."""
        import logging
        logging.info(f"[MAIN] LSP authenticated: {username}")
        # Update all editors with LSP client
        self._update_editors_lsp_client()

    def _update_editors_lsp_client(self):
        """Deprecated: use _update_editors_pynia_client."""
        self._update_editors_pynia_client()

    def _update_editors_pynia_client(self):
        """Attach Pynia agent to all session editors for inline autocomplete."""
        client = getattr(self, "_pynia_agent", None)
        if not client:
            return
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if hasattr(widget, "editor") and hasattr(widget.editor, "set_pynia_client"):
                widget.editor.set_pynia_client(client)

    def _on_settings_chat_login(self):
        """Handle Chat login request from settings dialog.
        
        Note: SettingsDialog now calls CopilotAuthService.login_chat() directly.
        This handler is kept for signal compatibility but does nothing.
        """
        logging.info("[Settings] Chat login signal received (handled by auth service)")

    def _on_settings_chat_logout(self):
        """Handle Chat logout request from settings dialog.
        
        Note: SettingsDialog now calls CopilotAuthService.logout_chat() directly.
        This handler is kept for signal compatibility but does nothing.
        """
        logging.info("[Settings] Chat logout signal received (handled by auth service)")

    def _on_settings_lsp_login(self):
        """Handle LSP/Autocomplete login request from settings dialog.
        
        Note: SettingsDialog now calls CopilotAuthService.login_lsp() directly.
        This handler is kept for signal compatibility but does nothing.
        """
        logging.info("[Settings] LSP login signal received (handled by auth service)")

    def _on_settings_lsp_logout(self):
        """Handle LSP/Autocomplete logout request from settings dialog.
        
        Note: SettingsDialog now calls CopilotAuthService.logout_lsp() directly.
        This handler is kept for signal compatibility but does nothing.
        """
        logging.info("[Settings] LSP logout signal received (handled by auth service)")

    def _show_copilot_download_dialog(self):
        """Show dialog to download the Copilot LSP server."""
        from src.ui.dialogs import CopilotDownloadDialog
        
        dialog = CopilotDownloadDialog(self)
        if dialog.exec() and dialog.was_successful():
            # Server downloaded - set it up
            self._setup_lsp_client()
            self._update_editors_lsp_client()

    def _show_copilot_status(self):
        """Show Copilot status dialog with LSP and SDK info."""
        from PyQt6.QtWidgets import QMessageBox
        from src.services.copilot import is_copilot_server_available, get_copilot_server_path
        
        # LSP status
        lsp_available = is_copilot_server_available()
        lsp_path = get_copilot_server_path() if lsp_available else "Not installed"
        lsp_client_running = hasattr(self, "_lsp_client") and self._lsp_client is not None
        lsp_authenticated = lsp_client_running and self._lsp_client.is_authenticated
        
        # SDK status
        sdk_available = hasattr(self, "_copilot_client") and self._copilot_client is not None
        sdk_authenticated = sdk_available and self._copilot_client.is_authenticated
        sdk_username = ""
        if sdk_authenticated:
            sdk_username = getattr(self._copilot_client, "_username", "unknown")
        
        # Build status message
        lines = []
        lines.append("=== Copilot Language Server (LSP) ===")
        lines.append(f"Installed: {'Yes' if lsp_available else 'No'}")
        if lsp_available:
            lines.append(f"Path: {lsp_path}")
        lines.append(f"Running: {'Yes' if lsp_client_running else 'No'}")
        lines.append(f"Authenticated: {'Yes' if lsp_authenticated else 'No'}")
        lines.append("")
        lines.append("=== Copilot Chat API (SDK) ===")
        lines.append(f"Loaded: {'Yes' if sdk_available else 'No'}")
        lines.append(f"Authenticated: {'Yes' if sdk_authenticated else 'No'}")
        if sdk_username:
            lines.append(f"User: {sdk_username}")
        lines.append("")
        lines.append("=== Autocomplete Status ===")
        if lsp_authenticated:
            lines.append("Using: LSP (fast, <500ms)")
        elif sdk_authenticated:
            lines.append("Using: Chat API (slower, 2-3s)")
        elif not lsp_available:
            lines.append("Status: LSP not installed")
            lines.append("Action: Use Tools > Copilot > Download Language Server")
        elif not lsp_client_running:
            lines.append("Status: LSP not running")
        else:
            lines.append("Status: Not authenticated")
            lines.append("Action: Open Copilot Chat panel and authenticate")
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Copilot Status")
        msg.setText("\n".join(lines))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def _connect_copilot_to_output(self):
        """Connect Pynia agent signals to output panel."""
        client = getattr(self, "_pynia_agent", None) or getattr(self, "_copilot_client", None)
        if not client:
            return
        if not hasattr(self, "_copilot_output_panel") or not self._copilot_output_panel:
            return
        output = self._copilot_output_panel

        # Auth signals
        client.authenticated.connect(
            lambda user: output.log_auth_status(f"Authenticated as {user}", success=True)
        )
        client.auth_failed.connect(
            lambda err: output.log_auth_status(f"Auth failed: {err}", success=False)
        )
        client.auth_required.connect(
            lambda code, uri: output.log_auth_status(f"Auth required: {code}", success=False)
        )
        if hasattr(client, "auth_started"):
            client.auth_started.connect(
                lambda msg: output.log_auth_status(msg, success=True)
            )

        # Chat signals
        client.chat_response_chunk.connect(lambda _: None)  # Ignore chunks in output
        client.chat_response_complete.connect(lambda _: output.log_response_complete())
        client.chat_error.connect(lambda err: output.log_error(err))

        # Tool call signal (name, args, tool_call_id)
        if hasattr(client, "tool_called"):
            client.tool_called.connect(
                lambda name, args, _id="": output.log_tool_call(name, args)
            )

        # Tool result signal
        if hasattr(client, "tool_result"):
            client.tool_result.connect(
                lambda name, result: output.log_tool_result(name, result)
            )

        # Thinking signal
        if hasattr(client, "thinking"):
            client.thinking.connect(lambda _: None)  # Just ignore for now

        # Connect chat panel thinking signal
        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            self._copilot_chat_panel.thinking_started.connect(output.log_thinking)

    def _on_insert_code_from_chat(self, code: str):
        """Insert code from Copilot chat into the active editor's focused block."""
        widget = self._get_current_session_widget()
        if not widget or not hasattr(widget, "editor"):
            return

        editor = widget.editor
        block = editor.get_last_focused_block()
        if not block:
            # No focused block -- insert into a new block
            editor.add_block()
            block = editor.get_last_focused_block()
            if not block:
                return

        # Use the block's inner editor to insert at cursor
        inner = getattr(block, "editor", None)
        if inner and hasattr(inner, "insert_text_at_cursor"):
            inner.insert_text_at_cursor(code)
        elif inner and hasattr(inner, "set_text"):
            # Append to existing content
            existing = inner.get_text() if hasattr(inner, "get_text") else ""
            inner.set_text(existing + code)
        elif hasattr(block, "set_code"):
            existing = block.get_code() if hasattr(block, "get_code") else ""
            block.set_code(existing + code)
