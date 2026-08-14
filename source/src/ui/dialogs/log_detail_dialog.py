"""
Log Detail Dialog - Rich view of a single log entry (frameless design system).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from src.design_system.button import GhostButton, PrimaryButton, SecondaryButton
from src.design_system.frameless_dialog import (
    frameless_body_stylesheet,
    install_frameless_shell,
)
from src.design_system.tokens import RADIUS, SCROLLBAR_STYLE, TYPOGRAPHY, get_colors
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class LogDetailDialog(QDialog):
    """Full detail view for a single LogEntry."""

    resolve_requested = pyqtSignal(dict)

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._detail_text = entry.detail or entry.message or ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        colors = get_colors()
        entry = self._entry

        self.setWindowTitle(S.output_panel.dialog_log_detail)
        self.resize(780, 520)

        layout = install_frameless_shell(
            self,
            S.output_panel.dialog_log_detail,
            min_width=500,
            min_height=300,
            content_margins=(20, 14, 20, 16),
            content_spacing=12,
            resizable=True,
        )
        self.setStyleSheet(
            self.styleSheet() + frameless_body_stylesheet()
        )

        level_colors = {
            "info": colors.info,
            "success": colors.success,
            "warning": colors.warning,
            "error": colors.danger,
            "debug": colors.text_tertiary,
        }
        lcolor = level_colors.get(entry.level, colors.info)

        layout.addWidget(self._build_header(entry, lcolor, colors))

        if entry.code_snippet:
            layout.addWidget(self._section_label(S.output_panel.detail_code, colors))
            layout.addWidget(self._code_area(entry.code_snippet, colors))

        if self._detail_text:
            header = (
                S.output_panel.detail_error
                if entry.level == "error"
                else S.output_panel.detail_output
            )
            layout.addWidget(self._section_label(header, colors))
            layout.addWidget(self._detail_area(self._detail_text, lcolor, colors), 1)

        layout.addLayout(self._build_footer(entry, colors))

    def _build_header(self, entry, lcolor: str, colors) -> QWidget:
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 8, 12, 8)
        h_layout.setSpacing(16)

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

        ts_label = QLabel(entry.timestamp.strftime("%H:%M:%S"))
        ts_label.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 12px; font-family: Consolas;"
        )
        h_layout.addWidget(ts_label)

        if entry.block_index is not None:
            block_text = entry.block_name or f"Block {entry.block_index + 1}"
            if entry.line_number is not None:
                if entry.column_number:
                    block_text += f" : L{entry.line_number}:{entry.column_number}"
                else:
                    block_text += f" : L{entry.line_number}"
            block_label = QLabel(block_text)
            block_label.setStyleSheet(
                f"color: {lcolor}; font-size: 12px; font-weight: bold; font-family: Consolas;"
            )
            h_layout.addWidget(block_label)

        if entry.connection_name:
            conn_text = entry.connection_name
            if entry.database_name:
                conn_text += f" / {entry.database_name}"
            conn_label = QLabel(conn_text)
            conn_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
            h_layout.addWidget(conn_label)

        h_layout.addStretch()

        if entry.duration_ms is not None:
            from src.ui.components.output_panel import OutputPanel

            dur_label = QLabel(OutputPanel._format_duration(entry.duration_ms))
            dur_label.setStyleSheet(
                f"color: {colors.text_tertiary}; font-size: 12px; font-family: Consolas;"
            )
            h_layout.addWidget(dur_label)

        return header

    @staticmethod
    def _section_label(text: str, colors) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {colors.text_secondary};"
            f" font-size: {TYPOGRAPHY.text_xs}px; font-weight: 600;"
        )
        return label

    @staticmethod
    def _text_area_style(colors, *, text_color: str | None = None) -> str:
        fg = text_color or colors.text_primary
        return f"""
            QTextEdit {{
                background-color: {colors.bg_secondary};
                color: {fg};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 8px;
            }}
            {SCROLLBAR_STYLE}
        """

    def _code_area(self, text: str, colors) -> QTextEdit:
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setFont(QFont("Consolas", 10))
        edit.setPlainText(text)
        edit.setMaximumHeight(150)
        edit.setStyleSheet(self._text_area_style(colors))
        return edit

    def _detail_area(self, text: str, lcolor: str, colors) -> QTextEdit:
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setFont(QFont("Consolas", 10))
        edit.setPlainText(text)
        edit.setStyleSheet(self._text_area_style(colors, text_color=lcolor))
        return edit

    def _build_footer(self, entry, colors) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(8)

        close_btn = GhostButton(S.output_panel.btn_close_detail, size="sm")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)

        footer.addStretch()

        copy_btn = SecondaryButton(S.output_panel.btn_copy_detail, size="sm")
        if HAS_QTAWESOME:
            copy_btn.setIcon(qta.icon("mdi.content-copy", color=colors.text_primary))
        copy_btn.clicked.connect(self._copy_detail)
        footer.addWidget(copy_btn)

        if entry.level == "error":
            label = getattr(
                S.output_panel, "btn_resolve_pynia", S.output_panel.btn_resolve_copilot
            )
            resolve_btn = PrimaryButton(label, size="sm")
            try:
                from src.assets.pynia_branding import load_pynia_logo

                pynia_icon = load_pynia_logo(16)
                if pynia_icon:
                    resolve_btn.setIcon(pynia_icon)
            except Exception:
                if HAS_QTAWESOME:
                    resolve_btn.setIcon(qta.icon("mdi.creation", color="#ffffff"))
            resolve_btn.clicked.connect(self._on_resolve_copilot)
            footer.addWidget(resolve_btn)

        return footer

    def _copy_detail(self) -> None:
        entry = self._entry
        parts = []
        if entry.code_snippet:
            parts.append(entry.code_snippet)
        if self._detail_text:
            parts.append(self._detail_text)
        QApplication.clipboard().setText("\n\n".join(parts) if parts else entry.message)

    def _on_resolve_copilot(self) -> None:
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
