"""
MonacoEditor - Implementacao do editor de codigo usando Monaco Editor.

Embeds Monaco Editor (VS Code editor) via QWebEngineView + QWebChannel.
Implementa a interface ICodeEditor seguindo o principio de Inversao de Dependencia.
"""

import sys
import os
import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QObject, QUrl, QTimer, QEventLoop
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel


MONACO_AVAILABLE = True

# Path to the HTML file - supports both dev and PyInstaller frozen mode
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).parent
_MONACO_HTML = str(_BASE_DIR / "monaco" / "monaco.html")


class _MonacoBridge(QObject):
    """
    Bridge object exposed to JavaScript via QWebChannel.
    Receives events from Monaco Editor and emits Qt signals.
    """

    # Signals forwarded from JS
    text_changed_signal = pyqtSignal()  # lightweight: content changed
    text_synced_signal = pyqtSignal(str)  # debounced: full text payload
    execute_requested_signal = pyqtSignal()
    focus_in_signal = pyqtSignal()
    focus_out_signal = pyqtSignal()
    cursor_changed_signal = pyqtSignal(int, int)
    editor_ready_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(str)
    def onTextChanged(self, _text):
        """Called from JS immediately on each keystroke (no payload)."""
        self.text_changed_signal.emit()

    @pyqtSlot(str)
    def onTextSynced(self, text):
        """Called from JS after debounce with full text content."""
        self.text_synced_signal.emit(text)

    @pyqtSlot()
    def onExecuteRequested(self):
        """Called from JS when user presses Ctrl+Enter / Shift+Enter / F5."""
        self.execute_requested_signal.emit()

    @pyqtSlot()
    def onFocusIn(self):
        """Called from JS when editor gains focus."""
        self.focus_in_signal.emit()

    @pyqtSlot()
    def onFocusOut(self):
        """Called from JS when editor loses focus."""
        self.focus_out_signal.emit()

    @pyqtSlot(int, int)
    def onCursorChanged(self, line, column):
        """Called from JS when cursor position changes."""
        self.cursor_changed_signal.emit(line, column)

    @pyqtSlot()
    def onEditorReady(self):
        """Called from JS when Monaco is fully loaded and ready."""
        self.editor_ready_signal.emit()

    @pyqtSlot(str)
    def onError(self, message):
        """Called from JS on error."""
        self.error_signal.emit(message)


class _MonacoPage(QWebEnginePage):
    """Custom page to suppress console messages in production."""

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Only show errors in console, suppress info/warnings
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            # Suppress known non-critical errors (bridge timing, GPU)
            if "bridge" in message.lower() and "not a function" in message.lower():
                return
            import logging

            logging.getLogger("MonacoEditor").debug(f"JS Error: {message}")


