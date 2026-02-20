"""
DataPyn IDE main window
"""

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
    QMessageBox,
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


from src.editors import UnifiedEditor
from src.database import ConnectionManager
from src.core import ResultsManager, ShortcutManager, WorkspaceManager, ThemeManager, SessionManager
from src.core.mixed_executor import MixedLanguageExecutor
from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog
from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
from src.ui.dialogs.update_dialog import UpdateDialog, UpdateDownloadDialog, UpdateCheckingDialog

# Componentes da UI
from src.ui.components.results_viewer import ResultsViewer
from src.ui.components.session_widget import SessionWidget
from src.ui.components.session_tabs import SessionTabs
from src.ui.components.connection_panel import ConnectionPanel
from src.ui.components.toolbar import MainToolbar
from src.ui.components.statusbar import MainStatusBar
from src.ui.components.output_panel import OutputPanel
from src.ui.components.variables_panel import VariablesPanel
from src.ui.components.object_explorer_panel import ObjectExplorerPanel
from src.ui.docking import DockingMainWindow
from src.design_system.tokens import get_colors, DARK_COLORS

# Services
from src.services import AutoUpdateService
from src.language import S

# Constantes
DEFAULT_VERSION = "1.1.6"  # Default version if unable to read from pyproject.toml


class SqlWorker(QObject):
    """Worker for executing SQL in background"""

    finished = pyqtSignal(object, str)  # (result_df or None, error_msg or '')

    def __init__(self, connector, query):
        super().__init__()
        self.connector = connector
        self.query = query

    def run(self):
        try:
            df = self.connector.execute_query(self.query)
            self.finished.emit(df, "")
        except Exception as e:
            self.finished.emit(None, str(e))


# ConnectionWorker REMOVED - each tab manages its own connection via SessionWidget


class PythonWorker(QObject):
    """Centralized worker for Python execution in background"""

    finished = pyqtSignal(object, str, str, dict, list)  # (result, output, error, namespace, figures)

    def __init__(self, code, namespace, is_expression):
        super().__init__()
        self.code = code
        self.namespace = namespace
        self.is_expression = is_expression

    def run(self):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            # Configure matplotlib for non-interactive backend (Agg) with dark theme
            self._setup_matplotlib_backend()

            # Snapshot of DataFrames before execution to detect new ones
            df_snapshot = {k: id(v) for k, v in self.namespace.items() if isinstance(v, pd.DataFrame)}

            # Capture stdout AND stderr to same buffer
            # Thus print(), logging.info(), warnings, sys.stderr.write()
            # all appear in output panel
            captured = StringIO()
            sys.stdout = captured
            sys.stderr = captured

            result_value = self._execute_centralized()

            sys.stdout = old_stdout
            sys.stderr = old_stderr
            output = captured.getvalue()

            # Capture pending matplotlib figures
            figures = self._capture_matplotlib_figures()

            # Se resultado e None, verificar se novos DataFrames foram criados
            if result_value is None:
                new_dfs = [
                    (k, v)
                    for k, v in self.namespace.items()
                    if isinstance(v, pd.DataFrame)
                    and not k.startswith("_")
                    and (k not in df_snapshot or id(v) != df_snapshot[k])
                ]
                if new_dfs:
                    result_value = new_dfs[-1][1]

            # Processar resultado rico (PIL Image, plotly, matplotlib Figure,
            # _repr_html_(), dict/list, etc.)
            result_value, extra_outputs = self._process_rich_result(result_value, has_captured_figures=bool(figures))
            figures.extend(extra_outputs)

            self.finished.emit(result_value, output, "", self.namespace, figures)
        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.finished.emit(None, "", traceback.format_exc(), self.namespace, [])

    def _setup_matplotlib_backend(self):
        """Configures matplotlib to use Agg backend (non-interactive) with dark theme"""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.close("all")
            # Substituir plt.show() por no-op para nao travar
            plt.show = lambda *args, **kwargs: None
            # Tema escuro para combinar com a IDE
            plt.rcParams.update(
                {
                    "figure.facecolor": "#1e1e1e",
                    "axes.facecolor": "#2d2d30",
                    "axes.edgecolor": "#555555",
                    "axes.labelcolor": "#d4d4d4",
                    "text.color": "#d4d4d4",
                    "xtick.color": "#d4d4d4",
                    "ytick.color": "#d4d4d4",
                    "grid.color": "#3e3e42",
                    "legend.facecolor": "#2d2d30",
                    "legend.edgecolor": "#555555",
                    "figure.edgecolor": "#1e1e1e",
                    "savefig.facecolor": "#1e1e1e",
                    "savefig.edgecolor": "#1e1e1e",
                }
            )
        except ImportError:
            pass  # matplotlib nao instalado, ignorar

    def _capture_matplotlib_figures(self) -> list:
        """Captures all open matplotlib figures as rich outputs.

        Returns:
            List of dicts {'type': 'image', 'data': bytes_png}
        """
        figures_data = []
        try:
            import matplotlib.pyplot as plt

            fig_nums = plt.get_fignums()
            if not fig_nums:
                return []

            for num in fig_nums:
                fig = plt.figure(num)
                buf = io.BytesIO()
                fig.savefig(
                    buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none"
                )
                buf.seek(0)
                figures_data.append({"type": "image", "data": buf.getvalue()})
                buf.close()

            plt.close("all")
        except ImportError:
            pass  # matplotlib nao instalado
        except Exception as e:
            logging.warning(f"Error capturing matplotlib figures: {e}")

        return figures_data

    def _execute_centralized(self):
        """Centralized execution using AST - all Python executions go through here.

        Usa o modulo ast para separar corretamente statements de expressoes,
        sem quebrar blocos multi-linha (for, if, try, def, class etc).
        """
        code = self.code.strip()
        if not code:
            return None

        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Deixar o exec levantar o erro com traceback correto
            exec(code, self.namespace)
            return None

        if not tree.body:
            return None

        last_node = tree.body[-1]

        # Se o ultimo node e uma expressao (nao assignment, for, if, etc),
        # executar tudo menos ele, depois avaliar a expressao e retornar o valor
        if isinstance(last_node, ast.Expr):
            if len(tree.body) > 1:
                exec_module = ast.Module(body=tree.body[:-1], type_ignores=[])
                ast.fix_missing_locations(exec_module)
                exec(compile(exec_module, "<exec>", "exec"), self.namespace)
            expr = ast.Expression(body=last_node.value)
            ast.fix_missing_locations(expr)
            return eval(compile(expr, "<eval>", "eval"), self.namespace)
        else:
            # Ultimo node e statement (assignment, for, if, etc) - executar tudo
            exec(compile(tree, "<exec>", "exec"), self.namespace)
            return None

    def _process_rich_result(self, result, has_captured_figures=False):
        """Converts rich objects into typed rich outputs.

        Detecta: matplotlib Figure, PIL Image, Plotly Figure,
        _repr_png_(), _repr_html_(), dict/list.

        Returns:
            (result, extra_outputs): resultado processado e lista de rich outputs.
            Rich outputs sao dicts: {'type': 'image'|'html'|'json', 'data': ...}
        """
        extra_outputs = []
        if result is None:
            return result, extra_outputs

        # matplotlib Figure retornado como valor de expressao
        try:
            from matplotlib.figure import Figure as MplFigure

            if isinstance(result, MplFigure):
                if has_captured_figures:
                    # Already captured by _capture_matplotlib_figures, don't duplicate
                    return None, extra_outputs
                buf = io.BytesIO()
                result.savefig(
                    buf, format="png", dpi=150, bbox_inches="tight", facecolor=result.get_facecolor(), edgecolor="none"
                )
                buf.seek(0)
                extra_outputs.append({"type": "image", "data": buf.getvalue()})
                buf.close()
                return None, extra_outputs
        except ImportError:
            pass

        # PIL/Pillow Image
        try:
            from PIL import Image as PILImage

            if isinstance(result, PILImage.Image):
                buf = io.BytesIO()
                # Converter RGBA para RGB se necessario (PNG suporta ambos)
                result.save(buf, format="PNG")
                buf.seek(0)
                extra_outputs.append({"type": "image", "data": buf.getvalue()})
                buf.close()
                return None, extra_outputs
        except ImportError:
            pass

        # Plotly Figure -> tenta PNG (kaleido), senao HTML interativo
        try:
            import plotly.graph_objects as go

            if isinstance(result, go.Figure):
                try:
                    img_bytes = result.to_image(format="png", scale=2, width=800, height=500)
                    extra_outputs.append({"type": "image", "data": img_bytes})
                    return None, extra_outputs
                except Exception:
                    # kaleido nao instalado - usar HTML interativo
                    try:
                        html_str = result.to_html(
                            include_plotlyjs="cdn", full_html=True, config={"displayModeBar": True}
                        )
                        extra_outputs.append({"type": "html", "data": html_str})
                        return None, extra_outputs
                    except Exception:
                        pass
        except ImportError:
            pass

        # Objeto com _repr_png_() (convencao IPython)
        if hasattr(result, "_repr_png_"):
            try:
                png_data = result._repr_png_()
                if png_data:
                    extra_outputs.append({"type": "image", "data": png_data})
                    return None, extra_outputs
            except Exception:
                pass

        # Objeto com _repr_html_() (pandas Styler, IPython.display.HTML etc.)
        # DO NOT apply for pure DataFrames (already has better grid)
        if hasattr(result, "_repr_html_") and not isinstance(result, pd.DataFrame):
            try:
                html_data = result._repr_html_()
                if html_data:
                    extra_outputs.append({"type": "html", "data": html_data})
                    return None, extra_outputs
            except Exception:
                pass

        # dict ou list -> JSON tree view
        if isinstance(result, (dict, list)) and not isinstance(result, pd.DataFrame):
            # So mostrar como JSON se nao e muito simples (mais de 1 item)
            if isinstance(result, dict) and len(result) >= 1:
                extra_outputs.append({"type": "json", "data": result})
                return None, extra_outputs
            elif isinstance(result, list) and len(result) >= 1:
                extra_outputs.append({"type": "json", "data": result})
                return None, extra_outputs

        return result, extra_outputs


class CrossSyntaxWorker(QObject):
    """Worker for executing Cross-Syntax in background"""

    finished = pyqtSignal(dict, str)  # (result_dict, error)

    def __init__(self, executor, code, namespace):
        super().__init__()
        self.executor = executor
        self.code = code
        self.namespace = namespace

    def run(self):
        try:
            result = self.executor.parse_and_execute(self.code, self.namespace)
            self.finished.emit(result, "")
        except Exception as e:
            self.finished.emit({}, traceback.format_exc())


