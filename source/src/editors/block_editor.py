"""
BlockEditor - Container that manages multiple code blocks

Similar to a Jupyter notebook, but focused on SQL/Python execution
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QPushButton,
    QToolButton,
    QHBoxLayout,
    QFrame,
    QSizePolicy,
    QSpacerItem,
    QLabel,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QUrl, QEvent, QSize
from PyQt6.QtGui import QKeyEvent, QDragEnterEvent, QDropEvent, QKeySequence
from typing import List, Optional
import os
import qtawesome as qta

from src.core.theme_manager import ThemeManager
from src.state.app_state import ApplicationState
from src.editors.code_block import CodeBlock
from src.language import S


class StickyBlockHeader(QWidget):
    """Pinned clone of the active block header while scrolling the notebook."""

    HEADER_HEIGHT = 42

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stickyBlockHeader")
        self.setFixedHeight(self.HEADER_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()

        from src.design_system.tokens import get_colors

        colors = get_colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self._lang_icon = QLabel()
        self._lang_icon.setFixedSize(18, 18)
        layout.addWidget(self._lang_icon)

        self._lang_label = QLabel()
        self._lang_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(self._lang_label)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._name_label, 1)

        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._status_label)

        self._bound_block: Optional[CodeBlock] = None

    def sync_from_block(self, block: CodeBlock) -> None:
        from src.design_system.tokens import get_colors

        self._bound_block = block
        colors = get_colors()
        lang = block.get_language()
        accent = CodeBlock.LANGUAGE_COLORS.get(lang, "#888")
        icon_color = "#E38C00" if lang == "sql" else "#3572A5"
        icon_name = "mdi.database" if lang == "sql" else "mdi.language-python"
        self._lang_icon.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(18, 18))
        self._lang_label.setText(lang.upper())
        name = (block.get_block_name() or "").strip()
        self._name_label.setText(name or S.block.placeholder_name)
        status = block.status_label.text().strip()
        self._status_label.setText(status)
        self._status_label.setVisible(bool(status))

        self.setStyleSheet(f"""
            StickyBlockHeader {{
                background: {colors.bg_secondary};
                border-bottom: 1px solid {colors.border_muted};
                border-left: 3px solid {accent};
            }}
        """)

    def mousePressEvent(self, event):
        if self._bound_block is not None:
            host = self.parent()
            while host is not None and not isinstance(host, BlockEditor):
                host = host.parent()
            if isinstance(host, BlockEditor):
                host.scroll_area.ensureWidgetVisible(self._bound_block, 0, 60)
                self._bound_block.focus_editor()
        super().mousePressEvent(event)


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
    execute_sql = pyqtSignal(str, object, object, object, object)  # query, block_name, connection_name, database_name, sql_parameters
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

    # Signal when focused block changes (for Object Explorer tracking)
    block_focused = pyqtSignal(object)  # CodeBlock that gained focus

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
        self._pynia_client = None  # Pynia agent for inline autocomplete
        self._copilot_client = None  # Deprecated alias storage
        self._lsp_client = None  # LSP client for inline completions
        self._database_context = ""  # Database schema context for SQL completions
        self._sql_schema = {}  # Cached SQL schema for completions
        self._maximized_block: Optional[CodeBlock] = None  # Block in maximized/focus mode
        self._session = None  # SessionWidget tab — namespace with SQL DataFrames

        self._completion_context_timer = QTimer(self)
        self._completion_context_timer.setSingleShot(True)
        self._completion_context_timer.setInterval(1200)
        self._completion_context_timer.timeout.connect(
            lambda: self.refresh_completion_context(self._focused_block)
        )

        self._setup_ui()

        # Enable drop
        self.setAcceptDrops(True)

        # Create first empty block
        self.add_block()

    # === Public Properties ===

    def set_pynia_client(self, client) -> None:
        """Set Pynia agent client for inline autocomplete in all blocks."""
        self._pynia_client = client
        self._copilot_client = client
        for block in self._blocks:
            block.set_pynia_client(client)

    def set_copilot_client(self, client) -> None:
        """Backward-compatible alias for set_pynia_client."""
        self.set_pynia_client(client)

    def set_lsp_client(self, client) -> None:
        """Set LSP client for inline completions in all blocks."""
        self._lsp_client = client
        for block in self._blocks:
            block.set_lsp_client(client)

    def _schedule_completion_context_refresh(self) -> None:
        """Debounce LSP/Monaco context refresh while the user edits."""
        self._completion_context_timer.start()
    
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

        self._sticky_header = StickyBlockHeader(self.scroll_area.viewport())
        self._sticky_header.raise_()
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._update_sticky_header)
        self.scroll_area.viewport().installEventFilter(self)

        # Add-block strip (divider + centered pill, matches tab accessory controls)
        from src.design_system.tokens import get_colors
        from src.design_system.tab_controls import TAB_ACCESSORY_BUTTON_SIZE, TAB_ACCESSORY_ICON_SIZE

        colors = get_colors()
        btn_size = TAB_ACCESSORY_BUTTON_SIZE
        self.add_button_container = QWidget()
        self.add_button_container.setObjectName("blockAddStrip")
        add_outer = QVBoxLayout(self.add_button_container)
        add_outer.setContentsMargins(12, 10, 12, 12)
        add_outer.setSpacing(0)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setFixedHeight(1)
        line_left.setStyleSheet(f"background-color: {colors.border_muted}; border: none; max-height: 1px;")

        self.add_btn = QToolButton()
        self.add_btn.setObjectName("blockAddButton")
        self.add_btn.setAutoRaise(True)
        self.add_btn.setIcon(
            qta.icon("mdi.plus", color=colors.text_secondary, scale_factor=0.85)
        )
        self.add_btn.setToolTip(S.block_editor.tooltip_add_block)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(btn_size, btn_size)
        self.add_btn.setIconSize(QSize(TAB_ACCESSORY_ICON_SIZE, TAB_ACCESSORY_ICON_SIZE))
        self.add_btn.setStyleSheet(f"""
            QToolButton#blockAddButton {{
                background-color: {colors.bg_tertiary};
                border: 1px solid {colors.border_muted};
                border-radius: {btn_size // 2}px;
                padding: 0px;
            }}
            QToolButton#blockAddButton:hover {{
                background-color: {colors.bg_elevated};
                border-color: {colors.interactive_primary};
            }}
            QToolButton#blockAddButton:pressed {{
                background-color: {colors.bg_secondary};
            }}
        """)
        self.add_btn.clicked.connect(lambda: self.add_block())

        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setFixedHeight(1)
        line_right.setStyleSheet(line_left.styleSheet())

        row_layout.addWidget(line_left, 1)
        row_layout.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(line_right, 1)
        add_outer.addWidget(row)

        self.blocks_layout.addWidget(self.add_button_container)

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self._position_sticky_header()
        return super().eventFilter(obj, event)

    def _position_sticky_header(self) -> None:
        if not hasattr(self, "_sticky_header"):
            return
        viewport = self.scroll_area.viewport()
        self._sticky_header.setFixedWidth(viewport.width())

    def _update_sticky_header(self) -> None:
        """Show a pinned header for the block currently crossing the scroll top."""
        if not hasattr(self, "_sticky_header"):
            return
        self._position_sticky_header()

        if self._maximized_block or len(self._blocks) <= 1:
            self._sticky_header.hide()
            return

        scroll_top = self.scroll_area.verticalScrollBar().value()
        sticky_block: Optional[CodeBlock] = None
        for block in self._blocks:
            top = block.pos().y()
            if top <= scroll_top + 2:
                sticky_block = block

        if sticky_block is None:
            self._sticky_header.hide()
            return

        header_bottom = sticky_block.pos().y() + sticky_block.control_bar.height()
        if header_bottom >= scroll_top + 4:
            self._sticky_header.hide()
            return

        self._sticky_header.sync_from_block(sticky_block)
        self._sticky_header.show()
        self._sticky_header.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_sticky_header()

    def keyPressEvent(self, event: QKeyEvent):
        """Intercept keys for execution shortcuts (reads from ShortcutManager)"""
        from src.core.shortcut_manager import ShortcutManager
        sm = ShortcutManager()

        # Build QKeySequence from event (PyQt6 enums need .value for int conversion)
        modifiers = event.modifiers()
        mod_val = modifiers.value if hasattr(modifiers, 'value') else int(modifiers)
        key_seq = QKeySequence(mod_val | event.key())

        # Execute SQL (default F5)
        exec_key = sm.get_shortcut("execute_sql")
        if exec_key and key_seq.matches(QKeySequence(exec_key)) == QKeySequence.SequenceMatch.ExactMatch:
            self._execute_smart()
            return

        # Execute All (default Ctrl+F5 / Ctrl+Enter)
        exec_all_key = sm.get_shortcut("execute_all")
        if exec_all_key and key_seq.matches(QKeySequence(exec_all_key)) == QKeySequence.SequenceMatch.ExactMatch:
            self.execute_all_blocks()
            return

        # Escape - restore from maximized mode
        if event.key() == Qt.Key.Key_Escape and self._maximized_block:
            self._restore_all_blocks()
            return

        super().keyPressEvent(event)

    def _execute_smart(self):
        """
        Run intelligently:
        - If there's a selection in focused block: runs selection with block's language
        - If no selection: runs focused block
        """
        if self._focused_block:
            editor = getattr(self._focused_block, "editor", None)
            if editor is not None and hasattr(editor, "request_execute"):
                editor.request_execute()
                return
            has_sel = self._focused_block.has_selection()
            if has_sel:
                code = self._focused_block.get_selected_text()
                lang = self._focused_block.get_language()
                self._execute_code(code, lang, self._focused_block)
                return

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

    def execute_block(self, block: CodeBlock):
        """Run a specific block (public API for MCP tools and internal use)."""
        code = block.get_code().strip()
        if not code:
            return

        lang = block.get_language()
        self._execute_code(code, lang, block)

    # Keep private alias for backward compatibility
    _execute_block = execute_block

    def _execute_code(self, code: str, language: str, block: CodeBlock):
        """Emit appropriate execution signal"""
        self._current_executing_block = block
        block.set_running(True)

        if language == "sql":
            block_name = block.get_block_name()
            connection_name = block.get_connection_name()
            database_name = block.get_database_name()
            get_sql_parameters = getattr(block, "get_sql_parameters_for_query", None)
            sql_parameters = get_sql_parameters(code) if callable(get_sql_parameters) else []
            if not isinstance(sql_parameters, list):
                sql_parameters = []
            self.execute_sql.emit(code, block_name, connection_name, database_name, sql_parameters)
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
            if code and block.is_active():
                get_sql_parameters = getattr(block, "get_sql_parameters_for_query", None)
                sql_parameters = get_sql_parameters(code) if callable(get_sql_parameters) else []
                if not isinstance(sql_parameters, list):
                    sql_parameters = []
                # Tuple: (language, code, block, block_name, connection_name, database_name, sql_parameters)
                queue.append((block.get_language(), code, block, block.get_block_name(), block.get_connection_name(), block.get_database_name(), sql_parameters))
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

    def get_current_block_index(self) -> Optional[int]:
        """Return index of the currently executing block, or focused block as fallback."""
        block = self._current_executing_block or self.get_focused_block()
        if block and block in self._blocks:
            return self._blocks.index(block)
        return None

    def bind_session(self, session) -> None:
        """Attach tab session so completions use executed DataFrames (not global state)."""
        self._session = session
        for block in self._blocks:
            block.set_block_editor(self)
        self.refresh_completion_context()

    def _get_completion_namespace(self) -> dict:
        if self._session is not None:
            if hasattr(self._session, "effective_namespace"):
                return self._session.effective_namespace()
            if hasattr(self._session, "namespace"):
                return self._session.namespace
        return ApplicationState.instance().get_namespace()

    # === Autocomplete Management ===

    def refresh_completion_context(
        self,
        focus_block: Optional[CodeBlock] = None,
        *,
        sync_lsp_documents: bool = False,
    ) -> None:
        """Push in-memory session context (namespace, blocks) to Monaco + LSP.

        Schema/SQL autocomplete is applied via set_sql_schema — do not reopen every
        LSP document here or schema load will stall the UI.
        """
        from src.editors.completion_context import (
            build_lsp_preamble_for_block,
            build_sibling_block_completions,
            collect_session_python_context,
        )

        namespace = self._get_completion_namespace()
        shared_imports = collect_session_python_context(
            self._blocks, namespace
        ).global_imports

        for block in self._blocks:
            try:
                lang = block.get_language()
                py_ctx = collect_session_python_context(
                    self._blocks, namespace, current_block=block if lang == "python" else None
                )
                preamble, line_offset = build_lsp_preamble_for_block(
                    lang,
                    global_imports=shared_imports,
                    namespace=namespace,
                    blocks_code_context=py_ctx.blocks_code_context,
                    database_context=self._database_context,
                )

                if hasattr(block, "apply_session_completion_context"):
                    block.apply_session_completion_context(
                        namespace=namespace if lang == "python" else None,
                        global_imports=shared_imports if lang == "python" else "",
                        blocks_code_context=py_ctx.blocks_code_context if lang == "python" else "",
                        lsp_preamble=preamble,
                        lsp_line_offset=line_offset,
                    )
                else:
                    if lang == "python":
                        block.set_python_namespace(namespace)
                    block.set_lsp_completion_preamble(preamble, line_offset)

                if hasattr(block, "editor") and hasattr(block.editor, "set_sibling_block_completions"):
                    block.editor.set_sibling_block_completions(
                        build_sibling_block_completions(
                            self._blocks,
                            current_block=block,
                            target_language=lang,
                        )
                    )

                if sync_lsp_documents and (
                    focus_block is None or block is focus_block
                ) and hasattr(block, "_update_document_info"):
                    block._update_document_info()
            except Exception as exc:
                import logging

                logging.getLogger(__name__).debug(
                    "refresh_completion_context skipped block: %s", exc
                )

    def update_python_completions_all(self):
        """Update Python completions for all Python blocks with current namespace."""
        self.refresh_completion_context()
    
    def set_database_context(self, context: str):
        """Set database context for SQL completions (Monaco)."""
        self._database_context = context
        for block in self._blocks:
            if hasattr(block, "set_database_context"):
                block.set_database_context(context)
    
    def set_sql_schema(self, schema: dict):
        """Set SQL schema for autocomplete in all SQL blocks.

        Args:
            schema: Dict with tables, columns, database info from SchemaService
        """
        self._sql_schema = schema or {}
        for block in self._blocks:
            if block.get_language() != "sql":
                continue
            if hasattr(block, "set_sql_schema"):
                block.set_sql_schema(self._sql_schema)
            elif hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema(self._sql_schema)
    
    def _on_block_language_changed(self, block: CodeBlock, language: str):
        """Handle block language change - update completions."""
        self._update_sticky_header()
        if language == "sql" and self._sql_schema:
            # Block switched to SQL - apply cached schema
            if hasattr(block, "set_sql_schema"):
                block.set_sql_schema(self._sql_schema)
        elif language == "python":
            self.refresh_completion_context(focus_block=block)

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
        block.set_block_editor(self)
        if code:
            block.set_code(code)
        
        # Pynia inline autocomplete (Monaco)
        if self._pynia_client:
            block.set_pynia_client(self._pynia_client)
        elif self._copilot_client:
            block.set_pynia_client(self._copilot_client)

        # Pass LSP client for inline completions (Monaco)
        if hasattr(self, "_lsp_client") and self._lsp_client:
            block.set_lsp_client(self._lsp_client)
        
        # Pass database context for SQL completions (Monaco)
        if self._database_context:
            block.set_database_context(self._database_context)
        
        # Pass SQL schema for completions (Monaco)
        if self._sql_schema and language == "sql" and hasattr(block, "set_sql_schema"):
            block.set_sql_schema(self._sql_schema)

        self.refresh_completion_context(focus_block=block)

        # Connect signals
        # execute_requested runs only that block
        block.execute_requested.connect(lambda b, sel: self._on_block_execute_requested(b, sel))
        block.remove_requested.connect(self.remove_block)
        block.cancel_requested.connect(lambda b: self.cancel_all_executions())
        block.focus_changed.connect(self._on_block_focus_changed)
        if hasattr(block, "name_input"):
            block.name_input.textChanged.connect(self._update_sticky_header)
        block.move_requested.connect(self._on_block_move_requested)
        block.select_connection_requested.connect(self.select_connection_for_block.emit)
        block.connection_name_changed.connect(self.block_connection_changed.emit)
        block.database_changed.connect(self.block_database_changed.emit)
        block.completion_log.connect(self.completion_log.emit)
        block.editor.textChanged.connect(self.content_changed.emit)
        block.editor.textChanged.connect(self._schedule_completion_context_refresh)
        block.language_changed.connect(lambda b, lang: self._on_block_language_changed(b, lang))
        block.maximize_requested.connect(self._toggle_maximize_block)
        
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
        QTimer.singleShot(0, self._update_sticky_header)

        # Set default name if it doesn't have one
        if not block.get_block_name():
            block.set_block_name(f"block{len(self._blocks)}")

        # Lock connection panel for first block (always uses tab connection)
        if index == 0:
            block.set_connection_locked(True)

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
        was_first = (index == 0)

        # If removing the maximized block, restore all first
        if self._maximized_block == block:
            self._restore_all_blocks()

        self._blocks.remove(block)

        # Remove from layout
        self.blocks_layout.removeWidget(block)
        block.cleanup()
        block.deleteLater()

        # If first block was removed, lock the new first block
        if was_first and self._blocks:
            self._blocks[0].set_connection_locked(True)
            # Clear any custom connection from what is now the first block
            self._blocks[0].set_connection_name(None)

        # Update focus
        if self._focused_block == block:
            if self._blocks:
                new_index = min(index, len(self._blocks) - 1)
                self._blocks[new_index].focus_editor()
            self._focused_block = None
        if self._last_focused_block == block:
            self._last_focused_block = None

        self.content_changed.emit()
        QTimer.singleShot(0, self._update_sticky_header)

    def _toggle_maximize_block(self, block: CodeBlock):
        """Toggle maximize/restore for a block."""
        if self._maximized_block == block:
            self._restore_all_blocks()
        else:
            self._maximize_block(block)

    def _maximize_block(self, block: CodeBlock):
        """Maximize a single block, hiding all others."""
        if block not in self._blocks:
            return

        # Restore previous maximized block if any
        if self._maximized_block:
            self._maximized_block.set_maximized(False)

        self._maximized_block = block

        # Save original editor height for restoration
        self._saved_editor_height = block.editor_container.height()

        # Hide all other blocks and the add button
        for b in self._blocks:
            if b != block:
                b.hide()
        self.add_button_container.hide()

        # Set maximized state on the target block
        block.set_maximized(True)
        block.show()

        # Remove layout alignment and margins so block fills all space
        self.blocks_layout.setAlignment(Qt.AlignmentFlag(0))
        self.blocks_layout.setContentsMargins(0, 0, 0, 0)
        self.blocks_layout.setSpacing(0)
        block.focus_editor()
        self._sticky_header.hide()

    def _restore_all_blocks(self):
        """Restore all blocks from maximized mode."""
        if self._maximized_block:
            # Restore original editor height
            saved = getattr(self, '_saved_editor_height', 0)
            if saved > 0:
                self._maximized_block.editor_container.setFixedHeight(saved)
            self._maximized_block.set_maximized(False)
            self._maximized_block = None

        # Show all blocks
        for b in self._blocks:
            b.show()
        self.add_button_container.show()

        # Restore top alignment, margins and spacing
        self.blocks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.blocks_layout.setContentsMargins(8, 8, 8, 8)
        self.blocks_layout.setSpacing(12)
        QTimer.singleShot(0, self._update_sticky_header)

    @property
    def is_maximized(self) -> bool:
        """Whether a block is currently maximized."""
        return self._maximized_block is not None

    def clear_blocks(self):
        """Remove all blocks and add an empty one"""
        for block in self._blocks[:]:
            self.blocks_layout.removeWidget(block)
            block.cleanup()
            block.deleteLater()
        self._blocks.clear()
        self._focused_block = None
        self._last_focused_block = None
        block = self.add_block()
        # First block is already locked by add_block, but ensure it's set
        block.set_connection_locked(True)

    def _on_block_focus_changed(self, block: CodeBlock, has_focus: bool):
        """When a block gains/loses focus"""
        if has_focus:
            self._focused_block = block
            self._last_focused_block = block
            if self._sql_schema and block.get_language() == "sql":
                if hasattr(block, "set_sql_schema"):
                    block.set_sql_schema(self._sql_schema)
            self.refresh_completion_context(
                focus_block=block, sync_lsp_documents=True
            )
            # Notify listeners (MainWindow) so Object Explorer can track focused connection
            self.block_focused.emit(block)
            # Cursor position will be updated by the editor's cursor_changed signal
        elif self._focused_block == block:
            self._focused_block = None

    # === Public API ===

    def get_focused_block(self) -> Optional[CodeBlock]:
        """Return currently focused block"""
        return self._focused_block

    def focus_block_at_line(self, block_index: int, line_number: int = 1, column: int = 0):
        """Focus a block by index and scroll to a specific line/column.

        Used by the Output panel to navigate to error locations.
        """
        if block_index < 0 or block_index >= len(self._blocks):
            return
        block = self._blocks[block_index]
        # Ensure block is visible (expand if minimized)
        if hasattr(block, 'is_minimized') and block.is_minimized:
            block.toggle_minimize()
        # Scroll to make the block visible
        self.scroll_area.ensureWidgetVisible(block)
        # Focus the editor
        if hasattr(block, 'editor'):
            block.editor.setFocus()
            # Go to line/column (0-based in QScintilla)
            if hasattr(block.editor, 'setCursorPosition'):
                line_0 = max(0, line_number - 1)
                col_0 = max(0, column - 1) if column > 0 else 0
                block.editor.setCursorPosition(line_0, col_0)
        self.block_focused.emit(block)

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
                # First block already exists (and is already locked)
                block = self._blocks[0]
                block.set_language(data.get("language", "python"))
                block.set_code(data.get("code", ""))
                # First block cannot have custom connection - ignore it from saved data
            else:
                block = self.add_block(language=data.get("language", "python"), code=data.get("code", ""))

                # Restore custom connection only for blocks after the first
                if "connection_name" in data:
                    block.set_connection_name(data["connection_name"], data.get("db_type"))

            # Restore block name
            if "block_name" in data and data["block_name"]:
                block.set_block_name(data["block_name"])

            # Restore custom database if exists
            if "database_name" in data and data["database_name"]:
                block.set_database_name(data["database_name"])

            # Restore SQL parameter definitions for all blocks, including the first one
            if "sql_parameters" in data and hasattr(block, "set_sql_parameters"):
                block.set_sql_parameters(data.get("sql_parameters") or [])
            if "sql_parameters_enabled" in data and hasattr(block, "set_sql_parameters_enabled"):
                block.set_sql_parameters_enabled(data.get("sql_parameters_enabled", True))

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
    
    def force_autocomplete_focused_block(self):
        """Force autocomplete on the focused block (Ctrl+. shortcut)."""
        block = self._focused_block
        if not block and self._blocks:
            block = self._blocks[0]
        
        if block and hasattr(block, 'force_autocomplete'):
            block.force_autocomplete()

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

    def cleanup(self):
        for block in self._blocks[:]:
            block.cleanup()

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
