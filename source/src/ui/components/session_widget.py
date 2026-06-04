"""
SessionWidget - Complete widget representing a session

Contains all session components:
- Code editor (UnifiedEditor)
- BottomTabs (Results, Output, Variables)
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QLabel
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject, pyqtSlot, QMetaObject
from PyQt6.QtGui import QFont
import pandas as pd
import sys
import traceback
import logging
from io import StringIO
from typing import Optional, Dict, Any
from datetime import datetime
import time

from src.core.session import Session
from src.core.theme_manager import ThemeManager
from src.database.database_connector import _format_sql_error_for_user, _safe_exception_text, get_connector_database_context
from src.editors.block_editor import BlockEditor
from src.language import S
from src.utils.sql_parameter_service import validate_and_convert_parameters
# from src.ui.components.bottom_tabs import BottomTabs  # Removed - using global panels

logger = logging.getLogger(__name__)


DEFAULT_TAB_NOTIFICATION_COLOR = "#1e8a3e"
DEFAULT_TAB_NOTIFICATION_RULE_COLOR = "#d64545"
INTERNAL_NOTIFICATION_NAMESPACE_KEYS = {"_last_result"}


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

    def __init__(self, connector, query, sql_parameters=None):
        super().__init__()
        self.connector = connector
        self.query = query
        self.sql_parameters = sql_parameters or []

    def run(self):
        try:
            df = self.connector.execute_query(self.query, parameters=self.sql_parameters)
            self.finished.emit(df, "")
        except Exception as e:
            raw_error_msg = _safe_exception_text(e)
            # Detect if it was cancellation
            cancelled = getattr(self.connector, "_cancelled", False)
            lower_msg = raw_error_msg.lower()
            if cancelled or "cancel" in lower_msg or "abort" in lower_msg:
                self.finished.emit(None, "__CANCELLED__")
            else:
                db_type = getattr(self.connector, "db_type", "")
                error_msg = _format_sql_error_for_user(e, db_type, self.query)
                self.finished.emit(None, error_msg)

    @pyqtSlot()
    def interrupt_query(self):
        """Driver-level cancel; must run on the SQL worker thread."""
        connector = self.connector
        if connector is None:
            return
        if hasattr(connector, "interrupt_query"):
            try:
                connector.interrupt_query()
            except Exception as e:
                logger.warning(f"Error interrupting SQL query on worker thread: {e}")


class BlockAutoConnectWorker(QObject):
    """Worker to auto-connect a per-block connection in background.

    Prevents UI freeze when a block needs to connect before executing SQL.
    """

    finished = pyqtSignal(object, str)  # (connector or None, error_msg)

    def __init__(self, connection_name: str, connection_manager=None):
        super().__init__()
        self.connection_name = connection_name
        self._manager = connection_manager

    def run(self):
        try:
            from src.database.database_connector import DatabaseConnector

            manager = self._manager
            if not manager:
                from src.database.connection_manager import ConnectionManager
                manager = ConnectionManager()

            connector = manager.get_connection(self.connection_name)
            if connector and connector.is_connected():
                self.finished.emit(connector, "")
                return

            config = manager.get_connection_config(self.connection_name)
            if not config:
                self.finished.emit(None, f"Connection config not found: {self.connection_name}")
                return

            connector = DatabaseConnector()
            connector.connect(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=config.get("username", ""),
                password=config.get("password", ""),
                use_windows_auth=config.get("use_windows_auth", False),
                sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
            )

            if connector.is_connected:
                manager.connections[self.connection_name] = connector
                self.finished.emit(connector, "")
            else:
                self.finished.emit(None, f"Failed to connect: {self.connection_name}")
        except Exception as e:
            self.finished.emit(None, str(e))


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
    cursor_changed = pyqtSignal(int, int)  # line, column (1-based) - for statusbar
    block_focused = pyqtSignal(object)  # CodeBlock that gained focus (for OE tracking)
    periodic_changed = pyqtSignal(bool)  # True=started, False=stopped - for tab icon

    def __init__(self, session: Session, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)

        self.session = session
        self.theme_manager = theme_manager or ThemeManager()

        # Active workers
        self._sql_thread: Optional[QThread] = None
        self._sql_worker: Optional[SessionSqlWorker] = None
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
        self._queue_last_rows: int = 0
        self._queue_blocks_done: int = 0
        self._queue_had_error: bool = False
        self._queue_last_error: str = ""
        self._queue_last_type: str = ""  # "sql", "python", "cross"
        self._queue_last_block_name: str = ""
        self._queue_last_connection: str = ""
        self._queue_last_database: str = ""

        # Per-execution context tracking (for structured LogEntry)
        self._execution_start_time: float = 0.0
        self._current_query: str = ""
        self._current_code: str = ""
        self._current_block_index: Optional[int] = None
        self._current_connection_name_exec: str = ""
        self._current_database_name_exec: str = ""
        self._sql_execution_token: int = 0

        # Overlay de loading
        self._loading_overlay: Optional[QLabel] = None

        # Per-tab file context (authoritative source of truth for save operations)
        self.file_path: Optional[str] = None
        self._original_file_type: Optional[str] = None

        # Per-tab custom notification config (lives in memory, persisted via DPW)
        self._tab_notification_config: Optional[Dict[str, Any]] = self._normalize_tab_notification_config(
            getattr(session, "notification_config", None)
        )
        self._last_notification_delivery: Dict[str, Any] = {
            "send_external": False,
            "color": None,
            "is_tab_custom": False,
            "suppressed": False,
        }

        # Per-tab periodic execution
        self._periodic_timer: Optional[QTimer] = None
        self._periodic_interval: int = 0  # seconds
        self._periodic_active: bool = False

        self._setup_ui()
        self._connect_signals()

        # Restore blocks if they exist
        if session.blocks:
            self.editor.from_list(session.blocks)
        elif session.code:
            # Compatibility: old code without blocks
            self.editor.setText(session.code)

        # Connections are selected per block via clickable panel (no need to populate list)

    # --- Per-tab notification config ---

    def get_tab_notification_config(self) -> Optional[Dict[str, Any]]:
        """Return the per-tab notification config dict, or None."""
        return self._tab_notification_config

    def set_tab_notification_config(self, config: Optional[Dict[str, Any]]):
        """Set per-tab notification config (or None to clear)."""
        self._tab_notification_config = self._normalize_tab_notification_config(config)
        self.session.notification_config = self._tab_notification_config

    def get_result_view_state(self) -> Dict[str, Any]:
        """Return persisted results-view settings for this session."""
        info = self._get_own_panels()
        viewer = info.get("results") if info else None
        if viewer and hasattr(viewer, "get_view_state"):
            return viewer.get_view_state()
        return getattr(self.session, "result_view_state", {}) or {}

    def set_result_view_state(self, state: Optional[Dict[str, Any]]):
        """Restore persisted results-view settings for this session."""
        self.session.result_view_state = state if isinstance(state, dict) else {}
        info = self._get_own_panels()
        viewer = info.get("results") if info else None
        if viewer and hasattr(viewer, "set_session"):
            viewer.set_session(self.session)
        elif viewer and hasattr(viewer, "set_view_state"):
            viewer.set_view_state(self.session.result_view_state)

    @staticmethod
    def _normalize_tab_notification_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(rule, dict):
            return {
                "enabled": False,
                "left": "",
                "operator": "equals",
                "value": "",
                "action": "suppress",
                "action_value": DEFAULT_TAB_NOTIFICATION_RULE_COLOR,
            }

        return {
            "enabled": bool(rule.get("enabled", True)),
            "left": str(rule.get("left", "")),
            "operator": str(rule.get("operator", "equals")),
            "value": str(rule.get("value", "")),
            "action": str(rule.get("action", "suppress")),
            "action_value": str(rule.get("action_value", DEFAULT_TAB_NOTIFICATION_RULE_COLOR)),
        }

    @classmethod
    def _normalize_tab_notification_config(cls, config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not config:
            return None

        raw_rules = config.get("rules") if isinstance(config, dict) else None
        rules = []
        if isinstance(raw_rules, list):
            rules = [cls._normalize_tab_notification_rule(rule) for rule in raw_rules]

        return {
            "enabled": bool(config.get("enabled", False)),
            "title": str(config.get("title", "{{tab_name}}")),
            "message": str(config.get("message", "{{rows}} rows")),
            "color": str(config.get("color", DEFAULT_TAB_NOTIFICATION_COLOR)),
            "rules": rules,
        }

    @staticmethod
    def _try_parse_number(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

    @classmethod
    def _notification_rule_matches(cls, left: str, operator: str, right: str) -> bool:
        normalized_operator = (operator or "equals").strip().lower()
        left_text = "" if left is None else str(left)
        right_text = "" if right is None else str(right)
        left_value = left_text.strip()
        right_value = right_text.strip()

        if normalized_operator in {"equals", "eq", "=="}:
            return left_value.casefold() == right_value.casefold()
        if normalized_operator in {"not_equals", "ne", "!=", "not equals"}:
            return left_value.casefold() != right_value.casefold()
        if normalized_operator in {"contains", "includes"}:
            return right_value.casefold() in left_value.casefold()
        if normalized_operator in {"not_contains", "does not contain"}:
            return right_value.casefold() not in left_value.casefold()
        if normalized_operator in {"is_empty", "empty"}:
            return left_value == ""
        if normalized_operator in {"is_not_empty", "not_empty"}:
            return left_value != ""
        if normalized_operator in {"greater_than", "gt", ">"}:
            left_number = cls._try_parse_number(left_value)
            right_number = cls._try_parse_number(right_value)
            return left_number is not None and right_number is not None and left_number > right_number
        if normalized_operator in {"less_than", "lt", "<"}:
            left_number = cls._try_parse_number(left_value)
            right_number = cls._try_parse_number(right_value)
            return left_number is not None and right_number is not None and left_number < right_number
        return False

    def _evaluate_tab_notification_rules(self, config: Dict[str, Any], renderer) -> Dict[str, Any]:
        result = {
            "matched": False,
            "suppress": False,
            "color": None,
            "rule": None,
        }

        for rule in config.get("rules", []):
            if not rule.get("enabled", True):
                continue

            left = renderer(rule.get("left", ""))
            right = renderer(rule.get("value", ""))
            if not self._notification_rule_matches(left, rule.get("operator", "equals"), right):
                continue

            action = str(rule.get("action", "suppress")).strip().lower()
            result["matched"] = True
            result["rule"] = rule

            if action == "set_color":
                color_value = str(rule.get("action_value", "")).strip()
                if color_value:
                    result["color"] = color_value
                continue

            if action == "suppress":
                result["suppress"] = True
                return result

        return result

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
        """Define resultados no painel DESTA sessao.

        `data` pode ser:
          - um DataFrame: exibido na aba unica (comportamento padrao);
          - uma lista de (label, DataFrame): cada item vira uma aba (multi-result);
          - uma lista de DataFrames: labels automaticos sao gerados.
        Quando o viewer nao suporta multi-tab, faz fallback exibindo apenas o
        ultimo item da lista.
        """
        info = self._get_own_panels()
        viewer = info["results"] if info else None
        if not viewer:
            # Fallback: usar viewer global (compatibilidade com testes/mocks)
            main_window = self._get_main_window()
            viewer = main_window.global_results_viewer if main_window else None
        if not viewer:
            return

        if hasattr(viewer, "set_session"):
            viewer.set_session(self.session)
        if hasattr(viewer, "set_connection_color"):
            viewer.set_connection_color(self._connection_color)

        if isinstance(data, list):
            if hasattr(viewer, "display_dataframes"):
                viewer.display_dataframes(data)
            else:
                # Fallback: last item only
                last = data[-1] if data else None
                if last is None:
                    return
                if isinstance(last, tuple):
                    label, df_last = last
                else:
                    label, df_last = name, last
                viewer.display_dataframe(df_last, label)
        else:
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
            if hasattr(viewer, "set_session"):
                viewer.set_session(self.session)
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

    def _log_entry(self, entry):
        """Log a structured LogEntry to this session's output panel."""
        info = self._get_own_panels()
        output = info["output"] if info else None
        if not output:
            main_window = self._get_main_window()
            output = main_window.global_output_panel if main_window else None
        if output:
            output.add_entry(entry)
            if entry.level == "error":
                self._show_output()

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

        # Cursor position change (for statusbar)
        self.editor.cursor_changed.connect(self.cursor_changed.emit)

        # Block focus change (for Object Explorer connection tracking)
        self.editor.block_focused.connect(self.block_focused.emit)

        # Drop data file (opens import dialog)
        self.editor.file_dropped.connect(self._on_file_dropped)

        # Connect session signals
        self.session.variables_changed.connect(self._update_variables_view)

        # Chain periodic timer after execution finishes
        self.execution_finished.connect(
            lambda title, msg, success: self.schedule_next_periodic()
        )

    def _format_log(self, log_type: str, message: str = "") -> str:
        """Format log message with timestamp and type"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if message:
            return f"[{timestamp}][{log_type}] {message}"
        return f"[{timestamp}][{log_type}]"

    # === SQL EXECUTION ===

    def _get_connection_manager(self):
        """Get the shared ConnectionManager instance from MainWindow.

        Avoids creating new instances that lose track of active connections.
        Falls back to a new instance if MainWindow is not reachable.
        """
        main_window = self._get_main_window()
        if main_window and hasattr(main_window, "connection_manager"):
            return main_window.connection_manager
        from src.database.connection_manager import ConnectionManager
        return ConnectionManager()

    def _on_execute_sql(
        self,
        query: str,
        block_name: str = None,
        connection_name: str = None,
        database_name: str = None,
        sql_parameters: list = None,
    ):
        """Execute SQL in background

        Args:
            query: SQL query
            block_name: Block name (DataFrame variable name)
            connection_name: Custom connection name (None = use session default)
            database_name: Custom database name (None = use connection default)
        """
        # Determine which connection to use
        if connection_name:
            # Fetch specific connection - auto-connect in background if needed
            manager = self._get_connection_manager()
            connector = manager.get_connection(connection_name)
            if connector and connector.is_connected():
                # Already connected, proceed directly
                self._execute_sql_with_connector(
                    connector, query, block_name, connection_name, database_name, sql_parameters
                )
            else:
                # Need auto-connect in background (never block UI)
                self._set_block_busy_status(S.block.status_reconnecting)
                self.append_output(S.session_widget.connecting_block.format(name=connection_name))
                self.status_changed.emit(S.session_widget.connecting_block.format(name=connection_name))

                thread = QThread()
                worker = BlockAutoConnectWorker(connection_name, connection_manager=manager)
                worker.moveToThread(thread)

                thread.started.connect(worker.run)
                worker.finished.connect(
                    lambda conn, err, q=query, bn=block_name, cn=connection_name, dn=database_name, sp=sql_parameters:
                        self._on_auto_connect_finished(conn, err, q, bn, cn, dn, sp)
                )
                worker.finished.connect(thread.quit)
                thread.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)

                # Keep reference to prevent GC
                if not hasattr(self, "_auto_connect_threads"):
                    self._auto_connect_threads = []
                self._auto_connect_threads.append((thread, worker))
                thread.finished.connect(lambda t=thread: self._cleanup_auto_connect_thread(t))

                thread.start()
                return
        else:
            # Use session default connection
            if not self.session.is_connected:
                self.append_output(S.session_widget.no_active_connection, error=True)
                self.status_changed.emit(S.session_widget.status_no_connection)
                self._process_next_in_queue()
                return
            connector = self.session.connector
            self._execute_sql_with_connector(
                connector, query, block_name, connection_name, database_name, sql_parameters
            )

    def _cleanup_auto_connect_thread(self, thread):
        """Remove finished auto-connect thread from tracking list."""
        if hasattr(self, "_auto_connect_threads"):
            self._auto_connect_threads = [
                (t, w) for t, w in self._auto_connect_threads if t is not thread
            ]

    def _on_auto_connect_finished(self, connector, error_msg, query, block_name, connection_name, database_name, sql_parameters=None):
        """Callback when auto-connect finishes. Proceeds with SQL execution if successful."""
        if not connector or error_msg:
            self.append_output(
                S.session_widget.block_connect_error.format(name=connection_name, error=error_msg),
                error=True
            )
            self.status_changed.emit(S.session_widget.status_conn_failed)
            self._finish_block_after_switch(has_error=True)
            return

        self._execute_sql_with_connector(connector, query, block_name, connection_name, database_name, sql_parameters)

    def _get_active_execution_block(self):
        block = self.editor.get_current_executing_block()
        if block is None:
            block = self.editor.get_focused_block() or self.editor.get_last_focused_block()
        return block

    def _set_block_busy_status(self, message: str):
        block = self._get_active_execution_block()
        if block is not None:
            block.set_running_status(message)

    def _finish_block_after_switch(self, has_error: bool = False):
        block = self._get_active_execution_block()
        if block is not None:
            self.editor.mark_execution_finished(block, has_error=has_error)
        self._process_next_in_queue()

    def _disconnect_previous_sql_worker(self) -> None:
        """Detach signals from a prior SQL worker before starting a new one."""
        worker = getattr(self, "_sql_worker", None)
        if worker is None:
            return
        try:
            worker.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._sql_worker = None

    def _request_sql_cancel_interrupt(self) -> None:
        """Request SQL cancellation without blocking the UI thread."""
        if not self._sql_thread or not self._sql_thread.isRunning():
            return
        worker = getattr(self, "_sql_worker", None)
        if worker is None:
            return
        connector = getattr(worker, "connector", None)
        if connector is not None and hasattr(connector, "request_cancel"):
            try:
                connector.request_cancel()
            except Exception as e:
                logger.warning(f"Error requesting SQL cancel flag: {e}")
        QMetaObject.invokeMethod(
            worker,
            "interrupt_query",
            Qt.ConnectionType.QueuedConnection,
        )

    def _cleanup_db_switch_thread(self, thread):
        if hasattr(self, "_db_switch_threads"):
            self._db_switch_threads = [
                (t, w) for t, w in self._db_switch_threads if t is not thread
            ]

    def _start_database_switch_async(
        self,
        connector,
        database_name: str,
        *,
        connection_name: str | None,
        busy_message: str,
        on_success,
        on_error=None,
    ):
        """Switch database without blocking the UI thread."""
        from src.workers import DatabaseSwitchWorker

        self._set_block_busy_status(busy_message)
        self.status_changed.emit(S.status.switching_database.format(name=database_name))
        self.execution_started.emit()

        thread = QThread()
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.switch_success.connect(on_success)
        if on_error:
            worker.error.connect(on_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        if not hasattr(self, "_db_switch_threads"):
            self._db_switch_threads = []
        self._db_switch_threads.append((thread, worker))
        thread.finished.connect(lambda t=thread: self._cleanup_db_switch_thread(t))

        thread.start()

    def _execute_sql_with_connector(
        self,
        connector,
        query,
        block_name,
        connection_name,
        database_name,
        sql_parameters=None,
        *,
        skip_database_prep: bool = False,
    ):
        """Execute SQL query using the given connector (called after connection is ready)."""
        import re
        conn_label = connection_name or S.session_widget.default_connection_label

        if database_name and not skip_database_prep:
            self._start_database_switch_async(
                connector,
                database_name,
                connection_name=connection_name,
                busy_message=S.block.status_switching_database,
                on_success=lambda _db: self._execute_sql_with_connector(
                    connector,
                    query,
                    block_name,
                    connection_name,
                    None,
                    sql_parameters,
                    skip_database_prep=True,
                ),
                on_error=self._on_database_switch_failed,
            )
            return

        use_match = re.match(
            r"^\s*USE\s+(?:CATALOG\s+|SCHEMA\s+)?[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$",
            query, re.IGNORECASE,
        )
        if use_match:
            db_name = use_match.group(1)
            if hasattr(connector, "db_type") and connector.db_type == "databricks":
                cat_m = re.match(r"^\s*USE\s+CATALOG\s+", query, re.IGNORECASE)
                sch_m = re.match(r"^\s*USE\s+SCHEMA\s+", query, re.IGNORECASE)
                if cat_m:
                    db_name = f"CATALOG:{db_name}"
                elif sch_m:
                    db_name = f"SCHEMA:{db_name}"

            def on_use_success(_db_name: str):
                try:
                    resolved = get_connector_database_context(connector) or _db_name
                    self.session.database_context = resolved if getattr(connector, "db_type", "") == "databricks" else ""
                    conn_name = connection_name or self.session.connection_name
                    if conn_name:
                        self.connection_changed.emit(conn_name, resolved)
                    self.append_output(self._format_log("SQL", f"Database changed to: {resolved}"))
                    self.status_changed.emit(f"Database: {resolved}")
                finally:
                    self._finish_block_after_switch(has_error=False)

            self._start_database_switch_async(
                connector,
                db_name,
                connection_name=connection_name,
                busy_message=S.block.status_switching_database,
                on_success=on_use_success,
                on_error=self._on_database_switch_failed,
            )
            return

        if self._is_executing or (self._sql_thread and self._sql_thread.isRunning()):
            self._execution_queue.append(("sql", query, None, block_name, connection_name, database_name, sql_parameters))
            return

        prepared_parameters = []
        if sql_parameters:
            prepared_parameters, parameter_errors = validate_and_convert_parameters(query, sql_parameters)
            if parameter_errors:
                message = S.sql_parameters.validation_failed.format(errors="; ".join(parameter_errors))
                self.append_output(self._format_log("SQL", message), error=True)
                self.status_changed.emit(S.sql_parameters.status_invalid)
                current_block = self.editor.get_current_executing_block()
                if not current_block:
                    current_block = self.editor.get_focused_block() or self.editor.get_last_focused_block()
                self.editor.mark_execution_finished(current_block, has_error=True)
                self.session.finish_execution(False, S.sql_parameters.status_invalid)
                self._queue_had_error = True
                self._queue_last_error = message[:80]
                self._queue_last_type = "sql"
                self._queue_blocks_done += 1
                self._is_executing = False
                self._process_next_in_queue()
                return

        self._is_executing = True
        self._cancel_requested = False  # Limpar flag de cancelamento anterior
        self._sql_execution_token += 1
        execution_token = self._sql_execution_token

        # Reset notification counters for single-block execution
        if self._queue_blocks_done == 0:
            self._queue_total_rows = 0
            self._queue_last_rows = 0
            self._queue_had_error = False
            self._queue_last_error = ""
            self._queue_last_type = ""

        self.session.start_execution("sql")
        self.status_changed.emit(S.session_widget.executing_sql.format(conn_label=conn_label))
        self.execution_started.emit()  # Notify main_window to show running indicator
        block = self._get_active_execution_block()
        if block is not None:
            self.editor.mark_block_started(block)

        # Track execution context for structured logs
        self._execution_start_time = time.time()
        self._current_query = query
        self._current_block_index = self.editor.get_current_block_index()
        self._current_connection_name_exec = connection_name or self.session.connection_name or ""
        self._current_database_name_exec = database_name or ""

        self._disconnect_previous_sql_worker()

        # Criar worker e thread
        self._sql_thread = QThread()
        self._sql_worker = SessionSqlWorker(connector, query, prepared_parameters)
        self._sql_worker.moveToThread(self._sql_thread)

        # Store block_name to use in callback
        self._current_block_name = block_name

        # Store db state before execution for change detection
        self._current_connector = connector
        self._current_connection_name = connection_name or self.session.connection_name
        try:
            self._db_before_execution = get_connector_database_context(connector)
        except Exception:
            self._db_before_execution = ""

        # Register thread in session
        self.session.register_thread(self._sql_thread)

        # Conectar sinais
        self._sql_thread.started.connect(self._sql_worker.run)
        token = execution_token

        def _sql_finished_handler(df, err, _token=token):
            if _token != self._sql_execution_token:
                if self._sql_thread:
                    thread = self._sql_thread
                    self._sql_thread = None
                    try:
                        self.session.unregister_thread(thread)
                    except Exception:
                        pass
                    thread.quit()
                    thread.deleteLater()
                self._sql_worker = None
                return
            self._on_sql_finished(df, err)

        self._sql_worker.finished.connect(_sql_finished_handler)

        # Iniciar
        self._sql_thread.start()

    def _on_database_switch_failed(self, error_msg: str):
        self.append_output(self._format_log("SQL", f"ERROR: {error_msg}"), error=True)
        self.status_changed.emit(S.session_widget.status_conn_failed)
        self._finish_block_after_switch(has_error=True)

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
            self._sql_worker = None
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
        self._sql_worker = None

        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)

        # Compute execution duration
        duration_ms = (time.time() - self._execution_start_time) * 1000 if self._execution_start_time else None

        if error:
            from src.ui.components.output_panel import LogEntry, parse_error_position
            err_line, err_col = parse_error_position(error, self._current_query, "SQL")
            entry = LogEntry(
                level="error",
                log_type="SQL",
                message=f"ERROR: {error.split(chr(10))[0][:120]}",
                detail=error,
                block_index=self._current_block_index,
                block_name=self._current_block_name or "",
                line_number=err_line,
                column_number=err_col,
                duration_ms=duration_ms,
                code_snippet=self._current_query,
                connection_name=self._current_connection_name_exec,
                database_name=self._current_database_name_exec,
            )
            self._log_entry(entry)
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
                from src.ui.components.output_panel import LogEntry
                msg = S.session_widget.sql_multi_result.format(count=len(df), rows=f"{total_rows:,}")
                entry = LogEntry(
                    level="success", log_type="SQL", message=msg,
                    block_index=self._current_block_index,
                    block_name=self._current_block_name or "",
                    duration_ms=duration_ms,
                    code_snippet=self._current_query,
                    connection_name=self._current_connection_name_exec,
                    database_name=self._current_database_name_exec,
                )
                self._log_entry(entry)

                # Create variables: test, test1, test2, ...
                for i, dataframe in enumerate(df):
                    var_name = var_base if i == 0 else f"{var_base}{i}"
                    self.session.set_variable(var_name, dataframe)
                    self._log(S.session_widget.sql_var_rows.format(var_name=var_name, rows=f"{len(dataframe):,}"))

                # Display ALL DataFrames as tabs in the results grid.
                # Fallback to last-only when the viewer doesn't support multi-tab.
                last_df = df[-1]
                last_var_name = f"{var_base}{len(df) - 1}" if len(df) > 1 else var_base
                items = [
                    (var_base if i == 0 else f"{var_base}{i}", dataframe)
                    for i, dataframe in enumerate(df)
                ]
                self._set_results(items, last_var_name)
                self._update_last_notification_result(last_df)

                self.session.finish_execution(True, S.session_widget.status_sql_multi.format(count=len(df)))
                self.status_changed.emit(S.session_widget.status_sql_multi.format(count=len(df)))
                self._queue_total_rows += total_rows
                self._queue_last_rows = len(last_df)
                self._queue_blocks_done += 1
                self._queue_last_type = "sql"
            else:
                # Single DataFrame
                rows = len(df) if df is not None else 0
                var_name = var_base
                from src.ui.components.output_panel import LogEntry
                msg = S.session_widget.sql_single_result.format(rows=f"{rows:,}", var_name=var_name)
                entry = LogEntry(
                    level="success", log_type="SQL", message=msg,
                    block_index=self._current_block_index,
                    block_name=self._current_block_name or "",
                    duration_ms=duration_ms,
                    code_snippet=self._current_query,
                    connection_name=self._current_connection_name_exec,
                    database_name=self._current_database_name_exec,
                )
                self._log_entry(entry)
                self._set_results(df, var_name)
                self.session.finish_execution(True, S.session_widget.status_sql_rows.format(rows=f"{rows:,}"))
                self.status_changed.emit(S.session_widget.status_sql_rows.format(rows=f"{rows:,}"))
                self._queue_total_rows += rows
                self._queue_last_rows = rows
                self._queue_blocks_done += 1
                self._queue_last_type = "sql"

                # Save in session namespace
                self.session.set_variable(var_name, df)
                self._update_last_notification_result(df)

            # Clear block_name after use
            self._current_block_name = None

            # Check if database changed (e.g. USE command)
            # Compares db before/after execution - only emits if actually changed
            if hasattr(self, "_current_connector") and self._current_connector:
                try:
                    db_after = get_connector_database_context(self._current_connector)
                except Exception:
                    db_after = ""
                db_before = getattr(self, "_db_before_execution", "")
                conn_name = getattr(self, "_current_connection_name", "") or self.session.connection_name
                if db_after and db_before and db_after != db_before and conn_name:
                    self.session.database_context = (
                        db_after if getattr(self._current_connector, "db_type", "") == "databricks" else ""
                    )
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
            self._queue_last_rows = 0
            self._queue_had_error = False
            self._queue_last_error = ""
            self._queue_last_type = ""

        self.session.start_execution("python")
        self.status_changed.emit(S.session_widget.executing_python)
        self.execution_started.emit()  # Notify main_window to show running indicator

        # Track execution context for structured logs
        self._execution_start_time = time.time()
        self._current_code = code
        self._current_block_index = self.editor.get_current_block_index()
        self._current_connection_name_exec = ""
        self._current_database_name_exec = ""
        
        # Prepare namespace with df if exists
        namespace = self._filter_internal_notification_namespace(self.session.namespace)
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

        # Compute execution duration
        duration_ms = (time.time() - self._execution_start_time) * 1000 if self._execution_start_time else None

        if error:
            from src.ui.components.output_panel import LogEntry, parse_error_position
            err_line, err_col = parse_error_position(error, self._current_code, "PYTHON")
            entry = LogEntry(
                level="error",
                log_type="PYTHON",
                message=f"ERROR: {error.split(chr(10))[-2] if chr(10) in error else error[:120]}",
                detail=error,
                block_index=self._current_block_index,
                block_name=self._current_block_name or "",
                line_number=err_line,
                column_number=err_col,
                duration_ms=duration_ms,
                code_snippet=self._current_code,
            )
            self._log_entry(entry)
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
            notification_result = self._normalize_notification_result(result)

            if notification_result is not None:
                self._update_last_notification_result(notification_result)

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
                self.session.update_namespace(
                    self._filter_internal_notification_namespace(updated_namespace)
                )

            self.session.finish_execution(True, S.session_widget.status_python_done)
            self._queue_blocks_done += 1
            self._queue_last_type = "python"
            if notification_result is not None:
                self._queue_last_rows = len(notification_result)
                self._queue_total_rows += len(notification_result)

        # Process next in queue if exists
        self._is_executing = False
        self._process_next_in_queue()

    # === EXECUTION NOTIFICATION ===

    @staticmethod
    def _normalize_notification_result(result) -> Optional[pd.DataFrame]:
        """Convert supported results into a tabular value for notification templates."""
        if result is None:
            return None

        if isinstance(result, pd.DataFrame):
            return result

        if isinstance(result, pd.Series):
            return result.to_frame(name=result.name or "value")

        return None

    def _update_last_notification_result(self, result):
        """Persist the last tabular result used by {{result[row][col]}} templates."""
        normalized = self._normalize_notification_result(result)
        if normalized is not None:
            self.session.set_variable("_last_result", normalized)

    @staticmethod
    def _filter_internal_notification_namespace(namespace: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Remove internal notification keys from Python execution namespaces."""
        if not isinstance(namespace, dict):
            return {}

        return {
            key: value
            for key, value in namespace.items()
            if key not in INTERNAL_NOTIFICATION_NAMESPACE_KEYS
        }

    @staticmethod
    def _resolve_result_refs(template: str, last_result) -> str:
        """Replace {{result[row][col]}} references with actual values from last_result DataFrame."""
        import re
        if last_result is None:
            return template

        def _replace_match(m):
            try:
                row = int(m.group(1))
                col = int(m.group(2))
                if hasattr(last_result, 'iloc'):
                    val = last_result.iloc[row, col]
                elif isinstance(last_result, list) and row < len(last_result):
                    row_data = last_result[row]
                    if isinstance(row_data, (list, tuple)) and col < len(row_data):
                        val = row_data[col]
                    else:
                        return m.group(0)
                else:
                    return m.group(0)
                return str(val)
            except (IndexError, KeyError, TypeError, ValueError):
                return m.group(0)

        return re.sub(r'\{\{result\[(\d+)\]\[(\d+)\]\}\}', _replace_match, template)

    def _emit_queue_notification(self):
        """Emit a single notification summarizing the entire queue execution."""
        if self._queue_blocks_done == 0:
            # Nothing user-facing to report, but the run still finished —
            # emit a silent finish so the tab "running" indicator clears
            # (the notification handler skips empty title/message).
            self.execution_finished.emit("", "", True)
            return

        from PyQt6.QtCore import QSettings
        settings = QSettings("DataPyn", "DataPyn")

        # Resolve type label
        if self._queue_last_type == "sql":
            type_label = S.notification.sql_query
        elif self._queue_last_type == "python":
            type_label = S.notification.python
        else:
            type_label = S.notification.cross_syntax if hasattr(S.notification, 'cross_syntax') else "Cross-Syntax"

        # Build template variables
        tpl_vars = {
            "rows": f"{self._queue_last_rows:,}",
            "blocks": str(self._queue_blocks_done),
            "tab_name": getattr(self.session, "title", "") or "",
            "block_name": self._queue_last_block_name or "",
            "connection": self._queue_last_connection or "",
            "database": self._queue_last_database or "",
            "type": type_label,
            "error": self._queue_last_error[:80] if self._queue_last_error else "",
        }

        # Get _last_result for result[N][M] references
        last_result = self.session.get_variable("_last_result") if hasattr(self.session, 'get_variable') else None

        def _render(template: str) -> str:
            """Replace {{var}} placeholders and result[N][M] in template."""
            result = template
            for key, value in tpl_vars.items():
                result = result.replace("{{" + key + "}}", value)
            result = self._resolve_result_refs(result, last_result)
            return result

        delivery = {
            "send_external": False,
            "color": None,
            "is_tab_custom": False,
            "suppressed": False,
        }

        # Check for per-tab custom notification config
        tab_config = self._tab_notification_config
        if tab_config and tab_config.get("enabled"):
            title = _render(tab_config.get("title", "{{tab_name}}"))
            msg = _render(tab_config.get("message", "{{rows}} rows"))
            success = not self._queue_had_error
            rule_result = self._evaluate_tab_notification_rules(tab_config, _render)
            delivery = {
                "send_external": not bool(rule_result.get("suppress", False)),
                "color": rule_result.get("color") or tab_config.get("color"),
                "is_tab_custom": True,
                "suppressed": bool(rule_result.get("suppress", False)),
            }
            self._last_notification_delivery = delivery
            self.execution_finished.emit(title, msg, success)
        elif self._queue_had_error:
            default_title = S.settings.notification_default_error_title if hasattr(S.settings, 'notification_default_error_title') else "{{type}}"
            default_msg = S.settings.notification_default_error_msg if hasattr(S.settings, 'notification_default_error_msg') else "Error: {{error}}"
            title = _render(settings.value("notifications/error_title", default_title))
            msg = _render(settings.value("notifications/error_message", default_msg))
            self._last_notification_delivery = delivery
            self.execution_finished.emit(title, msg, False)
        else:
            default_title = S.settings.notification_default_success_title if hasattr(S.settings, 'notification_default_success_title') else "{{type}}"
            default_msg = S.settings.notification_default_success_msg if hasattr(S.settings, 'notification_default_success_msg') else "Complete! {{rows}} rows returned"
            title = _render(settings.value("notifications/success_title", default_title))
            msg = _render(settings.value("notifications/success_message", default_msg))
            self._last_notification_delivery = delivery
            self.execution_finished.emit(title, msg, True)

        # Reset counters
        self._queue_total_rows = 0
        self._queue_last_rows = 0
        self._queue_blocks_done = 0
        self._queue_had_error = False
        self._queue_last_error = ""
        self._queue_last_type = ""
        self._queue_last_block_name = ""
        self._queue_last_connection = ""
        self._queue_last_database = ""

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
        self._queue_last_rows = 0
        self._queue_blocks_done = 0
        self._queue_had_error = False
        self._queue_last_error = ""
        self._queue_last_type = ""
        self._queue_last_block_name = ""
        self._queue_last_connection = ""
        self._queue_last_database = ""

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

        # Cancel SQL on the worker thread (never call driver cancel() on the UI thread).
        self._request_sql_cancel_interrupt()

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
        # Current: (language, code, block, block_name, connection_name, database_name, sql_parameters)
        if len(item) >= 7:
            language, code, block, block_name, connection_name, database_name, sql_parameters = item[:7]
            if block:
                self.editor.mark_block_started(block)
        elif len(item) >= 6:
            language, code, block, block_name, connection_name, database_name = item[:6]
            sql_parameters = None
            if block:
                self.editor.mark_block_started(block)
        elif len(item) == 5:
            language, code, block, block_name, connection_name = item[:5]
            database_name = None
            sql_parameters = None
            if block:
                self.editor.mark_block_started(block)
        elif len(item) == 3:
            language, code, block = item
            block_name = None
            connection_name = None
            database_name = None
            sql_parameters = None
            if block:
                self.editor.mark_block_started(block)
        else:
            language, code = item
            block = None
            block_name = None
            connection_name = None
            database_name = None
            sql_parameters = None

        # Execute according to language
        # Track context for notification templates
        if block_name:
            self._queue_last_block_name = block_name
        if connection_name:
            self._queue_last_connection = connection_name
        elif self.session.connection_name:
            self._queue_last_connection = self.session.connection_name
        if database_name:
            self._queue_last_database = database_name

        if language == "sql":
            self._on_execute_sql(
                code,
                block_name=block_name,
                connection_name=connection_name,
                database_name=database_name,
                sql_parameters=sql_parameters,
            )
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
        self.session.notification_config = self.get_tab_notification_config()
        self.session.result_view_state = self.get_result_view_state()
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

        self.set_tab_notification_config(getattr(self.session, "notification_config", None))
        self.set_result_view_state(getattr(self.session, "result_view_state", None))

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
                db = get_connector_database_context(self.session.connector)
                self.session.database_context = (
                    db if getattr(self.session.connector, "db_type", "") == "databricks" else ""
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
                    border-radius: 12px;
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

    # === PERIODIC EXECUTION ===

    def start_periodic(self, interval_seconds: int):
        """Start periodic execution on this tab with the given interval."""
        if self._periodic_timer is None:
            self._periodic_timer = QTimer(self)
            self._periodic_timer.setSingleShot(True)
            self._periodic_timer.timeout.connect(self._periodic_fire)

        self._periodic_interval = interval_seconds
        self._periodic_active = True
        self.periodic_changed.emit(True)
        # Execute immediately, then schedule_next_periodic will chain after completion
        self._execute_all()

    def stop_periodic(self):
        """Stop periodic execution on this tab."""
        if not self._periodic_active:
            return
        self._periodic_active = False
        if self._periodic_timer:
            self._periodic_timer.stop()
        self.periodic_changed.emit(False)

    def schedule_next_periodic(self):
        """Schedule the next periodic execution (called after execution finishes)."""
        if self._periodic_active and self._periodic_timer:
            self._periodic_timer.start(self._periodic_interval * 1000)

    def _periodic_fire(self):
        """Called when the periodic timer fires. Runs all blocks again."""
        if self._periodic_active:
            self._execute_all()

    def _execute_all(self):
        """Execute all blocks in this tab (used by periodic timer)."""
        if self.editor:
            self.editor.execute_all_blocks()

    @property
    def is_periodic_active(self) -> bool:
        return self._periodic_active

    @property
    def periodic_interval(self) -> int:
        return self._periodic_interval

    # === CLEANUP ===

    def cleanup(self):
        """Clean resources"""
        # Stop periodic timer if running
        self.stop_periodic()

        if hasattr(self, "editor") and self.editor:
            self.editor.cleanup()

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
