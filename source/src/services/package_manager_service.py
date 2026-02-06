"""
Package Manager Service - Gerenciamento de pacotes pip

Responsabilidades:
- Listar pacotes instalados
- Pesquisar pacotes no PyPI
- Instalar/desinstalar pacotes
- Verificar versoes
"""
import subprocess
import sys
import json
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PackageInfo:
    """Informacoes de um pacote"""
    name: str
    version: str = ""
    summary: str = ""
    author: str = ""
    latest_version: str = ""
    installed: bool = False

    @property
    def has_update(self) -> bool:
        """Verifica se ha atualizacao disponivel"""
        if not self.latest_version or not self.version:
            return False
        return self.version != self.latest_version


@dataclass
class PackageOperationResult:
    """Resultado de uma operacao de pacote"""
    success: bool
    package_name: str
    operation: str  # 'install', 'uninstall', 'update'
    message: str = ""
    error: str = ""


class PackageManagerService:
    """
    Servico para gerenciamento de pacotes Python via pip.

    Permite listar, pesquisar, instalar e desinstalar pacotes
    usando o pip do interpretador Python atual.
    """

    def __init__(self):
        self._python_executable = sys.executable

    def list_installed(self) -> List[PackageInfo]:
        """Lista todos os pacotes instalados"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "list",
                 "--format=json", "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode != 0:
                logger.error(f"Erro ao listar pacotes: {result.stderr}")
                return []

            packages = json.loads(result.stdout)
            return [
                PackageInfo(
                    name=pkg["name"],
                    version=pkg.get("version", ""),
                    installed=True
                )
                for pkg in packages
            ]
        except Exception as e:
            logger.error(f"Erro ao listar pacotes: {e}")
            return []

    def search_pypi(self, query: str) -> List[PackageInfo]:
        """
        Pesquisa pacotes no PyPI via pip index.

        Como o pip search foi desabilitado, usamos pip index versions
        para verificar se um pacote existe, e complementamos com
        informacoes basicas.
        """
        if not query or len(query) < 2:
            return []

        try:
            # Tentar obter info do pacote diretamente
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "install",
                 f"{query}==randominvalidversion",
                 "--disable-pip-version-check", "--dry-run"],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # pip vai listar versoes disponiveis no erro
            stderr = result.stderr

            # Verificar se o pacote existe
            if "No matching distribution" in stderr and "randominvalidversion" not in stderr:
                return []

            # Extrair versoes do output de erro
            versions = []
            import re
            # Padrao: "from versions: 1.0.0, 1.1.0, ..."
            match = re.search(r"from versions?:\s*(.+?)(?:\)|$)", stderr)
            if match:
                versions = [v.strip() for v in match.group(1).split(",")]

            latest = versions[-1] if versions else ""

            # Verificar se esta instalado
            installed_packages = {p.name.lower(): p for p in self.list_installed()}
            installed = installed_packages.get(query.lower())

            return [PackageInfo(
                name=query,
                version=installed.version if installed else "",
                latest_version=latest,
                installed=bool(installed),
                summary=f"Versoes disponiveis: {', '.join(versions[-5:])}" if versions else ""
            )]

        except Exception as e:
            logger.error(f"Erro na pesquisa PyPI: {e}")
            return []

    def get_package_info(self, package_name: str) -> Optional[PackageInfo]:
        """Obtem informacoes detalhadas de um pacote instalado"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "show",
                 package_name, "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode != 0:
                return None

            info = {}
            for line in result.stdout.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    info[key.strip()] = value.strip()

            return PackageInfo(
                name=info.get("Name", package_name),
                version=info.get("Version", ""),
                summary=info.get("Summary", ""),
                author=info.get("Author", ""),
                installed=True
            )
        except Exception as e:
            logger.error(f"Erro ao obter info do pacote: {e}")
            return None

    def install_package(self, package_name: str,
                        version: str = "") -> PackageOperationResult:
        """Instala um pacote via pip"""
        target = f"{package_name}=={version}" if version else package_name
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "install",
                 target, "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="install",
                    message=f"Pacote '{package_name}' instalado com sucesso."
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="install",
                    error=result.stderr or "Erro desconhecido na instalacao."
                )
        except subprocess.TimeoutExpired:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="install",
                error="Timeout: a instalacao demorou mais de 2 minutos."
            )
        except Exception as e:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="install",
                error=str(e)
            )

    def uninstall_package(self, package_name: str) -> PackageOperationResult:
        """Desinstala um pacote via pip"""
        # Proteger pacotes essenciais
        protected = {
            'pip', 'setuptools', 'wheel', 'pyqt6', 'pyqt6-qt6',
            'pyqt6-sip', 'qscintilla', 'pyqt6-qscintilla',
        }
        if package_name.lower() in protected:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="uninstall",
                error=f"O pacote '{package_name}' e protegido e nao pode ser removido."
            )

        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "uninstall",
                 package_name, "-y", "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="uninstall",
                    message=f"Pacote '{package_name}' removido com sucesso."
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="uninstall",
                    error=result.stderr or "Erro desconhecido ao desinstalar."
                )
        except Exception as e:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="uninstall",
                error=str(e)
            )

    def update_package(self, package_name: str) -> PackageOperationResult:
        """Atualiza um pacote para a versao mais recente"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "install",
                 "--upgrade", package_name, "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="update",
                    message=f"Pacote '{package_name}' atualizado com sucesso."
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="update",
                    error=result.stderr or "Erro desconhecido ao atualizar."
                )
        except Exception as e:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="update",
                error=str(e)
            )

    def check_package_exists(self, package_name: str) -> bool:
        """Verifica rapidamente se um pacote esta instalado"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "show",
                 package_name, "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return result.returncode == 0
        except Exception:
            return False
