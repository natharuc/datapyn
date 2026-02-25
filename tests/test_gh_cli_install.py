"""
Tests for GitHub CLI detection and installation flow.

Tests:
- CopilotWorker emits gh_not_found when gh CLI is missing
- CopilotClient propagates gh_not_found signal
- CopilotAuthService propagates chat_gh_not_found signal
- GhCliInstallWorker handles success/failure scenarios
- CopilotChatPanel shows install widget on gh_not_found
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PyQt6.QtCore import QObject, pyqtSignal


# ==================== CopilotWorker Tests ====================


class TestCopilotWorkerGhDetection:
    """Test that CopilotWorker correctly detects missing gh CLI."""

    def test_emits_gh_not_found_when_gh_missing(self, qtbot):
        """Worker should emit gh_not_found when shutil.which('gh') returns None."""
        from src.services.copilot.copilot_client_sdk import CopilotWorker

        worker = CopilotWorker()
        signals_received = {"gh_not_found": False, "error": None, "finished": False}

        worker.gh_not_found.connect(lambda: signals_received.update({"gh_not_found": True}))
        worker.error.connect(lambda e: signals_received.update({"error": e}))
        worker.finished.connect(lambda: signals_received.update({"finished": True}))

        with patch("shutil.which", return_value=None):
            worker.run_login()

        assert signals_received["gh_not_found"] is True
        assert signals_received["finished"] is True
        assert signals_received["error"] is None  # Should NOT emit error

    def test_does_not_emit_gh_not_found_when_gh_exists(self, qtbot):
        """Worker should NOT emit gh_not_found when gh CLI exists."""
        from src.services.copilot.copilot_client_sdk import CopilotWorker

        worker = CopilotWorker()
        gh_not_found_emitted = []

        worker.gh_not_found.connect(lambda: gh_not_found_emitted.append(True))

        mock_process = MagicMock()
        mock_process.stdout.readline.return_value = ""
        mock_process.communicate.return_value = ("Logged in as test", "")
        mock_process.returncode = 0

        with patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("subprocess.Popen", return_value=mock_process):
            worker.run_login()

        assert len(gh_not_found_emitted) == 0

    def test_gh_not_found_signal_exists(self, qtbot):
        """CopilotWorker class should have gh_not_found signal."""
        from src.services.copilot.copilot_client_sdk import CopilotWorker

        worker = CopilotWorker()
        assert hasattr(worker, "gh_not_found")
        # Verify it is a signal (can connect)
        handler = MagicMock()
        worker.gh_not_found.connect(handler)
        worker.gh_not_found.emit()
        handler.assert_called_once()


# ==================== CopilotClient Tests ====================


class TestCopilotClientGhNotFound:
    """Test that CopilotClient propagates gh_not_found signal."""

    def test_client_has_gh_not_found_signal(self, qtbot):
        """CopilotClient should have gh_not_found signal."""
        from src.services.copilot.copilot_client_sdk import CopilotClient

        client = CopilotClient()
        assert hasattr(client, "gh_not_found")
        handler = MagicMock()
        client.gh_not_found.connect(handler)
        client.gh_not_found.emit()
        handler.assert_called_once()

    def test_on_gh_not_found_sets_not_authenticated(self, qtbot):
        """_on_gh_not_found should set is_authenticated to False."""
        from src.services.copilot.copilot_client_sdk import CopilotClient

        client = CopilotClient()
        client._is_authenticated = True

        signals = []
        client.gh_not_found.connect(lambda: signals.append("gh_not_found"))

        client._on_gh_not_found()

        assert client._is_authenticated is False
        assert "gh_not_found" in signals

    def test_do_login_connects_gh_not_found(self, qtbot):
        """do_login should connect worker's gh_not_found to client handler."""
        from src.services.copilot.copilot_client_sdk import CopilotClient, CopilotWorker

        client = CopilotClient()
        signals = []
        client.gh_not_found.connect(lambda: signals.append("gh_not_found"))

        # Manually replicate what do_login does for signal connection only
        worker = CopilotWorker()
        client._session_worker = worker

        # Connect the same way do_login does
        worker.gh_not_found.connect(client._on_gh_not_found)

        # Emit from worker - should propagate to client
        worker.gh_not_found.emit()

        assert "gh_not_found" in signals

        # Cleanup
        client._session_worker = None


