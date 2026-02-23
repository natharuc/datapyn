"""
Output/Logs Panel

Displays log messages, command output, and errors.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QDialog, QDialogButtonBox
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from datetime import datetime
import html as html_module

from .buttons import IconButton, GhostButton

from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class OutputPanel(QWidget):
    """Output/logs panel with formatting"""

    # Signals
    cleared = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Configure UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Output toolbar
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(5, 3, 5, 3)
        toolbar_layout.setSpacing(5)

        toolbar_layout.addStretch()

        # Clear button
        self.btn_clear = GhostButton(S.output_panel.btn_clear)
        if HAS_QTAWESOME:
            from src.design_system.tokens import get_colors
            colors = get_colors()
            self.btn_clear.setIcon(qta.icon("fa5s.trash", color=colors.text_tertiary))
        self.btn_clear.clicked.connect(self.clear)
        toolbar_layout.addWidget(self.btn_clear)

        # Copy button
        self.btn_copy = GhostButton(S.output_panel.btn_copy)
        if HAS_QTAWESOME:
            self.btn_copy.setIcon(qta.icon("fa5s.copy", color=colors.text_tertiary))
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        toolbar_layout.addWidget(self.btn_copy)

        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border: none;
                border-bottom: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(toolbar)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 10))
        self.text_edit.mouseDoubleClickEvent = self._on_double_click
        layout.addWidget(self.text_edit)

    def _apply_theme(self):
        """Apply theme"""
        from src.design_system.tokens import get_colors
        tokens = get_colors()
        
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {"background": tokens.bg_primary, "foreground": tokens.text_primary}

        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                padding: 12px;
                font-size: 13px;
                line-height: 1.5;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Set theme manager"""
        self.theme_manager = theme_manager
        self._apply_theme()

    def append(self, text: str, level: str = "info"):
        """Add text to output

        Args:
            text: Text to add
            level: Level ('info', 'success', 'warning', 'error')
        """
        from src.design_system.tokens import get_colors
        tokens = get_colors()
        
        timestamp = datetime.now().strftime("%H:%M:%S")

        colors = {"info": tokens.info, "success": tokens.success, "warning": tokens.warning, "error": tokens.danger, "debug": tokens.text_tertiary}
        color = colors.get(level, colors["info"])

        # Icons by level
        icons = {"info": "", "success": S.output_panel.level_ok, "warning": S.output_panel.level_warning, "error": S.output_panel.level_error, "debug": S.output_panel.level_debug}
        icon = icons.get(level, "")

        # Escape HTML and convert \n to <br> to preserve formatting
        safe_text = html_module.escape(text).replace("\n", "<br>")

        if icon:
            html = f'<span style="color: {tokens.text_tertiary};">[{timestamp}]</span> <span style="color: {color};">{icon} {safe_text}</span><br>'
        else:
            html = f'<span style="color: {tokens.text_tertiary};">[{timestamp}]</span> <span style="color: {color};">{safe_text}</span><br>'

        self.text_edit.append(html)

        # Scroll to end
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    def append_output(self, text: str, error: bool = False):
        """Compatibility method with old code"""
        level = "error" if error else "info"
        self.append(text, level)

    def log(self, text: str):
        """Add info log"""
        self.append(text, "info")

    def success(self, text: str):
        """Add success log"""
        self.append(text, "success")

    def warning(self, text: str):
        """Add warning log"""
        self.append(text, "warning")

    def error(self, text: str):
        """Add error log"""
        self.append(text, "error")

    def debug(self, text: str):
        """Adiciona log de debug"""
        self.append(text, "debug")

    def _on_double_click(self, event):
        """Abre dialogo com log formatado ao dar duplo-clique"""
        cursor = self.text_edit.cursorForPosition(event.pos())
        block = cursor.block()
        if not block.isValid() or not block.text().strip():
            QTextEdit.mouseDoubleClickEvent(self.text_edit, event)
            return

        plain_text = block.text()

        dlg = QDialog(self)
        dlg.setWindowTitle(S.output_panel.dialog_log_detail)
        dlg.resize(720, 400)
        dlg.setMinimumSize(400, 200)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)

        detail_edit = QTextEdit(dlg)
        detail_edit.setReadOnly(True)
        detail_edit.setFont(QFont("Consolas", 10))
        detail_edit.setPlainText(plain_text)
        from src.design_system.tokens import get_colors
        colors = get_colors()
        detail_edit.setStyleSheet(
            f"QTextEdit {{ background: {colors.bg_primary}; color: {colors.text_primary}; border: none; }}"
        )
        layout.addWidget(detail_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        copy_btn = QPushButton(S.output_panel.btn_copy_detail)
        copy_btn.clicked.connect(lambda: (
            __import__("PyQt6.QtWidgets", fromlist=["QApplication"]).QApplication.clipboard().setText(plain_text)
        ))
        btn_layout.addWidget(copy_btn)

        close_btn = QPushButton(S.output_panel.btn_close_detail)
        close_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        dlg.exec()

    def clear(self):
        """Limpa o output"""
        self.text_edit.clear()
        self.cleared.emit()

    def _copy_to_clipboard(self):
        """Copy content to clipboard"""
        from PyQt6.QtWidgets import QApplication

        text = self.text_edit.toPlainText()
        QApplication.clipboard().setText(text)

    def get_text(self) -> str:
        """Retorna texto plano"""
        return self.text_edit.toPlainText()

    def get_html(self) -> str:
        """Retorna HTML"""
        return self.text_edit.toHtml()

    def toPlainText(self) -> str:
        """Compatibilidade: retorna texto plano"""
        return self.text_edit.toPlainText()

    def verticalScrollBar(self):
        """Compatibilidade: retorna barra de scroll vertical"""
        return self.text_edit.verticalScrollBar()
