"""
SessionWidget - Complete widget representing a session

Contains all session components:
- Code editor (UnifiedEditor)
- BottomTabs (Results, Output, Variables)
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QLabel
import weakref

from PyQt6 import sip
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
from src.database.block_connector_pool import BlockConnectorPool, connect_connector_from_config
from src.database.database_connector import (
    _format_sql_error_for_user,
    _safe_exception_text,
    get_connector_database_context,
    OperationCancelled,
    QueryBusyError,
)
from src.editors.block_editor import BlockEditor
from src.editors.sql_parameters_panel import SharedParametersPanel
from src.language import S
from src.utils.sql_parameter_service import (
    SqlParameterError,
    merge_shared_parameter_definitions,
    normalize_parameter_definition,
    prepare_python_code_with_shared_parameters,
    validate_and_convert_parameters,
)
# from src.ui.components.bottom_tabs import BottomTabs  # Removed - using global panels

logger = logging.getLogger(__name__)


DEFAULT_TAB_NOTIFICATION_COLOR = "#1e8a3e"
DEFAULT_TAB_NOTIFICATION_RULE_COLOR = "#d64545"
INTERNAL_NOTIFICATION_NAMESPACE_KEYS = {"_last_result"}


class SessionConnectionWorker(QObject):
    """Worker to connect to database in background"""

    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, session, connection_group, connection_name, password, widget=None):
        super().__init__()
        self._session_ref = weakref.ref(session)
        self._widget_ref = weakref.ref(widget) if widget is not None else None
        self.connection_group = connection_group or ""
        self.connection_name = connection_name
        self.password = password
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _ignore_ui_result(self) -> bool:
        """Tab closed or worker cancelled — do not surface connection errors."""
        if self._cancelled:
            return True
        if self._widget_ref is None:
            return False
        widget = self._widget_ref()
        if widget is None:
            return True
        try:
            return bool(getattr(widget, "_is_closing", False))
        except RuntimeError:
            return True

    def _emit_finished(self, success: bool, message: str = "") -> None:
        if self._ignore_ui_result():
            self.finished.emit(False, "")
            return
        self.finished.emit(success, message)

    def run(self):
        if self._cancelled:
            self.finished.emit(False, "")
            return
        session = self._session_ref()
        if session is None:
            self.finished.emit(False, "")
            return
        try:
            success = session.connect(self.connection_group, self.connection_name, self.password)
            if self._ignore_ui_result():
                self.finished.emit(False, "")
                return
            if success:
                self._emit_finished(
                    True,
                    f"{S.session_widget.connected_to.format(name=self.connection_name)}",
                )
            else:
                self._emit_finished(
                    False,
                    f"{S.session_widget.connect_failed.format(name=self.connection_name)}",
                )
        except Exception as e:
            if not self._ignore_ui_result():
                self._emit_finished(
                    False,
                    S.session_widget.connect_error.format(msg=str(e)),
                )
            else:
                self.finished.emit(False, "")


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
        except OperationCancelled:
            self.finished.emit(None, "__CANCELLED__")
        except QueryBusyError as e:
            self.finished.emit(None, str(e))
        except Exception as e:
            cancelled = getattr(self.connector, "_cancelled", False)
            if cancelled:
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
    """Open an isolated connector for a SQL block (never the shared connection pool)."""

    finished = pyqtSignal(object, str)  # (connector or None, error_msg)

    def __init__(
        self,
        connection_name: str,
        connection_manager=None,
        *,
        connection_group: str = "",
        database_name: str | None = None,
    ):
        super().__init__()
        self.connection_name = connection_name
        self.connection_group = connection_group or ""
        self._manager = connection_manager
        self._database_name = database_name

    def run(self):
        try:
            manager = self._manager
            if not manager:
                from src.database.connection_manager import ConnectionManager
                manager = ConnectionManager()

            config = manager.get_connection_config(self.connection_group, self.connection_name)
            if not config:
                self.finished.emit(None, f"Connection config not found: {self.connection_name}")
                return

            db_type = str(config.get("db_type", "")).lower()
            target_db = self._database_name
            connect_database = config.get("database", "")
            database_context = None
            if db_type == "databricks" and target_db:
                database_context = target_db
            elif target_db:
                connect_database = target_db

            connector = connect_connector_from_config(
                config,
                password=config.get("password", ""),
                database=connect_database,
                database_context=database_context,
            )
            if connector.is_connected():
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
    connection_drop_requested = pyqtSignal(str, str)  # group, name
    block_connection_changed = pyqtSignal(object, str)  # (CodeBlock, connection_name)
    block_database_changed = pyqtSignal(object, str)  # (CodeBlock, database_name)
    execution_started = pyqtSignal()  # Emitted when execution starts (for running indicator)
    execution_cancelling = pyqtSignal()  # Emitted when SQL cancel is in progress (tab spinner CCW)
    execution_finished = pyqtSignal(str, str, bool)  # (title, message, success)
    execution_cancelled = pyqtSignal()  # Emitted when execution is cancelled
    execution_idle = pyqtSignal()  # Emitted when workers finish after cancel
    completion_log = pyqtSignal(str, str)  # message, level - for autocomplete logging
    cursor_changed = pyqtSignal(int, int)  # line, column (1-based) - for statusbar
    block_focused = pyqtSignal(object)  # CodeBlock that gained focus (for OE tracking)
    periodic_changed = pyqtSignal(bool)  # True=started, False=stopped - for tab icon
    _persisted_variables_loaded = pyqtSignal(object)  # dict loaded off-thread (internal)
    _restore_dispatch = pyqtSignal(object)  # marshal restore payload to UI thread

    def __init__(self, session: Session, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)

        self.session = session
        self.theme_manager = theme_manager or ThemeManager()

        # Active workers
        self._sql_thread: Optional[QThread] = None
        self._sql_worker: Optional[SessionSqlWorker] = None
        self._sql_is_download: bool = False
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
        self._sql_finished_handler = None
        self._sql_stopping: bool = False
        self._sql_stop_is_cancel: bool = False
        self._sql_stopping_connector = None
        self._sql_stopping_thread = None
        self._sql_stopping_worker = None
        self._sql_stop_started_at: float = 0.0
        self._SQL_STOP_TIMEOUT_SEC: float = 15.0
        self._python_finished_handler = None
        self._db_switch_token: int = 0
        self._db_switch_threads: list = []
        self._is_closing: bool = False
        self._block_connector_pool = BlockConnectorPool()
        self._last_db_activity_at = time.monotonic()
        self._idle_reaper_timer = QTimer(self)
        self._idle_reaper_timer.timeout.connect(self._on_idle_reaper_tick)
        self._current_execution_block = None

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
        self._shared_parameters: list[dict[str, Any]] = list(getattr(session, "shared_parameters", []) or [])

        self._setup_ui()
        self._connect_signals()
        # Queued from the loader thread back onto the UI thread
        self._restore_dispatch.connect(
            self._emit_persisted_variables_loaded,
            Qt.ConnectionType.QueuedConnection,
        )
        self._persisted_variables_loaded.connect(self._apply_restored_variables)

        # Restore blocks if they exist
        if session.blocks:
            self.editor.from_list(session.blocks)
        elif session.code:
            # Compatibility: old code without blocks
            self.editor.setText(session.code)

        self._refresh_shared_parameters_from_blocks()

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
        self._editor_host = QWidget()
        editor_layout = QVBoxLayout(self._editor_host)
        editor_layout.setContentsMargins(0, 5, 0, 0)
        editor_layout.setSpacing(0)

        # Block editor (replaces UnifiedEditor)
        self.editor = BlockEditor(theme_manager=self.theme_manager)
        self.editor.bind_session(self.session)
        self.editor.bind_session_widget(self)
        editor_layout.addWidget(self.editor, 1)

        self.shared_parameters_panel = SharedParametersPanel()
        self.shared_parameters_panel.parameters_changed.connect(self._on_shared_parameters_changed)
        editor_layout.addWidget(self.shared_parameters_panel)

        self.splitter.addWidget(self._editor_host)

        # Note: BottomTabs removed - using global panels from MainWindow
        # Layout now only contains the editor (Results/Output/Variables panels are dockable)

        layout.addWidget(self.splitter)

        # Loading overlay (initially hidden)
        self._loading_overlay = QLabel(self)
        self._loading_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Style will be set dynamically in _show_loading
        self._loading_overlay.hide()
        self._loading_overlay.raise_()
        self._start_idle_reaper()

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

    def _set_results(self, data, name="result", show_panel: bool = True):
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
        if show_panel and main_window:
            main_window.show_panel("results")

    def persist_session_variables(self) -> None:
        """Snapshot DataFrame variables from the session namespace to disk (async)."""
        from src.core.session_result_storage import SessionResultStorage

        SessionResultStorage.save_from_namespace_async(
            self.session.session_id,
            self.session.namespace,
        )
        panel = self._get_variables_panel()
        if panel:
            QTimer.singleShot(800, panel.refresh_storage_column)

    def persist_session_variables_sync(self) -> bool:
        """Snapshot DataFrame variables to disk and refresh the variables panel status."""
        from src.core.session_result_storage import SessionResultStorage

        ok = SessionResultStorage.save_from_namespace(
            self.session.session_id,
            self.session.namespace,
        )
        panel = self._get_variables_panel()
        if panel:
            panel.refresh_storage_column()
        return ok

    def restore_persisted_variables(self) -> bool:
        """Restore auto-saved DataFrame variables when the app starts."""
        return self._restore_variables_from_disk(require_enabled=True)

    def restore_snapshot_from_disk(self) -> bool:
        """Restore DataFrame variables from the on-disk snapshot (manual action)."""
        return self._restore_variables_from_disk(require_enabled=False)

    def _emit_persisted_variables_loaded(self, variables: object) -> None:
        try:
            self._persisted_variables_loaded.emit(variables)
        except RuntimeError:
            pass  # widget destroyed while loading

    def _restore_variables_from_disk(self, *, require_enabled: bool) -> bool:
        """Load snapshot in a background thread; apply on the UI thread via signal."""
        import threading

        from src.core.session_result_storage import (
            SessionResultStorage,
            has_persisted_snapshot,
            is_session_result_restore_enabled,
        )

        if require_enabled and not is_session_result_restore_enabled():
            return False

        session_id = self.session.session_id
        if not has_persisted_snapshot(session_id):
            return False

        def _worker() -> None:
            try:
                variables = SessionResultStorage.load(
                    session_id,
                    require_enabled=require_enabled,
                )
            except Exception:
                variables = None
            if variables:
                try:
                    self._restore_dispatch.emit(variables)
                except RuntimeError:
                    pass  # widget destroyed while loading

        threading.Thread(
            target=_worker,
            name=f"restore-variables-{session_id}",
            daemon=True,
        ).start()
        return True

    def _apply_restored_variables(self, variables: object) -> None:
        """Apply variables loaded off-thread to the session namespace (UI thread)."""
        if self._is_closing or not isinstance(variables, dict) or not variables:
            return

        self.session.restore_dataframe_variables(variables)
        self._update_variables_view(self.session.namespace)
        panel = self._get_variables_panel()
        if panel:
            panel.refresh_storage_column()

    def refresh_variables_panel(self) -> None:
        self._update_variables_view(self.session.namespace)

    def _get_variables_panel(self):
        info = self._get_own_panels()
        panel = info.get("variables") if info else None
        if not panel:
            main_window = self._get_main_window()
            panel = main_window.global_variables_panel if main_window else None
        return panel

    def _dataframe_variables(self) -> dict:
        from src.core.session_result_storage import extract_dataframe_variables

        return dict(extract_dataframe_variables(self.session.namespace))

    def export_variable_parquet(self, name: str, value) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from src.core.session_result_storage import export_variables_to_path, _to_pandas_dataframe
        from src.design_system.app_dialogs import show_warning

        frame = _to_pandas_dataframe(value)
        if frame is None:
            show_warning(self, S.variables_panel.title_export, S.variables_panel.export_not_dataframe)
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            S.variables_panel.title_export,
            f"{name}.parquet",
            S.variables_panel.filter_parquet,
        )
        if not path:
            return
        export_variables_to_path(Path(path), {name: frame})

    def export_variables_parquet(self) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from src.core.session_result_storage import export_variables_to_path
        from src.design_system.app_dialogs import show_information, show_warning

        panel = self._get_variables_panel()
        selected = panel.get_selected_variable() if panel else None
        if selected and selected[0]:
            self.export_variable_parquet(selected[0], selected[1])
            return

        variables = self._dataframe_variables()
        if not variables:
            show_warning(self, S.variables_panel.title_export, S.variables_panel.export_none)
            return

        folder = QFileDialog.getExistingDirectory(self, S.variables_panel.title_export_folder)
        if not folder:
            return
        count = export_variables_to_path(Path(folder), variables)
        show_information(
            self,
            S.variables_panel.title_export,
            S.variables_panel.export_success.format(count=count),
        )

    def import_variables_parquet(self) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from src.core.session_result_storage import import_variables_from_path

        path, _ = QFileDialog.getOpenFileName(
            self,
            S.variables_panel.title_import,
            "",
            S.variables_panel.filter_parquet,
        )
        if not path:
            return
        self._import_variables_from_path(Path(path))

    def import_variables_folder(self) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, S.variables_panel.title_import_folder)
        if not folder:
            return
        self._import_variables_from_path(Path(folder))

    def _import_variables_from_path(self, path) -> None:
        from src.core.session_result_storage import import_variables_from_path
        from src.design_system.app_dialogs import show_information, show_warning

        loaded = import_variables_from_path(path)
        if not loaded:
            show_warning(self, S.variables_panel.title_import, S.variables_panel.import_none)
            return

        self.session.restore_dataframe_variables(loaded)
        self._update_variables_view(self.session.namespace)
        panel = self._get_variables_panel()
        if panel:
            panel.refresh_storage_column()
        show_information(
            self,
            S.variables_panel.title_import,
            S.variables_panel.import_success.format(count=len(loaded)),
        )

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
        self.editor.download_sql.connect(self._on_download_sql)
        self.editor.download_cancel_requested.connect(self._on_download_cancel_requested)
        self.editor.reveal_file_requested.connect(self._on_reveal_download_file)
        self.editor.execute_python.connect(self._on_execute_python)

        # Execution queue (multiple blocks)
        self.editor.execute_queue.connect(self._on_execute_queue)

        # Cancellation
        self.editor.cancel_execution.connect(self._on_cancel_execution)

        # Connection selection for specific block
        self.editor.select_connection_for_block.connect(self._on_block_select_connection)

        # Block connection change (to reload autocomplete)
        self.editor.block_connection_changed.connect(self._on_editor_block_connection_changed)
        self.editor.block_removed.connect(self._on_block_removed)

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

        if hasattr(self.editor, "sql_schema_requested"):
            self.editor.sql_schema_requested.connect(self._on_editor_sql_schema_requested)
        if hasattr(self.editor, "databases_requested"):
            self.editor.databases_requested.connect(self._on_editor_databases_requested)

        # Drop data file (opens import dialog)
        self.editor.file_dropped.connect(self._on_file_dropped)
        self.editor.shared_parameters_scan_needed.connect(self._refresh_shared_parameters_from_blocks)

        # Connect session signals
        self.session.variables_changed.connect(self._update_variables_view)
        self.session.variables_changed.connect(self._on_session_variables_changed)
        self.session.connection_changed.connect(self._on_session_connection_changed)

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

    def get_shared_parameters(self) -> list[dict[str, Any]]:
        if hasattr(self, "shared_parameters_panel"):
            return self.shared_parameters_panel.parameters()
        return [dict(item) for item in self._shared_parameters]

    def set_shared_parameters(self, parameters: list[dict[str, Any]] | None) -> None:
        self._shared_parameters = [dict(item) for item in (parameters or [])]
        if not hasattr(self, "shared_parameters_panel"):
            return
        if self._shared_parameters:
            self.shared_parameters_panel.set_parameters(self._shared_parameters)
        else:
            self.shared_parameters_panel.set_parameters([])
            self.shared_parameters_panel.hide()

    def _sql_parameters_for_execution(
        self,
        query: str,
        block_parameters: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        combined = list(self.get_shared_parameters()) + list(block_parameters or [])
        if not combined:
            return [], []
        return validate_and_convert_parameters(query, combined)

    def _prepare_python_code(self, code: str) -> tuple[str, list[str]]:
        shared_parameters = self.get_shared_parameters()
        if not shared_parameters:
            return code, []
        try:
            return prepare_python_code_with_shared_parameters(code, shared_parameters), []
        except SqlParameterError as exc:
            return code, [str(exc)]

    def _refresh_shared_parameters_from_blocks(self) -> None:
        if not hasattr(self, "editor"):
            return
        codes = [code for _language, code in self.editor.get_all_block_codes()]
        merged = merge_shared_parameter_definitions(
            codes,
            self._shared_parameters,
            self.editor.collect_sql_schemas(),
        )
        self._shared_parameters = [
            normalize_parameter_definition(item, index) for index, item in enumerate(merged)
        ]
        self.session.shared_parameters = self._shared_parameters
        if self._shared_parameters:
            self.shared_parameters_panel.set_parameters(self._shared_parameters)
        else:
            self.shared_parameters_panel.set_parameters([])
            self.shared_parameters_panel.hide()

    def _on_shared_parameters_changed(self, parameters: list[dict[str, Any]]) -> None:
        self._shared_parameters = [dict(item) for item in (parameters or [])]
        self.session.shared_parameters = self._shared_parameters
        self.editor.content_changed.emit()

    def _touch_db_activity(self) -> None:
        """Record database activity to defer idle disconnect."""
        self._last_db_activity_at = time.monotonic()

    def _start_idle_reaper(self) -> None:
        from src.core.connection_settings import get_idle_timeout_sec, get_reaper_interval_sec

        if get_idle_timeout_sec() <= 0:
            return
        interval_ms = max(1000, int(get_reaper_interval_sec() * 1000))
        self._idle_reaper_timer.start(interval_ms)

    def _on_idle_reaper_tick(self) -> None:
        if self._is_closing:
            return

        from src.core.connection_settings import get_idle_timeout_sec

        idle_timeout = float(get_idle_timeout_sec())
        if idle_timeout <= 0:
            return

        now = time.monotonic()
        if now - self._last_db_activity_at < idle_timeout:
            return

        self._block_connector_pool.reap_idle(idle_timeout)

        if (
            self.session.is_connected
            and not self.is_periodic_active
            and not self._is_executing
            and not self._sql_stopping
            and not self._execution_queue
        ):
            try:
                # Sleep (release the DB connection) but keep the connection
                # name so the next query auto-reconnects transparently instead
                # of erroring with "No active connection in this session".
                self.session.sleep()
            except Exception:
                pass

    def _on_editor_sql_schema_requested(self, block) -> None:
        self._touch_db_activity()
        main_window = self._get_main_window()
        if main_window is not None and hasattr(main_window, "request_lazy_schema_for_completion"):
            main_window.request_lazy_schema_for_completion(block, self)

    def _on_editor_databases_requested(self, block) -> None:
        """Empty per-block database dropdown clicked -> request server db list."""
        self._touch_db_activity()
        main_window = self._get_main_window()
        if main_window is not None and hasattr(main_window, "request_databases_for_block"):
            main_window.request_databases_for_block(block, self)

    # === SQL EXECUTION ===

    def _on_editor_block_connection_changed(self, block, connection_name: str) -> None:
        if block is not None and hasattr(block, "get_block_key"):
            self._block_connector_pool.release(block.get_block_key())
        self.block_connection_changed.emit(block, connection_name)

    def _on_block_removed(self, block) -> None:
        if block is not None and hasattr(block, "get_block_key"):
            self._block_connector_pool.release(block.get_block_key())

    def _resolve_block_database_targets(
        self, config: dict, database_name: str | None, block
    ) -> tuple[str | None, str | None]:
        """Return (connect_database, database_context) for a block."""
        target = database_name or (block.get_database_name() if block is not None else None)
        db_type = str(config.get("db_type", "")).lower()
        if db_type == "databricks":
            return config.get("database", ""), target or None
        return target or config.get("database", ""), None

    def _sql_connection_identity(self, block, connection_name=None):
        """Return (group, name) for SQL execution on a block or session default."""
        if connection_name:
            group = ""
            if block and hasattr(block, "get_connection_group"):
                group = block.get_connection_group() or ""
            return group, connection_name
        conn = self.session.connection_name
        if not conn:
            return "", None
        return self.session.connection_group or "", conn

    def _peek_sql_connector_for_block(
        self,
        block,
        connection_name: str | None,
        database_name: str | None,
    ):
        """Return a connected block connector if one is already in the pool (never connects)."""
        if block is None or not hasattr(block, "get_block_key"):
            return self.session.connector if self.session.is_connected else None

        conn_group, conn_name = self._sql_connection_identity(block, connection_name)
        if not conn_name:
            return None

        manager = self._get_connection_manager()
        config = manager.get_connection_config(conn_group, conn_name)
        if not config:
            return None

        connect_db, db_context = self._resolve_block_database_targets(
            config, database_name, block
        )
        return self._block_connector_pool.peek_connected(
            block.get_block_key(),
            conn_group,
            conn_name,
            database=connect_db,
            database_context=db_context,
        )

    def _apply_restored_block_databases(self) -> None:
        """After reconnect, load schema for blocks that keep an explicit database override."""
        editor = getattr(self, "editor", None)
        if editor is None or not hasattr(editor, "get_blocks"):
            return
        for block in editor.get_blocks():
            if not hasattr(block, "get_database_name"):
                continue
            db = block.get_database_name()
            if db:
                self.block_database_changed.emit(block, db)

    def _update_block_database_ui(self, block, database_name: str) -> None:
        """Update only the executing block's database context (not other blocks)."""
        if block is None or not database_name:
            return
        block.set_database_name(database_name)
        if hasattr(block, "db_panel"):
            block.db_panel.set_database(database_name)
        self.block_database_changed.emit(block, database_name)

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
        if self._reject_if_cancelling_sql():
            return

        self._touch_db_activity()

        block = self.editor.get_current_executing_block()
        conn_group, conn_name = self._sql_connection_identity(block, connection_name)
        if not conn_name:
            self.append_output(S.session_widget.no_active_connection, error=True)
            self.status_changed.emit(S.session_widget.status_no_connection)
            self._process_next_in_queue()
            return

        connector = self._peek_sql_connector_for_block(block, connection_name, database_name)

        if connector is None or not connector.is_connected():
            manager = self._get_connection_manager()
            self._set_block_busy_status(S.block.status_reconnecting)
            self.append_output(S.session_widget.connecting_block.format(name=conn_name))
            self.status_changed.emit(S.session_widget.connecting_block.format(name=conn_name))

            thread = QThread()
            worker = BlockAutoConnectWorker(
                conn_name,
                connection_manager=manager,
                connection_group=conn_group,
                database_name=database_name or (block.get_database_name() if block else None),
            )
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.finished.connect(
                lambda conn, err, q=query, bn=block_name, cn=connection_name, dn=database_name, sp=sql_parameters, b=block:
                    self._on_auto_connect_finished(conn, err, q, bn, cn, dn, sp, b)
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(lambda t=thread: self._cleanup_auto_connect_thread(t))

            if not hasattr(self, "_auto_connect_threads"):
                self._auto_connect_threads = []
            self._auto_connect_threads.append((thread, worker))
            self._register_background_thread(thread, worker)

            thread.start()
            return

        self._execute_sql_with_connector(
            connector, query, block_name, connection_name, database_name, sql_parameters
        )


    def _on_download_cancel_requested(self, block) -> None:
        """Cancel an in-flight streaming download from the block progress UI."""
        if not getattr(self, "_sql_is_download", False):
            return
        self._current_download_block = block
        self._on_cancel_execution()

    @staticmethod
    def _reveal_in_folder(path: str) -> None:
        import os
        import subprocess
        import sys

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        normalized = os.path.normpath(path)
        folder = os.path.dirname(normalized) or os.getcwd()
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        if opened:
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", f"/select,{normalized}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", normalized])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            logger.warning(f"Reveal failed for '{normalized}': {_safe_exception_text(e)}")

    def _on_reveal_download_file(self, file_path: str) -> None:
        """Open the OS file explorer at the downloaded file location."""
        if file_path:
            self._reveal_in_folder(file_path)

    def _on_download_sql(
        self,
        query: str,
        block_name: str = None,
        connection_name: str = None,
        database_name: str = None,
        sql_parameters: list = None,
        export_format: str = "csv",
        file_path: str = "",
        csv_options: dict | None = None,
    ):
        """Stream SQL results to a local file without loading into memory."""
        if self._reject_if_cancelling_sql():
            return

        block = self.editor.get_current_executing_block()
        conn_group, conn_name = self._sql_connection_identity(block, connection_name)
        if not conn_name:
            self.append_output(S.session_widget.no_active_connection, error=True)
            self.status_changed.emit(S.session_widget.status_no_connection)
            self.editor.mark_execution_finished(block, has_error=True)
            return

        connector = self._peek_sql_connector_for_block(block, connection_name, database_name)

        if connector is None or not connector.is_connected():
            manager = self._get_connection_manager()
            self._set_block_busy_status(S.block.status_reconnecting)
            self.append_output(S.session_widget.connecting_block.format(name=conn_name))
            self.status_changed.emit(S.session_widget.connecting_block.format(name=conn_name))

            thread = QThread()
            worker = BlockAutoConnectWorker(
                conn_name,
                connection_manager=manager,
                connection_group=conn_group,
                database_name=database_name or (block.get_database_name() if block else None),
            )
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.finished.connect(
                lambda conn, err, q=query, bn=block_name, cn=connection_name, dn=database_name,
                sp=sql_parameters, ef=export_format, fp=file_path, co=csv_options, b=block:
                    self._on_download_auto_connect_finished(
                        conn, err, q, bn, cn, dn, sp, ef, fp, co, b
                    )
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(lambda t=thread: self._cleanup_auto_connect_thread(t))

            if not hasattr(self, "_auto_connect_threads"):
                self._auto_connect_threads = []
            self._auto_connect_threads.append((thread, worker))
            self._register_background_thread(thread, worker)

            thread.start()
            return

        self._execute_download_with_connector(
            connector,
            query,
            block_name,
            connection_name,
            database_name,
            sql_parameters,
            export_format,
            file_path,
            csv_options,
        )

    def _on_download_auto_connect_finished(
        self,
        connector,
        error_msg,
        query,
        block_name,
        connection_name,
        database_name,
        sql_parameters,
        export_format,
        file_path,
        csv_options=None,
        block=None,
    ):
        if self._reject_if_cancelling_sql():
            return
        if not connector or error_msg:
            self.append_output(
                S.session_widget.block_connect_error.format(name=connection_name, error=error_msg),
                error=True,
            )
            self.status_changed.emit(S.session_widget.status_conn_failed)
            self._finish_block_after_switch(has_error=True)
            return

        self._execute_download_with_connector(
            connector,
            query,
            block_name,
            connection_name,
            database_name,
            sql_parameters,
            export_format,
            file_path,
            csv_options,
        )

    def _cleanup_auto_connect_thread(self, thread):
        """Remove finished auto-connect thread from tracking list."""
        if hasattr(self, "_auto_connect_threads"):
            self._auto_connect_threads = [
                (t, w) for t, w in self._auto_connect_threads if t is not thread
            ]

    def _on_auto_connect_finished(
        self,
        connector,
        error_msg,
        query,
        block_name,
        connection_name,
        database_name,
        sql_parameters=None,
        block=None,
    ):
        """Callback when auto-connect finishes. Proceeds with SQL execution if successful."""
        if self._reject_if_cancelling_sql():
            return
        if not connector or error_msg:
            self.append_output(
                S.session_widget.block_connect_error.format(name=connection_name, error=error_msg),
                error=True
            )
            self.status_changed.emit(S.session_widget.status_conn_failed)
            self._finish_block_after_switch(has_error=True)
            return

        self._touch_db_activity()

        conn_group, conn_name = self._sql_connection_identity(block, connection_name)
        if block is not None and conn_name and hasattr(block, "get_block_key"):
            self._block_connector_pool.register(
                block.get_block_key(), conn_group, conn_name, connector
            )

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

    def _finish_block_after_switch(self, has_error: bool = False, *, resume_queue: bool = True):
        block = self._get_active_execution_block()
        if block is not None:
            self.editor.mark_execution_finished(block, has_error=has_error)
        if resume_queue and not self._is_executing:
            self._process_next_in_queue()

    def _sql_thread_is_active(self) -> bool:
        thread = getattr(self, "_sql_thread", None)
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            self._sql_thread = None
            self._sql_worker = None
            self._sql_finished_handler = None
            return False

    def _python_thread_is_active(self) -> bool:
        thread = getattr(self, "_python_thread", None)
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            self._python_thread = None
            self._python_worker = None
            self._python_finished_handler = None
            return False

    def _disconnect_previous_sql_worker(self) -> None:
        """Detach SQL worker signals before starting a new run (e.g. after DB switch)."""
        self._detach_sql_worker_handler()

    def _register_background_thread(self, thread, worker=None) -> None:
        """Parent thread on MainWindow so it cannot be destroyed while running."""
        main = self.window()
        if main is not None and hasattr(main, "_adopt_background_thread"):
            main._adopt_background_thread(thread, worker)

    def _orphan_background_thread(self, thread, worker=None) -> None:
        """Detach from tab; MainWindow keeps thread alive until it stops."""
        if thread is None:
            return
        main = self.window()
        if (
            main is not None
            and main is not self
            and hasattr(main, "_orphan_background_thread")
        ):
            main._orphan_background_thread(thread, worker)
            return
        from src.utils.qt_threading import kick_qthread_stop

        kick_qthread_stop(thread, worker)

    def _orphan_running_threads(self) -> None:
        """Orphan all in-flight workers when the tab closes or cleans up."""
        for thread_attr, worker_attr in (
            ("_sql_thread", "_sql_worker"),
            ("_python_thread", "_python_worker"),
        ):
            thread = getattr(self, thread_attr, None)
            worker = getattr(self, worker_attr, None)
            setattr(self, thread_attr, None)
            setattr(self, worker_attr, None)
            if thread is not None:
                self._orphan_background_thread(thread, worker)

        for thread, worker in list(getattr(self, "_auto_connect_threads", []) or []):
            self._orphan_background_thread(thread, worker)
        self._auto_connect_threads = []

        pending = list(getattr(self, "_db_switch_threads", []) or [])
        self._db_switch_threads = []
        for thread, worker in pending:
            self._orphan_background_thread(thread, worker)

    def _detach_sql_worker_handler(self) -> None:
        worker = getattr(self, "_sql_worker", None)
        handler = getattr(self, "_sql_finished_handler", None)
        if worker is not None and handler is not None:
            try:
                worker.finished.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        self._sql_finished_handler = None

    def _detach_python_worker_handler(self) -> None:
        worker = getattr(self, "_python_worker", None)
        handler = getattr(self, "_python_finished_handler", None)
        if worker is not None and handler is not None:
            try:
                worker.finished.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        self._python_finished_handler = None

    def _maybe_emit_execution_idle(self) -> None:
        if not self.is_execution_busy() and not self._is_closing:
            self.execution_idle.emit()

    def _on_sql_thread_terminated(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread):
            return
        if thread is getattr(self, "_sql_thread", None):
            self._sql_thread = None
            self._sql_worker = None
            self._sql_finished_handler = None
            self._sql_is_download = False
        elif self._sql_stopping and thread is getattr(self, "_sql_stopping_thread", None):
            self._sql_stopping_thread = None
            self._sql_stopping_worker = None
        try:
            self.session.unregister_thread(thread)
        except Exception:
            pass
        if not self._is_executing and not self._is_closing and not self._sql_stopping:
            QTimer.singleShot(0, self._process_next_in_queue)
        if self._sql_stopping:
            QTimer.singleShot(0, self._schedule_sql_stop_finalize)
        self._maybe_emit_execution_idle()

    def _on_python_thread_terminated(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread):
            return
        if thread is getattr(self, "_python_thread", None):
            self._python_thread = None
            self._python_worker = None
            self._python_finished_handler = None
        try:
            self.session.unregister_thread(thread)
        except Exception:
            pass
        if not self._is_executing and not self._is_closing:
            QTimer.singleShot(0, self._process_next_in_queue)
        self._maybe_emit_execution_idle()

    def _release_sql_slot(self) -> None:
        """Drop widget refs to the SQL worker; thread may finish in background."""
        thread = getattr(self, "_sql_thread", None)
        worker = getattr(self, "_sql_worker", None)
        self._sql_thread = None
        self._sql_worker = None
        self._sql_finished_handler = None
        if thread is not None:
            self._orphan_background_thread(thread, worker)

    def _detach_stale_sql_thread(self) -> None:
        """Orphan a cancelled SQL thread that is still stopping."""
        thread = getattr(self, "_sql_thread", None)
        if thread is None:
            return
        try:
            if not thread.isRunning():
                self._sql_thread = None
                self._sql_worker = None
                self._sql_finished_handler = None
                return
        except RuntimeError:
            self._sql_thread = None
            self._sql_worker = None
            self._sql_finished_handler = None
            return
        worker = getattr(self, "_sql_worker", None)
        self._release_sql_slot()
        connector = getattr(worker, "connector", None) if worker is not None else None
        if connector is not None and hasattr(connector, "request_cancel"):
            try:
                connector.request_cancel()
            except Exception:
                pass

    def _stop_sql_execution(self) -> None:
        """Cancel the in-flight SQL worker without destroying a running QThread."""
        self._sql_execution_token += 1
        self._request_sql_cancel_interrupt()

    def _stop_python_execution(self) -> None:
        """Cancel the in-flight Python worker without destroying a running QThread."""
        self._detach_python_worker_handler()
        thread = getattr(self, "_python_thread", None)
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass

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
        if hasattr(worker, "cancel"):
            try:
                worker.cancel()
            except Exception:
                pass
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

    @staticmethod
    def _normalize_database_name(name: str) -> str:
        return str(name or "").strip().strip("[]`\"").lower()

    def _connector_matches_database(self, connector, database_name: str) -> bool:
        """True when the connector is already using the requested database context."""
        target = self._normalize_database_name(database_name)
        if not target:
            return True
        current = self._normalize_database_name(get_connector_database_context(connector))
        if not current:
            return False
        if current == target:
            return True
        if current.endswith(f".{target}") or target.endswith(f".{current}"):
            return True
        current_tail = current.split(".")[-1]
        target_tail = target.split(".")[-1]
        return current_tail == target_tail and ("." in current or "." in target)

    def _cancel_pending_db_switches(self) -> None:
        """Stop in-flight database switches without blocking the UI thread."""
        self._db_switch_token += 1
        pending = list(getattr(self, "_db_switch_threads", []) or [])
        self._db_switch_threads = []
        for thread, worker in pending:
            self._orphan_background_thread(thread, worker)

    def is_tab_cancellation_pending(self) -> bool:
        """True while a user-initiated SQL cancel is still stopping on this tab."""
        return self._sql_stopping and self._sql_stop_is_cancel

    def _reject_if_cancelling_sql(self) -> bool:
        """Block new execution while SQL cancel is in progress."""
        if not self.is_tab_cancellation_pending():
            return False
        self.status_changed.emit(S.session_widget.status_sql_cancelling)
        return True

    def is_execution_busy(self) -> bool:
        """True while SQL/Python runs or a database switch is still pending."""
        if self._sql_stopping:
            return True
        if self._is_executing:
            return True
        if self._sql_thread_is_active() or self._python_thread_is_active():
            return True
        for thread, _worker in getattr(self, "_db_switch_threads", []) or []:
            try:
                if thread.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

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

        if self._cancel_requested or self._is_closing:
            return

        self._db_switch_token += 1
        switch_token = self._db_switch_token

        self._set_block_busy_status(busy_message)
        self.status_changed.emit(S.status.switching_database.format(name=database_name))

        thread = QThread()
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        def _guarded_success(db_name: str):
            if switch_token != self._db_switch_token or self._cancel_requested or self._is_closing:
                self._finish_block_after_switch(has_error=False, resume_queue=False)
                return
            on_success(db_name)

        def _guarded_error(error_msg: str):
            if switch_token != self._db_switch_token or self._cancel_requested or self._is_closing:
                self._finish_block_after_switch(has_error=True, resume_queue=False)
                return
            if on_error:
                on_error(error_msg)

        thread.started.connect(worker.run)
        worker.switch_success.connect(_guarded_success)
        if on_error:
            worker.error.connect(_guarded_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda t=thread: self._cleanup_db_switch_thread(t))

        if not hasattr(self, "_db_switch_threads"):
            self._db_switch_threads = []
        self._db_switch_threads.append((thread, worker))
        self._register_background_thread(thread, worker)

        thread.start()

    def _execute_download_with_connector(
        self,
        connector,
        query,
        block_name,
        connection_name,
        database_name,
        sql_parameters=None,
        export_format: str = "csv",
        file_path: str = "",
        csv_options=None,
        *,
        skip_database_prep: bool = False,
    ):
        """Stream SQL results to file using the given connector."""
        if self._reject_if_cancelling_sql():
            return

        import re
        from src.workers import QueryDownloadWorker

        self._current_execution_block = self._get_active_execution_block()
        conn_label = connection_name or S.session_widget.default_connection_label

        if database_name and not skip_database_prep:
            if self._connector_matches_database(connector, database_name):
                self._execute_download_with_connector(
                    connector,
                    query,
                    block_name,
                    connection_name,
                    None,
                    sql_parameters,
                    export_format,
                    file_path,
                    csv_options,
                    skip_database_prep=True,
                )
            else:
                self._start_database_switch_async(
                    connector,
                    database_name,
                    connection_name=connection_name,
                    busy_message=S.block.status_switching_database,
                    on_success=lambda _db: self._execute_download_with_connector(
                        connector,
                        query,
                        block_name,
                        connection_name,
                        None,
                        sql_parameters,
                        export_format,
                        file_path,
                        csv_options,
                        skip_database_prep=True,
                    ),
                    on_error=self._on_database_switch_failed,
                )
            return

        use_match = re.match(
            r"^\s*USE\s+(?:CATALOG\s+|SCHEMA\s+)?[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$",
            query,
            re.IGNORECASE,
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
                    self._update_block_database_ui(self._current_execution_block, resolved)
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

        if self._sql_thread_is_active() or self._is_executing:
            self.append_output(
                getattr(S.block, "download_busy", "Another query is running. Try again when it finishes."),
                error=True,
            )
            self.editor.mark_execution_finished(self._get_active_execution_block(), has_error=True)
            return

        if getattr(connector, "is_query_busy", lambda: False)():
            self.append_output(
                getattr(S.block, "download_busy", "Another query is running. Try again when it finishes."),
                error=True,
            )
            self.editor.mark_execution_finished(self._get_active_execution_block(), has_error=True)
            return

        prepared_parameters = []
        combined_parameters = list(self.get_shared_parameters()) + list(sql_parameters or [])
        if combined_parameters:
            prepared_parameters, parameter_errors = self._sql_parameters_for_execution(query, sql_parameters)
            if parameter_errors:
                message = S.sql_parameters.validation_failed.format(errors="; ".join(parameter_errors))
                self.append_output(self._format_log("SQL", message), error=True)
                self.status_changed.emit(S.sql_parameters.status_invalid)
                current_block = self.editor.get_current_executing_block()
                self.editor.mark_execution_finished(current_block, has_error=True)
                return

        self._is_executing = True
        self._sql_is_download = True
        self._cancel_requested = False
        self._sql_execution_token += 1
        execution_token = self._sql_execution_token

        self.session.start_execution("sql")
        download_status = getattr(S.block, "download_running", "Downloading… ({conn})")
        self.status_changed.emit(download_status.format(conn=conn_label))
        self.execution_started.emit()
        block = self._get_active_execution_block()
        self._current_download_block = block
        if block is not None:
            self.editor.mark_block_started(block)
            from pathlib import Path as _Path

            block.clear_downloads()
            preparing = getattr(S.block, "download_preparing", "Preparing download...")
            block.start_download(1, _Path(file_path).name or preparing)

        self._execution_start_time = time.time()
        self._current_query = query
        self._current_block_index = self.editor.get_current_block_index()
        self._current_connection_name_exec = connection_name or self.session.connection_name or ""
        self._current_database_name_exec = database_name or ""
        self._current_block_name = block_name
        self._current_connector = connector
        self._current_connection_name = connection_name or self.session.connection_name
        self._current_download_path = file_path
        self._current_download_format = export_format
        self._current_download_csv_options = csv_options

        thread = QThread()
        worker = QueryDownloadWorker(
            connector,
            query,
            file_path,
            export_format,
            prepared_parameters,
            csv_options,
        )
        worker.moveToThread(thread)
        self._sql_thread = thread
        self._sql_worker = worker

        token = execution_token

        def _download_progress(file_index: int, rows: int, bytes_written: int, _token=token) -> None:
            if _token != self._sql_execution_token:
                return
            elapsed = max(time.time() - self._execution_start_time, 0.001)
            rate_mbps = (bytes_written / (1024 * 1024)) / elapsed
            active_block = getattr(self, "_current_download_block", None) or self._get_active_execution_block()
            if active_block is not None and hasattr(active_block, "update_download_progress"):
                active_block.update_download_progress(file_index, rows, bytes_written, rate_mbps)
            template = getattr(S.block, "download_progress", "Downloading… {rows:,} rows (file {file})")
            self.status_changed.emit(template.format(rows=rows, file=file_index))

        def _download_file_started(file_index: int, filename: str, _token=token) -> None:
            if _token != self._sql_execution_token:
                return
            active_block = getattr(self, "_current_download_block", None) or self._get_active_execution_block()
            if active_block is not None and hasattr(active_block, "start_download"):
                active_block.start_download(file_index, filename)

        def _download_total(file_index: int, total: int, _token=token) -> None:
            if _token != self._sql_execution_token:
                return
            active_block = getattr(self, "_current_download_block", None) or self._get_active_execution_block()
            if active_block is not None and hasattr(active_block, "set_download_total"):
                active_block.set_download_total(file_index, total)

        def _download_finished_handler(result, err, _token=token):
            if _token != self._sql_execution_token:
                return
            self._on_download_finished(result, err)

        self._sql_finished_handler = _download_finished_handler
        thread.started.connect(worker.run)
        worker.progress.connect(_download_progress)
        worker.file_started.connect(_download_file_started)
        worker.total_ready.connect(_download_total)
        worker.download_finished.connect(_download_finished_handler)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._on_sql_thread_terminated)

        self.session.register_thread(thread)
        self._register_background_thread(thread, worker)
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
        if self._reject_if_cancelling_sql():
            return

        self._touch_db_activity()

        import re
        self._current_execution_block = self._get_active_execution_block()
        conn_label = connection_name or S.session_widget.default_connection_label

        if database_name and not skip_database_prep:
            if self._connector_matches_database(connector, database_name):
                self._execute_sql_with_connector(
                    connector,
                    query,
                    block_name,
                    connection_name,
                    None,
                    sql_parameters,
                    skip_database_prep=True,
                )
            else:
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
                    self._update_block_database_ui(self._current_execution_block, resolved)
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

        if self._sql_thread_is_active():
            if self._is_executing:
                self._execution_queue.append(
                    ("sql", query, None, block_name, connection_name, database_name, sql_parameters)
                )
                return
            self._detach_stale_sql_thread()

        if getattr(connector, "is_query_busy", lambda: False)():
            self._execution_queue.append(
                ("sql", query, None, block_name, connection_name, database_name, sql_parameters)
            )
            if not self._sql_stopping:
                self._sql_stopping = True
                self._sql_stop_is_cancel = False
                self._arm_sql_stop_watch(None, None, connector)
                self.status_changed.emit(S.session_widget.status_sql_waiting_previous)
                self._schedule_sql_stop_finalize()
            return

        if self._is_executing:
            self._execution_queue.append(("sql", query, None, block_name, connection_name, database_name, sql_parameters))
            return

        prepared_parameters = []
        combined_parameters = list(self.get_shared_parameters()) + list(sql_parameters or [])
        if combined_parameters:
            prepared_parameters, parameter_errors = self._sql_parameters_for_execution(query, sql_parameters)
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

        # Criar worker e thread
        thread = QThread()
        worker = SessionSqlWorker(connector, query, prepared_parameters)
        worker.moveToThread(thread)
        self._sql_thread = thread
        self._sql_worker = worker

        # Store block_name to use in callback
        self._current_block_name = block_name

        # Store db state before execution for change detection
        self._current_connector = connector
        self._current_connection_name = connection_name or self.session.connection_name
        try:
            self._db_before_execution = get_connector_database_context(connector)
        except Exception:
            self._db_before_execution = ""

        token = execution_token

        def _sql_finished_handler(df, err, _token=token):
            if _token != self._sql_execution_token:
                return
            self._on_sql_finished(df, err)

        self._sql_finished_handler = _sql_finished_handler
        thread.started.connect(worker.run)
        worker.finished.connect(_sql_finished_handler)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._on_sql_thread_terminated)

        self.session.register_thread(thread)
        self._register_background_thread(thread, worker)
        thread.start()

    def _on_database_switch_failed(self, error_msg: str):
        self.append_output(self._format_log("SQL", f"ERROR: {error_msg}"), error=True)
        self.status_changed.emit(S.session_widget.status_conn_failed)
        self._finish_block_after_switch(has_error=True)

    def _on_sql_finished(self, df: Optional[pd.DataFrame], error: str):
        """Callback when SQL finishes"""
        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()

        # If cancelled, ignore result (UI already cleaned by cancel)
        if error == "__CANCELLED__" or self._cancel_requested:
            if current_block is not None and hasattr(current_block, "clear_downloads"):
                current_block.clear_downloads()
            self._current_download_block = None
            self._is_executing = False
            if self._sql_stopping:
                self._schedule_sql_stop_finalize()
            return

        self.editor.mark_execution_finished(current_block)

        # Compute execution duration
        duration_ms = (time.time() - self._execution_start_time) * 1000 if self._execution_start_time else None

        # Defensive: worker emitted no DataFrame and no error message (e.g. a
        # driver/path that swallows the failure). Synthesize an error so the UI
        # does not silently keep the previous result on the grid.
        if df is None and not error:
            error = getattr(
                S.session_widget,
                "sql_no_result_error",
                "Query returned no result and no error was reported.",
            )

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
            # Clear the results grid so stale rows from the previous query do
            # not linger while the error is shown in the output panel.
            info = self._get_own_panels()
            viewer = info.get("results") if info else None
            if viewer is not None and hasattr(viewer, "clear"):
                try:
                    viewer.clear()
                except Exception:
                    pass
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
                if db_after and db_before and db_after != db_before:
                    target_block = self._current_execution_block or self.editor.get_current_executing_block()
                    self._update_block_database_ui(target_block, db_after)

        self._is_executing = False
        self._current_execution_block = None

    def _on_download_finished(self, result, error: str) -> None:
        """Callback when a streaming download finishes."""
        self._sql_is_download = False
        current_block = getattr(self, "_current_download_block", None) or self.editor.get_current_executing_block()
        duration_ms = (time.time() - self._execution_start_time) * 1000 if self._execution_start_time else None

        if error == "__CANCELLED__" or self._cancel_requested:
            if current_block is not None and hasattr(current_block, "clear_downloads"):
                current_block.clear_downloads()
            self._current_download_block = None
            self._is_executing = False
            if self._sql_stopping:
                self._schedule_sql_stop_finalize()
            return

        if error:
            if current_block is not None and hasattr(current_block, "clear_downloads"):
                current_block.clear_downloads()
            self._current_download_block = None
            self.editor.mark_execution_finished(current_block, has_error=True)
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
            self._show_output()
        elif result is None or (not getattr(result, "files", None) and not getattr(result, "errors", None)):
            if current_block is not None and hasattr(current_block, "clear_downloads"):
                current_block.clear_downloads()
            self._current_download_block = None
            self.editor.mark_execution_finished(current_block)
            msg = getattr(S.block, "download_no_rows", "No row results to download.")
            self.append_output(self._format_log("SQL", msg))
            self.session.finish_execution(True, msg)
            self.status_changed.emit(msg)
        else:
            from src.ui.components.output_panel import LogEntry

            total_rows = getattr(result, "total_rows", 0) or 0
            file_count = len(result.files)
            paths = [str(p) for p in result.files]
            summary = getattr(S.block, "download_success", "Saved {files} file(s), {rows:,} rows")
            msg = summary.format(files=file_count, rows=total_rows)
            if result.errors:
                msg = f"{msg} ({len(result.errors)} warning(s))"

            if current_block is not None and hasattr(current_block, "finish_download"):
                for idx, path in enumerate(result.files, start=1):
                    row_count = result.row_counts[idx - 1] if idx - 1 < len(result.row_counts) else 0
                    current_block.finish_download(idx, str(path), row_count)
            self._current_download_block = None
            self.editor.mark_execution_finished(current_block)

            entry = LogEntry(
                level="success",
                log_type="SQL",
                message=msg,
                detail="\n".join(paths),
                block_index=self._current_block_index,
                block_name=self._current_block_name or "",
                duration_ms=duration_ms,
                code_snippet=self._current_query,
                connection_name=self._current_connection_name_exec,
                database_name=self._current_database_name_exec,
            )
            self._log_entry(entry)
            self.append_output(self._format_log("SQL", msg))
            self.session.finish_execution(True, msg)
            self.status_changed.emit(msg)

            try:
                from src.ui.components.toast_notification import ToastManager

                ToastManager.notify(
                    getattr(S.block, "download_toast_title", "Download complete"),
                    msg,
                    success=True,
                )
            except Exception:
                pass

            csv_options = getattr(self, "_current_download_csv_options", None) or {}
            if csv_options.get("open_folder") and paths:
                self._reveal_in_folder(paths[0])

        self._is_executing = False
        self._current_execution_block = None
        self._process_next_in_queue()

    # === PYTHON EXECUTION ===

    def _on_execute_python(self, code: str):
        """Execute Python in background"""
        if self._reject_if_cancelling_sql():
            return
        if self._python_thread_is_active():
            self._execution_queue.append(("python", code))
            return
        if self._is_executing:
            self._execution_queue.append(("python", code))
            return

        prepared_code, parameter_errors = self._prepare_python_code(code)
        if parameter_errors:
            message = S.sql_parameters.validation_failed.format(errors="; ".join(parameter_errors))
            self.append_output(self._format_log("Python", message), error=True)
            self.status_changed.emit(S.sql_parameters.status_invalid)
            current_block = self.editor.get_current_executing_block()
            if not current_block:
                current_block = self.editor.get_focused_block() or self.editor.get_last_focused_block()
            self.editor.mark_execution_finished(current_block, has_error=True)
            self.session.finish_execution(False, S.sql_parameters.status_invalid)
            self._is_executing = False
            self._process_next_in_queue()
            return
        code = prepared_code

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

        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression)
        worker.moveToThread(thread)
        self._python_thread = thread
        self._python_worker = worker

        def _python_finished_handler(result, output, error, ns, figures=None):
            self._on_python_finished_adapted(result, output, error, ns, figures or [])

        self._python_finished_handler = _python_finished_handler
        thread.started.connect(worker.run)
        worker.finished.connect(_python_finished_handler)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._on_python_thread_terminated)

        self.session.register_thread(thread)
        self._register_background_thread(thread, worker)
        thread.start()

    def _on_python_finished_adapted(self, result, output: str, error: str, namespace: dict, figures: list = None):
        """Adapter to use centralized PythonWorker"""
        # Call original callback with updated namespace
        self._on_python_finished(result, output, error, namespace, figures or [])

    def _on_python_finished(self, result, output: str, error: str, updated_namespace: dict, figures: list = None):
        """Callback when Python finishes"""
        figures = figures or []

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

        self._is_executing = False

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

        self.persist_session_variables()

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
        if self._reject_if_cancelling_sql():
            return

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

    def _schedule_sql_stop_finalize(self) -> None:
        """Poll until the SQL worker thread finishes, then finalize."""
        if not self._sql_stopping:
            return
        if self._sql_stop_timed_out():
            thread = getattr(self, "_sql_stopping_thread", None)
            thread_alive = False
            if thread is not None:
                try:
                    thread_alive = thread.isRunning()
                except RuntimeError:
                    thread_alive = False
            connector = self._sql_stopping_connector
            if thread_alive and connector is not None:
                connector._abandoned = True
                logger.warning(
                    "SQL cancel timed out with worker still running; connection marked abandoned"
                )
                self._finalize_sql_stop()
                return
            logger.warning("SQL cancel finalize timed out; forcing cleanup")
            self._force_release_stopping_query_lock()
            self._finalize_sql_stop()
            return
        if self._sql_stop_ready_to_finalize():
            self._finalize_sql_stop()
            return
        QTimer.singleShot(100, self._schedule_sql_stop_finalize)

    def _sql_stop_timed_out(self) -> bool:
        started = getattr(self, "_sql_stop_started_at", 0.0) or 0.0
        if started <= 0:
            return False
        return (time.time() - started) >= getattr(self, "_SQL_STOP_TIMEOUT_SEC", 15.0)

    def _sql_stop_ready_to_finalize(self) -> bool:
        """Finalize once the worker thread has stopped (lock should be released in finally)."""
        thread = getattr(self, "_sql_stopping_thread", None)
        if thread is not None:
            try:
                return not thread.isRunning()
            except RuntimeError:
                return True

        connector = self._sql_stopping_connector
        if connector is not None:
            try:
                return not connector.is_query_busy()
            except Exception:
                return True
        return True

    def _force_release_stopping_query_lock(self) -> None:
        connector = self._sql_stopping_connector
        if connector is None:
            return
        lock = getattr(connector, "_query_lock", None)
        if lock is None:
            return
        try:
            if lock.locked():
                lock.release()
        except RuntimeError:
            pass

    def _arm_sql_stop_watch(self, thread, worker, connector) -> None:
        """Keep watching an orphaned SQL worker until cancel cleanup can finish."""
        self._sql_stopping_thread = thread
        self._sql_stopping_worker = worker
        self._sql_stopping_connector = connector
        self._sql_stop_started_at = time.time()

        def _bump_finalize(*_args):
            if self._sql_stopping:
                QTimer.singleShot(0, self._schedule_sql_stop_finalize)

        if worker is not None:
            try:
                worker.finished.connect(
                    _bump_finalize,
                    Qt.ConnectionType.SingleShotConnection,
                )
            except (TypeError, RuntimeError):
                pass
        if thread is not None:
            try:
                thread.finished.connect(
                    _bump_finalize,
                    Qt.ConnectionType.SingleShotConnection,
                )
            except (TypeError, RuntimeError):
                pass

    def _clear_sql_stop_watch(self) -> None:
        self._sql_stopping_thread = None
        self._sql_stopping_worker = None
        self._sql_stopping_connector = None
        self._sql_stop_started_at = 0.0

    def _finalize_sql_stop(self, *, cancelled: bool | None = None) -> None:
        """Finish SQL stop/cancel UI once the worker thread has stopped."""
        if not self._sql_stopping:
            return
        if cancelled is None:
            cancelled = self._sql_stop_is_cancel

        if not self._sql_stop_ready_to_finalize() and not self._sql_stop_timed_out():
            self._schedule_sql_stop_finalize()
            return

        was_stopping = self._sql_stopping
        self._sql_stopping = False
        self._sql_stop_is_cancel = False
        self._clear_sql_stop_watch()

        if cancelled:
            self._complete_user_cancel()
        elif was_stopping and not self._is_executing and not self._is_closing:
            QTimer.singleShot(0, self._process_next_in_queue)
        self._maybe_emit_execution_idle()

    def _complete_user_cancel(self) -> None:
        """Apply cancelled UI/output after SQL worker and lock are idle."""
        self._is_executing = False
        self._current_block_name = None

        if hasattr(self.editor, "mark_execution_cancelled"):
            self.editor.mark_execution_cancelled()
        else:
            self.editor.mark_execution_finished()

        self.append_output(
            self._format_log(
                "CANCELLED",
                S.session_widget.cancelled_output.replace("[CANCELLED] ", ""),
            ),
            error=True,
        )
        self._show_output()
        self.status_changed.emit(S.session_widget.status_cancelled)
        self.session.finish_execution(False, S.session_widget.execution_cancelled)
        self.execution_cancelled.emit()

    def _on_cancel_execution(self):
        """Cancel current execution and clear queue.

        Non-blocking: sends cancellation signal and returns immediately.
        SQL cleanup finishes once the worker thread and query lock are idle.
        """
        self._cancel_requested = True
        self._execution_queue.clear()
        self._cancel_pending_db_switches()

        worker = getattr(self, "_sql_worker", None)
        stopping_thread = getattr(self, "_sql_thread", None)
        connector = getattr(worker, "connector", None) if worker is not None else None

        self._stop_sql_execution()
        had_sql_worker = worker is not None or stopping_thread is not None
        self._release_sql_slot()
        self._stop_python_execution()

        self._is_executing = False
        self._current_block_name = None

        if had_sql_worker and connector is not None:
            self._sql_stopping = True
            self._sql_stop_is_cancel = True
            self._arm_sql_stop_watch(stopping_thread, worker, connector)
            if hasattr(self.editor, "mark_execution_cancelling"):
                self.editor.mark_execution_cancelling()
            self.status_changed.emit(S.session_widget.status_sql_cancelling)
            self.execution_cancelling.emit()
            self._schedule_sql_stop_finalize()
        else:
            self._complete_user_cancel()

        self._cancel_requested = False

    def _process_next_in_queue(self):
        """Process next item in execution queue"""
        if self._sql_stopping:
            return

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

        if block is not None:
            self.editor._current_executing_block = block

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

    def _on_session_variables_changed(self, _namespace: dict):
        """Refresh Monaco offline completions when session variables change."""
        if hasattr(self.editor, "refresh_completion_context"):
            self.editor.refresh_completion_context()

    def _on_session_connection_changed(self, _connection_name: str = ""):
        """Connection metadata (db_*) affects Python autocomplete."""
        self._update_variables_view(self.session.namespace)
        if hasattr(self.editor, "refresh_completion_context"):
            self.editor.refresh_completion_context()

    def _update_variables_view(self, namespace: dict):
        """Update variables view, including database variables"""
        visible_vars = {
            k: v
            for k, v in self.session.effective_namespace().items()
            if not k.startswith("_") and k not in ("pd", "np", "plt")
        }

        self._set_variables(visible_vars)

    def _inject_db_variables(self, variables: dict):
        """Injeta variaveis de banco de dados (delega para Session)."""
        self.session.enrich_connection_variables(variables)

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
        self.session.shared_parameters = self._shared_parameters
        if self.session.is_connected:
            db = get_connector_database_context(self.session.connector)
            if db:
                self.session.database_context = db
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
        self.set_shared_parameters(getattr(self.session, "shared_parameters", []) or [])
        self._refresh_shared_parameters_from_blocks()

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
                group, conn_name, config = dialog.get_result()
                if conn_name:
                    db_type = config.get("db_type", "mysql") if config else "mysql"
                    color = config.get("color", "") if config else ""
                    block.set_connection_name(conn_name, db_type, color or None, group or "")
        except Exception as e:
            print(S.session_widget.conn_dialog_error.format(error=e))

    # === CONNECTION ===

    def ensure_connector_for_metadata(self, callback) -> None:
        """Reconnect after idle sleep, then invoke callback(connector)."""
        connector = getattr(self.session, "connector", None)
        if connector is not None and connector.is_connected():
            callback(connector)
            return

        group = self.session.connection_group or ""
        name = self.session.connection_name or ""
        if not name:
            return

        pending = getattr(self, "_metadata_connect_callbacks", None)
        if pending is None:
            self._metadata_connect_callbacks = []
            pending = self._metadata_connect_callbacks
        pending.append(callback)

        thread = getattr(self, "_metadata_connect_thread", None)
        if thread is not None:
            try:
                if thread.isRunning():
                    return
            except RuntimeError:
                pass

        thread = QThread()
        worker = SessionConnectionWorker(self.session, group, name, "", widget=self)
        worker.moveToThread(thread)

        def _on_finished(success: bool, _message: str):
            callbacks = list(getattr(self, "_metadata_connect_callbacks", []) or [])
            self._metadata_connect_callbacks = []
            if success:
                live = getattr(self.session, "connector", None)
                if live is not None and live.is_connected():
                    for cb in callbacks:
                        try:
                            cb(live)
                        except Exception:
                            pass

        thread.started.connect(worker.run)
        worker.finished.connect(_on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._metadata_connect_thread = thread
        thread.start()

    def connect_to_database(self, group: str, connection_name: str, password: str = "") -> bool:
        """
        Connect this session to a database (in background)

        Args:
            group: Connection group ("" for ungrouped)
            connection_name: Connection name
            password: Password (if required)

        Returns:
            True (always, as it's asynchronous)
        """
        from src.database.connection_manager import ConnectionManager
        from src.core.connection_ref import ConnectionRef

        manager = ConnectionManager()
        config = manager.get_connection_config(group, connection_name)
        if config:
            self._connection_color = config.get("color", "#007ACC") or "#007ACC"

        self.detach_connection_thread()

        display = ConnectionRef(group=group or "", name=connection_name).display()
        self._show_loading(S.session_widget.loading_connecting.format(name=display))

        self._connection_thread = QThread()
        self._connection_thread.setObjectName("SessionConnection")
        self._connection_worker = SessionConnectionWorker(
            self.session, group, connection_name, password, widget=self
        )
        self._connection_worker.moveToThread(self._connection_thread)

        # Conectar sinais
        self._connection_thread.started.connect(self._connection_worker.run)
        self._connection_worker.finished.connect(self._on_connection_finished)
        self._connection_worker.finished.connect(self._connection_thread.quit)
        self._connection_thread.finished.connect(self._on_connection_thread_finished)

        # Iniciar
        self._connection_thread.start()

        main = self.window()
        if main is not None and hasattr(main, "_register_session_connection_thread"):
            main._register_session_connection_thread(
                self, self._connection_thread, self._connection_worker
            )

        return True

    def blocks_are_empty(self) -> bool:
        """True when every block has no non-whitespace code."""
        editor = getattr(self, "editor", None)
        if editor is None or not hasattr(editor, "blocks"):
            return True
        try:
            blocks = editor.blocks
        except RuntimeError:
            return True
        if not blocks:
            return True
        for block in blocks:
            try:
                if block.get_code().strip():
                    return False
            except RuntimeError:
                continue
        return True

    def is_connecting(self) -> bool:
        """True while this tab's connection worker thread is still running."""
        try:
            thread = getattr(self, "_connection_thread", None)
            return thread is not None and thread.isRunning()
        except RuntimeError:
            return False

    def detach_connection_thread(self) -> None:
        """Drop UI ties to the connection worker; thread may finish in background."""
        thread = getattr(self, "_connection_thread", None)
        worker = getattr(self, "_connection_worker", None)
        self._connection_thread = None
        self._connection_worker = None
        if worker is not None:
            try:
                worker.cancel()
            except RuntimeError:
                pass
            try:
                worker.finished.disconnect(self._on_connection_finished)
            except (TypeError, RuntimeError):
                pass
        if thread is not None:
            try:
                thread.finished.disconnect(self._on_connection_thread_finished)
            except (TypeError, RuntimeError):
                pass
        main = self.window()
        if main is not None and hasattr(main, "_orphan_connection_thread"):
            main._orphan_connection_thread(thread, worker)
        self._hide_loading()

    def _abort_connection_thread(self, wait_ms: int = 5000, *, force: bool = False) -> None:
        """Blocking stop — app shutdown only; tab close uses detach_connection_thread."""
        from src.utils.qt_threading import stop_qthread

        thread = getattr(self, "_connection_thread", None)
        worker = getattr(self, "_connection_worker", None)
        if thread is None and worker is None:
            return
        self.detach_connection_thread()
        stop_qthread(thread, worker, wait_ms=wait_ms, force_terminate=force)

    def _on_connection_thread_finished(self) -> None:
        """Clear thread refs after natural quit — never deleteLater on QThread."""
        sender = self.sender()
        from PyQt6.QtCore import QThread

        if isinstance(sender, QThread):
            main = self.window()
            if main is not None and hasattr(main, "_unregister_session_connection_thread"):
                main._unregister_session_connection_thread(sender)
        if sender is getattr(self, "_connection_thread", None):
            self._connection_thread = None

    def _on_connection_finished(self, success: bool, message: str):
        """Callback when connection finishes"""
        if sip.isdeleted(self) or getattr(self, "_is_closing", False):
            self._hide_loading()
            return
        # Esconder loading
        self._hide_loading()

        # Mostrar resultado
        if success:
            self._touch_db_activity()
            self.append_output(message)
            self.status_changed.emit(message)
            # Emit connection change signal
            if self.session.connection_name and self.session.connector:
                db = get_connector_database_context(self.session.connector)
                if db:
                    self.session.database_context = db
                self.connection_changed.emit(self.session.connection_name, db)
                self._apply_restored_block_databases()
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
        if self._reject_if_cancelling_sql():
            return
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
        self._is_closing = True
        self._cancel_requested = True
        self._execution_queue.clear()
        self._cancel_pending_db_switches()

        # Stop periodic timer if running
        self.stop_periodic()

        if hasattr(self, "editor") and self.editor:
            self.editor.cleanup()

        self._stop_sql_execution()
        self._stop_python_execution()
        if self._sql_stopping:
            self._force_release_stopping_query_lock()
            self._finalize_sql_stop()
        self.detach_connection_thread()
        self._orphan_running_threads()
        self._idle_reaper_timer.stop()
        self._block_connector_pool.release_all()
        self._sql_finished_handler = None
        self._python_finished_handler = None
