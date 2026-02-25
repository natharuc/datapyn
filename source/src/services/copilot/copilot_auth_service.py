"""
Centralized authentication service for Copilot (Chat and LSP/Autocomplete).

This service is the SINGLE entry point for all Copilot authentication.
It manages:
- Auth flow locking (prevents concurrent browser opens)
- Chat authentication (via CopilotClient SDK)
- LSP authentication (via CopilotLSPClient)
- Auto-auth on startup
- State persistence via CopilotSettingsManager

Usage:
    from src.services.copilot import get_copilot_auth_service
    
    auth = get_copilot_auth_service()
    auth.login_chat()  # Start chat login flow
    auth.login_lsp()   # Start LSP login flow
    
    # Connect to signals for UI updates
    auth.chat_authenticated.connect(on_chat_auth)
    auth.lsp_authenticated.connect(on_lsp_auth)
"""

from typing import Optional, TYPE_CHECKING
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import logging

if TYPE_CHECKING:
    from .copilot_client_sdk import CopilotClient
    from .copilot_lsp_client import CopilotLSPClient

logger = logging.getLogger(__name__)


class CopilotAuthService(QObject):
    """Centralized authentication service for Copilot Chat and LSP.
    
    Signals:
        chat_authenticated(username): Chat login successful
        chat_auth_failed(error): Chat login failed
        chat_auth_required(code, url): Chat needs device code flow
        chat_logged_out(): Chat logged out
        
        lsp_authenticated(username): LSP login successful
        lsp_auth_failed(error): LSP login failed
        lsp_auth_required(code, url): LSP needs device code flow
        lsp_logged_out(): LSP logged out
        
        models_changed(models): Available models updated
    """
    
    # Chat signals
    chat_authenticated = pyqtSignal(str)  # username
    chat_auth_failed = pyqtSignal(str)  # error message
    chat_auth_required = pyqtSignal(str, str)  # code, url
    chat_auth_started = pyqtSignal(str)  # message
    chat_gh_not_found = pyqtSignal()  # GitHub CLI not installed
    chat_logged_out = pyqtSignal()
    
    # LSP signals
    lsp_authenticated = pyqtSignal(str)  # username
    lsp_auth_failed = pyqtSignal(str)  # error message
    lsp_auth_required = pyqtSignal(str, str)  # code, url
    lsp_logged_out = pyqtSignal()
    
    # Model signals
    models_changed = pyqtSignal(list)  # list of model dicts
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        # Auth clients (set via set_clients())
        self._chat_client: Optional["CopilotClient"] = None
        self._lsp_client: Optional["CopilotLSPClient"] = None
        
        # Auth lock - prevents concurrent auth flows
        self._auth_in_progress = False
        self._auth_type: Optional[str] = None  # "chat" or "lsp"
        
        # Settings manager for persistence
        from .copilot_settings import get_copilot_settings
        self._settings = get_copilot_settings()
        
        # Track connection state
        self._chat_connected = False
        self._lsp_connected = False
        
        logger.info("[AuthService] Initialized")
    
    # ========================
    # CLIENT SETUP
    # ========================
    
    def set_chat_client(self, client: "CopilotClient") -> None:
        """Set the CopilotClient (SDK) for chat authentication.
        
        Args:
            client: CopilotClient instance from main_window
        """
        if self._chat_client and self._chat_connected:
            self._disconnect_chat_signals()
        
        self._chat_client = client
        self._connect_chat_signals()
        logger.info("[AuthService] Chat client set")
    
    def set_lsp_client(self, client: "CopilotLSPClient") -> None:
        """Set the CopilotLSPClient for LSP authentication.
        
        Args:
            client: CopilotLSPClient instance from main_window
        """
        if self._lsp_client and self._lsp_connected:
            self._disconnect_lsp_signals()
        
        self._lsp_client = client
        self._connect_lsp_signals()
        logger.info("[AuthService] LSP client set")
    
    def _connect_chat_signals(self) -> None:
        """Connect to chat client signals."""
        if not self._chat_client:
            return
        
        try:
            self._chat_client.authenticated.connect(self._on_chat_authenticated)
            self._chat_client.auth_failed.connect(self._on_chat_auth_failed)
            self._chat_client.auth_required.connect(self._on_chat_auth_required)
            self._chat_client.auth_started.connect(self._on_chat_auth_started)
            self._chat_client.models_changed.connect(self._on_models_changed)
            if hasattr(self._chat_client, 'gh_not_found'):
                self._chat_client.gh_not_found.connect(self._on_chat_gh_not_found)
            self._chat_connected = True
            logger.debug("[AuthService] Chat signals connected")
        except Exception as e:
            logger.warning(f"[AuthService] Failed to connect chat signals: {e}")
    
    def _disconnect_chat_signals(self) -> None:
        """Disconnect from chat client signals."""
        if not self._chat_client:
            return
        
        try:
            self._chat_client.authenticated.disconnect(self._on_chat_authenticated)
            self._chat_client.auth_failed.disconnect(self._on_chat_auth_failed)
            self._chat_client.auth_required.disconnect(self._on_chat_auth_required)
            self._chat_client.auth_started.disconnect(self._on_chat_auth_started)
            self._chat_client.models_changed.disconnect(self._on_models_changed)
            if hasattr(self._chat_client, 'gh_not_found'):
                try:
                    self._chat_client.gh_not_found.disconnect(self._on_chat_gh_not_found)
                except (TypeError, RuntimeError):
                    pass
            self._chat_connected = False
        except Exception:
            pass
    
    def _connect_lsp_signals(self) -> None:
        """Connect to LSP client signals."""
        if not self._lsp_client:
            return
        
        try:
            self._lsp_client.authenticated.connect(self._on_lsp_authenticated)
            self._lsp_client.error.connect(self._on_lsp_auth_failed)
            self._lsp_client.auth_required.connect(self._on_lsp_auth_required)
            self._lsp_connected = True
            logger.debug("[AuthService] LSP signals connected")
        except Exception as e:
            logger.warning(f"[AuthService] Failed to connect LSP signals: {e}")
    
    def _disconnect_lsp_signals(self) -> None:
        """Disconnect from LSP client signals."""
        if not self._lsp_client:
            return
        
        try:
            self._lsp_client.authenticated.disconnect(self._on_lsp_authenticated)
            self._lsp_client.error.disconnect(self._on_lsp_auth_failed)
            self._lsp_client.auth_required.disconnect(self._on_lsp_auth_required)
            self._lsp_connected = False
        except Exception:
            pass
    
    # ========================
    # AUTH FLOW LOCK
    # ========================
    
    def _start_auth_flow(self, auth_type: str) -> bool:
        """Acquire auth lock. Returns False if already locked.
        
        Args:
            auth_type: "chat" or "lsp"
        """
        if self._auth_in_progress:
            logger.info(f"[AuthService] {auth_type} auth blocked - {self._auth_type} auth in progress")
            return False
        
        self._auth_in_progress = True
        self._auth_type = auth_type
        logger.info(f"[AuthService] {auth_type} auth flow started")
        return True
    
    def _end_auth_flow(self) -> None:
        """Release auth lock."""
        if self._auth_in_progress:
            logger.info(f"[AuthService] {self._auth_type} auth flow ended")
        self._auth_in_progress = False
        self._auth_type = None
    
    @property
    def auth_in_progress(self) -> bool:
        """Check if an auth flow is currently in progress."""
        return self._auth_in_progress
    
    # ========================
    # CHAT AUTHENTICATION
    # ========================
    
    def login_chat(self) -> bool:
        """Start chat login flow.
        
        Returns:
            True if login started, False if blocked (another auth in progress)
        """
        if not self._chat_client:
            logger.warning("[AuthService] Chat client not set")
            self.chat_auth_failed.emit("Chat client not initialized")
            return False
        
        if not self._start_auth_flow("chat"):
            return False
        
        logger.info("[AuthService] Starting chat login...")
        try:
            # do_login() starts the actual GitHub login flow (device code, browser)
            self._chat_client.do_login()
            return True
        except Exception as e:
            logger.exception("[AuthService] Chat login failed to start")
            self._end_auth_flow()
            self.chat_auth_failed.emit(str(e))
            return False
    
    def logout_chat(self) -> None:
        """Logout from chat."""
        if not self._chat_client:
            return
        
        logger.info("[AuthService] Logging out of chat...")
        try:
            self._chat_client.sign_out()
            self._settings.on_chat_logged_out()
            self.chat_logged_out.emit()
        except Exception as e:
            logger.warning(f"[AuthService] Chat logout failed: {e}")
    
    def verify_chat_auth(self) -> bool:
        """Verify current chat auth status (non-blocking).
        
        Returns:
            True if verification started, False if blocked
        """
        if not self._chat_client:
            return False
        
        if not self._start_auth_flow("chat"):
            return False
        
        logger.info("[AuthService] Verifying chat auth...")
        try:
            # start_auth() just verifies existing auth, doesn't prompt login
            self._chat_client.start_auth()
            return True
        except Exception as e:
            logger.warning(f"[AuthService] Chat verify failed: {e}")
            self._end_auth_flow()
            return False
    
    @property
    def is_chat_authenticated(self) -> bool:
        """Check if chat is currently authenticated."""
        if self._chat_client:
            return self._chat_client.is_authenticated
        return False
    
    @property
    def chat_username(self) -> str:
        """Get current chat username."""
        return self._settings.chat_username
    
    # ========================
    # LSP AUTHENTICATION
    # ========================
    
    def login_lsp(self) -> bool:
        """Start LSP login flow.
        
        Returns:
            True if login started, False if blocked
        """
        if not self._lsp_client:
            logger.warning("[AuthService] LSP client not set")
            self.lsp_auth_failed.emit("LSP client not initialized")
            return False
        
        if not self._start_auth_flow("lsp"):
            return False
        
        logger.info("[AuthService] Starting LSP login...")
        try:
            self._lsp_client.sign_in()
            return True
        except Exception as e:
            logger.exception("[AuthService] LSP login failed to start")
            self._end_auth_flow()
            self.lsp_auth_failed.emit(str(e))
            return False
    
    def logout_lsp(self) -> None:
        """Logout from LSP."""
        if not self._lsp_client:
            return
        
        logger.info("[AuthService] Logging out of LSP...")
        try:
            self._lsp_client.sign_out()
            self._settings.on_lsp_logged_out()
            self.lsp_logged_out.emit()
        except Exception as e:
            logger.warning(f"[AuthService] LSP logout failed: {e}")
    
    def check_lsp_status(self) -> bool:
        """Check LSP auth status without auto-login.
        
        Returns:
            True if check started, False if blocked
        """
        if not self._lsp_client:
            return False
        
        logger.debug("[AuthService] Checking LSP status...")
        # check_status with auto_sign_in=False just checks, doesn't login
        self._lsp_client.check_status(auto_sign_in=False)
        return True
    
    @property
    def is_lsp_authenticated(self) -> bool:
        """Check if LSP is currently authenticated."""
        if self._lsp_client:
            return getattr(self._lsp_client, '_is_authenticated', False)
        return False
    
    @property
    def lsp_username(self) -> str:
        """Get current LSP username."""
        return self._settings.lsp_username
    
    # ========================
    # AUTO-AUTH ON STARTUP
    # ========================
    
    def trigger_auto_auth(self, delay_ms: int = 500) -> None:
        """Trigger auto-authentication for both Chat and LSP if configured.
        
        Called after main window is fully initialized.
        
        Args:
            delay_ms: Delay before checking (default 500ms to let UI settle)
        """
        QTimer.singleShot(delay_ms, self._do_auto_auth)
    
    def _do_auto_auth(self) -> None:
        """Perform auto-auth checks."""
        logger.info("[AuthService] Checking auto-auth...")
        
        # Check Chat auto-auth
        if self._settings.should_auto_auth_chat():
            if self._chat_client and not self.is_chat_authenticated:
                logger.info("[AuthService] Auto-auth: verifying chat...")
                self.verify_chat_auth()
        
        # Check LSP auto-auth (after a small delay to avoid conflicts)
        if self._settings.should_auto_auth_lsp():
            QTimer.singleShot(200, self._do_lsp_auto_auth)
    
    def _do_lsp_auto_auth(self) -> None:
        """Perform LSP auto-auth after delay."""
        if self._lsp_client and not self.is_lsp_authenticated:
            if not self._auth_in_progress:
                logger.info("[AuthService] Auto-auth: checking LSP...")
                # Just check status, LSP's check_status will handle sign-in if needed
                if self._start_auth_flow("lsp"):
                    self._lsp_client.check_status(auto_sign_in=True)
    
    # ========================
    # SIGNAL HANDLERS
    # ========================
    
    def _on_chat_authenticated(self, username: str) -> None:
        """Handle chat authentication success."""
        logger.info(f"[AuthService] Chat authenticated: {username}")
        self._settings.on_chat_authenticated(username)
        self._end_auth_flow()
        self.chat_authenticated.emit(username)
    
    def _on_chat_auth_failed(self, error: str) -> None:
        """Handle chat authentication failure."""
        logger.warning(f"[AuthService] Chat auth failed: {error}")
        self._end_auth_flow()
        self.chat_auth_failed.emit(error)
    
    def _on_chat_gh_not_found(self) -> None:
        """Handle GitHub CLI not found during chat login."""
        logger.warning("[AuthService] GitHub CLI not found")
        self._end_auth_flow()
        self.chat_gh_not_found.emit()
    
    def _on_chat_auth_required(self, code: str, url: str) -> None:
        """Handle chat device code flow."""
        logger.info(f"[AuthService] Chat auth required: code={code}")
        self.chat_auth_required.emit(code, url)
    
    def _on_chat_auth_started(self, message: str) -> None:
        """Handle chat auth started."""
        logger.info(f"[AuthService] Chat auth started: {message}")
        self.chat_auth_started.emit(message)
    
    def _on_models_changed(self, models: list) -> None:
        """Handle models list update."""
        self.models_changed.emit(models)
    
    def _on_lsp_authenticated(self, username: str) -> None:
        """Handle LSP authentication success."""
        logger.info(f"[AuthService] LSP authenticated: {username}")
        self._settings.on_lsp_authenticated(username)
        self._end_auth_flow()
        self.lsp_authenticated.emit(username)
    
    def _on_lsp_auth_failed(self, error: str) -> None:
        """Handle LSP authentication failure."""
        logger.warning(f"[AuthService] LSP auth failed: {error}")
        # Only end flow if this was an auth error, not a general LSP error
        if self._auth_type == "lsp":
            self._end_auth_flow()
            self.lsp_auth_failed.emit(error)
    
    def _on_lsp_auth_required(self, code: str, url: str) -> None:
        """Handle LSP device code flow."""
        logger.info(f"[AuthService] LSP auth required: code={code}")
        self.lsp_auth_required.emit(code, url)
    
    # ========================
    # SETTINGS ACCESS
    # ========================
    
    @property
    def should_auto_auth_chat(self) -> bool:
        """Check if chat should auto-auth."""
        return self._settings.should_auto_auth_chat()
    
    @property
    def should_auto_auth_lsp(self) -> bool:
        """Check if LSP should auto-auth."""
        return self._settings.should_auto_auth_lsp()
    
    @property
    def chat_was_authenticated(self) -> bool:
        """Check if user ever authenticated chat."""
        return self._settings.chat_was_authenticated
    
    @property
    def chat_user_logged_out(self) -> bool:
        """Check if user explicitly logged out of chat."""
        return self._settings.chat_user_logged_out
    
    @property
    def lsp_was_authenticated(self) -> bool:
        """Check if user ever authenticated LSP."""
        return self._settings.lsp_was_authenticated
    
    @property
    def lsp_user_logged_out(self) -> bool:
        """Check if user explicitly logged out of LSP."""
        return self._settings.lsp_user_logged_out
    
    # ========================
    # CLEANUP
    # ========================
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self._disconnect_chat_signals()
        self._disconnect_lsp_signals()
        self._chat_client = None
        self._lsp_client = None
        self._end_auth_flow()
        logger.info("[AuthService] Cleaned up")


# ========================
# MODULE-LEVEL SINGLETON
# ========================

_auth_service_instance: Optional[CopilotAuthService] = None


def get_copilot_auth_service() -> CopilotAuthService:
    """Get the global CopilotAuthService instance.
    
    Creates the instance on first call.
    """
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = CopilotAuthService()
    return _auth_service_instance


def reset_copilot_auth_service() -> None:
    """Reset the auth service instance (for testing)."""
    global _auth_service_instance
    if _auth_service_instance:
        _auth_service_instance.cleanup()
    _auth_service_instance = None
