"""
Copilot Chat Panel - Chat interface for GitHub Copilot integration.

This panel functions as a dockable block in DataPyn, similar to
Variables, Object Explorer, etc. It provides:
- Chat message display
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
    QScrollArea,
    QFrame,
    QSizePolicy,
    QApplication,
    QMenu,
    QWidgetAction,
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer, QSettings, QByteArray
from PyQt6.QtGui import QFont, QDesktopServices, QKeyEvent, QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
import json
import logging
import os
import re
from datetime import datetime

from src.language import S
from src.design_system.tokens import get_colors, RADIUS

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
        self._current_assistant_widget = None
        self._thinking_indicator = None  # Animated thinking indicator
        self._current_thinking_widget = None  # Collapsible thinking content
        self._current_actions_widget = None  # Unified widget for all tool calls
        self._active_tool_calls: dict = {}  # tool_name -> widget reference
        self._settings = QSettings("DataPyn", "CopilotChat")
        self._current_session_id = None
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
                self._copilot_client.auth_required.disconnect(self._on_auth_required)
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
            except (TypeError, RuntimeError):
                pass

        self._copilot_client = client
        if client:
            client.chat_response_chunk.connect(self._on_response_chunk)
            client.chat_response_complete.connect(self._on_response_complete)
            client.chat_error.connect(self._on_chat_error)
            client.auth_required.connect(self._on_auth_required)
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

        # === Messages area ===
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._messages_container = QWidget()
        # Expanding width to fill viewport, Minimum height to fit content
        self._messages_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(8, 8, 8, 8)
        self._messages_layout.setSpacing(8)
        self._messages_layout.addStretch()

        self._scroll_area.setWidget(self._messages_container)
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {colors.bg_primary};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {colors.bg_primary};
            }}
        """)
        layout.addWidget(self._scroll_area, 1)

        # === Welcome message (shown when empty) ===
        self._welcome_label = QLabel(S.copilot.welcome_message)
        self._welcome_label.setWordWrap(True)
        self._welcome_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._welcome_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._welcome_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 13px;
                padding: 40px 20px;
                background: transparent;
            }}
        """)
        # Insert before the stretch, centered horizontally
        self._messages_layout.insertWidget(0, self._welcome_label, 0, Qt.AlignmentFlag.AlignHCenter)

        # === Config bar (Model selector only - always uses Agent mode) ===
        config_bar = QWidget()
        config_layout = QHBoxLayout(config_bar)
        config_layout.setContentsMargins(8, 4, 8, 4)
        config_layout.setSpacing(8)

        # Mode is always Agent (hidden) - tools only work in agent mode
        self._mode_combo = None  # Removed - always agent mode

        # Model selector
        self._model_combo = QComboBox()
        for model in [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
            {"id": "o3-mini", "name": "o3-mini"},
        ]:
            self._model_combo.addItem(model["name"], model["id"])
        self._model_combo.setFixedWidth(140)
        self._model_combo.setToolTip(S.copilot.model_tooltip)
        config_layout.addWidget(self._model_combo)

        # Usage label (shows premium requests percentage)
        self._usage_label = QLabel(S.copilot.usage_loading)
        self._usage_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 11px;
                padding: 0 8px;
            }}
        """)
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

    def _connect_signals(self):
        """Connect internal signals."""
        self._send_btn.clicked.connect(self._on_send)
        self._stop_btn.clicked.connect(self._on_stop)
        self._input.submit_requested.connect(self._on_send)
        self._auth_btn.clicked.connect(self._on_auth_clicked)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._new_chat_btn.clicked.connect(self._on_new_chat)
        self._sessions_btn.clicked.connect(self._on_sessions_clicked)

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

        # Hide welcome message
        self._welcome_label.hide()

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

        widget = ChatMessageWidget(role, content)
        # Insert before the stretch at the end
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, widget)

        # NOTE: Do NOT set _current_assistant_widget here!
        # That is only for streaming responses, handled in _on_response_chunk

        # Scroll to bottom
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll the messages area to the bottom with delay for layout update."""
        # Delay scroll to allow layout to update first
        QTimer.singleShot(50, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self):
        """Actually perform the scroll."""
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_response_chunk(self, chunk: str):
        """Handle streaming response chunk."""
        # Hide thinking indicator on first chunk
        self._hide_thinking_indicator()
        
        if self._current_assistant_widget:
            self._current_assistant_widget.append_content(chunk)
            self._scroll_to_bottom()
        else:
            # Create new assistant message widget for streaming
            self._messages.append({"role": "assistant", "content": chunk})
            widget = ChatMessageWidget("assistant", chunk)
            count = self._messages_layout.count()
            self._messages_layout.insertWidget(count - 1, widget)
            self._current_assistant_widget = widget
            self._scroll_to_bottom()

    def _on_response_complete(self, full_text: str):
        """Handle complete response."""
        self._set_loading(False)
        self._hide_thinking_indicator()
        
        # Mark thinking widget as complete
        if self._current_thinking_widget:
            self._current_thinking_widget.set_complete()
            self._current_thinking_widget = None
        
        # Mark actions widget as complete
        if self._current_actions_widget:
            self._current_actions_widget.set_complete()
            self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        if not self._current_assistant_widget:
            self._add_message("assistant", full_text)
        else:
            # Update the last message content in history
            if self._messages and self._messages[-1]["role"] == "assistant":
                self._messages[-1]["content"] = full_text
        self._current_assistant_widget = None
        self._scroll_to_bottom()
        # Auto-save session after each exchange
        self._save_current_session()

    def _on_chat_error(self, error: str):
        """Handle chat error."""
        self._set_loading(False)
        self._hide_thinking_indicator()
        
        # Mark thinking widget as complete on error too
        if self._current_thinking_widget:
            self._current_thinking_widget.set_complete()
            self._current_thinking_widget = None
        
        # Mark actions widget as complete on error
        if self._current_actions_widget:
            self._current_actions_widget.set_complete()
            self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        self._add_message("assistant", f"Error: {error}")
        self._current_assistant_widget = None

    def _show_thinking_indicator(self):
        """Show the animated thinking indicator."""
        self._hide_thinking_indicator()  # Remove any existing
        self._thinking_indicator = ThinkingIndicatorWidget()
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, self._thinking_indicator)
        self._scroll_to_bottom()

    def _hide_thinking_indicator(self):
        """Hide and remove the thinking indicator."""
        if self._thinking_indicator:
            self._thinking_indicator.stop()
            idx = self._messages_layout.indexOf(self._thinking_indicator)
            if idx >= 0:
                self._messages_layout.takeAt(idx)
            self._thinking_indicator.deleteLater()
            self._thinking_indicator = None

    def _on_tool_called(self, tool_name: str, arguments: dict, tool_call_id: str = ""):
        """Handle tool call from Copilot - add to unified actions widget."""
        logger.info(f"Tool called: {tool_name}({arguments})")
        
        # Use single unified widget for all tool calls
        if not hasattr(self, '_current_actions_widget') or self._current_actions_widget is None:
            self._current_actions_widget = ToolCallWidget()
            count = self._messages_layout.count()
            self._messages_layout.insertWidget(count - 1, self._current_actions_widget)
        
        # Add action to the widget
        self._current_actions_widget.add_action(tool_name, arguments, tool_call_id)
        
        # Track by name for later result update
        self._active_tool_calls[tool_name] = self._current_actions_widget
        
        # Auto-scroll to show tool call
        QTimer.singleShot(50, self._scroll_to_bottom)
        
        # Emit signal for external listeners (output panel)
        self.tool_call_requested.emit(tool_name, arguments)

    def _on_tool_result(self, tool_name: str, result: str):
        """Handle tool execution result - update the actions widget."""
        logger.info(f"Tool result: {tool_name} -> {result[:100]}...")
        
        # Update the unified widget
        if hasattr(self, '_current_actions_widget') and self._current_actions_widget:
            is_error = "error" in result.lower()[:50]
            self._current_actions_widget.update_action(tool_name, result, is_error)

    def _on_thinking(self, text: str):
        """Handle reasoning/thinking text from Copilot - show in collapsible widget."""
        if not text.strip():
            return
        
        logger.debug(f"Thinking: {text[:50]}...")
        
        # Create or update thinking widget
        if not self._current_thinking_widget:
            self._current_thinking_widget = ThinkingContentWidget()
            count = self._messages_layout.count()
            self._messages_layout.insertWidget(count - 1, self._current_thinking_widget)
        
        self._current_thinking_widget.append_content(text)

    def _on_models_changed(self, models: list):
        """Handle dynamic model list update from SDK."""
        if not models:
            return
        current_model = self._model_combo.currentData()
        self._model_combo.clear()
        for model in models:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)
            self._model_combo.addItem(model_name, model_id)
        # Restore selection if possible
        if current_model:
            idx = self._model_combo.findData(current_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

    def _on_auth_clicked(self):
        """Handle auth button click."""
        if self._copilot_client and self._copilot_client.is_authenticated:
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

        if self._copilot_client:
            self._copilot_client.start_auth()
            self._auth_btn.setText(S.copilot.signing_in)
            self._auth_btn.setEnabled(False)

    def _do_logout(self):
        """Perform logout."""
        if self._copilot_client:
            self._copilot_client.sign_out()
            self._update_auth_state()
            self._usage_label.setText(S.copilot.usage_loading)

    def _on_auth_required(self, user_code: str, verification_uri: str):
        """Show authentication instructions to the user."""
        # Device code flow - show code and open browser
        self._add_message(
            "assistant",
            S.copilot.auth_instructions.format(code=user_code, url=verification_uri),
        )
        # Copy code to clipboard
        QApplication.clipboard().setText(user_code)
        # Open browser
        QDesktopServices.openUrl(QUrl(verification_uri))

    def _on_auth_started(self, message: str):
        """Authentication process started - show info to user."""
        self._add_message("assistant", message)
        self._auth_btn.setText(S.copilot.signing_in)
        self._auth_btn.setEnabled(False)

    def _on_authenticated(self, info: str):
        """Authentication succeeded."""
        self._update_auth_state()
        self._add_message("assistant", S.copilot.auth_success)
        # Save auth state for auto-auth next time
        self._settings.setValue("was_authenticated", True)

    def _on_auth_failed(self, error: str):
        """Authentication failed."""
        self._auth_btn.setText(S.copilot.sign_in)
        self._auth_btn.setEnabled(True)
        self._add_message("assistant", S.copilot.auth_failed.format(error=error))

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
                    self._model_combo.addItem(model_name, model_id)
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
        # Remove all message widgets
        while self._messages_layout.count() > 1:  # Keep the stretch
            item = self._messages_layout.takeAt(0)
            widget = item.widget()
            if widget and widget != self._welcome_label:
                widget.deleteLater()
        self._welcome_label.show()
        self._current_assistant_widget = None
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
        # Also try auto-auth if previously authenticated
        QTimer.singleShot(500, self._try_auto_auth)

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
                if messages:
                    self._welcome_label.hide()
                return True
        return False

    def _delete_session(self, session_id: str):
        """Delete a saved chat session."""
        sessions = self._get_sessions_list()
        sessions = [s for s in sessions if s.get("id") != session_id]
        self._save_sessions_list(sessions)
        if self._current_session_id == session_id:
            self.clear_chat()

    def _try_auto_auth(self):
        """Try to automatically authenticate if previously logged in."""
        # Check if we were previously authenticated
        # QSettings.value() can return various types - normalize to string
        saved_value = self._settings.value("was_authenticated", False)
        was_authenticated = saved_value in (True, "true", "True", 1, "1")
        logger.info(f"Auto-auth check: saved_value={saved_value!r}, was_authenticated={was_authenticated}")
        
        if was_authenticated and self._copilot_client:
            if hasattr(self._copilot_client, "is_authenticated") and not self._copilot_client.is_authenticated:
                logger.info("Attempting auto-authentication...")
                if hasattr(self._copilot_client, "start_auth"):
                    try:
                        self._copilot_client.start_auth()
                    except Exception as e:
                        logger.debug(f"Auto-auth failed: {e}")

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
