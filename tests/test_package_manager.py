"""
Testes para o Gerenciador de Pacotes (PackageManagerService e PackageManagerDialog)
"""
import pytest
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.package_manager_service import (
    PackageManagerService, PackageInfo, PackageOperationResult
)


# ===========================================================================
# PackageInfo Dataclass
# ===========================================================================

class TestPackageInfo:
    """Testes para o dataclass PackageInfo"""

    def test_create_basic(self):
        """PackageInfo com campos obrigatorios"""
        pkg = PackageInfo(name="requests")
        assert pkg.name == "requests"
        assert pkg.version == ""
        assert pkg.installed is False

    def test_create_full(self):
        """PackageInfo com todos os campos"""
        pkg = PackageInfo(
            name="requests",
            version="2.31.0",
            summary="HTTP library",
            author="Kenneth Reitz",
            latest_version="2.32.0",
            installed=True,
        )
        assert pkg.name == "requests"
        assert pkg.version == "2.31.0"
        assert pkg.summary == "HTTP library"
        assert pkg.author == "Kenneth Reitz"
        assert pkg.latest_version == "2.32.0"
        assert pkg.installed is True

    def test_has_update_true(self):
        """has_update retorna True quando versoes diferem"""
        pkg = PackageInfo(name="x", version="1.0", latest_version="2.0")
        assert pkg.has_update is True

    def test_has_update_false_same(self):
        """has_update retorna False quando versoes iguais"""
        pkg = PackageInfo(name="x", version="1.0", latest_version="1.0")
        assert pkg.has_update is False

    def test_has_update_false_empty(self):
        """has_update retorna False sem versoes"""
        pkg = PackageInfo(name="x")
        assert pkg.has_update is False

    def test_has_update_false_no_latest(self):
        """has_update retorna False sem latest_version"""
        pkg = PackageInfo(name="x", version="1.0")
        assert pkg.has_update is False


class TestPackageOperationResult:
    """Testes para o dataclass PackageOperationResult"""

    def test_success_result(self):
        r = PackageOperationResult(
            success=True, package_name="flask", operation="install",
            message="OK"
        )
        assert r.success is True
        assert r.package_name == "flask"
        assert r.operation == "install"
        assert r.message == "OK"
        assert r.error == ""

    def test_failure_result(self):
        r = PackageOperationResult(
            success=False, package_name="flask", operation="install",
            error="Falha na rede"
        )
        assert r.success is False
        assert r.error == "Falha na rede"


# ===========================================================================
# PackageManagerService - list_installed
# ===========================================================================

class TestListInstalled:
    """Testes para PackageManagerService.list_installed"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_list_installed_ok(self, mock_run):
        """Lista pacotes instalados com sucesso"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"name": "requests", "version": "2.31.0"},
                {"name": "flask", "version": "3.0.0"},
            ]),
            stderr=""
        )
        svc = PackageManagerService()
        pkgs = svc.list_installed()
        assert len(pkgs) == 2
        assert pkgs[0].name == "requests"
        assert pkgs[0].version == "2.31.0"
        assert pkgs[0].installed is True
        assert pkgs[1].name == "flask"

    @patch("src.services.package_manager_service.subprocess.run")
    def test_list_installed_error(self, mock_run):
        """Retorna lista vazia em caso de erro"""
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        svc = PackageManagerService()
        pkgs = svc.list_installed()
        assert pkgs == []

    @patch("src.services.package_manager_service.subprocess.run")
    def test_list_installed_exception(self, mock_run):
        """Retorna lista vazia em caso de excecao"""
        mock_run.side_effect = Exception("boom")
        svc = PackageManagerService()
        pkgs = svc.list_installed()
        assert pkgs == []


# ===========================================================================
# PackageManagerService - search_pypi
# ===========================================================================

