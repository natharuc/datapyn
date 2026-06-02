"""Delegates chat agent operations to the existing GitHub Copilot SDK client."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import CopilotClient

logger = logging.getLogger(__name__)


class CopilotProviderAdapter(QObject):
    """Thin wrapper so Pynia can treat Copilot as one connector among many."""

    def __init__(self, client: "CopilotClient", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._client = client

    @property
    def client(self) -> "CopilotClient":
        return self._client

    @property
    def is_authenticated(self) -> bool:
        return bool(self._client and self._client.is_authenticated)

    def connect_signals(self, target: QObject) -> None:
        """Forward CopilotClient signals to PyniaAgentClient."""
        c = self._client
        c.auth_required.connect(target.auth_required.emit)
        c.authenticated.connect(target.authenticated.emit)
        c.auth_failed.connect(target.auth_failed.emit)
        c.auth_started.connect(target.auth_started.emit)
        c.chat_response_chunk.connect(target.chat_response_chunk.emit)
        c.chat_response_complete.connect(target.chat_response_complete.emit)
        c.chat_error.connect(target.chat_error.emit)
        c.tool_called.connect(target.tool_called.emit)
        c.tool_result.connect(target.tool_result.emit)
        c.thinking.connect(target.thinking.emit)
        c.models_changed.connect(target.models_changed.emit)
        c.usage_changed.connect(target.usage_changed.emit)
        if hasattr(c, "gh_not_found"):
            c.gh_not_found.connect(target.gh_not_found.emit)
        if hasattr(c, "license_warning"):
            c.license_warning.connect(target.license_warning.emit)

    def disconnect_signals(self, target: QObject) -> None:
        c = self._client
        for sig, slot in (
            (c.auth_required, target.auth_required.emit),
            (c.authenticated, target.authenticated.emit),
            (c.auth_failed, target.auth_failed.emit),
            (c.auth_started, target.auth_started.emit),
            (c.chat_response_chunk, target.chat_response_chunk.emit),
            (c.chat_response_complete, target.chat_response_complete.emit),
            (c.chat_error, target.chat_error.emit),
            (c.tool_called, target.tool_called.emit),
            (c.tool_result, target.tool_result.emit),
            (c.thinking, target.thinking.emit),
            (c.models_changed, target.models_changed.emit),
            (c.usage_changed, target.usage_changed.emit),
        ):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def start_auth(self) -> None:
        if hasattr(self._client, "do_login"):
            self._client.do_login()
        else:
            self._client.start_auth()

    def cancel_pending_auth(self) -> None:
        if hasattr(self._client, "cancel_pending_auth"):
            self._client.cancel_pending_auth()

    def send_chat(
        self,
        messages: List[Dict[str, str]],
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._client.send_chat(messages, attachments=attachments)

    def cancel(self) -> None:
        self._client.cancel()

    def reset_chat_session(self) -> None:
        if hasattr(self._client, "reset_chat_session"):
            self._client.reset_chat_session()

    def refresh_metadata(self) -> None:
        if hasattr(self._client, "refresh_metadata"):
            self._client.refresh_metadata()
        else:
            self.start_auth()

    def set_tool_registry(self, registry, parent=None) -> None:
        self._client.set_tool_registry(registry, parent=parent)

    @property
    def model(self) -> str:
        return self._client.model

    @model.setter
    def model(self, value: str) -> None:
        self._client.model = value

    @property
    def reasoning_effort(self) -> str:
        return self._client.reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, value: str) -> None:
        self._client.reasoning_effort = value

    @property
    def system_message(self) -> str:
        return self._client.system_message

    @system_message.setter
    def system_message(self, value: str) -> None:
        self._client.system_message = value

    def available_models(self) -> List[Dict[str, Any]]:
        return self._client.available_models()

    def usage_snapshot(self) -> Dict[str, Any]:
        return self._client.usage_snapshot()

    def request_inline_completion(self, *args, **kwargs) -> None:
        self._client.request_inline_completion(*args, **kwargs)
