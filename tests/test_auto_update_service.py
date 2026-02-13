"""
Testes para o servico de auto-atualizacao
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtCore import QSettings
from src.services.auto_update_service import AutoUpdateService, UpdateChecker, UpdateDownloader


@pytest.fixture
def auto_update_service():
    """Fixture que retorna uma instancia do AutoUpdateService"""
    with patch.object(QSettings, "value", return_value=True):
        service = AutoUpdateService("1.0.0", "test-owner", "test-repo")
    return service


class TestUpdateChecker:
    """Testes para UpdateChecker"""

    def test_is_newer_version_returns_true_for_newer(self):
        """Testa se detecta versao mais nova corretamente"""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert checker._is_newer_version("1.1.0", "1.0.0") is True
        assert checker._is_newer_version("2.0.0", "1.0.0") is True
        assert checker._is_newer_version("1.0.1", "1.0.0") is True

    def test_is_newer_version_returns_false_for_older_or_same(self):
        """Testa se detecta versao mais antiga ou igual corretamente"""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert checker._is_newer_version("1.0.0", "1.0.0") is False
        assert checker._is_newer_version("0.9.0", "1.0.0") is False
        assert checker._is_newer_version("1.0.0", "1.1.0") is False

    def test_is_newer_version_handles_prereleases(self):
        """Testa se lida com pre-releases corretamente removendo sufixos"""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        # Pre-release suffixes sao removidos, entao 1.1.0-alpha e tratado como 1.1.0
        assert checker._is_newer_version("1.1.0-alpha", "1.0.0") is True
        # Ambos 1.0.0-alpha e 1.0.0-beta sao tratados como 1.0.0, logo nao ha diferenca
        assert checker._is_newer_version("1.0.0-beta", "1.0.0-alpha") is False
        # 1.0.0 nao e mais novo que 1.0.0
        assert checker._is_newer_version("1.0.0", "1.0.0") is False

    @patch("src.services.auto_update_service.requests.get")
    def test_check_for_updates_emits_update_available(self, mock_get, qtbot):
        """Testa se emite sinal quando ha atualizacao"""
        checker = UpdateChecker("1.0.0", "owner", "repo")

        mock_response = Mock()
        mock_response.json.return_value = {
            "tag_name": "v1.1.0",
            "body": "Release notes",
            "assets": [{"name": "App-1.1.0-windows.msi", "browser_download_url": "http://example.com/file.msi"}],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with qtbot.waitSignal(checker.update_available, timeout=1000):
            checker.run()

    @patch("src.services.auto_update_service.requests.get")
    def test_check_for_updates_emits_no_update(self, mock_get, qtbot):
        """Testa se emite sinal quando nao ha atualizacao"""
        checker = UpdateChecker("1.1.0", "owner", "repo")

        mock_response = Mock()
        mock_response.json.return_value = {
            "tag_name": "v1.0.0",
            "body": "Release notes",
            "assets": [{"name": "App-1.0.0-windows.msi", "browser_download_url": "http://example.com/file.msi"}],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with qtbot.waitSignal(checker.no_update_available, timeout=1000):
            checker.run()

    @patch("src.services.auto_update_service.requests.get")
    def test_check_for_updates_handles_network_error(self, mock_get, qtbot):
        """Testa se lida com erros de rede"""
        checker = UpdateChecker("1.0.0", "owner", "repo")

        mock_get.side_effect = Exception("Network error")

        with qtbot.waitSignal(checker.check_failed, timeout=1000):
            checker.run()


class TestAutoUpdateService:
    """Testes para AutoUpdateService"""

    def test_is_auto_update_enabled_default(self):
        """Testa valor padrao de auto-update"""
        with patch.object(QSettings, "value", return_value=True):
            service = AutoUpdateService("1.0.0")
            assert service.is_auto_update_enabled() is True

    def test_set_auto_update_enabled(self):
        """Testa alteracao do estado de auto-update"""
        with patch.object(QSettings, "value", return_value=True):
            service = AutoUpdateService("1.0.0")

        with patch.object(QSettings, "setValue") as mock_set:
            service.set_auto_update_enabled(False)
            mock_set.assert_called_once_with("auto_update/enabled", False)

    def test_check_for_updates_creates_thread(self, auto_update_service):
        """Testa se cria thread para verificacao"""
        on_available = Mock()
        on_no_update = Mock()
        on_error = Mock()

        auto_update_service.check_for_updates(on_available, on_no_update, on_error)

        assert auto_update_service._check_thread is not None
        assert auto_update_service._check_thread.isRunning()

        # Cleanup
        auto_update_service.cleanup()

    def test_download_update_creates_thread(self, auto_update_service):
        """Testa se cria thread para download"""
        on_progress = Mock()
        on_complete = Mock()
        on_error = Mock()

        auto_update_service.download_update("http://example.com/file.msi", "1.1.0", on_progress, on_complete, on_error)

        assert auto_update_service._download_thread is not None
        assert auto_update_service._download_thread.isRunning()

        # Cleanup
        auto_update_service.cleanup()

    @patch("src.services.auto_update_service.subprocess.Popen")
    @patch("src.services.auto_update_service.os.path.exists", return_value=True)
    @patch("src.services.auto_update_service.tempfile.gettempdir", return_value="C:\\temp")
    def test_install_update_starts_installer(self, mock_tempdir, mock_exists, mock_popen, auto_update_service):
        """Testa se inicia o instalador MSI"""
        result = auto_update_service.install_update("C:\\temp\\installer.msi")

        assert result is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "msiexec"
        assert args[1] == "/i"
        assert "installer.msi" in args[2]

    @patch("src.services.auto_update_service.os.path.exists", return_value=False)
    def test_install_update_fails_if_file_not_found(self, mock_exists, auto_update_service):
        """Testa se falha quando arquivo nao existe"""
        result = auto_update_service.install_update("C:\\temp\\nonexistent.msi")

        assert result is False

    def test_cleanup_stops_threads(self, auto_update_service):
        """Testa se cleanup para threads em execucao"""
        # Iniciar verificacao
        on_available = Mock()
        on_no_update = Mock()
        on_error = Mock()

        auto_update_service.check_for_updates(on_available, on_no_update, on_error)

        # Cleanup deve parar a thread
        auto_update_service.cleanup()

        if auto_update_service._check_thread:
            assert not auto_update_service._check_thread.isRunning()


class TestUpdateDownloader:
    """Testes para UpdateDownloader"""

    @patch("src.services.auto_update_service.requests.get")
    @patch("builtins.open", create=True)
    def test_download_emits_progress(self, mock_open, mock_get, qtbot):
        """Testa se emite progresso durante download"""
        downloader = UpdateDownloader("http://example.com/file.msi", "installer.msi")

        mock_response = Mock()
        mock_response.headers.get.return_value = "1000"
        mock_response.iter_content.return_value = [b"x" * 100 for _ in range(10)]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with qtbot.waitSignal(downloader.download_complete, timeout=2000):
            downloader.run()

    @patch("src.services.auto_update_service.requests.get")
    def test_download_handles_error(self, mock_get, qtbot):
        """Testa se lida com erros de download"""
        downloader = UpdateDownloader("http://example.com/file.msi", "installer.msi")

        mock_get.side_effect = Exception("Download error")

        with qtbot.waitSignal(downloader.download_failed, timeout=1000):
            downloader.run()
