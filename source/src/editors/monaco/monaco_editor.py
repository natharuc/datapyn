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
    QEventLoop,
    Qt,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebChannel import QWebChannel

from .monaco_bridge import MonacoBridge

logger = logging.getLogger(__name__)


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
        
        # SQL/Python autocomplete data
        self._sql_schema: Dict[str, Any] = {}
        self._python_namespace: Dict[str, Any] = {}
        self._global_imports: str = ""
        
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
        
        layout.addWidget(self._web_view)
        
        # Set minimum size for the widget itself
        self.setMinimumSize(200, 80)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocusProxy(self._web_view)
    
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
        
        # SQL/Python context-aware completions
        self._bridge.sql_context_requested.connect(self._on_sql_context_requested)
        self._bridge.sql_completion_requested.connect(self._on_sql_completion_requested)
        self._bridge.python_completion_requested.connect(self._on_python_completion_requested)
    
    def _on_editor_ready(self):
        """Called when Monaco editor is fully loaded."""
        self._is_ready = True
        
        # Apply pending operations
        for operation, args in self._pending_operations:
            operation(*args)
        self._pending_operations.clear()
        
        # Apply initial theme
        self.apply_theme()
        
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
        self.cursor_changed.emit(line, column)
    
    def _on_sql_context_requested(self, full_text: str, prefix: str, line: int, column: int):
        """Handle SQL context-aware completion request.
        
        Uses SqlAutoCompleteService to resolve aliases, CTEs, and subqueries.
        """
        from src.services.sql_autocomplete_service import SqlAutoCompleteService
        
        try:
            service = SqlAutoCompleteService()
            service.set_schema(self._sql_schema)
            
            # Reuse the main completion path so dot completions honor
            # cursor scope, aliases, CTEs, subqueries and temp objects.
            completions = service.get_completions(full_text, line - 1, column - 1)
            
            # Format and send back to JavaScript
            js_completions = []
            for comp in completions:
                # comp is a tuple: (name, category, detail/type)
                name = comp[0] if len(comp) > 0 else ""
                category = comp[1] if len(comp) > 1 else "column"
                detail = comp[2] if len(comp) > 2 else ""
                
                js_completions.append({
                    'label': name,
                    'kind': 'variable' if category == 'variable' else 'field',
                    'insertText': name,
                    'detail': detail,
                    'category': category,
                    'table': prefix
                })
            
            escaped = json.dumps(js_completions)
            self._run_js_when_ready(f"receiveSqlContextCompletions({escaped})")
        except Exception as e:
            logger.warning(f"[MONACO] SQL context completion error: {e}")
            self._run_js_when_ready("receiveSqlContextCompletions([])")
    
    def _on_sql_completion_requested(self, full_text: str, line: int, column: int):
        """Handle SQL completion request (SSMS-style full context).
        
        Uses SqlAutoCompleteService to provide intelligent completions based on:
        - Current position (SELECT, FROM, WHERE, etc.)
        - Tables mentioned in FROM/JOIN clauses
        - Aliases defined in the query
        """
        from src.services.sql_autocomplete_service import SqlAutoCompleteService
        
        try:
            service = SqlAutoCompleteService()
            service.set_schema(self._sql_schema)
            
            # Get context-aware completions
            completions = service.get_completions(full_text, line - 1, column - 1)
            
            # Format for JavaScript
            js_completions = []
            for comp in completions:
                # comp is a tuple: (name, category, detail)
                name = comp[0] if len(comp) > 0 else ""
                category = comp[1] if len(comp) > 1 else "text"
                detail = comp[2] if len(comp) > 2 else ""
                
                # Map category to Monaco completion kind
                kind = 'text'
                if category == 'keyword':
                    kind = 'keyword'
                elif category == 'function':
                    kind = 'function'
                elif category == 'routine':
                    kind = 'function'
                elif category == 'table':
                    kind = 'class'
                elif category == 'column':
                    kind = 'field'
                elif category == 'variable':
                    kind = 'variable'
                elif category == 'database':
                    kind = 'module'
                
                js_completions.append({
                    'label': name,
                    'kind': kind,
                    'insertText': name,
                    'detail': detail,
                    'category': category
                })
            
            escaped = json.dumps(js_completions)
            self._run_js_when_ready(f"receiveSqlCompletions({escaped})")
        except Exception as e:
            logger.warning(f"[MONACO] SQL completion error: {e}")
            self._run_js_when_ready("receiveSqlCompletions([])")

    def _on_python_completion_requested(self, full_text: str, line: int, column: int):
        """Handle Python Jedi completion request.
        
        Uses JediCompleter with namespace injection for type-aware completions.
        """
        from src.services.jedi_completer import JediCompleter
        
        try:
            completer = JediCompleter.instance()
            completer.set_namespace(self._python_namespace)
            
            # Prepend global imports for better context
            code_with_context = self._global_imports + "\n" + full_text if self._global_imports else full_text
            
            # Adjust line number if we prepended imports
            adjusted_line = line
            if self._global_imports:
                import_lines = self._global_imports.count("\n") + 1
                adjusted_line = line + import_lines
            
            # Synchronous completion for dropdown
            # Returns list of (name, type, description) tuples
            completions = completer.complete_sync(code_with_context, adjusted_line, column)
            
            # Format for JavaScript
            js_completions = []
            for comp in completions:
                # comp is a tuple: (name, type, description)
                name = comp[0] if len(comp) > 0 else ""
                kind = comp[1] if len(comp) > 1 else "text"
                detail = comp[2] if len(comp) > 2 else ""
                
                js_completions.append({
                    'label': name,
                    'kind': kind,
                    'insertText': name,
                    'detail': detail,
                    'category': 'python'
                })
            
            escaped = json.dumps(js_completions)
            self._run_js_when_ready(f"receivePythonCompletions({escaped})")
        except Exception as e:
            logger.warning(f"[MONACO] Python completion error: {e}")
            self._run_js_when_ready("receivePythonCompletions([])")

    def _run_js(self, script: str, callback=None):
        """Execute JavaScript in the Monaco editor."""
        if callback:
            self._web_view.page().runJavaScript(script, callback)
        else:
            self._web_view.page().runJavaScript(script)
    
    def _run_js_when_ready(self, script: str, callback=None):
        """Execute JS when ready, or queue if not ready yet."""
        if self._is_ready:
            # Log completion-related JS calls at debug level (less spam)
            if "receiveCompletion" in script:
                logger.debug(f"[MONACO] Running JS: {script[:80]}...")
            self._run_js(script, callback)
        else:
            logger.debug(f"[MONACO] Queueing JS (not ready): {script[:40]}...")
            self._pending_operations.append(
                (lambda s=script, cb=callback: self._run_js(s, cb), ())
            )
    
    # === ICodeEditor Interface ===
    
    def get_text(self) -> str:
        """Returns all editor text."""
        return self._text_cache
    
    def set_text(self, text: str) -> None:
        """Sets the editor text."""
        self._text_cache = text
        escaped = json.dumps(text)
        self._run_js_when_ready(f"setValue({escaped})")
    
    def force_request_completion(self) -> None:
        """Force trigger an inline completion request (Ctrl+. shortcut)."""
        self._run_js_when_ready("forceRequestCompletion()")
    
    def get_selected_text(self) -> str:
        """Returns selected text or empty string."""
        # Sync call - use cached value or return empty
        # For async, we'd need to use callback
        result = [""]
        got_result = [False]
        
        def on_result(text):
            result[0] = text or ""
            got_result[0] = True
        
        if self._is_ready:
            # Run synchronously with event loop
            loop = QEventLoop()
            self._web_view.page().runJavaScript(
                "getSelectedText()",
                lambda x: (on_result(x), loop.quit())
            )
            QTimer.singleShot(500, loop.quit)  # Increased timeout
            loop.exec()
            
            if not got_result[0]:
                print("[MonacoEditor] get_selected_text timeout - JS did not respond in time")
        
        return result[0]
    
    def has_selection(self) -> bool:
        """Checks if there is selected text."""
        result = [False]
        got_result = [False]
        
        def on_result(val):
            result[0] = bool(val)
            got_result[0] = True
        
        if self._is_ready:
            loop = QEventLoop()
            self._web_view.page().runJavaScript(
                "hasSelection()",
                lambda x: (on_result(x), loop.quit())
            )
            QTimer.singleShot(500, loop.quit)  # Increased timeout
            loop.exec()
            
            if not got_result[0]:
                print("[MonacoEditor] has_selection timeout - JS did not respond in time")
        
        return result[0]
    
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
        self._run_js_when_ready(f"setFontSize({size})")
    
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
        """Returns the current cursor line (0-indexed)."""
        result = [0]
        
        def on_result(val):
            result[0] = int(val or 0)
        
        if self._is_ready:
            loop = QEventLoop()
            self._web_view.page().runJavaScript(
                "getCurrentLine()",
                lambda x: (on_result(x), loop.quit())
            )
            QTimer.singleShot(100, loop.quit)
            loop.exec()
        
        return result[0]
    
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
        logger.info(f"[MONACO] set_sql_schema called with {len(schema.get('tables', []))} tables")
        self._sql_schema = schema
        # Register SQL completions in Monaco
        self.update_sql_completions(schema)
    
    def set_python_namespace(self, namespace: dict) -> None:
        """Set Python namespace for autocompletion."""
        self._python_namespace = namespace
        # Register Python completions in Monaco
        self.update_python_completions(namespace)
    
    def set_global_imports(self, imports_code: str) -> None:
        """Set global imports for Jedi completion."""
        self._global_imports = imports_code
    
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
        if not completions:
            return
        completions_json = json.dumps(completions)
        self._run_js_when_ready(f"registerCompletions({completions_json})")
    
    def update_sql_completions(self, schema: Optional[dict]) -> None:
        """
        Update SQL autocomplete with database schema (context-aware).
        
        Args:
            schema: dict with keys:
                - tables: list of table dicts {"name": ..., "schema": ..., "type": ...}
                - columns: dict of {table_name: [{"name": ..., "type": ...}]}
                - database: current database name
        """
        if not schema:
            return
        
        completions = []
        
        # Add tables with category
        tables = schema.get("tables", [])
        for table in tables:
            # Handle both dict format (from SchemaService) and legacy string format
            if isinstance(table, dict):
                table_name = table.get("name", "")
                table_schema = table.get("schema", "")
                table_type = table.get("type", "TABLE")
                detail = f"{table_schema}.{table_name}" if table_schema else table_name
                if table_type == "VIEW":
                    detail = f"view: {detail}"
                else:
                    detail = f"table: {detail}"
            else:
                table_name = str(table)
                detail = "table"
            
            if table_name:
                completions.append({
                    "label": table_name,
                    "kind": "property",
                    "insertText": table_name,
                    "detail": detail,
                    "category": "table"
                })
        
        # Add columns with table reference for context filtering
        columns = schema.get("columns", {})
        for table_name, column_list in columns.items():
            for column in column_list:
                # Handle both dict format (from SchemaService) and legacy string format
                if isinstance(column, dict):
                    column_name = column.get("name", "")
                    column_type = column.get("type", "")
                    detail = f"{table_name}.{column_name} ({column_type})" if column_type else f"{table_name}.{column_name}"
                else:
                    column_name = str(column)
                    detail = f"{table_name}.{column_name}"
                
                if column_name:
                    completions.append({
                        "label": column_name,
                        "kind": "field",
                        "insertText": column_name,
                        "detail": detail,
                        "category": "column",
                        "table": table_name
                    })
        
        # Add common SQL keywords
        sql_keywords = [
            "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN",
            "LIKE", "IS", "NULL", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
            "ON", "AS", "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "DISTINCT",
            "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
            "TABLE", "DROP", "ALTER", "COUNT", "SUM", "AVG", "MIN", "MAX",
            "CAST", "CASE", "WHEN", "THEN", "ELSE", "END"
        ]
        for kw in sql_keywords:
            completions.append({
                "label": kw,
                "kind": "keyword",
                "insertText": kw,
                "detail": "SQL keyword"
            })
        
        logger.info(f"[MONACO] Registering {len(completions)} contextual SQL completions ({len(tables)} tables, {sum(len(cols) for cols in columns.values())} columns)")
        self.register_completions(completions)
    
    def update_python_completions(self, variables: Optional[dict]) -> None:
        """
        Update Python autocomplete with namespace variables.
        
        Args:
            variables: dict of {var_name: var_type_or_value}
        """
        if not variables:
            return
        
        completions = []
        
        # Add variables from namespace
        for var_name, var_info in variables.items():
            # Skip private/internal variables
            if var_name.startswith("_"):
                continue
            
            var_type = type(var_info).__name__ if not isinstance(var_info, str) else var_info
            completions.append({
                "label": var_name,
                "kind": "variable",
                "insertText": var_name,
                "detail": var_type
            })
        
        # Add common Python keywords/builtins
        python_keywords = [
            "def", "class", "if", "elif", "else", "for", "while", "break",
            "continue", "return", "import", "from", "as", "try", "except",
            "finally", "with", "lambda", "yield", "assert", "pass", "raise",
            "True", "False", "None", "and", "or", "not", "in", "is"
        ]
        for kw in python_keywords:
            completions.append({
                "label": kw,
                "kind": "keyword",
                "insertText": kw,
                "detail": "Python keyword"
            })
        
        # Add common imports/packages
        common_packages = [
            "pandas", "pd", "numpy", "np", "datetime", "json", "re", "os",
            "sys", "math", "random", "collections", "itertools"
        ]
        for pkg in common_packages:
            completions.append({
                "label": pkg,
                "kind": "module",
                "insertText": pkg,
                "detail": "module"
            })
        
        logger.info(f"[MONACO] Registering {len(completions)} Python completions ({len(variables)} variables)")
        self.register_completions(completions)
