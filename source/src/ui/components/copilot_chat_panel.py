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
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
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


class ModelActivationWidget(QFrame):
    """Widget to display model activation requirements."""

    # Signal emitted when user clicks Enable
    enable_requested = pyqtSignal(str)  # model_id

    def __init__(self, model_id: str, terms: str, activation_command: str, parent=None):
        super().__init__(parent)
        self.model_id = model_id
        self.terms = terms
        self.activation_command = activation_command
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title = QLabel(f"Enable {self.model_id}?")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {colors.text_primary}; background: transparent;")
        layout.addWidget(title)

        # Terms description
        terms_label = QLabel(self.terms)
        terms_label.setWordWrap(True)
        terms_label.setStyleSheet(f"color: {colors.text_secondary}; background: transparent;")
        layout.addWidget(terms_label)

        # Note about enabling
        note_label = QLabel(
            "Enabling this model will allow it to be used across all your Copilot clients."
        )
        note_label.setWordWrap(True)
        note_label.setStyleSheet(f"color: {colors.text_tertiary}; background: transparent; font-style: italic; margin-top: 4px;")
        layout.addWidget(note_label)

        # Buttons container
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 12, 0, 0)
        btn_layout.setSpacing(12)

        # Enable button
        self._enable_btn = QPushButton("Yes, enable this model")
        self._enable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enable_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: {RADIUS.radius_md}px;
                padding: 10px 20px;
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
        self._enable_btn.clicked.connect(self._on_enable_clicked)
        btn_layout.addWidget(self._enable_btn)

        # Cancel/pick different model button
        cancel_btn = QPushButton("No, pick a different model")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_md}px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()
        layout.addWidget(btn_container)

        # Status label (hidden initially)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {colors.text_tertiary}; background: transparent; font-style: italic;")
        self._status_label.hide()
        layout.addWidget(self._status_label)

        self.setStyleSheet(f"""
            ModelActivationWidget {{
                background-color: {colors.bg_secondary};
                border-radius: {RADIUS.radius_md}px;
                border: 1px solid {colors.border_default};
            }}
        """)

    def _on_enable_clicked(self):
        """Handle enable button click - open terminal with command."""
        import subprocess
        import os

        # Copy command to clipboard
        QApplication.clipboard().setText(self.activation_command)

        # Show status
        self._enable_btn.setEnabled(False)
        self._status_label.setText("Command copied to clipboard! Opening terminal...")
        self._status_label.show()

        # Open terminal with the command ready to run
        try:
            if os.name == 'nt':  # Windows
                # Use cmd to start PowerShell - more reliable
                cmd = f'start powershell -NoExit -Command "Write-Host \'Paste and run this command (already copied to clipboard):\' -ForegroundColor Green; Write-Host \'{self.activation_command}\' -ForegroundColor Yellow; Write-Host \'\' "'
                subprocess.Popen(cmd, shell=True)
            else:  # Linux/Mac
                subprocess.Popen(['gnome-terminal', '--', 'bash', '-c', f'echo "Run: {self.activation_command}"; exec bash'], start_new_session=True)
        except Exception as e:
            logger.warning(f"Could not open terminal: {e}")
            # Show manual instructions
            self._status_label.setText(f"Command copied! Open a terminal and paste: {self.activation_command}")

        # Update status
        QTimer.singleShot(2000, lambda: self._update_status_after_open())

    def _update_status_after_open(self):
        """Update status after terminal opens."""
        self._status_label.setText("Command copied! After running it in terminal and enabling, select the model again.")
        self._enable_btn.setEnabled(True)
        self._enable_btn.setText("Copy command again")

    def _on_cancel_clicked(self):
        """Handle cancel button click - just remove the widget."""
        self.setParent(None)
        self.deleteLater()

    def set_status(self, status: str, success: bool = True):
        """Update status message."""
        colors = get_colors()
        if success:
            color = getattr(colors, 'status_success', '#4CAF50')  # Green fallback
        else:
            color = getattr(colors, 'status_error', '#F44336')  # Red fallback
        self._status_label.setStyleSheet(f"color: {color}; background: transparent;")
        self._status_label.setText(status)
        self._status_label.show()

    def enable_buttons(self):
        """Re-enable buttons after operation."""
        self._enable_btn.setEnabled(True)
        self._enable_btn.setText("Yes, enable this model")