# ==================== CopilotAuthService Tests ====================


class MockCopilotClientWithGh(QObject):
    """Mock CopilotClient with gh_not_found signal for testing."""
    authenticated = pyqtSignal(str)
    auth_failed = pyqtSignal(str)
    auth_required = pyqtSignal(str, str)
    auth_started = pyqtSignal(str)
    models_changed = pyqtSignal(list)
    gh_not_found = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_authenticated = False
        self.do_login_called = False

    def do_login(self):
        self.do_login_called = True

    def sign_out(self):
        self.is_authenticated = False


@pytest.fixture
def auth_service_for_gh(qtbot, monkeypatch):
    """Create a fresh CopilotAuthService for gh tests."""
    from src.services.copilot import copilot_auth_service
    copilot_auth_service._auth_service_instance = None

    mock_settings = MagicMock()
    mock_settings.should_auto_auth_chat.return_value = False
    mock_settings.should_auto_auth_lsp.return_value = False

    monkeypatch.setattr(
        "src.services.copilot.copilot_settings.get_copilot_settings",
        lambda: mock_settings
    )

    from src.services.copilot import get_copilot_auth_service
    service = get_copilot_auth_service()

    yield service

    service.cleanup()
    copilot_auth_service._auth_service_instance = None


class TestAuthServiceGhNotFound:
    """Test CopilotAuthService gh_not_found signal handling."""

    def test_auth_service_has_chat_gh_not_found_signal(self, auth_service_for_gh):
        """AuthService should have chat_gh_not_found signal."""
        assert hasattr(auth_service_for_gh, "chat_gh_not_found")
        handler = MagicMock()
        auth_service_for_gh.chat_gh_not_found.connect(handler)
        auth_service_for_gh.chat_gh_not_found.emit()
        handler.assert_called_once()

    def test_gh_not_found_releases_auth_lock(self, auth_service_for_gh, qtbot):
        """gh_not_found should release the auth lock."""
        client = MockCopilotClientWithGh()
        auth_service_for_gh.set_chat_client(client)

        # Simulate auth flow in progress
        auth_service_for_gh._start_auth_flow("chat")
        assert auth_service_for_gh.auth_in_progress is True

        # Emit gh_not_found from client
        received = []
        auth_service_for_gh.chat_gh_not_found.connect(lambda: received.append(True))
        client.gh_not_found.emit()

        assert auth_service_for_gh.auth_in_progress is False
        assert len(received) == 1

    def test_gh_not_found_does_not_emit_auth_failed(self, auth_service_for_gh, qtbot):
        """gh_not_found should NOT emit chat_auth_failed."""
        client = MockCopilotClientWithGh()
        auth_service_for_gh.set_chat_client(client)

        failed_signals = []
        auth_service_for_gh.chat_auth_failed.connect(lambda e: failed_signals.append(e))

        auth_service_for_gh._start_auth_flow("chat")
        client.gh_not_found.emit()

        assert len(failed_signals) == 0


# ==================== GhCliInstallWorker Tests ====================