class TestSearchPyPI:
    """Testes para PackageManagerService.search_pypi"""

    def test_search_empty_query(self):
        """Pesquisa com query vazia retorna vazio"""
        svc = PackageManagerService()
        assert svc.search_pypi("") == []

    def test_search_short_query(self):
        """Pesquisa com query curta retorna vazio"""
        svc = PackageManagerService()
        assert svc.search_pypi("a") == []

    @patch("src.services.package_manager_service.subprocess.run")
    def test_search_found(self, mock_run):
        """Pesquisa encontra pacote com versoes"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=(
                "ERROR: Could not find a version that satisfies "
                "the requirement flask==randominvalidversion "
                "(from versions: 2.0.0, 2.1.0, 3.0.0)\n"
            ),
            stdout=""
        )
        svc = PackageManagerService()
        # Mock list_installed para evitar subprocess real
        svc.list_installed = MagicMock(return_value=[])
        results = svc.search_pypi("flask")
        assert len(results) == 1
        assert results[0].name == "flask"
        assert results[0].latest_version == "3.0.0"
        assert results[0].installed is False

    @patch("src.services.package_manager_service.subprocess.run")
    def test_search_installed_package(self, mock_run):
        """Pesquisa marca pacote como instalado se encontrado localmente"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=(
                "ERROR: (from versions: 1.0.0, 2.0.0)\n"
            ),
            stdout=""
        )
        svc = PackageManagerService()
        svc.list_installed = MagicMock(return_value=[
            PackageInfo(name="flask", version="1.0.0", installed=True)
        ])
        results = svc.search_pypi("flask")
        assert len(results) == 1
        assert results[0].installed is True
        assert results[0].version == "1.0.0"

    @patch("src.services.package_manager_service.subprocess.run")
    def test_search_not_found(self, mock_run):
        """Pesquisa retorna vazio se pacote nao existe"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="No matching distribution found for pacoteinexistente"
        )
        svc = PackageManagerService()
        results = svc.search_pypi("pacoteinexistente")
        assert results == []

    @patch("src.services.package_manager_service.subprocess.run")
    def test_search_exception(self, mock_run):
        """Pesquisa retorna vazio em caso de excecao"""
        mock_run.side_effect = Exception("network error")
        svc = PackageManagerService()
        results = svc.search_pypi("flask")
        assert results == []


# ===========================================================================
# PackageManagerService - install_package
# ===========================================================================

class TestInstallPackage:
    """Testes para PackageManagerService.install_package"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_install_success(self, mock_run):
        """Instala pacote com sucesso"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        result = svc.install_package("flask")
        assert result.success is True
        assert result.operation == "install"
        assert result.package_name == "flask"
        # Verifica que pip install foi chamado
        args = mock_run.call_args[0][0]
        assert "install" in args
        assert "flask" in args

    @patch("src.services.package_manager_service.subprocess.run")
    def test_install_with_version(self, mock_run):
        """Instala pacote com versao especifica"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        result = svc.install_package("flask", version="3.0.0")
        assert result.success is True
        args = mock_run.call_args[0][0]
        assert "flask==3.0.0" in args

    @patch("src.services.package_manager_service.subprocess.run")
    def test_install_failure(self, mock_run):
        """Falha na instalacao retorna resultado com erro"""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Failed to install"
        )
        svc = PackageManagerService()
        result = svc.install_package("pacotequebrado")
        assert result.success is False
        assert "Failed to install" in result.error

    @patch("src.services.package_manager_service.subprocess.run")
    def test_install_timeout(self, mock_run):
        """Timeout na instalacao"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pip", timeout=120)
        svc = PackageManagerService()
        result = svc.install_package("pacotegrande")
        assert result.success is False
        assert "Timeout" in result.error

    @patch("src.services.package_manager_service.subprocess.run")
    def test_install_exception(self, mock_run):
        """Excecao generica na instalacao"""
        mock_run.side_effect = Exception("algo deu errado")
        svc = PackageManagerService()
        result = svc.install_package("flask")
        assert result.success is False
        assert "algo deu errado" in result.error


# ===========================================================================
# PackageManagerService - uninstall_package
# ===========================================================================

class TestUninstallPackage:
    """Testes para PackageManagerService.uninstall_package"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_success(self, mock_run):
        """Desinstala pacote com sucesso"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        result = svc.uninstall_package("flask")
        assert result.success is True
        assert result.operation == "uninstall"
        args = mock_run.call_args[0][0]
        assert "uninstall" in args
        assert "-y" in args

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_pip(self, mock_run):
        """Nao permite desinstalar pip"""
        svc = PackageManagerService()
        result = svc.uninstall_package("pip")
        assert result.success is False
        assert "protegido" in result.error
        mock_run.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_pyqt6(self, mock_run):
        """Nao permite desinstalar pyqt6"""
        svc = PackageManagerService()
        result = svc.uninstall_package("pyqt6")
        assert result.success is False
        assert "protegido" in result.error
        mock_run.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_setuptools(self, mock_run):
        """Nao permite desinstalar setuptools"""
        svc = PackageManagerService()
        result = svc.uninstall_package("setuptools")
        assert result.success is False
        mock_run.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_case_insensitive(self, mock_run):
        """Protecao funciona independente de maiusculas/minusculas"""
        svc = PackageManagerService()
        result = svc.uninstall_package("PyQt6")
        assert result.success is False
        mock_run.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_failure(self, mock_run):
        """Falha ao desinstalar retorna erro"""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Not installed"
        )
        svc = PackageManagerService()
        result = svc.uninstall_package("flask")
        assert result.success is False

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_exception(self, mock_run):
        """Excecao ao desinstalar"""
        mock_run.side_effect = Exception("erro")
        svc = PackageManagerService()
        result = svc.uninstall_package("flask")
        assert result.success is False


# ===========================================================================
# PackageManagerService - update_package
# ===========================================================================

class TestUpdatePackage:
    """Testes para PackageManagerService.update_package"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_update_success(self, mock_run):
        """Atualiza pacote com sucesso"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        result = svc.update_package("flask")
        assert result.success is True
        assert result.operation == "update"
        args = mock_run.call_args[0][0]
        assert "--upgrade" in args

    @patch("src.services.package_manager_service.subprocess.run")
    def test_update_failure(self, mock_run):
        """Falha ao atualizar"""
        mock_run.return_value = MagicMock(returncode=1, stderr="Erro")
        svc = PackageManagerService()
        result = svc.update_package("flask")
        assert result.success is False

    @patch("src.services.package_manager_service.subprocess.run")
    def test_update_exception(self, mock_run):
        """Excecao ao atualizar"""
        mock_run.side_effect = Exception("erro")
        svc = PackageManagerService()
        result = svc.update_package("flask")
        assert result.success is False


# ===========================================================================
# PackageManagerService - get_package_info
# ===========================================================================

class TestGetPackageInfo:
    """Testes para PackageManagerService.get_package_info"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_get_info_success(self, mock_run):
        """Obtem informacoes de pacote instalado"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Name: flask\n"
                "Version: 3.0.0\n"
                "Summary: Web framework\n"
                "Author: Armin Ronacher\n"
            )
        )
        svc = PackageManagerService()
        pkg = svc.get_package_info("flask")
        assert pkg is not None
        assert pkg.name == "flask"
        assert pkg.version == "3.0.0"
        assert pkg.summary == "Web framework"
        assert pkg.author == "Armin Ronacher"
        assert pkg.installed is True

    @patch("src.services.package_manager_service.subprocess.run")
    def test_get_info_not_installed(self, mock_run):
        """Retorna None se pacote nao esta instalado"""
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        svc = PackageManagerService()
        pkg = svc.get_package_info("pacoteinexistente")
        assert pkg is None

    @patch("src.services.package_manager_service.subprocess.run")
    def test_get_info_exception(self, mock_run):
        """Retorna None em caso de excecao"""
        mock_run.side_effect = Exception("erro")
        svc = PackageManagerService()
        pkg = svc.get_package_info("flask")
        assert pkg is None


# ===========================================================================
# PackageManagerService - check_package_exists
# ===========================================================================

class TestCheckPackageExists:
    """Testes para PackageManagerService.check_package_exists"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_exists_true(self, mock_run):
        """Retorna True se pacote esta instalado"""
        mock_run.return_value = MagicMock(returncode=0)
        svc = PackageManagerService()
        assert svc.check_package_exists("flask") is True

    @patch("src.services.package_manager_service.subprocess.run")
    def test_exists_false(self, mock_run):
        """Retorna False se pacote nao esta instalado"""
        mock_run.return_value = MagicMock(returncode=1)
        svc = PackageManagerService()
        assert svc.check_package_exists("pacoteinexistente") is False

    @patch("src.services.package_manager_service.subprocess.run")
    def test_exists_exception(self, mock_run):
        """Retorna False em caso de excecao"""
        mock_run.side_effect = Exception("erro")
        svc = PackageManagerService()
        assert svc.check_package_exists("flask") is False


