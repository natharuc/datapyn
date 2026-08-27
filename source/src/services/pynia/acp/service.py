"""Single ACP session service used by every agent (Claude, Copilot, Codex, Cursor)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .client import AcpClient
from .protocol import (
    client_version,
    initialize_params,
    session_new_params,
    session_prompt_params,
    set_config_option_params,
    set_model_params,
)
from .session_config import NormalizedConfig, merge_config_snapshot, normalize_config

logger = logging.getLogger(__name__)


def _auth_method_listed(client: AcpClient, method_id: str) -> bool:
    wanted = (method_id or "").strip()
    if not wanted:
        return False
    for item in client.auth_methods or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or item.get("methodId") or "") == wanted:
            return True
    return False


class AcpSessionService:
    """Handshake, session/new, config, and prompt — one path for all agents."""

    def handshake(
        self,
        client: AcpClient,
        *,
        auth_method_id: Optional[str] = None,
        version: str = "",
    ) -> dict[str, Any]:
        if getattr(client, "_handshook", False) and client.is_running:
            return {
                "protocolVersion": 1,
                "agentCapabilities": client.agent_capabilities,
                "authMethods": client.auth_methods,
            }
        result = client.request(
            "initialize",
            initialize_params(version or client_version()),
            timeout=30.0,
        )
        if not isinstance(result, dict):
            result = {}
        client.agent_capabilities = result.get("agentCapabilities") or {}
        client.auth_methods = result.get("authMethods") or []
        client.initialized.emit(result)
        method = (auth_method_id or "").strip()
        if method and _auth_method_listed(client, method):
            try:
                client.authenticate(method)
            except Exception as exc:
                logger.info("ACP authenticate for %s skipped/failed: %s", client.agent_id, exc)
        client._handshook = True
        return result

    def connect(
        self,
        client: AcpClient,
        cwd: str,
        mcp_servers: Optional[list[dict]] = None,
        *,
        auth_method_id: Optional[str] = None,
        version: str = "",
    ) -> tuple[str, NormalizedConfig]:
        """Initialize (and auth if needed), then open a session and return config."""
        self.handshake(client, auth_method_id=auth_method_id, version=version)
        return self.open_session(client, cwd, mcp_servers)

    def open_session(
        self,
        client: AcpClient,
        cwd: str,
        mcp_servers: Optional[list[dict]] = None,
        previous: Optional[dict[str, Any]] = None,
    ) -> tuple[str, NormalizedConfig]:
        result = client.request(
            "session/new",
            session_new_params(cwd, mcp_servers),
            timeout=30.0,
        )
        snapshot = merge_config_snapshot(
            previous or client.last_session_info,
            result if isinstance(result, dict) else {},
        )
        client.last_session_info = snapshot
        session_id = str(snapshot.get("sessionId") or snapshot.get("session_id") or "")
        if not session_id:
            raise RuntimeError("session/new did not return sessionId")
        return session_id, normalize_config(snapshot)

    def set_option(
        self,
        client: AcpClient,
        session_id: str,
        config_id: str,
        value: str,
        previous: Optional[dict[str, Any]] = None,
        *,
        kind: str = "model",
    ) -> NormalizedConfig:
        result: dict[str, Any] = {}
        try:
            raw = client.request(
                "session/set_config_option",
                set_config_option_params(session_id, config_id, value),
                timeout=15.0,
            )
            result = raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.debug("ACP set_config_option failed: %s", exc)
            if kind != "model":
                return normalize_config(previous or client.last_session_info)
            try:
                raw = client.request(
                    "session/set_model",
                    set_model_params(session_id, value),
                    timeout=15.0,
                )
                result = raw if isinstance(raw, dict) else {}
            except Exception as exc2:
                logger.debug("ACP set_model failed: %s", exc2)
                return normalize_config(previous or client.last_session_info)
        snapshot = merge_config_snapshot(previous or client.last_session_info, result)
        client.last_session_info = snapshot
        return normalize_config(snapshot)

    def prompt(
        self,
        client: AcpClient,
        session_id: str,
        blocks: list[dict[str, Any]] | str,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        prompt = blocks if isinstance(blocks, list) else [{"type": "text", "text": str(blocks)}]
        result = client.request(
            "session/prompt",
            session_prompt_params(session_id, prompt),
            timeout=timeout,
        )
        return result if isinstance(result, dict) else {}

    def cancel(self, client: AcpClient, session_id: str) -> None:
        client.notify("session/cancel", {"sessionId": session_id})


def get_acp_service() -> AcpSessionService:
    return AcpSessionService()
