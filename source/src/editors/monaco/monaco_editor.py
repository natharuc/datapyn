"""
Monaco Editor wrapper for PyQt6.

Embeds Monaco Editor (same editor used in VS Code) via QWebEngineView
to provide advanced editing features like ghost text inline completions.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtCore import (
    pyqtSignal,
    QUrl,
    QTimer,
    QEvent,
    QSettings,
    Qt,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6 import sip
from PyQt6.QtWebChannel import QWebChannel

from .monaco_bridge import MonacoBridge
from .monaco_completion_service import MonacoCompletionService
from .monaco_sql_completions import (
    PythonCompletionBuildWorker,
    SqlCompletionBuildWorker,
    build_sql_completions,
)

logger = logging.getLogger(__name__)


def _qthread_alive(worker) -> bool:
    return worker is not None and not sip.isdeleted(worker)


def _qthread_is_running(worker) -> bool:
    if not _qthread_alive(worker):
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def _qthread_request_stop(worker) -> None:
    if not _qthread_alive(worker):
        return
    try:
        if worker.isRunning():
            worker.requestInterruption()
    except RuntimeError:
        pass


class MonacoPage(QWebEnginePage):
    """Custom WebEnginePage to capture JavaScript console messages."""
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """Override to capture JS console.log messages."""
        # Log Monaco messages at debug level to reduce spam
        # Only log errors at info level
        if level == self.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.error(f"[JS L{lineNumber}] {message}")
        elif "[Monaco]" in message or "completion" in message.lower():
            logger.debug(f"[JS L{lineNumber}] {message}")


class MonacoEditor(QWidget):
    """
    Monaco Editor widget implementing ICodeEditor interface.
    
    Uses QWebEngineView to embed Monaco Editor with full syntax highlighting,
    intelligent completions, and ghost text support for Copilot suggestions.
    """
    
    # Required signals (ICodeEditor interface)
    text_changed = pyqtSignal()
    execute_requested = pyqtSignal(str)  # selected_text (empty if no selection)
    focus_in = pyqtSignal()
    focus_out = pyqtSignal()
    
    # Compatibility signals (for blocks expecting QScintilla signals)
    SCN_FOCUSIN = pyqtSignal()
    SCN_FOCUSOUT = pyqtSignal()
    textChanged = pyqtSignal()
    
    # Completion signals
    completion_requested = pyqtSignal(str, str, int, int)
    force_completion_requested = pyqtSignal(str, str, int, int)  # bypasses throttling
    
    # Cursor position signal
    cursor_changed = pyqtSignal(int, int)  # line, column (1-based)

    SETTINGS_KEY_FONT_SIZE = "editor/code_font_size"
    DEFAULT_FONT_SIZE = 13
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 32
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        theme_manager=None,
        read_only: bool = False,
    ):
        super().__init__(parent)
        
        self.theme_manager = theme_manager
        self._language = "python"
        self._theme_name = "dark"
        self._text_cache = ""
        self._is_ready = False
        self._pending_operations = []
        self._read_only = read_only
        self._cleaned_up = False
        self._font_size = self._load_font_size()
        
        # SQL/Python autocomplete data
        self._sql_schema: Dict[str, Any] = {}
        self._sql_completion_worker: Optional[SqlCompletionBuildWorker] = None
        self._sql_completion_generation = 0
        self._python_completion_worker: Optional[PythonCompletionBuildWorker] = None
        self._python_completion_generation = 0
        self._selected_text_cache = ""
        self._has_selection_cache = False
        self._current_line_cache = 0
        self._python_namespace: Dict[str, Any] = {}
        self._global_imports: str = ""
        self._completion_service = MonacoCompletionService(self)
        
        self._setup_ui()
        self._setup_channel()
        self._load_editor()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the widget layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self._web_view = QWebEngineView(self)
        
        # Use custom page to capture JS console messages
        self._page = MonacoPage(self._web_view)
        self._page.setBackgroundColor(QColor("#1e1e1e"))  # Evita flash branco
        self._web_view.setPage(self._page)
        
        self._web_view.setContextMenuPolicy(
            self._web_view.contextMenuPolicy()
        )
        self._web_view.setMinimumSize(200, 80)
        
        # Enable loading remote content (Monaco CDN) from local file
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        settings = self._web_view.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        
        # Make QWebEngineView focusable and accept keyboard input
        self._web_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._web_view.installEventFilter(self)
        
        layout.addWidget(self._web_view)
        
        # Set minimum size for the widget itself
        self.setMinimumSize(200, 80)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocusProxy(self._web_view)

    def cleanup(self):
        """Release WebEngine resources owned by the editor."""
        if self._cleaned_up:
            return

        self._cleaned_up = True
        self._is_ready = False
        self._pending_operations.clear()
        _qthread_request_stop(self._sql_completion_worker)
        self._sql_completion_worker = None
        _qthread_request_stop(self._python_completion_worker)
        self._python_completion_worker = None
        if hasattr(self, "_completion_service") and self._completion_service is not None:
            self._completion_service.cancel()

        web_view = getattr(self, "_web_view", None)
        if web_view is not None and not sip.isdeleted(web_view):
            try:
                web_view.stop()
                page = web_view.page()
                if page is not None and not sip.isdeleted(page):
                    try:
                        page.setWebChannel(None)
                    except (RuntimeError, TypeError):
                        pass
                    replacement_page = QWebEnginePage(web_view)
                    web_view.setPage(replacement_page)
                    sip.delete(page)
                web_view.close()
            except RuntimeError:
                pass
            try:
                sip.delete(web_view)
            except RuntimeError:
                pass

        self._web_view = None
        self._page = None
        self._channel = None
        self._bridge = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def deleteLater(self):
        self.cleanup()
        super().deleteLater()

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.cleanup()
        return super().event(event)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_web_view", None) and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if self._handle_zoom_wheel(event.angleDelta().y()):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)
    
    def _setup_channel(self):
        """Setup QWebChannel for Python<->JS communication."""
        self._channel = QWebChannel(self._web_view.page())
        self._bridge = MonacoBridge(self)
        self._channel.registerObject("pyBridge", self._bridge)
        self._web_view.page().setWebChannel(self._channel)
    
    def _load_editor(self):
        """Load the Monaco editor HTML template."""
        template_path = self._get_template_path()
        
        if template_path and template_path.exists():
            # Load from local file - LocalContentCanAccessRemoteUrls enabled in _setup_ui
            logger.debug(f"[MONACO] Loading template from: {template_path}")
            self._web_view.setUrl(QUrl.fromLocalFile(str(template_path)))
        else:
            # Fallback: load from string
            logger.warning(f"[MONACO] Template not found, using fallback HTML. Tried: {template_path}")
            html = self._get_fallback_html()
            self._web_view.setHtml(html, QUrl("https://unpkg.com/"))
    
    def _get_template_path(self) -> Optional[Path]:
        """Get the path to monaco_template.html, handling PyInstaller packaging."""
        import sys
        
        # Check if running in PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running in PyInstaller bundle - look in _MEIPASS
            base_path = Path(sys._MEIPASS)
            template_path = base_path / "src" / "editors" / "monaco" / "monaco_template.html"
            if template_path.exists():
                return template_path
            # Also try relative to executable
            exe_path = Path(sys.executable).parent
            template_path = exe_path / "src" / "editors" / "monaco" / "monaco_template.html"
            if template_path.exists():
                return template_path
        
        # Development mode - use relative path from __file__
        template_path = Path(__file__).parent / "monaco_template.html"
        return template_path
    
    def _get_fallback_html(self) -> str:
        """Return minimal fallback HTML if template not found."""
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Editor</title></head>
        <body style="background:#1e1e1e;margin:0;">
        </body>
        </html>
        """
    
    def _connect_signals(self):
        """Connect bridge signals to editor signals."""
        # Bridge -> Editor signals
        self._bridge.editor_ready.connect(self._on_editor_ready)
        self._bridge.text_changed.connect(self._on_text_changed)
        self._bridge.focus_in.connect(self._on_focus_in)
        self._bridge.focus_out.connect(self._on_focus_out)
        self._bridge.execute_requested.connect(self._on_execute_requested)
        self._bridge.completion_requested.connect(self._on_completion_requested)
        self._bridge.force_completion_requested.connect(self._on_force_completion_requested)
        self._bridge.cursor_changed.connect(self._on_cursor_changed)
        self._bridge.selection_changed.connect(self._on_selection_changed)
        
        # SQL/Python context-aware completions
        self._bridge.sql_context_requested.connect(self._on_sql_context_requested)
        self._bridge.sql_completion_requested.connect(self._on_sql_completion_requested)
        self._bridge.python_completion_requested.connect(self._on_python_completion_requested)

        self._completion_service.sql_completions_ready.connect(self._deliver_sql_completions)
        self._completion_service.sql_context_completions_ready.connect(self._deliver_sql_context_completions)
        self._completion_service.python_completions_ready.connect(self._deliver_python_completions)
    
    def _deliver_sql_completions(self, request_id: int, completions: list) -> None:
        payload = json.dumps(completions or [])
        self._run_js_when_ready(f"receiveSqlCompletions({int(request_id)}, {payload})")

    def _deliver_sql_context_completions(self, request_id: int, completions: list) -> None:
        payload = json.dumps(completions or [])
        self._run_js_when_ready(f"receiveSqlContextCompletions({int(request_id)}, {payload})")

    def _deliver_python_completions(self, request_id: int, completions: list) -> None:
        payload = json.dumps(completions or [])
        self._run_js_when_ready(f"receivePythonCompletions({int(request_id)}, {payload})")
    def _on_editor_ready(self):
        """Called when Monaco editor is fully loaded."""
        if self._cleaned_up:
            return

        self._is_ready = True
        
        # Apply pending operations
        for operation, args, _replace_key in self._pending_operations:
            operation(*args)
        self._pending_operations.clear()
        
        # Apply initial theme
        self.apply_theme()
        self._apply_font_size()
        
        # Apply read-only state
        if self._read_only:
            self._run_js("setReadOnly(true)")
    
    def _on_text_changed(self, text: str):
        """Handle text change from JS."""
        self._text_cache = text
        self.text_changed.emit()
        self.textChanged.emit()
    
    def _on_focus_in(self):
        """Handle focus in from JS."""
        self.focus_in.emit()
        self.SCN_FOCUSIN.emit()
    
    def _on_focus_out(self):
        """Handle focus out from JS."""
        self.focus_out.emit()
        self.SCN_FOCUSOUT.emit()
    
    def _on_execute_requested(self, selected_text: str):
        """Handle execution request from JS."""
        self.execute_requested.emit(selected_text)
    
    def _on_completion_requested(self, prefix: str, suffix: str, line: int, column: int):
        """Handle inline completion request from JS."""
        self.completion_requested.emit(prefix, suffix, line, column)
    
    def _on_force_completion_requested(self, prefix: str, suffix: str, line: int, column: int):
        """Handle force inline completion request from JS (Ctrl+.)."""
        self.force_completion_requested.emit(prefix, suffix, line, column)
    
    def _on_cursor_changed(self, line: int, column: int):
        """Handle cursor position change from JS."""
        self._current_line_cache = max(0, int(line or 1) - 1)
        self.cursor_changed.emit(line, column)

    def _on_selection_changed(self, text: str, has_selection: bool):
        self._selected_text_cache = text or ""
        self._has_selection_cache = bool(has_selection)
    
    def _on_sql_context_requested(self, full_text: str, prefix: str, line: int, column: int, request_id: int):
        """Handle SQL context-aware completion request off the UI thread."""
        self._completion_service.set_sql_schema(self._sql_schema)
        self._completion_service.request_sql_context(request_id, full_text, prefix, line, column)
    
    def _on_sql_completion_requested(self, full_text: str, line: int, column: int, request_id: int):
        """Handle SQL completion request off the UI thread."""
        self._completion_service.set_sql_schema(self._sql_schema)
        self._completion_service.request_sql_completions(request_id, full_text, line, column)

    def _on_python_completion_requested(self, full_text: str, line: int, column: int, request_id: int):
        """Handle Python Jedi completion request off the UI thread."""
        self._completion_service.set_python_context(self._python_namespace, self._global_imports)
        self._completion_service.request_python_completions(request_id, full_text, line, column)

    def _run_js(self, script: str, callback=None):
        """Execute JavaScript in the Monaco editor."""
        web_view = getattr(self, "_web_view", None)
        if self._cleaned_up or web_view is None or sip.isdeleted(web_view):
            return

        if callback:
            web_view.page().runJavaScript(script, callback)
        else:
            web_view.page().runJavaScript(script)
    
    def _run_js_when_ready(self, script: str, callback=None, replace_key: str | None = None):
        """Execute JS when ready, or queue if not ready yet."""
        if self._cleaned_up:
            return

        if self._is_ready:
            # Log completion-related JS calls at debug level (less spam)
            if "receiveCompletion" in script:
                logger.debug(f"[MONACO] Running JS: {script[:80]}...")
            self._run_js(script, callback)
        else:
            logger.debug(f"[MONACO] Queueing JS (not ready): {script[:40]}...")
            if replace_key is not None:
                self._pending_operations = [
                    (pending_operation, pending_args, pending_key)
                    for pending_operation, pending_args, pending_key in self._pending_operations
                    if pending_key != replace_key
                ]
            self._pending_operations.append(
                (lambda s=script, cb=callback: self._run_js(s, cb), (), replace_key)
            )
    
    # === ICodeEditor Interface ===
    
    def get_text(self) -> str:
        """Returns all editor text."""
        return self._text_cache
    
    def set_text(self, text: str) -> None:
        """Sets the editor text."""
        self._text_cache = text
        escaped = json.dumps(text)
        self._run_js_when_ready(f"setValue({escaped})", replace_key="editor:setValue")
    
    def force_request_completion(self) -> None:
        """Force trigger an inline completion request (Ctrl+. shortcut)."""
        self._run_js_when_ready("forceRequestCompletion()")
    
    def get_selected_text(self) -> str:
        """Returns selected text from the latest JS selection snapshot."""
        return self._selected_text_cache
    
    def has_selection(self) -> bool:
        """Checks if there is selected text using the cached JS snapshot."""
        return self._has_selection_cache
    
    def selectAll(self) -> None:
        """Selects all text in the editor."""
        if self._is_ready:
            self._web_view.page().runJavaScript("selectAll()")
    
    def clear(self) -> None:
        """Clears all editor text."""
        self.set_text("")
    
    def set_language(self, language: str) -> None:
        """Sets the language for syntax highlighting."""
        self._language = language
        # Map DataPyn languages to Monaco languages
        monaco_lang = {
            "python": "python",
            "sql": "sql",
            "cross": "python",  # Default to Python for cross
        }.get(language, "python")
        
        escaped = json.dumps(monaco_lang)
        self._run_js_when_ready(f"setLanguage({escaped})")
    
    def get_language(self) -> str:
        """Returns the current language."""
        return self._language
    
    def set_theme(self, theme_name: str) -> None:
        """Sets the editor theme."""
        self._theme_name = theme_name
        self.apply_theme()
    
    def apply_theme(self) -> None:
        """Applies the current ThemeManager theme."""
        if not self._is_ready:
            return
        
        # Get theme colors
        theme_data = self._get_theme_data()
        if theme_data:
            theme_json = json.dumps(theme_data)
            theme_name = json.dumps(f"datapyn-{self._theme_name}")
            self._run_js(f"setCustomTheme({theme_name}, {theme_json})")
            
            # Set background color
            bg = theme_data.get("background", "#1e1e1e")
            self._run_js(f"setBackgroundColor('{bg}')")
    
    def _get_theme_data(self) -> Optional[Dict[str, Any]]:
        """Get theme data for Monaco from ThemeManager."""
        if not self.theme_manager:
            return None
        
        try:
            theme = self.theme_manager.get_theme()
            editor_colors = theme.get("editor", {})
            
            # Determine if dark theme
            bg = editor_colors.get("background", "#1e1e1e")
            is_dark = self._is_dark_color(bg)
            
            # Get syntax colors based on language
            syntax_colors = theme.get(self._language, theme.get("python", {}))
            
            return {
                "isDark": is_dark,
                "background": editor_colors.get("background", "#1e1e1e"),
                "foreground": editor_colors.get("foreground", "#d4d4d4"),
                "caret": editor_colors.get("caret", "#ffffff"),
                "caretLine": editor_colors.get("caret_line", "#2a2a2a"),
                "selection": editor_colors.get("selection", "#264f78"),
                "marginBg": editor_colors.get("margin_bg", "#1e1e1e"),
                "marginFg": editor_colors.get("margin_fg", "#858585"),
                "syntax": syntax_colors,
            }
        except Exception:
            return None
    
    def _is_dark_color(self, hex_color: str) -> bool:
        """Check if a hex color is dark."""
        try:
            hex_color = hex_color.lstrip("#")
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return luminance < 0.5
        except Exception:
            return True
    
    def set_font(self, family: str, size: int) -> None:
        """Sets the editor font."""
        escaped_family = json.dumps(family)
        self._run_js_when_ready(f"setFontFamily({escaped_family})")
        self.set_font_size(size)

    def set_font_size(self, size: int, persist: bool = True) -> int:
        """Set and optionally persist the Monaco editor font size."""
        font_size = self._clamp_font_size(size)
        self._font_size = font_size
        if persist:
            self._save_font_size(font_size)
        self._apply_font_size()
        return font_size

    def get_font_size(self) -> int:
        """Return current Monaco editor font size."""
        return self._font_size

    def _handle_zoom_wheel(self, delta: int) -> bool:
        if delta == 0:
            return False
        step = 1 if delta > 0 else -1
        self.set_font_size(self._font_size + step)
        return True

    def _apply_font_size(self):
        self._run_js_when_ready(f"setFontSize({self._font_size})", replace_key="editor:fontSize")

    @classmethod
    def _clamp_font_size(cls, size: int) -> int:
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = cls.DEFAULT_FONT_SIZE
        return max(cls.MIN_FONT_SIZE, min(cls.MAX_FONT_SIZE, value))

    @classmethod
    def _load_font_size(cls) -> int:
        settings = QSettings("DataPyn", "DataPyn")
        return cls._clamp_font_size(settings.value(cls.SETTINGS_KEY_FONT_SIZE, cls.DEFAULT_FONT_SIZE))

    @classmethod
    def _save_font_size(cls, size: int):
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue(cls.SETTINGS_KEY_FONT_SIZE, cls._clamp_font_size(size))
    
    def set_read_only(self, read_only: bool) -> None:
        """Sets if editor is read-only."""
        self._read_only = read_only
        self._run_js_when_ready(f"setReadOnly({'true' if read_only else 'false'})")
    
    def set_line_numbers_visible(self, visible: bool) -> None:
        """Sets if line numbers are visible."""
        self._run_js_when_ready(f"setLineNumbers({'true' if visible else 'false'})")
    
    def get_line_count(self) -> int:
        """Returns the number of lines."""
        return len(self._text_cache.split("\n"))
    
    def get_current_line(self) -> int:
        """Returns the current cursor line (0-indexed) from the cached snapshot."""
        return self._current_line_cache
    
    def go_to_line(self, line: int) -> None:
        """Moves cursor to the specified line (0-indexed)."""
        self._run_js_when_ready(f"goToLine({line})")

    def highlight_lines(self, start_line: int, end_line: int, duration_ms: int = 2000) -> None:
        """Temporarily highlight a range of lines (1-based) with a purple glow.
        
        Used to visually indicate lines that Copilot just edited.
        The highlight fades automatically after duration_ms.
        """
        self._run_js_when_ready(
            f"highlightLines({start_line}, {end_line}, {duration_ms})"
        )

    def get_widget(self) -> QWidget:
        """Returns the Qt widget of the editor."""
        return self
    
    # === Additional Methods ===
    
    def set_sql_schema(self, schema: dict) -> None:
        """Set SQL schema for autocompletion."""
        schema = schema or {}
        logger.debug("[MONACO] set_sql_schema called with %s tables", len(schema.get('tables', [])))
        self._sql_schema = schema
        self._completion_service.set_sql_schema(schema)
        if schema:
            self.update_sql_completions(schema)
            return
        self.clear_sql_completions()

    def clear_sql_completions(self) -> None:
        """Clear Monaco SQL completions so a new schema can be loaded cleanly."""
        self._sql_schema = {}
        self.register_completions([])
    
    def set_python_namespace(self, namespace: dict) -> None:
        """Set Python namespace for autocompletion."""
        self._python_namespace = namespace
        self._completion_service.set_python_context(namespace, self._global_imports)
        # Register Python completions in Monaco
        self.update_python_completions(namespace)
    
    def set_global_imports(self, imports_code: str) -> None:
        """Set global imports for Jedi completion."""
        self._global_imports = imports_code
        self._completion_service.set_python_context(self._python_namespace, imports_code)
    
    def insert_text_at_cursor(self, text: str) -> None:
        """Insert text at current cursor position."""
        escaped = json.dumps(text)
        self._run_js_when_ready(f"insertTextAtCursor({escaped})")
    
    def toggle_comment(self) -> None:
        """Toggle comment on current line/selection."""
        self._run_js_when_ready(
            "editor.getAction('editor.action.commentLine').run()"
        )
    
    def setFocus(self) -> None:
        """Set focus to the editor."""
        super().setFocus()
        self._run_js_when_ready("focusEditor()")
    
    def show_find(self) -> None:
        """Show the find widget."""
        self._run_js_when_ready("showFindWidget()")
    
    def show_find_replace(self) -> None:
        """Show the find and replace widget."""
        self._run_js_when_ready("showReplaceWidget()")
    
    # Compatibility methods for main_window shortcuts
    def _open_find(self) -> None:
        """Alias for show_find - compatibility with code_editor."""
        self.show_find()
    
    def _open_replace(self) -> None:
        """Alias for show_find_replace - compatibility with code_editor."""
        self.show_find_replace()
    
    # === Completion API ===
    
    def provide_completion(self, text: str) -> None:
        """
        Provide an inline completion (ghost text) to the editor.
        
        Called by the completion service after getting a suggestion from Copilot.
        
        Args:
            text: The completion text to show as ghost text
        """
        logger.debug(f"[MONACO] provide_completion called: {len(text) if text else 0} chars, is_ready={self._is_ready}")
        if not text:
            logger.debug("[MONACO] provide_completion: empty text, skipping")
            return
        escaped = json.dumps(text)
        logger.debug(f"[MONACO] Calling receiveCompletion with {len(escaped)} escaped chars")
        self._run_js_when_ready(f"receiveCompletion({escaped})")
    
    def register_completions(self, completions: list) -> None:
        """
        Register standard completions (non-Copilot autocomplete).
        
        Args:
            completions: List of completion items, each with:
                - label: Display text
                - kind: Type (keyword, function, variable, class, table, etc)
                - insertText: Text to insert (optional, defaults to label)
                - detail: Additional info (optional)
        """
        completions_json = json.dumps(completions or [])
        self._run_js_when_ready(f"registerCompletions({completions_json})")
    
    def update_sql_completions(self, schema: Optional[dict]) -> None:
        """Update SQL autocomplete with database schema (built off the UI thread)."""
        if not schema:
            return

        self._sql_completion_generation += 1
        generation = self._sql_completion_generation

        _qthread_request_stop(self._sql_completion_worker)

        worker = SqlCompletionBuildWorker(generation, schema, self)
        worker.completions_ready.connect(self._on_sql_completions_built)
        worker.finished.connect(lambda w=worker: self._release_sql_completion_worker(w))
        worker.finished.connect(worker.deleteLater)
        self._sql_completion_worker = worker
        worker.start()

    def _release_sql_completion_worker(self, worker: SqlCompletionBuildWorker) -> None:
        if self._sql_completion_worker is worker:
            self._sql_completion_worker = None

    def _on_sql_completions_built(self, generation: int, completions: list) -> None:
        if generation != self._sql_completion_generation:
            return
        tables = len(self._sql_schema.get("tables", [])) if self._sql_schema else 0
        columns = sum(len(cols) for cols in (self._sql_schema.get("columns") or {}).values())
        logger.debug(
            "[MONACO] Registering %s contextual SQL completions (%s tables, %s columns)",
            len(completions),
            tables,
            columns,
        )
        self.register_completions(completions)
    
    def update_python_completions(self, variables: Optional[dict]) -> None:
        """Update Python autocomplete with namespace variables (built off the UI thread)."""
        if not variables:
            return

        self._python_completion_generation += 1
        generation = self._python_completion_generation

        _qthread_request_stop(self._python_completion_worker)

        worker = PythonCompletionBuildWorker(generation, variables, self)
        worker.completions_ready.connect(self._on_python_completions_built)
        worker.finished.connect(lambda w=worker: self._release_python_completion_worker(w))
        worker.finished.connect(worker.deleteLater)
        self._python_completion_worker = worker
        worker.start()

    def _release_python_completion_worker(self, worker: PythonCompletionBuildWorker) -> None:
        if self._python_completion_worker is worker:
            self._python_completion_worker = None

    def _on_python_completions_built(self, generation: int, completions: list) -> None:
        if generation != self._python_completion_generation:
            return
        logger.debug(
            "[MONACO] Registering %s Python completions",
            len(completions),
        )
        self.register_completions(completions)
