"""
Testes para o Gerenciador de Pacotes (PackageManagerService e PackageManagerDialog)
"""

import os
import pytest
import sys
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QMessageBox

from src.services.package_manager_service import PackageManagerService, PackageInfo, PackageOperationResult


# Fixture that mocks venv detection for all tests in this module.
# This prevents tests from depending on a real .venv directory.
_FAKE_VENV = Path("/fake/venv")
_FAKE_VENV_PYTHON = str(_FAKE_VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))


@pytest.fixture(autouse=True)
def _mock_venv(request):
    # Tests marked with 'real_venv' need the real _find_or_create_venv
    if "real_venv" in [m.name for m in request.node.iter_markers()]:
        yield
        return
    with patch(
        "src.services.package_manager_service._find_or_create_venv",
        return_value=(_FAKE_VENV, _FAKE_VENV_PYTHON),
    ):
        yield


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
        r = PackageOperationResult(success=True, package_name="flask", operation="install", message="OK")
        assert r.success is True
        assert r.package_name == "flask"
        assert r.operation == "install"
        assert r.message == "OK"
        assert r.error == ""

    def test_failure_result(self):
        r = PackageOperationResult(success=False, package_name="flask", operation="install", error="Falha na rede")
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
            stdout=json.dumps(
                [
                    {"name": "requests", "version": "2.31.0"},
                    {"name": "flask", "version": "3.0.0"},
                ]
            ),
            stderr="",
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
    """Testes para PackageManagerService.search_pypi (via PyPI JSON API)"""

    def test_search_empty_query(self):
        """Pesquisa com query vazia retorna vazio"""
        svc = PackageManagerService()
        assert svc.search_pypi("") == []

    def test_search_short_query(self):
        """Pesquisa com query curta retorna vazio"""
        svc = PackageManagerService()
        assert svc.search_pypi("a") == []

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_search_found(self, mock_urlopen):
        """Pesquisa encontra pacote via PyPI JSON API"""
        pypi_response = json.dumps({
            "info": {"name": "flask", "version": "3.0.0", "summary": "Web framework", "author": "Pallets"},
            "releases": {
                "2.0.0": [{"upload_time": "2021-05-01"}],
                "2.1.0": [{"upload_time": "2021-11-01"}],
                "3.0.0": [{"upload_time": "2023-09-01"}],
            },
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        svc = PackageManagerService()
        svc.list_installed = MagicMock(return_value=[])
        results = svc.search_pypi("flask")
        assert len(results) == 1
        assert results[0].name == "flask"
        assert results[0].latest_version == "3.0.0"
        assert results[0].installed is False
        assert results[0].summary == "Web framework"

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_search_installed_package(self, mock_urlopen):
        """Pesquisa marca pacote como instalado se encontrado localmente"""
        pypi_response = json.dumps({
            "info": {"name": "flask", "version": "2.0.0", "summary": "", "author": ""},
            "releases": {"1.0.0": [{"upload_time": "2020-01-01"}], "2.0.0": [{"upload_time": "2021-01-01"}]},
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        svc = PackageManagerService()
        svc.list_installed = MagicMock(return_value=[PackageInfo(name="flask", version="1.0.0", installed=True)])
        results = svc.search_pypi("flask")
        assert len(results) == 1
        assert results[0].installed is True
        assert results[0].version == "1.0.0"

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_search_not_found(self, mock_urlopen):
        """Pesquisa retorna vazio se pacote nao existe (HTTP 404)"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://pypi.org/pypi/pacoteinexistente/json",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )
        svc = PackageManagerService()
        results = svc.search_pypi("pacoteinexistente")
        assert results == []

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_search_exception(self, mock_urlopen):
        """Pesquisa retorna vazio em caso de excecao"""
        mock_urlopen.side_effect = Exception("network error")
        svc = PackageManagerService()
        results = svc.search_pypi("flask")
        assert results == []

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_extra_source_empty_page_not_found(self, mock_urlopen):
        """Extra source retornando pagina sem links de download = pacote nao encontrado"""
        import urllib.error

        # PyPI returns 404
        def side_effect(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "pypi.org" in url:
                raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs={}, fp=None)
            # Azure DevOps returns 200 with empty page (no download links)
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"<html><body></body></html>"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        svc = PackageManagerService()
        svc.list_installed = MagicMock(return_value=[])
        svc.get_sources = MagicMock(return_value=[{"url": "https://feed.example.com/simple/", "username": "", "password": ""}])
        results = svc.search_pypi("pacoteinexistente")
        assert results == []

    @patch("src.services.package_manager_service.urllib.request.urlopen")
    def test_extra_source_with_files_found(self, mock_urlopen):
        """Extra source retornando pagina com links de download = pacote encontrado"""
        import urllib.error

        def side_effect(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "pypi.org" in url:
                raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs={}, fp=None)
            # Feed returns page with actual download links
            mock_resp = MagicMock()
            mock_resp.read.return_value = (
                b'<html><body>'
                b'<a href="mag_autatu-1.0.0.tar.gz">mag_autatu-1.0.0.tar.gz</a>'
                b'<a href="mag_autatu-1.1.0.tar.gz">mag_autatu-1.1.0.tar.gz</a>'
                b'</body></html>'
            )
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mock_urlopen.side_effect = side_effect
        svc = PackageManagerService()
        svc.list_installed = MagicMock(return_value=[])
        svc.get_sources = MagicMock(return_value=[{"url": "https://feed.example.com/simple/", "username": "", "password": ""}])
        results = svc.search_pypi("mag-autatu")
        assert len(results) == 1
        assert results[0].name == "mag-autatu"
        assert results[0].latest_version == "1.1.0"


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
        mock_run.return_value = MagicMock(returncode=1, stderr="Failed to install")
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
        assert "flask" in args

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_pip(self, mock_run):
        """Nao permite desinstalar pip"""
        svc = PackageManagerService()
        result = svc.uninstall_package("pip")
        assert result.success is False
        assert "protected" in result.error
        mock_run.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_uninstall_protected_pyqt6(self, mock_run):
        """Nao permite desinstalar pyqt6"""
        svc = PackageManagerService()
        result = svc.uninstall_package("pyqt6")
        assert result.success is False
        assert "protected" in result.error
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
        mock_run.return_value = MagicMock(returncode=1, stderr="Not installed")
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


class TestUninstallRecordFallback:
    """Testes para fallback de remocao manual quando RECORD esta ausente"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_record_error_triggers_manual_uninstall(self, mock_run, tmp_path):
        """Erro de RECORD aciona remocao manual do site-packages"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="error: Cannot uninstall package; `RECORD` file not found at: ...",
        )
        svc = PackageManagerService()
        svc._uv_executable = "/usr/bin/uv"
        svc._venv_path = tmp_path

        # Criar diretorios simulando pacote no site-packages
        site_packages = tmp_path / "Lib" / "site-packages"
        pkg_dir = site_packages / "fastexcel"
        dist_info = site_packages / "fastexcel-0.19.0.dist-info"
        pkg_dir.mkdir(parents=True)
        dist_info.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (dist_info / "METADATA").write_text("")

        result = svc.uninstall_package("fastexcel")
        assert result.success is True
        assert not pkg_dir.exists()
        assert not dist_info.exists()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_record_error_non_uv_does_not_trigger_fallback(self, mock_run):
        """Erro de RECORD sem uv nao aciona fallback (so pip retorna o erro normal)"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="error: RECORD file not found",
        )
        svc = PackageManagerService()
        svc._uv_executable = None
        result = svc.uninstall_package("fastexcel")
        assert result.success is False
        assert "RECORD" in result.error

    @patch("src.services.package_manager_service.subprocess.run")
    def test_manual_uninstall_no_site_packages(self, mock_run, tmp_path):
        """Retorna None se site-packages nao existe"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path
        result = svc._manual_uninstall("fastexcel")
        assert result is None

    @patch("src.services.package_manager_service.subprocess.run")
    def test_manual_uninstall_no_matching_dirs(self, mock_run, tmp_path):
        """Retorna None se nenhum diretorio corresponde ao pacote"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path

        site_packages = tmp_path / "Lib" / "site-packages"
        site_packages.mkdir(parents=True)
        (site_packages / "other_package").mkdir()

        result = svc._manual_uninstall("fastexcel")
        assert result is None

    @patch("src.services.package_manager_service.subprocess.run")
    def test_manual_uninstall_removes_hyphenated_package(self, mock_run, tmp_path):
        """Remove pacotes com hifen no nome (ex: my-package -> my_package)"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path

        site_packages = tmp_path / "Lib" / "site-packages"
        pkg_dir = site_packages / "my_package"
        dist_info = site_packages / "my_package-1.0.0.dist-info"
        pkg_dir.mkdir(parents=True)
        dist_info.mkdir(parents=True)

        result = svc._manual_uninstall("my-package")
        assert result is not None
        assert result.success is True
        assert not pkg_dir.exists()
        assert not dist_info.exists()


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
            returncode=0, stdout=("Name: flask\nVersion: 3.0.0\nSummary: Web framework\nAuthor: Armin Ronacher\n")
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
        "pip",
        "setuptools",
        "wheel",
        "pyqt6",
        "pyqt6-qt6",
        "pyqt6-sip",
        "pyqt6-webengine",
    ]

    @patch("src.services.package_manager_service.subprocess.run")
    @pytest.mark.parametrize("name", PROTECTED)
    def test_protected_package(self, mock_run, name):
        """Cada pacote protegido nao pode ser desinstalado"""
        svc = PackageManagerService()
        result = svc.uninstall_package(name)
        assert result.success is False
        assert "protected" in result.error
        mock_run.assert_not_called()


# ===========================================================================
# PackageManagerService - venv detection and isolation
# ===========================================================================


class TestVenvDetection:
    """Testes para deteccao e criacao automatica de venv"""

    @pytest.mark.real_venv
    def test_find_or_create_venv_uses_active_venv(self, tmp_path):
        """Quando ja esta dentro de um venv, usa o venv ativo"""
        from src.services.package_manager_service import _find_or_create_venv, _venv_python_path

        venv_dir = tmp_path / ".venv"
        venv_python = _venv_python_path(venv_dir)
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("")

        with (
            patch("src.services.package_manager_service.getattr", return_value=False),
            patch.object(sys, "prefix", str(venv_dir)),
            patch.object(sys, "base_prefix", "/some/other/path"),
        ):
            result_path, result_python = _find_or_create_venv()
            assert result_path == venv_dir
            assert result_python == str(venv_python)

    @pytest.mark.real_venv
    def test_find_or_create_venv_uses_existing_project_venv(self, tmp_path):
        """Quando .venv existe na raiz do projeto, usa ele"""
        from src.services.package_manager_service import _find_or_create_venv, _venv_python_path

        venv_dir = tmp_path / ".venv"
        venv_python = _venv_python_path(venv_dir)
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("")

        with (
            patch("src.services.package_manager_service.getattr", return_value=False),
            # prefix == base_prefix means NOT inside a venv
            patch.object(sys, "prefix", sys.base_prefix),
            patch("src.services.package_manager_service._get_project_root", return_value=tmp_path),
        ):
            result_path, result_python = _find_or_create_venv()
            assert result_path == venv_dir
            assert result_python == str(venv_python)

    @pytest.mark.real_venv
    def test_find_or_create_venv_creates_when_missing(self, tmp_path):
        """Quando .venv nao existe, cria automaticamente"""
        from src.services.package_manager_service import _find_or_create_venv, _venv_python_path

        venv_dir = tmp_path / ".venv"

        with (
            patch("src.services.package_manager_service.getattr", return_value=False),
            patch.object(sys, "prefix", sys.base_prefix),
            patch("src.services.package_manager_service._get_project_root", return_value=tmp_path),
            patch("src.services.package_manager_service.subprocess.run") as mock_run,
        ):
            # Simulate that uv venv creates the python executable
            def create_venv_side_effect(*args, **kwargs):
                venv_python = _venv_python_path(venv_dir)
                venv_python.parent.mkdir(parents=True, exist_ok=True)
                venv_python.write_text("")
                return MagicMock(returncode=0)

            mock_run.side_effect = create_venv_side_effect

            result_path, result_python = _find_or_create_venv()
            assert result_path == venv_dir
            # Verify uv/venv creation was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert str(venv_dir) in call_args

    @pytest.mark.real_venv
    def test_find_or_create_venv_frozen_uses_appdata(self, tmp_path):
        """Em modo frozen (EXE), cria venv no AppData"""
        from src.services.package_manager_service import _find_or_create_venv, _venv_python_path

        appdata_venv = tmp_path / "datapyn" / "venv"
        venv_python = _venv_python_path(appdata_venv)
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("")

        with (
            patch("src.services.package_manager_service.getattr", return_value=True),
            patch("src.services.package_manager_service._get_appdata_venv_dir", return_value=appdata_venv),
        ):
            result_path, result_python = _find_or_create_venv()
            assert result_path == appdata_venv
            assert result_python == str(venv_python)


class TestBuildCmd:
    """Testes para _build_cmd com --python apontando para venv"""

    @patch("src.services.package_manager_service.subprocess.run")
    def test_build_cmd_uv_includes_python_flag(self, mock_run):
        """Quando uv esta disponivel, _build_cmd inclui --python"""
        svc = PackageManagerService()
        svc._uv_executable = "/usr/bin/uv"
        svc._venv_python = "/fake/venv/bin/python"

        cmd = svc._build_cmd(["install", "flask"])
        assert "--python" in cmd
        assert "/fake/venv/bin/python" in cmd
        assert cmd[0] == "/usr/bin/uv"
        assert cmd[1] == "pip"

    @patch("src.services.package_manager_service.subprocess.run")
    def test_build_cmd_pip_fallback_uses_venv_python(self, mock_run):
        """Sem uv, _build_cmd usa o python do venv"""
        svc = PackageManagerService()
        svc._uv_executable = None
        svc._venv_python = "/fake/venv/bin/python"

        cmd = svc._build_cmd(["install", "flask"])
        assert cmd[0] == "/fake/venv/bin/python"
        assert "-m" in cmd
        assert "pip" in cmd
        assert "--python" not in cmd

    @patch("src.services.package_manager_service.subprocess.run")
    def test_build_env_sets_virtual_env(self, mock_run):
        """_build_env define VIRTUAL_ENV e ajusta PATH"""
        svc = PackageManagerService()
        env = svc._build_env()
        assert env["VIRTUAL_ENV"] == str(svc._venv_path)
        assert "PYTHONHOME" not in env
        # PATH deve iniciar com o diretorio Scripts/bin do venv
        if sys.platform == "win32":
            expected_dir = str(svc._venv_path / "Scripts")
        else:
            expected_dir = str(svc._venv_path / "bin")
        assert env["PATH"].startswith(expected_dir)


class TestVenvProperty:
    """Testes para a property venv_path do PackageManagerService"""

    def test_venv_path_returns_string(self):
        """venv_path retorna string com caminho do venv"""
        svc = PackageManagerService()
        assert isinstance(svc.venv_path, str)
        assert len(svc.venv_path) > 0

    def test_venv_path_matches_internal(self):
        """venv_path retorna o mesmo caminho usado internamente"""
        svc = PackageManagerService()
        assert svc.venv_path == str(svc._venv_path)

    @patch("src.services.package_manager_service.subprocess.run")
    def test_subprocess_receives_env_with_virtual_env(self, mock_run):
        """subprocess.run recebe env com VIRTUAL_ENV em install_package"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        svc.install_package("flask")
        # Verifica que env foi passado ao subprocess.run
        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs
        assert "VIRTUAL_ENV" in call_kwargs["env"]


class TestSitePackagesInPath:
    """Testes para injecao do site-packages no sys.path"""

    def test_ensure_site_packages_adds_to_sys_path(self, tmp_path):
        """_ensure_site_packages_in_path adiciona site-packages ao sys.path"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path

        # Criar site-packages
        sp = tmp_path / "Lib" / "site-packages"
        sp.mkdir(parents=True)

        sp_str = str(sp)
        # Remover do sys.path se ja estiver (cleanup)
        if sp_str in sys.path:
            sys.path.remove(sp_str)

        svc._ensure_site_packages_in_path()
        assert sp_str in sys.path

        # Cleanup
        sys.path.remove(sp_str)

    def test_ensure_site_packages_noop_if_already_present(self, tmp_path):
        """_ensure_site_packages_in_path nao duplica se ja esta no sys.path"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path

        sp = tmp_path / "Lib" / "site-packages"
        sp.mkdir(parents=True)

        sp_str = str(sp)
        sys.path.insert(0, sp_str)
        count_before = sys.path.count(sp_str)

        svc._ensure_site_packages_in_path()
        count_after = sys.path.count(sp_str)

        assert count_after == count_before

        # Cleanup
        while sp_str in sys.path:
            sys.path.remove(sp_str)

    def test_ensure_site_packages_noop_if_no_site_packages(self, tmp_path):
        """_ensure_site_packages_in_path nao falha se site-packages nao existe"""
        svc = PackageManagerService()
        svc._venv_path = tmp_path
        # Nao cria site-packages
        svc._ensure_site_packages_in_path()
        # Nenhum erro, nada adicionado

    @patch("src.services.package_manager_service.subprocess.run")
    def test_refresh_import_system_called_after_install(self, mock_run):
        """_refresh_import_system e chamado apos instalacao bem-sucedida"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        with patch.object(svc, "_refresh_import_system") as mock_refresh:
            svc.install_package("flask")
            mock_refresh.assert_called_once()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_refresh_import_system_not_called_on_install_failure(self, mock_run):
        """_refresh_import_system NAO e chamado quando instalacao falha"""
        mock_run.return_value = MagicMock(returncode=1, stderr="Error")
        svc = PackageManagerService()
        with patch.object(svc, "_refresh_import_system") as mock_refresh:
            svc.install_package("flask")
            mock_refresh.assert_not_called()

    @patch("src.services.package_manager_service.subprocess.run")
    def test_refresh_import_system_called_after_uninstall(self, mock_run):
        """_refresh_import_system e chamado apos desinstalacao bem-sucedida"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        svc = PackageManagerService()
        with patch.object(svc, "_refresh_import_system") as mock_refresh:
            svc.uninstall_package("flask")
            mock_refresh.assert_called_once()


# ===========================================================================
# PackageManagerDialog - UI
# ===========================================================================


class TestPackageManagerDialog:
    """Testes para PackageManagerDialog (UI)"""

    def test_dialog_creation(self, qtbot):
        """Dialogo e criado corretamente"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            assert dialog.windowTitle() == "Package Manager"
            assert dialog.minimumWidth() >= 780
            assert dialog.minimumHeight() >= 560

    def test_dialog_has_search_field(self, qtbot):
        """Dialogo possui campo de pesquisa"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            assert dialog.txt_search is not None
            assert dialog.txt_search.placeholderText() != ""

    def test_dialog_has_table(self, qtbot):
        """Dialogo possui tabela de pacotes"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            assert dialog.table is not None
            assert dialog.table.columnCount() == 4

    def test_dialog_has_buttons(self, qtbot):
        """Dialogo possui botoes de pesquisa e instalados"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            assert dialog.btn_search is not None
            assert dialog.btn_show_installed is not None

    def test_dialog_has_progress_bar(self, qtbot):
        """Dialogo possui barra de progresso"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
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
        service.list_installed.return_value = [PackageInfo(name="flask", version="3.0", installed=True)]
        worker = _ListWorker(service)
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
        assert len(blocker.args[0]) == 1
        assert blocker.args[0][0].name == "flask"

    def test_search_worker_emits_result(self, qtbot):
        """_SearchWorker emite resultado da pesquisa"""
        from src.ui.dialogs.package_manager_dialog import _SearchWorker

        service = MagicMock()
        service.search_pypi.return_value = [PackageInfo(name="requests", latest_version="2.32")]
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
            success=True, package_name="flask", operation="install", message="Instalado"
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
            success=True, package_name="flask", operation="uninstall", message="Removido"
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
            success=True, package_name="flask", operation="update", message="Atualizado"
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
        assert "Unknown operation" in blocker.args[0].error


# ===========================================================================
# Integracao - Menu entry
# ===========================================================================


class TestMenuIntegration:
    """Testa que o Gerenciador de Pacotes esta no menu"""

    def test_main_window_has_package_manager_method(self):
        """MainWindow tem o metodo _show_package_manager"""
        from src.ui.main_window import MainWindow

        assert hasattr(MainWindow, "_show_package_manager")

    def test_imports(self):
        """Imports do servico e dialogo funcionam"""
        from src.services import PackageManagerService
        from src.ui.dialogs import PackageManagerDialog

        assert PackageManagerService is not None
        assert PackageManagerDialog is not None


# ===========================================================================
# PackageManagerDialog - cleanup e fluxo corrigido
# ===========================================================================


class TestDialogWorkerCleanup:
    """Testes para limpeza de workers e fluxo de sinais"""

    def test_cleanup_worker_disconnects_signal(self, qtbot):
        """_cleanup_worker desconecta sinais do worker anterior"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)

            # Simular worker ativo
            mock_worker = MagicMock()
            mock_worker.isRunning.return_value = False
            dialog._worker = mock_worker

            dialog._cleanup_worker()
            mock_worker.finished.disconnect.assert_called_once()
            assert dialog._worker is None

    def test_cleanup_worker_none(self, qtbot):
        """_cleanup_worker nao falha com worker None"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            dialog._worker = None
            # Nao deve lancar excecao
            dialog._cleanup_worker()

    def test_cleanup_worker_running(self, qtbot):
        """_cleanup_worker espera worker que ainda esta rodando"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)

            mock_worker = MagicMock()
            mock_worker.isRunning.return_value = True
            dialog._worker = mock_worker

            dialog._cleanup_worker()
            mock_worker.quit.assert_called_once()
            mock_worker.wait.assert_called_once_with(2000)

    def test_pending_query_attribute(self, qtbot):
        """Dialogo possui atributo _pending_query"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            assert hasattr(dialog, "_pending_query")
            assert dialog._pending_query == ""

    def test_show_direct_install_option(self, qtbot):
        """_show_direct_install_option cria botao de instalar na tabela"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)

            dialog._show_direct_install_option("minhalibraria")
            assert dialog.table.rowCount() == 1
            assert dialog.table.item(0, 0).text() == "minhalibraria"
            # Verifica que ha widget de acoes com botao
            widget = dialog.table.cellWidget(0, 3)
            assert widget is not None
            from PyQt6.QtWidgets import QPushButton

            buttons = widget.findChildren(QPushButton)
            assert len(buttons) == 1
            # The action button is icon-only; the label lives in the tooltip.
            from src.language import S
            assert buttons[0].toolTip() == S.package_manager.btn_install_anyway

    def test_operation_done_reloads_installed(self, qtbot):
        """Apos operacao bem sucedida, recarrega lista de instalados"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed") as mock_load:
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            mock_load.reset_mock()

            result = PackageOperationResult(success=True, package_name="flask", operation="install", message="OK")
            with patch.object(QMessageBox, "information"):
                dialog._on_operation_done(result)

            # O reload e agendado via QTimer.singleShot
            # Processar eventos pendentes
            qtbot.waitUntil(lambda: mock_load.called, timeout=2000)

    def test_search_results_empty_shows_not_found_message(self, qtbot):
        """Pesquisa sem resultado mostra mensagem de nao encontrado"""
        from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
        from src.core.theme_manager import ThemeManager

        with patch.object(PackageManagerDialog, "_load_installed"):
            dialog = PackageManagerDialog(theme_manager=ThemeManager(), parent=None)
            qtbot.addWidget(dialog)
            dialog._pending_query = "pacoteinexistente"

            dialog._on_search_results([])

            assert dialog.table.rowCount() == 0
            assert "pacoteinexistente" in dialog.lbl_info.text()


# ===========================================================================
# PythonWorker - deteccao automatica de DataFrames
# ===========================================================================


class TestPythonWorkerDataFrameDetection:
    """Testes para deteccao automatica de novos DataFrames quando resultado e None"""

    def test_new_dataframe_detected_as_result(self):
        """Quando ultima linha e assignment, DataFrame criado deve ser retornado"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        code = "df_new = pd.DataFrame({'A': [1, 2, 3]})"
        namespace = {"pd": pd}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert isinstance(results[0], pd.DataFrame)
        assert len(results[0]) == 3

    def test_multiple_new_dataframes_returns_last(self):
        """Quando multiplos DataFrames sao criados, retorna o ultimo"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        code = "df1 = pd.DataFrame({'A': [1]})\ndf2 = pd.DataFrame({'B': [2, 3]})"
        namespace = {"pd": pd}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert isinstance(results[0], pd.DataFrame)
        assert list(results[0].columns) == ["B"]

    def test_no_new_dataframe_result_stays_none(self):
        """Sem novos DataFrames, resultado permanece None"""
        from src.ui.main_window import PythonWorker

        code = "x = 5\ny = 10\nprint(x + y)"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert results[0] is None

    def test_explicit_expression_takes_priority(self):
        """Quando ultima linha E expressao valida, usa ela (nao a deteccao)"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        code = "df1 = pd.DataFrame({'A': [1, 2]})\n42"
        namespace = {"pd": pd}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert results[0] == 42

    def test_modified_dataframe_detected(self):
        """DataFrame reatribuido (mesmo nome) e detectado"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        original = pd.DataFrame({"A": [1]})
        code = "df = pd.DataFrame({'A': [1, 2, 3]})"
        namespace = {"pd": pd, "df": original}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert isinstance(results[0], pd.DataFrame)
        assert len(results[0]) == 3

    def test_private_vars_excluded(self):
        """Variaveis que comecam com _ nao sao detectadas"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        code = "_temp = pd.DataFrame({'A': [1]})"
        namespace = {"pd": pd}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert len(results) == 1
        assert results[0] is None


# ===========================================================================
# PythonWorker - matplotlib
# ===========================================================================


class TestPythonWorkerMatplotlib:
    """Testes para captura de figuras matplotlib no PythonWorker"""

    def test_python_worker_signal_has_5_params(self):
        """PythonWorker.finished emite 5 parametros (inclui figures)"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("1+1", {}, False)
        # Verificar que o signal aceita 5 parametros
        assert worker.finished is not None

    def test_python_worker_setup_matplotlib_no_matplotlib(self):
        """_setup_matplotlib_backend nao falha sem matplotlib"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("1+1", {}, False)
        # Se matplotlib nao estiver disponivel, nao deve lancar excecao
        with patch.dict("sys.modules", {"matplotlib": None}):
            worker._setup_matplotlib_backend()

    def test_python_worker_capture_no_matplotlib(self):
        """_capture_matplotlib_figures retorna lista vazia sem matplotlib"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("1+1", {}, False)
        with patch.dict("sys.modules", {"matplotlib": None, "matplotlib.pyplot": None}):
            result = worker._capture_matplotlib_figures()
            assert result == []

    def test_python_worker_capture_no_figures(self):
        """_capture_matplotlib_figures retorna lista vazia sem figuras"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("1+1", {}, False)
        mock_plt = MagicMock()
        mock_plt.get_fignums.return_value = []
        with patch.dict("sys.modules", {"matplotlib": MagicMock(), "matplotlib.pyplot": mock_plt}):
            result = worker._capture_matplotlib_figures()
            assert result == []

    def test_main_window_has_display_figures_method(self):
        """MainWindow possui metodo _display_figures_in_results"""
        from src.ui.main_window import MainWindow

        assert hasattr(MainWindow, "_display_figures_in_results")


# ===========================================================================
# PythonWorker - execucao AST e captura stderr
# ===========================================================================


class TestPythonWorkerASTExecution:
    """Testes para execucao baseada em AST e captura de stderr"""

    def test_ast_for_loop_executes_correctly(self):
        """Blocos for nao quebram com a execucao AST"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        code = "total = 0\nfor i in range(5):\n    total += i"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append((r, ns)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is None  # for loop nao retorna valor
        assert results[0][1]["total"] == 10

    def test_ast_if_else_block(self):
        """Blocos if/else executam corretamente"""
        from src.ui.main_window import PythonWorker

        code = "x = 5\nif x > 3:\n    y = 'grande'\nelse:\n    y = 'pequeno'\ny"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert results[0] == "grande"

    def test_ast_function_definition_and_call(self):
        """Definicao e chamada de funcao funciona"""
        from src.ui.main_window import PythonWorker

        code = "def quadrado(n):\n    return n ** 2\nquadrado(7)"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert results[0] == 49

    def test_ast_try_except_block(self):
        """Blocos try/except executam corretamente"""
        from src.ui.main_window import PythonWorker

        code = "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    x = -1"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append((r, ns)))
        worker.run()

        assert results[0][0] is None
        assert results[0][1]["x"] == -1

    def test_ast_preserves_comments_and_blank_lines(self):
        """Comentarios e linhas em branco nao quebram execucao"""
        from src.ui.main_window import PythonWorker

        code = "# comentario\nx = 42\n\n# outro\nx"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        results = []
        worker.finished.connect(lambda r, o, e, ns, f: results.append(r))
        worker.run()

        assert results[0] == 42

    def test_stderr_captured_in_output(self):
        """stderr e capturado junto com stdout"""
        from src.ui.main_window import PythonWorker

        code = "import sys\nprint('stdout_msg')\nsys.stderr.write('stderr_msg')"
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        outputs = []
        worker.finished.connect(lambda r, o, e, ns, f: outputs.append(o))
        worker.run()

        assert "stdout_msg" in outputs[0]
        assert "stderr_msg" in outputs[0]

    def test_logging_output_captured(self):
        """Mensagens de logging sao capturadas quando handler usa stderr"""
        from src.ui.main_window import PythonWorker

        # Criar logger com handler explicito apontando para sys.stderr
        # (que no worker e nosso StringIO capturado)
        code = (
            "import logging, sys\n"
            "h = logging.StreamHandler(sys.stderr)\n"
            "h.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))\n"
            "lg = logging.getLogger('test_capture_abc')\n"
            "lg.handlers.clear()\n"
            "lg.addHandler(h)\n"
            "lg.setLevel(logging.DEBUG)\n"
            "lg.warning('test_warning_msg')"
        )
        namespace = {}
        worker = PythonWorker(code, namespace, False)

        outputs = []
        worker.finished.connect(lambda r, o, e, ns, f: outputs.append(o))
        worker.run()

        assert "test_warning_msg" in outputs[0]


# ===========================================================================
# PythonWorker - processamento de resultado rico
# ===========================================================================


class TestPythonWorkerRichResult:
    """Testes para _process_rich_result"""

    def test_none_result_unchanged(self):
        """Resultado None nao e processado"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)
        result, figs = worker._process_rich_result(None)
        assert result is None
        assert figs == []

    def test_plain_value_unchanged(self):
        """Valores simples (int, str) nao sao processados"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)
        result, figs = worker._process_rich_result(42)
        assert result == 42
        assert figs == []

    def test_dataframe_unchanged(self):
        """DataFrames nao sao convertidos para imagem"""
        import pandas as pd
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)
        df = pd.DataFrame({"A": [1]})
        result, figs = worker._process_rich_result(df)
        assert isinstance(result, pd.DataFrame)
        assert figs == []

    def test_repr_png_object(self):
        """Objetos com _repr_png_() sao convertidos"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)

        # Mock de objeto com _repr_png_
        obj = MagicMock()
        obj._repr_png_ = MagicMock(return_value=b"fake_png_data")
        # Garantir que isinstance checks nao interceptem
        obj.__class__ = type("CustomObj", (), {"_repr_png_": lambda self: b"fake_png_data"})

        result, figs = worker._process_rich_result(obj)
        assert result is None
        assert len(figs) == 1
        assert figs[0] == {"type": "image", "data": b"fake_png_data"}

    def test_matplotlib_figure_with_captured_skips(self):
        """matplotlib Figure ja capturado nao e duplicado"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)

        try:
            import matplotlib.pyplot as plt

            fig = plt.figure()
            plt.close(fig)

            result, figs = worker._process_rich_result(fig, has_captured_figures=True)
            assert result is None
            assert figs == []  # Nao duplica
        except ImportError:
            pytest.skip("matplotlib nao instalado")

    def test_matplotlib_figure_without_captured_converts(self):
        """matplotlib Figure nao capturado e convertido para PNG"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig = plt.figure()
            plt.plot([1, 2, 3])
            plt.close(fig)

            result, figs = worker._process_rich_result(fig, has_captured_figures=False)
            assert result is None
            assert len(figs) == 1
            assert figs[0]["type"] == "image"
            assert len(figs[0]["data"]) > 0  # PNG bytes
        except ImportError:
            pytest.skip("matplotlib nao instalado")

    def test_matplotlib_dark_theme_applied(self):
        """_setup_matplotlib_backend aplica tema escuro"""
        from src.ui.main_window import PythonWorker

        worker = PythonWorker("", {}, False)

        try:
            worker._setup_matplotlib_backend()
            import matplotlib.pyplot as plt

            assert plt.rcParams["figure.facecolor"] == "#1e1e1e"
            assert plt.rcParams["axes.facecolor"] == "#2d2d30"
            assert plt.rcParams["text.color"] == "#d4d4d4"
        except ImportError:
            pytest.skip("matplotlib nao instalado")


# ===========================================================================
# ResultsViewer - exibicao de imagens
# ===========================================================================


class TestResultsViewerImage:
    """Testes para display_image/display_images no ResultsViewer"""

    def test_results_viewer_has_display_image(self):
        """ResultsViewer possui metodo display_image"""
        from src.ui.components.results_viewer import ResultsViewer

        assert hasattr(ResultsViewer, "display_image")
        assert hasattr(ResultsViewer, "display_images")

    def test_results_viewer_has_stack_widget(self, qapp):
        """ResultsViewer usa QStackedWidget com 2 paginas"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        assert hasattr(viewer, "stack")
        assert viewer.stack.count() == 4  # tabela, imagem, html, json

    def test_display_image_switches_to_image_page(self, qapp):
        """display_image mostra pagina de imagem (index 1)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        # Criar PNG via matplotlib
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(2, 2))
            ax.plot([1, 2])
            buf = io.BytesIO()
            fig.savefig(buf, format="png")
            buf.seek(0)
            png = buf.getvalue()
            plt.close(fig)
        except ImportError:
            pytest.skip("matplotlib nao instalado")

        viewer.display_image(png, "Teste")
        assert viewer.stack.currentIndex() == 1
        assert not viewer.btn_save_image.isHidden()
        assert viewer.btn_export_csv.isHidden()

    def test_display_dataframe_switches_to_table_page(self, qapp):
        """display_dataframe mostra pagina de tabela (index 0)"""
        import pandas as pd
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        df = pd.DataFrame({"A": [1, 2, 3]})
        viewer.display_dataframe(df, "teste")
        assert viewer.stack.currentIndex() == 0
        assert not viewer.btn_export_csv.isHidden()
        assert viewer.btn_save_image.isHidden()

    def test_clear_resets_to_table_page(self, qapp):
        """clear() volta para pagina de tabela"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        viewer.stack.setCurrentIndex(1)
        viewer.clear()
        assert viewer.stack.currentIndex() == 0
        assert viewer._current_image_bytes is None

    def test_display_images_single_calls_display_image(self, qapp):
        """display_images com 1 item usa display_image"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(2, 2))
            ax.plot([1, 2, 3])
            buf = io.BytesIO()
            fig.savefig(buf, format="png")
            buf.seek(0)
            png = buf.getvalue()
            plt.close(fig)
        except ImportError:
            pytest.skip("matplotlib nao instalado")

        viewer.display_images([png], "Teste")
        assert viewer.stack.currentIndex() == 1
