"""
DataPyn IDE main window - core module.

MainWindow is composed of multiple mixins:
- ExecutionMixin: SQL/Python execution, timer, notifications
- FileIOMixin: File open/save/export, context detection
- ConnectionsMixin: Database connections, OE interaction
- SchemaMixin: Schema loading, OE updates, variables
- SessionsMixin: Session lifecycle, tab events, persistence
- LayoutMixin: Dockable panels, dock layout
- UISetupMixin: Menus, toolbar, shortcuts, settings, updates
- CopilotMixin: LSP setup, authentication, status
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QMenuBar,
    QMenu,
    QToolBar,
    QStatusBar,
    QTextEdit,
    QDockWidget,
    QLabel,
    QPushButton,
    QFileDialog,
    QLineEdit,
    QTabBar,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont, QColor
from src.ui.components.toast_notification import ToastManager
import sys
import re
import io
import ast
import hashlib
import logging
import traceback
import weakref
from io import StringIO
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)

from src.database import ConnectionManager
from src.core import ResultsManager, ShortcutManager, WorkspaceManager, ThemeManager, SessionManager
from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog
from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
from src.ui.dialogs.update_dialog import UpdateDialog, UpdateDownloadDialog, UpdateCheckingDialog

from src.ui.components.results_viewer import ResultsViewer
from src.ui.components.session_widget import SessionWidget
from src.ui.components.session_tabs import SessionTabs
from src.ui.components.connection_panel import ConnectionPanel
from src.ui.components.toolbar import MainToolbar
from src.ui.components.statusbar import MainStatusBar
from src.ui.components.output_panel import OutputPanel
from src.ui.components.variables_panel import VariablesPanel
from src.ui.components.object_explorer_panel import ObjectExplorerPanel
from src.ui.components.copilot_chat_panel import PyniaChatPanel
from src.ui.components.copilot_output_panel import CopilotOutputPanel
from src.ui.docking import DockingMainWindow
from src.design_system.tokens import get_colors, DARK_COLORS, RADIUS
from src.design_system.stylesheet import (
    get_main_window_stylesheet,
    get_dock_widget_stylesheet,
    get_bottom_dock_stylesheet,
    get_execution_label_stylesheet,
    get_connection_status_stylesheet,
    get_empty_state_stylesheet,
    get_start_button_stylesheet,
)

from src.services import AutoUpdateService
from src.services.copilot import MCPServer, CopilotClient
from src.services.pynia import PyniaAgentClient
from src.services.copilot.copilot_settings import get_copilot_settings
from src.language import S

from src.ui.main_window._workers import SqlWorker, PythonWorker, _read_file_with_encoding_fallback
from src.ui.main_window._execution import ExecutionMixin
from src.ui.main_window._file_io import FileIOMixin
from src.ui.main_window._connections import ConnectionsMixin
from src.ui.main_window._schema import SchemaMixin
from src.ui.main_window._sessions import SessionsMixin
from src.ui.main_window._layout import LayoutMixin
from src.ui.main_window._ui_setup import UISetupMixin
from src.ui.main_window._copilot import CopilotMixin

DEFAULT_VERSION = "1.1.6"


class MainWindow(
    ExecutionMixin,
    FileIOMixin,
    ConnectionsMixin,
    SchemaMixin,
    SessionsMixin,
    LayoutMixin,
    UISetupMixin,
    CopilotMixin,
    DockingMainWindow,
):
    """Janela principal da IDE"""

    def __init__(self, splash=None):
        self._splash = splash

        def _sp(value, msg):
            if self._splash:
                self._splash.set_progress(value, msg)

        _sp(45, "Carregando módulos…")

        # Inicializar atributos ANTES de chamar super().__init__()
        # to prevent DockingMainWindow._setup_ui() from accessing uninitialized attributes

        # Managers (ConnectionManager is now ONLY for configurations, not active connections)
        self.connection_manager = ConnectionManager()  # Only for managing saved configs
        self.results_manager = ResultsManager()
        self.shortcut_manager = ShortcutManager()
        self.shortcut_manager.detect_duplicates()  # Log any duplicate shortcuts
        self.workspace_manager = WorkspaceManager()
        from src.core.recent_files_manager import RecentFilesManager
        self.recent_files_manager = RecentFilesManager()
        self.theme_manager = ThemeManager()
        self.session_manager = SessionManager()  # New: Session manager

        # Auto-update service
        self._current_version = self._get_current_version()
        self.auto_update_service = AutoUpdateService(self._current_version)

        # Mapeia session_id -> SessionWidget
        self._session_widgets: dict = {}

        # Empty state widget (when there are no sessions)
        self._empty_state_widget = None

        # Threads for background execution
        self._worker_threads = []  # Keeps reference to prevent garbage collection

        # Servico de autocomplete SQL (carrega schema do banco em background)
        from src.services.schema_service import SchemaService

        self._schema_service = SchemaService()
        self._schema_service.schema_loaded.connect(self._on_schema_loaded)
        self._schema_service.schema_error.connect(self._on_schema_error)
        # Lazy loading signals for Object Explorer
        self._schema_service.schemas_loaded.connect(self._on_schemas_loaded)
        self._schema_service.tables_loaded.connect(self._on_tables_loaded)
        self._schema_service.columns_loaded.connect(self._on_columns_loaded)

        # Pynia agent (multi-provider chat) + Copilot backend (LSP / Copilot connector)
        self._mcp_server = MCPServer() if MCPServer else None
        self._copilot_client = CopilotClient() if CopilotClient else None
        self._pynia_agent = (
            PyniaAgentClient(copilot_client=self._copilot_client) if PyniaAgentClient else None
        )
        
        # LSP server manager for fast inline completions
        from src.services.copilot import CopilotServerManager, is_copilot_server_available
        self._copilot_server_manager = CopilotServerManager()
        self._lsp_client = None
        self._lsp_server_available = is_copilot_server_available()  # Check now, setup later

        # Intelligent file management system
        self._original_file_path = None  # Original opened file path (sql/py/dpw)
        self._original_file_type = None  # Tipo: 'sql', 'python', 'workspace'
        self._current_context = "workspace"  # Contexto atual: 'sql', 'python', 'workspace'
        self._is_closing = False

        # Icons
        self.icons = self._setup_icons()

        _sp(55, "Montando painéis…")

        # Agora chama super().__init__() que vai inicializar o docking system
        super().__init__()

        # Disable parent's auto-save layout timer (we have our own)
        if hasattr(self, 'auto_save_timer'):
            self.auto_save_timer.stop()
            try:
                self.auto_save_timer.timeout.disconnect()
            except Exception:
                pass

        # Enables advanced nesting and special dock configurations
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

        # Finalize docking system configuration (skip menu creation - MainWindow creates its own)
        self._connect_signals()  # Only connect signals, skip _setup_menu_actions

        # Apply theme after configuring editor themes
        self._apply_app_theme()

        _sp(65, "Construindo interface…")

        # Configure MainWindow-specific UI
        self._setup_ui()

        _sp(75, "Menus e barra de ferramentas…")

        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._setup_shortcuts()

        # Restore dock layout AFTER toolbar exists (restoreState affects toolbars)
        self._restore_dock_layout()

        if self.auto_update_service.has_pending_update():
            self._show_pending_update_button(self.auto_update_service.get_pending_version())
        self._setup_auto_save_layout()

        # Connect signals do SessionManager
        self.session_manager.session_focused.connect(self._on_session_focused)

        _sp(90, "Aplicando tema…")

        # Setup in-app toast notifications (before theme so update toasts can show)
        ToastManager.setup(self)

        # Apply initial theme (re-shows pending update button at the end)
        self._apply_app_theme()

        # Timer to update status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

        # Check for updates on startup (brief delay so UI finishes loading)
        if self.auto_update_service.is_auto_update_enabled():
            QTimer.singleShot(2000, self._check_for_updates_silent)

        # Update initial window title
        self._update_window_title()

        # Initialize MCP server with main window reference
        if self._mcp_server:
            self._mcp_server.set_main_window(self)


    # === DELEGATION PROPERTIES FOR CURRENT SESSION ===

    @property
    def results_viewer(self):
        """Returns the results_viewer of the current session"""
        widget = self._get_current_session_widget()
        return widget.results_viewer if widget else None

    @property
    def variables_viewer(self):
        """Returns the variables_viewer of the current session"""
        widget = self._get_current_session_widget()
        return widget.variables_viewer if widget else None

    @property
    def python_output(self):
        """Returns the output_text of the current session"""
        widget = self._get_current_session_widget()
        return widget.output_text if widget else None

    @property
    def bottom_tabs(self):
        """Returns a BottomTabs-compatible object using global panels"""

        # Returns a mock object that redirects to dockable panels
        class DockableBottomTabsCompat:
            def __init__(self, main_window):
                self.main_window = main_window

            def setCurrentIndex(self, index):
                """Simulates active tab change"""
                if index == 0:  # Results
                    self.main_window.show_panel("results")
                    results_panel = self.main_window.get_panel("results")
                    if results_panel and results_panel.tab_widget.count() > 0:
                        results_panel.tab_widget.setCurrentIndex(0)
                elif index == 1:  # Output
                    self.main_window.show_panel("output")
                elif index == 2:  # Variables
                    self.main_window.show_panel("variables")

            @property
            def results_viewer(self):
                return self.main_window.global_results_viewer

            @property
            def output_panel(self):
                return self.main_window.global_output_panel

            @property
            def variables_panel(self):
                return self.main_window.global_variables_panel

            def log(self, message, prefix="INFO"):
                """Compatibility: log to global output"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.log(message, prefix)

            def log_error(self, message):
                """Compatibility: error log to global output"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.error(message)

            def error(self, message):
                """Compatibility: alias for log_error"""
                self.log_error(message)

            def log_success(self, message):
                """Compatibility: success log to global output"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.success(message)

            def log_warning(self, message):
                """Compatibility: warning log to global output"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.warning(message)

            def set_results(self, df, title="Result", query_info=None):
                """Compatibility: sets results in the global panel"""
                if self.main_window.global_results_viewer:
                    self.main_window.global_results_viewer.display_dataframe(df, title)

            def set_variables(self, variables_dict):
                """Compatibility: sets variables in the global panel"""
                if self.main_window.global_variables_panel:
                    self.main_window.global_variables_panel.set_variables(variables_dict)

            def show_output(self):
                """Compatibility: shows output panel"""
                self.main_window.show_panel("output")

            def clear_output(self):
                """Compatibility: clears global output"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.clear()

            @property
            def output_text(self):
                """Compatibility: access to global output text"""
                if self.main_window.global_output_panel:
                    return self.main_window.global_output_panel
                return None

        return DockableBottomTabsCompat(self)

    def _get_bottom_tabs_instance(self):
        """Returns a single BottomTabs instance for compatibility"""
        if not hasattr(self, "_bottom_tabs_cache"):
            # Create single instance of compatibility class
            class DockableBottomTabsCompat:
                def __init__(self, main_window):
                    self.main_window = main_window

                def setCurrentIndex(self, index):
                    """Simulates active tab change"""
                    if index == 0:  # Results
                        self.main_window.show_panel("results")
                        results_panel = self.main_window.get_panel("results")
                        if results_panel and results_panel.tab_widget.count() > 0:
                            results_panel.tab_widget.setCurrentIndex(0)
                    elif index == 1:  # Output
                        self.main_window.show_panel("output")
                    elif index == 2:  # Variables
                        self.main_window.show_panel("variables")

                @property
                def results_viewer(self):
                    return self.main_window.global_results_viewer

                @property
                def output_panel(self):
                    return self.main_window.global_output_panel

                @property
                def variables_panel(self):
                    return self.main_window.global_variables_panel

                def log(self, message, prefix="INFO"):
                    """Compatibility: log to global output"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.log(message, prefix)

                def log_error(self, message):
                    """Compatibility: error log to global output"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.error(message)

                def error(self, message):
                    """Compatibility: alias for log_error"""
                    self.log_error(message)

                def log_success(self, message):
                    """Compatibility: success log to global output"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.success(message)

                def log_warning(self, message):
                    """Compatibility: warning log to global output"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.warning(message)

                def set_results(self, df, title="Result", query_info=None):
                    """Compatibility: sets results in the global panel"""
                    if self.main_window.global_results_viewer:
                        self.main_window.global_results_viewer.display_dataframe(df, title)

                def set_variables(self, variables_dict):
                    """Compatibility: sets variables in the global panel"""
                    if self.main_window.global_variables_panel:
                        self.main_window.global_variables_panel.set_variables(variables_dict)

                def show_output(self):
                    """Compatibility: shows output panel"""
                    self.main_window.show_panel("output")

                def clear_output(self):
                    """Compatibility: clears global output"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.clear()

                @property
                def output_text(self):
                    """Compatibility: access to global output text"""
                    if self.main_window.global_output_panel:
                        return self.main_window.global_output_panel
                    return None

            self._bottom_tabs_cache = DockableBottomTabsCompat(self)
        return self._bottom_tabs_cache

    @property
    def bottom_tabs(self):
        """Returns shared BottomTabs instance"""
        return self._get_bottom_tabs_instance()

    def _create_bottom_tabs_compat(self):
        """Creates the BottomTabs compatibility object"""

        # Returns a mock object that redirects to dockable panels
        class DockableBottomTabsCompat:
            pass

        return DockableBottomTabsCompat()

    def show(self):
        """Overrides show to restore window geometry"""
        super().show()
        # Restore geometry after window is shown
        self._restore_window_state()


    def closeEvent(self, event):
        """On window close"""
        from src.design_system.message_box import ask_yes_no

        has_running = any(
            widget._is_executing
            for widget in self._session_widgets.values()
            if hasattr(widget, "_is_executing")
        )

        if has_running:
            if not ask_yes_no(
                self,
                S.dialogs.execution_in_progress_title,
                S.dialogs.execution_in_progress_msg,
                default_yes=False,
            ):
                event.ignore()
                return

            # Cancel all executions
            for widget in self._session_widgets.values():
                if hasattr(widget, "_cancel_requested"):
                    widget._cancel_requested = True

        self._is_closing = True
        if hasattr(self, "_sessions_to_load"):
            self._sessions_to_load.clear()

        if hasattr(self, "_abort_all_background_connections"):
            self._abort_all_background_connections(wait_ms=3000)

        from src.utils.qt_threading import stop_qthread

        for thread, worker in list(getattr(self, "_worker_threads", [])):
            stop_qthread(thread, worker, wait_ms=3000, force_terminate=True)
        if hasattr(self, "_worker_threads"):
            self._worker_threads.clear()

        for widget in list(getattr(self, "_session_widgets", {}).values()):
            if hasattr(widget, "_orphan_running_threads"):
                widget._orphan_running_threads()

        # Sessions are saved live while editing; only cancel pending debounce.
        if hasattr(self, "_session_autosave"):
            self._session_autosave.cancel_pending()

        # Stop all timers to prevent resource leaks
        if hasattr(self, 'status_timer') and self.status_timer:
            self.status_timer.stop()
        if hasattr(self, '_execution_update_timer') and self._execution_update_timer:
            self._execution_update_timer.stop()
        if hasattr(self, '_layout_save_timer') and self._layout_save_timer:
            self._layout_save_timer.stop()

        if hasattr(self, "auto_update_service") and self.auto_update_service:
            self.auto_update_service.cleanup()

        for thread_attr in ("_entity_info_threads", "_connection_threads"):
            active_threads = list(getattr(self, thread_attr, []))
            for item in active_threads:
                thread = item[0]
                worker = item[1] if len(item) > 1 else None
                try:
                    if worker is not None and hasattr(worker, "cancel"):
                        worker.cancel()
                except RuntimeError:
                    pass
                try:
                    if thread and thread.isRunning():
                        thread.quit()
                        if not thread.wait(3000):
                            thread.terminate()
                            thread.wait(1000)
                except RuntimeError:
                    pass
            setattr(self, thread_attr, [])

        # Save dock layout before closing
        self._save_dock_layout()

        # Cleanup all sessions
        for widget in self._session_widgets.values():
            widget.cleanup()

        # Limpar schema service
        if hasattr(self, "_schema_service"):
            self._schema_service.cleanup()

        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            self._copilot_chat_panel.cleanup()

        # Cleanup Copilot auth/LSP before widgets and connections disappear
        if hasattr(self, "_copilot_auth_service") and self._copilot_auth_service:
            self._copilot_auth_service.cleanup()

        if hasattr(self, "_lsp_client") and self._lsp_client:
            self._lsp_client.cleanup()
            self._lsp_client = None

        self.session_manager.cleanup_all()

        # Close connections
        self.connection_manager.close_all()

        # Cleanup Copilot client
        if hasattr(self, "_pynia_agent") and self._pynia_agent:
            self._pynia_agent.cleanup()
        elif hasattr(self, "_copilot_client") and self._copilot_client:
            self._copilot_client.cleanup()

        # Cleanup docking manager timers
        if hasattr(self, "docking_manager"):
            self.docking_manager.cleanup()

        event.accept()

    def deleteLater(self):
        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            self._copilot_chat_panel.cleanup()
        super().deleteLater()
