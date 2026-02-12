"""
CodeEditor - Editor de codigo usando QScintilla com Find/Replace nativo.

Implementa a interface ICodeEditor seguindo o principio de Inversao de Dependencia.
Inclui barra de Find/Replace integrada (Ctrl+F / Ctrl+H).
"""

from PyQt6.QtCore import Qt, pyqtSignal, QStringListModel
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QLabel,
    QCompleter,
)
from PyQt6.Qsci import QsciScintilla, QsciLexerPython, QsciLexerSQL, QsciAPIs


# ---------------------------------------------------------------------------
# FindReplaceBar - Barra de busca/substituicao integrada
# ---------------------------------------------------------------------------

class FindReplaceBar(QWidget):
    """Barra de Find/Replace no estilo VS Code (dark)."""

    _BAR_STYLE = """
        FindReplaceBar {
            background: #252526;
            border-bottom: 1px solid #3e3e42;
        }
    """

    _INPUT_STYLE = """
        QLineEdit {
            background: #3c3c3c;
            color: #ccc;
            border: 1px solid #3e3e42;
            border-radius: 3px;
            padding: 3px 6px;
            font-size: 12px;
            min-width: 180px;
        }
        QLineEdit:focus {
            border-color: #007ACC;
        }
    """

    _BTN_STYLE = """
        QPushButton {
            background: transparent;
            color: #ccc;
            border: 1px solid #3e3e42;
            border-radius: 3px;
            padding: 3px 8px;
            font-size: 12px;
            min-width: 24px;
        }
        QPushButton:hover {
            background: #37373d;
            border-color: #555;
        }
        QPushButton:pressed {
            background: #094771;
        }
    """

    _CHECK_STYLE = """
        QCheckBox {
            color: #aaa;
            font-size: 11px;
            spacing: 4px;
        }
        QCheckBox::indicator {
            width: 14px;
            height: 14px;
        }
    """

    _LABEL_STYLE = "color: #888; font-size: 11px; padding: 0 4px;"

    close_requested = pyqtSignal()
    find_next = pyqtSignal(str, bool, bool, bool)  # text, case, whole_word, regex
    find_prev = pyqtSignal(str, bool, bool, bool)
    replace_one = pyqtSignal(str, str, bool, bool, bool)
    replace_all = pyqtSignal(str, str, bool, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FindReplaceBar")
        self._replace_visible = False
        self._setup_ui()
        self.hide()

    # -- UI ----------------------------------------------------------------

    def _setup_ui(self):
        self.setStyleSheet(self._BAR_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(4)

        # -- Find row -------------------------------------------------------
        find_row = QHBoxLayout()
        find_row.setSpacing(4)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Buscar...")
        self.find_input.setStyleSheet(self._INPUT_STYLE)
        self.find_input.returnPressed.connect(self._on_find_next)
        self.find_input.textChanged.connect(self._on_find_text_changed)
        find_row.addWidget(self.find_input, 1)

        self.match_case_cb = QCheckBox("Aa")
        self.match_case_cb.setToolTip("Diferenciar maiusculas/minusculas")
        self.match_case_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.match_case_cb)

        self.whole_word_cb = QCheckBox("W")
        self.whole_word_cb.setToolTip("Palavra inteira")
        self.whole_word_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.whole_word_cb)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip("Expressao regular")
        self.regex_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.regex_cb)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet(self._LABEL_STYLE)
        find_row.addWidget(self.info_label)

        btn_prev = QPushButton("\u2191")  # arrow up
        btn_prev.setToolTip("Anterior (Shift+Enter)")
        btn_prev.setStyleSheet(self._BTN_STYLE)
        btn_prev.setFixedWidth(28)
        btn_prev.clicked.connect(self._on_find_prev)
        find_row.addWidget(btn_prev)

        btn_next = QPushButton("\u2193")  # arrow down
        btn_next.setToolTip("Proximo (Enter)")
        btn_next.setStyleSheet(self._BTN_STYLE)
        btn_next.setFixedWidth(28)
        btn_next.clicked.connect(self._on_find_next)
        find_row.addWidget(btn_next)

        self.toggle_replace_btn = QPushButton("\u25B6")  # right triangle
        self.toggle_replace_btn.setToolTip("Expandir Replace (Ctrl+H)")
        self.toggle_replace_btn.setStyleSheet(self._BTN_STYLE)
        self.toggle_replace_btn.setFixedWidth(28)
        self.toggle_replace_btn.clicked.connect(self._toggle_replace)
        find_row.addWidget(self.toggle_replace_btn)

        btn_close = QPushButton("\u2715")  # multiplication X
        btn_close.setToolTip("Fechar (Esc)")
        btn_close.setStyleSheet(self._BTN_STYLE)
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self.close_bar)
        find_row.addWidget(btn_close)

        root.addLayout(find_row)

        # -- Replace row (oculto inicialmente) ------------------------------
        self.replace_row_widget = QWidget()
        replace_row = QHBoxLayout(self.replace_row_widget)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(4)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Substituir...")
        self.replace_input.setStyleSheet(self._INPUT_STYLE)
        replace_row.addWidget(self.replace_input, 1)

        btn_replace_one = QPushButton("Subst")
        btn_replace_one.setToolTip("Substituir proximo")
        btn_replace_one.setStyleSheet(self._BTN_STYLE)
        btn_replace_one.clicked.connect(self._on_replace_one)
        replace_row.addWidget(btn_replace_one)

        btn_replace_all = QPushButton("Todos")
        btn_replace_all.setToolTip("Substituir todos")
        btn_replace_all.setStyleSheet(self._BTN_STYLE)
        btn_replace_all.clicked.connect(self._on_replace_all)
        replace_row.addWidget(btn_replace_all)

        replace_row.addStretch()

        self.replace_row_widget.hide()
        root.addWidget(self.replace_row_widget)

    # -- Acoes -------------------------------------------------------------

    def _flags(self):
        return (
            self.match_case_cb.isChecked(),
            self.whole_word_cb.isChecked(),
            self.regex_cb.isChecked(),
        )

    def _on_find_next(self):
        t = self.find_input.text()
        if t:
            self.find_next.emit(t, *self._flags())

    def _on_find_prev(self):
        t = self.find_input.text()
        if t:
            self.find_prev.emit(t, *self._flags())

    def _on_find_text_changed(self, text):
        """Busca incremental ao digitar."""
        if text:
            self.find_next.emit(text, *self._flags())
        else:
            self.info_label.setText("")

    def _on_replace_one(self):
        f = self.find_input.text()
        r = self.replace_input.text()
        if f:
            self.replace_one.emit(f, r, *self._flags())

    def _on_replace_all(self):
        f = self.find_input.text()
        r = self.replace_input.text()
        if f:
            self.replace_all.emit(f, r, *self._flags())

    def _toggle_replace(self):
        self._replace_visible = not self._replace_visible
        self.replace_row_widget.setVisible(self._replace_visible)
        self.toggle_replace_btn.setText("\u25BC" if self._replace_visible else "\u25B6")
        if self._replace_visible:
            self.replace_input.setFocus()

    # -- API publica -------------------------------------------------------

    def open_find(self):
        """Abre barra de busca (Ctrl+F)."""
        self.show()
        self._replace_visible = False
        self.replace_row_widget.hide()
        self.toggle_replace_btn.setText("\u25B6")
        self.find_input.setFocus()
        self.find_input.selectAll()

    def open_replace(self):
        """Abre barra de busca+substituicao (Ctrl+H)."""
        self.show()
        self._replace_visible = True
        self.replace_row_widget.show()
        self.toggle_replace_btn.setText("\u25BC")
        self.find_input.setFocus()
        self.find_input.selectAll()

    def close_bar(self):
        """Fecha a barra."""
        self.hide()
        self.close_requested.emit()

    def set_info(self, text: str):
        """Define texto informativo (ex: '3 de 10')."""
        self.info_label.setText(text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._on_find_prev()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# CodeEditor - Editor QScintilla com Find/Replace integrado
# ---------------------------------------------------------------------------

class CodeEditor(QWidget):
    """
    Editor de codigo baseado em QScintilla com Find/Replace nativo.

    - Python = lexer Python
    - SQL e Cross-Syntax = lexer SQL
    - Tema dark sempre aplicado
    - Ctrl+F = Find, Ctrl+H = Find & Replace
    - Autocomplete SQL (schema) e Python (namespace)
    """

    # Signals da interface
    text_changed = pyqtSignal()
    execute_requested = pyqtSignal()
    focus_in = pyqtSignal()
    focus_out = pyqtSignal()

    # Signals de compatibilidade com QScintilla
    SCN_FOCUSIN = pyqtSignal()
    SCN_FOCUSOUT = pyqtSignal()
    textChanged = pyqtSignal()  # compatibilidade com QsciScintilla.textChanged

    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._language = "python"
        self._theme_name = "dark"

        # Dados de autocomplete customizado
        self._sql_schema = {}
        self._python_namespace = {}

        self._setup_container()
        self._setup_editor()
        self._setup_lexer()
        self._setup_shortcuts()
        self._connect_signals()

        # Aplicar tema se disponivel
        if self.theme_manager:
            self.apply_theme()

    def _setup_container(self):
        """Monta layout: FindReplaceBar + QsciScintilla."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.find_bar = FindReplaceBar(self)
        layout.addWidget(self.find_bar)

        self._sci = QsciScintilla(self)
        layout.addWidget(self._sci, 1)

        # Conectar sinais do find_bar
        self.find_bar.find_next.connect(self._do_find_next)
        self.find_bar.find_prev.connect(self._do_find_prev)
        self.find_bar.replace_one.connect(self._do_replace_one)
        self.find_bar.replace_all.connect(self._do_replace_all)
        self.find_bar.close_requested.connect(self._on_find_bar_closed)

    def _connect_signals(self):
        """Conecta sinais internos aos sinais da interface."""
        self._sci.textChanged.connect(self.text_changed.emit)
        self._sci.textChanged.connect(self.textChanged.emit)
        self._sci.SCN_FOCUSIN.connect(self._on_focus_in)
        self._sci.SCN_FOCUSOUT.connect(self._on_focus_out)

    def _on_focus_in(self):
        self.SCN_FOCUSIN.emit()
        self.focus_in.emit()

    def _on_focus_out(self):
        self.SCN_FOCUSOUT.emit()
        self.focus_out.emit()

    def _setup_editor(self):
        """Configura as propriedades basicas do editor."""
        sci = self._sci

        # Fonte
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        sci.setFont(font)

        # Margens (numeros de linha)
        sci.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        sci.setMarginWidth(0, "00000")
        sci.setMarginsForegroundColor(QColor("#858585"))
        sci.setMarginsBackgroundColor(QColor("#1e1e1e"))

        # Forcar cores da margem via stylesheet (qt-material nao sobrescreve)
        sci.setStyleSheet("""
            QsciScintilla {
                border: none;
            }
        """)

        # Indentacao
        sci.setIndentationGuides(True)
        sci.setTabWidth(4)
        sci.setIndentationsUseTabs(False)
        sci.setAutoIndent(True)
        sci.setBackspaceUnindents(True)

        # Brace matching
        sci.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        sci.setMatchedBraceBackgroundColor(QColor("#3e4451"))
        sci.setMatchedBraceForegroundColor(QColor("#61afef"))

        # Selecao
        sci.setSelectionBackgroundColor(QColor("#264f78"))

        # Caret (cursor)
        sci.setCaretForegroundColor(QColor("#c5c5c5"))
        sci.setCaretWidth(2)
        sci.setCaretLineVisible(True)
        sci.setCaretLineBackgroundColor(QColor("#2a2a2a"))

        # Autocompletar
        sci.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAPIs)
        sci.setAutoCompletionThreshold(2)
        sci.setAutoCompletionCaseSensitivity(False)
        sci.setAutoCompletionReplaceWord(True)

        # Folding
        sci.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle)
        sci.setFoldMarginColors(QColor("#1e1e1e"), QColor("#1e1e1e"))

        # Whitespace e EOL
        sci.setWhitespaceVisibility(QsciScintilla.WhitespaceVisibility.WsInvisible)
        sci.setEolMode(QsciScintilla.EolMode.EolWindows)
        sci.setEolVisibility(False)

        # Scroll
        sci.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTH, 1)
        sci.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTHTRACKING, True)

    def _setup_lexer(self):
        """Configura o lexer baseado na linguagem atual."""
        if self._language == "sql" or self._language == "cross":
            self._setup_sql_lexer()
        else:
            self._setup_python_lexer()
        # Reconstruir APIs de autocomplete apos trocar lexer
        self._rebuild_apis()

    def _setup_python_lexer(self):
        """Configura lexer Python com tema dark."""
        sci = self._sci
        lexer = QsciLexerPython(sci)
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
        sci.setLexer(lexer)

        # Reforcar cores da margem apos definir lexer
        sci.setMarginsForegroundColor(QColor("#858585"))
        sci.setMarginsBackgroundColor(QColor("#1e1e1e"))

    def _setup_sql_lexer(self):
        """Configura lexer SQL com tema dark."""
        sci = self._sci
        lexer = QsciLexerSQL(sci)
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
        sci.setLexer(lexer)

        # Reforcar cores da margem apos definir lexer
        sci.setMarginsForegroundColor(QColor("#858585"))
        sci.setMarginsBackgroundColor(QColor("#1e1e1e"))

    def _rebuild_apis(self):
        """Reconstroi a lista de APIs de autocomplete do lexer atual."""
        sci = self._sci
        lexer = sci.lexer()
        if not lexer:
            return

        apis = QsciAPIs(lexer)

        if self._language == "python":
            # Palavras-chave basicas do Python
            for kw in (
                "False", "None", "True", "and", "as", "assert", "async", "await",
                "break", "class", "continue", "def", "del", "elif", "else",
                "except", "finally", "for", "from", "global", "if", "import",
                "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
                "return", "try", "while", "with", "yield",
                "print", "len", "range", "enumerate", "zip", "map", "filter",
                "list", "dict", "set", "tuple", "str", "int", "float", "bool",
                "isinstance", "hasattr", "getattr", "setattr", "type", "super",
                "open", "input",
            ):
                apis.add(kw)

            # Namespace Python customizado
            for name, type_name in self._python_namespace.items():
                if type_name:
                    apis.add(f"{name}  ({type_name})")
                else:
                    apis.add(name)

        elif self._language in ("sql", "cross"):
            # Keywords SQL
            for kw in (
                "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN",
                "LIKE", "IS", "NULL", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
                "FULL", "CROSS", "ON", "AS", "ORDER", "BY", "GROUP", "HAVING",
                "LIMIT", "OFFSET", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
                "DELETE", "CREATE", "TABLE", "ALTER", "DROP", "INDEX", "VIEW",
                "UNION", "ALL", "DISTINCT", "TOP", "CASE", "WHEN", "THEN",
                "ELSE", "END", "EXISTS", "COUNT", "SUM", "AVG", "MIN", "MAX",
                "CAST", "CONVERT", "COALESCE", "ISNULL", "NULLIF",
                "GO", "USE", "EXEC", "DECLARE", "BEGIN", "COMMIT", "ROLLBACK",
            ):
                apis.add(kw)
                apis.add(kw.lower())

            # Schema SQL customizado
            tables = self._sql_schema.get("tables", [])
            columns = self._sql_schema.get("columns", {})

            for table in tables:
                apis.add(table)
                # Colunas de cada tabela
                for col in columns.get(table, []):
                    apis.add(f"{table}.{col}")
                    apis.add(col)

        apis.prepare()

    def _setup_shortcuts(self):
        """Configura atalhos de teclado."""
        # Ctrl+Enter - Executar
        shortcut_ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), self._sci)
        shortcut_ctrl_enter.activated.connect(self.execute_requested.emit)

        # Shift+Enter - Executar
        shortcut_shift_enter = QShortcut(QKeySequence("Shift+Return"), self._sci)
        shortcut_shift_enter.activated.connect(self.execute_requested.emit)

        # Ctrl+/ - Comentar/descomentar
        shortcut_comment = QShortcut(QKeySequence("Ctrl+/"), self._sci)
        shortcut_comment.activated.connect(self.toggle_comment)

        # Ctrl+F - Find
        shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self._sci)
        shortcut_find.activated.connect(self._open_find)

        # Ctrl+H - Find & Replace
        shortcut_replace = QShortcut(QKeySequence("Ctrl+H"), self._sci)
        shortcut_replace.activated.connect(self._open_replace)

    # === Find / Replace ===

    def _open_find(self):
        """Abre barra de busca."""
        sel = self._sci.selectedText() if self._sci.hasSelectedText() else ""
        self.find_bar.open_find()
        if sel:
            self.find_bar.find_input.setText(sel)
            self.find_bar.find_input.selectAll()

    def _open_replace(self):
        """Abre barra de busca + substituicao."""
        sel = self._sci.selectedText() if self._sci.hasSelectedText() else ""
        self.find_bar.open_replace()
        if sel:
            self.find_bar.find_input.setText(sel)
            self.find_bar.find_input.selectAll()

    def _on_find_bar_closed(self):
        """Retorna foco ao editor quando barra fecha."""
        self._sci.setFocus()

    def _do_find_next(self, text, match_case, whole_word, regex):
        """Busca proxima ocorrencia."""
        sci = self._sci
        line, index = sci.getCursorPosition()
        found = sci.findFirst(
            text, regex, match_case, whole_word, True,  # wrap
            True,  # forward
            line, index,
        )
        if not found:
            self.find_bar.set_info("Nenhum resultado")
        else:
            self.find_bar.set_info("")

    def _do_find_prev(self, text, match_case, whole_word, regex):
        """Busca ocorrencia anterior."""
        sci = self._sci
        line, index = sci.getCursorPosition()
        found = sci.findFirst(
            text, regex, match_case, whole_word, True,  # wrap
            False,  # backward
            line, index,
        )
        if not found:
            self.find_bar.set_info("Nenhum resultado")
        else:
            self.find_bar.set_info("")

    def _do_replace_one(self, find_text, replace_text, match_case, whole_word, regex):
        """Substitui ocorrencia atual e busca proxima."""
        sci = self._sci
        if sci.hasSelectedText():
            sci.replace(replace_text)
        # Buscar proxima
        self._do_find_next(find_text, match_case, whole_word, regex)

    def _do_replace_all(self, find_text, replace_text, match_case, whole_word, regex):
        """Substitui todas as ocorrencias."""
        sci = self._sci
        count = 0
        # Comecar do inicio
        sci.setCursorPosition(0, 0)
        while sci.findFirst(
            find_text, regex, match_case, whole_word, False,  # no wrap
            True,  # forward
        ):
            sci.replace(replace_text)
            count += 1
        self.find_bar.set_info(f"{count} substituicoes" if count else "Nenhum resultado")

    # === Implementacao da Interface ICodeEditor ===

    def get_text(self) -> str:
        """Retorna todo o texto do editor."""
        return self._sci.text()

    def set_text(self, text: str) -> None:
        """Define o texto do editor."""
        self._sci.setText(text)

    def get_selected_text(self) -> str:
        """Retorna o texto selecionado ou string vazia."""
        return self._sci.selectedText() if self._sci.hasSelectedText() else ""

    def has_selection(self) -> bool:
        """Verifica se ha texto selecionado."""
        return self._sci.hasSelectedText()

    def clear(self) -> None:
        """Limpa todo o texto do editor."""
        self._sci.setText("")

    def set_language(self, language: str) -> None:
        """Define a linguagem e atualiza o lexer."""
        language = language.lower()
        if language in ("python", "sql", "cross"):
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
        sci = self._sci

        sci.setMarginsBackgroundColor(QColor(colors.get("margin_bg", "#1e1e1e")))
        sci.setMarginsForegroundColor(QColor(colors.get("margin_fg", "#6e7681")))
        sci.setCaretLineBackgroundColor(QColor(colors.get("caret_line", "#2a2a2a")))
        sci.setCaretForegroundColor(QColor(colors.get("caret", "#c5c5c5")))
        sci.setSelectionBackgroundColor(QColor(colors.get("selection", "#264f78")))
        sci.setFoldMarginColors(
            QColor(colors.get("margin_bg", "#1e1e1e")),
            QColor(colors.get("margin_bg", "#1e1e1e")),
        )

    def set_font(self, family: str, size: int) -> None:
        """Define a fonte do editor."""
        font = QFont(family, size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._sci.setFont(font)
        if self._sci.lexer():
            self._sci.lexer().setFont(font)

    def set_read_only(self, read_only: bool) -> None:
        """Define se o editor e somente leitura."""
        self._sci.setReadOnly(read_only)

    def set_line_numbers_visible(self, visible: bool) -> None:
        """Define se os numeros de linha sao visiveis."""
        if visible:
            self._sci.setMarginWidth(0, "00000")
        else:
            self._sci.setMarginWidth(0, 0)

    def get_line_count(self) -> int:
        """Retorna o numero de linhas."""
        return self._sci.lines()

    def get_current_line(self) -> int:
        """Retorna a linha atual do cursor (0-indexed)."""
        line, _ = self._sci.getCursorPosition()
        return line

    def go_to_line(self, line: int) -> None:
        """Move o cursor para a linha especificada (0-indexed)."""
        self._sci.setCursorPosition(line, 0)
        self._sci.ensureLineVisible(line)

    def get_widget(self) -> QWidget:
        """Retorna o widget Qt do editor."""
        return self

    # === Autocomplete: SQL Schema & Python Namespace ===

    def set_sql_schema(self, schema: dict) -> None:
        """
        Define schema do banco para autocomplete SQL.

        Args:
            schema: dict com {tables: [...], columns: {...}, database: ''}
        """
        self._sql_schema = schema if schema else {}
        if self._language in ("sql", "cross"):
            self._rebuild_apis()

    def clear_sql_schema(self) -> None:
        """Limpa schema SQL do autocomplete."""
        self._sql_schema = {}
        if self._language in ("sql", "cross"):
            self._rebuild_apis()

    def set_python_namespace(self, namespace: dict) -> None:
        """
        Define namespace Python para autocomplete.

        Args:
            namespace: dict com {varName: typeName, ...}
        """
        self._python_namespace = namespace if namespace else {}
        if self._language == "python":
            self._rebuild_apis()

    def clear_python_namespace(self) -> None:
        """Limpa namespace Python do autocomplete."""
        self._python_namespace = {}
        if self._language == "python":
            self._rebuild_apis()

    def insert_text_at_cursor(self, text: str) -> None:
        """Insere texto na posicao atual do cursor."""
        sci = self._sci
        line, index = sci.getCursorPosition()
        sci.insertAt(text, line, index)
        sci.setCursorPosition(line, index + len(text))

    # === Metodos auxiliares ===

    def toggle_comment(self):
        """Comenta/descomenta a linha ou selecao atual."""
        sci = self._sci
        comment_char = "--" if self._language == "sql" else "#"

        if sci.hasSelectedText():
            start_line, start_index, end_line, end_index = sci.getSelection()
            for line_num in range(start_line, end_line + 1):
                line_text = sci.text(line_num)
                if line_text.strip().startswith(comment_char):
                    new_text = line_text.replace(comment_char, "", 1)
                else:
                    new_text = comment_char + line_text
                sci.setSelection(line_num, 0, line_num, len(line_text))
                sci.replaceSelectedText(new_text)
        else:
            line_num, index = sci.getCursorPosition()
            line_text = sci.text(line_num)
            if line_text.strip().startswith(comment_char):
                new_text = line_text.replace(comment_char, "", 1)
            else:
                new_text = comment_char + line_text
            sci.setSelection(line_num, 0, line_num, len(line_text))
            sci.replaceSelectedText(new_text)
            sci.setCursorPosition(line_num, index)

    # === Compatibilidade QScintilla (para codigo legado) ===

    def text(self) -> str:
        """Compatibilidade: QsciScintilla.text()"""
        return self._sci.text()

    def setText(self, text: str) -> None:
        """Compatibilidade: QsciScintilla.setText()"""
        self._sci.setText(text)

    def selectedText(self) -> str:
        """Compatibilidade: QsciScintilla.selectedText()"""
        return self._sci.selectedText()

    def hasSelectedText(self) -> bool:
        """Compatibilidade: QsciScintilla.hasSelectedText()"""
        return self._sci.hasSelectedText()

    def lines(self) -> int:
        """Compatibilidade: QsciScintilla.lines()"""
        return self._sci.lines()

    def getCursorPosition(self):
        """Compatibilidade: QsciScintilla.getCursorPosition()"""
        return self._sci.getCursorPosition()

    def setCursorPosition(self, line, index):
        """Compatibilidade: QsciScintilla.setCursorPosition()"""
        self._sci.setCursorPosition(line, index)

    def ensureLineVisible(self, line):
        """Compatibilidade: QsciScintilla.ensureLineVisible()"""
        self._sci.ensureLineVisible(line)

    def setReadOnly(self, ro):
        """Compatibilidade: QsciScintilla.setReadOnly()"""
        self._sci.setReadOnly(ro)

    def selectAll(self):
        """Compatibilidade: QsciScintilla.selectAll()"""
        self._sci.selectAll()

    def setFocus(self):
        """Redireciona foco para o editor interno."""
        self._sci.setFocus()

    # === Eventos de foco ===

    def focusInEvent(self, event):
        """Sobrescreve evento de foco para emitir sinal."""
        super().focusInEvent(event)
        self._sci.setFocus()

    def focusOutEvent(self, event):
        """Sobrescreve evento de perda de foco para emitir sinal."""
        super().focusOutEvent(event)
