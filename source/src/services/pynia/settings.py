"""Workspace-scoped settings and secure credential storage for Pynia connectors."""

from __future__ import annotations

import logging
from typing import Optional

import keyring
from PyQt6.QtCore import QSettings

from .types import DEFAULT_PROVIDER, PROVIDERS, ProviderId

logger = logging.getLogger(__name__)

PYNIA_KEYRING_SERVICE = "DataPyn.pynia"
_FALLBACK_SETTINGS = QSettings("DataPyn", "PyniaSecrets")


def _secret_key(provider_id: ProviderId) -> str:
    return f"{provider_id}_api_token"


def _fallback_get(provider_id: ProviderId) -> str:
    return _FALLBACK_SETTINGS.value(_secret_key(provider_id), "") or ""


def _fallback_set(provider_id: ProviderId, value: str) -> None:
    key = _secret_key(provider_id)
    if value:
        _FALLBACK_SETTINGS.setValue(key, value)
    else:
        _FALLBACK_SETTINGS.remove(key)


def get_provider_secret(provider_id: ProviderId) -> str:
    try:
        stored = keyring.get_password(PYNIA_KEYRING_SERVICE, _secret_key(provider_id))
        if stored:
            return stored
    except Exception as exc:
        logger.warning("Failed to load Pynia secret for %s: %s", provider_id, exc)
    return _fallback_get(provider_id)


def set_provider_secret(provider_id: ProviderId, value: str) -> None:
    key = _secret_key(provider_id)
    try:
        if value:
            keyring.set_password(PYNIA_KEYRING_SERVICE, key, value)
            _fallback_set(provider_id, value)
            return
        try:
            keyring.delete_password(PYNIA_KEYRING_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass
        _fallback_set(provider_id, "")
        return
    except Exception as exc:
        logger.warning("Failed to persist Pynia secret for %s: %s", provider_id, exc)
    _fallback_set(provider_id, value)


class PyniaSettingsManager:
    """Persist active connector, models, and auth flags per workspace."""

    _instance: Optional["PyniaSettingsManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cached_workspace = None
            cls._instance._cached_settings = None
        return cls._instance

    @property
    def _settings(self) -> QSettings:
        from src.core.workspace_service import get_workspace_service

        ws = get_workspace_service()
        current_workspace = str(ws.current_workspace)
        if self._cached_workspace != current_workspace:
            self._cached_settings = ws.get_workspace_settings("PyniaSettings")
            self._cached_workspace = current_workspace
        return self._cached_settings

    @property
    def active_provider(self) -> ProviderId:
        raw = self._settings.value("active_provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER
        if raw in PROVIDERS:
            return raw  # type: ignore[return-value]
        return DEFAULT_PROVIDER

    def set_active_provider(self, provider_id: ProviderId) -> None:
        self._settings.setValue("active_provider", provider_id)

    def selected_model(self, provider_id: Optional[ProviderId] = None) -> str:
        """Last chat model chosen for a connector (persisted per provider)."""
        pid = provider_id or self.active_provider
        key = f"{pid}/selected_model"
        stored = self._settings.value(key, "") or ""
        if not stored and pid == "copilot":
            from src.services.copilot.copilot_settings import get_copilot_settings

            stored = get_copilot_settings().chat_selected_model
        if not stored:
            legacy = self._settings.value("selected_model", "") or ""
            if legacy and pid == self.active_provider:
                stored = legacy
                self._settings.setValue(key, legacy)
        if not stored:
            stored = PROVIDERS[pid].default_model
        return stored

    def set_selected_model(
        self,
        model_id: str,
        provider_id: Optional[ProviderId] = None,
    ) -> None:
        pid = provider_id or self.active_provider
        self._settings.setValue(f"{pid}/selected_model", model_id or "")
        if pid == "copilot":
            from src.services.copilot.copilot_settings import get_copilot_settings

            get_copilot_settings().set_chat_selected_model(model_id)

    @property
    def reasoning_effort(self) -> str:
        return self._settings.value("reasoning_effort", "auto") or "auto"

    def set_reasoning_effort(self, effort: str) -> None:
        self._settings.setValue("reasoning_effort", effort or "auto")

    def base_url(self, provider_id: Optional[ProviderId] = None) -> str:
        pid = provider_id or self.active_provider
        custom = self._settings.value(f"{pid}/base_url", "") or ""
        if custom:
            return custom.rstrip("/")
        return PROVIDERS[pid].default_base_url

    def set_base_url(self, provider_id: ProviderId, url: str) -> None:
        self._settings.setValue(f"{provider_id}/base_url", (url or "").rstrip("/"))

    def is_authenticated(self, provider_id: Optional[ProviderId] = None) -> bool:
        pid = provider_id or self.active_provider
        if pid == "copilot":
            val = self._settings.value("copilot/was_authenticated", False)
            logged_out = self._settings.value("copilot/user_logged_out", False)
            return val in (True, "true", "True", 1, "1") and logged_out not in (
                True,
                "true",
                "True",
                1,
                "1",
            )
        return bool(get_provider_secret(pid))

    def on_token_authenticated(self, provider_id: ProviderId, label: str = "") -> None:
        self._settings.setValue(f"{provider_id}/was_authenticated", "true")
        self._settings.setValue(f"{provider_id}/user_logged_out", "false")
        if label:
            self._settings.setValue(f"{provider_id}/username", label)

    def on_logout(self, provider_id: ProviderId) -> None:
        self._settings.setValue(f"{provider_id}/user_logged_out", "true")
        if provider_id != "copilot":
            set_provider_secret(provider_id, "")

    def should_auto_auth(self, provider_id: Optional[ProviderId] = None) -> bool:
        pid = provider_id or self.active_provider
        was = self._settings.value(f"{pid}/was_authenticated", False)
        logged_out = self._settings.value(f"{pid}/user_logged_out", False)
        return was in (True, "true", "True", 1, "1") and logged_out not in (
            True,
            "true",
            "True",
            1,
            "1",
        )

    def username(self, provider_id: Optional[ProviderId] = None) -> str:
        pid = provider_id or self.active_provider
        return self._settings.value(f"{pid}/username", "") or ""

    @property
    def autocomplete_enabled(self) -> bool:
        val = self._settings.value("autocomplete_enabled", True)
        return val in (True, "true", "True", 1, "1")

    def set_autocomplete_enabled(self, enabled: bool) -> None:
        self._settings.setValue("autocomplete_enabled", "true" if enabled else "false")

    def completion_model(self, provider_id: Optional[ProviderId] = None) -> str:
        pid = provider_id or self.active_provider
        custom = self._settings.value(f"{pid}/completion_model", "") or ""
        if custom:
            return custom
        from src.services.pynia.completion import COMPLETION_MODELS

        return COMPLETION_MODELS.get(pid, COMPLETION_MODELS["openai"])

    def set_completion_model(self, provider_id: ProviderId, model_id: str) -> None:
        self._settings.setValue(f"{provider_id}/completion_model", model_id or "")


def get_pynia_settings() -> PyniaSettingsManager:
    return PyniaSettingsManager()
