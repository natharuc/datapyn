"""
Loading Component - Loading indicator

Visual states for asynchronous operations.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QMovie

from ..design_system import get_colors, TYPOGRAPHY, SPACING


class LoadingSpinner(QWidget):
    """
    Simple loading spinner

    Example:
        spinner = LoadingSpinner(message="Loading...")
        spinner.start()
    """

    def __init__(self, message: str = "Loading...", parent=None):
        super().__init__(parent)

        self.message = message
        self._is_spinning = False
        self._current_frame = 0

        self._setup_ui()
        self._timer = QTimer()
        self._timer.timeout.connect(self._rotate)

    def _setup_ui(self):
        """Sets up UI"""
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING.space_3)

        # Spinner visual (simplified - animated text)
        self.spinner_label = QLabel("⏳")
        font = QFont(TYPOGRAPHY.font_family_primary)
        font.setPixelSize(32)
        self.spinner_label.setFont(font)
        self.spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Message
        self.message_label = QLabel(self.message)
        msg_font = QFont(TYPOGRAPHY.font_family_primary)
        msg_font.setPixelSize(TYPOGRAPHY.text_base)
        self.message_label.setFont(msg_font)
        self.message_label.setStyleSheet(f"color: {colors.text_secondary};")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.spinner_label)
        layout.addWidget(self.message_label)

    def _rotate(self):
        """Animates spinner"""
        frames = ["⏳", "⌛"]
        self._current_frame = (self._current_frame + 1) % len(frames)
        self.spinner_label.setText(frames[self._current_frame])

    def start(self):
        """Starts animation"""
        if not self._is_spinning:
            self._is_spinning = True
            self._timer.start(500)  # 500ms

    def stop(self):
        """Stops animation"""
        if self._is_spinning:
            self._is_spinning = False
            self._timer.stop()
            self.spinner_label.setText("OK")

    def set_message(self, message: str):
        """Updates message"""
        self.message = message
        self.message_label.setText(message)


class ProgressIndicator(QWidget):
    """
    Progress bar with message

    Example:
        progress = ProgressIndicator()
        progress.set_progress(50, "Processing...")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Sets up UI"""
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING.space_2)

        # Message
        self.message_label = QLabel()
        font = QFont(TYPOGRAPHY.font_family_primary)
        font.setPixelSize(TYPOGRAPHY.text_sm)
        self.message_label.setFont(font)
        self.message_label.setStyleSheet(f"color: {colors.text_secondary};")
        layout.addWidget(self.message_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)

        # Modern style for progress bar
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {colors.bg_tertiary};
            }}
            QProgressBar::chunk {{
                background-color: {colors.interactive_primary};
                border-radius: 4px;
            }}
        """)

        layout.addWidget(self.progress_bar)

    def set_progress(self, value: int, message: str = ""):
        """
        Sets progress

        Args:
            value: 0-100
            message: Descriptive message
        """
        self.progress_bar.setValue(value)
        if message:
            self.message_label.setText(message)

    def reset(self):
        """Resets progress"""
        self.progress_bar.setValue(0)
        self.message_label.setText("")


class LoadingOverlay(QWidget):
    """
    Loading overlay that covers the entire parent

    Example:
        overlay = LoadingOverlay(parent_widget)
        overlay.show_loading("Connecting...")
        overlay.hide_loading()
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setVisible(False)
        self._setup_ui()

    def _setup_ui(self):
        """Sets up UI"""
        colors = get_colors()

        # Semi-transparent background
        self.setStyleSheet(f"""
            LoadingOverlay {{
                background-color: {colors.bg_overlay};
            }}
        """)

        # Centered layout
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Spinner
        self.spinner = LoadingSpinner()
        layout.addWidget(self.spinner)

    def show_loading(self, message: str = "Loading..."):
        """Shows overlay with message"""
        self.spinner.set_message(message)
        self.spinner.start()
        self.setVisible(True)
        self.raise_()  # Bring to front

        # Adjust size to cover parent
        if self.parent():
            self.resize(self.parent().size())

    def hide_loading(self):
        """Hides overlay"""
        self.spinner.stop()
        self.setVisible(False)

    def resizeEvent(self, event):
        """Adjusts size when parent resizes"""
        if self.parent():
            self.resize(self.parent().size())
        super().resizeEvent(event)
