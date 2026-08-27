"""Workspace-scoped Pynia settings (ACP agents + autocomplete)."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QSettings

from src.services.pynia.acp.catalog import AGENT_IDS

logger = logging.getLogger(__name__)


class PyniaSettingsManager:
    """Persist default agent and autocomplete for the current workspace."""

    _instance: Optional["PyniaSettingsManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cached_workspace = None
            cls._instance._cached_settings = None
        return cls._instance

    @property
    def _settings(self) -> QSettings:
        from src.core.workspace_service import get_workspace_service, qsettings_alive

        ws = get_workspace_service()
        current_workspace = str(ws.current_workspace)
        if (
            self._cached_workspace != current_workspace
            or not qsettings_alive(self._cached_settings)
        ):
            self._cached_settings = ws.get_workspace_settings("PyniaSettings")
            self._cached_workspace = current_workspace
        return self._cached_settings

    @property
    def default_agent_id(self) -> str:
        raw = self._settings.value("default_agent_id", "") or ""
        if raw in AGENT_IDS:
            return raw
        return ""

    def set_default_agent_id(self, agent_id: str) -> None:
        if agent_id and agent_id not in AGENT_IDS:
            return
        self._settings.setValue("default_agent_id", agent_id or "")

    @property
    def autocomplete_enabled(self) -> bool:
        val = self._settings.value("autocomplete_enabled", False)
        return val in (True, "true", "True", 1, "1")

    def set_autocomplete_enabled(self, enabled: bool) -> None:
        self._settings.setValue("autocomplete_enabled", "true" if enabled else "false")

    @property
    def model_id(self) -> str:
        return str(self._settings.value("model_id", "") or "")

    def set_model_id(self, model_id: str) -> None:
        self._settings.setValue("model_id", model_id or "")

    @property
    def thought_level(self) -> str:
        return str(self._settings.value("thought_level", "auto") or "auto")

    def set_thought_level(self, level: str) -> None:
        self._settings.setValue("thought_level", level or "auto")

    def _agent_pref_key(self, agent_id: str, field: str) -> str:
        return f"agent_prefs/{agent_id}/{field}"

    def _migrate_global_pref(self, agent_id: str, field: str, legacy: str) -> str:
        if not legacy:
            return ""
        key = self._agent_pref_key(agent_id, field)
        self._settings.setValue(key, legacy)
        return legacy

    def agent_model_id(self, agent_id: str) -> str:
        if agent_id not in AGENT_IDS:
            return ""
        raw = str(self._settings.value(self._agent_pref_key(agent_id, "model_id"), "") or "")
        if raw:
            return raw
        if agent_id == self.default_agent_id:
            return self._migrate_global_pref(agent_id, "model_id", self.model_id)
        return ""

    def set_agent_model_id(self, agent_id: str, model_id: str) -> None:
        if agent_id not in AGENT_IDS:
            return
        self._settings.setValue(self._agent_pref_key(agent_id, "model_id"), model_id or "")

    def agent_thought_level(self, agent_id: str) -> str:
        if agent_id not in AGENT_IDS:
            return ""
        raw = str(self._settings.value(self._agent_pref_key(agent_id, "thought_level"), "") or "")
        if raw:
            return raw
        if agent_id == self.default_agent_id:
            legacy = self.thought_level
            if legacy and legacy != "auto":
                return self._migrate_global_pref(agent_id, "thought_level", legacy)
        return ""

    def set_agent_thought_level(self, agent_id: str, level: str) -> None:
        if agent_id not in AGENT_IDS:
            return
        self._settings.setValue(self._agent_pref_key(agent_id, "thought_level"), level or "")


def get_pynia_settings() -> PyniaSettingsManager:
    return PyniaSettingsManager()


def reset_pynia_settings() -> None:
    PyniaSettingsManager._instance = None
