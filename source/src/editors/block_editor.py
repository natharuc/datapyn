"""
BlockEditor - Container that manages multiple code blocks

Similar to a Jupyter notebook, but focused on SQL/Python execution
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QPushButton,
    QHBoxLayout,
    QFrame,
    QSizePolicy,
    QSpacerItem,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QUrl
from PyQt6.QtGui import QKeyEvent, QDragEnterEvent, QDropEvent
from typing import List, Optional
import os
import qtawesome as qta

from src.core.theme_manager import ThemeManager
from src.state.app_state import ApplicationState
from src.editors.code_block import CodeBlock
from src.language import S


class BlockEditor(QWidget):
    """
    Block-based editor.

    Each block has its own language (Python, SQL, Cross-Syntax).

    Shortcuts:
    - F5: Runs focused block (selection if any, otherwise entire block)
    - Shift+Enter: Runs focused block and advances to next (configurable via Settings)
    - Ctrl+Enter: Runs all blocks

    Signals:
        execute_block: (language, code, block) - Runs a block
        execute_all: () - Runs all blocks
    """

    # Execution signals
    execute_sql = pyqtSignal(str, object, object, object)  # query, block_name, connection_name, database_name
    execute_python = pyqtSignal(str)  # code

    # Signal to run multiple blocks in sequence
    # Emits list of tuples: [(language, code, block, block_name, connection_name, database_name), ...]
    execute_queue = pyqtSignal(list)

    # Cancellation signal
    cancel_execution = pyqtSignal()

    # Signal when content changes
    content_changed = pyqtSignal()

    # Signal when block requests connection selection
    select_connection_for_block = pyqtSignal(object)  # CodeBlock

    # Signal when block connection changes
    block_connection_changed = pyqtSignal(object, str)  # CodeBlock, connection_name

    # Signal when block database changes
    block_database_changed = pyqtSignal(object, str)  # CodeBlock, database_name

    # Signal when connection is dropped on editor area (to connect session)
    connection_drop_requested = pyqtSignal(str)  # connection_name

    # Signal when data file is dropped (to show import dialog)
    file_dropped = pyqtSignal(str)  # file_path

    # Signal for completion/autocomplete logging
    completion_log = pyqtSignal(str, str)  # message, level

    # Signal when cursor position changes in focused block
    cursor_changed = pyqtSignal(int, int)  # line, column (1-based)

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._blocks: List[CodeBlock] = []
        self._focused_block: Optional[CodeBlock] = None
        self._last_focused_block: Optional[CodeBlock] = None
        self._executing_index: int = -1  # Index of block being executed in batch
        self._execution_queue_blocks: List[CodeBlock] = []  # Blocks in execution queue
        self._current_executing_block: Optional[CodeBlock] = None  # Currently executing block
        self._dragging_block: Optional[CodeBlock] = None  # Block being dragged
        self._copilot_client = None  # Copilot client for inline completions
        self._lsp_client = None  # LSP client for inline completions
        self._database_context = ""  # Database schema context for SQL completions
        self._sql_schema = {}  # Cached SQL schema for completions

        self._setup_ui()

        # Enable drop
        self.setAcceptDrops(True)

        # Create first empty block
        self.add_block()

    # === Public Properties ===

    def set_copilot_client(self, client) -> None:
        """Set Copilot client for inline completions in all blocks."""
        self._copilot_client = client
        for block in self._blocks:
            block.set_copilot_client(client)

    def set_lsp_client(self, client) -> None:
        """Set LSP client for inline completions in all blocks."""
        self._lsp_client = client
        for block in self._blocks:
            block.set_lsp_client(client)
    
    def set_database_context(self, context: str) -> None:
        """Set database schema context for SQL completions in all blocks."""
        self._database_context = context
        for block in self._blocks:
            block.set_database_context(context)

    @property
    def blocks(self) -> List["CodeBlock"]:
        """Get list of all code blocks."""
        return self._blocks

    @property
    def focused_block(self) -> Optional["CodeBlock"]:
        """Get the currently focused block, or None."""
        return self._focused_block

    def _setup_ui(self):
        """Setup the UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area for blocks
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # Blocks container
        self.blocks_container = QWidget()
        self.blocks_layout = QVBoxLayout(self.blocks_container)
        self.blocks_layout.setContentsMargins(8, 8, 8, 8)
        self.blocks_layout.setSpacing(12)
        self.blocks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.blocks_container)
        main_layout.addWidget(self.scroll_area)

        # Button to add new block (horizontal line with +)
        self.add_button_container = QWidget()
        add_layout = QHBoxLayout(self.add_button_container)
        add_layout.setContentsMargins(8, 4, 8, 8)

        # Horizontal line (like <hr/>)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("QFrame { color: #555; }")

        # Small button with + icon
        self.add_btn = QPushButton()
        self.add_btn.setIcon(qta.icon("mdi.plus", color="#888"))
        self.add_btn.setToolTip(S.block_editor.tooltip_add_block)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(24, 24)  # Small 24x24 button
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #555;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #333;
                border-color: #888;
            }
        """)
        self.add_btn.clicked.connect(lambda: self.add_block())

        # Layout: horizontal line + button +
        add_layout.addWidget(line, 1)  # Line takes all available space
        add_layout.addWidget(self.add_btn)  # + button at the end

        # Add button to blocks container
        self.blocks_layout.addWidget(self.add_button_container)

    def keyPressEvent(self, event: QKeyEvent):
        """Intercept keys for execution shortcuts"""
        # F5 - Run (focused block selection, or whole block, or all)
        if event.key() == Qt.Key.Key_F5 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._execute_smart()
            return

        # Ctrl+Enter - Run all blocks
        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.execute_all_blocks()
            return

        super().keyPressEvent(event)

    def _execute_smart(self):
        """
        Run intelligently:
        - If there's a selection in focused block: runs selection with block's language
        - If no selection: runs focused block
        """
        if self._focused_block:
            has_sel = self._focused_block.has_selection()
            print(f"[BlockEditor] _execute_smart: has_selection={has_sel}")
            if has_sel:
                # Run selection
                code = self._focused_block.get_selected_text()
                print(f"[BlockEditor] Running selected text ({len(code)} chars): {code[:50]!r}...")
                lang = self._focused_block.get_language()
                self._execute_code(code, lang, self._focused_block)
                return
        
        # Run focused block
        print("[BlockEditor] Running full block (no selection)")
        self._execute_block(self._focused_block or (self._blocks[0] if self._blocks else None))

    def _execute_focused_and_advance(self):
        """Run focused block and move focus to next"""
        if self._focused_block:
            self._execute_block(self._focused_block)

            # Advance to next block
            index = self._blocks.index(self._focused_block)
            if index < len(self._blocks) - 1:
                self._blocks[index + 1].focus_editor()
            else:
                # If it's the last one, create new block
                new_block = self.add_block()
                new_block.focus_editor()

    def _execute_block(self, block: CodeBlock):
        """Run a specific block"""
        code = block.get_code().strip()
        if not code:
            return

        lang = block.get_language()
        self._execute_code(code, lang, block)

    def _execute_code(self, code: str, language: str, block: CodeBlock):
        """Emit appropriate execution signal"""
        block.set_running(True)

        if language == "sql":
            block_name = block.get_block_name()
            connection_name = block.get_connection_name()
            database_name = block.get_database_name()
            self.execute_sql.emit(code, block_name, connection_name, database_name)
        elif language == "python":
            self.execute_python.emit(code)

        # Note: caller needs to call mark_execution_finished afterwards

    def execute_all_blocks(self):
        """Run all blocks in sequence"""
        if not self._blocks:
            return

        # Collect all blocks with code to run
        queue = []
        self._execution_queue_blocks = []

        for index, block in enumerate(self._blocks):
            code = block.get_code().strip()
            if code:
                # Tuple: (language, code, block, block_name, connection_name, database_name)
                queue.append((block.get_language(), code, block, block.get_block_name(), block.get_connection_name(), block.get_database_name()))
                self._execution_queue_blocks.append(block)
                block.set_waiting(True)  # Mark as waiting

        if queue:
            # Mark first as running
            if self._execution_queue_blocks:
                first_block = self._execution_queue_blocks[0]
                first_block.set_running(True)
                self._current_executing_block = first_block

            # Emit queue for SessionWidget to process sequentially
            self.execute_queue.emit(queue)

    def mark_block_started(self, block: CodeBlock):
        """Mark that a specific block started executing"""
        self._current_executing_block = block
        block.set_running(True)

    def mark_execution_finished(self, block: CodeBlock = None, has_error: bool = False):
        """Mark that a block execution finished"""
        if block:
            if has_error:
                block.set_error()
            else:
                block.set_running(False)
            # Remove from queue if still there
            if block in self._execution_queue_blocks:
                self._execution_queue_blocks.remove(block)
            # Mark next as running
            if self._execution_queue_blocks:
                next_block = self._execution_queue_blocks[0]
                next_block.set_running(True)
                self._current_executing_block = next_block
            else:
                self._current_executing_block = None
        else:
            # If not specified, mark all as not running
            for b in self._blocks:
                b.set_running(False)
                b.set_waiting(False)
            self._execution_queue_blocks = []
            self._current_executing_block = None

    def cancel_all_executions(self):
        """Cancel all pending executions"""        # Mark current block as cancelled
        if self._current_executing_block:
            self._current_executing_block.set_cancelled()

        # Mark waiting blocks as cancelled too
        for block in self._execution_queue_blocks:
            if block != self._current_executing_block:
                block.set_cancelled()

        self._execution_queue_blocks = []
        self._current_executing_block = None

        # Emit cancellation signal
        self.cancel_execution.emit()

    def get_current_executing_block(self) -> Optional[CodeBlock]:
        """Return currently executing block"""
        return self._current_executing_block

    # === Autocomplete Management ===
    
    def update_python_completions_all(self):
        """Update Python completions for all Python blocks with current namespace."""
        app_state = ApplicationState.instance()
        namespace = app_state.get_namespace()
        
        for block in self._blocks:
            if block.get_language() == "python" and hasattr(block.editor, "set_python_namespace"):
                block.editor.set_python_namespace(namespace)
    
    def set_database_context(self, context: str):
        """Set database context for SQL completions (Monaco)."""
        self._database_context = context
        # Propagate to existing blocks
        for block in self._blocks:
            if hasattr(block, "set_database_context"):
                block.set_database_context(context)
    
    def set_sql_schema(self, schema: dict):
        """Set SQL schema for autocomplete in all SQL blocks.
        
        Args:
            schema: Dict with tables, columns, database info from SchemaService
        """
        self._sql_schema = schema
        # Propagate to existing SQL blocks
        for block in self._blocks:
            if block.get_language() == "sql" and hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema(schema)
    
    def _on_block_language_changed(self, block: CodeBlock, language: str):
        """Handle block language change - update completions."""
        if language == "sql" and self._sql_schema:
            # Block switched to SQL - apply cached schema
            if hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema(self._sql_schema)
        elif language == "python":
            # Block switched to Python - apply namespace
            app_state = ApplicationState.instance()
            namespace = app_state.get_namespace()
            if hasattr(block.editor, "set_python_namespace"):
                block.editor.set_python_namespace(namespace)

    # === Block Management ===

    def add_block(self, language: str = None, code: str = "", after_block: CodeBlock = None) -> CodeBlock:
        """
        Add a new block.

        Args:
            language: 'python', 'sql', or 'cross'. If None, uses 'sql' for first block and 'python' for second
            code: Initial code
            after_block: If specified, insert after this block

        Returns:
            The new created block
        """
        # If language not specified, use SQL for first block and Python for all others
        if language is None:
            if len(self._blocks) == 0:
                language = "sql"  # First block
            else:
                language = "python"  # Second block onwards

        block = CodeBlock(theme_manager=self.theme_manager, default_language=language)
        if code:
            block.set_code(code)
        
        # Pass Copilot client for inline completions (Monaco)
        if self._copilot_client:
            block.set_copilot_client(self._copilot_client)

        # Pass LSP client for inline completions (Monaco)
        if hasattr(self, "_lsp_client") and self._lsp_client:
            block.set_lsp_client(self._lsp_client)
        
        # Pass database context for SQL completions (Monaco)
        if self._database_context:
            block.set_database_context(self._database_context)
        
        # Pass SQL schema for completions (Monaco)
        if self._sql_schema and language == "sql" and hasattr(block.editor, "set_sql_schema"):
            block.editor.set_sql_schema(self._sql_schema)

        # Connect signals
        # execute_requested runs only that block
        block.execute_requested.connect(lambda b, sel: self._on_block_execute_requested(b, sel))
        block.remove_requested.connect(self.remove_block)
        block.cancel_requested.connect(lambda b: self.cancel_all_executions())
        block.focus_changed.connect(self._on_block_focus_changed)
        block.move_requested.connect(self._on_block_move_requested)
        block.select_connection_requested.connect(self.select_connection_for_block.emit)
        block.connection_name_changed.connect(self.block_connection_changed.emit)
        block.database_changed.connect(self.block_database_changed.emit)
        block.completion_log.connect(self.completion_log.emit)
        block.editor.textChanged.connect(self.content_changed.emit)
        block.language_changed.connect(lambda b, lang: self._on_block_language_changed(b, lang))
        
        # Connect cursor position change (if editor supports it)
        if hasattr(block.editor, 'cursor_changed'):
            block.editor.cursor_changed.connect(self.cursor_changed.emit)

        # Determine position
        if after_block and after_block in self._blocks:
            index = self._blocks.index(after_block) + 1
        else:
            index = len(self._blocks)

        # Insert in list and layout
        self._blocks.insert(index, block)

        # Remove add button temporarily
        self.blocks_layout.removeWidget(self.add_button_container)

        # Insert block at correct position
        self.blocks_layout.insertWidget(index, block)

        # Re-add button at the end
        self.blocks_layout.addWidget(self.add_button_container)

        # Focus on new block after rendering
        QTimer.singleShot(50, block.focus_editor)

        # Set default name if it doesn't have one
        if not block.get_block_name():
            block.set_block_name(f"block{len(self._blocks)}")

        self.content_changed.emit()
        return block

    def remove_block(self, block: CodeBlock):
        """Remove a block"""
        if block not in self._blocks:
            return

        # Don't remove the last block
        if len(self._blocks) <= 1:
            # Instead of removing, just clear it
            block.set_code("")
            return

        index = self._blocks.index(block)
        self._blocks.remove(block)

        # Remove from layout
        self.blocks_layout.removeWidget(block)
        block.deleteLater()

        # Update focus
        if self._focused_block == block:
            if self._blocks:
                new_index = min(index, len(self._blocks) - 1)
                self._blocks[new_index].focus_editor()
            self._focused_block = None
        if self._last_focused_block == block:
            self._last_focused_block = None

        self.content_changed.emit()

    def clear_blocks(self):
        """Remove all blocks and add an empty one"""
        for block in self._blocks[:]:
            self.blocks_layout.removeWidget(block)
            block.deleteLater()
        self._blocks.clear()
        self._focused_block = None
        self._last_focused_block = None
        self.add_block()

    def _on_block_focus_changed(self, block: CodeBlock, has_focus: bool):
        """When a block gains/loses focus"""
        if has_focus:
            self._focused_block = block
            self._last_focused_block = block
            # Cursor position will be updated by the editor's cursor_changed signal
        elif self._focused_block == block:
            self._focused_block = None

    # === Public API ===

    def get_focused_block(self) -> Optional[CodeBlock]:
        """Return currently focused block"""
        return self._focused_block

    def get_last_focused_block(self) -> Optional[CodeBlock]:
        """Return last block that had focus (even if not currently focused).

        Useful for inserting text from external panels (Object Explorer,
        Variables) where clicking the panel removes editor focus.
        """
        # Validate that block still exists in blocks list
        if self._last_focused_block and self._last_focused_block in self._blocks:
            return self._last_focused_block
        if self._focused_block and self._focused_block in self._blocks:
            return self._focused_block
        # Fallback: first block
        return self._blocks[0] if self._blocks else None

    def focus_first_block(self):
        """Focus on first code block"""
        if self._blocks:
            self._blocks[0].focus_editor()

    def get_blocks(self) -> List[CodeBlock]:
        """Return list of all blocks"""
        return self._blocks.copy()

    def get_block_count(self) -> int:
        """Return number of blocks"""
        return len(self._blocks)

    def get_all_code(self) -> str:
        """Return all code concatenated (with separators)"""
        parts = []
        for i, block in enumerate(self._blocks):
            code = block.get_code().strip()
            if code:
                lang = block.get_language()
                parts.append(f"# === Block {i + 1} ({lang.upper()}) ===")
                parts.append(code)
                parts.append("")
        return "\n".join(parts)

    def text(self) -> str:
        """Alias for get_all_code - compatibility"""
        return self.get_all_code()

    def setText(self, text: str):
        """
        Set text (compatibility with old editor).
        Try to detect blocks in text or put everything in one block.
        """
        self.clear_blocks()

        if not text.strip():
            return

        # Try to detect block markers
        if "# === Block" in text or "# === Bloco" in text:
            self._parse_blocks_from_text(text)
        else:
            # Put everything in a single block
            # Detect language by content
            lang = self._detect_language(text)
            self._blocks[0].set_language(lang)
            self._blocks[0].set_code(text)

    def _parse_blocks_from_text(self, text: str):
        """Parse text with block markers"""
        import re

        # Pattern: # === Block N (LANG) === OR # === Bloco N (LANG) ===
        pattern = r"# === (Block|Bloco) \d+ \((\w+)\) ==="
        parts = re.split(pattern, text)

        # parts[0] is text before first marker (usually empty)
        # Then alternates: "Block"/"Bloco", lang, code, "Block"/"Bloco", lang, code, ...

        if len(parts) > 1:
            self._blocks[0].set_code("")  # Clear first block

            i = 1
            first = True
            while i < len(parts):
                # Skip the "Block"/"Bloco" capture group
                lang = parts[i+1].lower()
                code = parts[i + 2].strip() if i + 2 < len(parts) else ""

                if first:
                    self._blocks[0].set_language(lang)
                    self._blocks[0].set_code(code)
                    first = False
                else:
                    self.add_block(lang, code)

                i += 3  # Skip: block_word, lang, code

    def _detect_language(self, text: str) -> str:
        """Detect probable code language"""
        text_lower = text.lower()

        # Cross-syntax tem {{ }}
        if "{{" in text and "}}" in text:
            return "cross"

        # SQL keywords
        sql_keywords = ["select", "insert", "update", "delete", "create", "drop", "alter", "from", "where", "join"]
        sql_count = sum(1 for kw in sql_keywords if kw in text_lower)

        # Python keywords
        py_keywords = ["def ", "class ", "import ", "from ", "if ", "for ", "while ", "print(", "return "]
        py_count = sum(1 for kw in py_keywords if kw in text_lower)

        if sql_count > py_count:
            return "sql"
        return "python"

    def apply_theme(self):
        """Apply theme to all blocks"""
        for block in self._blocks:
            block.apply_theme()

    def to_list(self) -> List[dict]:
        """Serialize all blocks to list of dicts"""
        return [block.to_dict() for block in self._blocks]

    def from_list(self, blocks_data: List[dict]):
        """Load blocks from list of dicts"""
        self.clear_blocks()

        if not blocks_data:
            return

        for i, data in enumerate(blocks_data):
            if i == 0:
                # First block already exists
                block = self._blocks[0]
                block.set_language(data.get("language", "python"))
                block.set_code(data.get("code", ""))
            else:
                block = self.add_block(language=data.get("language", "python"), code=data.get("code", ""))

            # Restore block name
            if "block_name" in data and data["block_name"]:
                block.set_block_name(data["block_name"])

            # Restore custom connection if exists
            if "connection_name" in data:
                block.set_connection_name(data["connection_name"], data.get("db_type"))

            # Restore custom database if exists
            if "database_name" in data and data["database_name"]:
                block.set_database_name(data["database_name"])

    # === Compatibility with UnifiedEditor ===

    def clear(self):
        """Compatibility: clear all blocks"""
        self.clear_blocks()

    def get_selected_or_all_text(self) -> str:
        """Compatibility: return selection or all code"""
        if self._focused_block and self._focused_block.has_selection():
            return self._focused_block.get_selected_text()
        return self.get_all_code()

    def get_focused_block_code(self) -> str:
        """Return code of currently focused block"""
        if self._focused_block:
            return self._focused_block.get_code()
        # If no focused block, return first one
        if self._blocks:
            return self._blocks[0].get_code()
        return ""

    def execute_focused_block(self):
        """Execute only focused block with its language"""
        block = self._focused_block
        if not block and self._blocks:
            block = self._blocks[0]

        if block:
            if block.has_selection():
                code = block.get_selected_text()
            else:
                code = block.get_code()
            lang = block.get_language()
            self._execute_code(code, lang, block)

    def hasSelectedText(self) -> bool:
        """Compatibility: check if there's a selection"""
        return self._focused_block and self._focused_block.has_selection()

    def selectedText(self) -> str:
        """Compatibility: return selected text"""
        if self._focused_block:
            return self._focused_block.get_selected_text()
        return ""

    # === Unified execution (F5 and button do the same thing) ===

    def _on_block_execute_requested(self, block: CodeBlock, selected_text: str = ""):
        """
        Handler when a block requests execution (F5 or run button).

        Logic:
        - If there's a selection: run only selection
        - If no selection: run only this block
        
        Args:
            block: The CodeBlock requesting execution
            selected_text: Selected text from the editor (empty if no selection)
        """
        print(f"[BlockEditor] _on_block_execute_requested: selected_text={len(selected_text)} chars")
        if selected_text:
            # Run only selection from this block
            print(f"[BlockEditor] Running selected text ({len(selected_text)} chars): {selected_text[:50]!r}...")
            lang = block.get_language()
            self._execute_code(selected_text, lang, block)
        else:
            # Run only this block
            print("[BlockEditor] Running full block (no selection)")
            self._execute_block(block)

    # === Drag and Drop ===

    def _on_block_move_requested(self, block: CodeBlock, new_index: int):
        """When a block starts drag"""
        if new_index == -1:
            # Drag started
            self._dragging_block = block

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Accept drag of blocks, files, connections, and databases"""
        mime_data = event.mimeData()

        # Accept block drag
        if mime_data.hasText():
            text = mime_data.text()
            if text.startswith("block:"):
                event.acceptProposedAction()
                return

        # Accept connection or database drag
        if mime_data.hasFormat("application/x-connection-name") or mime_data.hasFormat(
            "application/x-database-name"
        ):
            event.acceptProposedAction()
            return

        # Accept file drag (CSV, JSON, XLSX, SQL, PY, DPW)
        if mime_data.hasUrls():
            urls = mime_data.urls()
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith((".csv", ".json", ".xlsx", ".xls", ".sql", ".py")):
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event):
        """During drag, show where block will be inserted"""
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """When a block, file, connection, or database is dropped"""
        mime_data = event.mimeData()

        # Process connection or database drop -> create SQL block
        if mime_data.hasFormat("application/x-connection-name") or mime_data.hasFormat(
            "application/x-database-name"
        ):
            self._handle_connection_drop(mime_data)
            event.acceptProposedAction()
            return

        # Process file drop
        if mime_data.hasUrls():
            urls = mime_data.urls()
            for url in urls:
                file_path = url.toLocalFile()
                lower_path = file_path.lower()
                if lower_path.endswith((".csv", ".json", ".xlsx", ".xls")):
                    # Emit signal to open import dialog
                    self.file_dropped.emit(file_path)
                    self.content_changed.emit()
                elif lower_path.endswith(".sql"):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        self.add_block(language="sql", code=content)
                        self.content_changed.emit()
                    except Exception:
                        pass
                elif lower_path.endswith(".py"):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        self.add_block(language="python", code=content)
                        self.content_changed.emit()
                    except Exception:
                        pass
            event.acceptProposedAction()
            return

        # Process block drop (existing code)
        if not self._dragging_block:
            return

        # Find drop position
        drop_pos = event.position().toPoint()
        drop_index = self._find_drop_index(drop_pos)

        # Move block
        self._move_block(self._dragging_block, drop_index)

        self._dragging_block = None
        event.acceptProposedAction()

    def _handle_connection_drop(self, mime_data):
        """Handle drop of a connection or database from panels.

        Creates a new SQL block pre-configured with the dropped connection
        and optionally the database.
        """
        conn_name = ""
        db_type = ""
        color = ""
        db_name = ""

        if mime_data.hasFormat("application/x-connection-name"):
            conn_name = bytes(mime_data.data("application/x-connection-name")).decode("utf-8")
        if mime_data.hasFormat("application/x-db-type"):
            db_type = bytes(mime_data.data("application/x-db-type")).decode("utf-8")
        if mime_data.hasFormat("application/x-connection-color"):
            color = bytes(mime_data.data("application/x-connection-color")).decode("utf-8")
        if mime_data.hasFormat("application/x-database-name"):
            db_name = bytes(mime_data.data("application/x-database-name")).decode("utf-8")

        block = self.add_block(language="sql")

        if conn_name:
            block.set_connection_name(conn_name, db_type=db_type or None, color=color or None)

        if db_name:
            block.set_database_name(db_name)

        block.editor.setFocus()
        self.content_changed.emit()

    def _find_drop_index(self, pos) -> int:
        """Find index where block should be inserted"""
        # Map position to scroll area
        scroll_pos = self.scroll_area.mapFromParent(pos)
        container_pos = self.blocks_container.mapFromParent(scroll_pos)

        for i, block in enumerate(self._blocks):
            block_geometry = block.geometry()
            block_center_y = block_geometry.y() + block_geometry.height() // 2

            if container_pos.y() < block_center_y:
                return i

        return len(self._blocks)

    def _move_block(self, block: CodeBlock, new_index: int):
        """Move a block to new position"""
        if block not in self._blocks:
            return

        old_index = self._blocks.index(block)
        if old_index == new_index:
            return

        # Adjust index if moving forward
        if new_index > old_index:
            new_index -= 1

        # Remove from current position
        self._blocks.remove(block)
        self.blocks_layout.removeWidget(block)

        # Insert at new position
        self._blocks.insert(new_index, block)
        self.blocks_layout.insertWidget(new_index, block)

        self.content_changed.emit()

    def _generate_import_code(self, file_path: str) -> Optional[str]:
        """
        Generate pandas import code based on file extension.

        Args:
            file_path: Full file path

        Returns:
            Python code to import file or None if extension not supported
        """
        if not file_path:
            return None

        # Normalize path (use raw string for Windows)
        # Use regular slashes as Python accepts them on both systems
        normalized_path = file_path.replace("\\", "/")

        # Extract extension
        _, ext = os.path.splitext(file_path.lower())

        # Generate code based on extension
        # pandas is already available as 'pd' in execution namespace
        if ext == ".csv":
            return f"df = pd.read_csv('{normalized_path}')"
        elif ext == ".json":
            return f"df = pd.read_json('{normalized_path}')"
        elif ext in (".xlsx", ".xls"):
            return f"df = pd.read_excel('{normalized_path}')"

        return None
