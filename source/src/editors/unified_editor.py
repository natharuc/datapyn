"""
Editor de código unificado que suporta SQL e Python
"""

from PyQt6.Qsci import QsciScintilla, QsciLexerSQL, QsciLexerPython
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QColor, QKeyEvent

from src.core.theme_manager import ThemeManager


class UnifiedEditor(QsciScintilla):
    """Editor de código que suporta SQL e Python"""

    execute_sql = pyqtSignal(str)  # código SQL
    execute_python = pyqtSignal(str)  # código Python
    execute_cross_syntax = pyqtSignal(str)  # código com sintaxe mista

    # Referência compartilhada do ThemeManager
    _theme_manager = None

    def __init__(self, parent=None, lexer_type="sql", theme_manager=None):
        super().__init__(parent)
        self.lexer_type = lexer_type  # 'sql' ou 'python'

        # Usar theme_manager compartilhado ou criar novo
        if theme_manager:
            UnifiedEditor._theme_manager = theme_manager
        if UnifiedEditor._theme_manager is None:
            UnifiedEditor._theme_manager = ThemeManager()

        self._setup_editor()
        self._apply_theme()

    def _setup_editor(self):
        """Configura o editor"""
        # Font
        font = QFont("Consolas", 11)
        self.setFont(font)

        # Margins
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(0, "00000")

        # Indentação
        self.setIndentationsUseTabs(False)
        self.setTabWidth(4)
        self.setAutoIndent(True)

        # Linhas
        self.setCaretLineVisible(True)

        # Cursor (caret) - garantir que seja visível
        self.setCaretWidth(2)  # Cursor mais largo

        # Brace matching
        self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)

        # Auto-completion
        self.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAll)
        self.setAutoCompletionThreshold(2)
        self.setAutoCompletionCaseSensitivity(False)

    def _apply_theme(self):
        """Aplica tema atual ao editor"""
        colors = UnifiedEditor._theme_manager.get_editor_colors()

        # Background e foreground
        self.setPaper(colors["background"])
        self.setColor(colors["foreground"])

        # Cursor (caret)
        self.setCaretForegroundColor(colors["caret"])
        self.setCaretLineBackgroundColor(colors["caret_line"])

        # Seleção
        self.setSelectionBackgroundColor(colors["selection"])

        # Margins
        self.setMarginsForegroundColor(colors["margin_fg"])
        self.setMarginsBackgroundColor(colors["margin_bg"])

        # Brace matching
        self.setMatchedBraceBackgroundColor(colors["brace_match"])
        self.setMatchedBraceForegroundColor(colors["foreground"])

        # Aplicar lexer com cores do tema
        self._apply_lexer()

    def _apply_lexer(self):
        """Aplica lexer baseado no tipo configurado"""
        colors = UnifiedEditor._theme_manager.get_editor_colors()

        if self.lexer_type == "sql":
            sql_colors = UnifiedEditor._theme_manager.get_sql_colors()
            lexer = QsciLexerSQL(self)
            lexer.setDefaultFont(self.font())

            # Cores do tema
            lexer.setDefaultPaper(colors["background"])
            lexer.setDefaultColor(colors["foreground"])

            lexer.setColor(sql_colors["keyword"], QsciLexerSQL.Keyword)
            lexer.setColor(sql_colors["string"], QsciLexerSQL.DoubleQuotedString)
            lexer.setColor(sql_colors["string"], QsciLexerSQL.SingleQuotedString)
            lexer.setColor(sql_colors["number"], QsciLexerSQL.Number)
            lexer.setColor(sql_colors["comment"], QsciLexerSQL.Comment)
            lexer.setColor(sql_colors["comment"], QsciLexerSQL.CommentLine)
            lexer.setColor(sql_colors["operator"], QsciLexerSQL.Operator)

            # Aplicar paper em todos os estilos
            for style in range(128):
                lexer.setPaper(colors["background"], style)

        else:  # python
            py_colors = UnifiedEditor._theme_manager.get_python_colors()
            lexer = QsciLexerPython(self)
            lexer.setDefaultFont(self.font())

            # Cores do tema
            lexer.setDefaultPaper(colors["background"])
            lexer.setDefaultColor(colors["foreground"])

            lexer.setColor(py_colors["keyword"], QsciLexerPython.Keyword)
            lexer.setColor(py_colors["string"], QsciLexerPython.DoubleQuotedString)
            lexer.setColor(py_colors["string"], QsciLexerPython.SingleQuotedString)
            lexer.setColor(py_colors["number"], QsciLexerPython.Number)
            lexer.setColor(py_colors["comment"], QsciLexerPython.Comment)
            lexer.setColor(py_colors["classname"], QsciLexerPython.ClassName)
            lexer.setColor(py_colors["function"], QsciLexerPython.FunctionMethodName)
            lexer.setColor(py_colors["identifier"], QsciLexerPython.Identifier)

            # Aplicar paper em todos os estilos
            for style in range(128):
                lexer.setPaper(colors["background"], style)

        self.setLexer(lexer)

    def apply_theme(self, theme_manager: ThemeManager = None):
        """Reaplica tema (chamado quando usuário muda tema)"""
        if theme_manager:
            UnifiedEditor._theme_manager = theme_manager
        self._apply_theme()

    def set_lexer_type(self, lexer_type: str):
        """Define o tipo de lexer (sql ou python) para syntax highlighting"""
        if lexer_type in ["sql", "python"]:
            self.lexer_type = lexer_type
            self._apply_lexer()

    def get_selected_or_all_text(self) -> str:
        """Retorna texto selecionado ou todo o texto se nada estiver selecionado"""
        if self.hasSelectedText():
            return self.selectedText()
        return self.text()

    def keyPressEvent(self, event: QKeyEvent):
        """Intercepta teclas para atalhos personalizados"""
        # Shift+Enter - Executar Python
        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            text = self.get_selected_or_all_text()
            if text.strip():
                self.execute_python.emit(text)
            return  # Não propaga o evento

        # Ctrl+Shift+Enter - Executar Cross-Syntax
        if event.key() == Qt.Key.Key_Return and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            text = self.get_selected_or_all_text()
            if text.strip():
                self.execute_cross_syntax.emit(text)
            return  # Não propaga o evento

        # F5 - Executar SQL
        if event.key() == Qt.Key.Key_F5 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            text = self.get_selected_or_all_text()
            if text.strip():
                self.execute_sql.emit(text)
            return  # Não propaga o evento

        # Ctrl+Shift+F5 - Executar Cross-Syntax
        if event.key() == Qt.Key.Key_F5 and event.modifiers() == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            text = self.get_selected_or_all_text()
            if text.strip():
                self.execute_cross_syntax.emit(text)
            return  # Não propaga o evento

        # Propaga outros eventos normalmente
        super().keyPressEvent(event)
