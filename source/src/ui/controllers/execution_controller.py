"""
ExecutionController - Manages code execution lifecycle

Extracted from MainWindow to follow Single Responsibility Principle.
Handles:
- Execution timer and UI feedback
- Tab running indicators
- Execution results handling
- Notifications
"""

from typing import TYPE_CHECKING, Optional, List, Tuple
from PyQt6.QtCore import QObject, QTimer, QElapsedTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from src.design_system.app_dialogs import show_danger
import pandas as pd
import re
import logging

from src.language import S
from src.design_system.tokens import get_colors

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.ui.main_window import MainWindow


class ExecutionController(QObject):
    """Controller for code execution management"""
    
    # Signals
    execution_started = pyqtSignal(str)  # execution_type
    execution_finished = pyqtSignal(str, bool)  # execution_type, success
    
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._main = main_window
        
        # Worker threads (prevent GC)
        self._worker_threads: List[Tuple[QThread, QObject]] = []
        
        # Execution timer
        self._execution_timer = QElapsedTimer()
        self._execution_update_timer = QTimer()
        self._execution_update_timer.timeout.connect(self._update_execution_time)
        self._current_execution_type = ""
    
    @property
    def session_manager(self):
        return self._main.session_manager
    
    @property
    def session_tabs(self):
        return self._main.session_tabs
    
    @property
    def results_manager(self):
        return self._main.results_manager
    
    # =========================================================================
    # EXECUTION TIMER
    # =========================================================================
    
    def start_execution_timer(self, execution_type: str = ""):
        """Starts execution timer and updates UI"""
        colors = get_colors()
        self._current_execution_type = execution_type
        self._execution_timer.start()
        
        # Update timer display
        self._main.time_label.setText("0.0s")
        self._main.time_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.warning};
                font-weight: bold;
                font-size: 11px;
                padding: 0 10px;
            }}
        """)
        
        # Start update timer (every 100ms)
        self._execution_update_timer.start(100)
        
        self.execution_started.emit(execution_type)
    
    def stop_execution_timer(self):
        """Stops execution timer"""
        self._execution_update_timer.stop()
        
        # Calculate elapsed time
        elapsed_ms = self._execution_timer.elapsed()
        elapsed_sec = elapsed_ms / 1000.0
        
        colors = get_colors()
        self._main.time_label.setText(f"{elapsed_sec:.1f}s")
        self._main.time_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_secondary};
                font-size: 11px;
                padding: 0 10px;
            }}
        """)
    
    def _update_execution_time(self):
        """Updates execution time display"""
        elapsed_ms = self._execution_timer.elapsed()
        elapsed_sec = elapsed_ms / 1000.0
        self._main.time_label.setText(f"{elapsed_sec:.1f}s")
    
    def clear_execution_label(self):
        """Clears the execution time label"""
        self._main.time_label.setText("")
    
    # =========================================================================
    # TAB RUNNING INDICATORS
    # =========================================================================
    
    def mark_tab_running(self, is_running: bool, tab_index: int = None) -> int:
        """
        Marks/unmarks a tab as running (with animated spinner).
        
        Args:
            is_running: If True, shows spinner. If False, stops it.
            tab_index: Tab index. If None, uses current tab.
        
        Returns:
            Index of modified tab
        """
        if tab_index is None:
            tab_index = self.session_tabs.currentIndex()
        
        if tab_index < 0 or tab_index >= self.session_tabs.count():
            return tab_index
        
        self.session_tabs.set_tab_running(tab_index, is_running)
        return tab_index
    
    # =========================================================================
    # EXECUTION COMMANDS
    # =========================================================================
    
    def execute_current_block(self):
        """Executes the currently focused block"""
        editor = self._main._get_current_editor()
        if not editor:
            return
        
        from src.editors.block_editor import BlockEditor
        
        if isinstance(editor, BlockEditor):
            editor.execute_focused_block()
        else:
            # Legacy editor - execute as Python
            code = editor.get_selected_or_all_text().strip()
            if code:
                self.execute_python(code)
    
    def execute_all_blocks(self):
        """Executes all blocks in sequence"""
        editor = self._main._get_current_editor()
        if not editor:
            return
        
        from src.editors.block_editor import BlockEditor
        
        if isinstance(editor, BlockEditor):
            editor.execute_all_blocks()
        else:
            code = editor.get_selected_or_all_text().strip()
            if code:
                self.execute_python(code)
    
    def execute_and_advance(self):
        """Executes current block and advances to next"""
        editor = self._main._get_current_editor()
        if not editor:
            return
        
        from src.editors.block_editor import BlockEditor
        
        if isinstance(editor, BlockEditor):
            editor.execute_and_advance()
    
    def force_execute_sql(self):
        """Forces SQL execution regardless of block language"""
        widget = self._main._get_current_session_widget()
        if widget and widget.editor:
            block = widget.editor.get_focused_block()
            if block:
                code = block.get_code().strip()
                if code:
                    self.execute_sql(code)
    
    def force_execute_python(self):
        """Forces Python execution regardless of block language"""
        widget = self._main._get_current_session_widget()
        if widget and widget.editor:
            block = widget.editor.get_focused_block()
            if block:
                code = block.get_code().strip()
                if code:
                    self.execute_python(code)
    
    # =========================================================================
    # SQL EXECUTION
    # =========================================================================
    
    def execute_sql(self, query: str):
        """Executes SQL query in background"""
        query = query.strip()
        if not query:
            editor = self._main._get_current_editor()
            if editor:
                query = editor.get_selected_or_all_text().strip()
            if not query:
                return
        
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            self._main._show_warning(
                S.dialogs.warning, S.dialogs.cross_no_connection_msg
            )
            return
        
        connector = session.connector
        
        # Detect USE database command
        use_match = re.match(
            r"^\s*USE\s+(?:CATALOG\s+|SCHEMA\s+)?[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$",
            query, re.IGNORECASE
        )
        if use_match:
            self._handle_use_database(use_match, query, connector, session)
            return
        
        # Start execution
        self.start_execution_timer("SQL")
        self._main.action_label.setText(S.status.sql_running_query)
        
        running_tab_index = self.mark_tab_running(True)
        
        # Save current database to detect changes
        try:
            current_db_before = connector.get_current_database() if hasattr(connector, "get_current_database") else ""
        except Exception:
            current_db_before = ""
        
        # Create thread and worker
        from src.ui.main_window import SqlWorker
        
        thread = QThread()
        worker = SqlWorker(connector, query)
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda df, err: self._on_sql_finished(df, err, thread, running_tab_index, current_db_before)
        )
        
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))
        
        self._worker_threads.append((thread, worker))
        thread.start()
    
    def _handle_use_database(self, use_match, query, connector, session):
        """Handles USE database command in a background thread."""
        database_name = use_match.group(1)

        if connector.db_type == "databricks":
            catalog_match = re.match(r"^\s*USE\s+CATALOG\s+", query, re.IGNORECASE)
            schema_match = re.match(r"^\s*USE\s+SCHEMA\s+", query, re.IGNORECASE)
            if catalog_match:
                database_name = f"CATALOG:{database_name}"
            elif schema_match:
                database_name = f"SCHEMA:{database_name}"

        self.start_execution_timer("SQL")
        self._main.action_label.setText(S.status.sql_switching_database.format(name=database_name))
        current_widget = self._main._get_current_session_widget()
        connection_name = getattr(session, "connection_name", "") or ""

        def on_success(db_name: str):
            from src.database.database_connector import get_connector_database_context

            try:
                display_name = get_connector_database_context(connector) or db_name
                self._main._update_connection_status()
                if connection_name:
                    self._main._schema_service.invalidate_cache(connection_name)
                    if current_widget and hasattr(current_widget, "connection_changed"):
                        current_widget.connection_changed.emit(connection_name, display_name)
                self._main._log_info(S.status.database_changed.format(name=display_name))
                self._main.action_label.setText(S.status.sql_database.format(name=display_name))
            finally:
                self.stop_execution_timer()

        def on_error(message: str):
            self.stop_execution_timer()
            show_danger(self._main, S.dialogs.error, S.dialogs.error_switching_db.format(error=message))
            self._main.action_label.setText(S.status.sql_error_switching)

        self._main._start_database_switch_worker(connector, database_name, on_success=on_success, on_error=on_error)
    
    def _on_sql_finished(self, df, error, thread, tab_index, db_before=""):
        """Callback when SQL finishes"""
        self.stop_execution_timer()
        self.mark_tab_running(False, tab_index)
        thread.quit()
        
        # Detect database change via USE within batch
        self._check_database_changed_after_sql(db_before)
        
        if error:
            self._main._show_error_output(f"[SQL] Error: {error}")
            self._main.action_label.setText(S.status.sql_execution_error)
            self._main._send_notification(
                S.notification.sql_query,
                S.notification.error.format(error=str(error)[:50]),
                success=False, tab_index=tab_index
            )
            self.execution_finished.emit("SQL", False)
            return
        
        success = self._main._handle_execution_result(
            result=df,
            error=None,
            execution_type="SQL",
            additional_info=f"Executed successfully ({len(df):,} rows returned)" if df is not None else "",
        )
        
        if success:
            rows = len(df) if df is not None else 0
            self._main.action_label.setText(S.status.sql_rows_returned.format(rows=f"{rows:,}"))
            self._main._send_notification(
                S.notification.sql_query,
                S.notification.complete_rows.format(rows=f"{rows:,}"),
                success=True, tab_index=tab_index
            )
        
        self.execution_finished.emit("SQL", success)
    
    def _check_database_changed_after_sql(self, db_before: str):
        """Checks if database changed after SQL execution"""
        if not db_before:
            return
        
        session = self.session_manager.focused_session
        if not session or not session.connector:
            return
        
        connector = session.connector
        try:
            db_after = connector.get_current_database() if hasattr(connector, "get_current_database") else ""
        except Exception:
            return
        
        if not db_after or db_after.lower() == db_before.lower():
            return
        
        connection_name = getattr(session, "connection_name", "") or ""
        if connection_name:
            self._main._schema_service.invalidate_cache(connection_name)
            current_widget = self._main._get_current_session_widget()
            if current_widget and hasattr(current_widget, "connection_changed"):
                current_widget.connection_changed.emit(connection_name, db_after)
    
    # =========================================================================
    # PYTHON EXECUTION
    # =========================================================================
    
    def execute_python(self, code: str):
        """Executes Python code in background"""
        code = code.strip()
        if not code:
            return
        
        self.start_execution_timer("Python")
        self._main.action_label.setText(S.status.python_running)
        
        running_tab_index = self.mark_tab_running(True)
        
        # Get current namespace
        namespace = self.results_manager.get_namespace()
        
        # Create thread and worker
        from src.ui.main_window import PythonWorker
        
        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression=False)
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, output, err, ns, figs: self._on_python_finished(
                result, output, err, ns, figs, thread, running_tab_index
            )
        )
        
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))
        
        self._worker_threads.append((thread, worker))
        thread.start()
    
    def _on_python_finished(self, result_value, output, error, updated_namespace, figures, thread, tab_index):
        """Callback when Python finishes"""
        self.stop_execution_timer()
        
        # Update namespace
        self.results_manager.update_namespace(updated_namespace)
        if updated_namespace:
            self._main._push_python_namespace(updated_namespace)
        
        self.mark_tab_running(False, tab_index)
        thread.quit()
        
        if error:
            self._main._show_error_output(f"[Python] Error: {error}")
            self._main.action_label.setText(S.status.python_execution_error)
            self._main._send_notification(
                S.notification.python,
                S.notification.error.format(error=str(error)[:50]),
                success=False, tab_index=tab_index
            )
            self.execution_finished.emit("Python", False)
            return
        
        # Show output from print()/stderr
        if output:
            self._main._log(output.strip())
        
        # Handle results
        has_figures = bool(figures)
        results_panel = self._main.global_results_viewer
        
        if has_figures and result_value is not None and isinstance(result_value, pd.DataFrame):
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self._main.show_panel("results")
            self._main._update_variables_view()
            self._main.action_label.setText(S.status.python_chart_data)
            self._main._send_notification(
                S.notification.python, S.notification.chart_data, success=True, tab_index=tab_index
            )
        elif has_figures:
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self._main.show_panel("results")
            self._main._update_variables_view()
            self._main.action_label.setText(S.status.python_result_displayed)
            self._main._send_notification(
                S.notification.python, S.notification.result_displayed, success=True, tab_index=tab_index
            )
        elif result_value is not None:
            success = self._main._handle_execution_result(result=result_value, error=None, execution_type="Python")
            if success:
                self._main._update_variables_view()
                self._main.action_label.setText(S.status.python_executed)
                self._main._send_notification(
                    S.notification.python, S.notification.executed, success=True, tab_index=tab_index
                )
        else:
            if output:
                self._main.show_panel("output")
            self._main._update_variables_view()
            self._main.action_label.setText(S.status.python_executed)
            self._main._send_notification(
                S.notification.python, S.notification.executed, success=True, tab_index=tab_index
            )
        
        self.execution_finished.emit("Python", True)
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def _remove_worker_thread(self, thread):
        """Removes thread from active workers list"""
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
    
    def on_execution_started(self, widget):
        """Handle execution started from SessionWidget"""
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self.mark_tab_running(True, tab_index)
            self.start_execution_timer()
    
    def on_execution_cancelled(self, widget):
        """Handle execution cancellation from SessionWidget"""
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self.mark_tab_running(False, tab_index)
            self.stop_execution_timer()
    
    def on_execution_finished_cleanup(self, widget):
        """Cleanup after execution finishes"""
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self.mark_tab_running(False, tab_index)
            self.stop_execution_timer()
