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
    QThread,
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


class _SyntaxValidateWorker(QThread):
    """Run syntax checks off the UI thread."""

    result_ready = pyqtSignal(int, list)

    def __init__(
        self,
        generation: int,
        language: str,
        code: str,
        db_type: str = "",
        sql_schema: Optional[Dict[str, Any]] = None,
        python_namespace: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._generation = generation
        self._language = language
        self._code = code
        self._db_type = db_type
        self._sql_schema = sql_schema
        self._python_namespace = python_namespace

    def run(self):
        if self.isInterruptionRequested():
            return
        from src.services.syntax_validator import validate_code

        markers = [
            m.to_dict()
            for m in validate_code(
                self._language,
                self._code,
                db_type=self._db_type or None,
                schema=self._sql_schema if self._language == "sql" else None,
                namespace=self._python_namespace if self._language == "python" else None,
                should_abort=self.isInterruptionRequested,
            )
        ]
        if not self.isInterruptionRequested():
            self.result_ready.emit(self._generation, markers)


def _qthread_alive(worker) -> bool:
    return worker is not None and not sip.isdeleted(worker)


def _qthread_is_running(worker) -> bool:
    if not _qthread_alive(worker):
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def _color_for_monaco(value: str, fallback: str) -> str:
    """Normalize theme colors to #hex — Monaco does not accept rgba in theme defs."""
    if not value:
        return fallback
    raw = value.strip()
    if raw.startswith("#"):
        return raw
    if raw.lower().startswith("rgba(") or raw.lower().startswith("rgb("):
        inner = raw[raw.index("(") + 1 : raw.rindex(")")]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) >= 3:
            try:
                r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
                return f"#{r:02x}{g:02x}{b:02x}"
            except (TypeError, ValueError):
                return fallback
    return raw if raw.startswith("#") else fallback


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
    sql_schema_requested = pyqtSignal()
    
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
        self._static_completions: list = []
        self._sibling_block_completions: list = []
        self._sql_db_type: str = ""
        self._schema_load_pending = False
        self._completion_service = MonacoCompletionService(self)
        self._syntax_validate_timer = QTimer(self)
        self._syntax_validate_timer.setSingleShot(True)
        self._syntax_validate_timer.setInterval(750)
        self._syntax_validate_generation = 0
        self._syntax_validate_worker: Optional[QThread] = None
        self._syntax_validate_timer.timeout.connect(self._run_syntax_validation)
        
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
        from src.design_system.tokens import get_colors
        editor_bg = get_colors().editor_bg
        self._page.setBackgroundColor(QColor(editor_bg))
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
        self._stop_syntax_worker()

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
        <body style="background:#0a0f18;margin:0;">
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
        self._bridge.cancel_inline_completion.connect(self._on_cancel_inline_completion)

        self._completion_service.sql_completions_ready.connect(self._deliver_sql_completions)
        self._completion_service.sql_context_completions_ready.connect(self._deliver_sql_context_completions)
        self._completion_service.python_completions_ready.connect(self._deliver_python_completions)
    
    def _deliver_sql_completions(self, request_id: int, completions: list) -> None:
        items = completions or []
        if not items and self._sql_schema:
            logger.warning(
                "[MONACO] SQL completion #%s returned 0 items (schema loaded)",
                request_id,
            )
        payload = json.dumps(items)
        self._run_js_when_ready(f"receiveSqlCompletions({int(request_id)}, {payload})")

    def _deliver_sql_context_completions(self, request_id: int, completions: list) -> None:
        items = completions or []
        if not items and self._sql_schema:
            logger.warning(
                "[MONACO] SQL context completion #%s returned 0 items (schema loaded)",
                request_id,
            )
        payload = json.dumps(items)
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

        if self._sql_schema:
            self._run_js(f"registerSqlSchemaIndex({json.dumps(self._sql_schema)})")
        if self._static_completions or self._sibling_block_completions:
            self._push_merged_completions()

        self._schedule_syntax_validation()
    
    def _on_text_changed(self, text: str):
        """Handle text change from JS."""
        self._text_cache = text
        self.text_changed.emit()
        self.textChanged.emit()
        self._schedule_syntax_validation()

    def _on_cancel_inline_completion(self) -> None:
        """Drop in-flight AI ghost text while the user is typing."""
        service = getattr(self, "_inline_completion_service", None)
        if service is not None and hasattr(service, "cancel_request"):
            service.cancel_request()

    def set_sql_dialect(self, db_type: str) -> None:
        """Connection db_type used for SQL syntax validation (mssql, mysql, ...)."""
        self._sql_db_type = (db_type or "").strip()
        self._schedule_syntax_validation()

    def _schedule_syntax_validation(self) -> None:
        if self._cleaned_up or sip.isdeleted(self):
            return
        lang = self._language
        if lang not in ("python", "sql"):
            self._clear_syntax_markers()
            return
        timer = getattr(self, "_syntax_validate_timer", None)
        if timer is None or sip.isdeleted(timer):
            return
        try:
            timer.start()
        except RuntimeError:
            # A queued schema/text update can arrive during Qt teardown.
            return

    def _clear_syntax_markers(self) -> None:
        self._run_js_when_ready("setDiagnostics([])")

    def _stop_syntax_worker(self) -> None:
        worker = getattr(self, "_syntax_validate_worker", None)
        self._syntax_validate_worker = None
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.quit()
            worker.wait(200)
        worker.deleteLater()

    def _run_syntax_validation(self) -> None:
        if self._cleaned_up or not self._is_ready:
            return
        lang = self._language
        if lang not in ("python", "sql"):
            self._clear_syntax_markers()
            return

        self._syntax_validate_generation += 1
        generation = self._syntax_validate_generation
        self._stop_syntax_worker()

        # Avoid spinning a worker for huge SQL — validate_sql would skip anyway.
        if lang == "sql":
            from src.services.syntax_validator import is_large_sql_document

            if is_large_sql_document(self._text_cache):
                self._on_syntax_validation_done(
                    generation,
                    [
                        {
                            "startLineNumber": 1,
                            "startColumn": 1,
                            "endLineNumber": 1,
                            "endColumn": 2,
                            "message": "Syntax check skipped for large script",
                            "severity": "warning",
                        }
                    ],
                )
                return

        worker = _SyntaxValidateWorker(
            generation,
            lang,
            self._text_cache,
            self._sql_db_type if lang == "sql" else "",
            self._sql_schema if lang == "sql" else None,
            self._python_namespace if lang == "python" else None,
            self,
        )
        worker.result_ready.connect(self._on_syntax_validation_done)
        worker.finished.connect(lambda w=worker: self._release_syntax_worker(w))
        worker.finished.connect(worker.deleteLater)
        self._syntax_validate_worker = worker
        worker.start()

    def _release_syntax_worker(self, worker: _SyntaxValidateWorker) -> None:
        if getattr(self, "_syntax_validate_worker", None) is worker:
            self._syntax_validate_worker = None

    def _on_syntax_validation_done(self, generation: int, markers: list) -> None:
        if generation != self._syntax_validate_generation:
            return
        payload = json.dumps(markers or [])
        self._run_js_when_ready(f"setDiagnostics({payload})")
    
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
    
    def _maybe_request_sql_schema(self) -> None:
        """Ask the host to load schema lazily when autocomplete has no metadata."""
        if self._language != "sql":
            return
        if self._sql_schema.get("tables") or self._sql_schema.get("columns"):
            return
        if self._schema_load_pending:
            return
        self._schema_load_pending = True
        self.sql_schema_requested.emit()

    def _on_sql_context_requested(self, full_text: str, prefix: str, line: int, column: int, request_id: int):
        """Handle SQL context-aware completion request off the UI thread."""
        if not self._sql_schema.get("tables") and not self._sql_schema.get("columns"):
            self._maybe_request_sql_schema()
            logger.warning(
                "[MONACO] SQL context completion without schema (prefix=%s)",
                prefix,
            )
        self._completion_service.set_sql_schema(self._sql_schema)
        self._completion_service.request_sql_context(request_id, full_text, prefix, line, column)
    
    def _on_sql_completion_requested(self, full_text: str, line: int, column: int, request_id: int):
        """Handle SQL completion request off the UI thread."""
        if not self._sql_schema.get("tables") and not self._sql_schema.get("columns"):
            self._maybe_request_sql_schema()
            logger.warning(
                "[MONACO] SQL completion request without schema (L%s:C%s)",
                line,
                column,
            )
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
        self._text_cache = text if text is not None else ""
        payload = self._text_cache
        # One giant runJavaScript("setValue(<json>)") duplicates multi-MB buffers and
        # can freeze WebEngine. Chunk large payloads instead.
        if len(payload) >= 80_000:
            chunk_size = 60_000
            self._run_js_when_ready("beginSetValue()", replace_key="editor:setValueBegin")
            for index in range(0, len(payload), chunk_size):
                chunk = payload[index : index + chunk_size]
                escaped = json.dumps(chunk)
                self._run_js_when_ready(
                    f"appendSetValueChunk({escaped})",
                    replace_key=f"editor:setValueChunk:{index}",
                )
            self._run_js_when_ready("endSetValue()", replace_key="editor:setValueEnd")
            return

        escaped = json.dumps(payload)
        self._run_js_when_ready(f"setValue({escaped})", replace_key="editor:setValue")
    
    def force_request_completion(self) -> None:
        """Force trigger an inline completion request (Ctrl+. shortcut)."""
        self._run_js_when_ready("forceRequestCompletion()")
    
    def request_execute(self) -> None:
        """Run the current selection (or full block) using live Monaco selection."""
        if self._is_ready:
            self._run_js("triggerExecute()")
        else:
            self.execute_requested.emit(self.get_selected_text())

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
        self._schedule_syntax_validation()
    
    def get_language(self) -> str:
        """Returns the current language."""
        return self._language
    
    def set_theme(self, theme_name: str) -> None:
        """Sets the editor theme."""
        self._theme_name = theme_name
        self.apply_theme()
    
    def apply_theme(self) -> None:
        """Applies the current ThemeManager theme."""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        bg = colors.editor_bg
        self._page.setBackgroundColor(QColor(bg))
        self._web_view.setStyleSheet(f"background-color: {bg};")

        if not self._is_ready:
            return

        surface = self._get_editor_surface_colors()
        self._run_js(f"applyEditorSurface({json.dumps(surface)})")
        self._run_js(f"setBackgroundColor('{surface['background']}')")

    def _get_editor_surface_colors(self) -> Dict[str, str]:
        """Editor chrome colors only — syntax highlighting stays on Monaco vs-dark."""
        from src.design_system.tokens import get_colors

        ds = get_colors()
        editor_colors: Dict[str, Any] = {}
        if self.theme_manager:
            try:
                editor_colors = self.theme_manager.get_theme().get("editor", {})
            except Exception:
                pass

        return {
            "background": _color_for_monaco(
                editor_colors.get("background", ds.editor_bg), ds.editor_bg
            ),
            "caretLine": _color_for_monaco(
                editor_colors.get("caret_line", ds.editor_line_highlight),
                ds.editor_line_highlight,
            ),
            "selection": _color_for_monaco(
                editor_colors.get("selection", ds.editor_selection),
                ds.editor_selection,
            ),
            "marginBg": _color_for_monaco(
                editor_colors.get("margin_bg", ds.editor_gutter_bg),
                ds.editor_gutter_bg,
            ),
            "marginFg": _color_for_monaco(
                editor_colors.get("margin_fg", ds.editor_gutter_fg),
                ds.editor_gutter_fg,
            ),
        }
    
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
        tables = len(schema.get("tables", []))
        columns = sum(len(v) for v in (schema.get("columns") or {}).values())
        # Idempotent: registering the full schema in Monaco (often 10k+
        # completions) is expensive and was re-run on EVERY block focus,
        # freezing the editor. Skip when the schema is unchanged.
        fingerprint = (id(schema), tables, columns, schema.get("db_type", ""))
        if fingerprint == getattr(self, "_sql_schema_fingerprint", None):
            return
        self._sql_schema_fingerprint = fingerprint
        logger.debug(
            "[MONACO] set_sql_schema: %s tables, %s column groups",
            tables,
            columns,
        )
        self._sql_schema = schema
        if tables or columns:
            self._schema_load_pending = False
        self._completion_service.set_sql_schema(schema)
        if schema.get("db_type"):
            self.set_sql_dialect(str(schema.get("db_type", "")))
        self._schedule_syntax_validation()
        payload = json.dumps(schema)
        self._run_js_when_ready(
            f"registerSqlSchemaIndex({payload})",
            replace_key="editor:sqlSchemaIndex",
        )
        # Schema tables/columns are resolved in JS via registerSqlSchemaIndex only.
        # Building 10k+ static completion items blocks the WebEngine main thread.
        if not schema:
            self.clear_sql_completions()

    def clear_sql_completions(self) -> None:
        """Clear Monaco SQL completions so a new schema can be loaded cleanly."""
        self._sql_schema = {}
        self._static_completions = []
        self._run_js_when_ready(
            "registerSqlSchemaIndex({})",
            replace_key="editor:sqlSchemaIndex",
        )
        self._push_merged_completions()
    
    def set_python_namespace(self, namespace: dict) -> None:
        """Set Python namespace for autocompletion."""
        self._python_namespace = namespace
        self._completion_service.set_python_context(namespace, self._global_imports)
        self.update_python_completions(namespace)
        self._schedule_syntax_validation()

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
    
    def provide_completion(
        self,
        text: str,
        line: int = 0,
        column: int = 0,
    ) -> None:
        """
        Provide an inline completion (ghost text) to the editor.

        line/column are 1-based Monaco coordinates from the original request
        (important when the LSP response arrives after a short typing pause).
        """
        logger.debug(
            "[MONACO] provide_completion: %s chars at L%s:C%s, ready=%s",
            len(text) if text else 0,
            line,
            column,
            self._is_ready,
        )
        escaped = json.dumps(text or "")
        self._run_js_when_ready(
            f"receiveCompletion({escaped}, {int(line or 0)}, {int(column or 0)})"
        )
    
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
        self._static_completions = completions or []
        self._push_merged_completions()

    def set_sibling_block_completions(self, completions: list) -> None:
        """Other blocks in the tab — full multiline insertText per item."""
        self._sibling_block_completions = completions or []
        self._push_merged_completions()

    def _push_merged_completions(self) -> None:
        # Python Jedi/static items + sibling block snippets (small lists only).
        merged = (self._static_completions or []) + (self._sibling_block_completions or [])
        payload = json.dumps(merged)
        self._run_js_when_ready(f"registerCompletions({payload})")
    
    def update_sql_completions(self, schema: Optional[dict]) -> None:
        """Refresh SQL schema index in Monaco (no bulk static completion list)."""
        if not schema:
            return
        self.set_sql_schema(schema)

    def _release_sql_completion_worker(self, worker: SqlCompletionBuildWorker) -> None:
        if self._sql_completion_worker is worker:
            self._sql_completion_worker = None

    def _on_sql_completions_built(self, generation: int, completions: list) -> None:
        # Legacy path — schema completions are served from sqlSchemaIndex in JS.
        if generation != self._sql_completion_generation:
            return
    
    def update_python_completions(self, variables: Optional[dict]) -> None:
        """Update Python autocomplete with namespace variables (built off the UI thread)."""
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
        self._static_completions = completions
        self._push_merged_completions()
