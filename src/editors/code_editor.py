"""
CodeEditor - Implementação do editor de código usando QScintilla.

Implementa a interface ICodeEditor seguindo o princípio de Inversão de Dependência.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget
from PyQt6.Qsci import QsciScintilla, QsciLexerPython, QsciLexerSQL


class CodeEditor(QsciScintilla):
    """
    Editor de código baseado em QScintilla.
    
    Simples e direto:
    - Python = lexer Python
    - SQL e Cross-Syntax = lexer SQL
    - Tema dark sempre aplicado
    """
    
    # Signals da interface
    text_changed = pyqtSignal()
    execute_requested = pyqtSignal()
    focus_in = pyqtSignal()
    focus_out = pyqtSignal()
    
    # Signals de compatibilidade com QScintilla
    SCN_FOCUSIN = pyqtSignal()
    SCN_FOCUSOUT = pyqtSignal()
    
    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)
        
        self.theme_manager = theme_manager
        self._language = 'python'
        self._theme_name = 'dark'
        
        self._setup_editor()
        self._setup_lexer()
        self._setup_shortcuts()
        self._connect_signals()
        
        # Aplicar tema se disponível
        if self.theme_manager:
            self.apply_theme()
    
    def _connect_signals(self):
        """Conecta sinais internos aos sinais da interface."""
        self.textChanged.connect(self.text_changed.emit)
        self.SCN_FOCUSIN.connect(self.focus_in.emit)
        self.SCN_FOCUSOUT.connect(self.focus_out.emit)
    
    def _setup_editor(self):
        """Configura as propriedades básicas do editor."""
        # Fonte
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        
        # Margens (números de linha)
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(0, "00000")
        self.setMarginsForegroundColor(QColor("#858585"))  # Cinza mais claro
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))
        
        # Forçar cores da margem via stylesheet (qt-material não sobrescreve)
        self.setStyleSheet("""
            QsciScintilla {
                border: none;
            }
        """)
        
        # Indentação
        self.setIndentationGuides(True)
        self.setTabWidth(4)
        self.setIndentationsUseTabs(False)
        self.setAutoIndent(True)
        self.setBackspaceUnindents(True)
        
        # Brace matching
        self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        self.setMatchedBraceBackgroundColor(QColor("#3e4451"))
        self.setMatchedBraceForegroundColor(QColor("#61afef"))
        
        # Seleção
        self.setSelectionBackgroundColor(QColor("#264f78"))
        
        # Caret (cursor)
        self.setCaretForegroundColor(QColor("#c5c5c5"))
        self.setCaretWidth(2)
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#2a2a2a"))
        
        # Autocompletar
        self.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAll)
        self.setAutoCompletionThreshold(2)
        self.setAutoCompletionCaseSensitivity(False)
        self.setAutoCompletionReplaceWord(True)
        
        # Folding
        self.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle)
        self.setFoldMarginColors(QColor("#1e1e1e"), QColor("#1e1e1e"))
        
        # Whitespace e EOL
        self.setWhitespaceVisibility(QsciScintilla.WhitespaceVisibility.WsInvisible)
        self.setEolMode(QsciScintilla.EolMode.EolWindows)
        self.setEolVisibility(False)
        
        # Scroll
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTH, 1)
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTHTRACKING, True)
    
    def _setup_lexer(self):
        """Configura o lexer baseado na linguagem atual."""
        if self._language == 'sql' or self._language == 'cross':
            self._setup_sql_lexer()
        else:
            self._setup_python_lexer()
    
    def _setup_python_lexer(self):
        """Configura lexer Python com tema dark."""
        lexer = QsciLexerPython(self)
        font = QFont("Consolas", 11)
        
        # Background dark
        lexer.setDefaultPaper(QColor("#1e1e1e"))
        lexer.setDefaultColor(QColor("#d4d4d4"))
        
        # Cores Python (VS Code Dark)
        lexer.setColor(QColor("#d4d4d4"), QsciLexerPython.Default)
        lexer.setColor(QColor("#6a9955"), QsciLexerPython.Comment)
        lexer.setColor(QColor("#6a9955"), QsciLexerPython.CommentBlock)
        lexer.setColor(QColor("#569cd6"), QsciLexerPython.Keyword)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.SingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.DoubleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.TripleSingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.TripleDoubleQuotedString)
        lexer.setColor(QColor("#b5cea8"), QsciLexerPython.Number)
        lexer.setColor(QColor("#d4d4d4"), QsciLexerPython.Operator)
        lexer.setColor(QColor("#9cdcfe"), QsciLexerPython.Identifier)
        lexer.setColor(QColor("#dcdcaa"), QsciLexerPython.FunctionMethodName)
        lexer.setColor(QColor("#4ec9b0"), QsciLexerPython.ClassName)
        lexer.setColor(QColor("#c586c0"), QsciLexerPython.Decorator)
        
        lexer.setDefaultFont(font)
        self.setLexer(lexer)
        
        # Reforçar cores da margem após definir lexer
        self.setMarginsForegroundColor(QColor("#858585"))
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))
    
    def _setup_sql_lexer(self):
        """Configura lexer SQL com tema dark."""
        lexer = QsciLexerSQL(self)
        font = QFont("Consolas", 11)
        
        # Background dark
        lexer.setDefaultPaper(QColor("#1e1e1e"))
        lexer.setDefaultColor(QColor("#d4d4d4"))
        
        # Cores SQL (VS Code Dark)
        lexer.setColor(QColor("#d4d4d4"), QsciLexerSQL.Default)
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.Comment)
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.CommentLine)
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.CommentDoc)
        lexer.setColor(QColor("#569cd6"), QsciLexerSQL.Keyword)
        lexer.setColor(QColor("#ce9178"), QsciLexerSQL.SingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerSQL.DoubleQuotedString)
        lexer.setColor(QColor("#b5cea8"), QsciLexerSQL.Number)
        lexer.setColor(QColor("#d4d4d4"), QsciLexerSQL.Operator)
        lexer.setColor(QColor("#9cdcfe"), QsciLexerSQL.Identifier)
        
        lexer.setDefaultFont(font)
        self.setLexer(lexer)
        
        # Reforçar cores da margem após definir lexer
        self.setMarginsForegroundColor(QColor("#858585"))
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))
    
    def _setup_shortcuts(self):
        """Configura atalhos de teclado."""
        # Nota: F5 é gerenciado globalmente pelo MainWindow
        # para evitar conflito de atalhos ambíguos
        
        # Ctrl+Enter - Executar
        shortcut_ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_ctrl_enter.activated.connect(self.execute_requested.emit)
        
        # Shift+Enter - Executar
        shortcut_shift_enter = QShortcut(QKeySequence("Shift+Return"), self)
        shortcut_shift_enter.activated.connect(self.execute_requested.emit)
        
        # Ctrl+/ - Comentar/descomentar
        shortcut_comment = QShortcut(QKeySequence("Ctrl+/"), self)
        shortcut_comment.activated.connect(self.toggle_comment)
    
    # === Implementação da Interface ICodeEditor ===
    
    def get_text(self) -> str:
        """Retorna todo o texto do editor."""
        return self.text()
    
    def set_text(self, text: str) -> None:
        """Define o texto do editor."""
        self.setText(text)
    
    def get_selected_text(self) -> str:
        """Retorna o texto selecionado ou string vazia."""
        return self.selectedText() if self.hasSelectedText() else ""
    
    def has_selection(self) -> bool:
        """Verifica se há texto selecionado."""
        return self.hasSelectedText()
    
    def clear(self) -> None:
        """Limpa todo o texto do editor."""
        self.setText("")
    
    def set_language(self, language: str) -> None:
        """Define a linguagem e atualiza o lexer."""
        language = language.lower()
        if language in ('python', 'sql', 'cross'):
            self._language = language
            self._setup_lexer()
    
    def get_language(self) -> str:
        """Retorna a linguagem atual."""
        return self._language
    
    def set_theme(self, theme_name: str) -> None:
        """Define o tema do editor."""
        self._theme_name = theme_name
        self.apply_theme()
    
    def apply_theme(self) -> None:
        """Aplica/atualiza o tema atual do ThemeManager."""
        if not self.theme_manager:
            return
        
        # Reconfigura o lexer com as cores do tema
        self._setup_lexer()
        
        # Atualiza cores do editor
        colors = self.theme_manager.get_editor_colors()
        
        self.setMarginsBackgroundColor(QColor(colors.get('margin_bg', '#1e1e1e')))
        self.setMarginsForegroundColor(QColor(colors.get('margin_fg', '#6e7681')))
        self.setCaretLineBackgroundColor(QColor(colors.get('caret_line', '#2a2a2a')))
        self.setCaretForegroundColor(QColor(colors.get('caret', '#c5c5c5')))
        self.setSelectionBackgroundColor(QColor(colors.get('selection', '#264f78')))
        self.setFoldMarginColors(
            QColor(colors.get('margin_bg', '#1e1e1e')),
            QColor(colors.get('margin_bg', '#1e1e1e'))
        )
    
    def set_font(self, family: str, size: int) -> None:
        """Define a fonte do editor."""
        font = QFont(family, size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        if self.lexer():
            self.lexer().setFont(font)
    
    def set_read_only(self, read_only: bool) -> None:
        """Define se o editor é somente leitura."""
        self.setReadOnly(read_only)
    
    def set_line_numbers_visible(self, visible: bool) -> None:
        """Define se os números de linha são visíveis."""
        if visible:
            self.setMarginWidth(0, "00000")
        else:
            self.setMarginWidth(0, 0)
    
    def get_line_count(self) -> int:
        """Retorna o número de linhas."""
        return self.lines()
    
    def get_current_line(self) -> int:
        """Retorna a linha atual do cursor (0-indexed)."""
        line, _ = self.getCursorPosition()
        return line
    
    def go_to_line(self, line: int) -> None:
        """Move o cursor para a linha especificada (0-indexed)."""
        self.setCursorPosition(line, 0)
        self.ensureLineVisible(line)
    
    def get_widget(self) -> QWidget:
        """Retorna o widget Qt do editor."""
        return self
    
    # === Métodos auxiliares ===
    
    def toggle_comment(self):
        """Comenta/descomenta a linha ou seleção atual."""
        comment_char = "--" if self._language == 'sql' else "#"
        
        if self.hasSelectedText():
            start_line, start_index, end_line, end_index = self.getSelection()
            for line in range(start_line, end_line + 1):
                line_text = self.text(line)
                if line_text.strip().startswith(comment_char):
                    new_text = line_text.replace(comment_char, "", 1)
                else:
                    new_text = comment_char + line_text
                self.setSelection(line, 0, line, len(line_text))
                self.replaceSelectedText(new_text)
        else:
            line, index = self.getCursorPosition()
            line_text = self.text(line)
            if line_text.strip().startswith(comment_char):
                new_text = line_text.replace(comment_char, "", 1)
            else:
                new_text = comment_char + line_text
            self.setSelection(line, 0, line, len(line_text))
            self.replaceSelectedText(new_text)
            self.setCursorPosition(line, index)
    
    # === Eventos de foco ===
    
    def focusInEvent(self, event):
        """Sobrescreve evento de foco para emitir sinal."""
        super().focusInEvent(event)
        self.SCN_FOCUSIN.emit()
    
    def focusOutEvent(self, event):
        """Sobrescreve evento de perda de foco para emitir sinal."""
        super().focusOutEvent(event)
        self.SCN_FOCUSOUT.emit()
