"""
SessionsMixin - Session lifecycle, tab events, persistence, empty state.
"""

from __future__ import annotations

import logging
import weakref
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject, QSettings
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QApplication,
)
from PyQt6.QtGui import QFont, QColor

from src.design_system.app_dialogs import confirm_yes_no
from src.database.database_connector import get_connector_database_context
from src.ui.components.session_widget import SessionWidget
from src.design_system.frameless_dialog import widget_is_valid
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
                    if not confirm_yes_no(
                        self,
                        S.dialogs.close_session_title,
                        S.dialogs.close_session_msg,
                    ):
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

            tab_index = self.session_tabs.insertTab(self.session_tabs.count(), new_widget, new_name)

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
            self._sync_chat_tab_context()

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

    def _show_selected_entity_info(self):
        """Open the entity information dialog for the selected SQL relation."""
        widget = self._get_current_session_widget()
        if not widget or not widget.editor:
            return

        block = widget.editor.get_focused_block()
        if not block:
            self.statusBar().showMessage(S.entity_info.no_active_sql_block, 4000)
            return

        if getattr(block, "get_language", lambda: "")() != "sql":
            self.statusBar().showMessage(S.entity_info.no_active_sql_block, 4000)
            return

        selected_text = (block.get_selected_text() or "").strip().strip(";").strip()
        if not selected_text:
            self.statusBar().showMessage(S.entity_info.no_selection, 4000)
            return

        session = getattr(widget, "session", None)
        block_connection_name = block.get_connection_name() if hasattr(block, "get_connection_name") else ""
        connection_name = block_connection_name or getattr(session, "connection_name", "")
        if not connection_name:
            self.statusBar().showMessage(S.entity_info.no_connection, 4000)
            return

        database_override = block.get_database_name() if hasattr(block, "get_database_name") else ""
        session_connector = getattr(session, "connector", None)
        existing_connector = None
        if block_connection_name:
            candidate = self.connection_manager.get_connection(connection_name)
            if candidate and self._connector_is_connected(candidate):
                existing_connector = candidate
        elif session_connector and self._connector_is_connected(session_connector):
            existing_connector = session_connector

        connection_config = self.connection_manager.get_connection_config(connection_name)
        connector = None if connection_config else existing_connector

        if connector is None and connection_config is None and existing_connector is None:
            self.statusBar().showMessage(S.entity_info.no_connection, 4000)
            return

        from src.services.entity_metadata_service import EntityMetadataWorker
        from src.ui.dialogs.entity_info_dialog import EntityInfoDialog

        dialog = EntityInfoDialog(selected_text, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        thread = QThread()
        worker = EntityMetadataWorker(
            entity_name=selected_text,
            connector=connector,
            fallback_connector=existing_connector if connection_config else None,
            connection_config=connection_config,
            database_override=database_override,
        )
        worker.moveToThread(thread)

        def on_loaded(metadata: dict, dlg=dialog, active_connection=connection_name):
            try:
                dlg.populate(metadata, active_connection)
            except RuntimeError:
                pass

        def on_error(error_text: str, dlg=dialog):
            try:
                dlg.set_error(S.entity_info.load_error.format(error=error_text))
            except RuntimeError:
                pass
            self.statusBar().showMessage(S.entity_info.load_error_status.format(error=error_text), 6000)

        thread.started.connect(worker.run)
        worker.loaded.connect(on_loaded)
        worker.error.connect(on_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda current_thread=thread: self._cleanup_entity_info_thread(current_thread))

        if not hasattr(self, "_entity_info_threads"):
            self._entity_info_threads = []
        self._entity_info_threads.append((thread, worker))
        thread.start()

    def _force_autocomplete(self):
        """Force trigger autocomplete in current block (Ctrl+. shortcut)."""
        widget = self._get_current_session_widget()
        if not widget or not widget.editor:
            return
        
        from src.editors.block_editor import BlockEditor
        
        if isinstance(widget.editor, BlockEditor):
            widget.editor.force_autocomplete_focused_block()
            logging.info("[MAIN] Force autocomplete triggered via Ctrl+.")

    def _cleanup_entity_info_thread(self, thread):
        if not hasattr(self, "_entity_info_threads"):
            return
        self._entity_info_threads = [
            (active_thread, worker)
            for active_thread, worker in self._entity_info_threads
            if active_thread is not thread
        ]

    def _add_block_to_current_session(self):
        """Adds a new code block in the current session"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            widget.editor.add_block()

    def _new_session(self, *, inherit_connection: bool = True):
        """Creates a new session, inheriting the connection from the current tab (if any).

        Args:
            inherit_connection: when False, the new tab is created without the
                deferred auto-connect to the previous tab's connection (used by
                flows that immediately connect to an explicit target, e.g.
                Ctrl+double-click on a connection).
        """
        # Guard to prevent duplicate creation
        if hasattr(self, "_creating_session") and self._creating_session:
            return
        self._creating_session = True

        try:
            # Capture active session connection BEFORE creating new one
            previous_connection = None
            previous_color = None
            previous_database_context = ""
            current_widget = self._get_current_session_widget() if inherit_connection else None
            if current_widget and hasattr(current_widget, "session"):
                previous_connection = current_widget.session.connection_name
                previous_database_context = getattr(current_widget.session, "database_context", "") or ""
                if not previous_database_context:
                    previous_database_context = get_connector_database_context(
                        getattr(current_widget.session, "connector", None)
                    )
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
                    widget, session, previous_connection, previous_color, previous_database_context
                ))
        finally:
            self._creating_session = False
            # Sync global file context from the now-active widget
            # (the guard skipped _on_session_tab_changed during creation)
            self._sync_file_context_from_widget()
            self._sync_chat_tab_context()

    def _is_widget_connecting(self, widget) -> bool:
        """True if the tab is connecting (widget thread or main-window background thread)."""
        if not widget_is_valid(widget):
            return False
        try:
            if widget.is_connecting():
                return True
        except RuntimeError:
            return False
        session = getattr(widget, "session", None)
        session_id = getattr(session, "session_id", None) if session else None
        for item in getattr(self, "_connection_threads", []):
            thread = item[0]
            bound = item[2] if len(item) >= 3 else None
            if bound is widget and thread.isRunning():
                return True
            if session_id and len(item) >= 2:
                worker = item[1]
                worker_session = None
                if hasattr(worker, "_session_ref"):
                    worker_session = worker._session_ref()
                else:
                    worker_session = getattr(worker, "_session", None)
                if (
                    worker_session is not None
                    and getattr(worker_session, "session_id", None) == session_id
                    and thread.isRunning()
                ):
                    return True
        return False

    def _ensure_connection_thread_guard(self) -> None:
        if getattr(self, "_connection_thread_guard", None) is None:
            self._connection_thread_guard = QObject(self)

    def _adopt_background_thread(self, thread, worker=None) -> bool:
        """Keep any background QThread alive under MainWindow until it finishes."""
        return self._adopt_connection_thread(thread, worker)

    def _orphan_background_thread(self, thread, worker=None) -> None:
        """Detach worker from UI; thread stays adopted until it stops."""
        self._orphan_connection_thread(thread, worker)

    def _adopt_connection_thread(self, thread, worker) -> bool:
        """Keep QThread alive under MainWindow until it finishes (prevents destroy-while-running)."""
        if thread is None:
            return False
        self._ensure_connection_thread_guard()
        adopted = getattr(self, "_adopted_connection_threads", None)
        if adopted is None:
            self._adopted_connection_threads = {}
        tid = id(thread)
        if tid in self._adopted_connection_threads:
            if worker is not None:
                self._adopted_connection_threads[tid] = (thread, worker)
            return False
        self._adopted_connection_threads[tid] = (thread, worker)
        try:
            thread.setParent(self._connection_thread_guard)
        except RuntimeError:
            pass

        def _on_finished(finished_thread=thread) -> None:
            self._release_adopted_connection_thread(finished_thread)

        try:
            thread.finished.connect(
                _on_finished, Qt.ConnectionType.SingleShotConnection
            )
        except (TypeError, RuntimeError):
            pass
        return True

    def _release_adopted_connection_thread(self, thread) -> None:
        adopted = getattr(self, "_adopted_connection_threads", None)
        if not adopted:
            return
        entry = adopted.pop(id(thread), None)
        if entry is None:
            return
        thread_obj, worker = entry
        if worker is not None:
            try:
                worker.deleteLater()
            except RuntimeError:
                pass
        if thread_obj is not None:
            try:
                if not thread_obj.isRunning():
                    thread_obj.deleteLater()
            except RuntimeError:
                pass

    def _register_session_connection_thread(self, widget, thread, worker) -> None:
        """Keep widget connection threads visible to MainWindow until fully stopped."""
        self._adopt_connection_thread(thread, worker)
        if not hasattr(self, "_connection_threads"):
            self._connection_threads = []
        self._connection_threads = [
            item
            for item in self._connection_threads
            if item[0] is not thread
        ]
        self._connection_threads.append((thread, worker, widget))

    def _unregister_session_connection_thread(self, thread) -> None:
        if not hasattr(self, "_connection_threads"):
            return
        self._connection_threads = [
            item for item in self._connection_threads if item[0] is not thread
        ]

    def _stop_connection_thread_item(
        self, thread, worker, wait_ms: int, *, force: bool = False
    ) -> None:
        """Quit and wait on a background connection thread; terminate if needed."""
        from src.utils.qt_threading import stop_qthread

        stop_qthread(thread, worker, wait_ms=wait_ms, force_terminate=force)

    def _detach_widget_connections(self, widget) -> None:
        """Cancel connection work for a closing tab without blocking the UI."""
        widget._is_closing = True
        if hasattr(widget, "detach_connection_thread"):
            widget.detach_connection_thread()
        if not hasattr(self, "_connection_threads"):
            return
        orphan = []
        kept = []
        session = getattr(widget, "session", None)
        session_id = getattr(session, "session_id", None) if session else None
        for item in list(self._connection_threads):
            thread, worker = item[0], item[1]
            bound = item[2] if len(item) >= 3 else None
            worker_session = None
            if hasattr(worker, "_session_ref"):
                worker_session = worker._session_ref()
            else:
                worker_session = getattr(worker, "_session", None)
            same_tab = bound is widget
            same_session = (
                session_id
                and worker_session is not None
                and getattr(worker_session, "session_id", None) == session_id
            )
            if same_tab or same_session:
                if hasattr(worker, "cancel"):
                    try:
                        worker.cancel()
                    except RuntimeError:
                        pass
                orphan.append((thread, worker))
                continue
            kept.append(item)
        self._connection_threads = kept
        for thread, worker in orphan:
            self._orphan_connection_thread(thread, worker)

    def _orphan_connection_thread(self, thread, worker) -> None:
        """Detach from tab UI; thread stays adopted on MainWindow until it stops."""
        if thread is None:
            return
        self._adopt_connection_thread(thread, worker)
        QTimer.singleShot(
            0, lambda t=thread, w=worker: self._kick_connection_thread_stop(t, w)
        )

    def _kick_connection_thread_stop(self, thread, worker) -> None:
        from src.utils.qt_threading import kick_qthread_stop

        kick_qthread_stop(thread, worker)

    def _stop_orphan_connection(self, thread, worker) -> None:
        """Blocking stop — app shutdown only."""
        from src.utils.qt_threading import stop_qthread

        stop_qthread(thread, worker, wait_ms=3000, force_terminate=True)
        self._release_adopted_connection_thread(thread)

    def _abort_widget_background_connection(
        self, widget, wait_ms: int = 3000, *, force: bool = False
    ) -> None:
        """Blocking abort — used on app exit only."""
        self._detach_widget_connections(widget)
        for item in list(getattr(self, "_connection_threads", [])):
            self._stop_connection_thread_item(item[0], item[1], wait_ms, force=force)
        if hasattr(self, "_connection_threads"):
            self._connection_threads.clear()
        for _tid, (thread, worker) in list(
            getattr(self, "_adopted_connection_threads", {}).items()
        ):
            self._stop_orphan_connection(thread, worker)

    def _abort_all_background_connections(self, wait_ms: int = 3000) -> None:
        """Cancel every in-flight background connection before app shutdown."""
        for widget in list(getattr(self, "_session_widgets", {}).values()):
            if hasattr(widget, "_abort_connection_thread"):
                widget._abort_connection_thread(wait_ms=wait_ms)
        for item in list(getattr(self, "_connection_threads", [])):
            self._stop_connection_thread_item(item[0], item[1], wait_ms, force=True)
        if hasattr(self, "_connection_threads"):
            self._connection_threads.clear()
        for _tid, (thread, worker) in list(
            getattr(self, "_adopted_connection_threads", {}).items()
        ):
            self._stop_orphan_connection(thread, worker)

    def _connect_session_background(self, widget, session, connection_name, color, database_context=""):
        """Connect session in a true background thread to avoid UI freeze."""
        from PyQt6.QtCore import QThread, pyqtSignal, QObject

        if getattr(self, "_is_closing", False) or not widget_is_valid(widget):
            return

        class ConnectionWorker(QObject):
            finished = pyqtSignal(bool)

            def __init__(self, session, connection_name, database_context, widget=None):
                super().__init__()
                self._session_ref = weakref.ref(session)
                self._widget_ref = weakref.ref(widget) if widget is not None else None
                self._connection_name = connection_name
                self._database_context = database_context
                self._cancelled = False

            def cancel(self):
                self._cancelled = True

            def _ignore_result(self) -> bool:
                if self._cancelled:
                    return True
                if self._widget_ref is None:
                    return False
                w = self._widget_ref()
                if w is None:
                    return True
                try:
                    return bool(getattr(w, "_is_closing", False))
                except RuntimeError:
                    return True

            def run(self):
                if self._cancelled:
                    self.finished.emit(False)
                    return
                session = self._session_ref()
                if session is None:
                    self.finished.emit(False)
                    return
                try:
                    if self._database_context:
                        session.database_context = self._database_context
                    result = session.connect(self._connection_name)
                    if self._ignore_result():
                        self.finished.emit(False)
                        return
                    self.finished.emit(result)
                except Exception as e:
                    if not self._ignore_result():
                        logger.warning(f"Background connection failed: {e}")
                    self.finished.emit(False)

        widget_ref = weakref.ref(widget)

        def on_connected(success):
            if getattr(self, "_is_closing", False):
                return
            w = widget_ref()
            if not widget_is_valid(w):
                return
            if getattr(w, "_is_closing", False):
                return
            if not success:
                return
            if success and color:
                idx = self.session_tabs.indexOf(w)
                if idx >= 0:
                    self.session_tabs.set_tab_connection_color(idx, color)

        # Create and start background thread
        thread = QThread()
        thread.setObjectName("SessionBackgroundConnection")
        worker = ConnectionWorker(session, connection_name, database_context, widget)
        self._adopt_connection_thread(thread, worker)

        def cleanup_connection_thread(active_thread=thread, active_worker=worker):
            if not hasattr(self, "_connection_threads"):
                return
            self._connection_threads = [
                stored
                for stored in self._connection_threads
                if stored[0] is not active_thread
            ]
            try:
                active_worker.deleteLater()
            except RuntimeError:
                pass

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_connected)
        worker.finished.connect(thread.quit)
        thread.finished.connect(cleanup_connection_thread)
        thread.start()

        # Store reference to prevent garbage collection
        if not hasattr(self, "_connection_threads"):
            self._connection_threads = []
        self._connection_threads.append((thread, worker, widget))

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
        # Esconder paineis inferiores (sem sessao, nao faz sentido mostralos)
        if hasattr(self, "results_dock"):
            self.results_dock.hide()
        if hasattr(self, "output_dock"):
            self.output_dock.hide()
        if hasattr(self, "variables_dock"):
            self.variables_dock.hide()

        if hasattr(self, "_empty_state_widget") and self._empty_state_widget:
            return  # Ja esta mostrando

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

        from src.design_system.button import PrimaryButton
        from src.design_system.font_manager import get_application_font
        from src.design_system.tokens import TYPOGRAPHY

        colors = get_colors()
        icon_label = QLabel()
        if hasattr(qta, "icon"):
            icon_label.setPixmap(
                qta.icon("mdi.file-document-outline", color=colors.interactive_primary).pixmap(72, 72)
            )
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel(S.empty_state.title)
        from PyQt6.QtGui import QFont

        title_label.setFont(get_application_font(20, QFont.Weight.DemiBold))
        title_label.setStyleSheet(
            f"color: {colors.text_primary}; margin-top: 16px; background: transparent;"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        subtitle_label = QLabel(S.empty_state.subtitle)
        subtitle_label.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: {TYPOGRAPHY.text_sm}px;"
            " margin-top: 8px; max-width: 420px; background: transparent;"
        )
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        layout.addSpacing(24)

        start_button = PrimaryButton(S.empty_state.start_button, size="lg")
        if hasattr(qta, "icon"):
            start_button.setIcon(qta.icon("mdi.plus", color="white"))
        start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        start_button.clicked.connect(self._new_session)
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Adicionar como "aba" invisivel ou substituir conteudo
        from src.design_system.tokens import CHROME_BG
        self._empty_state_widget.setStyleSheet(f"background-color: {CHROME_BG};")

        # Adicionar aba do empty state
        index = self.session_tabs.addTab(self._empty_state_widget, "")

        # Esconder o tab do estado vazio
        self.session_tabs.tabBar().setTabVisible(index, False)
        self.session_tabs.tabBar().setVisible(False)
        self.session_tabs.setCurrentIndex(index)
        if hasattr(self.session_tabs, "_sync_new_tab_button"):
            self.session_tabs._sync_new_tab_button()

    def _hide_empty_state(self):
        """Removes empty state and restores panels"""
        if hasattr(self, "_empty_state_widget") and self._empty_state_widget:
            index = self.session_tabs.indexOf(self._empty_state_widget)
            if index >= 0:
                self.session_tabs.removeTab(index)
            self._empty_state_widget = None

        self.session_tabs.tabBar().setVisible(True)
        if hasattr(self.session_tabs, "_sync_new_tab_button"):
            self.session_tabs._sync_new_tab_button()

        # Restaurar paineis inferiores ao sair do estado vazio
        if hasattr(self, "results_dock"):
            self.results_dock.show()
        if hasattr(self, "output_dock"):
            self.output_dock.show()
        if hasattr(self, "variables_dock"):
            self.variables_dock.show()

    def _create_session_widget(self, session):
        """Creates widget for a session and adds it to a tab"""
        if hasattr(self, "_empty_state_widget") and self._empty_state_widget:
            self._hide_empty_state()

        widget = SessionWidget(session, theme_manager=self.theme_manager)
        
        # Pynia inline autocomplete for Monaco editors
        if hasattr(widget.editor, "set_pynia_client"):
            if hasattr(self, "_pynia_agent") and self._pynia_agent:
                widget.editor.set_pynia_client(self._pynia_agent)
            elif hasattr(self, "_copilot_client") and self._copilot_client:
                widget.editor.set_pynia_client(self._copilot_client)

        # Native Copilot LSP completion (preferred over the prompt path).
        lsp_client = getattr(self, "_lsp_client", None)
        if lsp_client and hasattr(widget.editor, "set_lsp_client"):
            widget.editor.set_lsp_client(lsp_client)

        # Criar paineis por sessao (Results, Output, Variables)
        self._create_session_panels(session.session_id)

        # Connect output panel signals (navigate + Copilot resolve)
        panels = self._session_panel_indices.get(session.session_id)
        if panels and panels.get("output"):
            out_panel = panels["output"]
            out_panel.navigate_to_block.connect(
                lambda block_idx, line, col, w=widget: w.editor.focus_block_at_line(block_idx, line, col)
            )
            out_panel.resolve_with_copilot.connect(
                lambda ctx: self._resolve_with_copilot(ctx)
            )

        if panels and panels.get("variables"):
            panels["variables"].bind_session_widget(widget)

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
        widget.editor.content_changed.connect(lambda w=widget: self._schedule_cross_database_schema_sync(w))
        widget.editor.content_changed.connect(lambda: self._schedule_session_autosave())

        # Atualizar autocomplete quando namespace muda (apos SQL ou Python via SessionWidget)
        session.variables_changed.connect(
            lambda ns, w=widget: w.editor.refresh_completion_context()
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

        QTimer.singleShot(0, widget.restore_persisted_variables)

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
        self._schedule_session_autosave()

    def _ask_save_before_close(self) -> str:
        """Ask user whether to save, discard, or cancel when closing unsaved tab."""
        from src.design_system.message_box import ask_save_discard_cancel

        return ask_save_discard_cancel(
            self,
            S.dialogs.close_tab_unsaved_title,
            S.dialogs.close_tab_unsaved_msg,
        )

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

        is_busy = (
            getattr(widget, "is_execution_busy", None)
            and widget.is_execution_busy()
        ) or getattr(widget, "_is_executing", False)
        if is_busy:
            from src.design_system.message_box import ask_yes_no

            if not ask_yes_no(
                self,
                "Cancel Execution?",
                "A script is running in this tab. Do you want to cancel it and close the tab?",
            ):
                return
            widget._on_cancel_execution()

        self._finalize_close_session_tab(index, widget)

    def _finalize_close_session_tab(self, index: int, widget) -> None:
        """Remove session tab immediately; workers finish detached in background."""
        if index < 0 or index >= self.session_tabs.count():
            return
        if self.session_tabs.widget(index) is not widget:
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) is widget:
                    index = i
                    break
            else:
                return

        self._closing_session = True
        try:
            self._detach_widget_connections(widget)
            if hasattr(widget, "_orphan_running_threads"):
                widget._orphan_running_threads()
            closed_file_path = getattr(widget, "file_path", None)
            if closed_file_path and closed_file_path == self._original_file_path:
                self._original_file_path = None
                self._original_file_type = None

            session_id = widget.session.session_id
            if session_id in self._session_widgets:
                del self._session_widgets[session_id]

            self.session_tabs.removeTab(index)

            widget.cleanup()
            self.session_manager.close_session(session_id)
            self._remove_session_panels(session_id)
            widget.deleteLater()
            self._flush_session_autosave()

            session_count = sum(
                1 for i in range(self.session_tabs.count()) if isinstance(self.session_tabs.widget(i), SessionWidget)
            )
            if session_count == 0:
                self._original_file_path = None
                self._original_file_type = None
                self._show_empty_state()
                if hasattr(self, "_object_explorer_stack"):
                    for i in range(self._object_explorer_stack.count()):
                        w = self._object_explorer_stack.widget(i)
                        if hasattr(w, "clear"):
                            w.clear()
                    self.object_explorer_dock.hide()

            self._update_window_title()
            new_widget = self._get_current_session_widget()
            if new_widget and hasattr(new_widget, "session"):
                self._switch_session_panels(new_widget.session.session_id)
        finally:
            self._closing_session = False
            self._sync_file_context_from_widget()
            self._sync_chat_tab_context()

    def _sync_chat_tab_context(self):
        """Point the Pynia chat at the now-active tab.

        Needed where the tab-change signal was suppressed (_creating_session /
        _closing_session guards) — otherwise the chat keeps targeting the
        previous tab and the agent works on the wrong session.
        """
        if not (hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel):
            return
        try:
            index = self.session_tabs.currentIndex()
            widget = self.session_tabs.widget(index) if index >= 0 else None
            if isinstance(widget, SessionWidget):
                self._copilot_chat_panel.switch_tab_context(
                    widget.session.session_id,
                    self.session_tabs.tabText(index).strip(),
                )
        except Exception as e:
            logger.debug(f"Chat tab context sync skipped: {e}")

    def _on_session_tab_changed(self, index: int):
        """Event when session tab changes"""
        # Ignore during operations that alter tabs
        if hasattr(self, "_restoring_sessions") and self._restoring_sessions:
            return
        if hasattr(self, "_creating_session") and self._creating_session:
            return
        if hasattr(self, "_closing_session") and self._closing_session:
            return

        widget = self.session_tabs.widget(index)
        if isinstance(widget, SessionWidget):
            self.session_manager.focus_session(widget.session.session_id)
            # Trocar paineis para a sessao ativa
            self._switch_session_panels(widget.session.session_id)

            if hasattr(widget, "editor") and hasattr(widget.editor, "refresh_completion_context"):
                widget.editor.refresh_completion_context()

            # Atualizar OE para mostrar a conexao efetiva desta aba (deferido)
            QTimer.singleShot(0, lambda w=widget: self._update_oe_for_session(w))

            # Switch Copilot chat context to this tab
            if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
                tab_name = self.session_tabs.tabText(index).strip()
                self._copilot_chat_panel.switch_tab_context(
                    widget.session.session_id, tab_name
                )
                self._copilot_chat_panel.notify_block_focused()

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

    def _resolve_with_copilot(self, context: dict):
        """Send error context to the Copilot chat panel for resolution."""
        if not hasattr(self, "_copilot_chat_panel") or not self._copilot_chat_panel:
            return
        panel = self._copilot_chat_panel
        # Build a prompt from the error context
        parts = []
        block_name = context.get("block_name") or f"Block {(context.get('block_index') or 0) + 1}"
        lang = context.get("log_type", "SQL")
        parts.append(f"I got an error in {block_name} ({lang}):")
        code = context.get("code", "")
        if code:
            parts.append(f"```{lang.lower()}\n{code}\n```")
        err = context.get("error", "")
        if err:
            parts.append(f"Error:\n```\n{err}\n```")
        parts.append("Help me fix it.")
        prompt = "\n\n".join(parts)
        # Set text in input and trigger send
        panel._input.setPlainText(prompt)
        panel._on_send()
        # Show the Copilot chat dock
        if hasattr(self, "copilot_dock"):
            self.show_panel("copilot")

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
            current_db = get_connector_database_context(session.connector) or getattr(session, "database_context", "")
            if config:
                self.connection_panel.set_active_connection(
                    session.connection_name,
                    host=config.get("host", ""),
                    database=current_db or config.get("database", ""),
                    db_type=config.get("db_type", ""),
                )
            else:
                self.connection_panel.set_active_connection(session.connection_name)

            current_widget = self._get_current_session_widget()
            if current_widget and getattr(current_widget, "session", None) == session and hasattr(current_widget, "editor"):
                for block in current_widget.editor.get_blocks():
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn and block.uses_tab_default_database():
                        block._database_name = current_db or None
                        block.db_panel.set_database(current_db or None)

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
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return

        host = config.get("host", "localhost")
        db_type = config.get("db_type", "")

        # Usar o banco retornado (pode ter mudado via USE)
        current_db = database or get_connector_database_context(getattr(session, "connector", None)) or config.get("database", "")
        if current_db:
            session.database_context = current_db

        # Always refresh schema cache for the session that connected (not only focused tab).
        from src.database.database_connector import DatabaseConnector
        if (
            session.connector
            and isinstance(session.connector, DatabaseConnector)
            and session.connector.is_connected()
        ):
            if not hasattr(self, "_oe_current_connection"):
                self._oe_current_connection = {}
            self._oe_current_connection[session.session_id] = connection_name
            self._schema_service.invalidate_cache(connection_name, session_id=session.session_id)
            self._load_schema_with_loading(
                session.connector,
                connection_name,
                session_id=session.session_id,
            )

        # UI updates only for the focused session tab.
        if self.session_manager.focused_session != session:
            return

        current_widget = self._get_current_session_widget()
        if current_widget and getattr(current_widget, "session", None) == session:
            self._clear_sql_autocomplete_for_connection(current_widget, connection_name)

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

        # === ATUALIZAR BLOCOS NO PADRAO DA ABA (sem override de banco) ===
        if current_widget and hasattr(current_widget, "editor"):
            for block in current_widget.editor.get_blocks():
                if hasattr(block, "db_panel"):
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn and block.uses_tab_default_database():
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

    def _setup_session_autosave(self) -> None:
        """Live session persistence (debounced background writes)."""
        from src.services.session_autosave_service import SessionAutosaveService

        self._session_autosave = SessionAutosaveService(self)
        self._session_autosave.configure(self._collect_session_autosave_payload)

    def _schedule_session_autosave(self) -> None:
        if getattr(self, "_is_closing", False):
            return
        autosave = getattr(self, "_session_autosave", None)
        if autosave is not None:
            autosave.schedule()

    def _flush_session_autosave(self) -> None:
        autosave = getattr(self, "_session_autosave", None)
        if autosave is not None:
            autosave.flush_now()

    def _collect_session_autosave_payload(self):
        """Build a disk snapshot on the UI thread (widgets -> session models)."""
        from src.services.session_autosave_service import SessionAutosavePayload

        if not hasattr(self, "session_manager"):
            return None

        for widget in self._session_widgets.values():
            widget.sync_to_session()
            widget.persist_session_variables()

        focused = self.session_manager.focused_session
        sessions_data = {
            "version": 1,
            "focused_session": focused.session_id if focused else None,
            "session_order": list(self.session_manager._session_order),
            "sessions": {
                sid: session.serialize()
                for sid, session in self.session_manager._sessions.items()
            },
        }

        workspace_path = Path(self.workspace_manager.config_path)
        dock_visible = (
            self.connections_dock.isVisible() if hasattr(self, "connections_dock") else True
        )
        workspace_data = {
            "tabs": [],
            "active_tab": 0,
            "active_connection": None,
            "window_geometry": {
                "x": self.geometry().x(),
                "y": self.geometry().y(),
                "width": self.geometry().width(),
                "height": self.geometry().height(),
                "maximized": self.isMaximized(),
            },
            "splitter_sizes": [],
            "dock_visible": dock_visible,
        }

        return SessionAutosavePayload(
            sessions_path=Path(self.session_manager._sessions_file),
            sessions_data=sessions_data,
            workspace_path=workspace_path,
            workspace_data=workspace_data,
        )

    def _save_sessions(self):
        """Flush pending session autosave (sync paths: workspace switch, tests)."""
        self._flush_session_autosave()

    def _restore_sessions(self):
        """Restores saved sessions - loads incrementally"""
        self._restoring_sessions = True
        self._pending_session_reconnects = []
        self._restored_session_reconnects_active = False
        self._pending_legacy_active_connection = None

        # Load sessions from disk
        self.session_manager.load_sessions(self.connection_manager, reconnect=False)

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
        if getattr(self, "_is_closing", False):
            return

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

            self._start_restored_session_reconnects()
            return

        session = self._sessions_to_load.pop(0)

        # Create widget for session
        self._create_session_widget(session)

        if session.connection_name and not session.is_connected:
            self._queue_restored_session_connection(session.session_id, session.connection_name)

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
                self._pending_legacy_active_connection = workspace["active_connection"]
                self._start_restored_session_reconnects()
            except Exception as e:
                logger.warning(f"Could not restore connection: {e}")

        # Clear reference
        del self._pending_workspace_restore

    def _reconnect_saved_connection(self, connection_name: str):
        """Reconnects a legacy saved workspace connection in background."""
        current_widget = self._get_current_session_widget()
        if current_widget is None:
            self._pending_legacy_active_connection = connection_name
            return

        if current_widget.session.connection_name:
            self._pending_legacy_active_connection = None
            return

        self._queue_restored_session_connection(current_widget.session.session_id, connection_name)
        self._pending_legacy_active_connection = None
        self._start_restored_session_reconnects()

    def _queue_restored_session_connection(self, session_id: str, connection_name: str):
        """Queues a saved session connection to be restored after the UI is ready."""
        if not session_id or not connection_name:
            return

        pending = getattr(self, "_pending_session_reconnects", None)
        if pending is None:
            self._pending_session_reconnects = []
            pending = self._pending_session_reconnects

        item = (session_id, connection_name)
        if item not in pending:
            pending.append(item)

    def _start_restored_session_reconnects(self):
        """Starts background reconnects for restored sessions after tabs are ready."""
        self._queue_legacy_saved_connection_if_needed()

        if getattr(self, "_restored_session_reconnects_active", False):
            return

        if not getattr(self, "_pending_session_reconnects", None):
            return

        self._restored_session_reconnects_active = True
        QTimer.singleShot(0, self._connect_next_restored_session)

    def _queue_legacy_saved_connection_if_needed(self):
        """Queues the legacy workspace active connection onto the focused tab."""
        connection_name = getattr(self, "_pending_legacy_active_connection", None)
        if not connection_name:
            return

        current_widget = self._get_current_session_widget()
        if current_widget is None:
            return

        if current_widget.session.connection_name:
            self._pending_legacy_active_connection = None
            return

        self._queue_restored_session_connection(current_widget.session.session_id, connection_name)
        self._pending_legacy_active_connection = None

    def _connect_next_restored_session(self):
        """Dispatches saved session reconnects without blocking startup."""
        if getattr(self, "_is_closing", False):
            self._restored_session_reconnects_active = False
            return

        pending = getattr(self, "_pending_session_reconnects", None) or []
        while pending:
            session_id, connection_name = pending.pop(0)
            widget = self._session_widgets.get(session_id)
            if widget is None or widget.session.is_connected:
                continue

            widget.connect_to_database(connection_name)
            QTimer.singleShot(25, self._connect_next_restored_session)
            return

        self._restored_session_reconnects_active = False

