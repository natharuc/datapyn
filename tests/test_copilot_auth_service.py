"""
Tests for centralized CopilotAuthService.

Tests:
- Auth lock acquisition/release
- Chat login/logout flow
- LSP login/logout flow
- Auto-auth logic
- Concurrent auth prevention
- Signal emissions
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QObject, pyqtSignal


class MockCopilotClient(QObject):
    """Mock CopilotClient for testing."""
    authenticated = pyqtSignal(str)
    auth_failed = pyqtSignal(str)
    auth_required = pyqtSignal(str, str)
    auth_started = pyqtSignal(str)
    models_changed = pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.is_authenticated = False
        self.do_login_called = False
        self.sign_out_called = False
        self.start_auth_called = False
    
    def do_login(self):
        self.do_login_called = True
    
    def sign_out(self):
        self.sign_out_called = True
        self.is_authenticated = False
    
    def start_auth(self):
        self.start_auth_called = True


class MockLSPClient(QObject):
    """Mock CopilotLSPClient for testing."""
    authenticated = pyqtSignal(str)
    error = pyqtSignal(str)
    auth_required = pyqtSignal(str, str)
    
    def __init__(self):
        super().__init__()
        self._is_authenticated = False
        self.sign_in_called = False
        self.sign_out_called = False
        self.check_status_called = False
        self.last_auto_sign_in = None
    
    @property
    def is_authenticated(self):
        return self._is_authenticated
    
    def sign_in(self):
        self.sign_in_called = True
    
    def sign_out(self):
        self.sign_out_called = True
        self._is_authenticated = False
    
    def check_status(self, auto_sign_in=False):
        self.check_status_called = True
        self.last_auto_sign_in = auto_sign_in


@pytest.fixture
def auth_service(qtbot, monkeypatch):
    """Create a fresh CopilotAuthService for each test."""
    # Reset singleton BEFORE patching
    from src.services.copilot import copilot_auth_service
    copilot_auth_service._auth_service_instance = None
    
    # Mock CopilotSettingsManager - patch where it's DEFINED (copilot_settings module)
    mock_settings = MagicMock()
    mock_settings.should_auto_auth_chat.return_value = False
    mock_settings.should_auto_auth_lsp.return_value = False
    mock_settings.chat_was_authenticated = False
    mock_settings.chat_user_logged_out = False
    mock_settings.lsp_was_authenticated = False
    mock_settings.lsp_user_logged_out = False
    mock_settings.chat_username = ""
    mock_settings.lsp_username = ""
    
    monkeypatch.setattr(
        "src.services.copilot.copilot_settings.get_copilot_settings",
        lambda: mock_settings
    )
    
    from src.services.copilot import get_copilot_auth_service
    service = get_copilot_auth_service()
    service._mock_settings = mock_settings  # Store for tests to modify
    
    yield service
    
    # Cleanup
    service.cleanup()
    copilot_auth_service._auth_service_instance = None


@pytest.fixture
def mock_chat_client(qtbot):
    """Create mock chat client."""
    return MockCopilotClient()


@pytest.fixture
def mock_lsp_client(qtbot):
    """Create mock LSP client."""
    return MockLSPClient()


class TestAuthServiceBasics:
    """Test basic auth service functionality."""
    
    def test_singleton_instance(self, auth_service):
        """Auth service should be a singleton."""
        from src.services.copilot import get_copilot_auth_service
        service2 = get_copilot_auth_service()
        assert service2 is auth_service
    
    def test_initial_state(self, auth_service):
        """Auth service should start with no auth in progress."""
        assert auth_service.auth_in_progress is False
        assert auth_service._auth_type is None
    
    def test_set_chat_client(self, auth_service, mock_chat_client):
        """Setting chat client should work."""
        auth_service.set_chat_client(mock_chat_client)
        assert auth_service._chat_client is mock_chat_client
        assert auth_service._chat_connected is True
    
    def test_set_lsp_client(self, auth_service, mock_lsp_client):
        """Setting LSP client should work."""
        auth_service.set_lsp_client(mock_lsp_client)
        assert auth_service._lsp_client is mock_lsp_client
        assert auth_service._lsp_connected is True


class TestAuthLock:
    """Test auth flow locking."""
    
    def test_acquire_lock(self, auth_service):
        """Should be able to acquire lock when not in progress."""
        result = auth_service._start_auth_flow("chat")
        assert result is True
        assert auth_service.auth_in_progress is True
        assert auth_service._auth_type == "chat"
    
    def test_lock_blocks_second_acquire(self, auth_service):
        """Second acquire should fail when lock is held."""
        auth_service._start_auth_flow("chat")
        result = auth_service._start_auth_flow("lsp")
        assert result is False
        assert auth_service._auth_type == "chat"  # Still first type
    
    def test_release_lock(self, auth_service):
        """Releasing lock should allow new acquire."""
        auth_service._start_auth_flow("chat")
        auth_service._end_auth_flow()
        
        assert auth_service.auth_in_progress is False
        
        result = auth_service._start_auth_flow("lsp")
        assert result is True


class TestChatLogin:
    """Test chat login flow."""
    
    def test_login_chat_without_client(self, auth_service, qtbot):
        """Login without client should fail and emit error."""
        signals = []
        auth_service.chat_auth_failed.connect(lambda e: signals.append(("failed", e)))
        
        result = auth_service.login_chat()
        
        assert result is False
        assert len(signals) == 1
        assert signals[0][0] == "failed"
    
    def test_login_chat_with_client(self, auth_service, mock_chat_client, qtbot):
        """Login with client should call do_login."""
        auth_service.set_chat_client(mock_chat_client)
        
        result = auth_service.login_chat()
        
        assert result is True
        assert mock_chat_client.do_login_called is True
        assert auth_service.auth_in_progress is True
        assert auth_service._auth_type == "chat"
    
    def test_login_chat_blocked_when_in_progress(self, auth_service, mock_chat_client):
        """Login should be blocked when another auth is in progress."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service._start_auth_flow("lsp")
        
        result = auth_service.login_chat()
        
        assert result is False
        assert mock_chat_client.do_login_called is False
    
    def test_login_chat_signal_on_success(self, auth_service, mock_chat_client, qtbot):
        """Successful auth should emit signal and update state."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.login_chat()
        
        signals = []
        auth_service.chat_authenticated.connect(lambda u: signals.append(u))
        
        # Simulate successful auth
        mock_chat_client.authenticated.emit("testuser")
        
        assert len(signals) == 1
        assert signals[0] == "testuser"
        assert auth_service.auth_in_progress is False  # Lock released


class TestChatLogout:
    """Test chat logout flow."""
    
    def test_logout_chat(self, auth_service, mock_chat_client, qtbot):
        """Logout should call sign_out and emit signal."""
        auth_service.set_chat_client(mock_chat_client)
        mock_chat_client.is_authenticated = True
        
        signals = []
        auth_service.chat_logged_out.connect(lambda: signals.append("logged_out"))
        
        auth_service.logout_chat()
        
        assert mock_chat_client.sign_out_called is True
        assert len(signals) == 1


class TestLSPLogin:
    """Test LSP login flow."""
    
    def test_login_lsp_without_client(self, auth_service, qtbot):
        """Login without client should fail and emit error."""
        signals = []
        auth_service.lsp_auth_failed.connect(lambda e: signals.append(("failed", e)))
        
        result = auth_service.login_lsp()
        
        assert result is False
        assert len(signals) == 1
    
    def test_login_lsp_with_client(self, auth_service, mock_lsp_client, qtbot):
        """Login with client should call sign_in."""
        auth_service.set_lsp_client(mock_lsp_client)
        
        result = auth_service.login_lsp()
        
        assert result is True
        assert mock_lsp_client.sign_in_called is True
        assert auth_service.auth_in_progress is True
        assert auth_service._auth_type == "lsp"
    
    def test_login_lsp_signal_on_success(self, auth_service, mock_lsp_client, qtbot):
        """Successful LSP auth should emit signal and release lock."""
        auth_service.set_lsp_client(mock_lsp_client)
        auth_service.login_lsp()
        
        signals = []
        auth_service.lsp_authenticated.connect(lambda u: signals.append(u))
        
        # Simulate successful auth
        mock_lsp_client.authenticated.emit("lspuser")
        
        assert len(signals) == 1
        assert signals[0] == "lspuser"
        assert auth_service.auth_in_progress is False


class TestLSPLogout:
    """Test LSP logout flow."""
    
    def test_logout_lsp(self, auth_service, mock_lsp_client, qtbot):
        """Logout should call sign_out and emit signal."""
        auth_service.set_lsp_client(mock_lsp_client)
        
        signals = []
        auth_service.lsp_logged_out.connect(lambda: signals.append("logged_out"))
        
        auth_service.logout_lsp()
        
        assert mock_lsp_client.sign_out_called is True
        assert len(signals) == 1


class TestConcurrentAuth:
    """Test prevention of concurrent auth flows."""
    
    def test_chat_blocks_lsp(self, auth_service, mock_chat_client, mock_lsp_client):
        """Chat login should block LSP login."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.set_lsp_client(mock_lsp_client)
        
        # Start chat login
        auth_service.login_chat()
        
        # Try LSP login - should be blocked
        result = auth_service.login_lsp()
        
        assert result is False
        assert mock_lsp_client.sign_in_called is False
    
    def test_lsp_blocks_chat(self, auth_service, mock_chat_client, mock_lsp_client):
        """LSP login should block chat login."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.set_lsp_client(mock_lsp_client)
        
        # Start LSP login
        auth_service.login_lsp()
        
        # Try chat login - should be blocked
        result = auth_service.login_chat()
        
        assert result is False
        assert mock_chat_client.do_login_called is False


class TestAutoAuth:
    """Test auto-authentication on startup."""
    
    def test_auto_auth_disabled(self, auth_service, mock_chat_client, mock_lsp_client, qtbot):
        """Auto-auth should not trigger when disabled."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.set_lsp_client(mock_lsp_client)
        auth_service._mock_settings.should_auto_auth_chat.return_value = False
        auth_service._mock_settings.should_auto_auth_lsp.return_value = False
        
        # Trigger auto-auth with no delay for testing
        auth_service._do_auto_auth()
        
        assert mock_chat_client.start_auth_called is False
        assert mock_lsp_client.check_status_called is False
    
    def test_auto_auth_chat_enabled(self, auth_service, mock_chat_client, qtbot):
        """Auto-auth should verify chat when enabled."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service._mock_settings.should_auto_auth_chat.return_value = True
        
        auth_service._do_auto_auth()
        
        assert mock_chat_client.start_auth_called is True


class TestAuthFailureHandling:
    """Test handling of auth failures."""
    
    def test_chat_auth_failed_releases_lock(self, auth_service, mock_chat_client, qtbot):
        """Auth failure should release the lock."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.login_chat()
        
        assert auth_service.auth_in_progress is True
        
        # Simulate failure
        mock_chat_client.auth_failed.emit("Test error")
        
        assert auth_service.auth_in_progress is False
    
    def test_lsp_auth_failed_releases_lock(self, auth_service, mock_lsp_client, qtbot):
        """LSP auth failure should release the lock."""
        auth_service.set_lsp_client(mock_lsp_client)
        auth_service.login_lsp()
        
        assert auth_service.auth_in_progress is True
        
        # Simulate failure  
        mock_lsp_client.error.emit("Test error")
        
        assert auth_service.auth_in_progress is False


class TestCleanup:
    """Test cleanup functionality."""
    
    def test_cleanup_disconnects_signals(self, auth_service, mock_chat_client, mock_lsp_client):
        """Cleanup should disconnect from clients."""
        auth_service.set_chat_client(mock_chat_client)
        auth_service.set_lsp_client(mock_lsp_client)
        
        auth_service.cleanup()
        
        assert auth_service._chat_client is None
        assert auth_service._lsp_client is None
        assert auth_service._chat_connected is False
        assert auth_service._lsp_connected is False
    
    def test_cleanup_releases_lock(self, auth_service):
        """Cleanup should release any held lock."""
        auth_service._start_auth_flow("chat")
        
        auth_service.cleanup()
        
        assert auth_service.auth_in_progress is False
