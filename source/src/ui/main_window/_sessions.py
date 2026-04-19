"""
SessionsMixin - Session lifecycle, tab events, persistence, empty state.
"""

from __future__ import annotations

import logging
import weakref
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject, QSettings
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QApplication,
)
from PyQt6.QtGui import QFont, QColor

from src.ui.components.session_widget import SessionWidget
from src.design_system.tokens import get_colors
from src.language import S

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


class SessionsMixin:
    """Handles session lifecycle, tab events, empty state, persistence."""

    def _close_current_session(self):
        """Closes the current session/tab - delegates to _close_session_tab"""
        current_index = self.session_tabs.currentIndex()
        if current_index >= 0:
            widget = self.session_tabs.widget(current_index)
            if isinstance(widget, SessionWidget):
                # Confirmar fechamento se houver codigo nao salvo
                has_code = any(block.get_code().strip() for block in widget.editor.get_blocks())
                if has_code:
                    reply = QMessageBox.question(
                        self,
                        S.dialogs.close_session_title,
                        S.dialogs.close_session_msg,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return

                # Delegar para _close_session_tab que faz cleanup completo
                self._close_session_tab(current_index)

    def _duplicate_session(self, index: int):
        """Duplicates a session - creates new session with panels and copies content"""
        widget = self.session_tabs.widget(index)
        if not widget or not hasattr(widget, "editor"):
            return

        # Guard para evitar que _on_session_tab_changed dispare _new_session
        self._creating_session = True
        try:
            # Create new session with panels
            session = self.session_manager.create_session()
            new_widget = SessionWidget(session, theme_manager=self.theme_manager)

            # Create panels for new session
            self._create_session_panels(session.session_id)

            # Copy all editor content
            source_blocks = widget.editor.get_blocks()

            # Remove existing blocks from new session (except last)
            new_blocks = new_widget.editor.get_blocks()
            for b in new_blocks[:-1]:
                new_widget.editor.remove_block(b)

            # If source has blocks, use first empty block from new session
            if source_blocks:
                first_new_block = new_widget.editor.get_blocks()[0]
                first_new_block.set_language(source_blocks[0].get_language())
                first_new_block.set_code(source_blocks[0].get_code())

                # Add remaining blocks
                for block in source_blocks[1:]:
                    new_block = new_widget.editor.add_block(language=block.get_language())
                    new_block.set_code(block.get_code())

            # Copy file_path if exists
            if hasattr(widget, "file_path"):
                new_widget.file_path = widget.file_path

            # Inherit connection from original session
            if hasattr(widget, "session") and widget.session.connection_name:
                try:
                    connected = session.connect(widget.session.connection_name)
                    if not connected:
                        pass  # Connection failed, session remains without connection
                except Exception:
                    pass

            # Connect signals do widget
            new_widget.status_changed.connect(lambda msg: self._on_session_status_changed(session, msg))
            new_widget.connection_changed.connect(
                lambda conn_name, db: self._on_session_connection_changed(session, conn_name, db)
            )
            new_widget.block_connection_changed.connect(
                lambda block, conn_name: self._on_block_connection_changed(block, conn_name)
            )
            new_widget.connection_drop_requested.connect(
                lambda conn_name: self._quick_connect(conn_name)
            )
            new_widget.block_database_changed.connect(
                lambda block, db_name: self._on_block_database_changed(block, db_name)
            )
            new_widget.execution_finished.connect(
                lambda title, msg, success, w=new_widget: self._on_execution_finished_notification(
                    title, msg, success, w
                )
            )
            new_widget.execution_cancelled.connect(
                lambda w=new_widget: self._on_execution_cancelled(w)
            )
            new_widget.completion_log.connect(self._on_completion_log)
            new_widget.cursor_changed.connect(self._on_cursor_position_changed)

            # Block focus change (for Object Explorer connection tracking)
            new_widget.block_focused.connect(
                lambda block, w=new_widget: self._on_block_focused(block, w)
            )

            # Register widget
            self._session_widgets[session.session_id] = new_widget

            # New tab name
            original_name = self.session_tabs.tabText(index)
            new_name = f"{original_name} (copia)"

            # Insert before last tab (new tab button)
            insert_position = self.session_tabs.count() - 1 if self.session_tabs.count() > 0 else 0
            tab_index = self.session_tabs.insertTab(insert_position, new_widget, new_name)

            # Configure custom close button
            self.session_tabs._setup_close_button(tab_index)

            # Apply tab color if original session had connection
            if session.connection_name:
                config = self.connection_manager.get_connection_config(session.connection_name)
                if config:
                    color = config.get("color", "#007ACC") or "#007ACC"
                    self.session_tabs.set_tab_connection_color(tab_index, color)

            self.session_tabs.setCurrentIndex(tab_index)

            # Trocar paineis para a nova sessao
            self._switch_session_panels(session.session_id)
        finally:
            self._creating_session = False

    def _find_in_editor(self):
        """Opens search in the focused block of the current editor."""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            block = widget.editor.get_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "_open_find"):
                block.editor._open_find()

    def _replace_in_editor(self):
        """Opens find+replace in the focused block of the current editor."""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            block = widget.editor.get_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "_open_replace"):
                block.editor._open_replace()

    def _format_current_block(self):
        """Formata o codigo do bloco focado usando ruff (Python) ou sqlparse (SQL)."""
        widget = self._get_current_session_widget()
        if not widget or not widget.editor:
            return

        block = widget.editor.get_focused_block()
        if not block or not hasattr(block, "editor"):
            return

        code = block.editor.get_text()
        if not code.strip():
            return

        lang = block.editor.get_language()

        from src.services.code_formatter_service import format_code
        formatted, error = format_code(code, lang)

        if error:
            self.action_label.setText(S.status.formatting_error.format(error=error))
            self.statusBar().showMessage(S.status.formatting_error.format(error=error), 5000)
            return

        if formatted != code:
            # Preserve cursor position (only for QScintilla which has _sci)
            if hasattr(block.editor, "_sci"):
                sci = block.editor._sci
                line, col = sci.getCursorPosition()
                block.editor.set_text(formatted)
                # Restaurar cursor (limitar a linhas existentes)
                max_line = sci.lines() - 1
                sci.setCursorPosition(min(line, max_line), col)
            else:
                # Monaco: just set text (cursor handled by editor)
                block.editor.set_text(formatted)
            self.action_label.setText(S.status.code_formatted.format(lang=lang.upper()))
        else:
            self.action_label.setText(S.status.code_already_formatted.format(lang=lang.upper()))

    def _force_autocomplete(self):
        """Force trigger autocomplete in current block (Ctrl+. shortcut)."""
        widget = self._get_current_session_widget()
        if not widget or not widget.editor:
            return
        
        from src.editors.block_editor import BlockEditor
        
        if isinstance(widget.editor, BlockEditor):
            widget.editor.force_autocomplete_focused_block()
            logging.info("[MAIN] Force autocomplete triggered via Ctrl+.")

    def _add_block_to_current_session(self):
        """Adds a new code block in the current session"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            widget.editor.add_block()

    def _new_session(self):
        """Creates a new session, inheriting the connection from the current tab (if any)"""
        # Guard to prevent duplicate creation
        if hasattr(self, "_creating_session") and self._creating_session:
            return
        self._creating_session = True

        try:
            # Capture active session connection BEFORE creating new one
            previous_connection = None
            previous_color = None
            current_widget = self._get_current_session_widget()
            if current_widget and hasattr(current_widget, "session"):
                previous_connection = current_widget.session.connection_name
                if previous_connection:
                    config = self.connection_manager.get_connection_config(previous_connection)
                    if config:
                        previous_color = config.get("color", "#007ACC") or "#007ACC"

            # If in empty state, remove the placeholder
            self._hide_empty_state()

            session = self.session_manager.create_session()
            widget = self._create_session_widget(session)

            # Update window title immediately (context may have changed)
            self._update_window_title()

            # Defer connection to background with delay to ensure UI renders first
            if previous_connection:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(150, lambda: self._connect_session_background(
                    widget, session, previous_connection, previous_color
                ))
        finally:
            self._creating_session = False
            # Sync global file context from the now-active widget
            # (the guard skipped _on_session_tab_changed during creation)
            self._sync_file_context_from_widget()

    def _connect_session_background(self, widget, session, connection_name, color):
        """Connect session in a true background thread to avoid UI freeze."""
        from PyQt6.QtCore import QThread, pyqtSignal, QObject

        class ConnectionWorker(QObject):
            finished = pyqtSignal(bool)

            def __init__(self, session, connection_name):
                super().__init__()
                self._session = session
                self._connection_name = connection_name

            def run(self):
                try:
                    result = self._session.connect(self._connection_name)
                    self.finished.emit(result)
                except Exception as e:
                    logger.warning(f"Background connection failed: {e}")
                    self.finished.emit(False)

        def on_connected(success):
            if success and color:
                idx = self.session_tabs.indexOf(widget)
                if idx >= 0:
                    self.session_tabs.set_tab_connection_color(idx, color)
            # Cleanup thread
            thread.quit()
            thread.wait()
            thread.deleteLater()
            worker.deleteLater()

        # Create and start background thread
        thread = QThread()
        worker = ConnectionWorker(session, connection_name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_connected)
        thread.start()

        # Store reference to prevent garbage collection
        if not hasattr(self, "_connection_threads"):
            self._connection_threads = []
        self._connection_threads.append((thread, worker))

    def _handle_empty_state_drop(self, file_paths):
        """Handles file drop on empty state screen"""
        import os

        data_files = []
        code_files = []

        for file_path in file_paths:
            ext = os.path.splitext(file_path.lower())[1]
            if ext in (".csv", ".json", ".xlsx", ".xls"):
                data_files.append(file_path)
            elif ext in (".sql", ".py", ".dpw"):
                code_files.append(file_path)

        # Abrir arquivos de codigo/workspace normalmente
        for file_path in code_files:
            if file_path.lower().endswith(".dpw"):
                self._open_workspace(file_path)
            else:
                self._open_code_file(file_path)

        # Abrir arquivos de dados com dialogo de importacao
        if data_files:
            self._new_session()
            current_index = self.session_tabs.currentIndex()
            widget = self.session_tabs.widget(current_index)

            if widget and hasattr(widget, "editor"):
                for file_path in data_files:
                    # Usar o handler do SessionWidget (que abre o dialogo)
                    widget._on_file_dropped(file_path)

    def _handle_empty_state_connection_drop(self, mime_data):
        """Handle connection/database drop on empty state - creates new session with SQL block."""
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

        # Connect session using _quick_connect (creates tab, connects, loads schema,
        # updates Object Explorer, sets tab color)
        if conn_name:
            self._quick_connect(conn_name)
        else:
            self._new_session()

        # Get the widget that was just created
        widget = self._get_current_session_widget()
        if not widget or not hasattr(widget, "editor"):
            return

        # Get the first block (created by _quick_connect/_new_session)
        editor = widget.editor
        if not editor._blocks:
            return

        block = editor._blocks[0]
        block.set_language("sql")

        if conn_name:
            block.set_connection_name(conn_name, db_type=db_type or None, color=color or None)

        if db_name:
            block.set_database_name(db_name)

        block.editor.setFocus()

    def _show_empty_state(self):
        """Shows empty state when there are no sessions, hiding panels"""
        if hasattr(self, "_empty_state_widget") and self._empty_state_widget:
            return  # Ja esta mostrando

        # Esconder paineis inferiores (sem sessao, nao faz sentido mostralos)
        if hasattr(self, "results_dock"):
            self.results_dock.hide()
        if hasattr(self, "output_dock"):
            self.output_dock.hide()
        if hasattr(self, "variables_dock"):
            self.variables_dock.hide()

        # Criar widget de estado vazio com suporte a drag-and-drop
        from PyQt6.QtWidgets import QLabel, QPushButton
        from PyQt6.QtGui import QDragEnterEvent, QDropEvent

        main_window_ref = self

        class DropEmptyStateWidget(QWidget):
            """Empty state widget with drag-and-drop file and connection support"""

            def __init__(self, parent=None):
                super().__init__(parent)
                self.setAcceptDrops(True)

            def dragEnterEvent(self, event: QDragEnterEvent):
                mime_data = event.mimeData()
                # Accept connection or database drag
                if mime_data.hasFormat("application/x-connection-name") or mime_data.hasFormat(
                    "application/x-database-name"
                ):
                    event.acceptProposedAction()
                    return
                if mime_data.hasUrls():
                    for url in mime_data.urls():
                        file_path = url.toLocalFile()
                        if file_path.lower().endswith((".csv", ".json", ".xlsx", ".xls", ".sql", ".py", ".ipynb", ".dpw")):
                            event.acceptProposedAction()
                            return

            def dragMoveEvent(self, event):
                event.acceptProposedAction()

            def dropEvent(self, event: QDropEvent):
                mime_data = event.mimeData()
                # Handle connection or database drop
                if mime_data.hasFormat("application/x-connection-name") or mime_data.hasFormat(
                    "application/x-database-name"
                ):
                    main_window_ref._handle_empty_state_connection_drop(mime_data)
                    event.acceptProposedAction()
                    return
                if mime_data.hasUrls():
                    file_paths = []
                    for url in mime_data.urls():
                        file_path = url.toLocalFile()
                        if file_path.lower().endswith((".csv", ".json", ".xlsx", ".xls", ".sql", ".py", ".ipynb", ".dpw")):
                            file_paths.append(file_path)
                    if file_paths:
                        main_window_ref._handle_empty_state_drop(file_paths)
                        event.acceptProposedAction()

        self._empty_state_widget = DropEmptyStateWidget()
        layout = QVBoxLayout(self._empty_state_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icone grande
        icon_label = QLabel()
        if hasattr(qta, "icon"):
            icon_label.setPixmap(qta.icon("mdi.note-text", color="#64b5f6").pixmap(96, 96))
        icon_label.setStyleSheet("font-size: 96px; background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Texto principal
        title_label = QLabel(S.empty_state.title)
        title_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #cccccc;
            margin-top: 20px;
            background: transparent;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Subtitulo com dica de drag-and-drop
        subtitle_label = QLabel(S.empty_state.subtitle)
        subtitle_label.setStyleSheet("""
            font-size: 14px;
            color: #888888;
            margin-top: 10px;
            background: transparent;
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        # Botao iniciar
        colors = get_colors()
        start_button = QPushButton(f"  {S.empty_state.start_button}  ")
        start_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                padding: 12px 40px;
                font-size: 16px;
                font-weight: bold;
                border-radius: 8px;
                margin-top: 30px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
        """)
        start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        start_button.clicked.connect(self._new_session)
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Adicionar como "aba" invisivel ou substituir conteudo
        self._empty_state_widget.setStyleSheet("background-color: #1e1e1e;")

        # Adicionar aba do empty state
        index = self.session_tabs.addTab(self._empty_state_widget, "")

        # Esconder o tab do estado vazio
        self.session_tabs.tabBar().setTabVisible(index, False)
        self.session_tabs.setCurrentIndex(index)

    def _hide_empty_state(self):
        """Removes empty state and restores panels"""
        if hasattr(self, "_empty_state_widget") and self._empty_state_widget:
            index = self.session_tabs.indexOf(self._empty_state_widget)
            if index >= 0:
                self.session_tabs.removeTab(index)
            self._empty_state_widget = None

        # Restaurar paineis inferiores ao sair do estado vazio
        if hasattr(self, "results_dock"):
            self.results_dock.show()
        if hasattr(self, "output_dock"):
            self.output_dock.show()
        if hasattr(self, "variables_dock"):
            self.variables_dock.show()

    def _create_session_widget(self, session):
        """Creates widget for a session and adds it to a tab"""
        widget = SessionWidget(session, theme_manager=self.theme_manager)
        
        # Pass Copilot client to BlockEditor for inline completions (Monaco)
        if hasattr(self, "_copilot_client") and self._copilot_client:
            widget.editor.set_copilot_client(self._copilot_client)

        # Pass LSP client if available
        if hasattr(self, "_lsp_client") and self._lsp_client:
            widget.editor.set_lsp_client(self._lsp_client)

        # Criar paineis por sessao (Results, Output, Variables)
        self._create_session_panels(session.session_id)

        # Definir file_path no widget se disponivel na sessao
        if hasattr(session, "file_path") and session.file_path:
            widget.file_path = session.file_path
            widget._original_file_type = getattr(session, "original_file_type", None)
        else:
            widget.file_path = None
            widget._original_file_type = None

        # Inicializar hash de conteudo para rastreamento de modificacoes
        widget._content_hash = self._compute_widget_content_hash(widget)
        widget._is_modified = False

        # Connect signals do widget
        widget.status_changed.connect(lambda msg: self._on_session_status_changed(session, msg))
        widget.connection_changed.connect(
            lambda conn_name, db: self._on_session_connection_changed(session, conn_name, db)
        )
        widget.block_connection_changed.connect(
            lambda block, conn_name: self._on_block_connection_changed(block, conn_name)
        )
        widget.connection_drop_requested.connect(
            lambda conn_name: self._quick_connect(conn_name)
        )
        widget.block_database_changed.connect(
            lambda block, db_name: self._on_block_database_changed(block, db_name)
        )
        widget.execution_started.connect(
            lambda w=widget: self._on_execution_started(w)
        )
        widget.execution_finished.connect(
            lambda title, msg, success, w=widget: self._on_execution_finished_notification(
                title, msg, success, w
            )
        )
        widget.execution_finished.connect(
            lambda title, msg, success, w=widget: self._on_execution_finished_cleanup(w)
        )
        widget.execution_cancelled.connect(
            lambda w=widget: self._on_execution_cancelled(w)
        )

        # Per-tab periodic timer: update tab icon when periodic starts/stops
        widget.periodic_changed.connect(
            lambda active, w=widget: self._on_periodic_changed(w, active)
        )

        # Completion logging (for Copilot output panel)
        widget.completion_log.connect(self._on_completion_log)
        
        # Cursor position change (for statusbar)
        widget.cursor_changed.connect(self._on_cursor_position_changed)

        # Block focus change (for Object Explorer connection tracking)
        widget.block_focused.connect(
            lambda block, w=widget: self._on_block_focused(block, w)
        )

        # Conectar sinal de modificacao do editor para rastreamento por hash
        widget.editor.content_changed.connect(lambda w=widget: self._on_editor_modified(w))

        # Atualizar autocomplete quando namespace muda (apos SQL ou Python via SessionWidget)
        session.variables_changed.connect(
            lambda ns: self._push_python_namespace(ns)
        )

        # Guardar referencia
        self._session_widgets[session.session_id] = widget

        # Adicionar aba usando metodo do SessionTabs (ja lida com botao +)
        index = self.session_tabs.add_session(widget, session.title)

        # During restoration, apply tab color based on session connection
        if hasattr(session, "_connection_name") and session._connection_name:
            config = self.connection_manager.get_connection_config(session._connection_name)
            if config:
                color = config.get("color", "#007ACC") or "#007ACC"
                self.session_tabs.set_tab_connection_color(index, color)

        # Trocar paineis para a nova sessao (garante que paineis vazios aparecam)
        self._switch_session_panels(session.session_id)

        # If session already has an active connection (e.g., after restore), load schema
        if session.is_connected and session.connector and session.connection_name:
            QTimer.singleShot(100, lambda: self._load_schema_with_loading(
                session.connector, session.connection_name
            ))

        # Focar automaticamente no primeiro bloco (com delay para garantir renderizacao)
        if widget.editor and hasattr(widget.editor, "focus_first_block"):
            QTimer.singleShot(50, widget.editor.focus_first_block)

        return widget

    def _on_session_renamed(self, index: int, new_name: str):
        """Callback when session is renamed by SessionTabs component"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return

        widget.session.title = new_name.strip()
        self._save_sessions()

    def _ask_save_before_close(self) -> str:
        """Ask user whether to save, discard, or cancel when closing unsaved tab.
        
        Returns:
            'save': User wants to save first
            'discard': User wants to close without saving
            'cancel': User wants to cancel and keep tab open
        """
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(S.dialogs.close_tab_unsaved_title)
        msg_box.setText(S.dialogs.close_tab_unsaved_msg)
        
        save_btn = msg_box.addButton(S.dialogs.save_btn, QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton(S.dialogs.dont_save_btn, QMessageBox.ButtonRole.DestructiveRole)
        msg_box.addButton(QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(save_btn)
        
        msg_box.exec()
        clicked = msg_box.clickedButton()
        clicked_role = msg_box.buttonRole(clicked) if clicked else None
        
        if clicked_role == QMessageBox.ButtonRole.RejectRole:
            return "cancel"
        elif clicked_role == QMessageBox.ButtonRole.AcceptRole:
            return "save"
        else:
            return "discard"

    def _close_session_tab(self, index: int):
        """Closes session tab"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return

        # Check if tab has unsaved changes - ask user what to do
        if getattr(widget, "_is_modified", False):
            action = self._ask_save_before_close()
            if action == "cancel":
                return  # User clicked Cancel - don't close
            elif action == "save":
                # Save the file before closing
                self._save_file()

        # Check if execution is running - ask user to confirm cancellation
        if getattr(widget, "_is_executing", False):
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                "Cancel Execution?",
                "A script is running in this tab. Do you want to cancel it and close the tab?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            # User confirmed - cancel execution first
            widget._on_cancel_execution()

        # Guard para evitar criar sessao ao fechar
        self._closing_session = True

        try:
            # Se a aba fechada era a que fornecia o _original_file_path, limpar
            closed_file_path = getattr(widget, "file_path", None)
            if closed_file_path and closed_file_path == self._original_file_path:
                self._original_file_path = None
                self._original_file_type = None

            # Cleanup e remover
            session_id = widget.session.session_id
            widget.cleanup()
            self.session_manager.close_session(session_id)

            # Remover paineis da sessao dos stacks
            self._remove_session_panels(session_id)

            # Remover do dicionario apenas se existir
            if session_id in self._session_widgets:
                del self._session_widgets[session_id]

            self.session_tabs.removeTab(index)
            self._save_sessions()

            # Verificar se nao ha mais sessoes REAIS (ignorar aba do botao +)
            session_count = sum(
                1 for i in range(self.session_tabs.count()) if isinstance(self.session_tabs.widget(i), SessionWidget)
            )
            if session_count == 0:
                self._original_file_path = None
                self._original_file_type = None
                self._show_empty_state()
                # Limpar OE quando nao ha sessoes
                if hasattr(self, "_object_explorer_stack"):
                    for i in range(self._object_explorer_stack.count()):
                        w = self._object_explorer_stack.widget(i)
                        if hasattr(w, "clear"):
                            w.clear()
                    self.object_explorer_dock.hide()

            # Atualizar titulo e statusbar para refletir a aba ativa apos fechar
            self._update_window_title()
            
            # Atualizar OE para a nova aba ativa apos fechar
            new_widget = self._get_current_session_widget()
            if new_widget and hasattr(new_widget, "session"):
                new_sid = new_widget.session.session_id
                self._switch_session_panels(new_sid)
        finally:
            self._closing_session = False
            # Sync global file context from the now-active widget
            # (the guard skipped _on_session_tab_changed during close)
            self._sync_file_context_from_widget()

    def _on_session_tab_changed(self, index: int):
        """Event when session tab changes"""
        # Ignore during operations that alter tabs
        if hasattr(self, "_restoring_sessions") and self._restoring_sessions:
            return
        if hasattr(self, "_creating_session") and self._creating_session:
            return
        if hasattr(self, "_closing_session") and self._closing_session:
            return

        # If clicking + creates new session
        if self.session_tabs.tabText(index).strip() == "+":
            self._new_session()
            return

        widget = self.session_tabs.widget(index)
        if isinstance(widget, SessionWidget):
            self.session_manager.focus_session(widget.session.session_id)
            # Trocar paineis para a sessao ativa
            self._switch_session_panels(widget.session.session_id)

            # Atualizar OE para mostrar a conexao efetiva desta aba
            self._update_oe_for_session(widget)

            # Switch Copilot chat context to this tab
            if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
                tab_name = self.session_tabs.tabText(index).strip()
                self._copilot_chat_panel.switch_tab_context(
                    widget.session.session_id, tab_name
                )

            # Restaurar contexto de arquivo da aba selecionada
            if hasattr(widget, "file_path") and widget.file_path:
                self._original_file_path = widget.file_path
                self._original_file_type = getattr(widget, "_original_file_type", None)
            else:
                self._original_file_path = None
                self._original_file_type = None

            # Update toolbar timer button to reflect this tab's periodic state
            if hasattr(widget, "is_periodic_active") and hasattr(self, "main_toolbar"):
                self.main_toolbar.set_timer_running(
                    widget.is_periodic_active, widget.periodic_interval
                )
                if widget.is_periodic_active:
                    self.main_statusbar.action_label.setText(
                        S.toolbar.run_timer_running.format(seconds=widget.periodic_interval)
                    )
                else:
                    self.main_statusbar.action_label.setText("")

        # Atualizar titulo da janela quando muda de aba
        self._update_window_title()

    def _on_session_focused(self, session):
        """Callback when a session is focused"""
        # Update status bar and connection panel with session info
        if session.is_connected:
            # Update status bar
            self.connection_status_bar.setText(session.connection_name)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: #4ec9b0;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid #3e3e42;
                }
            """)

            # Update active connection panel
            config = self.connection_manager.get_connection_config(session.connection_name)
            if config:
                self.connection_panel.set_active_connection(
                    session.connection_name,
                    host=config.get("host", ""),
                    database=config.get("database", ""),
                    db_type=config.get("db_type", ""),
                )
            else:
                self.connection_panel.set_active_connection(session.connection_name)

            # Highlight connection in list
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == session.connection_name:
                    self.connections_list.setCurrentItem(item)
                    break
        else:
            # Desconectado
            self.connection_status_bar.setText(S.status.disconnected)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: #f48771;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid #3e3e42;
                }
            """)

            # Clear active connection panel
            self.connection_panel.set_disconnected()

        self.action_label.setText(S.status.session_label.format(title=session.title))

        # Update window title when session is focused
        self._update_window_title()

    def _on_session_status_changed(self, session, message: str):
        """Callback when a session status changes"""
        # Only updates if it is the focused session
        if self.session_manager.focused_session == session:
            self.action_label.setText(message)

    def _on_session_connection_changed(self, session, connection_name: str, database: str):
        """
        CENTRALIZED SERVICE: Manages session connection changes

        This method centralizes ALL updates when a session connects/switches database:
        - Updates active connections panel
        - Highlights connection in list
        - Atualiza status bar

        Args:
            session: Session that changed the connection
            connection_name: Connection name
            database: Nome do banco de dados atual
        """
        # Only updates if it is the focused session
        if self.session_manager.focused_session != session:
            return

        # Get connection config
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return

        host = config.get("host", "localhost")
        db_type = config.get("db_type", "")

        # Usar o banco retornado (pode ter mudado via USE)
        current_db = database if database else config.get("database", "")

        # === UPDATE ACTIVE CONNECTIONS PANEL ===
        self.connection_panel.set_active_connection(connection_name, host=host, database=current_db, db_type=db_type)

        # === HIGHLIGHT CONNECTION IN LIST ===
        for i in range(self.connections_list.count()):
            item = self.connections_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == connection_name:
                self.connections_list.setCurrentItem(item)
                break

        # === ATUALIZAR STATUS BAR ===
        self.action_label.setText(S.status.connected_to.format(name=connection_name, db=current_db))

        # === DEFINIR COR DA ABA ===
        color = config.get("color", "#007ACC") or "#007ACC"
        # Find tab index of this session
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if isinstance(widget, SessionWidget) and widget.session == session:
                self.session_tabs.set_tab_connection_color(i, color)
                break

        # === CARREGAR SCHEMA ===
        # This is the central place for schema loading when connection changes.
        # Invalidate cache only if database changed, otherwise load from cache.
        # Only load schema if we have a real connector (not a Mock in tests)
        from src.database.database_connector import DatabaseConnector
        if (session.connector 
            and isinstance(session.connector, DatabaseConnector)
            and session.connector.is_connected()):
            # Update OE tracking - the session's OE should show this connection now
            if not hasattr(self, "_oe_current_connection"):
                self._oe_current_connection = {}
            self._oe_current_connection[session.session_id] = connection_name

            self._load_schema_with_loading(session.connector, connection_name, session_id=session.session_id)

        # === ATUALIZAR TODOS OS BLOCOS (sem conexao customizada) ===
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            for block in current_widget.editor.get_blocks():
                if hasattr(block, "db_panel"):
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn:
                        block._database_name = current_db
                        block.db_panel.set_database(current_db)

    def _get_current_session_widget(self) -> SessionWidget:
        """Returns active tab SessionWidget"""
        widget = self.session_tabs.currentWidget()
        if isinstance(widget, SessionWidget):
            return widget
        return None

    def _get_current_editor(self):
        """Returns the editor (BlockEditor) of the active session"""
        widget = self._get_current_session_widget()
        if widget:
            return widget.editor
        return None

    def _save_sessions(self):
        """Saves all sessions"""
        # Synchronize code from widgets to sessions
        for session_id, widget in self._session_widgets.items():
            widget.sync_to_session()

        # Salvar via SessionManager
        self.session_manager.save_sessions()

        # Also save window geometry in workspace
        window_geometry = {
            "x": self.geometry().x(),
            "y": self.geometry().y(),
            "width": self.geometry().width(),
            "height": self.geometry().height(),
            "maximized": self.isMaximized(),
        }

        dock_visible = self.connections_dock.isVisible() if hasattr(self, "connections_dock") else True

        # Salvar no workspace manager (para geometria)
        # Note: active_connection is now per session, saved with each session
        self.workspace_manager.save_workspace(
            tabs=[],  # No longer used for tabs
            active_tab=0,
            active_connection=None,  # Connection is now per session
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible,
        )

    def _restore_sessions(self):
        """Restores saved sessions - loads incrementally"""
        self._restoring_sessions = True

        # Load sessions from disk
        self.session_manager.load_sessions(self.connection_manager)

        # Salvar workspace para restaurar geometria depois
        workspace = self.workspace_manager.load_workspace()
        self._pending_workspace_restore = workspace

        # Queue of sessions to load incrementally
        self._sessions_to_load = list(self.session_manager.sessions)

        self._restoring_sessions = False

        # Start loading sessions incrementally
        if self._sessions_to_load:
            QTimer.singleShot(50, self._load_next_session)
        else:
            # If there are no sessions, show empty state
            self._show_empty_state()

    def _load_next_session(self):
        """Loads the next session from the queue"""
        if not self._sessions_to_load:
            # Focus on active session
            focused = self.session_manager.focused_session
            if focused:
                index = self.session_manager.get_session_index(focused.session_id)
                if index >= 0:
                    self.session_tabs.setCurrentIndex(index)

                # Update connection indicator (if connection_panel exists)
                if focused.is_connected and hasattr(self, "connection_panel"):
                    # database_name removed - Session only has connection_name
                    self.connection_panel.set_active_connection(
                        focused.connection_name,
                        focused.connection_name,  # usar connection_name no lugar de database_name
                    )
            return

        session = self._sessions_to_load.pop(0)

        # Create widget for session
        self._create_session_widget(session)

        # Processar eventos pendentes da UI
        QApplication.processEvents()

        # Schedule next session
        QTimer.singleShot(10, self._load_next_session)

    def _restore_window_state(self):
        """Restores window geometry, splitter and dock after initialization"""
        if not hasattr(self, "_pending_workspace_restore"):
            return

        workspace = self._pending_workspace_restore

        # Restaurar geometria da janela
        geometry = workspace.get("window_geometry")
        if geometry:
            if geometry.get("maximized", False):
                self.showMaximized()
            else:
                self.setGeometry(
                    geometry.get("x", 100),
                    geometry.get("y", 100),
                    geometry.get("width", 1400),
                    geometry.get("height", 900),
                )

        # Restaurar visibilidade do dock
        dock_visible = workspace.get("dock_visible", True)
        if hasattr(self, "connections_dock"):
            self.connections_dock.setVisible(dock_visible)

        # Restore active connection (after UI is ready)
        if workspace.get("active_connection"):
            try:
                self._reconnect_saved_connection(workspace["active_connection"])
            except Exception as e:
                logger.warning(f"Could not restore connection: {e}")

        # Clear reference
        del self._pending_workspace_restore

    def _reconnect_saved_connection(self, connection_name: str):
        """Reconnects to saved connection automatically"""
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return

        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            # Tentar conectar sem senha primeiro (pode ter salvo)
            password = config.get("password", "")

        try:
            connector = self.connection_manager.create_connection(
                connection_name,
                config["db_type"],
                config["host"],
                config["port"],
                config["database"],
                config.get("username", ""),
                password,
                use_windows_auth=config.get("use_windows_auth", False),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
            )

            self.connection_manager.mark_connection_used(connection_name)
            self._update_connection_status()
            self.action_label.setText(S.status.reconnected_to.format(name=connection_name))

        except Exception as e:
            logger.error(f"Error reconnecting {connection_name}: {e}")
            # Does not fail silently - shows in statusbar
            self.action_label.setText(S.status.reconnection_failed.format(name=connection_name))