class MainWindow(DockingMainWindow):
    """Janela principal da IDE"""

    def __init__(self, splash=None):
        self._splash = splash

        def _sp(value, msg):
            if self._splash:
                self._splash.set_progress(value, msg)

        _sp(45, "Loading managers...")

        # Inicializar atributos ANTES de chamar super().__init__()
        # to prevent DockingMainWindow._setup_ui() from accessing uninitialized attributes

        # Managers (ConnectionManager is now ONLY for configurations, not active connections)
        self.connection_manager = ConnectionManager()  # Only for managing saved configs
        self.results_manager = ResultsManager()
        self.shortcut_manager = ShortcutManager()
        self.workspace_manager = WorkspaceManager()
        self.theme_manager = ThemeManager()
        self.theme_manager.set_editor_theme("monokai")  # Specific theme for code editors
        self.session_manager = SessionManager()  # New: Session manager
        self.mixed_executor = MixedLanguageExecutor(None, self.results_manager)

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

        # Intelligent file management system
        self._original_file_path = None  # Original opened file path (sql/py/dpw)
        self._original_file_type = None  # Tipo: 'sql', 'python', 'workspace'
        self._current_context = "workspace"  # Contexto atual: 'sql', 'python', 'workspace'

        # Icons
        self.icons = self._setup_icons()

        _sp(55, "Building docking system...")

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

        # Finalize docking system configuration
        self.finish_docking_setup()

        # Apply theme after configuring editor themes
        self._apply_app_theme()

        _sp(65, "Building interface...")

        # Configure MainWindow-specific UI
        self._setup_ui()

        _sp(75, "Creating menus and toolbar...")

        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._setup_shortcuts()

        # Restore dock layout AFTER toolbar exists (restoreState affects toolbars)
        self._restore_dock_layout()
        self._setup_auto_save_layout()

        # Connect signals do SessionManager
        self.session_manager.session_focused.connect(self._on_session_focused)

        _sp(90, "Applying theme...")

        # Apply initial theme
        self._apply_app_theme()

        # Setup in-app toast notifications
        ToastManager.setup(self)

        # Timer to update status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

        # Check for updates on startup (after 5 seconds)
        if self.auto_update_service.is_auto_update_enabled():
            QTimer.singleShot(5000, self._check_for_updates_silent)

        # Update initial window title
        self._update_window_title()

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

    def _setup_icons(self):
        """Configures QtAwesome icons with uniform color"""
        if not HAS_QTAWESOME:
            return {}

        c = "#b0b0b0"  # Cor padrao uniforme para todos os icones
        return {
            "database": qta.icon("mdi.database", color=c),
            "play": qta.icon("mdi.play", color=c),
            "python": qta.icon("mdi.language-python", color=c),
            "table": qta.icon("mdi.table", color=c),
            "save": qta.icon("mdi.content-save", color=c),
            "folder-open": qta.icon("mdi.folder-open", color=c),
            "trash": qta.icon("mdi.delete-outline", color=c),
            "cog": qta.icon("mdi.cog-outline", color=c),
            "plug": qta.icon("mdi.connection", color=c),
            "code": qta.icon("mdi.code-tags", color=c),
            "chart-bar": qta.icon("mdi.chart-bar", color=c),
            "memory": qta.icon("mdi.memory", color=c),
            "terminal": qta.icon("mdi.console", color=c),
        }

    def _setup_ui(self):
        """Configures the main interface"""
        self.setWindowTitle(S.main_window.window_title)
        self.setGeometry(100, 100, 1400, 900)

        # Carregar cores do design system
        colors = get_colors()

        # Tema escuro
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {colors.bg_primary};
            }}
            QMenuBar {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border-bottom: 1px solid {colors.border_default};
            }}
            QMenuBar::item:selected {{
                background-color: {colors.bg_elevated};
            }}
            QMenu {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                padding: 5px 0px;
            }}
            QMenu::item {{
                padding: 6px 40px 6px 30px;
                min-width: 180px;
            }}
            QMenu::item:selected {{
                background-color: {colors.interactive_primary_active};
            }}
            QMenu::icon {{
                padding-left: 8px;
                width: 16px;
                height: 16px;
            }}
            QToolBar {{
                background-color: {colors.bg_tertiary};
                border-bottom: 1px solid {colors.border_default};
                spacing: 5px;
            }}
            QStatusBar {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
            }}
            QTabWidget::pane {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_primary};
            }}
            QTabBar::tab {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                padding: 8px 20px;
                border: 1px solid {colors.border_default};
                border-bottom: none;
            }}
            QTabBar::tab:selected {{
                background-color: {colors.bg_primary};
                color: {colors.text_inverse};
            }}
            QTabBar::tab:hover {{
                background-color: {colors.bg_elevated};
            }}
            QSplitter::handle {{
                background-color: {colors.border_default};
            }}
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QTextEdit {{
                background-color: {colors.bg_primary};
                color: {colors.editor_fg};
                border: 1px solid {colors.border_default};
            }}
        """)

        # Container for session tabs (will be the central area)
        session_container = QWidget()
        session_layout = QVBoxLayout(session_container)
        session_layout.setContentsMargins(5, 5, 5, 5)

        # TabWidget for sessions (each tab is a complete SessionWidget)
        self.session_tabs = SessionTabs()
        self.session_tabs.session_closed.connect(self._close_session_tab)
        self.session_tabs.session_renamed.connect(self._on_session_renamed)
        self.session_tabs.session_changed.connect(self._on_session_tab_changed)
        self.session_tabs.duplicate_session.connect(self._duplicate_session)

        session_layout.addWidget(self.session_tabs)

        # Configure central area with sessions in the docking system
        self.set_central_content(session_container)

        # Restore sessions
        self._restore_sessions()

        # Dock for connections (left side)
        self._create_connections_dock()

        # Configure dockable panels (Results, Output, Variables)
        self._setup_dockable_panels()

        # Object Explorer (lateral direita, abaixo de Variables)
        self._create_object_explorer_dock()

        # Layout restore deferred to after toolbar creation (see __init__)

    def _create_connections_dock(self):
        """Creates the connections side panel using ConnectionPanel"""
        # Usar o componente ConnectionPanel
        self.connection_panel = ConnectionPanel(
            connection_manager=self.connection_manager, theme_manager=self.theme_manager
        )

        # Connect signals
        self.connection_panel.connection_requested.connect(self._quick_connect)
        self.connection_panel.new_tab_connection_requested.connect(self._connect_new_tab)
        self.connection_panel.new_connection_clicked.connect(self._new_connection)
        self.connection_panel.manage_connections_clicked.connect(self._manage_connections)
        self.connection_panel.edit_connection_clicked.connect(self._edit_connection)
        self.connection_panel.disconnect_clicked.connect(self._disconnect)

        # Create dock widget
        self.connections_dock = QDockWidget(S.dock.connections, self)
        self.connections_dock.setObjectName("ConnectionsDock")  # Para saveState/restoreState
        self.connections_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.connections_dock.setWidget(self.connection_panel)
        self.connections_dock.setStyleSheet("""
            QDockWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QDockWidget::title {
                background-color: #2d2d30;
                padding: 8px;
                font-weight: bold;
            }
        """)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)

        # Configure size policy to occupy full side
        self.connections_dock.setMinimumWidth(200)
        self.connections_dock.setMaximumWidth(400)

        # Configure features to allow full repositioning
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.connections_dock.setFeatures(features)

        # Create compatibility properties
        self._setup_connection_panel_compat()

    def _setup_connection_panel_compat(self):
        """Creates compatibility properties for legacy code"""
        # Maps old attributes to new component
        self.connections_list = self.connection_panel.connections_list.list_widget
        self.active_conn_name_label = self.connection_panel.active_widget.name_label
        self.active_conn_info_label = self.connection_panel.active_widget.info_label
        self.btn_disconnect = self.connection_panel.active_widget.btn_disconnect

    def _create_object_explorer_dock(self):
        """Creates Object Explorer panel (right side, below Variables).

        Usa QStackedWidget para que cada sessao tenha seu proprio Object Explorer.
        """
        from PyQt6.QtWidgets import QStackedWidget

        self._object_explorer_stack = QStackedWidget()
        # Mapeamento session_id -> ObjectExplorerPanel
        self._session_explorers: dict = {}

        # Criar dock widget
        self.object_explorer_dock = QDockWidget(S.dock.object_explorer, self)
        self.object_explorer_dock.setObjectName("ObjectExplorerDock")
        self.object_explorer_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.object_explorer_dock.setWidget(self._object_explorer_stack)
        self.object_explorer_dock.setStyleSheet("""
            QDockWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QDockWidget::title {
                background-color: #2d2d30;
                padding: 8px;
                font-weight: bold;
            }
        """)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.object_explorer_dock)

        self.object_explorer_dock.setMinimumWidth(200)
        self.object_explorer_dock.setMinimumHeight(150)

        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.object_explorer_dock.setFeatures(features)

        # Hide until there is an active connection
        self.object_explorer_dock.hide()

    def _get_session_explorer(self, session_id: str) -> ObjectExplorerPanel:
        """Returns the ObjectExplorerPanel for the session, creating if necessary."""
        if session_id in self._session_explorers:
            return self._session_explorers[session_id]

        panel = ObjectExplorerPanel(theme_manager=self.theme_manager)
        panel.insert_text_requested.connect(self._on_object_explorer_insert_text)
        panel.query_requested.connect(self._on_object_explorer_query)
        panel.database_switch_requested.connect(self._on_object_explorer_database_switch)
        panel.btn_refresh.clicked.connect(self._on_object_explorer_refresh)

        self._object_explorer_stack.addWidget(panel)
        self._session_explorers[session_id] = panel
        return panel

    def _remove_session_explorer(self, session_id: str):
        """Removes Object Explorer from a session."""
        panel = self._session_explorers.pop(session_id, None)
        if panel:
            self._object_explorer_stack.removeWidget(panel)
            panel.deleteLater()

    def _switch_session_explorer(self, session_id: str):
        """Switches to the Object Explorer of the active session."""
        panel = self._session_explorers.get(session_id)
        if panel:
            self._object_explorer_stack.setCurrentWidget(panel)

    @property
    def _active_object_explorer(self):
        """Returns the ObjectExplorerPanel of the active session."""
        sid = self._get_active_session_id()
        return self._session_explorers.get(sid) if sid else None

    def _on_object_explorer_insert_text(self, text: str):
        """Inserts text in the block that was focused before clicking on OE"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_last_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(text)
                # Refoca o editor apos inserir
                if hasattr(block.editor, "setFocus"):
                    block.editor.setFocus()

    def _on_object_explorer_query(self, query: str):
        """Inserts query in the block that was focused before clicking on OE"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_last_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(query)
                if hasattr(block.editor, "setFocus"):
                    block.editor.setFocus()

    def _on_object_explorer_database_switch(self, database_name: str):
        """Switches the database of the active tab connection (in background)"""
        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "session"):
            return

        session = current_widget.session
        connector = getattr(session, "connector", None)
        connection_name = getattr(session, "connection_name", "") or ""

        if not connector or not connector.is_connected():
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        self.statusBar().showMessage(S.status.switching_database.format(name=database_name), 10000)

        from src.workers import DatabaseSwitchWorker

        thread = QThread()
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.switch_success.connect(
            lambda db: self._on_database_switch_success(db, connection_name, connector, current_widget)
        )
        worker.error.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        thread.start()

    def _on_database_switch_success(self, database_name, connection_name, connector, widget):
        """Callback when database switch completes successfully.

        Propagates the database change to: connection panel, status bar,
        tab color, schema cache, object explorer, and ALL blocks.
        """
        self.statusBar().showMessage(S.status.database_changed.format(name=database_name), 5000)

        # --- Schema reload ---
        self._schema_service.invalidate_cache(connection_name)
        self._schema_service.load_schema(connector, connection_name)

        if hasattr(widget, "connection_changed"):
            widget.connection_changed.emit(connection_name, database_name)

        # --- Update connection panel ---
        config = self.connection_manager.get_connection_config(connection_name)
        if config:
            host = config.get("host", "localhost")
            db_type = config.get("db_type", "")
            self.connection_panel.set_active_connection(
                connection_name, host=host, database=database_name, db_type=db_type
            )

            # --- Tab color ---
            color = config.get("color", "#007ACC") or "#007ACC"
            for i in range(self.session_tabs.count()):
                tab_widget = self.session_tabs.widget(i)
                if isinstance(tab_widget, SessionWidget) and tab_widget == widget:
                    self.session_tabs.set_tab_connection_color(i, color)
                    break

        # --- Highlight connection in list ---
        for i in range(self.connections_list.count()):
            item = self.connections_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == connection_name:
                self.connections_list.setCurrentItem(item)
                break

        # --- Status bar ---
        self.action_label.setText(S.status.connected_to.format(name=connection_name, db=database_name))

        # --- Update ALL blocks' database panel (not just focused) ---
        if hasattr(widget, "editor"):
            for block in widget.editor.get_blocks():
                if hasattr(block, "db_panel"):
                    # Only update blocks using the session connection (no custom connection)
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn:
                        block._database_name = database_name
                        block.db_panel.set_database(database_name)

    def _on_object_explorer_refresh(self):
        """Object Explorer refresh - reloads schema from active connection"""
        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "session"):
            return

        session = current_widget.session
        connector = getattr(session, "connector", None)
        connection_name = getattr(session, "connection_name", "") or ""

        if connector and connector.is_connected():
            self._schema_service.invalidate_cache(connection_name)
            self._schema_service.load_schema(connector, connection_name)

    def _setup_dockable_panels(self):
        """Configures dockable panels (Results, Output, Variables) using QDockWidget.

        Cada dock contem um QStackedWidget. Cada sessao adiciona seus proprios
        paineis (ResultsViewer, OutputPanel, VariablesPanel) ao stack.
        Ao trocar de aba, troca-se a pagina visivel no stack.
        """
        from PyQt6.QtWidgets import QStackedWidget

        # Stacks - each session will have its page
        self._results_stack = QStackedWidget()
        self._output_stack = QStackedWidget()
        self._variables_stack = QStackedWidget()

        # Mapeamento session_id -> indice no stack
        self._session_panel_indices: dict = {}

        # Dock styling compartilhado
        dock_style_bottom = """
            QDockWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QDockWidget::title {
                background-color: #2d2d30;
                padding: 8px;
                font-weight: bold;
            }
        """

        # Results Panel
        self.results_dock = QDockWidget(S.dock.results, self)
        self.results_dock.setObjectName("ResultsDock")
        self.results_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.results_dock.setWidget(self._results_stack)
        self.results_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)

        # Output Panel
        self.output_dock = QDockWidget(S.dock.output, self)
        self.output_dock.setObjectName("OutputDock")
        self.output_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.output_dock.setWidget(self._output_stack)
        self.output_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)

        # Variables Panel
        self.variables_dock = QDockWidget(S.dock.variables, self)
        self.variables_dock.setObjectName("VariablesDock")
        self.variables_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.variables_dock.setWidget(self._variables_stack)
        self.variables_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)

        # Configure minimum sizes to ensure visibility
        self.results_dock.setMinimumHeight(180)
        self.output_dock.setMinimumHeight(180)
        self.variables_dock.setMinimumWidth(200)
        self.variables_dock.setMinimumHeight(180)

        # Tabifica Results e Output por padrao (fica em abas)
        self.tabifyDockWidget(self.results_dock, self.output_dock)

        # Results fica como aba ativa
        self.results_dock.raise_()

        # Esconder Results e Variables ate a primeira execucao
        self.results_dock.hide()
        self.variables_dock.hide()

    def _create_session_panels(self, session_id: str):
        """Creates panels (Results, Output, Variables) for a session and adds to stacks."""
        results = ResultsViewer(theme_manager=self.theme_manager)
        output = OutputPanel(theme_manager=self.theme_manager)
        variables = VariablesPanel(theme_manager=self.theme_manager)

        # Connect signals do painel de variaveis
        variables.insert_variable_name.connect(self._on_insert_variable_in_editor)
        variables.delete_variable.connect(self._on_delete_variable)

        r_idx = self._results_stack.addWidget(results)
        o_idx = self._output_stack.addWidget(output)
        v_idx = self._variables_stack.addWidget(variables)

        self._session_panel_indices[session_id] = {
            "results_idx": r_idx,
            "output_idx": o_idx,
            "variables_idx": v_idx,
            "results": results,
            "output": output,
            "variables": variables,
        }
        return results, output, variables

    def _remove_session_panels(self, session_id: str):
        """Removes panels of a session from stacks."""
        info = self._session_panel_indices.pop(session_id, None)
        if not info:
            return
        self._results_stack.removeWidget(info["results"])
        self._output_stack.removeWidget(info["output"])
        self._variables_stack.removeWidget(info["variables"])
        info["results"].deleteLater()
        info["output"].deleteLater()
        info["variables"].deleteLater()

        # Remove Object Explorer from session
        if hasattr(self, "_session_explorers"):
            self._remove_session_explorer(session_id)

    def _switch_session_panels(self, session_id: str):
        """Switches stacks to display panels of the active session.

        Usa setCurrentWidget() em vez de setCurrentIndex() para evitar
        bugs com indices invalidos apos remocao de widgets do stack.
        """
        info = self._session_panel_indices.get(session_id)
        if not info:
            return
        if info["results"]:
            self._results_stack.setCurrentWidget(info["results"])
        if info["output"]:
            self._output_stack.setCurrentWidget(info["output"])
        if info["variables"]:
            self._variables_stack.setCurrentWidget(info["variables"])

        # Trocar Object Explorer para a sessao ativa
        if hasattr(self, "_session_explorers"):
            self._switch_session_explorer(session_id)

    @property
    def global_results_viewer(self):
        """Returns the ResultsViewer of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["results"] if info else None

    @property
    def global_output_panel(self):
        """Returns the OutputPanel of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["output"] if info else None

    @property
    def global_variables_panel(self):
        """Returns the VariablesPanel of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["variables"] if info else None

    def _get_active_session_id(self) -> str:
        """Returns the session_id of the active tab."""
        widget = self._get_current_session_widget()
        if widget and hasattr(widget, "session"):
            return widget.session.session_id
        return None

    def _on_namespace_updated(self, namespace: dict):
        """Callback when namespace is updated"""
        panel = self.global_variables_panel
        if panel:
            panel.refresh_variables(namespace)

    def show_output(self, text: str):
        """Shows output in the active session panel"""
        panel = self.global_output_panel
        if panel:
            panel.append_output(text)

        # Mostra o painel de output
        self.show_panel("output")

    def show_panel(self, name: str):
        """Shows specific panel using QDockWidget.

        Para docks tabificados (results/output), raise_() sozinho nao
        funciona. Precisamos buscar o QTabBar do grupo e trocar a aba ativa.
        """
        dock_map = {
            "results": self.results_dock,
            "output": self.output_dock,
            "variables": self.variables_dock,
            "object_explorer": getattr(self, "object_explorer_dock", None),
        }
        dock = dock_map.get(name)
        if dock is None:
            return

        dock.show()
        dock.raise_()

        # Se mostrando results pela primeira vez, mostrar variables tambem
        if name == "results" and not self.variables_dock.isVisible():
            self.variables_dock.show()

        # Para docks tabificados, raise_() nao troca a aba visivel.
        # Precisamos encontrar o QTabBar que controla o grupo e selecionar
        # a aba correspondente manualmente.
        if name in ("results", "output"):
            self._activate_tabified_dock(dock)

    def _activate_tabified_dock(self, dock: QDockWidget):
        """Activates the correct tab in a group of tabified docks.

        When docks are tabified via tabifyDockWidget(), they share
        an internal QTabBar of QMainWindow. raise_() alone does not switch the tab.
        This method finds the correct QTabBar and selects the dock tab.
        """
        from PyQt6.QtWidgets import QTabBar

        target_title = dock.windowTitle()
        for tab_bar in self.findChildren(QTabBar):
            for i in range(tab_bar.count()):
                if tab_bar.tabText(i) == target_title:
                    tab_bar.setCurrentIndex(i)
                    return

    def hide_panel(self, name: str):
        """Hides specific panel using QDockWidget"""
        if name == "results":
            self.results_dock.hide()
        elif name == "output":
            self.output_dock.hide()
        elif name == "variables":
            self.variables_dock.hide()
        elif name == "object_explorer" and hasattr(self, "object_explorer_dock"):
            self.object_explorer_dock.hide()

    def _refresh_connections_list(self):
        """Updates the saved connections list"""
        self.connection_panel.refresh_connections()

    def _on_connection_double_click(self, item: QListWidgetItem):
        """Connects on double click on connection"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self._quick_connect(conn_name)

    def _toggle_panel_visibility(self, panel_name: str, visible: bool):
        """Controls visibility of a panel"""
        if visible:
            self.show_panel(panel_name)
        else:
            self.hide_panel(panel_name)

    def _toggle_output_tab(self, visible: bool):
        """Controls Output panel visibility"""
        if visible:
            self.show_panel("output")
        else:
            self.hide_panel("output")

    def _restore_default_layout(self):
        """Restores the default panel layout"""
        self._setup_default_layout()
        self._sync_view_menu_checks()

    def _save_dock_layout(self):
        """Save current dock layout to QSettings."""
        try:
            # Ensure toolbar objectName is set (required for saveState)
            if hasattr(self, 'main_toolbar'):
                self.main_toolbar.setObjectName("MainToolbar")
            settings = QSettings("DataPyn", "MainWindow")
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("windowState", self.saveState(3))  # version=3
            settings.sync()
        except Exception:
            pass

    def _restore_dock_layout(self):
        """Restores dock widget layout from QSettings."""
        self._restoring_layout = True
        try:
            settings = QSettings("DataPyn", "MainWindow")
            geometry = settings.value("geometry")
            window_state = settings.value("windowState")

            restored = False

            if geometry and len(geometry) > 20:
                self.restoreGeometry(geometry)

            if window_state and len(window_state) > 50:
                # Window is NOT visible at this point (show() is called later
                # by the splash screen), so restoreState runs invisibly.
                if self.restoreState(window_state, 3):  # version=3
                    restored = True
                # Re-ensure toolbar settings (restoreState may override them)
                if hasattr(self, 'main_toolbar'):
                    self.main_toolbar.setObjectName("MainToolbar")
                    self.main_toolbar.setMovable(False)
                    self.main_toolbar.setVisible(True)

            if not restored:
                self._setup_default_layout()

            # Ensure all non-hidden docks are properly docked (not floating)
            for dock in [self.connections_dock, self.results_dock, self.output_dock, self.variables_dock]:
                if dock.isFloating() and dock.isVisible():
                    dock.setFloating(False)

            # Sync view menu after a short delay (docks need to settle)
            QTimer.singleShot(300, self._finish_layout_restore)

        except Exception:
            self._setup_default_layout()
            self._restoring_layout = False

    def _finish_layout_restore(self):
        """Called after layout restore settles - sync menu and allow auto-save."""
        self._restoring_layout = False
        self._sync_view_menu_checks()

    def _setup_auto_save_layout(self):
        """Configure auto-save: save layout when dock visibility/position changes."""
        self._layout_save_timer = QTimer()
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(1000)
        self._layout_save_timer.timeout.connect(self._save_dock_layout)

        # Connect dock visibility changes to schedule save
        all_docks = [self.connections_dock, self.results_dock, self.output_dock, self.variables_dock]
        if hasattr(self, "object_explorer_dock"):
            all_docks.append(self.object_explorer_dock)
        for dock in all_docks:
            dock.visibilityChanged.connect(self._on_dock_changed)
            dock.dockLocationChanged.connect(self._on_dock_changed)
            dock.topLevelChanged.connect(self._on_dock_changed)

    def _on_dock_changed(self, *args):
        """Schedule layout save after dock state changes."""
        if getattr(self, "_restoring_layout", False):
            return
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def _clear_saved_layout(self):
        """Clears saved layout (for reset)."""
        try:
            settings = QSettings("DataPyn", "MainWindow")
            settings.remove("geometry")
            settings.remove("windowState")
            settings.sync()
        except Exception:
            pass

    def _setup_default_layout(self):
        """Configures the default dock layout."""
        try:
            all_docks = [self.connections_dock, self.results_dock, self.output_dock, self.variables_dock]
            if hasattr(self, "object_explorer_dock"):
                all_docks.append(self.object_explorer_dock)

            # Reset: make all non-floating
            for dock in all_docks:
                dock.setFloating(False)

            # Position docks in their default areas
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)

            if hasattr(self, "object_explorer_dock"):
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.object_explorer_dock)
                self.object_explorer_dock.hide()

            # Tabify Results and Output (bottom tabs)
            self.tabifyDockWidget(self.results_dock, self.output_dock)
            self.results_dock.raise_()

            # Show main panels
            self.connections_dock.show()
            self.results_dock.show()
            self.output_dock.show()
            self.variables_dock.show()

            # Window size
            screen = QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                w = min(1400, int(available.width() * 0.8))
                h = min(900, int(available.height() * 0.8))
                x = available.x() + (available.width() - w) // 2
                y = available.y() + (available.height() - h) // 2
                self.setGeometry(x, y, w, h)
            else:
                self.setGeometry(100, 100, 1400, 900)

        except Exception:
            # Fallback: just show docks
            try:
                self.connections_dock.show()
                self.results_dock.show()
                self.output_dock.show()
                self.variables_dock.show()
            except Exception:
                pass

    def _is_layout_valid(self):
        """Checks if the current layout is sane."""
        try:
            geom = self.geometry()
            if geom.width() < 400 or geom.height() < 300:
                return False
            return True
        except Exception:
            return False

    def _validate_restored_layout(self):
        """Validates layout after restore and fixes if necessary."""
        if not self._is_layout_valid():
            self._clear_saved_layout()
            self._setup_default_layout()

    def _reset_layout_completely(self):
        """Resets layout completely (clears settings and applies default)."""
        reply = QMessageBox.question(
            self,
            S.dialogs.confirm_reset_title,
            S.dialogs.layout_reset_confirm_msg if hasattr(S.dialogs, 'layout_reset_confirm_msg') else "This will completely reset the panel layout.\nAll layout settings will be lost.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._clear_saved_layout()
            self._setup_default_layout()
            self._sync_view_menu_checks()
            QMessageBox.information(self, S.dialogs.layout_reset_title, S.dialogs.layout_reset_msg)

    def _sync_view_menu_checks(self):
        """Sync View menu check states with actual dock visibility."""
        dock_action_map = [
            ("connections_dock", "connections_action"),
            ("results_dock", "results_action"),
            ("output_dock", "output_action"),
            ("variables_dock", "variables_action"),
            ("object_explorer_dock", "object_explorer_action"),
        ]
        for dock_attr, action_attr in dock_action_map:
            dock = getattr(self, dock_attr, None)
            action = getattr(self, action_attr, None)
            if dock and action:
                action.setChecked(dock.isVisible())

    def _quick_connect(self, connection_name: str):
        """
        Conecta a um banco de dados.
        - If there is no tab: creates a new tab
        - If current tab is connecting: creates a new tab
        - If current tab is available: switches the connection of that tab
        Connection happens in background (does not block the application).
        """
        # Get current tab
        current_widget = self._get_current_session_widget()

        # If there is no tab or current tab is connecting, create a new one
        if not current_widget or current_widget.is_connecting():
            self._new_session()
            current_widget = self._get_current_session_widget()

        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return

        # Get config (metadata only, not connection)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")

        # DELEGATE to tab - it manages connection in background
        # Returns True immediately (asynchronous)
        current_widget.connect_to_database(connection_name, password)

        # Update status (tab will show loading internally)
        self.action_label.setText(S.status.connecting_to.format(name=connection_name))

    def _connect_new_tab(self, connection_name: str):
        """
        Connects to a database ALWAYS creating a new tab.
        Used when CTRL+double-click or 'Connect in New Tab' in menu.
        """
        # Always create new tab
        self._new_session()
        current_widget = self._get_current_session_widget()

        if not current_widget:
            self._show_warning(S.dialogs.error, "Could not create new tab")
            return

        # Get config (metadata only, not connection)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        # Get password if necessary
        password = ""
        if not config.get("use_windows_auth", False):
            password = config.get("password", "")

        # DELEGATE to tab - it manages connection in background
        current_widget.connect_to_database(connection_name, password)

        # Update status
        self.action_label.setText(S.status.connecting_to_new_tab.format(name=connection_name))

    def _create_menus(self):
        """Creates the menus"""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu(S.menu.file)

        new_action = QAction(S.menu.new_tab, self)
        # Shortcut managed by ShortcutManager (Ctrl+T)
        new_action.triggered.connect(self._new_session)
        file_menu.addAction(new_action)

        open_action = QAction(S.menu.open, self)
        # Shortcut managed by ShortcutManager (Ctrl+O)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        save_action = QAction(S.menu.save, self)
        # Shortcut managed by ShortcutManager (Ctrl+S)
        save_action.triggered.connect(self._save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction(S.menu.save_as, self)
        # Shortcut managed by ShortcutManager (Ctrl+Shift+S)
        save_as_action.triggered.connect(self._save_file_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        export_script_action = QAction(S.menu.export_script, self)
        if HAS_QTAWESOME:
            export_script_action.setIcon(qta.icon("mdi.file-export", color="#b0b0b0"))
        # Shortcut managed by ShortcutManager (Ctrl+Shift+E)
        export_script_action.triggered.connect(self._export_as_script)
        file_menu.addAction(export_script_action)

        file_menu.addSeparator()

        exit_action = QAction(S.menu.exit, self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)  # Keep system default Quit
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Connection Menu
        conn_menu = menubar.addMenu(S.menu.connection)

        manage_conn_action = QAction(S.menu.manage_connections, self)
        if HAS_QTAWESOME:
            manage_conn_action.setIcon(self.icons["database"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+M)
        manage_conn_action.triggered.connect(self._manage_connections)
        conn_menu.addAction(manage_conn_action)

        conn_menu.addSeparator()

        new_conn_action = QAction(S.menu.new_connection, self)
        if HAS_QTAWESOME:
            new_conn_action.setIcon(self.icons["plug"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+D)
        new_conn_action.triggered.connect(self._new_connection)
        conn_menu.addAction(new_conn_action)

        disconnect_action = QAction(S.menu.disconnect, self)
        if HAS_QTAWESOME:
            disconnect_action.setIcon(self.icons["trash"])
        disconnect_action.triggered.connect(self._disconnect)
        conn_menu.addAction(disconnect_action)

        # Run Menu
        run_menu = menubar.addMenu(S.menu.run)

        run_current_action = QAction(S.menu.run_current_block, self)
        if HAS_QTAWESOME:
            run_current_action.setIcon(self.icons["play"])
        # Shortcut managed by ShortcutManager (F5)
        run_current_action.triggered.connect(self._execute_current_block)
        run_menu.addAction(run_current_action)

        run_all_action = QAction(S.menu.run_all_blocks, self)
        if HAS_QTAWESOME:
            run_all_action.setIcon(qta.icon("mdi.fast-forward", color="#b0b0b0"))
        # Shortcut managed by ShortcutManager (Ctrl+F5)
        run_all_action.triggered.connect(self._execute_all_blocks)
        run_menu.addAction(run_all_action)

        run_menu.addSeparator()

        clear_results_action = QAction(S.menu.clear_results, self)
        if HAS_QTAWESOME:
            clear_results_action.setIcon(self.icons["trash"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+C)
        clear_results_action.triggered.connect(self._clear_results)
        run_menu.addAction(clear_results_action)

        # View Menu
        view_menu = menubar.addMenu(S.menu.view)

        # Panels Submenu
        panels_menu = view_menu.addMenu(S.menu.panels)

        # Results panel toggle
        results_action = QAction(S.menu.panel_results, self)
        results_action.setCheckable(True)
        results_action.setChecked(True)
        results_action.triggered.connect(lambda checked: self._toggle_panel_visibility("results", checked))
        panels_menu.addAction(results_action)
        self.results_action = results_action

        # Output panel toggle
        output_action = QAction(S.menu.panel_output, self)
        output_action.setCheckable(True)
        output_action.setChecked(True)
        output_action.triggered.connect(lambda checked: self._toggle_output_tab(checked))
        panels_menu.addAction(output_action)
        self.output_action = output_action

        # Variables panel toggle
        variables_action = QAction(S.menu.panel_variables, self)
        variables_action.setCheckable(True)
        variables_action.setChecked(True)
        variables_action.triggered.connect(lambda checked: self._toggle_panel_visibility("variables", checked))
        panels_menu.addAction(variables_action)
        self.variables_action = variables_action

        # Connections panel toggle
        connections_action = QAction(S.menu.panel_connections, self)
        connections_action.setCheckable(True)
        connections_action.setChecked(True)
        connections_action.triggered.connect(lambda checked: self.connections_dock.setVisible(checked))
        panels_menu.addAction(connections_action)
        self.connections_action = connections_action

        # Object Explorer toggle
        object_explorer_action = QAction(S.menu.panel_object_explorer, self)
        object_explorer_action.setCheckable(True)
        object_explorer_action.setChecked(False)
        object_explorer_action.triggered.connect(
            lambda checked: self._toggle_panel_visibility("object_explorer", checked)
        )
        panels_menu.addAction(object_explorer_action)
        self.object_explorer_action = object_explorer_action

        view_menu.addSeparator()

        # Restore default view
        restore_action = QAction(S.menu.restore_default_view, self)
        restore_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        restore_action.triggered.connect(self._restore_default_layout)
        view_menu.addAction(restore_action)

        # Reset layout completely (clears saved settings)
        reset_layout_action = QAction(S.menu.complete_layout_reset, self)
        reset_layout_action.setShortcut(QKeySequence("Ctrl+Shift+Alt+R"))
        reset_layout_action.triggered.connect(self._reset_layout_completely)
        view_menu.addAction(reset_layout_action)

        # Tools Menu
        tools_menu = menubar.addMenu(S.menu.tools)

        packages_action = QAction(S.menu.package_manager, self)
        if HAS_QTAWESOME:
            packages_action.setIcon(qta.icon("mdi.package-variant", color="#b0b0b0"))
        packages_action.triggered.connect(self._show_package_manager)
        tools_menu.addAction(packages_action)

        tools_menu.addSeparator()

        settings_action = QAction(S.menu.shortcut_settings, self)
        if HAS_QTAWESOME:
            settings_action.setIcon(self.icons["cog"])
        # Shortcut managed by ShortcutManager (Ctrl+,)
        settings_action.triggered.connect(self._show_settings)
        tools_menu.addAction(settings_action)

        tools_menu.addSeparator()

        # Auto-update toggle
        auto_update_action = QAction(S.menu.auto_update, self)
        auto_update_action.setCheckable(True)
        auto_update_action.setChecked(self.auto_update_service.is_auto_update_enabled())
        auto_update_action.triggered.connect(self._toggle_auto_update)
        tools_menu.addAction(auto_update_action)
        self._auto_update_action = auto_update_action  # Save reference to update state

        # Help Menu
        help_menu = menubar.addMenu(S.menu.help)

        check_updates_action = QAction(S.menu.check_updates, self)
        if HAS_QTAWESOME:
            check_updates_action.setIcon(qta.icon("mdi.update", color="#b0b0b0"))
        check_updates_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(check_updates_action)

        help_menu.addSeparator()

        about_action = QAction(S.menu.about, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Creates the toolbar using MainToolbar"""
        self.main_toolbar = MainToolbar(theme_manager=self.theme_manager)
        self.main_toolbar.setObjectName("MainToolbar")  # Para saveState/restoreState
        self.addToolBar(self.main_toolbar)

        # Connect signals
        self.main_toolbar.new_connection_clicked.connect(self._new_connection)
        self.main_toolbar.new_tab_clicked.connect(self._new_session)
        self.main_toolbar.run_clicked.connect(self._execute_from_toolbar)

    def _execute_from_toolbar(self):
        """Executes code from the current editor via toolbar button"""
        editor = self._get_current_editor()
        if not editor:
            return

        # Toolbar run button executes only the focused block
        if hasattr(editor, "execute_focused_block"):
            editor.execute_focused_block()
        elif hasattr(editor, "get_selected_or_all_text"):
            # Fallback para editor antigo
            code = editor.get_selected_or_all_text()
            if code.strip():
                self._execute_cross_syntax(code)

    def _create_statusbar(self):
        """Creates the status bar using MainStatusBar"""
        self.main_statusbar = MainStatusBar(theme_manager=self.theme_manager)
        self.setStatusBar(self.main_statusbar)

        # Create compatibility properties
        self.statusbar = self.main_statusbar
        self.connection_status_bar = self.main_statusbar.connection_label
        self.action_label = self.main_statusbar.action_label
        self.execution_label = self.main_statusbar.timer_label

        # Timers - usar os do componente
        self._is_executing = False
        self._execution_timer = QElapsedTimer()
        self._execution_update_timer = QTimer()
        self._execution_update_timer.timeout.connect(self._update_execution_time)

    def _start_execution_timer(self, mode: str = ""):
        """Starts the execution timer"""
        self._is_executing = True
        self._execution_mode = mode
        self._execution_timer.start()
        self._execution_update_timer.start(100)
        # Estilizar label UMA vez (nao a cada tick)
        self.execution_label.setStyleSheet("""
            QLabel {
                color: #FFD700;
                font-weight: bold;
                padding: 4px 12px;
                background: rgba(255, 215, 0, 0.15);
                border-left: 3px solid #FFD700;
                border-radius: 2px;
            }
        """)
        self._update_execution_time()
        self.main_statusbar.start_timer()

    def _stop_execution_timer(self):
        """Stops the execution timer and shows final time"""
        self._execution_update_timer.stop()
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
            self.main_statusbar.stop_timer()
            self.execution_label.setText(f"{elapsed:.2f}s")
            self.execution_label.setStyleSheet("""
                QLabel {
                    color: #00FF00;
                    font-weight: bold;
                    padding: 0 10px;
                }
            """)
            # Clears after 5 seconds
            QTimer.singleShot(5000, self._clear_execution_label)
        self._is_executing = False

    def _update_execution_time(self):
        """Updates the label with execution time"""
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
            mode = f"{self._execution_mode}" if self._execution_mode else "Code"
            self.execution_label.setText(S.status.running_mode_elapsed.format(mode=mode, elapsed=f"{elapsed:.1f}"))

    def _clear_execution_label(self):
        """Clears the execution label"""
        if not self._is_executing:
            self.execution_label.setText("")

    def _setup_shortcuts(self):
        """Configures global application shortcuts"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt

        # Guardar shortcuts como atributos para evitar garbage collection
        self._shortcuts = []

        # Map actions to callbacks
        shortcuts_map = {
            # Execution
            "execute_sql": self._execute_current_block,
            "execute_all": self._execute_all_blocks,
            "execute_block_advance": self._execute_and_advance,
            "clear_results": self._clear_results,
            # File
            "open_file": self._open_file,
            "save_file": self._save_file,
            "save_as": self._save_file_as,
            "export_script": self._export_as_script,
            # Sessions
            "new_tab": self._new_session,
            "new_session": self._new_session,
            "close_tab": self._close_current_session,
            "add_block": self._add_block_to_current_session,
            # Edicao
            "find": self._find_in_editor,
            "replace": self._replace_in_editor,
            "format_code": self._format_current_block,
            # Conexoes
            "manage_connections": self._manage_connections,
            "new_connection": self._new_connection,
            # Schema
            "reload_schema": self._reload_schema,
            # Tools
            "settings": self._show_settings,
        }

        # Create shortcuts from ShortcutManager
        app_keys = set()
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
                app_keys.add(key_sequence)

        # Informar editores quais atalhos o app usa
        from src.editors.code_editor import CodeEditor
        CodeEditor.set_app_shortcuts(app_keys)

        # Informar editores sobre atalhos configuraveis do editor (QScintilla)
        editor_shortcuts = {
            action: self.shortcut_manager.get_shortcut(action)
            for action in self.shortcut_manager.get_all_shortcuts()
            if action.startswith("editor_")
        }
        CodeEditor.set_editor_shortcuts(editor_shortcuts)

    def _reload_shortcuts(self):
        """Re-registers all shortcuts (called when user changes settings)"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt

        # Limpar atalhos antigos
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts.clear()

        # Map actions to callbacks
        shortcuts_map = {
            # Execution
            "execute_sql": self._execute_current_block,
            "execute_all": self._execute_all_blocks,
            "execute_block_advance": self._execute_and_advance,
            "clear_results": self._clear_results,
            # File
            "open_file": self._open_file,
            "save_file": self._save_file,
            "save_as": self._save_file_as,
            "export_script": self._export_as_script,
            # Sessions
            "new_tab": self._new_session,
            "new_session": self._new_session,
            "close_tab": self._close_current_session,
            "add_block": self._add_block_to_current_session,
            # Edicao
            "find": self._find_in_editor,
            "replace": self._replace_in_editor,
            "format_code": self._format_current_block,
            # Conexoes
            "manage_connections": self._manage_connections,
            "new_connection": self._new_connection,
            # Schema
            "reload_schema": self._reload_schema,
            # Tools
            "settings": self._show_settings,
        }

        # Create new shortcuts
        app_keys = set()
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
                app_keys.add(key_sequence)

        # Update editors
        from src.editors.code_editor import CodeEditor
        CodeEditor.set_app_shortcuts(app_keys)

        # Atualizar atalhos configuraveis do editor (QScintilla)
        editor_shortcuts = {
            action: self.shortcut_manager.get_shortcut(action)
            for action in self.shortcut_manager.get_all_shortcuts()
            if action.startswith("editor_")
        }
        CodeEditor.set_editor_shortcuts(editor_shortcuts)

        # Re-aplicar keybindings nos editores ja existentes
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if isinstance(widget, SessionWidget):
                for block in widget.editor.get_blocks():
                    if isinstance(block.editor, CodeEditor):
                        block.editor._apply_editor_keybindings()

    # NOTA: _new_session() definido mais abaixo (linha ~2745) com guard contra duplicacao

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
            new_widget.execute_cross_syntax.connect(lambda code: self._execute_cross_syntax_for_session(session, code))
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
            if block and hasattr(block, "editor"):
                block.editor._open_find()

    def _replace_in_editor(self):
        """Opens find+replace in the focused block of the current editor."""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            block = widget.editor.get_focused_block()
            if block and hasattr(block, "editor"):
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
            # Preserve cursor position
            sci = block.editor._sci
            line, col = sci.getCursorPosition()
            block.editor.set_text(formatted)
            # Restaurar cursor (limitar a linhas existentes)
            max_line = sci.lines() - 1
            sci.setCursorPosition(min(line, max_line), col)
            self.action_label.setText(S.status.code_formatted.format(lang=lang.upper()))
        else:
            self.action_label.setText(S.status.code_already_formatted.format(lang=lang.upper()))

    def _add_block_to_current_session(self):
        """Adds a new code block in the current session"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            widget.editor.add_block()

    def _manage_connections(self):
        """Opens the connection management dialog"""
        dialog = ConnectionsManagerDialog(self.connection_manager, theme_manager=self.theme_manager, parent=self)
        dialog.connection_selected.connect(self._connect_from_manager)
        dialog.exec()
        # Update list after closing dialog
        self._refresh_connections_list()

    def _connect_from_manager(self, name: str, config: dict):
        """Connects from the connection manager - same behavior as the side panel"""
        self._quick_connect(name)

    def _new_connection(self):
        """Opens dialog for new connection"""
        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            name, config = dialog.get_result()

            # Save connection
            self.connection_manager.save_connection_config(
                name,
                config["db_type"],
                config["host"],
                config["port"],
                config["database"],
                config.get("username", ""),
                config.get("save_password", False),
                config.get("password", ""),
                config.get("group", ""),
                config.get("use_windows_auth", False),
                config.get("color", ""),
                config.get("trust_server_certificate", True),
            )

            self._update_connection_status()
            self._refresh_connections_list()
            self._log_info(S.status.connection_created.format(name=name))
            self.action_label.setText(S.status.connection_created.format(name=name))

    def _edit_connection(self, connection_name: str):
        """Opens dialog to edit a specific connection"""
        # Get connection config
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning(S.dialogs.error, f"Connection '{connection_name}' not found")
            return

        dialog = ConnectionEditDialog(
            connection_name=connection_name,
            config=config,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            name, new_config = dialog.get_result()

            # Se mudou o nome, deletar antiga
            if name != connection_name:
                self.connection_manager.delete_connection_config(connection_name)

            # Save connection
            self.connection_manager.save_connection_config(
                name,
                new_config["db_type"],
                new_config["host"],
                new_config["port"],
                new_config["database"],
                new_config.get("username", ""),
                new_config.get("save_password", False),
                new_config.get("password", ""),
                new_config.get("group", ""),
                new_config.get("use_windows_auth", False),
                new_config.get("color", ""),
                new_config.get("trust_server_certificate", True),
            )

            self._update_connection_status()
            self._refresh_connections_list()
            self._log_info(S.status.connection_updated.format(name=name))
            self.action_label.setText(S.status.connection_updated.format(name=name))

    # === Helper methods for dialogs with icons ===

    def _show_warning(self, title: str, message: str):
        """Shows warning with icon"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_error(self, title: str, message: str):
        """Shows error with icon"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_info(self, title: str, message: str):
        """Shows information with icon"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _disconnect(self):
        """Disconnects the current session"""
        session = self.session_manager.focused_session
        if session and session.is_connected:
            # Clear session connection
            session.clear_connection()
            self._update_connection_status()
            self.action_label.setText(S.status.disconnected)

    def _update_connection_status(self):
        """Updates the connection status of the current session"""
        session = self.session_manager.focused_session

        if session and session.is_connected:
            conn_name = session.connection_name
            connector = session.connector

            # Get connection config
            config = self.connection_manager.get_connection_config(conn_name)
            host = config.get("host", "localhost") if config else "localhost"
            db = config.get("database", "") if config else ""
            db_type = config.get("db_type", "") if config else ""

            # === PAINEL LATERAL ===
            self.connection_panel.set_active_connection(conn_name, host=host, database=db, db_type=db_type)

            # Highlight active connection in list
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == conn_name:
                    self.connections_list.setCurrentItem(item)
                    break

            # === STATUSBAR ===
            conn_display = f"{conn_name} @ {host}/{db}"
            self.connection_status_bar.setText(conn_display)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }
            """)

            # Use configured connection color (or default blue)
            status_color = config.get("color", "#007acc") if config else "#007acc"
            if not status_color:
                status_color = "#007acc"
            self.statusbar.setStyleSheet(f"QStatusBar {{ background-color: {status_color}; color: white; }}")
        else:
            # === PAINEL LATERAL ===
            self.connection_panel.set_disconnected()
            self.connections_list.clearSelection()

            # === STATUSBAR ===
            self.connection_status_bar.setText(S.status.disconnected)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }
            """)
            # Barra de status cinza escuro quando desconectado
            self.statusbar.setStyleSheet("QStatusBar { background-color: #3e3e42; color: white; }}")

    def _execute_current_block(self):
        """Executes the currently focused block with its language"""
        editor = self._get_current_editor()
        if not editor:
            return

        # If it's a BlockEditor, executes only the focused block
        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor.execute_focused_block()
        else:
            # Legacy editor - executes as Python by default
            code = editor.get_selected_or_all_text().strip()
            if code:
                self._execute_python(code)

    def _execute_all_blocks(self):
        """Executes all blocks in sequence"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor.execute_all_blocks()
        else:
            # Editor antigo - executa tudo como Python
            code = editor.get_selected_or_all_text().strip()
            if code:
                self._execute_python(code)

    def _execute_and_advance(self):
        """Executes focused block and advances to next"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor._execute_focused_and_advance()

    def _force_execute_sql(self):
        """Forces execution of current block as SQL"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()

        if code and code.strip():
            self._execute_sql(code.strip())

    def _force_execute_python(self):
        """Forces execution of current block as Python"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()

        if code and code.strip():
            self._execute_python(code.strip())

    def _force_execute_cross(self):
        """Forces execution of current block as Cross-Syntax"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()

        if code and code.strip():
            self._execute_cross_syntax(code.strip())

    def _execute_sql(self, query: str):
        """Executes SQL query in background"""
        query = query.strip()
        if not query:
            # Get from current tab if empty
            editor = self._get_current_editor()
            if editor:
                query = editor.get_selected_or_all_text().strip()
            if not query:
                return

        # Use current session connection
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            self._show_warning(
                S.dialogs.warning, S.dialogs.cross_no_connection_msg
            )
            return

        connector = session.connector

        # Detect USE database command (runs synchronously since it's fast)
        # Supports: USE db, USE [db], USE `db`, USE db;
        use_match = re.match(r"^\s*USE\s+[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$", query, re.IGNORECASE)
        if use_match:
            database_name = use_match.group(1)
            try:
                self._start_execution_timer("SQL")
                self.action_label.setText(S.status.sql_switching_database.format(name=database_name))

                connector.change_database(database_name)

                # Update statusbar
                self._update_connection_status()

                # Reload Object Explorer for the new database
                connection_name = getattr(session, "connection_name", "") or ""
                if connection_name:
                    self._schema_service.invalidate_cache(connection_name)
                    self._schema_service.load_schema(connector, connection_name)

                    # Emit connection change signal to update UI
                    current_widget = self._get_current_session_widget()
                    if current_widget and hasattr(current_widget, "connection_changed"):
                        current_widget.connection_changed.emit(connection_name, database_name)

                # Update focused block's database panel (direct update to avoid signal loop)
                current_widget = self._get_current_session_widget()
                if current_widget and hasattr(current_widget, "editor"):
                    focused_block = current_widget.editor.get_focused_block()
                    if not focused_block:
                        focused_block = current_widget.editor.get_last_focused_block()
                    if focused_block and hasattr(focused_block, "db_panel"):
                        focused_block._database_name = database_name
                        focused_block.db_panel.set_database(database_name)

                self._log_info(S.status.database_changed.format(name=database_name))
                self.action_label.setText(S.status.sql_database.format(name=database_name))
                self._stop_execution_timer()
                return

            except Exception as e:
                self._stop_execution_timer()
                QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_switching_db.format(error=str(e)))
                self.action_label.setText(S.status.sql_error_switching)
                return

        # Background execution
        self._start_execution_timer("SQL")
        self.action_label.setText(S.status.sql_running_query)

        # Mark tab as running
        running_tab_index = self._mark_tab_running(True)

        # Save current database to detect change via USE within batch
        try:
            current_db_before = connector.get_current_database() if hasattr(connector, "get_current_database") else ""
        except Exception:
            current_db_before = ""

        # Create thread and worker
        thread = QThread()
        worker = SqlWorker(connector, query)
        worker.moveToThread(thread)

        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda df, err: self._on_sql_finished(df, err, thread, running_tab_index, current_db_before)
        )

        # Safe cleanup: only delete when thread actually stops
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        # Keep reference
        self._worker_threads.append((thread, worker))

        # Start
        thread.start()

    def _display_figures_in_results(self, figures: list, label: str = "Result"):
        """Displays rich outputs (images/HTML/JSON) in the results panel."""
        results_panel = self.global_results_viewer
        if not results_panel or not figures:
            return
        results_panel.display_rich_output(figures, label)
        self.show_panel("results")

    def _handle_execution_result(self, result=None, error=None, execution_type="Unknown", additional_info=""):
        """
        Centralized method for handling execution results

        Args:
            result: Execution result (DataFrame, string, etc) or None
            error: Mensagem de erro ou None
            execution_type: Execution type ("SQL", "Python", "Cross-Syntax")
            additional_info: Additional information for logs
        """
        if error:
            # ERRO → OUTPUT (console)
            self._show_error_output(f"[{execution_type}] {error}")
            self.action_label.setText(S.status.execution_error_generic.format(type=execution_type))
            return False  # Indica erro

        if result is None:
            # SEM RESULTADO → OUTPUT (console)
            self.show_panel("output")
            return True

        # SUCESSO -> Decidir painel baseado no tipo do resultado
        import pandas as pd

        results_panel = self.global_results_viewer

        if isinstance(result, pd.DataFrame):
            # DATAFRAME -> GRID (results)
            if results_panel:
                results_panel.display_dataframe(result, f"{execution_type} Result")
            self.show_panel("results")
            rows = len(result)
            self._log_info(f"[{execution_type}] {additional_info or S.log.df_displayed.format(type=execution_type, rows=f'{rows:,}')}")
            return True

        elif isinstance(result, (list, tuple)) and len(result) > 0:
            # LISTA/TUPLA → Tentar converter para DataFrame
            try:
                df = pd.DataFrame(result)
                if len(df) > 0:
                    if results_panel:
                        results_panel.display_dataframe(df, f"{execution_type} Result")
                    self.show_panel("results")
                    self._log_info(S.log.list_converted.format(type=execution_type, rows=len(df)))
                    return True
            except:
                pass

            # If could not convert, goes to output
            self._log(f"[{execution_type}] {repr(result)}")
            return True

        elif isinstance(result, dict):
            # DICT → Tentar converter para DataFrame
            try:
                df = (
                    pd.DataFrame([result])
                    if not isinstance(list(result.values())[0], (list, tuple))
                    else pd.DataFrame(result)
                )
                if results_panel:
                    results_panel.display_dataframe(df, f"{execution_type} Result")
                self.show_panel("results")
                self._log_info(S.log.dict_converted.format(type=execution_type))
                return True
            except:
                pass

            # If could not convert, goes to output
            self._log(f"[{execution_type}] {repr(result)}")
            return True

        else:
            # OUTROS TIPOS -> OUTPUT (console)
            self._log(f"[{execution_type}] {repr(result)}")
            return True

    def _remove_worker_thread(self, thread):
        """Removes thread from active workers list (called via thread.finished)."""
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]

    def _on_sql_finished(self, df, error, thread, tab_index, db_before=""):
        """Callback quando SQL termina"""
        self._stop_execution_timer()

        # Remove running mark
        self._mark_tab_running(False, tab_index)

        # Stop thread (finished signal handles cleanup)
        thread.quit()

        # Detectar mudanca de banco via USE dentro do batch SQL
        self._check_database_changed_after_sql(db_before)

        # FORCAR: Se ha erro, SEMPRE mostrar output
        if error:
            self._show_error_output(f"[SQL] Error: {error}")
            self.action_label.setText(S.status.sql_execution_error)
            self._send_notification(S.notification.sql_query, S.notification.error.format(error=str(error)[:50]), success=False, tab_index=tab_index)
            return

        # ONLY if there is no error, use centralized method
        success = self._handle_execution_result(
            result=df,
            error=None,  # Ensure error is None here
            execution_type="SQL",
            additional_info=f"Executed successfully ({len(df):,} rows returned)" if df is not None else "",
        )

        if success:
            rows = len(df) if df is not None else 0
            self.action_label.setText(S.status.sql_rows_returned.format(rows=f"{rows:,}"))
            self._send_notification(
                S.notification.sql_query, S.notification.complete_rows.format(rows=f"{rows:,}"), success=True, tab_index=tab_index
            )

    def _check_database_changed_after_sql(self, db_before: str):
        """Checks if the database changed after SQL execution (e.g. USE within batch).

        Se mudou, recarrega o Object Explorer com o novo banco.
        Propaga a mudanca para: connection panel, status bar, tab color, todos os blocos.
        """
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

        if db_after and db_after.lower() != db_before.lower():
            connection_name = getattr(session, "connection_name", "") or ""
            if connection_name:
                self._schema_service.invalidate_cache(connection_name)
                self._schema_service.load_schema(connector, connection_name)

                current_widget = self._get_current_session_widget()
                if current_widget and hasattr(current_widget, "connection_changed"):
                    current_widget.connection_changed.emit(connection_name, db_after)

                # --- Update connection panel with actual db_after ---
                config = self.connection_manager.get_connection_config(connection_name)
                if config:
                    host = config.get("host", "localhost")
                    db_type = config.get("db_type", "")
                    self.connection_panel.set_active_connection(
                        connection_name, host=host, database=db_after, db_type=db_type
                    )

                    # --- Tab color ---
                    color = config.get("color", "#007ACC") or "#007ACC"
                    for i in range(self.session_tabs.count()):
                        tab_widget = self.session_tabs.widget(i)
                        if isinstance(tab_widget, SessionWidget) and tab_widget == current_widget:
                            self.session_tabs.set_tab_connection_color(i, color)
                            break

                # --- Highlight connection in list ---
                for i in range(self.connections_list.count()):
                    item = self.connections_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == connection_name:
                        self.connections_list.setCurrentItem(item)
                        break

                # --- Status bar ---
                self.action_label.setText(S.status.connected_to.format(name=connection_name, db=db_after))

                # --- Update ALL blocks' database panel ---
                if current_widget and hasattr(current_widget, "editor"):
                    for block in current_widget.editor.get_blocks():
                        if hasattr(block, "db_panel"):
                            block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                            if not block_conn:
                                block._database_name = db_after
                                block.db_panel.set_database(db_after)

    def _execute_python(self, code: str):
        """Executes Python code in background"""
        code = code.strip()
        if not code:
            # Get from current tab if empty
            editor = self._get_current_editor()
            if editor:
                code = editor.get_selected_or_all_text().strip()
            if not code:
                return

        self._start_execution_timer("Python")
        self.action_label.setText(S.status.python_running)

        # Mark tab as running
        running_tab_index = self._mark_tab_running(True)

        # Namespace with DataFrames
        namespace = self.results_manager.get_namespace()

        # Always use centralized logic
        is_expression = False

        # Create thread and worker
        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression)
        worker.moveToThread(thread)

        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, output, err, namespace, figures: self._on_python_finished(
                result, output, err, namespace, figures, thread, running_tab_index
            )
        )

        # Safe cleanup: only delete when thread actually stops
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        # Keep reference
        self._worker_threads.append((thread, worker))

        # Start
        thread.start()

    def _on_python_finished(self, result_value, output, error, updated_namespace, figures, thread, tab_index):
        """Callback quando Python termina"""
        self._stop_execution_timer()

        # Save updated namespace
        self.results_manager.update_namespace(updated_namespace)

        # Update Python autocomplete with updated namespace
        if updated_namespace:
            self._push_python_namespace(updated_namespace)

        # Remove running mark
        self._mark_tab_running(False, tab_index)

        # Stop thread (finished signal handles cleanup)
        thread.quit()

        # FORCE: If there is an error, ALWAYS show output first
        if error:
            self._show_error_output(f"[Python] Error: {error}")
            self.action_label.setText(S.status.python_execution_error)
            self._send_notification(S.notification.python, S.notification.error.format(error=str(error)[:50]), success=False, tab_index=tab_index)
            return

        # Show output from print()/stderr (if any) -> output panel
        if output:
            self._log(output.strip())

        # Decide what to show in the Results panel:
        # Priority: rich outputs (charts/html/json) > DataFrame > nothing
        has_figures = bool(figures)
        results_panel = self.global_results_viewer

        if has_figures and result_value is not None and isinstance(result_value, pd.DataFrame):
            # Rich outputs + DataFrame: show rich output in results
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self.show_panel("results")
            self._update_variables_view()
            self.action_label.setText(S.status.python_chart_data)
            self._send_notification(S.notification.python, S.notification.chart_data, success=True, tab_index=tab_index)
        elif has_figures:
            # Only rich outputs: show in results
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self.show_panel("results")
            self._update_variables_view()
            self.action_label.setText(S.status.python_result_displayed)
            self._send_notification(S.notification.python, S.notification.result_displayed, success=True, tab_index=tab_index)
        elif result_value is not None:
            # Result without charts: use centralized handler
            success = self._handle_execution_result(result=result_value, error=None, execution_type="Python")
            if success:
                self._update_variables_view()
                self.action_label.setText(S.status.python_executed)
                self._send_notification(S.notification.python, S.notification.executed, success=True, tab_index=tab_index)
        else:
            # No result, no charts: only output
            if output:
                self.show_panel("output")
            self._update_variables_view()
            self.action_label.setText(S.status.python_executed)
            self._send_notification(S.notification.python, S.notification.executed, success=True, tab_index=tab_index)

    def _execute_cross_syntax(self, code: str):
        """Executes cross syntax {{ SQL }} code in background"""
        code = code.strip()
        if not code:
            # Get from current tab if empty
            editor = self._get_current_editor()
            if editor:
                code = editor.get_selected_or_all_text().strip()
            if not code:
                return

        self._start_execution_timer("Cross")
        self.action_label.setText(S.status.cross_running)

        # Mark tab as running
        running_tab_index = self._mark_tab_running(True)

        # Validate syntax first (synchronous, it's fast)
        is_valid, error = self.mixed_executor.validate_syntax(code)
        if not is_valid:
            self._stop_execution_timer()
            self._mark_tab_running(False, running_tab_index)
            self._show_error_output(f"[Cross-Syntax] Syntax error: {error}")
            self.action_label.setText(S.status.cross_syntax_error)
            return

        # Use current session connection
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            self._stop_execution_timer()
            self._mark_tab_running(False, running_tab_index)
            QMessageBox.warning(
                self, S.dialogs.warning, S.dialogs.cross_no_connection_msg
            )
            self.action_label.setText(S.status.cross_no_connection)
            return

        # Keep reference to session that started execution
        executing_session = session

        self.mixed_executor.db_connector = session.connector

        # Create thread and worker - use namespace of the executing session
        thread = QThread()
        worker = CrossSyntaxWorker(self.mixed_executor, code, session.namespace)
        worker.moveToThread(thread)

        # Connect signals - pass the session that started
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, err: self._on_cross_finished(result, err, code, thread, running_tab_index, executing_session)
        )

        # Safe cleanup: only delete when thread actually stops
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        # Keep reference
        self._worker_threads.append((thread, worker))

        # Start
        thread.start()

    def _on_cross_finished(self, result, error, code, thread, tab_index, session):
        """Callback quando Cross-Syntax termina

        Args:
            result: Execution result
            error: Error if any
            code: Executed code
            thread: Thread used
            tab_index: Tab index
            session: Session that STARTED the execution (not the currently focused one)
        """
        self._stop_execution_timer()

        # Remove running mark
        self._mark_tab_running(False, tab_index)

        # Stop thread (finished signal handles cleanup)
        thread.quit()

        # Mark blocks as not executing
        widget = self._get_current_session_widget()
        if widget and hasattr(widget.editor, "mark_execution_finished"):
            widget.editor.mark_execution_finished()

        # FORCE: If there is an error, ALWAYS show output first
        if error:
            self._show_error_output(f"[Cross-Syntax] Error: {error}")
            self.action_label.setText(S.status.cross_execution_error)
            self._send_notification(S.notification.cross_syntax, S.notification.error.format(error=str(error)[:50]), success=False, tab_index=tab_index)
            return

        # Show output first (if any)
        if result and result.get("output"):
            self._log(result["output"].strip())

        # Show executed queries in log
        if result and result.get("queries_executed"):
            # Display created variables
            queries = self.mixed_executor.extract_queries(code)
            for var_name, sql in queries:
                # Search in namespace of the session that executed
                var_value = session.namespace.get(var_name)
                if var_value is not None:
                    if isinstance(var_value, pd.DataFrame):
                        rows = len(var_value)
                        self._log_info(S.log.cross_variable_created.format(name=var_name, rows=f"{rows:,}"))
                    else:
                        self._log_info(S.log.cross_variable_created_no_rows.format(name=var_name))

        # ONLY if there is no error, use centralized method
        success = self._handle_execution_result(
            result=result.get("result") if result else None,
            error=None,  # Ensure error is None here
            execution_type="Cross-Syntax",
        )

        if success:
            # Updates variables - from the session that executed, if still focused
            if session == self.session_manager.focused_session:
                self._update_variables_view()
                # Update Python autocomplete with updated namespace
                self._push_python_namespace(session.namespace)

            self.action_label.setText(S.status.cross_executed)

            # Success notification
            queries_count = result.get("queries_executed", 0) if result else 0
            self._send_notification(
                S.notification.cross_syntax, S.notification.complete_queries.format(count=queries_count), success=True, tab_index=tab_index
            )

    def _mark_tab_running(self, is_running: bool, tab_index: int = None) -> int:
        """
        Marca/desmarca aba como rodando (com spinner animado).

        Args:
            is_running: Se True, mostra spinner. Se False, para.
            tab_index: Indice da aba. Se None, usa a aba atual.

        Returns:
            Indice da aba modificada
        """
        if tab_index is None:
            tab_index = self.session_tabs.currentIndex()

        if tab_index < 0 or tab_index >= self.session_tabs.count():
            return tab_index

        self.session_tabs.set_tab_running(tab_index, is_running)
        return tab_index

    def _on_execution_finished_notification(self, title: str, message: str, success: bool, widget):
        """
        Decide se deve enviar notificacao apos execucao terminar.

        Regras:
        - Nao notifica se o usuario esta focado na aba que executou
          (janela ativa + aba visivel)
        - Notifica se a janela esta minimizada ou se outra aba esta selecionada
        """
        tab_index = self.session_tabs.indexOf(widget)
        current_tab = self.session_tabs.currentIndex()
        is_active_window = self.isActiveWindow() and not self.isMinimized()

        # Skip notification if user is looking at the executing tab
        if is_active_window and current_tab == tab_index:
            return

        self._send_notification(title, message, success, tab_index)

    def _send_notification(self, title: str, message: str, success: bool = True, tab_index: int = None):
        """
        Envia notificacao in-app (toast) no canto inferior direito.

        Args:
            title: Titulo da notificacao
            message: Mensagem
            success: Se True, notificacao de sucesso (verde), senao erro (vermelho)
            tab_index: Indice da aba que originou (foca nela ao clicar)
        """
        try:
            on_click = None
            if tab_index is not None:
                on_click = lambda idx=tab_index: self._focus_window_and_tab(idx)

            ToastManager.notify(
                title=title,
                message=message,
                success=success,
                on_click=on_click,
            )
        except Exception as e:
            logger.error(f"Error sending toast notification: {e}")

    def _focus_window_and_tab(self, tab_index: int = None):
        """Brings window to front, focuses, and selects the tab that notified"""
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.show()
        if tab_index is not None and 0 <= tab_index < self.session_tabs.count():
            self.session_tabs.setCurrentIndex(tab_index)

    def _focus_window(self):
        """Brings window to front and focuses"""
        self._focus_window_and_tab(None)

    def _log_info(self, message: str):
        """Adds message to log with timestamp (without showing panel)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        if self.global_output_panel:
            self.global_output_panel.text_edit.append(f"[{timestamp}] {message}")

    def _log(self, message: str):
        """Adds message to log with timestamp and shows output panel"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        if self.global_output_panel:
            self.global_output_panel.text_edit.append(f"[{timestamp}] {message}")

        # Mostrar painel de output
        self.show_panel("output")

    def _show_error_output(self, error_msg: str):
        """Shows error in Output in red and switches to the Output panel"""
        if not self.global_output_panel:
            return
        # Adiciona timestamp e erro em vermelho usando HTML
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        error_html = f'<span style="color: #ff6b6b; font-weight: bold;">[{timestamp}] {error_msg}</span>'
        self.global_output_panel.text_edit.append(error_html)

        # Mostrar painel de output
        self.show_panel("output")

        # Scroll para o final
        scrollbar = self.global_output_panel.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_variables_view(self):
        """Updates variable visualization in memory"""
        panel = self.global_variables_panel
        if not panel:
            return
        vars_df = self.results_manager.get_variables_info()
        panel.display_dataframe(vars_df, "Variaveis")

    def _clear_results(self):
        """Clears all results"""
        reply = QMessageBox.question(
            self,
            S.dialogs.confirm_clear_title,
            S.dialogs.confirm_clear_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.results_manager.clear_all()
            results = self.global_results_viewer
            if results:
                results.clear()
            variables = self.global_variables_panel
            if variables:
                variables.clear()
            output = self.global_output_panel
            if output:
                output.text_edit.clear()
            self.action_label.setText(S.status.results_cleared)

    def _new_file(self):
        """Clears current tab editor"""
        editor = self._get_current_editor()
        if editor:
            editor.clear()

    def _open_file(self):
        """Opens workspace or code file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            S.dialogs.open_file_title,
            "",
            S.dialogs.open_file_filter,
        )
        if filename:
            # Check if it is workspace
            if filename.endswith(".dpw"):
                self._open_workspace(filename)
            else:
                # Create NEW tab for file
                self._open_code_file(filename)

    def _open_code_file(self, filename: str):
        """Opens code file in new tab with complete panels"""
        try:
            # 1. Read file content (or cells if notebook)
            is_notebook = filename.endswith(".ipynb")
            cells = None
            content = ""

            if is_notebook:
                # Import service to parse notebook
                from src.services.file_import_service import FileImportService

                try:
                    cells = FileImportService.parse_ipynb_file(filename)
                    # Keep original content as JSON
                    with open(filename, "r", encoding="utf-8") as f:
                        content = f.read()
                except ValueError as e:
                    from PyQt6.QtWidgets import QMessageBox

                    QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_opening_notebook.format(error=e))
                    return
            else:
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read()

            # 2. Detect language and configure context
            if filename.endswith(".py"):
                language = "python"
                self._original_file_type = "python"
            elif filename.endswith(".ipynb"):
                language = "python"
                self._original_file_type = "notebook"
            elif filename.endswith(".dpw"):
                language = "sql"
                self._original_file_type = "workspace"
            else:
                language = "sql"
                self._original_file_type = "sql"

            # 3. Se estava no estado vazio, remover placeholder e mostrar paineis
            self._hide_empty_state()

            # 4. Criar nova sessao
            import os

            tab_title = os.path.basename(filename)
            session = self.session_manager.create_session(title=tab_title)

            # 5. Criar widget da sessao usando _create_session_widget (centralizado)
            widget = self._create_session_widget(session)

            # Definir file_path e tipo ANTES de qualquer setCurrentIndex
            # para que _on_session_tab_changed restaure corretamente
            widget.file_path = filename
            widget._original_file_type = self._original_file_type

            # Armazenar caminho do arquivo original (apos widget estar configurado)
            self._original_file_path = filename

            # 6. Configurar conteudo
            if is_notebook and cells:
                # Notebook: criar um bloco por celula
                blocks = widget.editor.get_blocks()
                for i, cell in enumerate(cells):
                    if i == 0 and blocks:
                        # Usar primeiro bloco existente
                        blocks[0].set_language(cell["language"])
                        blocks[0].set_code(cell["code"])
                    else:
                        # Criar novos blocos para celulas subsequentes
                        new_block = widget.editor.add_block(language=cell["language"])
                        if new_block:
                            new_block.set_code(cell["code"])
            else:
                # File tradicional: um bloco unico
                blocks = widget.editor.get_blocks()
                if blocks:
                    blocks[0].set_language(language)
                    blocks[0].set_code(content)

            # 7. Calcular hash apos carregar conteudo (content_changed ja esta conectado)
            widget._content_hash = self._compute_widget_content_hash(widget)
            widget._is_modified = False

            # Remover asterisco que pode ter sido adicionado durante set_code
            index = self.session_tabs.indexOf(widget)
            if index >= 0:
                tab_text = self.session_tabs.tabText(index)
                if tab_text.endswith(" *"):
                    self.session_tabs.setTabText(index, tab_text[:-2])

            # 8. Focar na aba criada
            index = self.session_tabs.indexOf(widget)
            if index >= 0:
                self.session_tabs.setCurrentIndex(index)

            # Ensure file context survives tab change events
            self._original_file_path = filename
            self._original_file_type = widget._original_file_type

            self.main_statusbar.show_save_feedback(S.status.file_opened.format(filename=filename))
            self.main_statusbar.set_file_info(filename)

            # 9. Update window title with context
            self._update_window_title()

            # 10. Switch panels to new session
            self._switch_session_panels(session.session_id)

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_opening_file.format(error=e))

    def _save_file(self):
        """Intelligent saving system"""
        self._save_intelligently()

    def _save_file_as(self):
        """Save As - detects context to offer appropriate filter"""
        context = self._detect_file_context()

        if context == "sql":
            filter_text = "SQL Files (*.sql);;DataPyn Workspace (*.dpw);;All Files (*.*)"
        elif context == "python":
            filter_text = "Python Files (*.py);;DataPyn Workspace (*.dpw);;All Files (*.*)"
        else:
            filter_text = "DataPyn Workspace (*.dpw);;SQL Files (*.sql);;Python Files (*.py);;All Files (*.*)"

        filename, selected_filter = QFileDialog.getSaveFileName(
            self, S.dialogs.save_as_title, "", filter_text
        )
        if filename:
            if filename.endswith(".dpw"):
                self._save_workspace_to_file(filename)
                self.main_statusbar.show_save_feedback(S.status.workspace_saved.format(path=filename))
                self.main_statusbar.set_file_info(filename)
            elif filename.endswith(".sql"):
                self._original_file_path = filename
                self._original_file_type = "sql"
                self._save_single_file(filename, "sql")
            elif filename.endswith(".py"):
                self._original_file_path = filename
                self._original_file_type = "python"
                self._save_single_file(filename, "python")
            else:
                # Infer from context or add default extension
                if context == "sql":
                    filename += ".sql"
                    self._original_file_path = filename
                    self._original_file_type = "sql"
                    self._save_single_file(filename, "sql")
                elif context == "python":
                    filename += ".py"
                    self._original_file_path = filename
                    self._original_file_type = "python"
                    self._save_single_file(filename, "python")
                else:
                    filename += ".dpw"
                    self._save_workspace_to_file(filename)
                    self.main_statusbar.show_save_feedback(S.status.workspace_saved.format(path=filename))
                    self.main_statusbar.set_file_info(filename)

            self._update_window_title()

    def _open_workspace(self, filename: str):
        """Opens a workspace from a specific file"""
        try:
            # Load workspace from file
            workspace = self.workspace_manager.load_workspace(filename)

            # Close all current sessions
            self._close_all_sessions()

            # Reload sessions from workspace
            self._restore_sessions()

            self.main_statusbar.show_save_feedback(S.status.workspace_opened.format(filename=filename))
            self.main_statusbar.set_file_info(filename)
            self._update_window_title()

        except Exception as e:
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, S.dialogs.error_opening_workspace_title, S.dialogs.error_opening_workspace_msg.format(error=str(e)))

    def _save_workspace_to_file(self, filename: str):
        """Saves workspace to a specific file"""
        # Synchronize current session
        widget = self._get_current_session_widget()
        if widget:
            widget.sync_to_session()

        # Salvar via SessionManager
        self.session_manager.save_sessions()

        # Salvar geometria da janela
        window_geometry = {
            "x": self.geometry().x(),
            "y": self.geometry().y(),
            "width": self.geometry().width(),
            "height": self.geometry().height(),
            "maximized": self.isMaximized(),
        }

        dock_visible = self.connections_dock.isVisible() if hasattr(self, "connections_dock") else True

        # Save in workspace manager with specific path
        self.workspace_manager.save_workspace(
            tabs=[],
            active_tab=0,
            active_connection=None,
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible,
            file_path=filename,  # Passa o caminho do arquivo
        )

        # Clear tab modification markers
        self._clear_modification_markers()

    def _clear_modification_markers(self):
        """Removes asterisks from tabs, resets flags and updates hashes"""
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if hasattr(widget, "_is_modified"):
                widget._is_modified = False
            if hasattr(widget, "editor"):
                widget._content_hash = self._compute_widget_content_hash(widget)

            # Remover asterisco do titulo da aba se existir
            current_text = self.session_tabs.tabText(i)
            if current_text.endswith(" *"):
                self.session_tabs.setTabText(i, current_text[:-2])

    def _update_status(self):
        """Updates status periodically (no I/O on main thread)."""
        # Check rapido sem I/O - apenas verifica estado do pool
        session = self.session_manager.focused_session
        if session and session.connector and not session.connector.is_connected():
            session.clear_connection()
            self._update_connection_status()

    # _change_theme removido - tema fixo em 'dark'

    def _apply_app_theme(self):
        """Applies theme to the application (not to editors)"""
        colors = self.theme_manager.get_app_colors()

        # Apply general style to window
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {colors["background"]};
            }}
            QMenuBar {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border-bottom: 1px solid {colors["border"]};
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 6px 12px;
            }}
            QMenuBar::item:selected {{
                background-color: {colors["accent"]};
            }}
            QMenu {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
            }}
            QMenu::item {{
                padding: 6px 40px 6px 30px;
                min-width: 180px;
            }}
            QMenu::item:selected {{
                background-color: {colors["accent"]};
            }}
            QToolBar {{
                background-color: {colors["background"]};
                border-bottom: 1px solid {colors["border"]};
                spacing: 5px;
                padding: 3px;
            }}
            QPushButton {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                border: none;
                padding: 6px 12px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors["accent"]};
            }}
            QTabWidget::pane {{
                border: 1px solid {colors["border"]};
                background-color: {colors["background"]};
            }}
            QTabBar::tab {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                padding: 8px 15px;
                padding-right: 25px;
                margin-right: 2px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background-color: {colors["background"]};
                color: {colors["accent"]};
            }}
            QTabBar::tab:hover {{
                background-color: {colors["accent"]};
            }}
            QTabBar::tab:last {{
                min-width: 30px;
                padding: 8px 10px;
                padding-right: 10px;
            }}
            QTabBar::close-button {{
                subcontrol-position: right;
                width: 12px;
                height: 12px;
            }}
            QTabBar::close-button:hover {{
                background-color: #ff6b6b;
                border-radius: 2px;
            }}
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
            }}
            QLabel {{
                color: {colors["foreground"]};
            }}
            QGroupBox {{
                color: {colors["accent"]};
                font-weight: bold;
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QListWidget {{
                background-color: {colors["background"]};
                border: 1px solid {colors["border"]};
                color: {colors["foreground"]};
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {colors["border"]};
            }}
            QListWidget::item:hover {{
                background-color: {colors["border"]};
            }}
            QListWidget::item:selected {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QDockWidget {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
            }}
            QDockWidget::title {{
                background-color: {colors["border"]};
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton#btnPrimary {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QPushButton#btnPrimary:hover {{
                background-color: {colors["accent"]};
            }}
            QPushButton#btnDisconnect:hover {{
                background-color: #f48771;
                color: white;
            }}
            QPushButton:disabled {{
                background-color: {colors["border"]};
                color: #666666;
            }}
        """)

        # Atualizar paineis de todas as sessoes
        if hasattr(self, "_session_panel_indices"):
            for info in self._session_panel_indices.values():
                info["results"].set_theme_manager(self.theme_manager)
                if hasattr(info["output"], "set_theme_manager"):
                    info["output"].set_theme_manager(self.theme_manager)
                if hasattr(info["variables"], "set_theme_manager"):
                    info["variables"].set_theme_manager(self.theme_manager)

        # Atualizar SessionWidgets
        if hasattr(self, "_session_widgets"):
            for widget in self._session_widgets.values():
                if hasattr(widget, "apply_theme"):
                    widget.apply_theme()

    def _show_about(self):
        """Shows the about dialog"""
        QMessageBox.about(
            self,
            S.about.title,
            f"""<h2>{S.about.ide_name}</h2>
            <p><b>{S.about.version.format(version=self._current_version)}</b></p>
            <p>{S.about.description}</p>
            
            <p><b>{S.about.technologies}</b></p>
            <ul>
                <li>Python 3.12+</li>
                <li>PyQt6 - Graphical interface</li>
                <li>Pandas & Polars - Data analysis</li>
                <li>SQLAlchemy - Database abstraction</li>
                <li>QScintilla - Code editor</li>
                <li>Matplotlib - Data visualization</li>
            </ul>
            
            <p><b>{S.about.databases}</b></p>
            <ul>
                <li>Microsoft SQL Server</li>
                <li>MySQL / MariaDB</li>
                <li>PostgreSQL</li>
                <li>SQLite</li>
            </ul>
            
            <p><b>{S.about.license}</b></p>
            <p><b>Repository:</b> <a href="https://github.com/natharuc/datapyn">github.com/natharuc/datapyn</a></p>
            
            <p style="margin-top: 15px; color: #888;">{S.about.built_with}</p>
            """,
        )

    def _show_package_manager(self):
        """Shows package manager dialog"""
        dialog = PackageManagerDialog(theme_manager=self.theme_manager, parent=self)
        dialog.exec()

    def _show_settings(self):
        """Shows the settings dialog"""
        dialog = SettingsDialog(self.shortcut_manager, theme_manager=self.theme_manager)
        dialog.shortcuts_changed.connect(self._reload_shortcuts)
        dialog.exec()

    def _toggle_auto_update(self, checked: bool):
        """Enables or disables auto-update"""
        self.auto_update_service.set_auto_update_enabled(checked)
        if checked:
            self.statusbar.showMessage(S.status.auto_update_enabled, 3000)
        else:
            self.statusbar.showMessage(S.status.auto_update_disabled, 3000)

    def _get_current_version(self) -> str:
        """Gets current version from pyproject.toml"""
        try:
            import tomllib
            import os

            # Path to pyproject.toml
            if getattr(sys, "frozen", False):
                # If running as executable, use embedded version
                base_path = sys._MEIPASS
            else:
                # In development, go to project root
                base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

            pyproject_path = os.path.join(base_path, "pyproject.toml")

            if os.path.exists(pyproject_path):
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", DEFAULT_VERSION)
            else:
                return DEFAULT_VERSION
        except Exception as e:
            logger.warning(f"Error reading version from pyproject.toml: {e}")
            return DEFAULT_VERSION

    def _check_for_updates(self):
        """Manually checks for updates"""
        if not self.auto_update_service.is_auto_update_enabled():
            reply = QMessageBox.question(
                self,
                S.dialogs.auto_update_disabled_title,
                S.dialogs.auto_update_disabled_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.auto_update_service.set_auto_update_enabled(True)
            else:
                return

        # Show loading dialog
        self._update_checking_dialog = UpdateCheckingDialog(self)
        
        # Start verificacao
        self.auto_update_service.check_for_updates(
            on_available=lambda v, url, notes: self._on_update_check_complete(v, url, notes),
            on_no_update=lambda: self._on_update_check_complete(None, None, None),
            on_error=lambda msg: self._on_update_check_error(msg),
        )
        
        # Show dialog (modal)
        self._update_checking_dialog.exec()

    def _on_update_check_complete(self, version: str, download_url: str, release_notes: str):
        """Callback when update check is complete"""
        # Close loading dialog
        if hasattr(self, "_update_checking_dialog") and self._update_checking_dialog:
            self._update_checking_dialog.close()
        
        if version:
            # Update available
            self._on_update_available(version, download_url, release_notes)
        else:
            # No update available
            self._on_no_update_available()

    def _check_for_updates_silent(self):
        """Silently checks for updates on startup"""
        if not self.auto_update_service.is_auto_update_enabled():
            return

        self.auto_update_service.check_for_updates(
            on_available=self._on_update_available,
            on_no_update=lambda: None,  # Silencioso se nao houver atualizacao
            on_error=lambda msg: logger.info(f"Update check failed: {msg}"),
        )

    def _on_update_available(self, version: str, download_url: str, release_notes: str):
        """Callback when an update is available"""
        self.statusbar.showMessage(S.status.new_version_available.format(version=version), 5000)

        dialog = UpdateDialog(self._current_version, version, release_notes, self)
        if dialog.exec() == UpdateDialog.DialogCode.Accepted and dialog.should_download:
            self._download_update(version, download_url)

    def _on_no_update_available(self):
        """Callback when no updates are available"""
        self.statusbar.showMessage(S.status.latest_version, 5000)
        QMessageBox.information(
            self,
            S.dialogs.no_updates_title,
            S.dialogs.no_updates_msg.format(version=self._current_version),
        )

    def _on_update_check_error(self, error_message: str):
        """Callback when an error occurs while checking for updates"""
        # Close loading dialog
        if hasattr(self, "_update_checking_dialog") and self._update_checking_dialog:
            self._update_checking_dialog.close()
        
        self.statusbar.showMessage(S.status.error_checking_updates, 5000)
        QMessageBox.warning(
            self, S.dialogs.verification_error_title, S.dialogs.verification_error_msg.format(error=error_message)
        )

    def _download_update(self, version: str, download_url: str):
        """Starts the update download"""
        download_dialog = UpdateDownloadDialog(version, self)

        self.auto_update_service.download_update(
            download_url,
            version,
            on_progress=download_dialog.update_progress,
            on_complete=lambda path: self._on_download_complete(path, download_dialog),
            on_error=download_dialog.download_failed,
        )

        download_dialog.exec()

    def _on_download_complete(self, installer_path: str, download_dialog):
        """Callback when the download is complete"""
        download_dialog.download_complete(installer_path)

        reply = QMessageBox.question(
            self,
            S.dialogs.download_complete_title,
            S.dialogs.download_complete_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.auto_update_service.install_update(installer_path):
                QApplication.quit()
            else:
                QMessageBox.critical(
                    self, S.dialogs.installation_error_title, S.dialogs.installation_error_msg
                )

    def _new_session(self):
        """Creates a new session, inheriting the connection from the current tab (if any)"""
        # Guard to prevent duplicate creation
        if hasattr(self, "_creating_session") and self._creating_session:
            return
        self._creating_session = True

        try:
            # Capture active session connection BEFORE creating new one
            previous_connection = None
            current_widget = self._get_current_session_widget()
            if current_widget and hasattr(current_widget, "session"):
                previous_connection = current_widget.session.connection_name

            # If in empty state, remove the placeholder
            self._hide_empty_state()

            session = self.session_manager.create_session()
            widget = self._create_session_widget(session)

            # Inherit connection from previous tab
            if previous_connection:
                try:
                    connected = session.connect(previous_connection)
                    if connected:
                        # Apply tab color
                        config = self.connection_manager.get_connection_config(previous_connection)
                        if config:
                            color = config.get("color", "#007ACC") or "#007ACC"
                            idx = self.session_tabs.indexOf(widget)
                            if idx >= 0:
                                self.session_tabs.set_tab_connection_color(idx, color)
                except Exception as e:
                    print(f"[WARNING] Could not inherit connection: {e}")

            # Update window title (context may have changed)
            self._update_window_title()
        finally:
            self._creating_session = False

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
                border-radius: 4px;
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
        widget.execute_cross_syntax.connect(lambda code: self._execute_cross_syntax_for_session(session, code))
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
        widget.execution_finished.connect(
            lambda title, msg, success, w=widget: self._on_execution_finished_notification(
                title, msg, success, w
            )
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

    def _close_session_tab(self, index: int):
        """Closes session tab"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return

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

            # Atualizar titulo e statusbar para refletir a aba ativa apos fechar
            self._update_window_title()
        finally:
            self._closing_session = False

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

            # Restaurar contexto de arquivo da aba selecionada
            if hasattr(widget, "file_path") and widget.file_path:
                self._original_file_path = widget.file_path
                self._original_file_type = getattr(widget, "_original_file_type", None)
            else:
                self._original_file_path = None
                self._original_file_type = None

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

        # === CARREGAR SCHEMA (INVALIDA CACHE + RELOAD) ===
        if session.connector:
            self._schema_service.invalidate_cache(connection_name)
            self._schema_service.load_schema(session.connector, connection_name)

        # === ATUALIZAR TODOS OS BLOCOS (sem conexao customizada) ===
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            for block in current_widget.editor.get_blocks():
                if hasattr(block, "db_panel"):
                    block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
                    if not block_conn:
                        block._database_name = current_db
                        block.db_panel.set_database(current_db)

    def _reload_schema(self):
        """Reloads the SQL schema from the focused block connection (or session).

        Usa a conexao do bloco focado se ele tiver conexao customizada,
        caso contrario usa a conexao da sessao ativa.
        """
        widget = self._get_current_session_widget()
        if not widget:
            self.statusBar().showMessage(S.status.no_active_session, 3000)
            return

        # Determine connection: focused block or session
        connection_name = None
        connector = None

        focused_block = widget.editor.get_focused_block()
        if focused_block:
            block_conn = focused_block.get_connection_name()
            if block_conn:
                connection_name = block_conn

        if not connection_name:
            # Use session connection
            if widget.session.is_connected and widget.session.connection_name:
                connection_name = widget.session.connection_name
                connector = widget.session.connector

        if not connection_name:
            self.statusBar().showMessage(S.status.no_active_connection_reload, 3000)
            return

        # Invalidate cache and reload
        self._schema_service.invalidate_cache(connection_name)
        self.statusBar().showMessage(S.status.reloading_schema.format(name=connection_name), 5000)

        if connector and connector.is_connected():
            self._schema_service.load_schema(connector, connection_name)
        else:
            # Need to get connector from ConnectionManager
            from src.database.connection_manager import ConnectionManager
            manager = ConnectionManager()
            conn = manager.connections.get(connection_name)
            if conn and conn.is_connected():
                self._schema_service.load_schema(conn, connection_name)
            else:
                self.statusBar().showMessage(S.status.connection_not_active.format(name=connection_name), 3000)

    def _on_schema_loaded(self, schema: dict, connection_name: str):
        """Callback when database schema is loaded by SchemaService.

        Distribui o schema para os blocos SQL que usam
        a conexao correspondente.
        Se connection_name e a conexao da sessao, aplica aos blocos sem conexao customizada.
        Se connection_name e uma conexao de bloco especifico, aplica so a esse bloco.
        """
        tables_total = len(schema.get('tables', []))
        cols_total = sum(len(v) for v in schema.get('columns', {}).values())
        self._log_info(
            S.log.schema_loaded.format(name=connection_name, tables=tables_total, cols=cols_total)
        )

        # Feedback na statusbar
        tables_count = len(schema.get("tables", []))
        cols_count = sum(len(v) for v in schema.get("columns", {}).values())
        self.statusBar().showMessage(
            S.status.schema_loaded.format(name=connection_name, tables=tables_count, cols=cols_count), 5000
        )

        # Enviar schema para blocos que usam esta conexao
        all_databases = schema.get("databases", [])
        for widget in self._session_widgets.values():
            if not (hasattr(widget, "editor") and widget.editor):
                continue

            # Verificar se esta conexao e a conexao da sessao
            session_conn = ""
            if hasattr(widget, "session") and widget.session:
                session_conn = getattr(widget.session, "connection_name", "") or ""

            for block in widget.editor.get_blocks():
                if not (hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema")):
                    continue

                block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None

                if block_conn:
                    # Block with custom connection: only apply if same connection
                    if block_conn == connection_name:
                        block.editor.set_sql_schema(schema)
                        if hasattr(block, "set_available_databases"):
                            block.set_available_databases(all_databases)
                elif session_conn == connection_name:
                    # Block without custom connection: apply if session connection
                    block.editor.set_sql_schema(schema)
                    if hasattr(block, "set_available_databases"):
                        block.set_available_databases(all_databases)

        # Update Object Explorer for corresponding session
        if hasattr(self, "_session_explorers"):
            for sid, widget in self._session_widgets.items():
                if not (hasattr(widget, "session") and widget.session):
                    continue
                session_conn = getattr(widget.session, "connection_name", "") or ""
                if session_conn == connection_name:
                    explorer = self._get_session_explorer(sid)
                    explorer.set_schema(schema, connection_name)
                    # Mostrar dock se e a sessao ativa
                    current_widget = self._get_current_session_widget()
                    if current_widget and hasattr(current_widget, "session"):
                        if current_widget.session.session_id == sid:
                            self._switch_session_explorer(sid)
                            self.object_explorer_dock.show()

    def _on_block_connection_changed(self, block, connection_name: str):
        """Callback when an individual block connection changes.

        Loads schema from new connection and applies to block (in background).
        """
        if not connection_name:
            return

        # Verificar cache primeiro
        cached = self._schema_service.get_cached_schema(connection_name)
        if cached:
            if hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema(cached)
            if hasattr(block, "set_available_databases"):
                block.set_available_databases(cached.get("databases", []))
            return

        # Precisa carregar schema - criar connector em background
        try:
            from src.database.connection_manager import ConnectionManager
            from src.workers import BlockConnectionWorker

            manager = ConnectionManager()
            config = manager.get_connection_config(connection_name)
            if not config:
                return

            thread = QThread()
            worker = BlockConnectionWorker(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=config.get("username", ""),
                password=config.get("password", ""),
                use_windows_auth=config.get("use_windows_auth", False),
                trust_server_certificate=config.get("trust_server_certificate", False),
            )
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.connection_ready.connect(
                lambda connector: self._schema_service.load_schema(connector, connection_name)
            )
            worker.error.connect(
                lambda msg: self._log_info(f"Error loading schema for block ({connection_name}): {msg}")
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: self._remove_worker_thread(thread))

            self._worker_threads.append((thread, worker))
            thread.start()
        except Exception as e:
            self._log_info(f"Error loading schema for block ({connection_name}): {e}")

    def _on_block_database_changed(self, block, database_name: str):
        """Callback when a block's database is changed.

        Switches the database of the block's connection (or session connection).
        """
        if not database_name:
            return

        current_widget = self._get_current_session_widget()
        if not current_widget or not hasattr(current_widget, "session"):
            return

        session = current_widget.session

        # Determine which connector to use (block-specific or session)
        block_conn_name = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        if block_conn_name:
            # Block has its own connection - not switching session connector
            return

        connector = getattr(session, "connector", None)
        connection_name = getattr(session, "connection_name", "") or ""

        if not connector or not connector.is_connected():
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        # Switch database in background
        self._on_object_explorer_database_switch(database_name)

    def _on_insert_variable_in_editor(self, var_name: str):
        """Inserts variable name in the focused editor of the active session"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            block = current_widget.editor.get_focused_block()
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(var_name)

    def _on_delete_variable(self, var_name: str):
        """Removes variable from the active session namespace"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "session"):
            ns = current_widget.session.namespace
            if var_name in ns:
                del ns[var_name]
                current_widget.session.variables_changed.emit(ns)

    def _push_python_namespace(self, namespace: dict):
        """Sends updated Python namespace to code editors.

        Chamado apos execucao Python para alimentar autocomplete.
        """
        # Construir mapa varName -> typeName
        ns_types = {}
        for key, value in namespace.items():
            if key.startswith("_"):
                continue
            # Pular modulos internos e funcoes builtin
            type_name = type(value).__name__
            if type_name in ("module",):
                ns_types[key] = "module"
            elif type_name in ("function", "builtin_function_or_method"):
                ns_types[key] = "function"
            elif type_name == "type":
                ns_types[key] = "class"
            else:
                ns_types[key] = type_name

        # Enviar para todos os blocos Python da sessao ativa
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor") and current_widget.editor:
            # Collect import lines from all blocks to share as global context
            import_lines = []
            for block in current_widget.editor.get_blocks():
                if block.get_language() == "python":
                    for line in block.get_code().splitlines():
                        stripped = line.strip()
                        if stripped.startswith("import ") or stripped.startswith("from "):
                            import_lines.append(stripped)
            global_imports = "\n".join(dict.fromkeys(import_lines))  # deduplicate preserving order

            for block in current_widget.editor.get_blocks():
                if hasattr(block, "editor") and hasattr(block.editor, "set_python_namespace"):
                    block.editor.set_python_namespace(ns_types)
                if hasattr(block, "editor") and hasattr(block.editor, "set_global_imports"):
                    block.editor.set_global_imports(global_imports)

    def _compute_widget_content_hash(self, widget):
        """Calcula hash do conteudo atual do editor do widget"""
        if not hasattr(widget, "editor") or not widget.editor:
            return ""

        blocks = widget.editor.get_blocks()
        parts = []
        for block in blocks:
            parts.append(block.get_language())
            parts.append(block.get_code())

        content = "\n".join(parts)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _on_editor_modified(self, widget):
        """Callback quando o conteudo do editor e modificado - usa hash para comparacao"""
        current_hash = self._compute_widget_content_hash(widget)
        original_hash = getattr(widget, "_content_hash", "")

        is_modified = current_hash != original_hash
        was_modified = getattr(widget, "_is_modified", False)
        widget._is_modified = is_modified

        # Atualizar titulo da aba conforme estado de modificacao
        if is_modified != was_modified:
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) == widget:
                    current_text = self.session_tabs.tabText(i)
                    if is_modified and not current_text.endswith(" *"):
                        self.session_tabs.setTabText(i, current_text + " *")
                    elif not is_modified and current_text.endswith(" *"):
                        self.session_tabs.setTabText(i, current_text[:-2])
                    break

            self._update_window_title()

    def _get_current_session_widget(self) -> SessionWidget:
        """Returns active tab SessionWidget"""
        widget = self.session_tabs.currentWidget()
        if isinstance(widget, SessionWidget):
            return widget
        return None

    def _get_current_editor(self) -> UnifiedEditor:
        """Returns the editor of the active session"""
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
                print(f"Could not restore connection: {e}")

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
            )

            self.connection_manager.mark_connection_used(connection_name)
            self._update_connection_status()
            self.action_label.setText(S.status.reconnected_to.format(name=connection_name))

        except Exception as e:
            print(f"Error reconnecting {connection_name}: {e}")
            # Does not fail silently - shows in statusbar
            self.action_label.setText(S.status.reconnection_failed.format(name=connection_name))

    def _execute_cross_syntax_for_session(self, session, code: str):
        """Executes cross-syntax for a specific session"""
        # TODO: Implement cross-syntax per session
        # For now, uses the global method
        self._execute_cross_syntax(code)

    # =========================================================================
    # Sistema de Gerenciamento Inteligente de Arquivos
    # =========================================================================

    def _detect_file_context(self) -> str:
        """
        Detects the current context based on the number of blocks and types

        Returns:
            'sql'       - um bloco SQL apenas
            'python'    - um bloco Python apenas
            'workspace' - multiple blocks or .dpw file
        """
        # If has multiple sessions = always workspace
        if len(self._session_widgets) > 1:
            return "workspace"

        # If original file is already workspace
        if self._original_file_type == "workspace":
            return "workspace"

        # If there are no sessions but there is an original sql/py file, use file type
        current_widget = self._get_current_session_widget()
        if not current_widget:
            if self._original_file_type in ["sql", "python"]:
                return self._original_file_type
            return "workspace"

        blocks = current_widget.editor.get_blocks()

        # Se tem mais de 1 bloco = workspace
        if len(blocks) > 1:
            return "workspace"

        # Se tem 1 bloco apenas, usar tipo do arquivo original ou tipo do bloco
        if len(blocks) == 1:
            block_language = blocks[0].get_language()
            if self._original_file_type in ["sql", "python"]:
                # If block is compatible with original file
                if (self._original_file_type == "sql" and block_language == "sql") or (
                    self._original_file_type == "python" and block_language == "python"
                ):
                    return self._original_file_type
            else:
                # Novo arquivo, usar linguagem do bloco
                if block_language in ["sql", "python"]:
                    return block_language

        # Fallback: se tem arquivo original sql/py, usar ele
        if self._original_file_type in ["sql", "python"]:
            return self._original_file_type

        return "workspace"

    def _update_window_title(self):
        """Updates window title with context indicator and file path"""
        base_title = "DataPyn"

        # Detectar contexto atual
        context = self._detect_file_context()
        self._current_context = context

        # Adicionar indicador
        if context == "sql":
            indicator = "[SQL]"
        elif context == "python":
            indicator = "[Python]"
        else:
            indicator = "[Workspace]"

        # Adicionar caminho do arquivo se disponivel
        file_info = ""
        file_path_for_statusbar = ""
        if self._original_file_path:
            import os

            file_info = f" - {self._original_file_path}"
            file_path_for_statusbar = self._original_file_path
        elif self.workspace_manager.current_file_path:
            import os

            file_info = f" - {self.workspace_manager.current_file_path}"
            file_path_for_statusbar = str(self.workspace_manager.current_file_path)

        self.setWindowTitle(f"{indicator} {base_title}{file_info}")

        # Atualizar informacao do arquivo na statusbar
        if hasattr(self, "main_statusbar"):
            self.main_statusbar.set_file_info(file_path_for_statusbar)

    def _save_intelligently(self):
        """Intelligent save system based on context"""
        context = self._detect_file_context()

        if context in ["sql", "python"]:
            # Contexto de arquivo unico - salvar no arquivo original
            if self._original_file_path:
                self._save_single_file(self._original_file_path, context)
            else:
                # Pedir caminho para arquivo unico
                self._save_single_file_as(context)
        else:
            # Contexto workspace - usar workspace_manager diretamente
            window_geometry = {
                "x": self.geometry().x(),
                "y": self.geometry().y(),
                "width": self.geometry().width(),
                "height": self.geometry().height(),
                "maximized": self.isMaximized(),
            }

            dock_visible = self.connections_dock.isVisible() if hasattr(self, "connections_dock") else True

            self.workspace_manager.save_workspace(
                tabs=[],
                active_tab=0,
                active_connection=None,
                window_geometry=window_geometry,
                splitter_sizes=[],
                dock_visible=dock_visible,
            )

            # Feedback visual para o usuario
            save_path = str(self.workspace_manager.current_file_path or self.workspace_manager.config_path)
            self.main_statusbar.show_save_feedback(S.status.workspace_saved.format(path=save_path))
            self.main_statusbar.set_file_info(save_path)

            self._clear_modification_markers()

    def _save_single_file(self, file_path: str, file_type: str):
        """Saves content to single file (sql/py)"""
        try:
            current_widget = self._get_current_session_widget()
            if not current_widget:
                return

            blocks = current_widget.editor.get_blocks()
            if not blocks:
                return

            # Pegar conteudo do primeiro bloco
            content = blocks[0].get_code()

            # Salvar arquivo
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Atualizar file_path no widget e sessao
            current_widget.file_path = file_path
            current_widget._original_file_type = file_type
            current_widget.session.file_path = file_path
            current_widget.session.original_file_type = file_type

            # Update content hash after saving (now it's the new "original")
            current_widget._content_hash = self._compute_widget_content_hash(current_widget)
            current_widget._is_modified = False

            # Atualizar nome da aba com o nome do arquivo (sem asterisco)
            import os

            filename = os.path.basename(file_path)
            index = self.session_tabs.indexOf(current_widget)
            if index >= 0:
                self.session_tabs.setTabText(index, filename)
                current_widget.session.title = filename

            self.main_statusbar.show_save_feedback(S.status.file_saved.format(path=file_path))
            self.main_statusbar.set_file_info(file_path)

            self._update_window_title()

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_saving_file.format(error=e))

    def _save_single_file_as(self, file_type: str):
        """Asks for path to save single file"""
        from PyQt6.QtWidgets import QFileDialog

        if file_type == "sql":
            filter_text = "SQL Files (*.sql);;All Files (*.*)"
            default_ext = ".sql"
        else:
            filter_text = "Python Files (*.py);;All Files (*.*)"
            default_ext = ".py"

        filename, _ = QFileDialog.getSaveFileName(self, S.dialogs.save_python_file_title.format(type=file_type.upper()), "", filter_text)

        if filename:
            # Ensure correct extension
            if not filename.endswith(default_ext):
                filename += default_ext

            self._original_file_path = filename
            self._original_file_type = file_type
            self._save_single_file(filename, file_type)

    def _export_as_script(self):
        """Exports the current analysis as a complete Python script"""
        from PyQt6.QtWidgets import QFileDialog
        
        current_widget = self._get_current_session_widget()
        if not current_widget:
            QMessageBox.warning(self, S.dialogs.warning, S.dialogs.export_no_session)
            return
        
        blocks = current_widget.editor.get_blocks()
        if not blocks:
            QMessageBox.warning(self, S.dialogs.warning, S.dialogs.export_no_blocks)
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            S.dialogs.export_script_title,
            "",
            "Python Files (*.py);;All Files (*.*)"
        )
        
        if not filename:
            return
        
        if not filename.endswith('.py'):
            filename += '.py'
        
        try:
            script_content = self._generate_script_from_blocks(blocks, current_widget)
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            self.action_label.setText(S.status.script_exported.format(filename=filename))
            QMessageBox.information(
                self,
                S.dialogs.export_complete_title,
                S.dialogs.export_complete_msg.format(filename=filename)
            )
        
        except Exception as e:
            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_exporting_script.format(error=e))
    
    def _generate_script_from_blocks(self, blocks, session_widget) -> str:
        """Generates complete Python code from the blocks"""
        lines = []
        
        lines.append('"""')
        lines.append('Python Script Exported from DataPyn')
        lines.append('')
        lines.append(f'Generated at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        if session_widget.session.connection_name:
            lines.append(f'Connection: {session_widget.session.connection_name}')
        lines.append('"""')
        lines.append('')
        
        imports_needed = set()
        has_sql = False
        has_cross = False
        
        for block in blocks:
            lang = block.get_language()
            if lang == 'sql':
                has_sql = True
            elif lang == 'cross':
                has_cross = True
                has_sql = True
        
        imports_needed.add('import pandas as pd')
        
        if has_sql or has_cross:
            imports_needed.add('from sqlalchemy import create_engine')
            # Note: pyodbc is only added for SQL Server connections below
        
        lines.extend(sorted(imports_needed))
        lines.append('')
        
        if has_sql or has_cross:
            lines.append('# Database Connection Configuration')
            lines.append('# IMPORTANT: Adjust the credentials below according to your configuration')
            
            if session_widget.session.connection_name:
                conn_name = session_widget.session.connection_name
                config = self.connection_manager.get_connection_config(conn_name)
                if config:
                    db_type = config.get('db_type', 'mysql')
                    host = config.get('host', 'localhost')
                    port = config.get('port', 3306)
                    database = config.get('database', 'database')
                    username = config.get('username', 'user')
                    
                    lines.append(f"# Database type: {db_type}")
                    lines.append(f"DB_HOST = '{host}'")
                    lines.append(f"DB_PORT = {port}")
                    lines.append(f"DB_NAME = '{database}'")
                    lines.append(f"DB_USER = '{username}'")
                    lines.append("DB_PASSWORD = ''  # Enter password here")
                    lines.append('')
                    
                    if db_type == 'mysql':
                        lines.append("# MySQL connection string")
                        lines.append("connection_string = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'")
                    elif db_type == 'postgresql':
                        lines.append("# PostgreSQL connection string")
                        lines.append("connection_string = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'")
                    elif db_type == 'sqlserver':
                        lines.append("# SQL Server connection string")
                        lines.append("# Requer: pip install pyodbc")
                        lines.append("connection_string = f'mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?driver=ODBC+Driver+17+for+SQL+Server'")
                    else:
                        lines.append(f"# {db_type} connection string")
                        lines.append("connection_string = ''  # Configure the appropriate connection string")
                    
                    lines.append('')
                    lines.append('# Create connection engine')
                    lines.append('engine = create_engine(connection_string)')
                    lines.append('')
            else:
                lines.append("connection_string = ''  # Configure your connection string")
                lines.append('engine = create_engine(connection_string)')
                lines.append('')
        
        lines.append('# ========================================')
        lines.append('# Code Blocks')
        lines.append('# ========================================')
        lines.append('')
        
        for i, block in enumerate(blocks, 1):
            lang = block.get_language()
            code = block.get_code().strip()
            block_name = block.get_block_name()
            
            if not code:
                continue
            
            lines.append(f'# --- Block {i}: {lang.upper()}' + (f' ({block_name})' if block_name else '') + ' ---')
            
            if lang == 'sql':
                lines.append('# SQL Query executed via pandas')
                var_name = block_name if block_name else f'df_block_{i}'
                lines.append(f'{var_name} = pd.read_sql("""')
                lines.append(code)
                lines.append('""", engine)')
                lines.append(f'print(f"Query executed: {{len({var_name})}} rows returned")')
            
            elif lang == 'cross':
                lines.append('# Cross-syntax: SQL + Python')
                processed_code = self._convert_cross_syntax_to_python(code, i)
                lines.append(processed_code)
            
            elif lang == 'python':
                lines.append('# Python code')
                lines.append(code)
            
            lines.append('')
        
        lines.append('# ========================================')
        lines.append('# End of Script')
        lines.append('# ========================================')
        
        return '\n'.join(lines)
    
    def _convert_cross_syntax_to_python(self, code: str, block_index: int) -> str:
        """Converts cross syntax (var = {{ SQL }}) to pure Python"""
        import re
        
        # Match pattern: variable_name = {{ SQL query }}
        # Captures: group(1) = variable_name, group(2) = SQL query
        pattern = r"(\w+)\s*=\s*\{\{\s*(.+?)\s*\}\}"
        
        lines = []
        last_end = 0
        
        for match in re.finditer(pattern, code, re.DOTALL):
            before_match = code[last_end:match.start()]
            if before_match.strip():
                lines.append(before_match.rstrip())
            
            var_name = match.group(1)
            sql = match.group(2).strip()
            
            lines.append(f'# SQL query assigned to variable {var_name}')
            lines.append(f'{var_name} = pd.read_sql("""')
            lines.append(sql)
            lines.append('""", engine)')
            
            last_end = match.end()
        
        after_match = code[last_end:]
        if after_match.strip():
            lines.append(after_match.rstrip())
        
        return '\n'.join(lines)

    def closeEvent(self, event):
        """On window close"""
        # Check if there is execution in progress
        has_running = any(
            widget._is_executing for widget in self._session_widgets.values() if hasattr(widget, "_is_executing")
        )

        if has_running:
            reply = QMessageBox.question(
                self,
                S.dialogs.execution_in_progress_title,
                S.dialogs.execution_in_progress_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            # Cancel all executions
            for widget in self._session_widgets.values():
                if hasattr(widget, "_cancel_requested"):
                    widget._cancel_requested = True

        # Save sessions before closing
        self._save_sessions()

        # Stop auto-save timer BEFORE saving to prevent it from overwriting
        if hasattr(self, '_layout_save_timer'):
            self._layout_save_timer.stop()

        # Save dock layout before closing
        self._save_dock_layout()

        # Cleanup all sessions
        for widget in self._session_widgets.values():
            widget.cleanup()

        self.session_manager.cleanup_all()

        # Close connections
        self.connection_manager.close_all()

        # Limpar schema service
        if hasattr(self, "_schema_service"):
            self._schema_service.cleanup()

        event.accept()