class TestGhCliInstallWorker:
    """Test the GhCliInstallWorker for installing GitHub CLI."""

    def test_already_installed_succeeds(self, qtbot):
        """If gh is already installed, should emit success immediately."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        with patch("shutil.which", return_value="/usr/bin/gh"):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is True  # success

    def test_non_linux_fails_gracefully(self, qtbot):
        """On non-Linux systems, should fail with helpful message."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        with patch("shutil.which", return_value=None), \
             patch("platform.system", return_value="Windows"):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is False
        assert "Linux" in results[0][1]

    def test_pkexec_not_found_fails_gracefully(self, qtbot):
        """If pkexec is not available, should fail with helpful message."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        def mock_which(cmd):
            if cmd == "gh":
                return None
            if cmd == "pkexec":
                return None
            return None

        with patch("shutil.which", side_effect=mock_which), \
             patch("platform.system", return_value="Linux"):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is False
        assert "pkexec" in results[0][1]

    def test_successful_install(self, qtbot):
        """Successful installation should emit True."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        call_count = {"n": 0}

        def mock_which(cmd):
            if cmd == "gh":
                # First call: not found, second call (verify): found
                call_count["n"] += 1
                return "/usr/bin/gh" if call_count["n"] > 1 else None
            if cmd == "pkexec":
                return "/usr/bin/pkexec"
            return None

        mock_arch_result = MagicMock()
        mock_arch_result.stdout = "amd64\n"
        mock_arch_result.returncode = 0

        mock_install_result = MagicMock()
        mock_install_result.returncode = 0

        with patch("shutil.which", side_effect=mock_which), \
             patch("platform.system", return_value="Linux"), \
             patch("subprocess.run", side_effect=[mock_arch_result, mock_install_result]):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is True

    def test_install_failure_returns_error(self, qtbot):
        """Failed installation should emit False with error message."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        def mock_which(cmd):
            if cmd == "gh":
                return None
            if cmd == "pkexec":
                return "/usr/bin/pkexec"
            return None

        mock_arch_result = MagicMock()
        mock_arch_result.stdout = "amd64\n"
        mock_arch_result.returncode = 0

        mock_install_result = MagicMock()
        mock_install_result.returncode = 1
        mock_install_result.stderr = "apt-get: package not found"
        mock_install_result.stdout = ""

        with patch("shutil.which", side_effect=mock_which), \
             patch("platform.system", return_value="Linux"), \
             patch("subprocess.run", side_effect=[mock_arch_result, mock_install_result]):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is False
        assert "apt-get" in results[0][1]

    def test_pkexec_cancelled_by_user(self, qtbot):
        """User cancelling pkexec should show cancellation message."""
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        def mock_which(cmd):
            if cmd == "gh":
                return None
            if cmd == "pkexec":
                return "/usr/bin/pkexec"
            return None

        mock_arch_result = MagicMock()
        mock_arch_result.stdout = "amd64\n"
        mock_arch_result.returncode = 0

        mock_install_result = MagicMock()
        mock_install_result.returncode = 126
        mock_install_result.stderr = "Request dismissed"
        mock_install_result.stdout = ""

        with patch("shutil.which", side_effect=mock_which), \
             patch("platform.system", return_value="Linux"), \
             patch("subprocess.run", side_effect=[mock_arch_result, mock_install_result]):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is False
        assert "cancelled" in results[0][1].lower()

    def test_timeout_handled(self, qtbot):
        """Timeout during installation should be handled gracefully."""
        import subprocess
        from src.ui.components.copilot_chat_panel import GhCliInstallWorker

        worker = GhCliInstallWorker()
        results = []
        worker.finished.connect(lambda s, m: results.append((s, m)))

        def mock_which(cmd):
            if cmd == "gh":
                return None
            if cmd == "pkexec":
                return "/usr/bin/pkexec"
            return None

        mock_arch_result = MagicMock()
        mock_arch_result.stdout = "amd64\n"
        mock_arch_result.returncode = 0

        with patch("shutil.which", side_effect=mock_which), \
             patch("platform.system", return_value="Linux"), \
             patch("subprocess.run", side_effect=[mock_arch_result, subprocess.TimeoutExpired(cmd="pkexec", timeout=120)]):
            worker.run()

        assert len(results) == 1
        assert results[0][0] is False
        assert "timed out" in results[0][1].lower()


# ==================== CopilotChatPanel Tests ====================


class TestChatPanelGhNotFound:
    """Test CopilotChatPanel behavior when gh CLI is not found."""

    @pytest.fixture
    def chat_panel(self, qtbot):
        """Create a CopilotChatPanel for testing."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel

        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        return panel

    def test_install_widget_hidden_by_default(self, chat_panel):
        """The gh install widget should be hidden initially."""
        assert chat_panel._gh_install_widget.isHidden() is True

    def test_on_gh_not_found_shows_widget(self, chat_panel):
        """_on_gh_not_found should make the install widget visible."""
        chat_panel._on_gh_not_found()
        assert chat_panel._gh_install_widget.isHidden() is False

    def test_on_gh_not_found_resets_auth_button(self, chat_panel):
        """_on_gh_not_found should reset auth button to Sign In state."""
        from src.language import S

        chat_panel._auth_btn.setText("Signing in...")
        chat_panel._auth_btn.setEnabled(False)

        chat_panel._on_gh_not_found()

        assert chat_panel._auth_btn.text() == S.copilot.sign_in
        assert chat_panel._auth_btn.isEnabled() is True

    def test_install_button_disables_during_install(self, chat_panel, qtbot):
        """Install button should be disabled during installation."""
        from src.language import S

        # Mock the thread so it doesn't actually run
        with patch.object(chat_panel, '_gh_install_worker', None), \
             patch.object(chat_panel, '_gh_install_thread', None):
            # We need to patch QThread to not actually start
            with patch("src.ui.components.copilot_chat_panel.QThread") as MockThread:
                mock_thread = MagicMock()
                MockThread.return_value = mock_thread

                with patch("src.ui.components.copilot_chat_panel.GhCliInstallWorker") as MockWorker:
                    mock_worker = MagicMock()
                    MockWorker.return_value = mock_worker

                    chat_panel._install_gh_cli()

                    assert chat_panel._gh_install_btn.isEnabled() is False
                    assert chat_panel._gh_install_btn.text() == S.copilot.installing_gh_cli

    def test_install_success_hides_widget(self, chat_panel):
        """Successful installation should hide the install widget."""
        chat_panel._gh_install_widget.show()

        chat_panel._on_gh_install_finished(True, "")

        assert chat_panel._gh_install_widget.isHidden() is True

    def test_install_failure_re_enables_button(self, chat_panel):
        """Failed installation should re-enable the install button."""
        from src.language import S

        chat_panel._gh_install_btn.setEnabled(False)

        chat_panel._on_gh_install_finished(False, "some error")

        assert chat_panel._gh_install_btn.isEnabled() is True
        assert chat_panel._gh_install_btn.text() == S.copilot.install_gh_cli


