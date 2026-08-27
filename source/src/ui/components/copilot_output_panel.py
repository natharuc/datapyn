"""
Pynia Output Panel

Displays Pynia tool calls, responses, and debug information.
Shows what Pynia is doing in real-time.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6 import sip
from datetime import datetime
import html as html_module
import json

from .buttons import GhostButton

from src.language import S
from src.design_system.tokens import get_colors, SCROLLBAR_STYLE
from src.design_system.font_manager import get_monospace_font

_RESULT_MAX = 500


def stringify_tool_result(result) -> tuple[str, bool]:
    """Turn a tool payload into truncated text. Dicts from MCP are not slices."""
    is_error = isinstance(result, dict) and bool(result.get("error") or result.get("isError"))
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            text = str(result)
    if len(text) > _RESULT_MAX:
        text = text[:_RESULT_MAX] + "..."
    return text, is_error

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class CopilotOutputPanel(QWidget):
    """Panel showing Pynia activity and tool executions."""

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
        self._toolbar = QWidget()
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(5, 3, 5, 3)
        toolbar_layout.setSpacing(5)

        self._logo_label = QLabel()
        self._logo_label.setFixedSize(20, 20)
        from src.assets.pynia_branding import load_pynia_logo

        logo_icon = load_pynia_logo(20)
        if logo_icon:
            self._logo_label.setPixmap(logo_icon.pixmap(20, 20))
            self._logo_label.setToolTip("Pynia")
        toolbar_layout.addWidget(self._logo_label)

        self._title_label = QLabel(S.dock.pynia_output)
        toolbar_layout.addWidget(self._title_label)

        toolbar_layout.addStretch()

        # Clear button
        self.btn_clear = GhostButton(S.output_panel.btn_clear)
        if HAS_QTAWESOME:
            self.btn_clear.setIcon(qta.icon("fa5s.trash", color="#888888"))
        self.btn_clear.clicked.connect(self.clear)
        toolbar_layout.addWidget(self.btn_clear)

        layout.addWidget(self._toolbar)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(get_monospace_font(10))
        layout.addWidget(self.text_edit)

    def _apply_theme(self):
        """Apply theme."""
        colors = get_colors()
        self._title_label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; font-weight: 600;"
        )
        self._toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_tertiary};
                border: none;
                border-bottom: 1px solid {colors.border_muted};
            }}
        """)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: none;
                padding: 12px;
                font-size: 12px;
                line-height: 1.4;
            }}
            {SCROLLBAR_STYLE}
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
        # Guard against deleted C++ object
        if sip.isdeleted(self.text_edit):
            return
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
        """Log a tool call from Pynia."""
        ts = self._timestamp()
        try:
            args_str = json.dumps(arguments, indent=2, ensure_ascii=False, default=str) if arguments else "{}"
        except Exception:
            args_str = str(arguments)
        escaped_args = html_module.escape(args_str)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#569cd6;font-weight:bold;">TOOL</span> '
            f'<span style="color:#dcdcaa;">{html_module.escape(str(tool_name))}</span>'
            f'<pre style="color:#9cdcfe;margin:2px 0 2px 20px;font-size:11px;">{escaped_args}</pre>'
        )

    def log_tool_result(self, tool_name: str, result, is_error: bool = False):
        """Log a tool result (string or MCP dict)."""
        ts = self._timestamp()
        text, inferred_error = stringify_tool_result(result)
        is_error = is_error or inferred_error
        color = "#f14c4c" if is_error else "#4ec9b0"
        label = "ERROR" if is_error else "RESULT"
        escaped = html_module.escape(text)
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">{label}</span> '
            f'<span style="color:#dcdcaa;">{html_module.escape(str(tool_name))}</span>: '
            f'<span style="color:#e0e0e4;">{escaped}</span>'
        )

    def log_thinking(self):
        """Log that Pynia is thinking."""
        ts = self._timestamp()
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#c586c0;">Pynia is thinking...</span>'
        )

    def log_response_start(self):
        """Log that Pynia started responding."""
        ts = self._timestamp()
        self._append_html(
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:#4ec9b0;">Generating response...</span>'
        )

    def log_response_complete(self):
        """Log that Pynia finished responding."""
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
