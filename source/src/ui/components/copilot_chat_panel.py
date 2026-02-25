"""
Copilot Chat Panel - Chat interface for GitHub Copilot integration.

This panel functions as a dockable block in DataPyn, similar to
Variables, Object Explorer, etc. It provides:
- Chat message display (WebView-based)
- Message input area
- Model selection
- Mode selection (chat/edit/agent)
- GitHub authentication flow
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QSizePolicy,
    QApplication,
    QMenu,
    QWidgetAction,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QUrl, QTimer, QSettings, QByteArray, QObject, QRect, QSize, QThread
from PyQt6.QtGui import QFont, QDesktopServices, QKeyEvent, QIcon, QPixmap, QPainter, QPen, QColor, QFontMetrics
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWebEngineWidgets import QWebEngineView
import sys
from PyQt6.QtWebChannel import QWebChannel
from pathlib import Path
import json
import logging
import os
import re
from datetime import datetime

from src.language import S
from src.design_system.tokens import get_colors, RADIUS
from src.services.copilot.copilot_settings import get_copilot_settings

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


def _load_copilot_icon(color: str, size: int = 20) -> QIcon:
    """Load Copilot SVG icon with custom color."""
    try:
        # Get path relative to this file (ui/components -> ui -> src -> assets/icons)
        components_dir = os.path.dirname(os.path.abspath(__file__))
        ui_dir = os.path.dirname(components_dir)
        src_dir = os.path.dirname(ui_dir)
        svg_path = os.path.join(src_dir, "assets", "icons", "copilot_icon.svg")

        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        # Replace all fill colors
        svg_content = re.sub(r"fill\s*:\s*#[0-9a-fA-F]{3,6}", f"fill:{color}", svg_content)
        svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)

        svg_bytes = QByteArray(svg_content.encode("utf-8"))
        renderer = QSvgRenderer(svg_bytes)

        if not renderer.isValid():
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)
    except Exception as e:
        logger.error(f"Failed to load Copilot icon: {e}")
        return None


class ModelItemDelegate(QStyledItemDelegate):
    """Custom delegate for model combobox with right-aligned multiplier."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = get_colors()
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint item with model name left-aligned and multiplier right-aligned."""
        painter.save()
        
        # Get colors
        colors = self._colors
        
        # Draw background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(colors.interactive_primary))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(colors.bg_elevated))
        else:
            painter.fillRect(option.rect, QColor(colors.bg_tertiary))
        
        # Get data
        display_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        multiplier = index.data(Qt.ItemDataRole.UserRole + 1)  # Store multiplier separately
        
        # Parse multiplier from display text if not stored separately
        if multiplier is None and "  (" in display_text:
            # Extract from "Model Name  (0.33x)" format
            parts = display_text.rsplit("  (", 1)
            if len(parts) == 2:
                display_text = parts[0]
                multiplier = parts[1].rstrip(")")
        
        # Text rect with padding
        rect = option.rect.adjusted(12, 0, -12, 0)
        
        # Draw model name (left aligned)
        painter.setPen(QColor(colors.text_primary))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        
        fm = QFontMetrics(font)
        name_rect = QRect(rect.left(), rect.top(), rect.width() - 50, rect.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, display_text)
        
        # Draw multiplier (right aligned, smaller, dimmer)
        if multiplier:
            painter.setPen(QColor(colors.text_tertiary))
            mult_font = painter.font()
            mult_font.setPointSize(10)
            painter.setFont(mult_font)
            
            mult_rect = QRect(rect.right() - 45, rect.top(), 45, rect.height())
            painter.drawText(mult_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(multiplier))
        
        painter.restore()
    
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Return size hint for item."""
        return QSize(200, 32)


class ChatBridge(QObject):
    """
    Bridge class for QWebChannel communication between Python and chat HTML.
    
    JavaScript calls Python slots via bridge.methodName()
    Python calls JavaScript via web_view.page().runJavaScript()
    """
    
    # Signals emitted when JS calls our slots
    web_view_ready = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    @pyqtSlot()
    def onWebViewReady(self):
        """Called when the WebView chat is fully loaded."""
        self.web_view_ready.emit()