class MonacoEditor(QWidget):
    """
    Editor de codigo baseado em Monaco Editor (VS Code).

    Usa QWebEngineView para hospedar o Monaco Editor.
    Comunicacao bidirecional via QWebChannel.
    Mantem mirror do texto/estado em Python para acesso sincrono.
    """

    # Signals da interface ICodeEditor
    text_changed = pyqtSignal()
    execute_requested = pyqtSignal()
    focus_in = pyqtSignal()
    focus_out = pyqtSignal()

    # Signals de compatibilidade com CodeEditor (QScintilla)
    SCN_FOCUSIN = pyqtSignal()
    SCN_FOCUSOUT = pyqtSignal()

    # Signal nativo de compatibilidade com QsciScintilla.textChanged
    textChanged = pyqtSignal()

    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._language = "python"
        self._theme_name = "dark"
        self._is_ready = False
        self._pending_calls = []

        # Mirror text for synchronous access
        self._text = ""
        self._dirty = False
        self._current_line = 0
        self._current_column = 0
        self._selected_text = ""
        self._has_selection = False
        self._focus_pending = False

        self._setup_ui()
        self._setup_bridge()
        self._load_editor()

    def _setup_ui(self):
        """Create layout with QWebEngineView."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._page = _MonacoPage(self)

        # Enable settings for better integration
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        layout.addWidget(self._view)

        # Route keyboard focus directly to QWebEngineView
        self.setFocusProxy(self._view)

    def _setup_bridge(self):
        """Setup QWebChannel bridge for Python <-> JS communication."""
        self._bridge = _MonacoBridge(self)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)

        # Connect bridge signals
        self._bridge.text_changed_signal.connect(self._on_text_changed)
        self._bridge.text_synced_signal.connect(self._on_text_synced)
        self._bridge.execute_requested_signal.connect(self._on_execute_requested)
        self._bridge.focus_in_signal.connect(self._on_focus_in)
        self._bridge.focus_out_signal.connect(self._on_focus_out)
        self._bridge.cursor_changed_signal.connect(self._on_cursor_changed)
        self._bridge.editor_ready_signal.connect(self._on_editor_ready)

    def _load_editor(self):
        """Load Monaco HTML file."""
        url = QUrl.fromLocalFile(_MONACO_HTML)
        self._page.load(url)

    def _on_editor_ready(self):
        """Called when Monaco is fully loaded."""
        self._is_ready = True

        # Apply pending language
        if self._language:
            self._run_js(f"api_setLanguage({json.dumps(self._language)})")

        # Apply pending text
        if self._text:
            escaped = json.dumps(self._text)
            self._run_js(f"api_setText({escaped})")

        # Apply theme
        if self.theme_manager:
            self.apply_theme()

        # Execute pending calls
        for js_code in self._pending_calls:
            self._run_js(js_code)
        self._pending_calls.clear()

        # Auto-focus if requested while loading
        if self._focus_pending:
            self._focus_pending = False
            QTimer.singleShot(30, self._do_focus)

    def _run_js(self, code, callback=None):
        """
        Execute JavaScript in the Monaco page.
        If editor not ready, queue the call.
        """
        if not self._is_ready:
            self._pending_calls.append(code)
            return
        if callback:
            self._page.runJavaScript(code, callback)
        else:
            self._page.runJavaScript(code)

    # === Event handlers from JS bridge ===

    def _on_text_changed(self):
        """Handle lightweight text-change notification (no payload)."""
        self._dirty = True
        self.text_changed.emit()
        self.textChanged.emit()

    def _on_text_synced(self, text):
        """Handle debounced full-text sync from JS."""
        self._text = text
        self._dirty = False

    def _on_execute_requested(self):
        """Handle execute request from Monaco."""
        self.execute_requested.emit()

    def _on_focus_in(self):
        """Handle focus in from Monaco."""
        self.focus_in.emit()
        self.SCN_FOCUSIN.emit()

    def _on_focus_out(self):
        """Handle focus out from Monaco."""
        self.focus_out.emit()
        self.SCN_FOCUSOUT.emit()

    def _on_cursor_changed(self, line, column):
        """Handle cursor position change from Monaco."""
        self._current_line = line
        self._current_column = column

    # === Implementacao da Interface ICodeEditor ===

    def get_text(self) -> str:
        """Retorna todo o texto do editor.

        Se houver mudancas pendentes (dirty), busca direto do JS.
        Caso contrario, usa o mirror local.
        """
        if self._dirty and self._is_ready:
            result = [None]
            loop = QEventLoop()

            def callback(val):
                result[0] = val if val else ""
                loop.quit()

            self._page.runJavaScript("api_getText()", callback)
            QTimer.singleShot(300, loop.quit)
            loop.exec()
            if result[0] is not None:
                self._text = result[0]
                self._dirty = False
        return self._text

    def set_text(self, text: str) -> None:
        """Define o texto do editor."""
        self._text = text
        self._dirty = False
        escaped = json.dumps(text)
        self._run_js(f"api_setText({escaped})")

    def get_selected_text(self) -> str:
        """Retorna o texto selecionado ou string vazia."""
        # Use synchronous JS call with event loop for accurate results
        if not self._is_ready:
            return ""
        result = [None]
        loop = QEventLoop()

        def callback(val):
            result[0] = val if val else ""
            loop.quit()

        self._page.runJavaScript("api_getSelectedText()", callback)
        QTimer.singleShot(500, loop.quit)  # timeout safety
        loop.exec()
        return result[0] if result[0] is not None else ""

    def has_selection(self) -> bool:
        """Verifica se ha texto selecionado."""
        if not self._is_ready:
            return False
        result = [None]
        loop = QEventLoop()

        def callback(val):
            result[0] = bool(val) if val is not None else False
            loop.quit()

        self._page.runJavaScript("api_hasSelection()", callback)
        QTimer.singleShot(500, loop.quit)  # timeout safety
        loop.exec()
        return result[0] if result[0] is not None else False

    def clear(self) -> None:
        """Limpa todo o texto do editor."""
        self._text = ""
        self._dirty = False
        self._run_js('api_setText("")')

    def set_language(self, language: str) -> None:
        """Define a linguagem e atualiza o highlighting."""
        language = language.lower()
        if language in ("python", "sql", "cross"):
            self._language = language
            self._run_js(f"api_setLanguage({json.dumps(language)})")

    def get_language(self) -> str:
        """Retorna a linguagem atual."""
        return self._language

    def set_theme(self, theme_name: str) -> None:
        """Define o tema do editor."""
        self._theme_name = theme_name
        self._run_js(f"api_setTheme({json.dumps(theme_name)})")

    def apply_theme(self) -> None:
        """Aplica/atualiza o tema atual do ThemeManager."""
        if not self.theme_manager:
            return
        # Monaco handles theming internally; just set the theme
        self._run_js('api_setTheme("datapyn-dark")')

    def set_font(self, family: str, size: int) -> None:
        """Define a fonte do editor."""
        self._run_js(f"api_setFont({json.dumps(family)}, {size})")

    def set_read_only(self, read_only: bool) -> None:
        """Define se o editor e somente leitura."""
        val = "true" if read_only else "false"
        self._run_js(f"api_setReadOnly({val})")

    def set_line_numbers_visible(self, visible: bool) -> None:
        """Define se os numeros de linha sao visiveis."""
        val = "true" if visible else "false"
        self._run_js(f"api_setLineNumbers({val})")

    def get_line_count(self) -> int:
        """Retorna o numero de linhas."""
        return self._text.count("\n") + 1 if self._text else 1

    def get_current_line(self) -> int:
        """Retorna a linha atual do cursor (0-indexed)."""
        return self._current_line

    def go_to_line(self, line: int) -> None:
        """Move o cursor para a linha especificada (0-indexed)."""
        self._run_js(f"api_goToLine({line})")

    def get_widget(self) -> QWidget:
        """Retorna o widget Qt do editor."""
        return self

    # === Metodos auxiliares ===

    def toggle_comment(self):
        """Comenta/descomenta a linha ou selecao atual.
        Monaco tem suporte nativo via Ctrl+/ (nao precisa implementar)."""
        self._run_js("""
            editor.trigger('keyboard', 'editor.action.commentLine');
        """)

    # === Eventos de foco ===

    def focusInEvent(self, event):
        """Sobrescreve evento de foco para emitir sinal."""
        super().focusInEvent(event)
        self.SCN_FOCUSIN.emit()

    def focusOutEvent(self, event):
        """Sobrescreve evento de perda de foco para emitir sinal."""
        super().focusOutEvent(event)
        self.SCN_FOCUSOUT.emit()

    def setFocus(self):
        """Override setFocus to also focus the Monaco editor inside."""
        if not self._is_ready:
            self._focus_pending = True
            return
        # Small delay to let Qt settle the widget focus before JS focus
        QTimer.singleShot(30, self._do_focus)

    def _do_focus(self):
        """Perform actual focus: Qt widget + Monaco JS."""
        self._view.setFocus()
        self._run_js("api_focus()")

    def text(self):
        """Compatibility method - returns full text like QsciScintilla."""
        return self.get_text()

    def setText(self, text):
        """Compatibility method - sets text like QsciScintilla."""
        self.set_text(text)

    def selectedText(self):
        """Compatibility method."""
        return self.get_selected_text()

    def hasSelectedText(self):
        """Compatibility method."""
        return self.has_selection()

    def lines(self):
        """Compatibility method - returns line count like QsciScintilla."""
        return self.get_line_count()

    def getCursorPosition(self):
        """Compatibility method - returns (line, index) like QsciScintilla."""
        return (self._current_line, self._current_column)

    def setCursorPosition(self, line, index):
        """Compatibility method."""
        self._run_js(f"""
            if (editor) {{
                editor.setPosition({{ lineNumber: {line + 1}, column: {index + 1} }});
            }}
        """)

    def ensureLineVisible(self, line):
        """Compatibility method."""
        self._run_js(f"""
            if (editor) {{
                editor.revealLineInCenter({line + 1});
            }}
        """)

    def setReadOnly(self, read_only):
        """Compatibility method."""
        self.set_read_only(read_only)

    def selectAll(self):
        """Compatibility method - select all text like QsciScintilla."""
        self._run_js("""
            if (editor) {
                var model = editor.getModel();
                var lastLine = model.getLineCount();
                var lastCol = model.getLineMaxColumn(lastLine);
                editor.setSelection(new monaco.Range(1, 1, lastLine, lastCol));
            }
        """)

    def resizeEvent(self, event):
        """Handle resize - automaticLayout handles Monaco sizing."""
        super().resizeEvent(event)

    # === Autocomplete & Code Suggestions ===

    def set_sql_schema(self, schema: dict) -> None:
        """
        Envia schema do banco para o Monaco para autocomplete SQL.

        Args:
            schema: dict com {tables: [...], columns: {...}, database: ''}
        """
        escaped = json.dumps(schema)
        self._run_js(f"api_setSqlSchema({json.dumps(escaped)})")

    def clear_sql_schema(self) -> None:
        """Limpa schema SQL do autocomplete"""
        self._run_js("api_clearSqlSchema()")

    def set_python_namespace(self, namespace: dict) -> None:
        """
        Envia namespace Python para o Monaco para autocomplete.

        Args:
            namespace: dict com {varName: typeName, ...}
                       ex: {'df': 'DataFrame', 'x': 'int', 'os': 'module'}
        """
        escaped = json.dumps(namespace)
        self._run_js(f"api_setPythonNamespace({json.dumps(escaped)})")

    def clear_python_namespace(self) -> None:
        """Limpa namespace Python do autocomplete"""
        self._run_js("api_clearPythonNamespace()")
