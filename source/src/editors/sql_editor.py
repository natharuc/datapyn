"""
Editor SQL com syntax highlighting estilo Monaco
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget
from PyQt6.Qsci import QsciScintilla, QsciLexerSQL


class SQLEditor(QsciScintilla):
    """Editor de SQL com syntax highlighting e autocompletar"""

    execute_requested = pyqtSignal(str)  # Signal when F5 is pressed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_editor()
        self._setup_lexer()
        self._setup_shortcuts()

    def _setup_editor(self):
        """Configure basic editor properties"""
        # Fonte
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        # Margens
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(0, "00000")
        self.setMarginsForegroundColor(QColor("#6e7681"))
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))

        # Indentation
        self.setIndentationGuides(True)
        self.setTabWidth(4)
        self.setIndentationsUseTabs(False)
        self.setAutoIndent(True)

        # Brace matching
        self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        self.setMatchedBraceBackgroundColor(QColor("#3e4451"))
        self.setMatchedBraceForegroundColor(QColor("#61afef"))

        # Selection
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

        # Folding (code folding)
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
        """Configura o lexer SQL para syntax highlighting"""
        lexer = QsciLexerSQL(self)

        # Cores do tema escuro (estilo VS Code Dark)
        # Default
        lexer.setColor(QColor("#d4d4d4"), QsciLexerSQL.Default)
        lexer.setPaper(QColor("#1e1e1e"), QsciLexerSQL.Default)

        # Comments
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.Comment)
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.CommentLine)
        lexer.setColor(QColor("#6a9955"), QsciLexerSQL.CommentDoc)

        # Keywords (SELECT, FROM, WHERE, etc)
        lexer.setColor(QColor("#569cd6"), QsciLexerSQL.Keyword)

        # Strings
        lexer.setColor(QColor("#ce9178"), QsciLexerSQL.SingleQuotedString)
        lexer.setColor(QColor("#ce9178"), QsciLexerSQL.DoubleQuotedString)

        # Numbers
        lexer.setColor(QColor("#b5cea8"), QsciLexerSQL.Number)

        # Operadores
        lexer.setColor(QColor("#d4d4d4"), QsciLexerSQL.Operator)

        # Identificadores
        lexer.setColor(QColor("#9cdcfe"), QsciLexerSQL.Identifier)

        # QsciLexerSQL already comes with pre-configured SQL keywords
        # No need to define manually

        self.setLexer(lexer)

    def _setup_shortcuts(self):
        """Configure keyboard shortcuts"""
        # F5 - Run query
        shortcut_execute = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        shortcut_execute.activated.connect(self._on_execute)

        # Ctrl+Enter - Run query
        shortcut_execute2 = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_execute2.activated.connect(self._on_execute)

        # Ctrl+/ - Comment/uncomment line
        shortcut_comment = QShortcut(QKeySequence("Ctrl+/"), self)
        shortcut_comment.activated.connect(self.toggle_comment)

    def _on_execute(self):
        """Callback when run query is requested"""
        text = self.selectedText() if self.hasSelectedText() else self.text()
        if text.strip():
            self.execute_requested.emit(text)

    def toggle_comment(self):
        """Comment/uncomment current line or selection"""
        if self.hasSelectedText():
            # Comment selection
            start_line, start_index, end_line, end_index = self.getSelection()
            for line in range(start_line, end_line + 1):
                line_text = self.text(line)
                if line_text.strip().startswith("--"):
                    # Descomentar
                    new_text = line_text.replace("--", "", 1)
                else:
                    # Comentar
                    new_text = "--" + line_text
                self.setSelection(line, 0, line, len(line_text))
                self.replaceSelectedText(new_text)
        else:
            # Comment current line
            line, index = self.getCursorPosition()
            line_text = self.text(line)
            if line_text.strip().startswith("--"):
                # Descomentar
                new_text = line_text.replace("--", "", 1)
            else:
                # Comentar
                new_text = "--" + line_text
            self.setSelection(line, 0, line, len(line_text))
            self.replaceSelectedText(new_text)
            self.setCursorPosition(line, index)

    def insert_sql_template(self, template_name: str):
        """Insere um template SQL"""
        templates = {
            "select": "SELECT * FROM table_name WHERE condition;",
            "insert": "INSERT INTO table_name (column1, column2) VALUES (value1, value2);",
            "update": "UPDATE table_name SET column1 = value1 WHERE condition;",
            "delete": "DELETE FROM table_name WHERE condition;",
            "create_table": """CREATE TABLE table_name (
    id INT PRIMARY KEY,
    column1 VARCHAR(255),
    column2 INT
);""",
        }

        template = templates.get(template_name, "")
        if template:
            self.insert(template)
