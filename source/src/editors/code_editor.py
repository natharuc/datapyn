"""
CodeEditor - Editor de codigo usando QScintilla com Find/Replace nativo.

Implementa a interface ICodeEditor seguindo o principio de Inversao de Dependencia.
Inclui barra de Find/Replace integrada (Ctrl+F / Ctrl+H).
"""

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent, QObject
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QLabel,
)
from PyQt6.Qsci import QsciScintilla, QsciLexerPython, QsciLexerSQL, QsciAPIs

from src.language import S
from src.services.jedi_completer import JediCompleter
from src.services.sql_autocomplete_service import SqlAutoCompleteService


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
            border-radius: 0px;
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
            border-radius: 0px;
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
        self.find_input.setPlaceholderText(S.find_replace.placeholder_find)
        self.find_input.setStyleSheet(self._INPUT_STYLE)
        self.find_input.returnPressed.connect(self._on_find_next)
        self.find_input.textChanged.connect(self._on_find_text_changed)
        find_row.addWidget(self.find_input, 1)

        self.match_case_cb = QCheckBox("Aa")
        self.match_case_cb.setToolTip(S.find_replace.tooltip_match_case)
        self.match_case_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.match_case_cb)

        self.whole_word_cb = QCheckBox("W")
        self.whole_word_cb.setToolTip(S.find_replace.tooltip_whole_word)
        self.whole_word_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.whole_word_cb)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip(S.find_replace.tooltip_regex)
        self.regex_cb.setStyleSheet(self._CHECK_STYLE)
        find_row.addWidget(self.regex_cb)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet(self._LABEL_STYLE)
        find_row.addWidget(self.info_label)

        btn_prev = QPushButton("\u2191")  # arrow up
        btn_prev.setToolTip(S.find_replace.tooltip_prev)
        btn_prev.setStyleSheet(self._BTN_STYLE)
        btn_prev.setFixedWidth(28)
        btn_prev.clicked.connect(self._on_find_prev)
        find_row.addWidget(btn_prev)

        btn_next = QPushButton("\u2193")  # arrow down
        btn_next.setToolTip(S.find_replace.tooltip_next)
        btn_next.setStyleSheet(self._BTN_STYLE)
        btn_next.setFixedWidth(28)
        btn_next.clicked.connect(self._on_find_next)
        find_row.addWidget(btn_next)

        self.toggle_replace_btn = QPushButton("\u25B6")  # right triangle
        self.toggle_replace_btn.setToolTip(S.find_replace.tooltip_toggle_replace)
        self.toggle_replace_btn.setStyleSheet(self._BTN_STYLE)
        self.toggle_replace_btn.setFixedWidth(28)
        self.toggle_replace_btn.clicked.connect(self._toggle_replace)
        find_row.addWidget(self.toggle_replace_btn)

        btn_close = QPushButton("\u2715")  # multiplication X
        btn_close.setToolTip(S.find_replace.tooltip_close)
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
        self.replace_input.setPlaceholderText(S.find_replace.placeholder_replace)
        self.replace_input.setStyleSheet(self._INPUT_STYLE)
        replace_row.addWidget(self.replace_input, 1)

        btn_replace_one = QPushButton(S.find_replace.btn_replace_one)
        btn_replace_one.setToolTip(S.find_replace.tooltip_replace_one)
        btn_replace_one.setStyleSheet(self._BTN_STYLE)
        btn_replace_one.clicked.connect(self._on_replace_one)
        replace_row.addWidget(btn_replace_one)

        btn_replace_all = QPushButton(S.find_replace.btn_replace_all)
        btn_replace_all.setToolTip(S.find_replace.tooltip_replace_all)
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
# _ScintillaKeyFilter - Filtro de eventos para QScintilla
# ---------------------------------------------------------------------------

class _ScintillaKeyFilter(QObject):
    """Filtro de eventos instalado no QScintilla para controlar atalhos.

    Intercepta ShortcutOverride e KeyPress. Se a combinacao de teclas
    pertence aos atalhos do aplicativo (ex: Shift+Return para
    execute_block_advance), o evento e filtrado para que o QShortcut
    global do MainWindow possa trata-lo.

    Usa installEventFilter (nivel C++) em vez de monkey-patch do event(),
    garantindo que funcione tanto com eventos reais quanto com QTest.
    """

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def eventFilter(self, obj, evt):
        if evt.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            key = evt.key()
            if key not in (Qt.Key.Key_Control, Qt.Key.Key_Shift,
                           Qt.Key.Key_Alt, Qt.Key.Key_Meta):
                mods = evt.modifiers()
                seq = QKeySequence(mods.value | key)
                if seq.toString() in CodeEditor._app_shortcut_sequences:
                    # Atalho do app - filtrar para que QShortcut global trate
                    return True
        return False