class ChatMessageWidget(QFrame):
    """A single chat message bubble with proper alignment (user right, assistant left)."""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.content = content
        self._timestamp = datetime.now()
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()

        # Outer layout to handle alignment
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(4, 2, 4, 2)
        outer_layout.setSpacing(0)

        # Create the bubble frame
        bubble = QFrame()
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Content label (no role label - cleaner look)
        content_label = QLabel(self.content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        # Expanding width to fill bubble, Minimum height for content
        content_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        content_label.setMinimumWidth(50)  # Prevent complete collapse
        content_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_primary};
                background: transparent;
                font-size: 13px;
            }}
        """)
        bubble_layout.addWidget(content_label)
        self._content_label = content_label

        # Timestamp label
        time_str = self._timestamp.strftime("%H:%M")
        time_label = QLabel(time_str)
        time_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                background: transparent;
                font-size: 10px;
            }}
        """)
        bubble_layout.addWidget(time_label)
        self._time_label = time_label

        # Style the bubble based on role
        if self.role == "user":
            # User messages: right aligned, primary color accent
            outer_layout.addStretch()
            outer_layout.addWidget(bubble)
            bubble.setStyleSheet(f"""
                QFrame {{
                    background-color: {colors.interactive_primary};
                    border-radius: {RADIUS.radius_md}px;
                }}
            """)
            content_label.setStyleSheet(f"""
                QLabel {{
                    color: white;
                    background: transparent;
                    font-size: 13px;
                }}
            """)
            time_label.setStyleSheet(f"""
                QLabel {{
                    color: rgba(255, 255, 255, 0.6);
                    background: transparent;
                    font-size: 10px;
                }}
            """)
            time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            # Spacer takes ~15% on left, bubble takes rest
            outer_layout.setStretch(0, 15)  # stretch spacer
            outer_layout.setStretch(1, 85)  # bubble
        else:
            # Assistant messages: left aligned, secondary background
            outer_layout.addWidget(bubble)
            outer_layout.addStretch()
            bubble.setStyleSheet(f"""
                QFrame {{
                    background-color: {colors.bg_secondary};
                    border-radius: {RADIUS.radius_md}px;
                    border: none;
                }}
            """)
            # Bubble takes ~85%, spacer takes ~15%
            outer_layout.setStretch(0, 85)  # bubble
            outer_layout.setStretch(1, 15)  # stretch spacer

        # Main widget fills available width
        self.setStyleSheet("ChatMessageWidget { background: transparent; border: none; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def append_content(self, text: str):
        """Append text to the message content (for streaming)."""
        self.content += text
        self._content_label.setText(self.content)
        self._content_label.adjustSize()
        self.adjustSize()


class ThinkingIndicatorWidget(QFrame):
    """Animated thinking indicator widget - left aligned like assistant messages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dot_count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._setup_ui()
        self._timer.start(400)  # Animation speed

    def _setup_ui(self):
        colors = get_colors()

        # Outer layout for left alignment
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(0)

        # Bubble frame
        bubble = QFrame()
        bubble_layout = QHBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Thinking text with animated dots
        self._thinking_label = QLabel("thinking")
        self._thinking_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 13px;
                font-style: italic;
                background: transparent;
            }}
        """)
        bubble_layout.addWidget(self._thinking_label)

        # Style the bubble
        bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.bg_secondary};
                border-radius: {RADIUS.radius_md}px;
                border: 1px solid {colors.border_muted};
            }}
        """)

        outer_layout.addWidget(bubble)
        outer_layout.addStretch()

        self.setStyleSheet("ThinkingIndicatorWidget { background: transparent; }")

    def _animate(self):
        """Animate the dots."""
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        self._thinking_label.setText(f"thinking{dots}")

    def stop(self):
        """Stop the animation."""
        self._timer.stop()


class ThinkingContentWidget(QFrame):
    """Collapsible widget to show Copilot's reasoning/thinking text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content = ""
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Header row with toggle button
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4)

        # Disclosure triangle
        self._toggle_btn = QPushButton("\u25B6")  # Right triangle (collapsed)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {colors.text_tertiary};
                font-size: 10px;
            }}
            QPushButton:hover {{
                color: {colors.text_secondary};
            }}
        """)
        self._toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self._toggle_btn)

        # Label
        self._header_label = QLabel("Thinking...")
        self._header_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 11px;
                font-style: italic;
                background: transparent;
            }}
        """)
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Collapsible content
        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
        self._content_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                background: rgba(128, 128, 128, 0.1);
                border: 1px solid {colors.border_muted};
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
            }}
        """)
        self._content_label.hide()
        layout.addWidget(self._content_label)

        self.setStyleSheet("ThinkingContentWidget { background: transparent; }")

    def _toggle(self):
        self._expanded = not self._expanded
        self._content_label.setVisible(self._expanded)
        self._toggle_btn.setText("\u25BC" if self._expanded else "\u25B6")

    def append_content(self, text: str):
        """Append thinking text."""
        self._content += text
        self._content_label.setText(self._content)
        # Update header with preview
        preview = self._content[:50].replace("\n", " ")
        if len(self._content) > 50:
            preview += "..."
        self._header_label.setText(f"Thinking: {preview}")

    def set_complete(self):
        """Mark thinking as complete."""
        self._header_label.setText(f"Thought ({len(self._content)} chars)")


class ToolCallWidget(QFrame):
    """Collapsible widget showing all tool calls in a single unified widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: list = []  # [{name, widget, status}]
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Header row - "Pensando..." with toggle
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4)

        # Disclosure triangle
        self._toggle_btn = QPushButton("\u25B6")
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {colors.text_tertiary};
                font-size: 10px;
            }}
            QPushButton:hover {{
                color: {colors.text_secondary};
            }}
        """)
        self._toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self._toggle_btn)

        # Animated dots label
        self._header_label = QLabel("Pensando...")
        self._header_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 11px;
                font-style: italic;
                background: transparent;
            }}
        """)
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Scrollable actions list (hidden by default)
        self._scroll = QScrollArea()
        self._scroll.setMaximumHeight(150)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
        """)
        self._scroll.hide()

        self._actions_container = QWidget()
        self._actions_layout = QVBoxLayout(self._actions_container)
        self._actions_layout.setContentsMargins(20, 4, 4, 4)
        self._actions_layout.setSpacing(2)
        self._scroll.setWidget(self._actions_container)
        layout.addWidget(self._scroll)

        self.setStyleSheet("ToolCallWidget { background: transparent; }")

        # Animation timer for dots
        self._dot_count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate_dots)
        self._timer.start(400)

    def _animate_dots(self):
        """Animate the dots in 'Pensando...' header."""
        if not self._actions:  # Only animate when no actions yet
            return
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        pending = sum(1 for a in self._actions if a.get("status") == "running")
        if pending > 0:
            self._header_label.setText(S.copilot.actions_running.format(count=len(self._actions)))

    def _toggle(self):
        self._expanded = not self._expanded
        self._scroll.setVisible(self._expanded)
        self._toggle_btn.setText("\u25BC" if self._expanded else "\u25B6")

    def add_action(self, tool_name: str, arguments: dict, tool_call_id: str = ""):
        """Add a new action to the list."""
        colors = get_colors()
        
        # Create row for this action
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(4)
        
        # Tool name
        name_label = QLabel(f"<span style='color:#569cd6;font-family:Consolas;'>{tool_name}</span>")
        row_layout.addWidget(name_label)
        
        # Status
        status_label = QLabel(S.copilot.action_running)
        status_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic;")
        row_layout.addWidget(status_label)
        row_layout.addStretch()
        
        self._actions_layout.addWidget(row)
        self._actions.append({
            "name": tool_name,
            "id": tool_call_id,
            "status": "running",
            "row": row,
            "status_label": status_label,
        })
        
        # Update header
        self._header_label.setText(S.copilot.actions_running.format(count=len(self._actions)))

    def update_action(self, tool_name: str, result: str, is_error: bool = False):
        """Update action status to done/error."""
        for action in self._actions:
            if action["name"] == tool_name and action["status"] == "running":
                if is_error:
                    action["status_label"].setText(S.copilot.action_error)
                    action["status_label"].setStyleSheet("color: #f14c4c; font-size: 10px;")
                else:
                    action["status_label"].setText(S.copilot.action_ok)
                    action["status_label"].setStyleSheet("color: #4ec9b0; font-size: 10px;")
                action["status"] = "done" if not is_error else "error"
                break
        
        # Check if all done
        pending = sum(1 for a in self._actions if a.get("status") == "running")
        if pending == 0:
            self._header_label.setText(S.copilot.actions_complete.format(count=len(self._actions)))
            self._timer.stop()

    def set_complete(self):
        """Mark all actions as complete."""
        self._header_label.setText(S.copilot.actions_complete.format(count=len(self._actions)))
        self._timer.stop()


class ChatInputWidget(QTextEdit):
    """Custom text input that sends on Enter (Shift+Enter for newline)."""

    submit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(S.copilot.input_placeholder)
        self.setMaximumHeight(120)
        self.setMinimumHeight(36)
        self.setAcceptRichText(False)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submit_requested.emit()
                return
        super().keyPressEvent(event)


class GhCliInstallWorker(QObject):
    """Worker that installs GitHub CLI using QProcess (non-blocking)."""

    progress = pyqtSignal(str)  # Status message
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._arch = "amd64"

    def run(self):
        """Install GitHub CLI on Ubuntu/Debian using the official repository."""
        import shutil
        import platform
        import subprocess

        try:
            # Check if already installed (race condition guard)
            if shutil.which("gh"):
                self.finished.emit(True, "GitHub CLI is already installed.")
                return

            system = platform.system()
            if system != "Linux":
                self.finished.emit(
                    False,
                    f"Automatic installation is only supported on Linux. "
                    f"Please install manually from https://cli.github.com/"
                )
                return

            # Use pkexec for graphical sudo prompt
            pkexec = shutil.which("pkexec")
            if not pkexec:
                self.finished.emit(
                    False,
                    "pkexec not found. Please install GitHub CLI manually:\n"
                    "https://cli.github.com/"
                )
                return

            self.progress.emit("Downloading GitHub CLI package...")

            # Pre-compute architecture
            try:
                arch_result = subprocess.run(
                    ["dpkg", "--print-architecture"],
                    capture_output=True, text=True, timeout=10,
                )
                self._arch = arch_result.stdout.strip() or "amd64"
            except Exception:
                self._arch = "amd64"

            # Build install script
            setup_script = (
                "set -e && "
                "mkdir -p -m 755 /etc/apt/keyrings && "
                "wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg "
                "| tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null && "
                "chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && "
                f"echo 'deb [arch={self._arch} "
                "signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
                "https://cli.github.com/packages stable main' "
                "| tee /etc/apt/sources.list.d/github-cli.list > /dev/null && "
                "apt-get update -qq && "
                "apt-get install -y gh"
            )

            # Use QProcess for non-blocking execution
            from PyQt6.QtCore import QProcess

            self._process = QProcess(self)
            self._process.finished.connect(self._on_process_finished)
            self._process.errorOccurred.connect(self._on_process_error)

            self._process.start(pkexec, ["bash", "-c", setup_script])

        except Exception as e:
            self.finished.emit(False, str(e))

    def _on_process_finished(self, exit_code, exit_status):
        """Handle QProcess completion."""
        import shutil
        from PyQt6.QtCore import QProcess

        if exit_code == 0:
            # Verify installation
            if shutil.which("gh"):
                self.finished.emit(True, "")
            else:
                self.finished.emit(
                    False,
                    "Installation completed but 'gh' command not found in PATH."
                )
        elif exit_code == 126:
            self.finished.emit(False, "Installation cancelled by user.")
        else:
            stderr = ""
            if self._process:
                stderr = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
            error_msg = stderr.strip() or f"Installation failed (exit code {exit_code})"
            self.finished.emit(False, error_msg[:200])

        self._process = None

    def _on_process_error(self, error):
        """Handle QProcess error."""
        from PyQt6.QtCore import QProcess

        error_messages = {
            QProcess.ProcessError.FailedToStart: "Failed to start pkexec",
            QProcess.ProcessError.Crashed: "Installation process crashed",
            QProcess.ProcessError.Timedout: "Installation timed out",
            QProcess.ProcessError.WriteError: "Write error",
            QProcess.ProcessError.ReadError: "Read error",
            QProcess.ProcessError.UnknownError: "Unknown error",
        }
        msg = error_messages.get(error, "Unknown error")
        self.finished.emit(False, msg)
        self._process = None


class CopilotChatPanel(QWidget):
    """
    Copilot Chat panel - integrates as a dockable panel in DataPyn.

    Provides chat interface with GitHub Copilot, model selection,
    mode selection, and authentication.

    Signals:
        message_sent(str): User sent a message.
        tool_call_requested(str, dict): Tool call requested by Copilot.
        thinking_started(): Copilot started processing.
    """

    message_sent = pyqtSignal(str)
    tool_call_requested = pyqtSignal(str, dict)
    thinking_started = pyqtSignal()

    def __init__(self, copilot_client=None, mcp_server=None, theme_manager=None, parent=None):
        super().__init__(parent)
        self._copilot_client = copilot_client
        self._mcp_server = mcp_server
        self.theme_manager = theme_manager
        self._messages: list = []  # Chat history [{role, content}]
        self._current_stream_id = None  # Tracks current streaming message
        self._current_thinking_widget = None  # Legacy - not used with WebView
        self._current_actions_widget = None  # Legacy - not used with WebView
        self._active_tool_calls: dict = {}  # tool_name -> reference
        self._settings = QSettings("DataPyn", "CopilotChat")
        self._current_session_id = None
        self._gh_install_worker = None
        self._setup_ui()
        self._connect_signals()
        # Restore last session on startup
        QTimer.singleShot(100, self._restore_last_session)

    def set_copilot_client(self, client):
        """Set or update the Copilot client."""
        if self._copilot_client:
            try:
                self._copilot_client.chat_response_chunk.disconnect(self._on_response_chunk)
                self._copilot_client.chat_response_complete.disconnect(self._on_response_complete)
                self._copilot_client.chat_error.disconnect(self._on_chat_error)
                # NOTE: auth_required handled by main_window to avoid duplication
                self._copilot_client.authenticated.disconnect(self._on_authenticated)
                self._copilot_client.auth_failed.disconnect(self._on_auth_failed)
                if hasattr(self._copilot_client, 'tool_called'):
                    self._copilot_client.tool_called.disconnect(self._on_tool_called)
                if hasattr(self._copilot_client, 'tool_result'):
                    self._copilot_client.tool_result.disconnect(self._on_tool_result)
                if hasattr(self._copilot_client, 'thinking'):
                    self._copilot_client.thinking.disconnect(self._on_thinking)
                if hasattr(self._copilot_client, 'models_changed'):
                    self._copilot_client.models_changed.disconnect(self._on_models_changed)
                if hasattr(self._copilot_client, 'auth_started'):
                    self._copilot_client.auth_started.disconnect(self._on_auth_started)
                if hasattr(self._copilot_client, 'gh_not_found'):
                    self._copilot_client.gh_not_found.disconnect(self._on_gh_not_found)
            except (TypeError, RuntimeError):
                pass

        self._copilot_client = client
        if client:
            client.chat_response_chunk.connect(self._on_response_chunk)
            client.chat_response_complete.connect(self._on_response_complete)
            client.chat_error.connect(self._on_chat_error)
            # NOTE: auth_required handled by main_window to avoid duplication
            client.authenticated.connect(self._on_authenticated)
            client.auth_failed.connect(self._on_auth_failed)
            if hasattr(client, 'tool_called'):
                client.tool_called.connect(self._on_tool_called)
            if hasattr(client, 'tool_result'):
                client.tool_result.connect(self._on_tool_result)
            if hasattr(client, 'thinking'):
                client.thinking.connect(self._on_thinking)
            if hasattr(client, 'models_changed'):
                client.models_changed.connect(self._on_models_changed)
            if hasattr(client, 'auth_started'):
                client.auth_started.connect(self._on_auth_started)
            if hasattr(client, 'gh_not_found'):
                client.gh_not_found.connect(self._on_gh_not_found)
            # Pass tool registry from MCP server to client
            if self._mcp_server and hasattr(client, 'set_tool_registry'):
                client.set_tool_registry(self._mcp_server.tool_registry)
            self._update_auth_state()
            # Update model list from client if available
            self._update_models_from_client()

    def set_mcp_server(self, server):
        """Set or update the MCP server reference."""
        self._mcp_server = server
        # Update tool registry in client if available
        if server and self._copilot_client and hasattr(self._copilot_client, 'set_tool_registry'):
            self._copilot_client.set_tool_registry(server.tool_registry)

    def _setup_ui(self):
        """Build the chat panel UI."""
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === Header bar ===
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)

        # Copilot icon + title
        copilot_icon = _load_copilot_icon(colors.text_primary, size=20)
        if copilot_icon:
            icon_label = QLabel()
            icon_label.setPixmap(copilot_icon.pixmap(20, 20))
            header_layout.addWidget(icon_label)

        title_label = QLabel(S.copilot.title)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {colors.text_primary};")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # New chat button
        self._new_chat_btn = QPushButton()
        self._new_chat_btn.setFixedSize(28, 28)
        self._new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_chat_btn.setToolTip("New Chat")
        if HAS_QTAWESOME:
            self._new_chat_btn.setIcon(qta.icon("mdi.plus", color=colors.text_primary))
        else:
            self._new_chat_btn.setText("+")
        self._new_chat_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {colors.border_muted};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        header_layout.addWidget(self._new_chat_btn)

        # Sessions button (history)
        self._sessions_btn = QPushButton()
        self._sessions_btn.setFixedSize(28, 28)
        self._sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_btn.setToolTip("Chat History")
        if HAS_QTAWESOME:
            self._sessions_btn.setIcon(qta.icon("mdi.history", color=colors.text_primary))
        else:
            self._sessions_btn.setText("H")
        self._sessions_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {colors.border_muted};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        header_layout.addWidget(self._sessions_btn)

        # Auth button (no icon, just text showing username or sign-in)
        self._auth_btn = QPushButton(S.copilot.sign_in)
        self._auth_btn.setFixedWidth(90)
        self._auth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self._auth_btn)

        header.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-bottom: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(header)

        # === Messages area (WebView-based) ===
        self._setup_chat_webview()
        layout.addWidget(self._chat_webview, 1)

        # === GitHub CLI install bar (hidden by default) ===
        self._gh_install_widget = QWidget()
        gh_layout = QHBoxLayout(self._gh_install_widget)
        gh_layout.setContentsMargins(10, 8, 10, 8)
        gh_layout.setSpacing(8)

        gh_icon_label = QLabel()
        if HAS_QTAWESOME:
            gh_icon_label.setPixmap(
                qta.icon("mdi.alert-circle-outline", color="#e5c07b").pixmap(20, 20)
            )
        else:
            gh_icon_label.setText("!")
        gh_layout.addWidget(gh_icon_label)

        gh_text = QLabel(S.copilot.gh_cli_not_found.split("\n")[0])
        gh_text.setWordWrap(True)
        gh_text.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        gh_layout.addWidget(gh_text, 1)

        self._gh_install_btn = QPushButton(S.copilot.install_gh_cli)
        self._gh_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gh_install_btn.setFixedHeight(30)
        self._gh_install_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
            }}
        """)
        self._gh_install_btn.clicked.connect(self._install_gh_cli)
        gh_layout.addWidget(self._gh_install_btn)

        self._gh_install_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_muted};
            }}
        """)
        self._gh_install_widget.setVisible(False)
        layout.addWidget(self._gh_install_widget)

        # === Config bar (Model selector only - always uses Agent mode) ===
        config_bar = QWidget()
        config_layout = QHBoxLayout(config_bar)
        config_layout.setContentsMargins(8, 4, 8, 4)
        config_layout.setSpacing(8)

        # Mode is always Agent (hidden) - tools only work in agent mode
        self._mode_combo = None  # Removed - always agent mode

        # Model selector with custom delegate
        self._model_combo = QComboBox()
        self._model_delegate = ModelItemDelegate(self._model_combo)
        self._model_combo.setItemDelegate(self._model_delegate)
        for model in [
            {"id": "gpt-4o", "name": "GPT-4o", "multiplier": "1x"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "multiplier": "0.33x"},
            {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "multiplier": "1x"},
            {"id": "o3-mini", "name": "o3-mini", "multiplier": "1x"},
        ]:
            idx = self._model_combo.count()
            self._model_combo.addItem(model["name"], model["id"])
            self._model_combo.setItemData(idx, model["multiplier"], Qt.ItemDataRole.UserRole + 1)
        self._model_combo.setFixedWidth(220)  # Accommodate model names + multiplier
        self._model_combo.setToolTip(S.copilot.model_tooltip)
        config_layout.addWidget(self._model_combo)

        # Usage label (shows premium requests percentage)
        # Hidden by default - shown when usage data becomes available
        self._usage_label = QLabel("")
        self._usage_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 11px;
                padding: 0 8px;
            }}
        """)
        self._usage_label.setVisible(False)  # Hidden until we have data
        config_layout.addWidget(self._usage_label)

        config_layout.addStretch()

        config_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_muted};
            }}
        """)
        layout.addWidget(config_bar)

        # === Input area ===
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 6, 8, 8)
        input_layout.setSpacing(6)

        self._input = ChatInputWidget()
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_md}px;
                padding: 8px 12px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {colors.interactive_primary};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton()
        self._send_btn.setFixedSize(36, 36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setToolTip(S.copilot.send_tooltip)
        if HAS_QTAWESOME:
            self._send_btn.setIcon(qta.icon("mdi.send", color=colors.text_primary))
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                border: none;
                border-radius: {RADIUS.radius_md}px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
        """)
        input_layout.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)

        # Stop button (hidden by default, shown when loading)
        self._stop_btn = QPushButton()
        self._stop_btn.setFixedSize(36, 36)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setToolTip(S.copilot.stop_tooltip)
        if HAS_QTAWESOME:
            self._stop_btn.setIcon(qta.icon("mdi.stop", color=colors.text_primary))
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.danger};
                border: none;
                border-radius: {RADIUS.radius_md}px;
            }}
            QPushButton:hover {{
                background-color: {colors.danger_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.danger_active};
            }}
        """)
        self._stop_btn.hide()  # Hidden by default
        input_layout.addWidget(self._stop_btn, 0, Qt.AlignmentFlag.AlignBottom)

        input_container.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(input_container)

        # Style combo boxes
        combo_style = f"""
            QComboBox {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                selection-background-color: {colors.interactive_primary};
            }}
        """
        # Mode combo was removed - always agent mode
        self._model_combo.setStyleSheet(combo_style)

        self._auth_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_secondary_hover};
            }}
        """)

    def _get_template_path(self) -> Path:
        """Get path to chat template, handling PyInstaller bundle."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running as PyInstaller bundle
            return Path(sys._MEIPASS) / 'src' / 'ui' / 'components' / 'chat_template.html'
        else:
            # Development mode
            return Path(__file__).parent / 'chat_template.html'

    def _setup_chat_webview(self):
        """Setup the WebView-based chat messages area."""
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtGui import QColor
        
        # Create WebView
        self._chat_webview = QWebEngineView()
        self._chat_webview.setMinimumSize(200, 100)
        self._chat_webview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Set dark background BEFORE loading to avoid white flash
        self._chat_webview.setStyleSheet("background-color: #1e1e1e;")
        self._chat_webview.page().setBackgroundColor(QColor("#1e1e1e"))
        
        # Enable JavaScript
        settings = self._chat_webview.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        
        # Setup QWebChannel for Python <-> JS communication
        self._chat_channel = QWebChannel(self._chat_webview.page())
        self._chat_bridge = ChatBridge(self)
        self._chat_channel.registerObject("bridge", self._chat_bridge)
        self._chat_webview.page().setWebChannel(self._chat_channel)
        
        # Connect bridge signals
        self._chat_bridge.web_view_ready.connect(self._on_webview_ready)
        
        # Track WebView ready state
        self._webview_ready = False
        self._pending_webview_ops = []
        
        # Load the HTML template
        template_path = self._get_template_path()
        if template_path.exists():
            self._chat_webview.setUrl(QUrl.fromLocalFile(str(template_path)))
        else:
            logger.error(f"Chat template not found: {template_path}")
            # Fallback minimal HTML
            self._chat_webview.setHtml("""
                <!DOCTYPE html>
                <html>
                <body style="background:#1e1e1e;color:#ccc;font-family:sans-serif;padding:20px;">
                    <p>Chat template not found. Please check installation.</p>
                </body>
                </html>
            """)
    
    def _on_webview_ready(self):
        """Called when chat WebView is ready."""
        self._webview_ready = True
        
        # Set welcome text from translation
        welcome_title = "GitHub Copilot"
        welcome_msg = S.copilot.welcome_message if hasattr(S.copilot, 'welcome_message') else "Sign in to start chatting."
        self._run_chat_js(f"setWelcomeText({json.dumps(welcome_title)}, {json.dumps(welcome_msg)})")
        
        # Execute pending operations
        for op in self._pending_webview_ops:
            self._run_chat_js(op)
        self._pending_webview_ops.clear()
        
        logger.debug("Chat WebView ready")
    
    def _run_chat_js(self, code: str):
        """Run JavaScript in the chat WebView."""
        if self._webview_ready:
            self._chat_webview.page().runJavaScript(code)
        else:
            self._pending_webview_ops.append(code)

    def _connect_signals(self):
        """Connect internal signals."""
        self._send_btn.clicked.connect(self._on_send)
        self._stop_btn.clicked.connect(self._on_stop)
        self._input.submit_requested.connect(self._on_send)
        self._auth_btn.clicked.connect(self._on_auth_clicked)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._new_chat_btn.clicked.connect(self._on_new_chat)
        self._sessions_btn.clicked.connect(self._on_sessions_clicked)
        
        # Connect to auth service for cross-component updates
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        auth_service.chat_authenticated.connect(self._on_auth_service_chat_updated)
        auth_service.chat_logged_out.connect(self._on_auth_service_chat_logged_out)
        if hasattr(auth_service, 'chat_gh_not_found'):
            auth_service.chat_gh_not_found.connect(self._on_gh_not_found)

    def _on_new_chat(self):
        """Start a new chat session."""
        self._save_current_session()
        self.clear_chat()

    def _on_sessions_clicked(self):
        """Show sessions menu."""
        colors = get_colors()
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 12px;
                color: {colors.text_primary};
            }}
            QMenu::item:selected {{
                background-color: {colors.bg_tertiary};
            }}
        """)

        sessions = self._get_sessions_list()
        if not sessions:
            action = menu.addAction(S.copilot.no_sessions)
            action.setEnabled(False)
        else:
            for session in sessions[:10]:  # Show last 10
                name = session.get("name", "Untitled")[:35]
                session_id = session.get("id", "")

                # Create a widget action with session name and delete button
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(8, 4, 4, 4)
                layout.setSpacing(4)

                label = QLabel(name)
                label.setStyleSheet(f"color: {colors.text_primary}; font-size: 12px;")
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                layout.addWidget(label, 1)

                delete_btn = QPushButton()
                if HAS_QTAWESOME:
                    delete_btn.setIcon(qta.icon("mdi.delete-outline", color=colors.text_tertiary))
                else:
                    delete_btn.setText("x")
                delete_btn.setFixedSize(20, 20)
                delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                delete_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                        border-radius: 2px;
                    }}
                    QPushButton:hover {{
                        background: {colors.bg_tertiary};
                    }}
                """)
                delete_btn.clicked.connect(lambda checked, sid=session_id, m=menu: self._delete_session(sid, m))
                layout.addWidget(delete_btn)

                action = QWidgetAction(menu)
                action.setDefaultWidget(widget)
                # Connect label click to restore session
                def make_click_handler(sid, m):
                    def handler(event):
                        self._restore_session(sid)
                        m.close()
                    return handler
                label.mousePressEvent = make_click_handler(session_id, menu)
                menu.addAction(action)

            menu.addSeparator()

            # Delete all option
            if sessions:
                clear_action = menu.addAction(S.copilot.clear_all)
                clear_action.triggered.connect(self._clear_all_sessions)

        menu.exec(self._sessions_btn.mapToGlobal(self._sessions_btn.rect().bottomLeft()))

    def _delete_session(self, session_id: str, menu: QMenu):
        """Delete a specific session."""
        sessions = self._get_sessions_list()
        sessions = [s for s in sessions if s.get("id") != session_id]
        self._settings.setValue("sessions", json.dumps(sessions))

        # If deleting current session, clear it
        if self._current_session_id == session_id:
            self._current_session_id = ""
            self._settings.setValue("last_session_id", "")

        menu.close()

    def _clear_all_sessions(self):
        """Clear all saved sessions."""
        self._settings.setValue("sessions", "[]")
        self._settings.setValue("last_session_id", "")

    def _set_loading(self, loading: bool):
        """Set loading state - disable input while waiting for response."""
        self._send_btn.setEnabled(not loading)
        self._input.setEnabled(not loading)
        if loading:
            self._send_btn.setToolTip("Waiting for Copilot response...")
            self._send_btn.hide()
            self._stop_btn.show()
        else:
            self._send_btn.setToolTip(S.copilot.send_tooltip)
            self._stop_btn.hide()
            self._send_btn.show()

    def _on_stop(self):
        """Handle stop button - cancel current operation."""
        if self._copilot_client:
            self._copilot_client.cancel()
        self._set_loading(False)
        self._hide_thinking_indicator()
        # Mark any widgets as complete
        if hasattr(self, '_current_thinking_widget') and self._current_thinking_widget:
            self._current_thinking_widget.set_complete()
            self._current_thinking_widget = None
        if hasattr(self, '_current_actions_widget') and self._current_actions_widget:
            self._current_actions_widget.set_complete()
            self._current_actions_widget = None

    def _on_send(self):
        """Handle send button or Enter key."""
        text = self._input.toPlainText().strip()
        if not text:
            return

        self._input.clear()

        # Hide welcome message (done automatically in _add_message via WebView)

        # Add user message
        self._add_message("user", text)

        # Show loading state
        self._set_loading(True)

        # Build system prompt with context
        system_prompt = self._build_system_prompt()

        # Prepare messages for API
        api_messages = [{"role": "system", "content": system_prompt}]
        for msg in self._messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        # Send to Copilot
        if self._copilot_client:
            # Clear any previous assistant widget to ensure fresh response
            self._current_assistant_widget = None
            # Add animated thinking indicator
            self._show_thinking_indicator()
            self.thinking_started.emit()
            self._copilot_client.send_chat(api_messages)
        else:
            self._set_loading(False)
            self._add_message("assistant", S.copilot.not_authenticated)

        self.message_sent.emit(text)

    def _build_system_prompt(self) -> str:
        """Build system prompt with current editor context and available tools."""
        parts = [
            "You are an AI coding assistant in DataPyn, a Python/SQL data analysis IDE.",
            "",
            "## CRITICAL: HOW DATAPYN DATA FLOW WORKS",
            "",
            "### Block Names = Variable Names",
            "Every block has a NAME. When a SQL block executes, the result DataFrame is stored with that name.",
            "",
            "Example:",
            "- Block named 'vendas' with SQL `SELECT * FROM sales` -> Creates DataFrame `vendas`",
            "- Block named 'clientes' with SQL `SELECT * FROM customers` -> Creates DataFrame `clientes`",
            "- Python block can use: `vendas.head()`, `clientes['name']`, `pd.merge(vendas, clientes, ...)`",
            "",
            "### ALWAYS give semantic names to SQL blocks!",
            "- GOOD: name='vendas', name='produtos', name='pedidos'",
            "- BAD: no name (defaults to 'block1', 'block2' which is confusing)",
            "",
            "### Multi-block workflow example:",
            "```",
            "### Block 'vendas' (SQL)",
            "SELECT produto, SUM(valor) as total FROM pedidos GROUP BY produto",
            "",
            "### Block 'grafico' (Python)",
            "import matplotlib.pyplot as plt",
            "# 'vendas' is the DataFrame from the SQL block above!",
            "plt.bar(vendas['produto'], vendas['total'])",
            "plt.title('Vendas por Produto')",
            "plt.show()",
            "```",
            "",
            "## PLANNING FIRST - THINK BEFORE ACTING",
            "Before creating ANY block:",
            "1. Use 'think' tool to plan your approach",
            "2. Determine how many blocks you need (SQL for data, Python for visualization)",
            "3. Choose semantic names for each block",
            "4. Create blocks ONE AT A TIME with proper names",
            "",
            "## VERIFYING RESULTS",
            "After executing a block, use 'get_execution_results' to:",
            "- See the output panel (print statements, logs)",
            "- See the DataFrame in the results grid (preview)",
            "- Verify the execution worked correctly",
            "",
            "## NOTIFYING THE USER",
            "Use 'notify_user' when:",
            "- Task is complete ('Analysis done!', success=True)",
            "- Need user attention ('Please check the chart', success=True)",
            "- Found an issue ('Error in query', success=False)",
            "",
            "## NEVER DELETE BLOCKS",
            "- If you made a mistake, use 'edit_current_block' to FIX it",
            "- NEVER use delete_block unless the user explicitly asks",
            "",
            "## CRITICAL RULES",
            "1. THINK FIRST: Always use 'think' tool before acting",
            "2. NAME BLOCKS: Always provide a semantic 'name' parameter for SQL blocks",
            "3. ONE BLOCK AT A TIME: Create/edit ONE block per tool call",
            "4. VERIFY: Use 'get_execution_results' after execution to check results",
            "5. COMPLETE CODE: Put ENTIRE code in ONE block",
            "6. NO DELETE: Never delete blocks unless explicitly asked",
            "",
            "## MAIN TOOLS",
            "- **think**: ALWAYS use first to plan",
            "- **write_and_run**: Create block with name, write code, execute (most common)",
            "- **create_block**: Create block with name without executing (for multi-block setup)",
            "- **edit_current_block**: Edit the focused block",
            "- **rename_block**: Rename a block (changes the DataFrame variable name)",
            "- **get_execution_results**: See output and DataFrame after execution",
            "- **notify_user**: Show a notification to the user",
            "- **run_all_blocks**: Execute ALL blocks in sequence",
            "",
            "## WORKFLOW",
            "1. 'think' to plan",
            "2. 'write_and_run' with name='dados' to create SQL block",
            "3. 'get_execution_results' to verify",
            "4. 'write_and_run' with name='grafico' to create Python block using 'dados'",
            "5. 'get_execution_results' to verify",
            "6. 'notify_user' when done",
            "",
            "## SUPPORTED LANGUAGES",
            "- **sql**: Database queries -> result stored as DataFrame with block name",
            "- **python**: Data analysis, pandas, matplotlib, numpy, etc.",
            "",
            "## RULES",
            "- ONLY use tools listed below. 'view', 'grep', 'read_file' DO NOT EXIST.",
            "- Respond in the user's language.",
            "",
        ]

        # Add available tools information with descriptions - VERY EXPLICIT
        if self._mcp_server:
            try:
                tools = self._mcp_server.tool_registry.list_tools()
                
                # Highlight the main tools
                parts.append("## PREFERRED TOOLS:")
                parts.append("  - **write_and_run**: Creates block with name, writes code, executes")
                parts.append("  - **edit_current_block**: BEST for editing user's current block")
                parts.append("  - **get_execution_results**: See output and DataFrame after execution")
                parts.append("  - **notify_user**: Alert the user when task is done")
                parts.append("")
                
                parts.append("## ALL AVAILABLE TOOLS:")
                tool_info = []
                for t in tools:
                    name = t.get("name", "")
                    desc = t.get("description", "")
                    tool_info.append(f"  - {name}: {desc}")
                parts.extend(tool_info)
                parts.append("")
                parts.append(f"Total: {len(tools)} tools available")
                parts.append("")
            except Exception as e:
                logger.debug(f"Error listing tools: {e}")

        # Add context from MCP if available
        if self._mcp_server:
            # Get editor context (blocks, session info)
            try:
                context_result = self._mcp_server.tool_registry.execute("get_context", {})
                if "content" in context_result:
                    context_text = context_result["content"][0].get("text", "")
                    if context_text and context_text != "{}":
                        parts.append(f"## Current Editor Context:\n```json\n{context_text}\n```")
            except Exception as e:
                logger.debug(f"Error getting editor context: {e}")

            # Get database schema if connected
            try:
                schema_result = self._mcp_server.tool_registry.execute("read_schema", {})
                if "content" in schema_result:
                    schema_text = schema_result["content"][0].get("text", "")
                    if schema_text and "No schema" not in schema_text:
                        parts.append(f"## Database Schema:\n{schema_text}")
            except Exception as e:
                logger.debug(f"Error getting schema: {e}")

        return "\n".join(parts)

    def _add_message(self, role: str, content: str):
        """Add a message to the chat."""
        self._messages.append({"role": role, "content": content})

        # Generate unique ID for this message
        msg_id = f"msg_{len(self._messages)}_{id(content) % 10000}"
        
        # Add message via WebView JS
        role_js = "error" if role == "assistant" and content.startswith("Error:") else role
        content_escaped = json.dumps(content)
        self._run_chat_js(f"addMessage({json.dumps(role_js)}, {content_escaped}, {json.dumps(msg_id)})")
        
        # Hide welcome on first message
        self._run_chat_js("hideWelcome()")

    def _scroll_to_bottom(self):
        """Scroll the messages area to the bottom via WebView."""
        self._run_chat_js("scrollToBottom()")

    def _on_response_chunk(self, chunk: str):
        """Handle streaming response chunk."""
        # Hide thinking indicator on first chunk
        self._hide_thinking_indicator()
        
        if self._current_stream_id:
            # Stream to existing message
            chunk_escaped = json.dumps(chunk)
            self._run_chat_js(f"streamChunk({chunk_escaped})")
        else:
            # Start a new streaming message
            self._messages.append({"role": "assistant", "content": chunk})
            self._current_stream_id = f"stream_{len(self._messages)}"
            self._run_chat_js("startStreaming()")
            chunk_escaped = json.dumps(chunk)
            self._run_chat_js(f"streamChunk({chunk_escaped})")

    def _on_response_complete(self, full_text: str):
        """Handle complete response."""
        self._set_loading(False)
        self._hide_thinking_indicator()
        
        # End streaming in WebView
        self._run_chat_js("endStreaming()")
        
        # End tool group (mark as complete)
        self._run_chat_js("endToolGroup()")
        
        # Mark thinking widget as complete (legacy - not used with WebView)
        if self._current_thinking_widget:
            self._current_thinking_widget = None
        
        # Mark actions widget as complete (legacy - not used with WebView)
        if self._current_actions_widget:
            self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        if not self._current_stream_id:
            self._add_message("assistant", full_text)
        else:
            # Update the last message content in history
            if self._messages and self._messages[-1]["role"] == "assistant":
                self._messages[-1]["content"] = full_text
        self._current_stream_id = None
        
        # Auto-save session after each exchange
        self._save_current_session()

    def _on_chat_error(self, error: str):
        """Handle chat error."""
        self._set_loading(False)
        self._hide_thinking_indicator()
        
        # End any streaming
        self._run_chat_js("endStreaming()")
        self._current_stream_id = None
        
        # End tool group (mark as complete)
        self._run_chat_js("endToolGroup()")
        
        # Mark widgets as complete (legacy)
        self._current_thinking_widget = None
        self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        self._add_message("assistant", f"Error: {error}")

    def _show_thinking_indicator(self):
        """Show the animated thinking indicator via WebView."""
        self._run_chat_js("showThinking()")

    def _hide_thinking_indicator(self):
        """Hide the thinking indicator via WebView."""
        self._run_chat_js("hideThinking()")

    def _on_tool_called(self, tool_name: str, arguments: dict, tool_call_id: str = ""):
        """Handle tool call from Copilot - show in WebView."""
        logger.info(f"Tool called: {tool_name}({arguments})")
        
        # Show tool use in WebView
        tool_name_escaped = json.dumps(tool_name)
        self._run_chat_js(f"addToolUse({tool_name_escaped})")
        
        # Track by name for later result update
        self._active_tool_calls[tool_name] = True
        
        # Emit signal for external listeners (output panel)
        self.tool_call_requested.emit(tool_name, arguments)

    def _on_tool_result(self, tool_name: str, result: str):
        """Handle tool execution result."""
        logger.info(f"Tool result: {tool_name} -> {result[:100]}...")
        
        # Update tool status in WebView
        is_error = "error" in result.lower()[:100]
        tool_name_escaped = json.dumps(tool_name)
        self._run_chat_js(f"updateToolStatus({tool_name_escaped}, 'done', {str(is_error).lower()})")

    def _on_thinking(self, text: str):
        """Handle reasoning/thinking text from Copilot."""
        if not text.strip():
            return
        
        logger.debug(f"Thinking: {text[:50]}...")
        # Thinking is handled via showThinking/hideThinking in WebView
        # The actual thinking text is not displayed in WebView (keeping it simple)

    def _on_models_changed(self, models: list):
        """Handle dynamic model list update from SDK."""
        if not models:
            return
        current_model = self._model_combo.currentData()
        self._model_combo.clear()
        for model in models:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)
            multiplier = model.get("multiplier", 1.0)
            # Format multiplier: show as "0.33x", "1x", "2x" etc.
            if multiplier is not None:
                if multiplier == int(multiplier):
                    mult_str = f"{int(multiplier)}x"
                else:
                    mult_str = f"{multiplier:.2g}x"
            else:
                mult_str = "1x"
            
            idx = self._model_combo.count()
            self._model_combo.addItem(model_name, model_id)
            self._model_combo.setItemData(idx, mult_str, Qt.ItemDataRole.UserRole + 1)
        # Restore selection if possible
        if current_model:
            idx = self._model_combo.findData(current_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

    def _on_auth_clicked(self):
        """Handle auth button click."""
        # Use centralized auth service
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        if auth_service.is_chat_authenticated:
            # Show menu with options
            colors = get_colors()
            menu = QMenu(self)
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {colors.bg_secondary};
                    border: 1px solid {colors.border_default};
                    border-radius: 4px;
                    padding: 4px;
                }}
                QMenu::item {{
                    padding: 6px 12px;
                    color: {colors.text_primary};
                }}
                QMenu::item:selected {{
                    background-color: {colors.bg_tertiary};
                }}
            """)

            # Show subscription
            subscription_action = menu.addAction(S.copilot.show_subscription)
            subscription_action.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl("https://github.com/settings/copilot"))
            )

            menu.addSeparator()

            # Logout
            logout_action = menu.addAction(S.copilot.logout)
            logout_action.triggered.connect(self._do_logout)

            menu.exec(self._auth_btn.mapToGlobal(self._auth_btn.rect().bottomLeft()))
            return

        # Start login via centralized auth service
        if auth_service.login_chat():
            self._auth_btn.setText(S.copilot.signing_in)
            self._auth_btn.setEnabled(False)
        else:
            logger.info("Chat login blocked - auth already in progress")

    def _do_logout(self):
        """Perform logout via centralized auth service."""
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        auth_service.logout_chat()
        self._update_auth_state()
        self._usage_label.setVisible(False)
        # Also update legacy setting
        self._settings.setValue("was_authenticated", "false")
        # Reset model combo to defaults
        self._model_combo.clear()
        for model in [
            {"id": "gpt-4o", "name": "GPT-4o", "multiplier": "1x"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "multiplier": "0.33x"},
            {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "multiplier": "1x"},
            {"id": "o3-mini", "name": "o3-mini", "multiplier": "1x"},
        ]:
            idx = self._model_combo.count()
            self._model_combo.addItem(model["name"], model["id"])
            self._model_combo.setItemData(idx, model["multiplier"], Qt.ItemDataRole.UserRole + 1)

    def _on_auth_required(self, user_code: str, verification_uri: str):
        """Show authentication instructions to the user."""
        # Device code flow - show code to user
        # NOTE: Browser is opened by main_window._on_lsp_auth_required
        # Do NOT open browser here to avoid duplication
        self._add_message(
            "assistant",
            S.copilot.auth_instructions.format(code=user_code, url=verification_uri),
        )
        # Copy code to clipboard
        QApplication.clipboard().setText(user_code)

    def _on_auth_started(self, message: str):
        """Authentication process started - show info to user."""
        self._add_message("assistant", message)
        self._auth_btn.setText(S.copilot.signing_in)
        self._auth_btn.setEnabled(False)

    def _on_authenticated(self, info: str):
        """Authentication succeeded."""
        self._update_auth_state()
        self._add_message("assistant", S.copilot.auth_success)
        # Save auth state using centralized settings manager
        username = getattr(self._copilot_client, "_username", "") if self._copilot_client else ""
        get_copilot_settings().on_chat_authenticated(username)
        # Also keep legacy setting for backwards compatibility
        self._settings.setValue("was_authenticated", True)

    def _on_auth_failed(self, error: str):
        """Authentication failed."""
        self._auth_btn.setText(S.copilot.sign_in)
        self._auth_btn.setEnabled(True)
        self._add_message("assistant", S.copilot.auth_failed.format(error=error))

    def _on_gh_not_found(self):
        """GitHub CLI not found - show install widget and message."""
        self._auth_btn.setText(S.copilot.sign_in)
        self._auth_btn.setEnabled(True)
        self._gh_install_widget.setVisible(True)
        self._add_message("assistant", S.copilot.gh_cli_not_found)

    def _install_gh_cli(self):
        """Start GitHub CLI installation (non-blocking via QProcess)."""
        self._gh_install_btn.setEnabled(False)
        self._gh_install_btn.setText(S.copilot.installing_gh_cli)
        self._add_message("assistant", S.copilot.installing_gh_cli)

        # GhCliInstallWorker uses QProcess internally - no QThread needed
        self._gh_install_worker = GhCliInstallWorker(self)
        self._gh_install_worker.progress.connect(
            lambda msg: self._add_message("assistant", msg)
        )
        self._gh_install_worker.finished.connect(self._on_gh_install_finished)

        # Start the installation (non-blocking)
        self._gh_install_worker.run()

    def _on_gh_install_finished(self, success: bool, message: str):
        """Handle GitHub CLI installation result."""
        if success:
            self._add_message("assistant", S.copilot.gh_cli_installed)
            self._gh_install_widget.setVisible(False)
        else:
            self._add_message(
                "assistant",
                S.copilot.gh_cli_install_failed.format(error=message),
            )
            self._gh_install_btn.setEnabled(True)
            self._gh_install_btn.setText(S.copilot.install_gh_cli)

        # Cleanup worker
        self._gh_install_worker = None

    def _update_auth_state(self):
        """Update UI based on authentication state."""
        if self._copilot_client and self._copilot_client.is_authenticated:
            # Get username from client
            username = getattr(self._copilot_client, "_username", None)
            if username:
                self._auth_btn.setText(f"@{username}")
                self._auth_btn.setToolTip(S.copilot.click_to_sign_out)
            else:
                self._auth_btn.setText(S.copilot.connected)
                self._auth_btn.setToolTip(S.copilot.click_to_sign_out)
            self._auth_btn.setEnabled(True)
        else:
            self._auth_btn.setText(S.copilot.sign_in)
            self._auth_btn.setToolTip(S.copilot.sign_in_tooltip)
            self._auth_btn.setEnabled(True)

    def _on_auth_service_chat_updated(self, username: str):
        """Handle chat auth state change from auth service (e.g., login via Settings)."""
        self._update_auth_state()
        # Update models if available
        self._update_models_from_client()

    def _on_auth_service_chat_logged_out(self):
        """Handle chat logout from auth service (e.g., logout via Settings)."""
        self._update_auth_state()
        self._usage_label.setVisible(False)

    def _update_models_from_client(self):
        """Update model combo box from client's available models."""
        if not self._copilot_client:
            return

        try:
            models = self._copilot_client.available_models()
            if models and len(models) > 0:
                current_model = self._model_combo.currentData()
                self._model_combo.clear()
                for model in models:
                    model_id = model.get("id", "")
                    model_name = model.get("name", model_id)
                    multiplier = model.get("multiplier", 1.0)
                    # Format multiplier
                    if multiplier is not None:
                        if multiplier == int(multiplier):
                            mult_str = f"{int(multiplier)}x"
                        else:
                            mult_str = f"{multiplier:.2g}x"
                    else:
                        mult_str = "1x"
                    
                    idx = self._model_combo.count()
                    self._model_combo.addItem(model_name, model_id)
                    self._model_combo.setItemData(idx, mult_str, Qt.ItemDataRole.UserRole + 1)
                # Restore selection if possible
                if current_model:
                    idx = self._model_combo.findData(current_model)
                    if idx >= 0:
                        self._model_combo.setCurrentIndex(idx)
        except Exception as e:
            logger.debug(f"Could not update models from client: {e}")

    def _on_model_changed(self, index: int):
        """Handle model selection change."""
        model_id = self._model_combo.currentData()
        if model_id and self._copilot_client:
            self._copilot_client.model = model_id

    def set_theme_manager(self, theme_manager):
        """Set theme manager for dynamic theming."""
        self.theme_manager = theme_manager

    def clear_chat(self):
        """Clear all messages."""
        self._messages.clear()
        # Clear messages in WebView
        self._run_chat_js("clearMessages()")
        self._current_stream_id = None
        self._current_session_id = None

    # === Session Persistence ===

    def _get_sessions_list(self) -> list:
        """Get list of saved chat sessions."""
        sessions_json = self._settings.value("sessions", "[]")
        try:
            return json.loads(sessions_json)
        except Exception:
            return []

    def _save_sessions_list(self, sessions: list):
        """Save list of chat sessions."""
        self._settings.setValue("sessions", json.dumps(sessions))

    def _save_current_session(self):
        """Save the current chat session."""
        if not self._messages:
            return

        import uuid
        from datetime import datetime

        session_id = self._current_session_id or str(uuid.uuid4())[:8]
        self._current_session_id = session_id

        # Generate session name from first user message or timestamp
        session_name = datetime.now().strftime("%d/%m %H:%M")
        for msg in self._messages:
            if msg["role"] == "user":
                session_name = msg["content"][:40] + ("..." if len(msg["content"]) > 40 else "")
                break

        sessions = self._get_sessions_list()

        # Update existing or add new
        existing_idx = None
        for i, s in enumerate(sessions):
            if s.get("id") == session_id:
                existing_idx = i
                break

        session_data = {
            "id": session_id,
            "name": session_name,
            "timestamp": datetime.now().isoformat(),
            "messages": self._messages.copy(),
        }

        if existing_idx is not None:
            sessions[existing_idx] = session_data
        else:
            # Insert at beginning (most recent)
            sessions.insert(0, session_data)

        # Keep only last 20 sessions
        sessions = sessions[:20]
        self._save_sessions_list(sessions)

        # Save as last session
        self._settings.setValue("last_session_id", session_id)

    def _restore_last_session(self):
        """Restore the last chat session on startup."""
        last_id = self._settings.value("last_session_id", "")
        if last_id:
            self._restore_session(last_id)
        # Note: Auto-auth is now handled by CopilotAuthService.trigger_auto_auth()

    def _restore_session(self, session_id: str):
        """Restore a specific chat session."""
        sessions = self._get_sessions_list()
        for session in sessions:
            if session.get("id") == session_id:
                self.clear_chat()
                self._current_session_id = session_id
                messages = session.get("messages", [])
                for msg in messages:
                    self._add_message(msg["role"], msg["content"])
                # Welcome is auto-hidden when messages are added
                return True
        return False

    # Note: _try_auto_auth removed - CopilotAuthService handles auto-auth centrally

    def _on_authenticated_save(self):
        """Save authentication state when authenticated."""
        self._settings.setValue("was_authenticated", "true")

    def new_chat_session(self):
        """Start a new chat session."""
        # Save current session first
        self._save_current_session()
        self.clear_chat()
        self._current_session_id = None

    def get_saved_sessions(self) -> list:
        """Get list of saved sessions for UI display."""
        return self._get_sessions_list()