# ===========================================================================
# PackageManagerService - protected packages
# ===========================================================================

class TestProtectedPackages:
    """Garante que todos os pacotes essenciais estao protegidos"""

    PROTECTED = [
        'pip', 'setuptools', 'wheel',
        'pyqt6', 'pyqt6-qt6', 'pyqt6-sip',
        'qscintilla', 'pyqt6-qscintilla',
    ]

    @patch("src.services.package_manager_service.subprocess.run")
    @pytest.mark.parametrize("name", PROTECTED)
    def test_protected_package(self, mock_run, name):
        """Cada pacote protegido nao pode ser desinstalado"""
        svc = PackageManagerService()
        result = svc.uninstall_package(name)
        assert result.success is False
        assert "protegido" in result.error
        mock_run.assert_not_called()


# ===========================================================================
# PackageManagerDialog - UI
# ===========================================================================

class TestPackageManagerDialog:
    """Testes para PackageManagerDialog (UI)"""

    def test_dialog_creation(self, qtbot):
        """Dialogo e criado corretamente"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, '_load_installed'):
            dialog = PackageManagerDialog(
                theme_manager=ThemeManager(), parent=None
            )
            qtbot.addWidget(dialog)
            assert dialog.windowTitle() == "Gerenciador de Pacotes"
            assert dialog.minimumWidth() >= 780
            assert dialog.minimumHeight() >= 560

    def test_dialog_has_search_field(self, qtbot):
        """Dialogo possui campo de pesquisa"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, '_load_installed'):
            dialog = PackageManagerDialog(
                theme_manager=ThemeManager(), parent=None
            )
            qtbot.addWidget(dialog)
            assert dialog.txt_search is not None
            assert dialog.txt_search.placeholderText() != ""

    def test_dialog_has_table(self, qtbot):
        """Dialogo possui tabela de pacotes"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, '_load_installed'):
            dialog = PackageManagerDialog(
                theme_manager=ThemeManager(), parent=None
            )
            qtbot.addWidget(dialog)
            assert dialog.table is not None
            assert dialog.table.columnCount() == 4

    def test_dialog_has_buttons(self, qtbot):
        """Dialogo possui botoes de pesquisa e instalados"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, '_load_installed'):
            dialog = PackageManagerDialog(
                theme_manager=ThemeManager(), parent=None
            )
            qtbot.addWidget(dialog)
            assert dialog.btn_search is not None
            assert dialog.btn_show_installed is not None

    def test_dialog_has_progress_bar(self, qtbot):
        """Dialogo possui barra de progresso"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, '_load_installed'):
            dialog = PackageManagerDialog(
                theme_manager=ThemeManager(), parent=None
            )
            qtbot.addWidget(dialog)
            assert dialog.progress is not None


# ===========================================================================
# PackageManagerDialog - Workers
# ===========================================================================

class TestWorkers:
    """Testes para os workers QThread"""

    def test_list_worker_emits_result(self, qtbot):
        """_ListWorker emite resultado da listagem"""
        from src.ui.dialogs.package_manager_dialog import _ListWorker

        service = MagicMock()
        service.list_installed.return_value = [
            PackageInfo(name="flask", version="3.0", installed=True)
        ]
        worker = _ListWorker(service)
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert len(blocker.args[0]) == 1
        assert blocker.args[0][0].name == "flask"

    def test_search_worker_emits_result(self, qtbot):
        """_SearchWorker emite resultado da pesquisa"""
        from src.ui.dialogs.package_manager_dialog import _SearchWorker

        service = MagicMock()
        service.search_pypi.return_value = [
            PackageInfo(name="requests", latest_version="2.32")
        ]
        worker = _SearchWorker(service, "requests")
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert len(blocker.args[0]) == 1
        assert blocker.args[0][0].name == "requests"

    def test_install_worker_install(self, qtbot):
        """_InstallWorker executa instalacao"""
        from src.ui.dialogs.package_manager_dialog import _InstallWorker

        service = MagicMock()
        service.install_package.return_value = PackageOperationResult(
            success=True, package_name="flask", operation="install",
            message="Instalado"
        )
        worker = _InstallWorker(service, "install", "flask")
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert blocker.args[0].success is True

    def test_install_worker_uninstall(self, qtbot):
        """_InstallWorker executa desinstalacao"""
        from src.ui.dialogs.package_manager_dialog import _InstallWorker

        service = MagicMock()
        service.uninstall_package.return_value = PackageOperationResult(
            success=True, package_name="flask", operation="uninstall",
            message="Removido"
        )
        worker = _InstallWorker(service, "uninstall", "flask")
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert blocker.args[0].success is True
        assert blocker.args[0].operation == "uninstall"

    def test_install_worker_update(self, qtbot):
        """_InstallWorker executa atualizacao"""
        from src.ui.dialogs.package_manager_dialog import _InstallWorker

        service = MagicMock()
        service.update_package.return_value = PackageOperationResult(
            success=True, package_name="flask", operation="update",
            message="Atualizado"
        )
        worker = _InstallWorker(service, "update", "flask")
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert blocker.args[0].success is True
        assert blocker.args[0].operation == "update"

    def test_install_worker_unknown_operation(self, qtbot):
        """_InstallWorker retorna erro para operacao desconhecida"""
        from src.ui.dialogs.package_manager_dialog import _InstallWorker

        service = MagicMock()
        worker = _InstallWorker(service, "delete", "flask")
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert blocker.args[0].success is False
        assert "desconhecida" in blocker.args[0].error


# ===========================================================================
# Integracao - Menu entry
# ===========================================================================

class TestMenuIntegration:
    """Testa que o Gerenciador de Pacotes esta no menu"""

    def test_main_window_has_package_manager_method(self):
        """MainWindow tem o metodo _show_package_manager"""
        from src.ui.main_window import MainWindow
        assert hasattr(MainWindow, '_show_package_manager')

    def test_imports(self):
        """Imports do servico e dialogo funcionam"""
        from src.services import PackageManagerService
        from src.ui.dialogs import PackageManagerDialog
        assert PackageManagerService is not None
        assert PackageManagerDialog is not None
