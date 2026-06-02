"""
Log Detail Dialog - Rich view of a single log entry.

Shows timestamp, duration, block info, code snippet, full error/traceback,
and action buttons (Copy Error, Resolve with Copilot).
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QWidget, QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from src.design_system.tokens import get_colors, RADIUS, SCROLLBAR_STYLE
from src.language import S

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class LogDetailDialog(QDialog):
    """Full detail view for a single LogEntry."""

    resolve_requested = pyqtSignal(dict)  # context dict for Copilot

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._setup_ui()

    def _setup_ui(self):
        from src.ui.components.output_panel import LogEntry
        colors = get_colors()
        entry = self._entry

        self.setWindowTitle(S.output_panel.dialog_log_detail)
        self.resize(780, 520)
        self.setMinimumSize(500, 300)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- Header info bar ---
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-radius: {RADIUS}px;
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 8, 12, 8)
        h_layout.setSpacing(16)

        level_colors = {
            "info": colors.info,
            "success": colors.success,
            "warning": colors.warning,
            "error": colors.danger,
            "debug": colors.text_tertiary,
        }
        lcolor = level_colors.get(entry.level, colors.info)

        # Level badge
        level_label = QLabel(entry.level.upper())
        level_label.setStyleSheet(f"""
            QLabel {{
                background-color: {lcolor}30;
                color: {lcolor};
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 3px;
            }}
        """)
        h_layout.addWidget(level_label)

        # Timestamp
        ts_label = QLabel(entry.timestamp.strftime("%H:%M:%S"))
        ts_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 12px; font-family: Consolas;")
        h_layout.addWidget(ts_label)

        # Block info
        if entry.block_index is not None:
            block_text = entry.block_name or f"Block {entry.block_index + 1}"
            if entry.line_number is not None:
                if entry.column_number:
                    block_text += f" : L{entry.line_number}:{entry.column_number}"
                else:
                    block_text += f" : L{entry.line_number}"
            block_label = QLabel(block_text)
            block_label.setStyleSheet(f"color: {lcolor}; font-size: 12px; font-weight: bold; font-family: Consolas;")
            h_layout.addWidget(block_label)

        # Connection
        if entry.connection_name:
            conn_text = entry.connection_name
            if entry.database_name:
                conn_text += f" / {entry.database_name}"
            conn_label = QLabel(conn_text)
            conn_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
            h_layout.addWidget(conn_label)

        h_layout.addStretch()

        # Duration
        if entry.duration_ms is not None:
            from src.ui.components.output_panel import OutputPanel
            dur_text = OutputPanel._format_duration(entry.duration_ms)
            dur_label = QLabel(dur_text)
            dur_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 12px; font-family: Consolas;")
            h_layout.addWidget(dur_label)

        layout.addWidget(header)

        # --- Code snippet (if present) ---
        if entry.code_snippet:
            code_header = QLabel(S.output_panel.detail_code)
            code_header.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: bold;")
            layout.addWidget(code_header)

            code_edit = QTextEdit()
            code_edit.setReadOnly(True)
            code_edit.setFont(QFont("Consolas", 10))
            code_edit.setPlainText(entry.code_snippet)
            code_edit.setMaximumHeight(150)
            code_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {colors.bg_secondary};
                    color: {colors.text_primary};
                    border: 1px solid {colors.border_default};
                    border-radius: {RADIUS}px;
                    padding: 8px;
                }}
                {SCROLLBAR_STYLE}
            """)
            layout.addWidget(code_edit)

        # --- Error / detail text ---
        detail_text = entry.detail or entry.message
        if detail_text:
            detail_header_text = (
                S.output_panel.detail_error
                if entry.level == "error"
                else S.output_panel.detail_output
            )
            detail_header = QLabel(detail_header_text)
            detail_header.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: bold;")
            layout.addWidget(detail_header)

            detail_edit = QTextEdit()
            detail_edit.setReadOnly(True)
            detail_edit.setFont(QFont("Consolas", 10))
            detail_edit.setPlainText(detail_text)
            detail_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {colors.bg_secondary};
                    color: {lcolor};
                    border: 1px solid {colors.border_default};
                    border-radius: {RADIUS}px;
                    padding: 8px;
                }}
                {SCROLLBAR_STYLE}
            """)
            layout.addWidget(detail_edit, 1)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # Copy button
        copy_btn = QPushButton(S.output_panel.btn_copy_detail)
        if HAS_QTAWESOME:
            copy_btn.setIcon(qta.icon("mdi.content-copy", color=colors.text_primary))
        copy_btn.setStyleSheet(self._btn_style(colors))
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(detail_text))
        btn_row.addWidget(copy_btn)

        # Resolve with Copilot (only for errors)
        if entry.level == "error":
            label = getattr(S.output_panel, "btn_resolve_pynia", S.output_panel.btn_resolve_copilot)
            copilot_btn = QPushButton(label)
            try:
                from src.ui.components.copilot_chat_panel import _load_copilot_icon
                copilot_icon = _load_copilot_icon("#ffffff", size=16)
                if copilot_icon:
                    copilot_btn.setIcon(copilot_icon)
            except Exception:
                if HAS_QTAWESOME:
                    copilot_btn.setIcon(qta.icon("mdi.github", color="#ffffff"))
            copilot_btn.setStyleSheet(self._btn_style(colors, accent=True))
            copilot_btn.clicked.connect(self._on_resolve_copilot)
            btn_row.addWidget(copilot_btn)

        btn_row.addStretch()

        # Close
        close_btn = QPushButton(S.output_panel.btn_close_detail)
        close_btn.setStyleSheet(self._btn_style(colors))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _on_resolve_copilot(self):
        entry = self._entry
        context = {
            "block_index": entry.block_index,
            "block_name": entry.block_name,
            "code": entry.code_snippet,
            "error": entry.detail or entry.message,
            "log_type": entry.log_type,
            "connection": entry.connection_name,
            "database": entry.database_name,
        }
        self.resolve_requested.emit(context)
        self.accept()

    @staticmethod
    def _btn_style(colors, accent=False):
        bg = colors.interactive_primary if accent else colors.bg_elevated
        fg = "#ffffff" if accent else colors.text_primary
        hover = colors.interactive_primary_hover if accent else colors.bg_secondary
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS}px;
                padding: 6px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
        """
