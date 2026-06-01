"""
Bridge between Python and Monaco Editor JavaScript.

Uses QWebChannel to enable bidirectional communication between
PyQt6 and the embedded Monaco Editor.
"""

from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal


class MonacoBridge(QObject):
    """
    Bridge class exposed to JavaScript via QWebChannel.
    
    JavaScript calls methods via pyBridge.methodName()
    Python emits signals that are connected to the MonacoEditor.
    """
    
    # Signals emitted when JS calls our slots
    editor_ready = pyqtSignal()
    text_changed = pyqtSignal(str)
    focus_in = pyqtSignal()
    focus_out = pyqtSignal()
    cursor_changed = pyqtSignal(int, int)  # line, column
    selection_changed = pyqtSignal(str, bool)  # selected_text, has_selection
    execute_requested = pyqtSignal(str)  # selected_text (empty if no selection)
    completion_requested = pyqtSignal(str, str, int, int)  # prefix, suffix, line, column
    force_completion_requested = pyqtSignal(str, str, int, int)  # prefix, suffix, line, column (bypasses throttling)
    
    # SQL context-aware completion request (for dot patterns)
    sql_context_requested = pyqtSignal(str, str, int, int, int)  # full_text, prefix, line, column, request_id
    
    # SQL general completion request (like SSMS - full context)
    sql_completion_requested = pyqtSignal(str, int, int, int)  # full_text, line, column, request_id
    
    # Python Jedi completion request
    python_completion_requested = pyqtSignal(str, int, int, int)  # full_text, line, column, request_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._completion_callback = None
    
    # === Slots called from JavaScript ===
    
    @pyqtSlot()
    def onEditorReady(self):
        """Called when Monaco editor finishes initialization."""
        self.editor_ready.emit()
    
    @pyqtSlot(str)
    def onTextChanged(self, text: str):
        """Called when editor text changes."""
        self.text_changed.emit(text)
    
    @pyqtSlot()
    def onFocusIn(self):
        """Called when editor gains focus."""
        self.focus_in.emit()
    
    @pyqtSlot()
    def onFocusOut(self):
        """Called when editor loses focus."""
        self.focus_out.emit()
    
    @pyqtSlot(int, int)
    def onCursorChanged(self, line: int, column: int):
        """Called when cursor position changes."""
        self.cursor_changed.emit(line, column)

    @pyqtSlot(str, bool)
    def onSelectionChanged(self, selected_text: str, has_selection: bool):
        """Called when the editor selection changes."""
        self.selection_changed.emit(selected_text, bool(has_selection))
    
    @pyqtSlot(str)
    def onExecuteRequested(self, selected_text: str = ""):
        """Called when user requests code execution (F5 or Ctrl+Enter).
        
        Args:
            selected_text: Currently selected text, or empty if no selection
        """
        self.execute_requested.emit(selected_text)
    
    @pyqtSlot(str, str, int, int)
    def requestCompletion(self, prefix: str, suffix: str, line: int, column: int):
        """
        Called when inline completion is requested.
        
        Args:
            prefix: Text before cursor
            suffix: Text after cursor
            line: Current line number (1-indexed)
            column: Current column (1-indexed)
        """
        self.completion_requested.emit(prefix, suffix, line, column)
    
    @pyqtSlot(str, str, int, int)
    def forceRequestCompletion(self, prefix: str, suffix: str, line: int, column: int):
        """
        Called when force inline completion is requested (Ctrl+.).
        
        Bypasses throttling and minimum prefix checks.
        
        Args:
            prefix: Text before cursor
            suffix: Text after cursor
            line: Current line number (1-indexed)
            column: Current column (1-indexed)
        """
        self.force_completion_requested.emit(prefix, suffix, line, column)

    @pyqtSlot(str, str, int, int, int)
    def requestSqlContext(self, full_text: str, prefix: str, line: int, column: int, request_id: int):
        """
        Called when SQL context-aware completion is requested.
        
        Used for "table." or "alias." completion to get specific columns.
        """
        self.sql_context_requested.emit(full_text, prefix, line, column, int(request_id))

    @pyqtSlot(str, int, int, int)
    def requestSqlCompletion(self, full_text: str, line: int, column: int, request_id: int):
        """Called when SQL completion is requested (SSMS-style full context)."""
        self.sql_completion_requested.emit(full_text, line, column, int(request_id))

    @pyqtSlot(str, int, int, int)
    def requestPythonCompletion(self, full_text: str, line: int, column: int, request_id: int):
        """Called when Python Jedi completion is requested."""
        self.python_completion_requested.emit(full_text, line, column, int(request_id))
