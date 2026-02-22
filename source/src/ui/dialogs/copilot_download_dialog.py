"""
Dialog for downloading the Copilot Language Server.

Shows a progress bar during the download process.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
)
from PyQt6.QtCore import Qt, QSize, pyqtSlot
from PyQt6.QtGui import QFont
import logging

from src.language import S
from src.services.copilot.copilot_server_manager import CopilotServerManager

logger = logging.getLogger(__name__)


class CopilotDownloadDialog(QDialog):
    """Dialog for downloading the Copilot Language Server binary."""

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._server_manager = CopilotServerManager(self)
        self._download_started = False
        self._success = False
        self._server_path = ""

        self.setWindowTitle(S.copilot_download.title)
        self.setMinimumSize(QSize(400, 150))
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel(S.copilot_download.downloading_title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Description
        self._status_label = QLabel(S.copilot_download.preparing)
        layout.addWidget(self._status_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # Size label
        self._size_label = QLabel("")
        self._size_label.setStyleSheet("color: #888;")
        layout.addWidget(self._size_label)

        layout.addStretch()

        # Cancel button
        self._cancel_btn = QPushButton(S.copilot_download.btn_cancel)
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.setLayout(layout)

    def _connect_signals(self):
        """Connect manager signals."""
        self._server_manager.download_started.connect(self._on_download_started)
        self._server_manager.download_progress.connect(self._on_progress)
        self._server_manager.download_finished.connect(self._on_finished)

    def start_download(self) -> bool:
        """
        Start the download process.
        
        Returns:
            True if download was started, False otherwise.
        """
        if self._download_started:
            return False
        
        return self._server_manager.start_download()

    def get_server_path(self) -> str:
        """Get the path to the downloaded server, or empty if not downloaded."""
        return self._server_path

    def was_successful(self) -> bool:
        """Check if the download was successful."""
        return self._success

    @pyqtSlot()
    def _on_download_started(self):
        """Handle download started."""
        self._download_started = True
        self._status_label.setText(S.copilot_download.connecting)

    @pyqtSlot(int, int)
    def _on_progress(self, downloaded: int, total: int):
        """Handle download progress."""
        if total > 0:
            percent = int((downloaded / total) * 100)
            self._progress_bar.setValue(percent)
            
            # Format sizes
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self._size_label.setText(
                S.copilot_download.progress_format.format(
                    downloaded=downloaded_mb,
                    total=total_mb
                )
            )
            
            self._status_label.setText(S.copilot_download.downloading)
        else:
            # Unknown size - use indeterminate progress
            self._progress_bar.setMaximum(0)
            self._status_label.setText(S.copilot_download.downloading)

    @pyqtSlot(bool, str)
    def _on_finished(self, success: bool, message: str):
        """Handle download completion."""
        self._success = success
        
        if success:
            self._server_path = message
            self._progress_bar.setValue(100)
            self._status_label.setText(S.copilot_download.complete)
            self._size_label.setText("")
            self._cancel_btn.setText(S.copilot_download.btn_close)
            
            logger.info(f"[COPILOT-DL] Download complete: {message}")
            
            # Auto-close after brief delay
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1000, self.accept)
        else:
            self._progress_bar.setValue(0)
            self._status_label.setText(
                S.copilot_download.failed.format(error=message)
            )
            self._size_label.setText("")
            self._cancel_btn.setText(S.copilot_download.btn_close)
            
            logger.error(f"[COPILOT-DL] Download failed: {message}")

    @pyqtSlot()
    def _on_cancel(self):
        """Handle cancel button."""
        if self._download_started and not self._success:
            self._server_manager.cancel_download()
        
        self.reject()

    def showEvent(self, event):
        """Start download when dialog is shown."""
        super().showEvent(event)
        if not self._download_started:
            self.start_download()
