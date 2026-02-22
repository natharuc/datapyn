"""
SessionWidget - Complete widget representing a session

Contains all session components:
- Code editor (UnifiedEditor)
- BottomTabs (Results, Output, Variables)
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QLabel
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont
import pandas as pd
import sys
import traceback
import logging
from io import StringIO
from typing import Optional, Dict, Any
from datetime import datetime

from src.core.session import Session
from src.core.theme_manager import ThemeManager
from src.editors import BlockEditor
from src.language import S
# from src.ui.components.bottom_tabs import BottomTabs  # Removed - using global panels

logger = logging.getLogger(__name__)


class SessionConnectionWorker(QObject):
    """Worker to connect to database in background"""

    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, session, connection_name, password):
        super().__init__()
        self.session = session
        self.connection_name = connection_name
        self.password = password

    def run(self):
        try:
            success = self.session.connect(self.connection_name, self.password)
            if success:
                self.finished.emit(True, f"{S.session_widget.connected_to.format(name=self.connection_name)}")
            else:
                self.finished.emit(False, f"{S.session_widget.connect_failed.format(name=self.connection_name)}")
        except Exception as e:
            self.finished.emit(False, S.session_widget.connect_error.format(msg=str(e)))


class SessionSqlWorker(QObject):
    """Worker to execute SQL in background for a session"""

    finished = pyqtSignal(object, str)  # (result_df ou None, error_msg)

    def __init__(self, connector, query):
        super().__init__()
        self.connector = connector
        self.query = query

    def run(self):
        try:
            df = self.connector.execute_query(self.query)
            self.finished.emit(df, "")
        except Exception as e:
            error_msg = str(e)
            # Detect if it was cancellation
            cancelled = getattr(self.connector, "_cancelled", False)
            lower_msg = error_msg.lower()
            if cancelled or "cancel" in lower_msg or "abort" in lower_msg:
                self.finished.emit(None, "__CANCELLED__")
            else:
                self.finished.emit(None, error_msg)


class SessionPythonWorker(QObject):
    """Worker to execute Python in background for a session"""

    finished = pyqtSignal(object, str, str, dict)  # (result, output, error, updated_namespace)

    def __init__(self, code, namespace, is_expression):
        super().__init__()
        self.code = code
        self.namespace = namespace.copy()  # Copy for thread safety
        self.is_expression = is_expression

    def run(self):
        """REMOVIDO - usar PythonWorker centralizado do main_window.py"""
        raise NotImplementedError("Use PythonWorker from main_window.py - centralized execution!")


class SessionWidget(QWidget):
    """
    Complete widget representing a session.

    Contains:
    - Code editor
    - Results table
    - Output/Logs
    - Variables in memory
    """

    # Signals for MainWindow
    execute_sql = pyqtSignal(str)  # query
    execute_python = pyqtSignal(str)  # code
    status_changed = pyqtSignal(str)  # status message
    connection_changed = pyqtSignal(str, str)  # (connection_name, database)
    connection_drop_requested = pyqtSignal(str)  # connection_name
    block_connection_changed = pyqtSignal(object, str)  # (CodeBlock, connection_name)
    block_database_changed = pyqtSignal(object, str)  # (CodeBlock, database_name)
    execution_started = pyqtSignal()  # Emitted when execution starts (for running indicator)
    execution_finished = pyqtSignal(str, str, bool)  # (title, message, success)
    execution_cancelled = pyqtSignal()  # Emitted when execution is cancelled
    completion_log = pyqtSignal(str, str)  # message, level - for autocomplete logging

    def __init__(self, session: Session, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)

        self.session = session
        self.theme_manager = theme_manager or ThemeManager()

        # Active workers
        self._sql_thread: Optional[QThread] = None
        self._python_thread: Optional[QThread] = None
        self._connection_thread: Optional[QThread] = None
        self._connection_worker: Optional[SessionConnectionWorker] = None

        # Connection color (will be set when connecting)
        self._connection_color: str = "#007ACC"  # Default: primary blue

        # Execution queue for multiple blocks
        self._execution_queue: list = []  # List of (language, code, block, block_name, connection_name, database_name)
        self._is_executing: bool = False
        self._cancel_requested: bool = False  # Cancellation flag
        self._current_block_name: str = None  # Currently executing block name (for isolated namespace)

        # Notification aggregation: accumulate results per queue run
        self._queue_total_rows: int = 0
        self._queue_blocks_done: int = 0
        self._queue_had_error: bool = False
        self._queue_last_error: str = ""
        self._queue_last_type: str = ""  # "sql", "python", "cross"

        # Overlay de loading
        self._loading_overlay: Optional[QLabel] = None

        self._setup_ui()
        self._connect_signals()

        # Restore blocks if they exist
        if session.blocks:
            self.editor.from_list(session.blocks)
        elif session.code:
            # Compatibility: old code without blocks
            self.editor.setText(session.code)

        # Connections are selected per block via clickable panel (no need to populate list)

    def _setup_ui(self):
        """Configure widget UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main splitter (vertical) - Editor on top, Results on bottom
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        # === PARTE SUPERIOR: Editor de Blocos ===
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(5, 5, 5, 5)

        # Block editor (replaces UnifiedEditor)
        self.editor = BlockEditor(theme_manager=self.theme_manager)
        editor_layout.addWidget(self.editor)

        self.splitter.addWidget(editor_container)

        # Note: BottomTabs removed - using global panels from MainWindow
        # Layout now only contains the editor (Results/Output/Variables panels are dockable)

        layout.addWidget(self.editor)  # Simplified layout: just editor

        # Loading overlay (initially hidden)
        self._loading_overlay = QLabel(self)
        self._loading_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Style will be set dynamically in _show_loading
        self._loading_overlay.hide()
        self._loading_overlay.raise_()

    # === Propriedades de compatibilidade ===

    @property
    def results_viewer(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_results_viewer if main_window else None

    @property
    def output_text(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_output_panel if main_window else None

    @property
    def variables_viewer(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_variables_panel if main_window else None

    @property
    def bottom_tabs(self):
        """Compatibility: returns object that delegates to dockable panels"""
        # Always return the same object for consistency
        if not hasattr(self, "_bottom_tabs_cache"):
            main_window = self._get_main_window()
            self._bottom_tabs_cache = main_window.bottom_tabs if main_window else None
        return self._bottom_tabs_cache

    def _get_main_window(self):
        """Get MainWindow reference"""
        parent = self.parent()
        while parent and not hasattr(parent, "global_results_viewer"):
            parent = parent.parent()
        return parent

    def _get_own_panels(self):
        """Get this session's own panels (results, output, variables).

        Returns the panels that belong to THIS session, not the currently focused one.
        This is critical to avoid results from one tab appearing in another.
        """
        try:
            main_window = self._get_main_window()
            if not main_window or not hasattr(main_window, "_session_panel_indices"):
                return None
            return main_window._session_panel_indices.get(self.session.session_id)
        except (AttributeError, TypeError):
            return None

    # === Delegation methods for global panels ===

    def _show_output(self):
        """Mostra o painel de output"""
        main_window = self._get_main_window()
        if main_window:
            main_window.show_panel("output")

    def _set_results(self, data, name="result"):
        """Define resultados no painel DESTA sessao"""
        info = self._get_own_panels()
        viewer = info["results"] if info else None
        if not viewer:
            # Fallback: usar viewer global (compatibilidade com testes/mocks)
            main_window = self._get_main_window()
            viewer = main_window.global_results_viewer if main_window else None
        if viewer:
            viewer.display_dataframe(data, name)
            main_window = self._get_main_window()
            if main_window:
                main_window.show_panel("results")

    def _set_figures(self, figures: list, label: str = "Resultado"):
        """Exibe rich outputs (imagens, HTML, JSON) no painel DESTA sessao"""
        info = self._get_own_panels()
        viewer = info["results"] if info else None
        if not viewer:
            main_window = self._get_main_window()
            viewer = main_window.global_results_viewer if main_window else None
        if viewer:
            viewer.display_rich_output(figures, label)
            main_window = self._get_main_window()
            if main_window:
                main_window.show_panel("results")

    def _log_error(self, text):
        """Log error to this session's output"""
        info = self._get_own_panels()
        output = info["output"] if info else None
        if not output:
            main_window = self._get_main_window()
            output = main_window.global_output_panel if main_window else None
        if output:
            output.error(text)
            self._show_output()

    def _log(self, text):
        """Registra texto no output desta sessao"""
        info = self._get_own_panels()
        output = info["output"] if info else None
        if not output:
            main_window = self._get_main_window()
            output = main_window.global_output_panel if main_window else None
        if output:
            output.log(text)

    def _clear_output(self):
        """Limpa output desta sessao"""
        info = self._get_own_panels()
        output = info["output"] if info else None
        if not output:
            main_window = self._get_main_window()
            output = main_window.global_output_panel if main_window else None
        if output:
            output.clear()

    def _set_variables(self, variables_dict):
        """Set variables in this session's panel"""
        info = self._get_own_panels()
        panel = info["variables"] if info else None
        if not panel:
            main_window = self._get_main_window()
            panel = main_window.global_variables_panel if main_window else None
        if panel:
            panel.set_variables(variables_dict)

    def _connect_signals(self):
        """Connect editor signals"""
        # BlockEditor emits signals with correct language
        self.editor.execute_sql.connect(self._on_execute_sql)
        self.editor.execute_python.connect(self._on_execute_python)

        # Execution queue (multiple blocks)
        self.editor.execute_queue.connect(self._on_execute_queue)

        # Cancellation
        self.editor.cancel_execution.connect(self._on_cancel_execution)

        # Connection selection for specific block
        self.editor.select_connection_for_block.connect(self._on_block_select_connection)

        # Block connection change (to reload autocomplete)
        self.editor.block_connection_changed.connect(self.block_connection_changed.emit)

        # Connection drop on editor area (connect session + Object Explorer)
        self.editor.connection_drop_requested.connect(self.connection_drop_requested.emit)

        # Block database change
        self.editor.block_database_changed.connect(self.block_database_changed.emit)

        # Completion logging (for Copilot output panel)
        self.editor.completion_log.connect(self.completion_log.emit)

        # Drop data file (opens import dialog)
        self.editor.file_dropped.connect(self._on_file_dropped)

        # Connect session signals
        self.session.variables_changed.connect(self._update_variables_view)

    def _format_log(self, log_type: str, message: str = "") -> str:
        """Format log message with timestamp and type"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if message:
            return f"[{timestamp}][{log_type}] {message}"
        return f"[{timestamp}][{log_type}]"

    # === SQL EXECUTION ===

    def _on_execute_sql(self, query: str, block_name: str = None, connection_name: str = None, database_name: str = None):
        """Execute SQL in background

        Args:
            query: SQL query
            block_name: Block name (DataFrame variable name)
            connection_name: Custom connection name (None = use session default)
            database_name: Custom database name (None = use connection default)
        """
        # Determine which connection to use
        if connection_name:
            # Fetch specific connection - auto-connect if needed
            from src.database.connection_manager import ConnectionManager
            from src.database.database_connector import DatabaseConnector

            manager = ConnectionManager()
            connector = manager.get_connection(connection_name)
            if not connector or not connector.is_connected():
                # Try to auto-connect from saved config
                config = manager.get_connection_config(connection_name)
                if config:
                    try:
                        connector = DatabaseConnector()
                        connector.connect(
                            db_type=config["db_type"],
                            host=config["host"],
                            port=config["port"],
                            database=config["database"],
                            username=config.get("username", ""),
                            password=config.get("password", ""),
                            use_windows_auth=config.get("use_windows_auth", False),
                            trust_server_certificate=config.get("trust_server_certificate", False),
                            http_path=config.get("http_path", ""),
                        )
                        if connector.is_connected:
                            manager.connections[connection_name] = connector
                        else:
                            self.append_output(S.session_widget.block_connect_failed.format(name=connection_name), error=True)
                            self.status_changed.emit(S.session_widget.status_conn_failed)
                            self._process_next_in_queue()
                            return
                    except Exception as e:
                        self.append_output(S.session_widget.block_connect_error.format(name=connection_name, error=e), error=True)
                        self.status_changed.emit(S.session_widget.status_conn_failed)
                        self._process_next_in_queue()
                        return
                else:
                    self.append_output(S.session_widget.conn_not_found.format(name=connection_name), error=True)
                    self.status_changed.emit(S.session_widget.status_conn_unavailable)
                    self._process_next_in_queue()
                    return
            conn_label = connection_name
        else:
            # Use session default connection
            if not self.session.is_connected:
                self.append_output(S.session_widget.no_active_connection, error=True)
                self.status_changed.emit(S.session_widget.status_no_connection)
                self._process_next_in_queue()
                return
            connector = self.session.connector
            conn_label = S.session_widget.default_connection_label

        # Apply custom database if specified (before executing)
        if database_name:
            try:
                connector.change_database(database_name)
            except Exception as e:
                self.append_output(S.session_widget.block_connect_error.format(name=database_name, error=e), error=True)
                self._process_next_in_queue()
                return

        if self._is_executing or (self._sql_thread and self._sql_thread.isRunning()):
            self._execution_queue.append(("sql", query, None, block_name, connection_name, database_name))
            return

        self._is_executing = True
        self._cancel_requested = False  # Limpar flag de cancelamento anterior

        # Reset notification counters for single-block execution
        if self._queue_blocks_done == 0:
            self._queue_total_rows = 0
            self._queue_had_error = False
            self._queue_last_error = ""
            self._queue_last_type = ""

        self.session.start_execution("sql")
        self.status_changed.emit(S.session_widget.executing_sql.format(conn_label=conn_label))
        self.execution_started.emit()  # Notify main_window to show running indicator

        # Criar worker e thread
        self._sql_thread = QThread()
        self._sql_worker = SessionSqlWorker(connector, query)
        self._sql_worker.moveToThread(self._sql_thread)

        # Store block_name to use in callback
        self._current_block_name = block_name

        # Store db state before execution for change detection
        self._current_connector = connector
        self._current_connection_name = connection_name or self.session.connection_name
        try:
            self._db_before_execution = connector.get_current_database() if connector else ""
        except Exception:
            self._db_before_execution = ""

        # Register thread in session
        self.session.register_thread(self._sql_thread)

        # Conectar sinais
        self._sql_thread.started.connect(self._sql_worker.run)
        self._sql_worker.finished.connect(self._on_sql_finished)

        # Iniciar
        self._sql_thread.start()

    def _on_sql_finished(self, df: Optional[pd.DataFrame], error: str):
        """Callback when SQL finishes"""
        # If cancelled, ignore result (UI already cleaned by cancel)
        if error == "__CANCELLED__" or self._cancel_requested:
            # Async thread cleanup - don't wait synchronously
            if self._sql_thread:
                thread = self._sql_thread
                self._sql_thread = None
                try:
                    self.session.unregister_thread(thread)
                except Exception:
                    pass
                thread.quit()
                thread.deleteLater()
            return

        # Async thread cleanup - don't wait synchronously
        if self._sql_thread:
            thread = self._sql_thread
            self._sql_thread = None
            try:
                self.session.unregister_thread(thread)
            except Exception:
                pass
            thread.quit()
            thread.deleteLater()

        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)

        if error:
            self.append_output(self._format_log("SQL", f"ERROR: {error}"), error=True)
            self.session.finish_execution(False, f"Error: {error[:50]}...")
            self.status_changed.emit(S.session_widget.status_sql_error)
            self._queue_had_error = True
            self._queue_last_error = error[:80]
            self._queue_last_type = "sql"
            self._queue_blocks_done += 1
            self._show_output()
        else:
            # Determine namespace prefix (isolated per block or global)
            if self._current_block_name:
                var_base = self._current_block_name  # block name
            else:
                var_base = "df"  # fallback (compatibilidade)

            # Check if returned list of DataFrames (multiple SELECTs)
            if isinstance(df, list):
                # Multiple DataFrames - create variables
                total_rows = sum(len(d) for d in df)
                self.append_output(self._format_log("SQL", S.session_widget.sql_multi_result.format(count=len(df), rows=f"{total_rows:,}")))

                # Create variables: test, test1, test2, ...
                for i, dataframe in enumerate(df):
                    var_name = var_base if i == 0 else f"{var_base}{i}"
                    self.session.set_variable(var_name, dataframe)
                    self.append_output(self._format_log("SQL", S.session_widget.sql_var_rows.format(var_name=var_name, rows=f"{len(dataframe):,}")))

                # Display only last DataFrame in grid
                last_df = df[-1]
                last_var_name = f"{var_base}{len(df) - 1}" if len(df) > 1 else var_base
                self._set_results(last_df, last_var_name)
                self.session.set_variable("_last_result", last_df)

                self.session.finish_execution(True, S.session_widget.status_sql_multi.format(count=len(df)))
                self.status_changed.emit(S.session_widget.status_sql_multi.format(count=len(df)))
                self._queue_total_rows += total_rows
                self._queue_blocks_done += 1
                self._queue_last_type = "sql"
            else:
                # Single DataFrame
                rows = len(df) if df is not None else 0
                var_name = var_base
                self.append_output(self._format_log("SQL", S.session_widget.sql_single_result.format(rows=f"{rows:,}", var_name=var_name)))
                self._set_results(df, var_name)
                self.session.finish_execution(True, S.session_widget.status_sql_rows.format(rows=f"{rows:,}"))
                self.status_changed.emit(S.session_widget.status_sql_rows.format(rows=f"{rows:,}"))
                self._queue_total_rows += rows
                self._queue_blocks_done += 1
                self._queue_last_type = "sql"

                # Save in session namespace
                self.session.set_variable(var_name, df)
                self.session.set_variable("_last_result", df)

            # Clear block_name after use
            self._current_block_name = None

            # Check if database changed (e.g. USE command)
            # Compares db before/after execution - only emits if actually changed
            if hasattr(self, "_current_connector") and self._current_connector:
                try:
                    db_after = self._current_connector.get_current_database() or ""
                except Exception:
                    db_after = ""
                db_before = getattr(self, "_db_before_execution", "")
                conn_name = getattr(self, "_current_connection_name", "") or self.session.connection_name
                if db_after and db_before and db_after != db_before and conn_name:
                    self.connection_changed.emit(conn_name, db_after)
                    # Update block db_panel if not from a per-block connection
                    current_block = self.editor.get_focused_block()
                    if not current_block:
                        current_block = self.editor.get_last_focused_block()
                    if current_block and hasattr(current_block, "db_panel"):
                        current_block._database_name = db_after
                        current_block.db_panel.set_database(db_after)
                # Note: Do NOT emit connection_changed if database didn't change
                # This avoids unnecessary schema reloads which cause performance issues

        # Process next in queue if available
        self._is_executing = False
        self._process_next_in_queue()

    # === PYTHON EXECUTION ===

    def _on_execute_python(self, code: str):
        """Execute Python in background"""
        # If already executing, add to queue
        if self._is_executing or (self._python_thread and self._python_thread.isRunning()):
            self._execution_queue.append(("python", code))
            return

        self._is_executing = True
        self._cancel_requested = False  # Limpar flag de cancelamento anterior

        # Reset notification counters for single-block execution
        if self._queue_blocks_done == 0:
            self._queue_total_rows = 0
            self._queue_had_error = False
            self._queue_last_error = ""
            self._queue_last_type = ""

        self.session.start_execution("python")
        self.status_changed.emit(S.session_widget.executing_python)
        self.execution_started.emit()  # Notify main_window to show running indicator
        
        # Prepare namespace with df if exists
        namespace = self.session.namespace.copy()
        namespace["pd"] = pd

        # Inject database variables for direct access in Python code
        self._inject_db_variables(namespace)

        # Check if it's an expression
        is_expression = False
        try:
            compile(code, "<string>", "eval")
            is_expression = True
        except SyntaxError:
            pass

        # Use CENTRALIZED PythonWorker from main_window
        from src.ui.main_window import PythonWorker

        # Criar worker e thread
        self._python_thread = QThread()
        self._python_worker = PythonWorker(code, namespace, is_expression)
        self._python_worker.moveToThread(self._python_thread)

        self.session.register_thread(self._python_thread)

        self._python_thread.started.connect(self._python_worker.run)
        self._python_worker.finished.connect(self._on_python_finished_adapted)

        self._python_thread.start()

    def _on_python_finished_adapted(self, result, output: str, error: str, namespace: dict, figures: list = None):
        """Adapter to use centralized PythonWorker"""
        # Call original callback with updated namespace
        self._on_python_finished(result, output, error, namespace, figures or [])

    def _on_python_finished(self, result, output: str, error: str, updated_namespace: dict, figures: list = None):
        """Callback when Python finishes"""
        figures = figures or []

        # Async thread cleanup - don't wait synchronously
        if self._python_thread:
            thread = self._python_thread
            self._python_thread = None
            try:
                self.session.unregister_thread(thread)
            except Exception:
                pass
            thread.quit()
            thread.deleteLater()

        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)

        if error:
            self.append_output(self._format_log("PYTHON", f"ERROR:\n{error}"), error=True)
            self.session.finish_execution(False, S.session_widget.status_python_error)
            self.status_changed.emit(S.session_widget.status_python_error)
            self._queue_had_error = True
            self._queue_last_error = error[:80]
            self._queue_last_type = "python"
            self._queue_blocks_done += 1
            self._show_output()
        else:
            has_dataframe_result = False
            has_figures = bool(figures)
            has_output = bool(output)

            # 1. Logs/print -> Output
            if output:
                self.append_output(self._format_log("PYTHON", output))

            # 2. Resultado -> Results (DataFrame) ou Output (outro)
            if result is not None:
                if isinstance(result, pd.DataFrame):
                    has_dataframe_result = True
                    self._set_results(result, "result")
                    self.append_output(self._format_log("PYTHON", S.session_widget.python_df_result.format(rows=f"{len(result):,}")))
                else:
                    self.append_output(self._format_log("PYTHON", f"{repr(result)}"))
                    has_output = True

            # 3. Figuras matplotlib -> Results (imagem)
            if has_figures:
                self._set_figures(figures)

            # Display logic:
            # - Figuras + DataFrame -> mostra figuras (prioridade visual)
            # - Figuras -> mostra figuras
            # - DataFrame -> mostra grid
            # - Output -> mostra output
            if has_figures:
                if has_dataframe_result:
                    self.status_changed.emit(S.session_widget.status_chart_data)
                else:
                    self.status_changed.emit(S.session_widget.status_chart_shown)
            elif has_dataframe_result:
                self.status_changed.emit(S.session_widget.status_df_rows.format(rows=f"{len(result):,}"))
            elif has_output:
                self._show_output()
                self.status_changed.emit(S.session_widget.status_python_done)
            else:
                self.status_changed.emit(S.session_widget.status_python_done)

            # Update session namespace
            if updated_namespace:
                self.session.update_namespace(updated_namespace)

            self.session.finish_execution(True, S.session_widget.status_python_done)
            self._queue_blocks_done += 1
            self._queue_last_type = "python"

        # Process next in queue if exists
        self._is_executing = False
        self._process_next_in_queue()

    # === EXECUTION NOTIFICATION ===

    def _emit_queue_notification(self):
        """Emit a single notification summarizing the entire queue execution."""
        if self._queue_blocks_done == 0:
            return

        if self._queue_had_error:
            title = S.notification.sql_query if self._queue_last_type == "sql" else S.notification.python
            msg = S.notification.error.format(error=self._queue_last_error)
            self.execution_finished.emit(title, msg, False)
        else:
            # Build a meaningful message based on what ran
            if self._queue_last_type == "sql":
                title = S.notification.sql_query
                msg = S.notification.complete_rows.format(rows=f"{self._queue_total_rows:,}")
            else:
                title = S.notification.python
                msg = S.notification.executed

            # If multiple blocks ran, mention that
            if self._queue_blocks_done > 1:
                msg = f"{self._queue_blocks_done} blocks - {msg}"

            self.execution_finished.emit(title, msg, True)

        # Reset counters
        self._queue_total_rows = 0
        self._queue_blocks_done = 0
        self._queue_had_error = False
        self._queue_last_error = ""
        self._queue_last_type = ""

    # === EXECUTION QUEUE ===

    def _on_execute_queue(self, queue: list):
        """
        Recebe uma fila de blocos para executar sequencialmente.

        Args:
            queue: Lista de tuplas (language, code, block)
        """
        # Reset cancellation flag
        self._cancel_requested = False

        # Reset notification tracking for this queue run
        self._queue_total_rows = 0
        self._queue_blocks_done = 0
        self._queue_had_error = False
        self._queue_last_error = ""
        self._queue_last_type = ""

        # Add all to queue
        self._execution_queue.extend(queue)

        # Start processing if not executing
        if not self._is_executing:
            self._process_next_in_queue()

    def _on_cancel_execution(self):
        """Cancel current execution and clear queue.
        
        Non-blocking: sends cancellation signal and returns immediately.
        Actual cleanup happens when worker emits finished signal.
        """
        self._cancel_requested = True
        self._execution_queue.clear()

        # Cancel SQL query in database (real cancellation)
        if self._sql_thread and self._sql_thread.isRunning():
            # Try to cancel query in database - this is non-blocking
            if hasattr(self, "_sql_worker") and self._sql_worker:
                connector = getattr(self._sql_worker, "connector", None)
                if connector and hasattr(connector, "cancel_query"):
                    try:
                        connector.cancel_query()
                    except Exception as e:
                        logger.warning(f"Error cancelling SQL query: {e}")
            
            # Don't wait synchronously - let the finished signal handle cleanup
            # The cancel_query() will interrupt the cursor, causing worker.run() to return
            # with error, which emits finished signal, triggering _on_sql_finished for cleanup.

        if self._python_thread and self._python_thread.isRunning():
            # For Python, we can only request quit - the thread will finish when it can
            self._python_thread.requestInterruption()

        # CRITICO: Resetar estado de execucao e UI do bloco imediatamente
        self._is_executing = False
        self._current_block_name = None

        # Marcar todos os blocos como nao executando (limpa visual)
        self.editor.mark_execution_finished()

        self.append_output(self._format_log("CANCELLED", S.session_widget.cancelled_output.replace("[CANCELLED] ", "")), error=True)
        self._show_output()
        self.status_changed.emit(S.session_widget.status_cancelled)

        # Terminar execucao na sessao
        self.session.finish_execution(False, S.session_widget.execution_cancelled)

        # Emit cancellation signal so MainWindow can clear tab running state
        self.execution_cancelled.emit()

        # CRITICO: Resetar flag de cancelamento para nao bloquear proximas execucoes
        self._cancel_requested = False

    def _process_next_in_queue(self):
        """Process next item in execution queue"""
        # Check if cancelled
        if self._cancel_requested:
            self._cancel_requested = False
            return

        if not self._execution_queue:
            # Fila vazia, marca todos os blocos como finalizados
            self.editor.mark_execution_finished()
            # Emit single notification for entire queue run
            self._emit_queue_notification()
            return

        # Get next from queue
        item = self._execution_queue.pop(0)

        # Supports formats:
        # Old: (language, code)
        # Medium: (language, code, block)
        # Legacy: (language, code, block, block_name, connection_name)
        # Current: (language, code, block, block_name, connection_name, database_name)
        if len(item) >= 6:
            language, code, block, block_name, connection_name, database_name = item[:6]
            if block:
                self.editor.mark_block_started(block)
        elif len(item) == 5:
            language, code, block, block_name, connection_name = item[:5]
            database_name = None
            if block:
                self.editor.mark_block_started(block)
        elif len(item) == 3:
            language, code, block = item
            block_name = None
            connection_name = None
            database_name = None
            if block:
                self.editor.mark_block_started(block)
        else:
            language, code = item
            block = None
            block_name = None
            connection_name = None
            database_name = None

        # Execute according to language
        if language == "sql":
            self._on_execute_sql(code, block_name=block_name, connection_name=connection_name, database_name=database_name)
        elif language == "python":
            self._on_execute_python(code)
        else:
            # Unknown language, continue to next
            self._process_next_in_queue()

    # === OUTPUT/LOG ===

    def append_output(self, text: str, error: bool = False):
        """Add text to output"""
        if error:
            self._log_error(text)
        else:
            self._log(text)

    def clear_output(self):
        """Limpa o output"""
        self._clear_output()

    # === VARIABLES ===

    def _update_variables_view(self, namespace: dict):
        """Update variables view, including database variables"""
        # Filter internal variables
        visible_vars = {k: v for k, v in namespace.items() if not k.startswith("_") and k not in ("pd", "np", "plt")}

        # Injetar variaveis de banco de dados se houver conexao ativa
        self._inject_db_variables(visible_vars)

        # Usar o metodo do BottomTabs
        self._set_variables(visible_vars)

    def _inject_db_variables(self, variables: dict):
        """Injeta variaveis de banco de dados no namespace visivel.

        Expoe engine, connection_string, db_type, host, database, etc.
        para o usuario poder usar diretamente em blocos Python.
        """
        connector = self.session.connector
        conn_name = self.session.connection_name

        if not connector or not conn_name:
            return

        try:
            # Engine SQLAlchemy
            if hasattr(connector, "engine") and connector.engine is not None:
                variables["db_engine"] = connector.engine

            # Tipo do banco (sqlserver, mysql, postgresql, etc.)
            if hasattr(connector, "db_type") and connector.db_type:
                variables["db_type"] = connector.db_type

            # Nome da conexao
            variables["db_connection_name"] = conn_name

            # Connection string (URL do engine, mascarando senha)
            if hasattr(connector, "engine") and connector.engine is not None:
                try:
                    url_str = str(connector.engine.url)
                    # Mascarar senha na exibicao (seguranca)
                    variables["db_connection_string"] = url_str
                except Exception:
                    pass

            # Parametros de conexao (host, port, database, username)
            if hasattr(connector, "connection_params") and connector.connection_params:
                params = connector.connection_params
                if "host" in params:
                    variables["db_host"] = params["host"]
                if "port" in params:
                    variables["db_port"] = params["port"]
                if "database" in params:
                    variables["db_database"] = params["database"]
                if "username" in params:
                    variables["db_username"] = params["username"]
        except Exception:
            pass  # Silenciar erros ao coletar info de banco

    # === TEMA ===

    def apply_theme(self):
        """Apply current theme"""
        self.editor.apply_theme()
        # Theme manager delegated to global panels - no longer needed

    # === ESTADO ===

    def get_code(self) -> str:
        """Return current editor code"""
        return self.editor.text()

    def set_code(self, code: str):
        """Set editor code"""
        self.editor.setText(code)

    def sync_to_session(self):
        """Sync widget state to session"""
        self.session.code = self.get_code()  # Compatibilidade
        self.session.blocks = self.editor.to_list()  # Novo: blocos
        # Sync file_path and file type
        if hasattr(self, "file_path") and self.file_path:
            self.session.file_path = self.file_path
        if hasattr(self, "_original_file_type") and self._original_file_type:
            self.session.original_file_type = self._original_file_type

    def sync_from_session(self):
        """Sync session state to widget"""
        if self.session.blocks:
            self.editor.from_list(self.session.blocks)
        elif self.session.code:
            self.set_code(self.session.code)

    def _on_file_dropped(self, file_path: str):
        """Open import dialog when data file is dropped on editor"""
        try:
            from src.ui.dialogs.file_import_dialog import FileImportDialog

            dialog = FileImportDialog(file_path, self.theme_manager, self)
            if dialog.exec():
                code, var_name = dialog.get_result()
                if code:
                    # Adicionar bloco com o codigo gerado
                    self.editor.add_block(language="python", code=code)
                    self.editor.content_changed.emit()

                    # Executar o codigo automaticamente
                    self._on_execute_python(code)
        except Exception as e:
            self.append_output(S.session_widget.file_import_error.format(error=e), error=True)
            self._show_output()

    def _on_block_select_connection(self, block):
        """Opens simple dialog to select connection for a SQL block"""
        try:
            from src.ui.dialogs.connection_picker_dialog import ConnectionPickerDialog

            # Obter connection_manager da MainWindow (instancia unica)
            main_window = self._get_main_window()
            if main_window and hasattr(main_window, "connection_manager"):
                manager = main_window.connection_manager
            else:
                from src.database.connection_manager import ConnectionManager

                manager = ConnectionManager()

            dialog = ConnectionPickerDialog(manager, self.theme_manager, self)

            if dialog.exec():
                conn_name, config = dialog.get_result()
                if conn_name:
                    db_type = config.get("db_type", "mysql") if config else "mysql"
                    color = config.get("color", "") if config else ""
                    block.set_connection_name(conn_name, db_type, color or None)
        except Exception as e:
            print(S.session_widget.conn_dialog_error.format(error=e))

    # === CONNECTION ===

    def connect_to_database(self, connection_name: str, password: str = "") -> bool:
        """
        Connect this session to a database (in background)

        Args:
            connection_name: Connection name
            password: Password (if required)

        Returns:
            True (always, as it's asynchronous)
        """
        # Get connection color
        from src.database.connection_manager import ConnectionManager

        manager = ConnectionManager()
        config = manager.get_connection_config(connection_name)
        if config:
            self._connection_color = config.get("color", "#007ACC") or "#007ACC"

        # Cancel previous connection if still running (async cleanup)
        try:
            if self._connection_thread and self._connection_thread.isRunning():
                old_thread = self._connection_thread
                self._connection_thread = None
                old_thread.quit()
                old_thread.deleteLater()
        except RuntimeError:
            pass  # Thread was already deleted

        # Mostrar loading overlay
        self._show_loading(S.session_widget.loading_connecting.format(name=connection_name))

        # Criar worker e thread
        self._connection_thread = QThread()
        self._connection_worker = SessionConnectionWorker(self.session, connection_name, password)
        self._connection_worker.moveToThread(self._connection_thread)

        # Conectar sinais
        self._connection_thread.started.connect(self._connection_worker.run)
        self._connection_worker.finished.connect(self._on_connection_finished)
        self._connection_worker.finished.connect(self._connection_thread.quit)
        self._connection_worker.finished.connect(self._connection_worker.deleteLater)
        self._connection_thread.finished.connect(self._connection_thread.deleteLater)

        # Iniciar
        self._connection_thread.start()

        return True

    def is_connecting(self) -> bool:
        """Check if connection is in progress"""
        try:
            return self._connection_thread is not None and self._connection_thread.isRunning()
        except RuntimeError:
            return False  # Thread was deleted

    def _on_connection_finished(self, success: bool, message: str):
        """Callback when connection finishes"""
        # Esconder loading
        self._hide_loading()

        # Mostrar resultado
        if success:
            self.append_output(message)
            self.status_changed.emit(message)
            # Emit connection change signal
            if self.session.connection_name and self.session.connector:
                db = (
                    self.session.connector.get_current_database()
                    if hasattr(self.session.connector, "get_current_database")
                    else ""
                )
                self.connection_changed.emit(self.session.connection_name, db)
        else:
            self.append_output(message, error=True)
            self.status_changed.emit(S.session_widget.status_conn_error)

    def _show_loading(self, message: str):
        """Show loading overlay - subtle and modern"""
        if self._loading_overlay:
            # Add spinner icon before message
            spinner_text = f"  {message}"
            self._loading_overlay.setText(spinner_text)
            # Apply subtle style
            self._loading_overlay.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(26, 26, 28, 200);
                    color: {self._connection_color};
                    font-size: 14px;
                    font-weight: 500;
                    border: 1px solid {self._connection_color};
                    border-radius: 0px;
                    padding: 20px 40px;
                }}
            """)
            # Adjust size and position
            self._loading_overlay.resize(self.size())
            self._loading_overlay.move(0, 0)
            self._loading_overlay.show()
            self._loading_overlay.raise_()

    def _hide_loading(self):
        """Hide loading overlay"""
        if self._loading_overlay:
            self._loading_overlay.hide()

    def resizeEvent(self, event):
        """Adjust loading overlay on resize"""
        super().resizeEvent(event)
        if self._loading_overlay and self._loading_overlay.isVisible():
            self._loading_overlay.resize(self.size())

    # === CLEANUP ===

    def cleanup(self):
        """Clean resources"""
        try:
            if self._sql_thread and self._sql_thread.isRunning():
                self._sql_thread.quit()
                self._sql_thread.wait()
        except RuntimeError:
            pass  # Thread was already deleted

        try:
            if self._python_thread and self._python_thread.isRunning():
                self._python_thread.quit()
                self._python_thread.wait()
        except RuntimeError:
            pass  # Thread was already deleted

        try:
            if self._connection_thread and self._connection_thread.isRunning():
                self._connection_thread.quit()
                self._connection_thread.wait()
        except RuntimeError:
            pass  # Thread was already deleted
