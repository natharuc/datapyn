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
    execute_requested = pyqtSignal(str)  # selected_text (empty if no selection)
    completion_requested = pyqtSignal(str, str, int, int)  # prefix, suffix, line, column
    
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
