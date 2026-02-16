"""
Dialog for displaying information about available updates
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QFont
import logging

from src.language import S

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """Dialog for informing about available updates"""

    def __init__(self, current_version: str, new_version: str, release_notes: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.new_version = new_version
        self.release_notes = release_notes
        self.should_download = False

        self.setWindowTitle(S.update_dialog.title)
        self.setMinimumSize(QSize(500, 400))
        self.setModal(True)

        self._init_ui()

    def _init_ui(self):
        """Initializes the UI"""
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Title
        title_label = QLabel(S.update_dialog.new_version_label.format(version=self.new_version))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Current version
        current_label = QLabel(S.update_dialog.current_version_label.format(version=self.current_version))
        layout.addWidget(current_label)

        # Release notes
        notes_label = QLabel(S.update_dialog.whats_new_label)
        notes_label_font = QFont()
        notes_label_font.setBold(True)
        notes_label.setFont(notes_label_font)
        layout.addWidget(notes_label)

        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMarkdown(self.release_notes)
        self.notes_text.setMaximumHeight(200)
        layout.addWidget(self.notes_text)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.later_button = QPushButton(S.update_dialog.btn_later)
        self.later_button.clicked.connect(self.reject)
        button_layout.addWidget(self.later_button)

        self.download_button = QPushButton(S.update_dialog.btn_download_install)
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._on_download)
        button_layout.addWidget(self.download_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _on_download(self):
        """User chose to download the update"""
        self.should_download = True
        self.accept()


class UpdateDownloadDialog(QDialog):
    """Dialog for showing download progress"""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.version = version
        self.installer_path = None

        self.setWindowTitle(S.update_dialog.download_title)
        self.setMinimumSize(QSize(400, 150))
        self.setModal(True)

        # Prevent closing during download
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self._init_ui()

    def _init_ui(self):
        """Initializes the UI"""
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Title
        title_label = QLabel(S.update_dialog.download_msg.format(version=self.version))
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel(S.update_dialog.download_starting)
        layout.addWidget(self.status_label)

        # Cancel button (initially disabled)
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton(S.update_dialog.btn_cancel)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def update_progress(self, percentage: int):
        """Updates progress bar"""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(S.update_dialog.download_progress.format(pct=percentage))

    def download_complete(self, installer_path: str):
        """Marks download as complete"""
        self.installer_path = installer_path
        self.progress_bar.setValue(100)
        self.status_label.setText(S.update_dialog.download_complete)
        self.accept()

    def download_failed(self, error_message: str):
        """Marks download as failed"""
        self.status_label.setText(S.update_dialog.download_error_msg.format(msg=error_message))
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(S.update_dialog.btn_close)

        QMessageBox.critical(
            self, S.update_dialog.download_error_title, S.update_dialog.download_error_detail.format(msg=error_message)
        )


class UpdateCheckingDialog(QDialog):
    """Dialog for showing loading during update check"""

    TIMEOUT_MS = 30000  # 30 seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.update_dialog.checking_title)
        self.setMinimumSize(QSize(350, 150))
        self.setModal(True)

        self._init_ui()

        # Timeout to prevent infinite loading
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(self.TIMEOUT_MS)

    def _init_ui(self):
        """Initializes the UI"""
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Title
        title_label = QLabel(S.update_dialog.checking_msg)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Indeterminate progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)  # Indeterminate mode
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel(S.update_dialog.checking_connecting)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Cancel button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.cancel_button = QPushButton(S.update_dialog.btn_cancel)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _on_timeout(self):
        """Timeout: closes dialog if the check takes too long"""
        self.status_label.setText(S.update_dialog.checking_timeout)
        self.reject()

    def close(self):
        """Stops the timer on close"""
        self._timeout_timer.stop()
        super().close()