class AuthCodeWidget(QFrame):
    """Widget to display authentication code with copy button."""

    def __init__(self, user_code: str, verification_uri: str, parent=None):
        super().__init__(parent)
        self.user_code = user_code
        self.verification_uri = verification_uri
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Instructions
        instructions = QLabel(S.copilot.auth_code_instructions)
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {colors.text_primary}; background: transparent;")
        layout.addWidget(instructions)

        # Code display with copy button
        code_container = QWidget()
        code_layout = QHBoxLayout(code_container)
        code_layout.setContentsMargins(0, 8, 0, 8)
        code_layout.setSpacing(8)

        code_label = QLabel(self.user_code)
        code_font = QFont("Consolas", 18)
        code_font.setBold(True)
        code_label.setFont(code_font)
        code_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.interactive_primary};
                background-color: {colors.bg_tertiary};
                padding: 12px 20px;
                border-radius: {RADIUS.radius_md}px;
                letter-spacing: 4px;
            }}
        """)
        code_layout.addWidget(code_label)

        copy_btn = QPushButton(S.copilot.copy_code)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: {RADIUS.radius_md}px;
                padding: 12px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
        """)
        copy_btn.clicked.connect(self._copy_code)
        code_layout.addWidget(copy_btn)

        code_layout.addStretch()
        layout.addWidget(code_container)

        # Link to verification URL
        link_label = QLabel(f'<a href="{self.verification_uri}" style="color: {colors.interactive_primary};">{self.verification_uri}</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet(f"color: {colors.text_secondary}; background: transparent;")
        layout.addWidget(link_label)

        # Status
        status_label = QLabel(S.copilot.waiting_auth)
        status_label.setStyleSheet(f"color: {colors.text_tertiary}; background: transparent; font-style: italic;")
        layout.addWidget(status_label)

        self.setStyleSheet(f"""
            AuthCodeWidget {{
                background-color: {colors.bg_secondary};
                border-radius: {RADIUS.radius_md}px;
                border: 1px solid {colors.border_default};
            }}
        """)

    def _copy_code(self):
        """Copy code to clipboard and show feedback."""
        QApplication.clipboard().setText(self.user_code)
        # Visual feedback - change button text temporarily
        sender = self.sender()
        if sender:
            original_text = sender.text()
            sender.setText(S.copilot.code_copied)
            sender.setEnabled(False)
            # Restore after 2 seconds
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._restore_copy_button(sender, original_text))

    def _restore_copy_button(self, button, original_text):
        """Restore copy button to original state."""
        try:
            button.setText(original_text)
            button.setEnabled(True)
        except RuntimeError:
            pass  # Widget may have been deleted


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
        self._auth_code_widget = None  # Auth code widget reference
        self._activation_widget = None  # Model activation widget reference
        self._is_processing = False  # Flag to prevent multiple sends
        self._thinking_widget = None  # Thinking indicator widget
        self._thinking_timer = None  # Animation timer
        self._thinking_label = None  # Thinking text label
        self._thinking_dots = 0  # Animation state
        self._setup_ui()
        self._connect_signals()

    def set_copilot_client(self, client):
        """Set or update the Copilot client."""
        if self._copilot_client:
            try:
                self._copilot_client.chat_response_chunk.disconnect(self._on_response_chunk)
                self._copilot_client.chat_response_complete.disconnect(self._on_response_complete)
                self._copilot_client.chat_error.disconnect(self._on_chat_error)
                self._copilot_client.authenticated.disconnect(self._on_authenticated)
                self._copilot_client.auth_failed.disconnect(self._on_auth_failed)
                self._copilot_client.models_updated.disconnect(self._on_models_updated)
                # auth_required is only available in legacy client
                if hasattr(self._copilot_client, 'auth_required'):
                    self._copilot_client.auth_required.disconnect(self._on_auth_required)
            except (TypeError, RuntimeError):
                pass

        self._copilot_client = client
        if client:
            client.chat_response_chunk.connect(self._on_response_chunk)
            client.chat_response_complete.connect(self._on_response_complete)
            client.chat_error.connect(self._on_chat_error)
            client.authenticated.connect(self._on_authenticated)
            client.auth_failed.connect(self._on_auth_failed)
            client.models_updated.connect(self._on_models_updated)
            # Connect to model activation signals
            if hasattr(client, 'model_activation_required'):
                client.model_activation_required.connect(self._on_model_activation_required)
            if hasattr(client, 'model_activated'):
                client.model_activated.connect(self._on_model_activated)
            # auth_required is only available in legacy client
            if hasattr(client, 'auth_required'):
                client.auth_required.connect(self._on_auth_required)
            self._update_auth_state()
            # Update models from client
            self._populate_models()
            # Auto-check authentication in background
            if not client.is_authenticated:
                QTimer.singleShot(100, client.start_auth)

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
        self._populate_models()
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

        # Prevent sending while processing
        if self._is_processing:
            return

        self._input.clear()

        # Hide welcome message
        self._welcome_label.hide()

        # Add user message
        self._add_message("user", text)

        # Set processing state
        self._set_processing(True)

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
            self._set_processing(False)

        self.message_sent.emit(text)

    def _set_processing(self, processing: bool):
        """Set the processing state and update UI accordingly."""
        self._is_processing = processing

        # Only disable send button, allow typing in input field
        self._send_btn.setEnabled(not processing)

        if processing:
            # Show thinking indicator
            self._show_thinking_indicator()
        else:
            # Remove thinking indicator
            self._hide_thinking_indicator()

    def _show_thinking_indicator(self):
        """Show a thinking indicator while waiting for response."""
        if self._thinking_widget:
            return

        self._thinking_widget = QWidget()
        layout = QHBoxLayout(self._thinking_widget)
        layout.setContentsMargins(12, 8, 12, 8)

        # Animated dots label
        self._thinking_label = QLabel("Copilot is thinking")
        self._thinking_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._thinking_label)
        layout.addStretch()

        # Start animation timer
        self._thinking_dots = 0
        self._thinking_timer = QTimer(self)
        self._thinking_timer.timeout.connect(self._update_thinking_animation)
        self._thinking_timer.start(500)

        # Insert before stretch
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, self._thinking_widget)
        self._scroll_to_bottom()

    def _update_thinking_animation(self):
        """Update the thinking animation dots."""
        if not self._thinking_label:
            return
        self._thinking_dots = (self._thinking_dots + 1) % 4
        dots = "." * self._thinking_dots
        self._thinking_label.setText(f"Copilot is thinking{dots}")

    def _hide_thinking_indicator(self):
        """Hide the thinking indicator."""
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None

        if self._thinking_widget:
            self._thinking_widget.setParent(None)
            self._thinking_widget.deleteLater()
            self._thinking_widget = None
            self._thinking_label = None

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
        logger.debug(f"Received chunk: {chunk[:50] if chunk else 'empty'}...")

        # Remove thinking indicator on first chunk
        self._hide_thinking_indicator()

        if not chunk:
            return

        if self._current_assistant_widget:
            self._current_assistant_widget.append_content(chunk)
            self._scroll_to_bottom()
        else:
            self._add_message("assistant", chunk)

    def _on_response_complete(self, full_text: str):
        """Handle complete response."""
        logger.info(f"Response complete: {len(full_text) if full_text else 0} chars")

        # Reset processing state
        self._set_processing(False)

        if not full_text:
            logger.warning("Empty response received")
            self._current_assistant_widget = None
            return

        if self._current_assistant_widget:
            # Response was already added via streaming chunks
            if self._messages and self._messages[-1]["role"] == "assistant":
                self._messages[-1]["content"] = full_text
        else:
            # No streaming happened, add the complete message now
            self._add_message("assistant", full_text)

        self._current_assistant_widget = None

    def _on_chat_error(self, error: str):
        """Handle chat error."""
        # Reset processing state
        self._set_processing(False)

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
        """Show the device code to the user with copy button."""
        # Hide welcome message
        self._welcome_label.hide()

        # Remove any existing auth widget
        if hasattr(self, '_auth_code_widget') and self._auth_code_widget:
            self._auth_code_widget.setParent(None)
            self._auth_code_widget.deleteLater()
            self._auth_code_widget = None

        # Add auth code widget
        self._auth_code_widget = AuthCodeWidget(user_code, verification_uri)
        count = self._messages_layout.count()
        self._messages_layout.insertWidget(count - 1, self._auth_code_widget)

        # Scroll to bottom
        self._scroll_to_bottom()

        # Open browser automatically
        QDesktopServices.openUrl(QUrl(verification_uri))

    def _on_authenticated(self, info: str):
        """Authentication succeeded."""
        # Remove auth code widget if present
        if hasattr(self, '_auth_code_widget') and self._auth_code_widget:
            self._auth_code_widget.setParent(None)
            self._auth_code_widget.deleteLater()
            self._auth_code_widget = None

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

    def _populate_models(self):
        """Populate model combo with available models."""
        # Default models if no client
        from src.services.copilot.copilot_client import DEFAULT_COPILOT_MODELS

        models = DEFAULT_COPILOT_MODELS
        if self._copilot_client:
            models = self._copilot_client.available_models()

        current_model = self._model_combo.currentData() if self._model_combo.count() > 0 else None

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in models:
            self._model_combo.addItem(model["name"], model["id"])

        # Restore previous selection if possible
        if current_model:
            idx = self._model_combo.findData(current_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

        self._model_combo.blockSignals(False)

    def _on_models_updated(self, models: list):
        """Handle models list update from Copilot API."""
        current_model = self._model_combo.currentData() if self._model_combo.count() > 0 else None

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in models:
            self._model_combo.addItem(model["name"], model["id"])

        # Restore previous selection if possible
        if current_model:
            idx = self._model_combo.findData(current_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

        self._model_combo.blockSignals(False)

    def _on_model_changed(self, index: int):
        """Handle model selection change."""
        model_id = self._model_combo.currentData()
        if model_id and self._copilot_client:
            # Use set_model which checks for activation requirement
            if hasattr(self._copilot_client, 'set_model'):
                self._copilot_client.set_model(model_id)
            else:
                self._copilot_client.model = model_id

    def _on_model_activation_required(self, model_id: str, terms: str):
        """Handle model that requires activation."""
        # Create activation dialog widget
        self._show_model_activation_dialog(model_id, terms)

        # Revert to previous model
        current_model = self._copilot_client.model if self._copilot_client else "gpt-4.1"
        idx = self._model_combo.findData(current_model)
        if idx >= 0:
            self._model_combo.blockSignals(True)
            self._model_combo.setCurrentIndex(idx)
            self._model_combo.blockSignals(False)

    def _show_model_activation_dialog(self, model_id: str, terms: str):
        """Show dialog explaining how to activate a model."""
        try:
            # Hide welcome message
            self._welcome_label.hide()

            # Remove any existing activation widget
            if hasattr(self, '_activation_widget') and self._activation_widget:
                try:
                    self._activation_widget.setParent(None)
                    self._activation_widget.deleteLater()
                except RuntimeError:
                    pass
                self._activation_widget = None

            # Get activation command
            activation_command = f"copilot --model {model_id}"
            if self._copilot_client:
                try:
                    activation_command = self._copilot_client.get_model_activation_command(model_id)
                except Exception:
                    pass

            # Create activation widget
            self._activation_widget = ModelActivationWidget(
                model_id,
                terms or "Enable access to this model.",
                activation_command
            )

            # Connect enable request to copilot client
            self._activation_widget.enable_requested.connect(self._on_enable_model_requested)

            # Insert before stretch
            count = self._messages_layout.count()
            self._messages_layout.insertWidget(count - 1, self._activation_widget)
            self._scroll_to_bottom()
        except Exception as e:
            logger.exception(f"Error showing model activation dialog: {e}")

    def _on_enable_model_requested(self, model_id: str):
        """Handle request to enable a model."""
        if self._copilot_client and hasattr(self._copilot_client, 'activate_model'):
            self._copilot_client.activate_model(model_id)
        else:
            # Fallback: show error
            if self._activation_widget:
                self._activation_widget.set_status(
                    "Could not enable model automatically. Please run the command in terminal.",
                    success=False
                )
                self._activation_widget.enable_buttons()

    def _on_model_activated(self, model_id: str, success: bool):
        """Handle model activation result."""
        if self._activation_widget:
            if success:
                self._activation_widget.set_status(
                    f"Model {model_id} enabled successfully! You can now select it.",
                    success=True
                )
                # Auto-remove widget after a delay
                QTimer.singleShot(3000, self._remove_activation_widget)
                # Auto-select the model
                idx = self._model_combo.findData(model_id)
                if idx >= 0:
                    self._model_combo.blockSignals(True)
                    self._model_combo.setCurrentIndex(idx)
                    self._model_combo.blockSignals(False)
                    if self._copilot_client:
                        self._copilot_client.model = model_id
            else:
                self._activation_widget.set_status(
                    "Could not enable model automatically. Please run the command in terminal manually.",
                    success=False
                )
                self._activation_widget.enable_buttons()

    def _remove_activation_widget(self):
        """Remove the activation widget."""
        if self._activation_widget:
            self._activation_widget.setParent(None)
            self._activation_widget.deleteLater()
            self._activation_widget = None

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
