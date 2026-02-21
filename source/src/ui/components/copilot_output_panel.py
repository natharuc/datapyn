"""
Copilot Output Panel

Displays Copilot tool calls, responses, and debug information.
Shows what Copilot is doing in real-time.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QColor
from datetime import datetime
import html as html_module
import json

from .buttons import GhostButton

from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class CopilotOutputPanel(QWidget):
    """Panel showing Copilot activity and tool executions."""

    cleared = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Configure UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(5, 3, 5, 3)
        toolbar_layout.setSpacing(5)

        toolbar_layout.addStretch()

        # Clear button
        self.btn_clear = GhostButton(S.output_panel.btn_clear)
        if HAS_QTAWESOME:
            self.btn_clear.setIcon(qta.icon("fa5s.trash", color="#888888"))
        self.btn_clear.clicked.connect(self.clear)
        toolbar_layout.addWidget(self.btn_clear)

        toolbar.setStyleSheet("""
            QWidget {
                background-color: #222225;
                border: none;
                border-bottom: 1px solid #28282c;
            }
        """)
        layout.addWidget(toolbar)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)

    def _apply_theme(self):
        """Apply theme."""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {"background": "#1a1a1c", "foreground": "#e0e0e4"}

        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                padding: 12px;
                font-size: 12px;
                line-height: 1.4;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Set theme manager."""
        self.theme_manager = theme_manager
        self._apply_theme()

    def clear(self):
        """Clear all output."""
        self.text_edit.clear()
        self.cleared.emit()

    def _timestamp(self) -> str:
        """Get current timestamp."""
        return datetime.now().strftime("%H:%M:%S")

    def _append_html(self, html: str):
        """Append HTML content and scroll to bottom."""
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html + "<br>")
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()

    def log_info(self, message: str):
        """Log an info message."""
        ts = self._timestamp()
        escaped = html_module.escape(message)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#e0e0e4;">{escaped}</span>'
        )

    def log_tool_call(self, tool_name: str, arguments: dict):
        """Log a tool call from Copilot."""
        ts = self._timestamp()
        args_str = json.dumps(arguments, indent=2, ensure_ascii=False) if arguments else "{}"
        escaped_args = html_module.escape(args_str)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#569cd6;font-weight:bold;">TOOL</span> '
            f'<span style="color:#dcdcaa;">{html_module.escape(tool_name)}</span>'
            f'<pre style="color:#9cdcfe;margin:2px 0 2px 20px;font-size:11px;">{escaped_args}</pre>'
        )

    def log_tool_result(self, tool_name: str, result: str, is_error: bool = False):
        """Log a tool result."""
        ts = self._timestamp()
        color = "#f14c4c" if is_error else "#4ec9b0"
        label = "ERROR" if is_error else "RESULT"
        escaped = html_module.escape(result[:500])  # Truncate long results
        if len(result) > 500:
            escaped += "..."
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">{label}</span> '
            f'<span style="color:#dcdcaa;">{html_module.escape(tool_name)}</span>: '
            f'<span style="color:#e0e0e4;">{escaped}</span>'
        )

    def log_thinking(self):
        """Log that Copilot is thinking."""
        ts = self._timestamp()
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#c586c0;">Copilot is thinking...</span>'
        )

    def log_response_start(self):
        """Log that Copilot started responding."""
        ts = self._timestamp()
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#4ec9b0;">Generating response...</span>'
        )

    def log_response_complete(self):
        """Log that Copilot finished responding."""
        ts = self._timestamp()
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#4ec9b0;">Response complete.</span>'
        )

    def log_error(self, error: str):
        """Log an error."""
        ts = self._timestamp()
        escaped = html_module.escape(error)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#f14c4c;font-weight:bold;">ERROR</span> '
            f'<span style="color:#f14c4c;">{escaped}</span>'
        )

    def log_auth_status(self, status: str, success: bool = True):
        """Log authentication status."""
        ts = self._timestamp()
        color = "#4ec9b0" if success else "#f14c4c"
        escaped = html_module.escape(status)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">AUTH</span> '
            f'<span style="color:#e0e0e4;">{escaped}</span>'
        )