# ---------------------------------------------------------------------------
# CodeEditor - Editor QScintilla com Find/Replace integrado
# ---------------------------------------------------------------------------

class CodeEditor(QWidget):
    """
    Editor de codigo baseado em QScintilla com Find/Replace nativo.

    - Python = lexer Python
    - SQL = lexer SQL
    - Tema dark sempre aplicado
    - Ctrl+F = Find, Ctrl+H = Find & Replace
    - Autocomplete SQL (schema) e Python (namespace)
    """

    # Atalhos da aplicacao que o editor NAO deve consumir.
    # Preenchido pelo MainWindow via set_app_shortcuts().
    _app_shortcut_sequences: set = set()

    # Mapeamento de atalhos do editor (QScintilla) configuraveis.
    # Preenchido pelo MainWindow via set_editor_shortcuts().
    _editor_shortcut_config: dict = {}

    # Mapa de acoes do editor para comandos Scintilla.
    # Cada entrada: action -> (default_scintilla_key, scintilla_command)
    # Formato do scintilla_key: keyCode + (modifiers << 16)
    # Modifiers: SCMOD_SHIFT=1, SCMOD_CTRL=2, SCMOD_ALT=4
    _SCINTILLA_BINDINGS = {
        "editor_newline": {
            "default_keys": [(13 + (1 << 16),)],  # Shift+Return
            "command": 2329,  # SCI_NEWLINE
        },
        "editor_duplicate_line": {
            "default_keys": [(ord("D") + (2 << 16),)],  # Ctrl+D
            "command": 2469,  # SCI_SELECTIONDUPLICATE
        },
        "editor_cut_line": {
            "default_keys": [(ord("L") + (2 << 16),)],  # Ctrl+L
            "command": 2337,  # SCI_LINECUT
        },
        "editor_transpose_line": {
            "default_keys": [(ord("T") + (2 << 16),)],  # Ctrl+T
            "command": 2339,  # SCI_LINETRANSPOSE
        },
        "editor_lowercase": {
            "default_keys": [(ord("U") + (2 << 16),)],  # Ctrl+U
            "command": 2340,  # SCI_LOWERCASE
        },
        "editor_uppercase": {
            "default_keys": [(ord("U") + (2 << 16) + (1 << 16),)],  # Ctrl+Shift+U
            "command": 2341,  # SCI_UPPERCASE
        },
        "editor_delete_line": {
            "default_keys": [
                (ord("K") + (2 << 16) + (1 << 16),),  # Ctrl+Shift+K
                (ord("L") + (2 << 16) + (1 << 16),),  # Ctrl+Shift+L (Scintilla default)
            ],
            "command": 2338,  # SCI_LINEDELETE
        },
    }

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

        self._apis_timer = None  # Timer para rebuild_apis debounced
        self._current_lexer_lang = None  # Cache para evitar rebuild redundante

        # Jedi completer para Python inteligente
        self._jedi_completer = JediCompleter(self)
        self._jedi_completer.completions_ready.connect(self._on_jedi_completions)
        self._jedi_timer = None  # debounce para trigger jedi
        self._global_imports = ""  # imports globais compartilhados entre blocos

        # SQL autocomplete contextual
        self._sql_completer = SqlAutoCompleteService()
        self._sql_timer = None  # debounce para trigger sql autocomplete

        self._setup_container()
        self._setup_editor()
        self._setup_lexer()
        self._setup_shortcuts()
        self._connect_signals()

        # Aplicar apenas cores do tema (lexer ja foi configurado acima)
        if self.theme_manager:
            self._apply_theme_colors()

    def closeEvent(self, event):
        """Garante shutdown do jedi thread antes de fechar."""
        if hasattr(self, '_jedi_completer') and self._jedi_completer:
            self._jedi_completer.shutdown()
        super().closeEvent(event)

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
        self._sci.textChanged.connect(self._on_text_changed)
        self._sci.SCN_FOCUSIN.connect(self._on_focus_in)
        self._sci.SCN_FOCUSOUT.connect(self._on_focus_out)
        self._sci.SCN_CHARADDED.connect(self._on_char_added)

    def _on_text_changed(self):
        """Emite ambos os sinais de texto alterado."""
        self.text_changed.emit()
        self.textChanged.emit()

    def _on_focus_in(self):
        self.SCN_FOCUSIN.emit()
        self.focus_in.emit()

    def _on_focus_out(self):
        self.SCN_FOCUSOUT.emit()
        self.focus_out.emit()

    def _on_char_added(self, char_code: int):
        """Triggered when a character is typed - requests context-aware completions."""
        ch = chr(char_code) if char_code > 0 else ""

        if self._language == "python":
            # Trigger on '.' or after typing identifier chars (with threshold)
            if ch == ".":
                self._request_jedi_completion()
            elif ch.isalnum() or ch == "_":
                if self._jedi_timer is None:
                    self._jedi_timer = QTimer(self)
                    self._jedi_timer.setSingleShot(True)
                    self._jedi_timer.timeout.connect(self._request_jedi_completion)
                self._jedi_timer.start(300)

        elif self._language == "sql":
            # Trigger SQL contextual autocomplete
            if ch == ".":
                self._request_sql_completion()
            elif ch.isalnum() or ch == "_":
                if self._sql_timer is None:
                    self._sql_timer = QTimer(self)
                    self._sql_timer.setSingleShot(True)
                    self._sql_timer.timeout.connect(self._request_sql_completion)
                self._sql_timer.start(200)

    def _request_jedi_completion(self):
        """Request jedi completions at current cursor position."""
        if not self._jedi_completer.is_available():
            return

        sci = self._sci
        line_num, col = sci.getCursorPosition()

        # Build source: global imports + current editor text
        editor_text = sci.text()
        source = self._global_imports + "\n" + editor_text if self._global_imports else editor_text

        # Adjust line number (+1 for jedi's 1-based, +N for prepended imports)
        import_lines = self._global_imports.count("\n") + 1 if self._global_imports else 0
        jedi_line = line_num + 1 + import_lines  # jedi uses 1-based lines

        self._jedi_completer.request_completions(source, jedi_line, col)

    def _on_jedi_completions(self, completions: list):
        """Handle jedi completions: populate QsciAPIs and show autocomplete."""
        if not completions:
            return

        sci = self._sci
        lexer = sci.lexer()
        if not lexer:
            return

        apis = QsciAPIs(lexer)

        # Add jedi completions
        for name, comp_type, description in completions:
            if comp_type:
                apis.add(f"{name}  ({comp_type})")
            else:
                apis.add(name)

        # Also add namespace variables
        for name, type_name in self._python_namespace.items():
            if type_name:
                apis.add(f"{name}  ({type_name})")
            else:
                apis.add(name)

        apis.prepare()
        sci.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAPIs)
        sci.autoCompleteFromAPIs()

    def _request_sql_completion(self):
        """Request contextual SQL completions at current cursor position."""
        sci = self._sci
        line_num, col = sci.getCursorPosition()
        text = sci.text()

        completions = self._sql_completer.get_completions(text, line_num, col)
        if not completions:
            return

        lexer = sci.lexer()
        if not lexer:
            return

        apis = QsciAPIs(lexer)
        for name, category, detail in completions:
            if detail:
                apis.add(f"{name}  ({detail})")
            else:
                apis.add(name)

        apis.prepare()
        sci.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAPIs)
        sci.autoCompleteFromAPIs()

    def set_global_imports(self, imports_code: str):
        """Set global imports context shared across blocks.

        Args:
            imports_code: String with import statements from all blocks.
        """
        self._global_imports = imports_code or ""

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

        # Autocompletar (desabilitado ate ter APIs reais)
        sci.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsNone)
        sci.setAutoCompletionThreshold(2)
        sci.setAutoCompletionCaseSensitivity(False)
        sci.setAutoCompletionReplaceWord(True)

        # Folding - DESABILITADO para performance
        # BoxedTreeFoldStyle recalcula fold levels no documento inteiro a cada mudanca
        sci.setFolding(QsciScintilla.FoldStyle.NoFoldStyle)

        # Whitespace e EOL
        sci.setWhitespaceVisibility(QsciScintilla.WhitespaceVisibility.WsInvisible)
        sci.setEolMode(QsciScintilla.EolMode.EolWindows)
        sci.setEolVisibility(False)

        # Scroll - largura fixa, sem tracking (evita scan de todas as linhas a cada mudanca)
        sci.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTH, 2000)
        sci.SendScintilla(QsciScintilla.SCI_SETSCROLLWIDTHTRACKING, False)

    def _setup_lexer(self):
        """Configura o lexer baseado na linguagem atual."""
        # Guard: evita rebuild se o lexer ja esta configurado para esta linguagem
        if self._current_lexer_lang == self._language:
            return
        self._current_lexer_lang = self._language

        if self._language == "sql":
            self._setup_sql_lexer()
        else:
            self._setup_python_lexer()

        # Agendar rebuild de APIs apenas se houver dados reais
        if self._sql_schema or self._python_namespace:
            self._schedule_rebuild_apis()

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

    def _schedule_rebuild_apis(self):
        """Agenda rebuild de APIs com debounce para evitar multiplas chamadas."""
        if self._apis_timer is None:
            self._apis_timer = QTimer(self)
            self._apis_timer.setSingleShot(True)
            self._apis_timer.timeout.connect(self._rebuild_apis)
        self._apis_timer.start(100)  # 100ms debounce

    def _rebuild_apis(self):
        """Reconstroi a lista de APIs de autocomplete do lexer atual."""
        sci = self._sci
        lexer = sci.lexer()
        if not lexer:
            return

        apis = QsciAPIs(lexer)
        has_entries = False

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
            has_entries = True

            # Namespace Python customizado
            for name, type_name in self._python_namespace.items():
                if type_name:
                    apis.add(f"{name}  ({type_name})")
                else:
                    apis.add(name)

        elif self._language == "sql":
            # Fallback: populate APIs with keywords + all schema items
            # (contextual completions are handled by _request_sql_completion)
            from src.services.sql_autocomplete_service import SQL_KEYWORDS
            for kw in SQL_KEYWORDS:
                apis.add(kw)
                apis.add(kw.lower())
            has_entries = True

            tables = self._sql_schema.get("tables", [])
            columns = self._sql_schema.get("columns", {})

            for table in tables:
                tname = table["name"] if isinstance(table, dict) else str(table)
                apis.add(tname)
                for col in columns.get(tname, []):
                    cname = col["name"] if isinstance(col, dict) else str(col)
                    apis.add(f"{tname}.{cname}")
                    apis.add(cname)

        if has_entries:
            apis.prepare()
            sci.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAPIs)

    def _setup_shortcuts(self):
        """Configura atalhos de teclado."""
        # Ctrl+/ - Comentar/descomentar
        shortcut_comment = QShortcut(QKeySequence("Ctrl+/"), self._sci)
        shortcut_comment.activated.connect(self.toggle_comment)

        # Instalar filtro de eventos no QScintilla para controlar prioridade
        # de atalhos.
        #
        # Usa installEventFilter (C++ level) em vez de monkey-patch do event(),
        # garantindo que funcione tanto com eventos reais quanto com QTest.
        #
        # Intercepta ShortcutOverride E KeyPress para teclas do app:
        # - ShortcutOverride: impede QScintilla de "roubar" o atalho do app.
        # - KeyPress: impede QScintilla de executar o comando interno
        #   (ex: Shift+Return -> SCI_NEWLINE) antes do QShortcut do app.
        self._key_filter = _ScintillaKeyFilter(self)
        self._sci.installEventFilter(self._key_filter)

        # Aplicar keybindings do editor (limpar defaults e reatribuir do config)
        self._apply_editor_keybindings()

    @staticmethod
    def _qt_key_to_scintilla(key_sequence_str: str):
        """Converte string de atalho Qt para codigo Scintilla (keyDef).

        Args:
            key_sequence_str: Ex: "Shift+Return", "Ctrl+D", "Ctrl+Shift+U"

        Returns:
            int com keyCode + (modifiers << 16) no formato Scintilla,
            ou None se nao for possivel converter.
        """
        if not key_sequence_str:
            return None

        # Mapa de nomes de tecla Qt -> codigo Scintilla (SCK_*)
        key_map = {
            "Return": 13, "Enter": 13,
            "Tab": 9, "Backspace": 8, "Escape": 7,
            "Delete": 308, "Del": 308,
            "Insert": 309, "Ins": 309,
            "Home": 304, "End": 305,
            "PgUp": 306, "PgDown": 307,
            "Up": 301, "Down": 300,
            "Left": 302, "Right": 303,
        }

        parts = key_sequence_str.replace(" ", "").split("+")
        scmod = 0  # SCMOD_NORM
        key_code = None

        for part in parts:
            p = part.lower()
            if p in ("ctrl", "control"):
                scmod |= 2  # SCMOD_CTRL
            elif p in ("shift",):
                scmod |= 1  # SCMOD_SHIFT
            elif p in ("alt",):
                scmod |= 4  # SCMOD_ALT
            elif p in ("meta", "super"):
                scmod |= 8  # SCMOD_SUPER
            else:
                # Tecla principal
                if part in key_map:
                    key_code = key_map[part]
                elif len(part) == 1 and part.isalpha():
                    key_code = ord(part.upper())
                else:
                    return None  # Tecla nao mapeavel

        if key_code is None:
            return None

        return key_code + (scmod << 16)

    def _apply_editor_keybindings(self):
        """Limpa keybindings internos do QScintilla e reatribui do config.

        Para cada acao em _SCINTILLA_BINDINGS:
        1. Remove as teclas default do Scintilla (SCI_CLEARCMDKEY)
        2. Se o usuario configurou uma tecla, atribui (SCI_ASSIGNCMDKEY)
        """
        sci = self._sci
        SCI_CLEARCMDKEY = 2181
        SCI_ASSIGNCMDKEY = 2180

        for action, binding in self._SCINTILLA_BINDINGS.items():
            # 1. Limpar todas as teclas default para esta acao
            for (default_key,) in binding["default_keys"]:
                sci.SendScintilla(SCI_CLEARCMDKEY, default_key)

            # 2. Se usuario configurou uma tecla, reatribuir
            user_key_str = self._editor_shortcut_config.get(action, "")
            if user_key_str:
                sci_key = self._qt_key_to_scintilla(user_key_str)
                if sci_key is not None:
                    sci.SendScintilla(SCI_ASSIGNCMDKEY, sci_key, binding["command"])

    @classmethod
    def set_app_shortcuts(cls, shortcut_keys: set):
        """Define quais key sequences sao atalhos do app.

        Chamado pelo MainWindow apos registrar seus atalhos.
        O editor NAO consumira essas combinacoes, permitindo que
        o sistema de QShortcut do app as trate.

        Args:
            shortcut_keys: Set de strings como {'Ctrl+T', 'Ctrl+S', ...}
        """
        # Normalizar para o formato do QKeySequence.toString()
        normalized = set()
        for k in shortcut_keys:
            normalized.add(QKeySequence(k).toString())
        cls._app_shortcut_sequences = normalized

    @classmethod
    def set_editor_shortcuts(cls, editor_shortcuts: dict):
        """Define mapeamento de atalhos do editor a partir do ShortcutManager.

        Args:
            editor_shortcuts: Dict com action -> key_sequence para acoes
                              que comecam com 'editor_'. Ex:
                              {'editor_newline': 'Shift+Return', ...}
        """
        cls._editor_shortcut_config = editor_shortcuts.copy()

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
        if language in ("python", "sql") and language != self._language:
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
        # Apenas atualiza cores - NAO recria lexer/APIs
        self._apply_theme_colors()

    def _apply_theme_colors(self) -> None:
        """Atualiza apenas as cores do editor sem recriar lexer/APIs."""
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
        self._sql_completer.set_schema(self._sql_schema)
        if self._language == "sql":
            self._schedule_rebuild_apis()

    def clear_sql_schema(self) -> None:
        """Limpa schema SQL do autocomplete."""
        self._sql_schema = {}
        self._sql_completer.set_schema({})
        if self._language == "sql":
            self._schedule_rebuild_apis()

    def set_python_namespace(self, namespace: dict) -> None:
        """
        Define namespace Python para autocomplete.

        Args:
            namespace: dict com {varName: typeName, ...}
        """
        self._python_namespace = namespace if namespace else {}
        if self._language == "python":
            self._schedule_rebuild_apis()

    def clear_python_namespace(self) -> None:
        """Limpa namespace Python do autocomplete."""
        self._python_namespace = {}
        if self._language == "python":
            self._schedule_rebuild_apis()

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
