"""
Centralized settings manager for Copilot authentication state.

Tracks:
- Whether user has ever authenticated (Chat / LSP)
- Whether user explicitly logged out
- Auto-connect preferences

Logic:
- Auto-auth happens ONLY if: was_authenticated=True AND user_logged_out=False
- On successful login: was_authenticated=True, user_logged_out=False
- On logout: user_logged_out=True (was_authenticated remains True)
- Never authenticated: both False
"""

from PyQt6.QtCore import QSettings
import logging
import json

logger = logging.getLogger(__name__)


class CopilotSettingsManager:
    """Centralized manager for Copilot authentication settings.
    
    Uses workspace-scoped settings so each workspace has its own
    authentication state and preferences.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._auth_in_progress = False  # Flag to prevent concurrent auth flows (in-memory)
            cls._instance._cached_workspace = None  # Track which workspace settings are cached for
            cls._instance._cached_settings = None
        return cls._instance
    
    @property
    def _settings(self):
        """Get workspace-scoped settings, refreshing cache if workspace changed."""
        from src.core.workspace_service import get_workspace_service
        ws = get_workspace_service()
        current_workspace = str(ws.current_workspace)
        
        # Refresh cache if workspace changed
        if self._cached_workspace != current_workspace:
            self._cached_settings = ws.get_workspace_settings("CopilotSettings")
            self._cached_workspace = current_workspace
            logger.info(f"CopilotSettings reloaded for workspace: {current_workspace}")
        
        return self._cached_settings
    
    # ========================
    # AUTH FLOW CONTROL
    # ========================
    
    def start_auth_flow(self) -> bool:
        """
        Try to start an auth flow. Returns True if OK to proceed.
        Returns False if another auth is already in progress.
        """
        if self._auth_in_progress:
            logger.info("Auth flow blocked - another auth already in progress")
            return False
        self._auth_in_progress = True
        logger.info("Auth flow started")
        return True
    
    def end_auth_flow(self):
        """Call when auth flow completes (success or failure)."""
        self._auth_in_progress = False
        logger.info("Auth flow ended")
    
    @property
    def auth_in_progress(self) -> bool:
        """Check if an auth flow is currently in progress."""
        return self._auth_in_progress
    
    # ========================
    # CHAT SETTINGS
    # ========================
    
    @property
    def chat_was_authenticated(self) -> bool:
        """Check if user has ever authenticated with Chat."""
        val = self._settings.value("chat/was_authenticated", False)
        return val in (True, "true", "True", 1, "1")
    
    @property
    def chat_user_logged_out(self) -> bool:
        """Check if user explicitly logged out of Chat."""
        val = self._settings.value("chat/user_logged_out", False)
        return val in (True, "true", "True", 1, "1")
    
    @property
    def chat_username(self) -> str:
        """Get the last authenticated Chat username."""
        return self._settings.value("chat/username", "") or ""
    
    def should_auto_auth_chat(self) -> bool:
        """
        Determine if Chat should auto-authenticate on startup.
        
        Returns True only if:
        - User has authenticated before AND
        - User did NOT explicitly log out
        """
        return self.chat_was_authenticated and not self.chat_user_logged_out
    
    def on_chat_authenticated(self, username: str = ""):
        """Call when Chat authentication succeeds."""
        self._settings.setValue("chat/was_authenticated", "true")
        self._settings.setValue("chat/user_logged_out", "false")
        self._settings.setValue("chat/username", username)
        logger.info(f"Chat auth state saved: authenticated as {username}")
    
    def on_chat_logged_out(self):
        """Call when user explicitly logs out of Chat."""
        self._settings.setValue("chat/user_logged_out", "true")
        logger.info("Chat auth state: user logged out")
    
    def reset_chat_auth(self):
        """Reset Chat auth state (for testing)."""
        self._settings.remove("chat/was_authenticated")
        self._settings.remove("chat/user_logged_out")
        self._settings.remove("chat/username")

    @property
    def chat_selected_model(self) -> str:
        """Get the preferred chat model for this workspace."""
        return self._settings.value("chat/selected_model", "gpt-4o") or "gpt-4o"

    def set_chat_selected_model(self, model_id: str):
        """Persist the preferred chat model for this workspace."""
        self._settings.setValue("chat/selected_model", str(model_id or "gpt-4o"))

    @property
    def chat_reasoning_effort(self) -> str:
        """Get the preferred reasoning effort for this workspace."""
        try:
            from src.services.copilot.copilot_models import normalize_reasoning_effort
            return normalize_reasoning_effort(self._settings.value("chat/reasoning_effort", "auto"))
        except Exception:
            value = str(self._settings.value("chat/reasoning_effort", "auto") or "auto").lower()
            return value if value in ("auto", "low", "medium", "high", "xhigh") else "auto"

    def set_chat_reasoning_effort(self, effort: str):
        """Persist the preferred reasoning effort for this workspace."""
        try:
            from src.services.copilot.copilot_models import normalize_reasoning_effort
            effort = normalize_reasoning_effort(effort)
        except Exception:
            effort = "auto"
        self._settings.setValue("chat/reasoning_effort", effort)

    @property
    def chat_usage_snapshot(self) -> dict:
        """Get the last known usage snapshot."""
        raw = self._settings.value("chat/usage_snapshot", "{}") or "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def set_chat_usage_snapshot(self, snapshot: dict):
        """Persist the last known usage snapshot."""
        if not isinstance(snapshot, dict):
            snapshot = {}
        self._settings.setValue("chat/usage_snapshot", json.dumps(snapshot))
    
    # ========================
    # LSP / AUTOCOMPLETE SETTINGS
    # ========================
    
    @property
    def lsp_was_authenticated(self) -> bool:
        """Check if user has ever authenticated with LSP."""
        val = self._settings.value("lsp/was_authenticated", False)
        return val in (True, "true", "True", 1, "1")
    
    @property
    def lsp_user_logged_out(self) -> bool:
        """Check if user explicitly logged out of LSP."""
        val = self._settings.value("lsp/user_logged_out", False)
        return val in (True, "true", "True", 1, "1")
    
    @property
    def lsp_username(self) -> str:
        """Get the last authenticated LSP username."""
        return self._settings.value("lsp/username", "") or ""
    
    def should_auto_auth_lsp(self) -> bool:
        """
        Determine if LSP should auto-authenticate on startup.
        
        Returns True only if:
        - User has authenticated before AND
        - User did NOT explicitly log out
        """
        return self.lsp_was_authenticated and not self.lsp_user_logged_out
    
    def on_lsp_authenticated(self, username: str = ""):
        """Call when LSP authentication succeeds."""
        self._settings.setValue("lsp/was_authenticated", "true")
        self._settings.setValue("lsp/user_logged_out", "false")
        self._settings.setValue("lsp/username", username)
        logger.info(f"LSP auth state saved: authenticated as {username}")
    
    def on_lsp_logged_out(self):
        """Call when user explicitly logs out of LSP."""
        self._settings.setValue("lsp/user_logged_out", "true")
        logger.info("LSP auth state: user logged out")
    
    def reset_lsp_auth(self):
        """Reset LSP auth state (for testing)."""
        self._settings.remove("lsp/was_authenticated")
        self._settings.remove("lsp/user_logged_out")
        self._settings.remove("lsp/username")
    
    # ========================
    # STATUS HELPERS
    # ========================
    
    def get_chat_status_text(self) -> str:
        """Get human-readable Chat auth status."""
        if self.chat_user_logged_out:
            return "logged_out"
        if self.chat_was_authenticated:
            return "was_authenticated"
        return "never_authenticated"
    
    def get_lsp_status_text(self) -> str:
        """Get human-readable LSP auth status."""
        if self.lsp_user_logged_out:
            return "logged_out"
        if self.lsp_was_authenticated:
            return "was_authenticated"
        return "never_authenticated"


def get_copilot_settings() -> CopilotSettingsManager:
    """Get the singleton CopilotSettingsManager instance."""
    return CopilotSettingsManager()
