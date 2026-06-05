"""
Auto-update service for DataPyn

Checks and installs updates from GitHub Releases (Windows ZIP artifacts).
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

import requests
from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

from src.services.windows_installer import (
    find_windows_zip_asset,
    is_newer_version,
    launch_setup_update,
    normalize_version,
    resolve_update_install_dir,
)

logger = logging.getLogger(__name__)

SETTINGS_PENDING_VERSION = "auto_update/pending_version"
SETTINGS_PENDING_ZIP = "auto_update/pending_zip"

_GITHUB_HEADERS = {"User-Agent": "DataPyn-Updater", "Accept": "application/vnd.github+json"}


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
            response = requests.get(url, timeout=15, headers=_GITHUB_HEADERS)
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

            response = requests.get(
                self.download_url,
                stream=True,
                timeout=(15, 120),
                headers={"User-Agent": "DataPyn-Updater"},
            )
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

            logger.info("Update package downloaded: %s (%s bytes)", file_path, downloaded_size)
            self.download_complete.emit(file_path)

        except requests.RequestException as e:
            logger.error(f"Error downloading update: {e}")
            self.download_failed.emit(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error downloading update: {e}")
            self.download_failed.emit(f"Error: {str(e)}")


class AutoUpdateService(QObject):
    """Main auto-update service (lives on the UI thread; marshals worker callbacks safely)."""

    update_downloading = pyqtSignal(str)  # version — emitted when background download starts
    update_ready = pyqtSignal(str)  # version — emitted when ZIP is saved and ready to install

    def __init__(self, current_version: str, repo_owner: str = "natharuc", repo_name: str = "datapyn"):
        super().__init__()
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.settings = QSettings("DataPyn", "DataPyn")
        self._pending_update_version: str = ""

        self._check_thread: Optional[QThread] = None
        self._checker: Optional[UpdateChecker] = None
        self._download_thread: Optional[QThread] = None
        self._downloader: Optional[UpdateDownloader] = None

        self._cb_on_available = None
        self._cb_on_no_update = None
        self._cb_on_error = None
        self._cb_on_progress = None
        self._cb_on_complete = None
        self._cb_on_download_error = None

    def is_auto_update_enabled(self) -> bool:
        return self.settings.value("auto_update/enabled", True, type=bool)

    def set_auto_update_enabled(self, enabled: bool):
        self.settings.setValue("auto_update/enabled", enabled)

    def get_pending_version(self) -> str:
        return normalize_version(str(self.settings.value(SETTINGS_PENDING_VERSION, "") or ""))

    def get_pending_zip_path(self) -> str:
        return str(self.settings.value(SETTINGS_PENDING_ZIP, "") or "")

    def save_pending_update(self, version: str, zip_path: str) -> None:
        self.settings.setValue(SETTINGS_PENDING_VERSION, normalize_version(version))
        self.settings.setValue(SETTINGS_PENDING_ZIP, zip_path)

    def clear_pending_update(self) -> None:
        self.settings.remove(SETTINGS_PENDING_VERSION)
        self.settings.remove(SETTINGS_PENDING_ZIP)

    def has_pending_update(self) -> bool:
        version = self.get_pending_version()
        zip_path = self.get_pending_zip_path()
        if not version or not zip_path:
            return False
        if not os.path.isfile(zip_path):
            self.clear_pending_update()
            return False
        if not is_newer_version(version, self.current_version):
            self.clear_pending_update()
            return False
        return True

    def check_for_updates(self, on_available, on_no_update, on_error):
        try:
            if self._check_thread and self._check_thread.isRunning():
                logger.warning("Update check already in progress")
                return
        except RuntimeError:
            self._check_thread = None

        self._cb_on_available = on_available
        self._cb_on_no_update = on_no_update
        self._cb_on_error = on_error

        self._check_thread = QThread()
        self._checker = UpdateChecker(self.current_version, self.repo_owner, self.repo_name)
        self._checker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._checker.run)
        self._checker.update_available.connect(self._dispatch_update_available)
        self._checker.no_update_available.connect(self._dispatch_no_update)
        self._checker.check_failed.connect(self._dispatch_check_failed)

        self._checker.update_available.connect(self._check_thread.quit)
        self._checker.no_update_available.connect(self._check_thread.quit)
        self._checker.check_failed.connect(self._check_thread.quit)

        self._check_thread.finished.connect(self._checker.deleteLater)
        self._check_thread.finished.connect(self._check_thread.deleteLater)

        self._check_thread.start()

    def _dispatch_update_available(self, version: str, download_url: str, release_notes: str) -> None:
        if self._cb_on_available:
            self._cb_on_available(version, download_url, release_notes)

    def _dispatch_no_update(self) -> None:
        if self._cb_on_no_update:
            self._cb_on_no_update()

    def _dispatch_check_failed(self, message: str) -> None:
        if self._cb_on_error:
            self._cb_on_error(message)

    def check_and_download_in_background(
        self,
        on_ready: Callable[[str], None],
        on_no_update: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Check GitHub; if newer, download ZIP to TEMP silently and persist pending state."""

        def _on_available(version: str, download_url: str, _notes: str) -> None:
            norm = normalize_version(version)
            if self.has_pending_update() and self.get_pending_version() == norm:
                logger.info("Pending update v%s already downloaded", norm)
                self.update_ready.emit(norm)
                return
            logger.info("Update v%s available — starting background download", norm)
            self.update_downloading.emit(norm)
            self._start_background_download(version, download_url, on_ready, on_error)

        self.check_for_updates(_on_available, on_no_update, on_error)

    def _start_background_download(
        self,
        version: str,
        download_url: str,
        on_ready: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        def _on_complete(path: str) -> None:
            norm = normalize_version(version)
            self.save_pending_update(norm, path)
            logger.info("Background update ready: v%s at %s", norm, path)
            self.update_ready.emit(norm)

        self.download_update(
            download_url,
            version,
            on_progress=lambda _pct: None,
            on_complete=_on_complete,
            on_error=on_error,
        )

    def download_update(self, download_url: str, version: str, on_progress, on_complete, on_error):
        try:
            if self._download_thread and self._download_thread.isRunning():
                logger.warning("Update download already in progress")
                return
        except RuntimeError:
            self._download_thread = None

        self._pending_update_version = version
        filename = f"DataPyn-{normalize_version(version)}-windows.zip"

        self._cb_on_progress = on_progress
        self._cb_on_complete = on_complete
        self._cb_on_download_error = on_error

        self._download_thread = QThread()
        self._downloader = UpdateDownloader(download_url, filename)
        self._downloader.moveToThread(self._download_thread)

        self._download_thread.started.connect(self._downloader.run)
        self._downloader.download_progress.connect(self._dispatch_download_progress)
        self._downloader.download_complete.connect(self._dispatch_download_complete)
        self._downloader.download_failed.connect(self._dispatch_download_failed)

        self._downloader.download_complete.connect(self._download_thread.quit)
        self._downloader.download_failed.connect(self._download_thread.quit)

        self._download_thread.finished.connect(self._downloader.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)

        self._download_thread.start()

    def _dispatch_download_progress(self, pct: int) -> None:
        if self._cb_on_progress:
            self._cb_on_progress(pct)

    def _dispatch_download_complete(self, path: str) -> None:
        if self._cb_on_complete:
            self._cb_on_complete(path)

    def _dispatch_download_failed(self, message: str) -> None:
        if self._cb_on_download_error:
            self._cb_on_download_error(message)

    def apply_pending_update(self, install_dir: Optional[Path] = None) -> tuple[bool, str]:
        """Launch DataPyn-Setup.exe --update with the downloaded ZIP (progress UI in Setup)."""
        if not self.has_pending_update():
            return False, "No update package is ready"

        zip_path = self.get_pending_zip_path()
        version = self.get_pending_version()
        root = install_dir or resolve_update_install_dir()
        ok, err = launch_setup_update(Path(zip_path), version, root)
        return ok, err

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
