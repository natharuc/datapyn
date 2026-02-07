"""
Painel de Output/Logs

Exibe mensagens de log, saída de comandos e erros.
"""

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .buttons import GhostButton, IconButton

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class OutputPanel(QWidget):
    """Painel de output/logs com formatação"""

    # Sinais
    cleared = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Configura UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar do output
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(5, 3, 5, 3)
        toolbar_layout.setSpacing(5)

        toolbar_layout.addStretch()

        # Botão limpar
        self.btn_clear = GhostButton("Limpar")
        if HAS_QTAWESOME:
            self.btn_clear.setIcon(qta.icon("fa5s.trash", color="#888888"))
        self.btn_clear.clicked.connect(self.clear)
        toolbar_layout.addWidget(self.btn_clear)

        # Botão copiar
        self.btn_copy = GhostButton("Copiar")
        if HAS_QTAWESOME:
            self.btn_copy.setIcon(qta.icon("fa5s.copy", color="#888888"))
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        toolbar_layout.addWidget(self.btn_copy)

        toolbar.setStyleSheet("""
            QWidget {
                background-color: #2d2d30;
                border-bottom: 1px solid #3e3e42;
            }
        """)
        layout.addWidget(toolbar)

        # Área de texto
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)

    def _apply_theme(self):
        """Aplica tema"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {"background": "#1e1e1e", "foreground": "#d4d4d4"}

        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                padding: 8px;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Define theme manager"""
        self.theme_manager = theme_manager
        self._apply_theme()

    def append(self, text: str, level: str = "info"):
        """Adiciona texto ao output

        Args:
            text: Texto a adicionar
            level: Nível ('info', 'success', 'warning', 'error')
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        colors = {"info": "#9cdcfe", "success": "#4ec9b0", "warning": "#dcdcaa", "error": "#f48771", "debug": "#808080"}
        color = colors.get(level, colors["info"])

        # Ícones por nível
        icons = {"info": "", "success": "[OK]", "warning": "[AVISO]", "error": "[ERRO]", "debug": "[DEBUG]"}
        icon = icons.get(level, "")

        if icon:
            html = f'<span style="color: #808080;">[{timestamp}]</span> <span style="color: {color};">{icon} {text}</span><br>'
        else:
            html = f'<span style="color: #808080;">[{timestamp}]</span> <span style="color: {color};">{text}</span><br>'

        self.text_edit.append(html)

        # Scroll para o final
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    def append_output(self, text: str, error: bool = False):
        """Método de compatibilidade com código antigo"""
        level = "error" if error else "info"
        self.append(text, level)

    def log(self, text: str):
        """Adiciona log de info"""
        self.append(text, "info")

    def success(self, text: str):
        """Adiciona log de sucesso"""
        self.append(text, "success")

    def warning(self, text: str):
        """Adiciona log de warning"""
        self.append(text, "warning")

    def error(self, text: str):
        """Adiciona log de erro"""
        self.append(text, "error")

    def debug(self, text: str):
        """Adiciona log de debug"""
        self.append(text, "debug")

    def clear(self):
        """Limpa o output"""
        self.text_edit.clear()
        self.cleared.emit()

    def _copy_to_clipboard(self):
        """Copia conteúdo para clipboard"""
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
