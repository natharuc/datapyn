"""
Pynia authentication coordinator.

Routes login/logout to the active connector while keeping Copilot LSP auth
separate for inline completions.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from src.services.pynia.settings import get_pynia_settings
from src.services.pynia.types import ProviderId

if TYPE_CHECKING:
    from src.services.pynia.agent_client import PyniaAgentClient
    from src.services.copilot.copilot_lsp_client import CopilotLSPClient

logger = logging.getLogger(__name__)

_auth_service: Optional["PyniaAuthService"] = None


class PyniaAuthService(QObject):
    chat_authenticated = pyqtSignal(str)
    chat_auth_failed = pyqtSignal(str)
    chat_auth_required = pyqtSignal(str, str)
    chat_auth_started = pyqtSignal(str)
    chat_logged_out = pyqtSignal()
    chat_gh_not_found = pyqtSignal()

    lsp_authenticated = pyqtSignal(str)
    lsp_auth_failed = pyqtSignal(str)
    lsp_auth_required = pyqtSignal(str, str)
    lsp_logged_out = pyqtSignal()

    models_changed = pyqtSignal(list)
    provider_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._agent_client: Optional["PyniaAgentClient"] = None
        self._lsp_client: Optional["CopilotLSPClient"] = None
        self._settings = get_pynia_settings()
        self._auth_in_progress = False
        self._agent_connected = False
        self._lsp_connected = False

    def set_agent_client(self, client: "PyniaAgentClient") -> None:
        if self._agent_client and self._agent_connected:
            self._disconnect_agent_signals()
        self._agent_client = client
        self._connect_agent_signals()

    def set_lsp_client(self, client: "CopilotLSPClient") -> None:
        if self._lsp_client and self._lsp_connected:
            self._disconnect_lsp_signals()
        self._lsp_client = client
        self._connect_lsp_signals()

    def _connect_agent_signals(self) -> None:
        if not self._agent_client:
            return
        c = self._agent_client
        c.authenticated.connect(self._on_chat_authenticated)
        c.auth_failed.connect(self._on_chat_auth_failed)
        c.auth_required.connect(self.chat_auth_required.emit)
        c.auth_started.connect(self.chat_auth_started.emit)
        c.models_changed.connect(self.models_changed.emit)
        c.gh_not_found.connect(self.chat_gh_not_found.emit)
        c.provider_changed.connect(self.provider_changed.emit)
        self._agent_connected = True

    def _disconnect_agent_signals(self) -> None:
        if not self._agent_client:
            return
        c = self._agent_client
        try:
            c.authenticated.disconnect(self._on_chat_authenticated)
            c.auth_failed.disconnect(self._on_chat_auth_failed)
            c.auth_required.disconnect(self.chat_auth_required.emit)
            c.auth_started.disconnect(self.chat_auth_started.emit)
            c.models_changed.disconnect(self.models_changed.emit)
            c.gh_not_found.disconnect(self.chat_gh_not_found.emit)
            c.provider_changed.disconnect(self.provider_changed.emit)
        except (TypeError, RuntimeError):
            pass
        self._agent_connected = False

    def _connect_lsp_signals(self) -> None:
        if not self._lsp_client:
            return
        self._lsp_client.authenticated.connect(self.lsp_authenticated.emit)
        self._lsp_client.auth_required.connect(self.lsp_auth_required.emit)
        self._lsp_connected = True

    def _disconnect_lsp_signals(self) -> None:
        if not self._lsp_client:
            return
        try:
            self._lsp_client.authenticated.disconnect(self.lsp_authenticated.emit)
            self._lsp_client.auth_required.disconnect(self.lsp_auth_required.emit)
        except (TypeError, RuntimeError):
            pass
        self._lsp_connected = False

    def _on_chat_authenticated(self, username: str) -> None:
        self._auth_in_progress = False
        pid = self._agent_client.provider_id if self._agent_client else "copilot"
        if pid == "copilot":
            from src.services.copilot.copilot_settings import get_copilot_settings

            get_copilot_settings().on_chat_authenticated(username)
        else:
            self._settings.on_token_authenticated(pid, username)
        self.chat_authenticated.emit(username)

    def _on_chat_auth_failed(self, error: str) -> None:
        self._auth_in_progress = False
        self.chat_auth_failed.emit(error)

    def _copilot_backend(self):
        if not self._agent_client:
            return None
        return getattr(self._agent_client, "_copilot_backend", None)

    def login_chat(self) -> bool:
        if self._auth_in_progress or not self._agent_client:
            return False
        self._auth_in_progress = True
        client = self._agent_client
        try:
            if client.provider_id == "copilot":
                backend = self._copilot_backend()
                if backend is None:
                    self._auth_in_progress = False
                    self.chat_auth_failed.emit("Copilot connector not available.")
                    return False
                from src.services.copilot.copilot_client_sdk import _gh_executable, _is_gh_logged_in

                if _is_gh_logged_in(_gh_executable()):
                    logger.info("[PyniaAuth] GitHub CLI session found — verifying Copilot")
                    client.start_auth()
                elif hasattr(backend, "do_login"):
                    logger.info("[PyniaAuth] Starting GitHub login for Copilot")
                    backend.do_login()
                else:
                    client.start_auth()
            else:
                client.start_auth()
            return True
        except Exception as exc:
            logger.exception("[PyniaAuth] Failed to start chat login")
            self._auth_in_progress = False
            self.chat_auth_failed.emit(str(exc))
            return False

    def logout_chat(self) -> None:
        if not self._agent_client:
            return
        pid = self._agent_client.provider_id
        self._settings.on_logout(pid)
        if pid == "copilot":
            from src.services.copilot.copilot_settings import get_copilot_settings

            get_copilot_settings().on_chat_logout()
            backend = self._copilot_backend()
            if backend and hasattr(backend, "sign_out"):
                backend.sign_out()
        self._agent_client.cancel()
        self._auth_in_progress = False
        self.chat_logged_out.emit()

    def login_lsp(self) -> bool:
        if self._lsp_client:
            self._lsp_client.sign_in()
            return True
        return False

    @property
    def is_chat_authenticated(self) -> bool:
        return bool(self._agent_client and self._agent_client.is_authenticated)

    def cancel_chat_auth(self) -> None:
        if self._agent_client:
            self._agent_client.cancel_pending_auth()
        self._auth_in_progress = False

    def should_auto_auth(self, provider_id: Optional[ProviderId] = None) -> bool:
        pid = provider_id or (self._agent_client.provider_id if self._agent_client else "copilot")
        if pid == "copilot":
            from src.services.copilot.copilot_settings import get_copilot_settings

            return get_copilot_settings().should_auto_auth_chat()
        return self._settings.should_auto_auth(pid)

    def trigger_auto_auth(self, delay_ms: int = 500) -> bool:
        if not self.should_auto_auth():
            return False
        QTimer.singleShot(delay_ms, self._auto_auth_chat)
        return True

    def trigger_auto_auth_on_open(self, delay_ms: int = 400) -> bool:
        """Verify Copilot when gh is already logged in, even before first successful chat."""
        if not self._agent_client or self._agent_client.is_authenticated:
            return False
        if self._auth_in_progress:
            return False
        if self._agent_client.provider_id != "copilot":
            return self.trigger_auto_auth(delay_ms)
        from src.services.copilot.copilot_client_sdk import _gh_executable, _is_gh_logged_in

        if not _is_gh_logged_in(_gh_executable()):
            return self.trigger_auto_auth(delay_ms)
        QTimer.singleShot(delay_ms, self._auto_verify_copilot)
        return True

    def _auto_verify_copilot(self) -> None:
        if self._auth_in_progress or not self._agent_client or self._agent_client.is_authenticated:
            return
        self._auth_in_progress = True
        try:
            self._agent_client.start_auth()
        except Exception as exc:
            self._auth_in_progress = False
            self.chat_auth_failed.emit(str(exc))

    def _auto_auth_chat(self) -> None:
        if self._agent_client and not self._agent_client.is_authenticated:
            if not self.login_chat():
                self._auth_in_progress = False

    def prepare_chat_account_switch(self, username: str):
        """Copilot-only multi-account via gh CLI."""
        from src.services.copilot import get_copilot_auth_service

        return get_copilot_auth_service().prepare_chat_account_switch(username)


def get_pynia_auth_service() -> PyniaAuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = PyniaAuthService()
    return _auth_service


def reset_pynia_auth_service() -> None:
    global _auth_service
    _auth_service = None
