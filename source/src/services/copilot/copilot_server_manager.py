"""
Copilot Language Server Manager.

Downloads and manages the copilot-language-server binary for inline completions.
The binary is downloaded on first use and cached locally.
"""

import logging
import os
import platform
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

# Fixed version for stability - update via app releases
COPILOT_SERVER_VERSION = "1.430.0"

# NPM package URLs by platform
PLATFORM_PACKAGES = {
    ("Windows", "AMD64"): "copilot-language-server-win32-x64",
    ("Windows", "x86_64"): "copilot-language-server-win32-x64",
    ("Darwin", "arm64"): "copilot-language-server-darwin-arm64",
    ("Darwin", "x86_64"): "copilot-language-server-darwin-x64",
    ("Linux", "x86_64"): "copilot-language-server-linux-x64",
    ("Linux", "aarch64"): "copilot-language-server-linux-arm64",
}


def get_copilot_server_dir() -> Path:
    """Get the directory where the Copilot server is stored."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    
    return base / "datapyn" / "copilot-lsp"


def get_copilot_server_path() -> Optional[Path]:
    """Get the path to the Copilot language server executable."""
    server_dir = get_copilot_server_dir()
    
    if sys.platform == "win32":
        exe_name = "copilot-language-server.exe"
    else:
        exe_name = "copilot-language-server"
    
    exe_path = server_dir / exe_name
    
    if exe_path.exists():
        return exe_path
    return None


def is_copilot_server_available() -> bool:
    """Check if the Copilot language server is available."""
    return get_copilot_server_path() is not None


def get_platform_package() -> Optional[str]:
    """Get the npm package name for the current platform."""
    system = platform.system()
    machine = platform.machine()
    
    key = (system, machine)
    return PLATFORM_PACKAGES.get(key)


def get_download_url() -> Optional[str]:
    """Get the download URL for the current platform."""
    package = get_platform_package()
    if not package:
        return None
    
    # NPM registry URL format
    return (
        f"https://registry.npmjs.org/@github/{package}/-/"
        f"{package}-{COPILOT_SERVER_VERSION}.tgz"
    )


class DownloadWorker(QObject):
    """Worker thread for downloading the Copilot server."""
    
    progress = pyqtSignal(int, int)  # bytes_downloaded, total_bytes
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, url: str, target_dir: Path):
        super().__init__()
        self._url = url
        self._target_dir = target_dir
        self._cancelled = False
    
    def cancel(self):
        """Cancel the download."""
        self._cancelled = True
    
    def run(self):
        """Download and extract the server."""
        import urllib.request
        import urllib.error
        
        try:
            logger.info(f"[COPILOT-DL] Starting download from {self._url}")
            
            # Create temp file for download
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as tmp:
                tmp_path = tmp.name
            
            # Download with progress
            request = urllib.request.Request(
                self._url,
                headers={"User-Agent": "DataPyn/1.0"}
            )
            
            with urllib.request.urlopen(request, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536  # 64KB chunks
                
                with open(tmp_path, "wb") as f:
                    while True:
                        if self._cancelled:
                            logger.info("[COPILOT-DL] Download cancelled")
                            self.finished.emit(False, "Download cancelled")
                            return
                        
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)
            
            logger.info(f"[COPILOT-DL] Downloaded {downloaded} bytes, extracting...")
            
            # Extract to target directory
            self._target_dir.mkdir(parents=True, exist_ok=True)
            
            with tarfile.open(tmp_path, "r:gz") as tar:
                # NPM packages have a "package" folder inside
                for member in tar.getmembers():
                    if self._cancelled:
                        self.finished.emit(False, "Extraction cancelled")
                        return
                    
                    # Strip "package/" prefix from path
                    if member.name.startswith("package/"):
                        member.name = member.name[8:]  # Remove "package/"
                        if member.name:  # Skip empty names
                            tar.extract(member, self._target_dir)
            
            # Find and make executable
            exe_path = self._find_executable()
            if exe_path and sys.platform != "win32":
                os.chmod(exe_path, 0o755)
            
            # Cleanup temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            
            if exe_path:
                logger.info(f"[COPILOT-DL] Server installed at {exe_path}")
                self.finished.emit(True, str(exe_path))
            else:
                self.finished.emit(False, "Executable not found after extraction")
        
        except urllib.error.URLError as e:
            logger.error(f"[COPILOT-DL] Download failed: {e}")
            self.finished.emit(False, f"Download failed: {e.reason}")
        except Exception as e:
            logger.exception(f"[COPILOT-DL] Error: {e}")
            self.finished.emit(False, str(e))
    
    def _find_executable(self) -> Optional[Path]:
        """Find the executable in the extracted files."""
        if sys.platform == "win32":
            exe_name = "copilot-language-server.exe"
        else:
            exe_name = "copilot-language-server"
        
        # Check direct path
        direct = self._target_dir / exe_name
        if direct.exists():
            return direct
        
        # Search in subdirectories (npm package structure varies)
        for root, dirs, files in os.walk(self._target_dir):
            if exe_name in files:
                return Path(root) / exe_name
        
        return None


class CopilotServerManager(QObject):
    """
    Manages the Copilot Language Server lifecycle.
    
    Handles downloading, updating, and launching the server.
    
    Signals:
        download_started: Download has begun
        download_progress(int, int): bytes downloaded, total bytes
        download_finished(bool, str): success, path or error message
        server_ready(str): Server is ready, path to executable
    """
    
    download_started = pyqtSignal()
    download_progress = pyqtSignal(int, int)
    download_finished = pyqtSignal(bool, str)
    server_ready = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._download_thread: Optional[QThread] = None
        self._download_worker: Optional[DownloadWorker] = None
    
    def is_available(self) -> bool:
        """Check if the server is available."""
        return is_copilot_server_available()
    
    def get_server_path(self) -> Optional[str]:
        """Get the path to the server executable, or None if not available."""
        path = get_copilot_server_path()
        return str(path) if path else None
    
    def ensure_server(self) -> None:
        """
        Ensure the server is available.
        
        If not available, starts download and emits download_started.
        If available, emits server_ready immediately.
        """
        path = get_copilot_server_path()
        if path:
            logger.info(f"[COPILOT] Server already available at {path}")
            self.server_ready.emit(str(path))
            return
        
        # Start download
        self.start_download()
    
    def start_download(self) -> bool:
        """
        Start downloading the server.
        
        Returns:
            True if download started, False if already downloading or unsupported platform.
        """
        if self._download_thread and self._download_thread.isRunning():
            logger.warning("[COPILOT] Download already in progress")
            return False
        
        url = get_download_url()
        if not url:
            platform_info = f"{platform.system()} {platform.machine()}"
            logger.error(f"[COPILOT] Unsupported platform: {platform_info}")
            self.download_finished.emit(False, f"Unsupported platform: {platform_info}")
            return False
        
        target_dir = get_copilot_server_dir()
        
        # Create worker and thread
        self._download_worker = DownloadWorker(url, target_dir)
        self._download_thread = QThread()
        
        self._download_worker.moveToThread(self._download_thread)
        
        # Connect signals
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.finished.connect(self._on_finished)
        
        self.download_started.emit()
        self._download_thread.start()
        
        logger.info(f"[COPILOT] Starting download from {url}")
        return True
    
    def cancel_download(self) -> None:
        """Cancel an in-progress download."""
        if self._download_worker:
            self._download_worker.cancel()
    
    def _on_progress(self, downloaded: int, total: int) -> None:
        """Handle download progress."""
        self.download_progress.emit(downloaded, total)
    
    def _on_finished(self, success: bool, message: str) -> None:
        """Handle download completion."""
        # Cleanup thread
        if self._download_thread:
            self._download_thread.quit()
            self._download_thread.wait(1000)
            self._download_thread = None
        self._download_worker = None
        
        self.download_finished.emit(success, message)
        
        if success:
            self.server_ready.emit(message)
    
    def remove_server(self) -> bool:
        """
        Remove the installed server.
        
        Returns:
            True if removed successfully.
        """
        server_dir = get_copilot_server_dir()
        if server_dir.exists():
            try:
                shutil.rmtree(server_dir)
                logger.info(f"[COPILOT] Removed server from {server_dir}")
                return True
            except Exception as e:
                logger.error(f"[COPILOT] Failed to remove server: {e}")
                return False
        return True
    
    def get_server_version(self) -> str:
        """Get the version of the bundled server."""
        return COPILOT_SERVER_VERSION
