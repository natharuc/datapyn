"""
Auto-update service for DataPyn
Checks and installs updates from GitHub Releases
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
    """Worker to check for updates in background"""

    update_available = pyqtSignal(str, str, str)  # version, download_url, release_notes
    no_update_available = pyqtSignal()
    check_failed = pyqtSignal(str)  # error_message

    def __init__(self, current_version: str, repo_owner: str, repo_name: str):
        super().__init__()
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name

    def run(self):
        """Check if updates are available"""
        try:
            url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            release_data = response.json()
            latest_version = release_data["tag_name"]
            # Remove 'v' prefix if present (e.g. v1.0.0 -> 1.0.0)
            if latest_version.startswith("v"):
                latest_version = latest_version[1:]
            release_notes = release_data.get("body", "")

            # Find MSI asset for Windows
            download_url = None
            for asset in release_data.get("assets", []):
                if asset["name"].endswith("-windows.msi"):
                    download_url = asset["browser_download_url"]
                    break

            if not download_url:
                self.check_failed.emit("No Windows installer found in release")
                return

            # Compare versions
            if self._is_newer_version(latest_version, self.current_version):
                self.update_available.emit(latest_version, download_url, release_notes)
            else:
                self.no_update_available.emit()

        except requests.RequestException as e:
            logger.error(f"Error checking for updates: {e}")
            self.check_failed.emit(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}")
            self.check_failed.emit(f"Error: {str(e)}")

    def _is_newer_version(self, latest: str, current: str) -> bool:
        """Compare versions in semantic versioning format"""
        try:
            # Remove suffixes like -dryrun, -alpha, etc.
            latest_clean = latest.split("-")[0]
            current_clean = current.split("-")[0]

            latest_parts = [int(x) for x in latest_clean.split(".")]
            current_parts = [int(x) for x in current_clean.split(".")]

            # Ensure same size
            while len(latest_parts) < 3:
                latest_parts.append(0)
            while len(current_parts) < 3:
                current_parts.append(0)

            return latest_parts > current_parts
        except (ValueError, IndexError):
            logger.warning(f"Error comparing versions: {latest} vs {current}")
            return False


class UpdateDownloader(QObject):
    """Worker to download updates in background"""

    download_progress = pyqtSignal(int)  # percentage
    download_complete = pyqtSignal(str)  # file_path
    download_failed = pyqtSignal(str)  # error_message

    def __init__(self, download_url: str, filename: str):
        super().__init__()
        self.download_url = download_url
        self.filename = filename

    def run(self):
        """Download the installer"""
        try:
            # Create temporary directory for download
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, self.filename)

            # Download with progress
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
            logger.error(f"Error downloading update: {e}")
            self.download_failed.emit(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error downloading update: {e}")
            self.download_failed.emit(f"Error: {str(e)}")


class AutoUpdateService:
    """Main auto-update service"""

    def __init__(self, current_version: str, repo_owner: str = "natharuc", repo_name: str = "datapyn"):
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.settings = QSettings("DataPyn", "DataPyn")

        # Threads and workers (keep reference to avoid GC)
        self._check_thread: Optional[QThread] = None
        self._checker: Optional[UpdateChecker] = None
        self._download_thread: Optional[QThread] = None
        self._downloader: Optional[UpdateDownloader] = None

    def is_auto_update_enabled(self) -> bool:
        """Check if auto-update is enabled"""
        return self.settings.value("auto_update/enabled", True, type=bool)

    def set_auto_update_enabled(self, enabled: bool):
        """Enable or disable auto-update"""
        self.settings.setValue("auto_update/enabled", enabled)

    def check_for_updates(self, on_available, on_no_update, on_error):
        """
        Check if updates are available
        
        Args:
            on_available: callback(version, download_url, release_notes)
            on_no_update: callback()
            on_error: callback(error_message)
        """
        # Check if thread already running (with try/except for deleted object)
        try:
            if self._check_thread and self._check_thread.isRunning():
                logger.warning("Update check already in progress")
                return
        except RuntimeError:
            # C++ object was deleted, clear reference
            self._check_thread = None

        self._check_thread = QThread()
        self._checker = UpdateChecker(self.current_version, self.repo_owner, self.repo_name)
        self._checker.moveToThread(self._check_thread)

        # Conectar sinais
        self._check_thread.started.connect(self._checker.run)
        self._checker.update_available.connect(on_available)
        self._checker.no_update_available.connect(on_no_update)
        self._checker.check_failed.connect(on_error)

        # Quit thread when worker finishes (use queued connection to ensure signals are delivered first)
        self._checker.update_available.connect(self._check_thread.quit)
        self._checker.no_update_available.connect(self._check_thread.quit)
        self._checker.check_failed.connect(self._check_thread.quit)
        
        # Cleanup - use deleteLater to ensure proper cleanup after event loop processes
        self._check_thread.finished.connect(self._checker.deleteLater)
        self._check_thread.finished.connect(self._check_thread.deleteLater)

        self._check_thread.start()

    def download_update(self, download_url: str, version: str, on_progress, on_complete, on_error):
        """
        Download the update
        
        Args:
            download_url: MSI installer URL
            version: Version being downloaded
            on_progress: callback(percentage)
            on_complete: callback(file_path)
            on_error: callback(error_message)
        """
        # Check if download already running (with try/except for deleted object)
        try:
            if self._download_thread and self._download_thread.isRunning():
                logger.warning("Update download already in progress")
                return
        except RuntimeError:
            # C++ object was deleted, clear reference
            self._download_thread = None

        filename = f"DataPyn-{version}-windows.msi"

        self._download_thread = QThread()
        self._downloader = UpdateDownloader(download_url, filename)
        self._downloader.moveToThread(self._download_thread)

        # Conectar sinais
        self._download_thread.started.connect(self._downloader.run)
        self._downloader.download_progress.connect(on_progress)
        self._downloader.download_complete.connect(on_complete)
        self._downloader.download_failed.connect(on_error)

        # Quit thread when worker finishes
        self._downloader.download_complete.connect(self._download_thread.quit)
        self._downloader.download_failed.connect(self._download_thread.quit)
        
        # Cleanup - use deleteLater to ensure proper cleanup after event loop processes
        self._download_thread.finished.connect(self._downloader.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)

        self._download_thread.start()

    def install_update(self, installer_path: str) -> bool:
        """
        Start update installation
        
        Args:
            installer_path: MSI installer path
            
        Returns:
            True if installation started successfully
        """
        try:
            if not os.path.exists(installer_path):
                logger.error(f"Installer not found: {installer_path}")
                return False

            # Validate file is MSI and in temp directory
            if not installer_path.lower().endswith(".msi"):
                logger.error(f"File is not an MSI installer: {installer_path}")
                return False

            # Validate it's in temp directory (security)
            temp_dir = tempfile.gettempdir()
            if not os.path.commonpath([installer_path, temp_dir]) == temp_dir:
                logger.error(f"Installer not in temp directory: {installer_path}")
                return False

            # Execute MSI installer
            # /i = install
            # /passive = show progress bar but no interaction
            # /norestart = don't restart automatically
            subprocess.Popen(["msiexec", "/i", installer_path, "/passive", "/norestart"])

            logger.info(f"Installation started: {installer_path}")
            return True

        except Exception as e:
            logger.error(f"Error starting installation: {e}")
            return False

    def cleanup(self):
        """Clean up resources"""
        self._stop_thread("_check_thread")
        self._stop_thread("_download_thread")
        self._checker = None
        self._downloader = None

    def _stop_thread(self, attr_name: str):
        thread = getattr(self, attr_name, None)
        if not thread:
            return

        try:
            is_running = thread.isRunning()
        except RuntimeError:
            setattr(self, attr_name, None)
            return

        if is_running:
            try:
                thread.quit()
                if not thread.wait(3000):
                    thread.terminate()
                    thread.wait(1000)
            except RuntimeError:
                pass

        setattr(self, attr_name, None)