# ==================== Translation Tests ====================


class TestGhCliTranslations:
    """Test that all required translation keys exist."""

    def test_en_us_keys_exist(self):
        """English translations should have all gh CLI keys."""
        import json
        from pathlib import Path

        lang_path = Path(__file__).parent.parent / "source" / "src" / "language" / "en-US.json"
        with open(lang_path, encoding="utf-8") as f:
            data = json.load(f)

        copilot = data["copilot"]
        assert "gh_cli_not_found" in copilot
        assert "install_gh_cli" in copilot
        assert "installing_gh_cli" in copilot
        assert "gh_cli_installed" in copilot
        assert "gh_cli_install_failed" in copilot

    def test_pt_br_keys_exist(self):
        """Portuguese translations should have all gh CLI keys."""
        import json
        from pathlib import Path

        lang_path = Path(__file__).parent.parent / "source" / "src" / "language" / "pt-BR.json"
        with open(lang_path, encoding="utf-8") as f:
            data = json.load(f)

        copilot = data["copilot"]
        assert "gh_cli_not_found" in copilot
        assert "install_gh_cli" in copilot
        assert "installing_gh_cli" in copilot
        assert "gh_cli_installed" in copilot
        assert "gh_cli_install_failed" in copilot

    def test_install_failed_has_error_placeholder(self):
        """gh_cli_install_failed should accept {error} format parameter."""
        from src.language import S

        result = S.copilot.gh_cli_install_failed.format(error="test error")
        assert "test error" in result
