"""
Auto-update service for DataPyn
Checks and installs updates from GitHub Releases (Windows ZIP artifacts).
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import requests
from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

from src.services.windows_installer import (
    apply_downloaded_update,
    find_windows_zip_asset,
    is_newer_version,
    normalize_version,
)

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
            latest_version = normalize_version(release_data.get("tag_name", ""))
            release_notes = release_data.get("body", "")

            asset = find_windows_zip_asset(release_data.get("assets", []))
            if not asset or not asset.download_url:
                self.check_failed.emit("No Windows ZIP package found in release")
                return

            if is_newer_version(latest_version, self.current_version):
                self.update_available.emit(latest_version, asset.download_url, release_notes)
            else:
                self.no_update_available.emit()

        except requests.RequestException as e:
            logger.error(f"Error checking for updates: {e}")
            self.check_failed.emit(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}")
            self.check_failed.emit(f"Error: {str(e)}")


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
        """Download the update package"""
        try:
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, self.filename)

            response = requests.get(self.download_url, stream=True, timeout=60)
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
        self._pending_update_version: str = ""

        self._check_thread: Optional[QThread] = None
        self._checker: Optional[UpdateChecker] = None
        self._download_thread: Optional[QThread] = None
        self._downloader: Optional[UpdateDownloader] = None

    def is_auto_update_enabled(self) -> bool:
        return self.settings.value("auto_update/enabled", True, type=bool)

    def set_auto_update_enabled(self, enabled: bool):
        self.settings.setValue("auto_update/enabled", enabled)

    def check_for_updates(self, on_available, on_no_update, on_error):
        try:
            if self._check_thread and self._check_thread.isRunning():
                logger.warning("Update check already in progress")
                return
        except RuntimeError:
            self._check_thread = None

        self._check_thread = QThread()
        self._checker = UpdateChecker(self.current_version, self.repo_owner, self.repo_name)
        self._checker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._checker.run)
        self._checker.update_available.connect(on_available)
        self._checker.no_update_available.connect(on_no_update)
        self._checker.check_failed.connect(on_error)

        self._checker.update_available.connect(self._check_thread.quit)
        self._checker.no_update_available.connect(self._check_thread.quit)
        self._checker.check_failed.connect(self._check_thread.quit)

        self._check_thread.finished.connect(self._checker.deleteLater)
        self._check_thread.finished.connect(self._check_thread.deleteLater)

        self._check_thread.start()

    def download_update(self, download_url: str, version: str, on_progress, on_complete, on_error):
        try:
            if self._download_thread and self._download_thread.isRunning():
                logger.warning("Update download already in progress")
                return
        except RuntimeError:
            self._download_thread = None

        self._pending_update_version = version
        filename = f"DataPyn-{version}-windows.zip"

        self._download_thread = QThread()
        self._downloader = UpdateDownloader(download_url, filename)
        self._downloader.moveToThread(self._download_thread)

        self._download_thread.started.connect(self._downloader.run)
        self._downloader.download_progress.connect(on_progress)
        self._downloader.download_complete.connect(on_complete)
        self._downloader.download_failed.connect(on_error)

        self._downloader.download_complete.connect(self._download_thread.quit)
        self._downloader.download_failed.connect(self._download_thread.quit)

        self._download_thread.finished.connect(self._downloader.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)

        self._download_thread.start()

    def install_update(self, package_path: str, version: str = "") -> bool:
        """Apply a downloaded ZIP update (app should exit immediately after)."""
        try:
            if not os.path.exists(package_path):
                logger.error(f"Update package not found: {package_path}")
                return False

            if not package_path.lower().endswith(".zip"):
                logger.error(f"Update package must be a ZIP file: {package_path}")
                return False

            temp_dir = tempfile.gettempdir()
            if os.path.commonpath([os.path.abspath(package_path), temp_dir]) != temp_dir:
                logger.error(f"Update package not in temp directory: {package_path}")
                return False

            target_version = normalize_version(version or self._pending_update_version or "")
            if not target_version:
                logger.error("Update version is required to apply ZIP update")
                return False

            apply_downloaded_update(Path(package_path), target_version)
            logger.info("Update applied from %s", package_path)
            return True

        except Exception as e:
            logger.error(f"Error applying update: {e}")
            return False

    def cleanup(self):
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
