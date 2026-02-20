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
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QDesktopServices, QKeyEvent
import logging

from src.language import S
from src.design_system.tokens import get_colors, RADIUS

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


class ChatMessageWidget(QFrame):
    """A single chat message bubble."""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.content = content
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Role label
        role_label = QLabel("You" if self.role == "user" else "Copilot")
        role_font = QFont()
        role_font.setBold(True)
        role_font.setPointSize(10)
        role_label.setFont(role_font)

        if self.role == "user":
            role_label.setStyleSheet(f"color: {colors.interactive_primary}; background: transparent;")
        else:
            role_label.setStyleSheet(f"color: {colors.success}; background: transparent;")

        layout.addWidget(role_label)

        # Content label
        content_label = QLabel(self.content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        content_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_primary};
                background: transparent;
                font-size: 13px;
                line-height: 1.5;
            }}
        """)
        layout.addWidget(content_label)
        self._content_label = content_label

        # Style the bubble
        if self.role == "user":
            bg = colors.bg_tertiary
        else:
            bg = colors.bg_secondary

        self.setStyleSheet(f"""
            ChatMessageWidget {{
                background-color: {bg};
                border-radius: {RADIUS.radius_md}px;
                border: 1px solid {colors.border_muted};
            }}
        """)

    def append_content(self, text: str):
        """Append text to the message content (for streaming)."""
        self.content += text
        self._content_label.setText(self.content)


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
    """

    message_sent = pyqtSignal(str)
    tool_call_requested = pyqtSignal(str, dict)

    def __init__(self, copilot_client=None, mcp_server=None, theme_manager=None, parent=None):
        super().__init__(parent)
        self._copilot_client = copilot_client
        self._mcp_server = mcp_server
        self.theme_manager = theme_manager
        self._messages: list = []  # Chat history [{role, content}]
        self._current_assistant_widget = None
        self._setup_ui()
        self._connect_signals()

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
            self._update_auth_state()

    def set_mcp_server(self, server):
        """Set or update the MCP server reference."""
        self._mcp_server = server

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
        title_label = QLabel(S.copilot.title)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {colors.text_primary};")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Mode selector
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Chat", "Edit", "Agent"])
        self._mode_combo.setFixedWidth(80)
        self._mode_combo.setToolTip(S.copilot.mode_tooltip)
        header_layout.addWidget(self._mode_combo)

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
        header_layout.addWidget(self._model_combo)

        # Auth button
        self._auth_btn = QPushButton(S.copilot.sign_in)
        self._auth_btn.setFixedWidth(90)
        self._auth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self._auth_btn.setIcon(qta.icon("mdi.github", color=colors.text_primary))
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

        self._messages_container = QWidget()
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
            QWidget {{
                background-color: {colors.bg_primary};
            }}
        """)
        layout.addWidget(self._scroll_area, 1)

        # === Welcome message (shown when empty) ===
        self._welcome_label = QLabel(S.copilot.welcome_message)
        self._welcome_label.setWordWrap(True)
        self._welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 13px;
                padding: 40px 20px;
                background: transparent;
            }}
        """)
        # Insert before the stretch
        self._messages_layout.insertWidget(0, self._welcome_label)

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
        self._mode_combo.setStyleSheet(combo_style)
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
        self._input.submit_requested.connect(self._on_send)
        self._auth_btn.clicked.connect(self._on_auth_clicked)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)

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

        # Build system prompt with context
        system_prompt = self._build_system_prompt()

        # Prepare messages for API
        api_messages = [{"role": "system", "content": system_prompt}]
        for msg in self._messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        # Send to Copilot
        if self._copilot_client:
            self._copilot_client.send_chat(api_messages)
        else:
            self._add_message("assistant", S.copilot.not_authenticated)

        self.message_sent.emit(text)

    def _build_system_prompt(self) -> str:
        """Build system prompt with current editor context."""
        parts = [
            "You are GitHub Copilot integrated with DataPyn, a Python IDE for SQL and data analysis.",
            "You can help with SQL queries, Python code, data analysis, and database operations.",
        ]

        # Add context from MCP if available
        if self._mcp_server:
            context_result = self._mcp_server.tool_registry.execute("get_context", {})
            if "content" in context_result:
                context_text = context_result["content"][0].get("text", "")
                if context_text:
                    parts.append(f"\nCurrent editor context:\n{context_text}")

        return "\n".join(parts)

    def _add_message(self, role: str, content: str):
        """Add a message to the chat."""
        self._messages.append({"role": role, "content": content})

        widget = ChatMessageWidget(role, content)
        # Insert before the stretch at the end
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, widget)

        if role == "assistant":
            self._current_assistant_widget = widget

        # Scroll to bottom
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll the messages area to the bottom."""
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_response_chunk(self, chunk: str):
        """Handle streaming response chunk."""
        if self._current_assistant_widget:
            self._current_assistant_widget.append_content(chunk)
            self._scroll_to_bottom()
        else:
            self._add_message("assistant", chunk)

    def _on_response_complete(self, full_text: str):
        """Handle complete response."""
        if not self._current_assistant_widget:
            self._add_message("assistant", full_text)
        else:
            # Update the last message content in history
            if self._messages and self._messages[-1]["role"] == "assistant":
                self._messages[-1]["content"] = full_text
        self._current_assistant_widget = None

    def _on_chat_error(self, error: str):
        """Handle chat error."""
        self._add_message("assistant", f"Error: {error}")
        self._current_assistant_widget = None

    def _on_auth_clicked(self):
        """Handle auth button click."""
        if self._copilot_client and self._copilot_client.is_authenticated:
            self._copilot_client.sign_out()
            self._update_auth_state()
            return

        if self._copilot_client:
            self._copilot_client.start_auth()
            self._auth_btn.setText(S.copilot.signing_in)
            self._auth_btn.setEnabled(False)

    def _on_auth_required(self, user_code: str, verification_uri: str):
        """Show the device code to the user."""
        self._add_message(
            "assistant",
            S.copilot.auth_instructions.format(code=user_code, url=verification_uri),
        )
        # Copy code to clipboard
        QApplication.clipboard().setText(user_code)
        # Open browser
        QDesktopServices.openUrl(QUrl(verification_uri))

    def _on_authenticated(self, info: str):
        """Authentication succeeded."""
        self._update_auth_state()
        self._add_message("assistant", S.copilot.auth_success)

    def _on_auth_failed(self, error: str):
        """Authentication failed."""
        self._auth_btn.setText(S.copilot.sign_in)
        self._auth_btn.setEnabled(True)
        self._add_message("assistant", S.copilot.auth_failed.format(error=error))

    def _update_auth_state(self):
        """Update UI based on authentication state."""
        if self._copilot_client and self._copilot_client.is_authenticated:
            self._auth_btn.setText(S.copilot.sign_out)
            self._auth_btn.setEnabled(True)
        else:
            self._auth_btn.setText(S.copilot.sign_in)
            self._auth_btn.setEnabled(True)

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
