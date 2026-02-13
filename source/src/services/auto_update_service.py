"""
Servico de auto-atualizacao para o DataPyn
Verifica e instala atualizacoes do GitHub Releases
"""

import sys
import os
import requests
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QSettings
import logging

logger = logging.getLogger(__name__)


class UpdateChecker(QObject):
    """Worker para verificar atualizacoes em background"""

    update_available = pyqtSignal(str, str, str)  # version, download_url, release_notes
    no_update_available = pyqtSignal()
    check_failed = pyqtSignal(str)  # error_message

    def __init__(self, current_version: str, repo_owner: str, repo_name: str):
        super().__init__()
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name

    def run(self):
        """Verifica se ha atualizacoes disponiveis"""
        try:
            url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            release_data = response.json()
            latest_version = release_data["tag_name"].lstrip("v")
            release_notes = release_data.get("body", "")

            # Encontrar o asset MSI para Windows
            download_url = None
            for asset in release_data.get("assets", []):
                if asset["name"].endswith("-windows.msi"):
                    download_url = asset["browser_download_url"]
                    break

            if not download_url:
                self.check_failed.emit("Nenhum instalador Windows encontrado na release")
                return

            # Comparar versoes
            if self._is_newer_version(latest_version, self.current_version):
                self.update_available.emit(latest_version, download_url, release_notes)
            else:
                self.no_update_available.emit()

        except requests.RequestException as e:
            logger.error(f"Erro ao verificar atualizacoes: {e}")
            self.check_failed.emit(f"Erro de rede: {str(e)}")
        except Exception as e:
            logger.error(f"Erro inesperado ao verificar atualizacoes: {e}")
            self.check_failed.emit(f"Erro: {str(e)}")

    def _is_newer_version(self, latest: str, current: str) -> bool:
        """Compara versoes no formato semantic versioning"""
        try:
            # Remove sufixos como -dryrun, -alpha, etc.
            latest_clean = latest.split("-")[0]
            current_clean = current.split("-")[0]

            latest_parts = [int(x) for x in latest_clean.split(".")]
            current_parts = [int(x) for x in current_clean.split(".")]

            # Garantir mesmo tamanho
            while len(latest_parts) < 3:
                latest_parts.append(0)
            while len(current_parts) < 3:
                current_parts.append(0)

            return latest_parts > current_parts
        except (ValueError, IndexError):
            logger.warning(f"Erro ao comparar versoes: {latest} vs {current}")
            return False


class UpdateDownloader(QObject):
    """Worker para baixar atualizacoes em background"""

    download_progress = pyqtSignal(int)  # percentage
    download_complete = pyqtSignal(str)  # file_path
    download_failed = pyqtSignal(str)  # error_message

    def __init__(self, download_url: str, filename: str):
        super().__init__()
        self.download_url = download_url
        self.filename = filename

    def run(self):
        """Baixa o instalador"""
        try:
            # Criar diretorio temporario para o download
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, self.filename)

            # Download com progresso
            response = requests.get(self.download_url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded_size = 0

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            self.download_progress.emit(progress)

            self.download_complete.emit(file_path)

        except requests.RequestException as e:
            logger.error(f"Erro ao baixar atualizacao: {e}")
            self.download_failed.emit(f"Erro de rede: {str(e)}")
        except Exception as e:
            logger.error(f"Erro inesperado ao baixar atualizacao: {e}")
            self.download_failed.emit(f"Erro: {str(e)}")


class AutoUpdateService:
    """Servico principal de auto-atualizacao"""

    def __init__(self, current_version: str, repo_owner: str = "natharuc", repo_name: str = "datapyn"):
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.settings = QSettings("DataPyn", "DataPyn")

        # Threads
        self._check_thread: Optional[QThread] = None
        self._download_thread: Optional[QThread] = None

    def is_auto_update_enabled(self) -> bool:
        """Verifica se auto-update esta habilitado"""
        return self.settings.value("auto_update/enabled", True, type=bool)

    def set_auto_update_enabled(self, enabled: bool):
        """Habilita ou desabilita auto-update"""
        self.settings.setValue("auto_update/enabled", enabled)

    def check_for_updates(self, on_available, on_no_update, on_error):
        """
        Verifica se ha atualizacoes disponiveis
        
        Args:
            on_available: callback(version, download_url, release_notes)
            on_no_update: callback()
            on_error: callback(error_message)
        """
        if self._check_thread and self._check_thread.isRunning():
            logger.warning("Verificacao de atualizacao ja em andamento")
            return

        self._check_thread = QThread()
        checker = UpdateChecker(self.current_version, self.repo_owner, self.repo_name)
        checker.moveToThread(self._check_thread)

        # Conectar sinais
        self._check_thread.started.connect(checker.run)
        checker.update_available.connect(on_available)
        checker.no_update_available.connect(on_no_update)
        checker.check_failed.connect(on_error)

        # Cleanup
        checker.update_available.connect(self._check_thread.quit)
        checker.no_update_available.connect(self._check_thread.quit)
        checker.check_failed.connect(self._check_thread.quit)
        self._check_thread.finished.connect(self._check_thread.deleteLater)

        self._check_thread.start()

    def download_update(self, download_url: str, version: str, on_progress, on_complete, on_error):
        """
        Baixa a atualizacao
        
        Args:
            download_url: URL do instalador MSI
            version: Versao sendo baixada
            on_progress: callback(percentage)
            on_complete: callback(file_path)
            on_error: callback(error_message)
        """
        if self._download_thread and self._download_thread.isRunning():
            logger.warning("Download de atualizacao ja em andamento")
            return

        filename = f"DataPyn-{version}-windows.msi"

        self._download_thread = QThread()
        downloader = UpdateDownloader(download_url, filename)
        downloader.moveToThread(self._download_thread)

        # Conectar sinais
        self._download_thread.started.connect(downloader.run)
        downloader.download_progress.connect(on_progress)
        downloader.download_complete.connect(on_complete)
        downloader.download_failed.connect(on_error)

        # Cleanup
        downloader.download_complete.connect(self._download_thread.quit)
        downloader.download_failed.connect(self._download_thread.quit)
        self._download_thread.finished.connect(self._download_thread.deleteLater)

        self._download_thread.start()

    def install_update(self, installer_path: str) -> bool:
        """
        Inicia a instalacao da atualizacao
        
        Args:
            installer_path: Caminho do instalador MSI
            
        Returns:
            True se a instalacao foi iniciada com sucesso
        """
        try:
            if not os.path.exists(installer_path):
                logger.error(f"Instalador nao encontrado: {installer_path}")
                return False

            # Executar o instalador MSI
            # /i = instalar
            # /passive = mostrar barra de progresso mas sem interacao
            # /norestart = nao reiniciar automaticamente
            subprocess.Popen(["msiexec", "/i", installer_path, "/passive", "/norestart"])

            logger.info(f"Instalacao iniciada: {installer_path}")
            return True

        except Exception as e:
            logger.error(f"Erro ao iniciar instalacao: {e}")
            return False

    def cleanup(self):
        """Limpa recursos"""
        if self._check_thread and self._check_thread.isRunning():
            self._check_thread.quit()
            self._check_thread.wait()

        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.quit()
            self._download_thread.wait()
