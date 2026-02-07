"""
Editor Python para manipular resultados das queries
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PyQt6.Qsci import QsciScintilla, QsciLexerPython


class PythonEditor(QsciScintilla):
    """Editor de Python com syntax highlighting"""

    execute_requested = pyqtSignal(str)  # Sinal quando Shift+F5 é pressionado

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_editor()
        self._setup_lexer()
        self._setup_shortcuts()

    def _setup_editor(self):
        """Configura as propriedades básicas do editor"""
        # Fonte
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        # Margens
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(0, "00000")
        self.setMarginsForegroundColor(QColor("#6e7681"))
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))

        # Indentação Python
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

        # Whitespace
        self.setWhitespaceVisibility(QsciScintilla.WhitespaceVisibility.WsInvisible)

        # EOL
        self.setEolMode(QsciScintilla.EolMode.EolWindows)
        self.setEolVisibility(False)

        # Scroll
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTH, 1)
        self.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTHTRACKING, True)

    def _setup_lexer(self):
        """Configura o lexer Python para syntax highlighting"""
        lexer = QsciLexerPython(self)

        # Cores do tema escuro (estilo VS Code Dark)
        # Default
        lexer.setColor(QColor("#d4d4d4"), QsciLexerPython.Default)
        lexer.setPaper(QColor("#1e1e1e"), QsciLexerPython.Default)

        # Comentários
        lexer.setColor(QColor("#6a9955"), QsciLexerPython.Comment)
        lexer.setColor(QColor("#6a9955"), QsciLexerPython.CommentBlock)

        # Keywords
        lexer.setColor(QColor("#569cd6"), QsciLexerPython.Keyword)

        # Strings
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.SingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.DoubleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.TripleSingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerPython.TripleDoubleQuotedString)

        # Números
        lexer.setColor(QColor("#b5cea8"), QsciLexerPython.Number)

        # Operadores
        lexer.setColor(QColor("#d4d4d4"), QsciLexerPython.Operator)

        # Identificadores
        lexer.setColor(QColor("#9cdcfe"), QsciLexerPython.Identifier)

        # Funções
        lexer.setColor(QColor("#dcdcaa"), QsciLexerPython.FunctionMethodName)

        # Classes
        lexer.setColor(QColor("#4ec9b0"), QsciLexerPython.ClassName)

        # Decoradores
        lexer.setColor(QColor("#c586c0"), QsciLexerPython.Decorator)

        self.setLexer(lexer)

    def _setup_shortcuts(self):
        """Configura atalhos de teclado"""
        # Shift+F5 - Executar código Python
        shortcut_execute = QShortcut(QKeySequence("Shift+F5"), self)
        shortcut_execute.activated.connect(self._on_execute)

        # Ctrl+Shift+Enter - Executar código Python
        shortcut_execute2 = QShortcut(QKeySequence("Ctrl+Shift+Return"), self)
        shortcut_execute2.activated.connect(self._on_execute)

        # Ctrl+/ - Comentar/descomentar linha
        shortcut_comment = QShortcut(QKeySequence("Ctrl+/"), self)
        shortcut_comment.activated.connect(self.toggle_comment)

    def _on_execute(self):
        """Callback quando executar código é solicitado"""
        text = self.selectedText() if self.hasSelectedText() else self.text()
        if text.strip():
            self.execute_requested.emit(text)

    def toggle_comment(self):
        """Comenta/descomenta a linha ou seleção atual"""
        if self.hasSelectedText():
            # Comentar seleção
            start_line, start_index, end_line, end_index = self.getSelection()
            for line in range(start_line, end_line + 1):
                line_text = self.text(line)
                if line_text.strip().startswith("#"):
                    # Descomentar
                    new_text = line_text.replace("#", "", 1)
                else:
                    # Comentar
                    new_text = "#" + line_text
                self.setSelection(line, 0, line, len(line_text))
                self.replaceSelectedText(new_text)
        else:
            # Comentar linha atual
            line, index = self.getCursorPosition()
            line_text = self.text(line)
            if line_text.strip().startswith("#"):
                # Descomentar
                new_text = line_text.replace("#", "", 1)
            else:
                # Comentar
                new_text = "#" + line_text
            self.setSelection(line, 0, line, len(line_text))
            self.replaceSelectedText(new_text)
            self.setCursorPosition(line, index)

    def insert_python_template(self, template_name: str):
        """Insere um template Python"""
        templates = {
            "filter": "# Filtrar dados\nfiltered_df = df[df['coluna'] > valor]",
            "groupby": "# Agrupar dados\ngrouped = df.groupby('coluna').agg({'coluna2': 'sum'})",
            "plot": "# Plotar dados\nimport matplotlib.pyplot as plt\ndf.plot(kind='bar')\nplt.show()",
            "export": "# Exportar para CSV\ndf.to_csv('resultado.csv', index=False)",
        }

        template = templates.get(template_name, "")
        if template:
            self.insert(template)
