"""
CodeBlock - An individual code block with language selector

Similar to a Jupyter notebook cell.
Uses Monaco Editor for code editing with Copilot inline completions.
"""

import time
import uuid
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
    QLineEdit,
    QMenu,
)
from PyQt6.QtCore import pyqtSignal, Qt, QMimeData, QPoint, QTimer, QSize
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor
import qtawesome as qta

from src.core.theme_manager import ThemeManager
from src.state.app_state import ApplicationState
from src.editors.editor_config import get_code_editor_class
from src.editors.sql_parameters_panel import SqlParametersPanel
from src.language import S
from src.utils.sql_parameter_service import (
    extract_sql_parameter_tokens,
    filter_parameters_for_query,
    merge_parameter_definitions,
    normalize_parameter_definition,
)


class BlockConnectionPanel(QFrame):
    """
    Clickable panel to select a block's SQL connection.
    Shows icon + connection name, accepts drag & drop.
    """

    connection_clicked = pyqtSignal()  # User clicked on panel
    connection_dropped = pyqtSignal(str, str, str)  # connection_name, db_type, color (drag & drop)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connection_name = None
        self._db_type = None
        self._locked = False  # True = first block, cannot change connection
        self._setup_ui()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setup_ui(self):
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setStyleSheet(f"""
            BlockConnectionPanel {{
                background: {colors.bg_tertiary};
                border: none;
                border-radius: 6px;
            }}
            BlockConnectionPanel:hover {{
                background: {colors.bg_elevated};
            }}
        """)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # Icone
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setScaledContents(True)
        layout.addWidget(self.icon_label)

        # Connection name
        self.name_label = QLabel(S.block.conn_tab_default)
        self.name_label.setStyleSheet("color: #9d9d9d; font-size: 11px;")
        self.name_label.setMinimumWidth(40)
        layout.addWidget(self.name_label, 1)

    def set_connection(self, connection_name: str = None, db_type: str = None, color: str = None):
        """Set the connection to display"""
        self._connection_name = connection_name
        self._db_type = db_type
        self._color = color

        if connection_name:
            # Custom connection
            self.name_label.setText(connection_name)
            self.name_label.setStyleSheet("color: #e8e8e8; font-size: 11px; font-weight: 500;")

            # Colored icon (import here to avoid circular import)
            if db_type:
                from src.ui.components.connection_panel import get_db_icon

                icon = get_db_icon(db_type, custom_color=color)
                self.icon_label.setPixmap(icon.pixmap(16, 16))
            else:
                icon_color = color or "#64b5f6"
                self.icon_label.setPixmap(qta.icon("mdi.database", color=icon_color).pixmap(16, 16))
        else:
            # Tab default
            self.name_label.setText(S.block.conn_tab_default)
            self.name_label.setStyleSheet("color: #9d9d9d; font-size: 11px;")
            self.icon_label.setPixmap(qta.icon("mdi.link-variant", color="#9d9d9d").pixmap(16, 16))

    def get_connection_name(self):
        """Return current connection name (None = tab default)"""
        return self._connection_name

    def set_locked(self, locked: bool):
        """Lock/unlock connection changes (first block is always locked)"""
        self._locked = locked
        if locked:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setAcceptDrops(False)
            self.setToolTip(S.block.conn_first_block_locked)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAcceptDrops(True)
            self.setToolTip("")

    def is_locked(self) -> bool:
        """Return whether connection changes are locked"""
        return self._locked

    def mousePressEvent(self, event):
        """Click on panel"""
        if self._locked:
            return  # Ignore clicks when locked
        if event.button() == Qt.MouseButton.LeftButton:
            self.connection_clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        """Accept connection drag"""
        if self._locked:
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-connection-name"):
            event.acceptProposedAction()
            self.setStyleSheet("""
                BlockConnectionPanel {
                    background: #2a2a2e;
                    border: 1px solid #4b7bec;
                    border-radius: 8px;
                }
            """)

    def dragLeaveEvent(self, event):
        """Remove highlight on exit"""
        self.setStyleSheet("""
            BlockConnectionPanel {
                background: #222225;
                border: 1px solid #333338;
                border-radius: 8px;
            }
            BlockConnectionPanel:hover {
                border-color: #4a4a50;
            }
        """)

    def dropEvent(self, event):
        """Receive dragged connection"""
        if event.mimeData().hasFormat("application/x-connection-name"):
            connection_name = event.mimeData().data("application/x-connection-name").data().decode("utf-8")
            db_type = (
                event.mimeData().data("application/x-db-type").data().decode("utf-8")
                if event.mimeData().hasFormat("application/x-db-type")
                else None
            )
            color = (
                event.mimeData().data("application/x-connection-color").data().decode("utf-8")
                if event.mimeData().hasFormat("application/x-connection-color")
                else ""
            )

            self.connection_dropped.emit(connection_name, db_type or "", color)
            event.acceptProposedAction()

            # Restore style
            self.dragLeaveEvent(event)


class BlockDatabasePanel(QFrame):
    """
    Panel to display and allow switching the database for a block.
    Shows icon + database name, accepts drag & drop of databases from Object Explorer.
    """

    database_clicked = pyqtSignal()  # User clicked on panel
    database_dropped = pyqtSignal(str)  # database_name (drag & drop from Object Explorer)
    database_selected = pyqtSignal(str)  # database_name (selected from popup menu)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._database_name = None
        self._available_databases: list = []
        self._setup_ui()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setup_ui(self):
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setStyleSheet(f"""
            BlockDatabasePanel {{
                background: {colors.bg_tertiary};
                border: none;
                border-radius: 6px;
            }}
            BlockDatabasePanel:hover {{
                background: {colors.bg_elevated};
            }}
        """)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setScaledContents(True)
        self.icon_label.setPixmap(qta.icon("mdi.database-outline", color=colors.text_tertiary).pixmap(16, 16))
        layout.addWidget(self.icon_label)

        # Database name
        self.name_label = QLabel(S.block.db_default)
        self.name_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
        self.name_label.setMinimumWidth(40)
        layout.addWidget(self.name_label, 1)

    def set_database(self, database_name: str = None):
        """Set the database to display"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self._database_name = database_name
        display_name = database_name
        if isinstance(display_name, str):
            if display_name.startswith("CATALOG:"):
                display_name = display_name[8:]
            elif display_name.startswith("SCHEMA:"):
                display_name = display_name[7:]

        if database_name:
            self.name_label.setText(display_name)
            self.name_label.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: 500;")
            self.icon_label.setPixmap(qta.icon("mdi.database", color=colors.info).pixmap(16, 16))
        else:
            self.name_label.setText(S.block.db_default)
            self.name_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
            self.icon_label.setPixmap(qta.icon("mdi.database-outline", color=colors.text_tertiary).pixmap(16, 16))

    def get_database_name(self):
        """Return current database name (None = connection default)"""
        return self._database_name

    def set_available_databases(self, databases: list):
        """Set the list of databases available for selection."""
        self._available_databases = list(databases) if databases else []

    def get_available_databases(self) -> list:
        """Return list of available databases."""
        return self._available_databases

    def mousePressEvent(self, event):
        """Click on panel - show database selection popup."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._available_databases:
                self._show_database_menu()
            else:
                self.database_clicked.emit()
        super().mousePressEvent(event)

    def _show_database_menu(self):
        """Show popup menu with available databases."""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 24px 8px 12px;
                color: {colors.text_primary};
                font-size: 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {colors.interactive_primary};
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background: {colors.border_default};
                margin: 6px 8px;
            }}
        """)

        # Option to reset to connection default
        default_action = menu.addAction(
            qta.icon("mdi.database-outline", color=colors.text_tertiary),
            S.block.db_default,
        )
        default_action.setData(None)
        menu.addSeparator()

        # Add each database
        for db in sorted(self._available_databases):
            icon_name = "mdi.database"
            icon_color = colors.info
            if db == self._database_name:
                icon_name = "mdi.database-check"
                icon_color = colors.success
            action = menu.addAction(
                qta.icon(icon_name, color=icon_color),
                db,
            )
            action.setData(db)

        chosen = menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        if chosen is not None:
            db_name = chosen.data()
            self.set_database(db_name)
            self.database_selected.emit(db_name or "")

    def dragEnterEvent(self, event):
        """Accept database drag from Object Explorer"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        if event.mimeData().hasFormat("application/x-database-name"):
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                BlockDatabasePanel {{
                    background: {colors.bg_tertiary};
                    border: 1px solid {colors.info};
                    border-radius: 4px;
                }}
            """)

    def dragLeaveEvent(self, event):
        """Remove highlight on exit"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self.setStyleSheet(f"""
            BlockDatabasePanel {{
                background: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
            }}
            BlockDatabasePanel:hover {{
                border-color: {colors.border_strong};
            }}
        """)

    def dropEvent(self, event):
        """Receive dragged database"""
        if event.mimeData().hasFormat("application/x-database-name"):
            database_name = event.mimeData().data("application/x-database-name").data().decode("utf-8")
            self.database_dropped.emit(database_name)
            event.acceptProposedAction()

            # Restore style
            self.dragLeaveEvent(event)


class CodeBlock(QFrame):
    """
    An individual code block.

    Contains:
    - Control bar (language, run, remove)
    - Monaco editor
    """

    execute_requested = pyqtSignal(object, str)  # self, selected_text
    remove_requested = pyqtSignal(object)  # self
    move_requested = pyqtSignal(object, int)  # self, new_index (-1 = drag started)
    language_changed = pyqtSignal(object, str)  # self, new_language
    focus_changed = pyqtSignal(object, bool)  # self, has_focus
    cancel_requested = pyqtSignal(object)  # self - to cancel execution
    select_connection_requested = pyqtSignal(object)  # self - to open connection dialog
    connection_name_changed = pyqtSignal(object, str)  # self, connection_name - when block connection changes
    database_changed = pyqtSignal(object, str)  # self, database_name - when block database changes
    completion_log = pyqtSignal(str, str)  # message, level - for autocomplete logging
    maximize_requested = pyqtSignal(object)  # self - toggle maximize/restore
    download_requested = pyqtSignal(object, str)  # self, export_format ("csv"|"parquet")
    cancel_download_requested = pyqtSignal(object)  # self
    reveal_file_requested = pyqtSignal(str)  # absolute file path

    LANGUAGE_COLORS = {"python": "#3572A5", "sql": "#E38C00"}
    BLOCK_RADIUS = 12

    # Initial editor heights (in pixels, ~20px per line)
    DEFAULT_SQL_HEIGHT = 400     # ~20 lines for SQL blocks
    DEFAULT_PYTHON_HEIGHT = 200  # ~10 lines for Python blocks

    def __init__(self, theme_manager: ThemeManager = None, parent=None, default_language="sql"):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._is_focused = False
        self._is_running = False
        self._is_waiting = False
        self._is_cancelling = False
        self._is_resizing = False
        self._resize_start_y = 0
        self._resize_start_height = 0
        self._execution_start_time = 0
        self._custom_running_status = ""
        self._last_execution_time = None
        self._execution_tick_timer = QTimer(self)
        self._execution_tick_timer.setInterval(100)
        self._execution_tick_timer.timeout.connect(self._update_running_elapsed)
        self._sql_parameter_sync_timer = QTimer(self)
        self._sql_parameter_sync_timer.setSingleShot(True)
        self._sql_parameter_sync_timer.setInterval(250)
        self._sql_parameter_sync_timer.timeout.connect(self.sync_sql_parameters_from_query)
        self._lsp_document_sync_timer = QTimer(self)
        self._lsp_document_sync_timer.setSingleShot(True)
        self._lsp_document_sync_timer.setInterval(650)
        self._lsp_document_sync_timer.timeout.connect(self._sync_lsp_document)
        self._default_language = default_language
        self._connection_name = None  # None = use session connection
        self._database_name = None  # None = use connection default database
        self._sql_parameters = []  # Custom SQL parameters detected from @name tokens
        self._sql_parameters_enabled = True  # False = user chose to define variables manually in the query
        self._sql_schema = {}  # Cached SQL schema for parameter inference/autocomplete
        self._block_name = ""  # Block name (namespace prefix)
        self._block_key = uuid.uuid4().hex  # Stable id for per-block DB sessions
        self._block_editor = None  # BlockEditor parent container
        self._is_copilot_editing = False  # Copilot is editing this block
        self._copilot_editing_timer = None  # Auto-dismiss timer
        self._copilot_animation = None
        self._spinner_animation = None
        self._is_maximized = False  # Block is in maximized/focus mode
        self._is_active = True  # Block is active (included in execute all)

        self._setup_ui()
        self._connect_signals()
        # Set initial language explicitly (setCurrentIndex doesn't fire signal during init)
        self.editor.set_language(self._default_language)
        self._update_style()
        self._update_connection_panel_visibility()  # Update connection panel visibility (after language)
        
        # Initialize completions based on language
        if self._default_language == "python":
            self._update_python_completions()
        
        # Set initial height based on language (SQL = larger, Python = smaller)
        initial_height = self.DEFAULT_SQL_HEIGHT if self._default_language == "sql" else self.DEFAULT_PYTHON_HEIGHT
        self._set_editor_height(initial_height)

    def closeEvent(self, event):
        """Stop timers to prevent callbacks on deleted C++ objects."""
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self):
        try:
            self._execution_tick_timer.stop()
        except RuntimeError:
            pass

        try:
            self._sql_parameter_sync_timer.stop()
        except RuntimeError:
            pass

        if self._copilot_editing_timer is not None:
            try:
                self._copilot_editing_timer.stop()
            except RuntimeError:
                pass
            self._copilot_editing_timer = None

        for animation_name in ("_copilot_animation", "_spinner_animation"):
            animation = getattr(self, animation_name, None)
            if animation is not None:
                try:
                    animation.stop()
                except RuntimeError:
                    pass
                setattr(self, animation_name, None)

        try:
            self._spinner_widget.hide()
        except RuntimeError:
            pass

        if hasattr(self, "_completion_service") and self._completion_service is not None:
            try:
                self._completion_service.cancel()
            except RuntimeError:
                pass
            self._completion_service = None

        editor = getattr(self, "editor", None)
        if editor is not None and hasattr(editor, "cleanup"):
            try:
                editor.cleanup()
            except RuntimeError:
                pass

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Import design tokens
        from src.design_system.tokens import get_colors
        colors = get_colors()

        # Default height for all header controls
        CTRL_H = 26

        # Shared base style for header inputs/combos (using design tokens)
        _input_base_style = f"""
            background: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            min-height: {CTRL_H - 4}px;
            max-height: {CTRL_H - 4}px;
        """

        # === Control bar ===
        self.control_bar = QWidget()
        self.control_bar.setFixedHeight(42)
        self.control_bar.setObjectName("controlBar")
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setContentsMargins(8, 6, 12, 6)
        control_layout.setSpacing(8)

        # Drag handle - primeiro elemento (para arrastar o bloco)
        self.drag_handle = QPushButton()
        self.drag_handle.setFixedSize(CTRL_H, CTRL_H)
        self.drag_handle.setToolTip(S.block.tooltip_drag)
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_handle.setIcon(qta.icon("mdi.drag-horizontal-variant", color=colors.text_tertiary))
        self.drag_handle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {colors.bg_elevated};
            }}
        """)
        self.drag_handle.pressed.connect(self._start_drag)
        control_layout.addWidget(self.drag_handle)

        # Run button (play icon)
        self.run_btn = QPushButton()
        self.run_btn.setFixedSize(26, 26)
        self.run_btn.setToolTip(S.block.tooltip_run)
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_icon_play = True
        self.run_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.run_btn.customContextMenuRequested.connect(self._on_run_btn_context_menu)
        control_layout.addWidget(self.run_btn)

        # Language selector with icons
        self.lang_combo = QComboBox()
        self.lang_combo.addItem(qta.icon("mdi.database", color="#E38C00"), "SQL", "sql")
        self.lang_combo.addItem(qta.icon("mdi.language-python", color="#3572A5"), "Python", "python")
        if self._default_language == "sql":
            self.lang_combo.setCurrentIndex(0)
        else:
            self.lang_combo.setCurrentIndex(1)
        self.lang_combo.setFixedHeight(CTRL_H)
        self.lang_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.lang_combo.setMinimumWidth(96)
        from src.design_system.tokens import apply_combobox_style

        apply_combobox_style(self.lang_combo, variant="block_header", icon_size=14)
        control_layout.addWidget(self.lang_combo)

        # Status with spinner - ao lado do dropdown de linguagem
        self._spinner_widget = qta.IconWidget()
        self._spinner_widget.setFixedSize(16, 16)
        self._spinner_widget.hide()
        control_layout.addWidget(self._spinner_widget)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_secondary};
                font-size: 11px;
                padding: 2px 8px;
                background: transparent;
            }}
        """)
        control_layout.addWidget(self.status_label)

        # Copilot editing indicator (hidden by default)
        self._copilot_indicator = QWidget()
        copilot_ind_layout = QHBoxLayout(self._copilot_indicator)
        copilot_ind_layout.setContentsMargins(4, 0, 4, 0)
        copilot_ind_layout.setSpacing(4)
        self._copilot_icon = QLabel()
        self._copilot_icon.setFixedSize(16, 16)
        self._copilot_icon.setScaledContents(True)
        from src.assets.pynia_branding import load_pynia_logo

        pynia_logo = load_pynia_logo(16)
        if pynia_logo:
            self._copilot_icon.setPixmap(pynia_logo.pixmap(16, 16))
        copilot_ind_layout.addWidget(self._copilot_icon)
        label_text = getattr(S.block, "pynia_editing", None) or getattr(
            S.block, "copilot_editing", "Pynia editing..."
        )
        self._copilot_label = QLabel(label_text)
        self._copilot_label.setStyleSheet("""
            QLabel {
                color: #b48ead;
                font-size: 11px;
                font-style: italic;
                background: transparent;
                padding: 0;
            }
        """)
        copilot_ind_layout.addWidget(self._copilot_label)
        self._copilot_indicator.setStyleSheet("background: transparent;")
        self._copilot_indicator.hide()
        control_layout.addWidget(self._copilot_indicator)

        # Language indicator (hidden, kept for compatibility)
        self.lang_indicator = QFrame()
        self.lang_indicator.hide()

        control_layout.addStretch()

        # Connection panel (only visible for SQL) - lado direito
        self.conn_panel = BlockConnectionPanel()
        self.conn_panel.setFixedHeight(CTRL_H)
        self.conn_panel.setMinimumWidth(100)
        self.conn_panel.setMaximumWidth(220)
        control_layout.addWidget(self.conn_panel)

        # Database panel (only visible for SQL)
        self.db_panel = BlockDatabasePanel()
        self.db_panel.setFixedHeight(CTRL_H)
        self.db_panel.setMinimumWidth(80)
        self.db_panel.setMaximumWidth(180)
        control_layout.addWidget(self.db_panel)

        from src.ui.components.toggle_switch import ToggleSwitch

        self.active_toggle = ToggleSwitch(checked=True)
        self.active_toggle.setToolTip(S.block.tooltip_active)
        self.active_toggle.toggled.connect(self._on_active_toggled)
        control_layout.addWidget(self.active_toggle)

        # Block name field (becomes dataframe variable name for SQL)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(S.block.placeholder_name)
        self.name_input.setToolTip(S.block.tooltip_block_name)
        self.name_input.setFixedWidth(120)
        self.name_input.setFixedHeight(CTRL_H)
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {colors.interactive_primary};
            }}
            QLineEdit::placeholder {{
                color: {colors.text_tertiary};
            }}
        """)
        control_layout.addWidget(self.name_input)

        self.show_sql_parameters_btn = QPushButton()
        self.show_sql_parameters_btn.setIcon(qta.icon("mdi.function-variant", color=colors.text_tertiary))
        self.show_sql_parameters_btn.setFixedSize(CTRL_H, CTRL_H)
        self.show_sql_parameters_btn.setToolTip(S.sql_parameters.tooltip_show_panel)
        self.show_sql_parameters_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_sql_parameters_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {colors.bg_elevated};
            }}
        """)
        self.show_sql_parameters_btn.hide()
        control_layout.addWidget(self.show_sql_parameters_btn)

        # Maximize button (expand/collapse icon)
        self.maximize_btn = QPushButton()
        self.maximize_btn.setIcon(qta.icon("mdi.arrow-expand", color=colors.text_tertiary))
        self.maximize_btn.setFixedSize(CTRL_H, CTRL_H)
        self.maximize_btn.setToolTip(S.block.tooltip_maximize)
        self.maximize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.maximize_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba(100, 100, 255, 0.15);
            }}
        """)
        control_layout.addWidget(self.maximize_btn)

        # Remove button (discrete X icon)
        self.remove_btn = QPushButton()
        self.remove_btn.setIcon(qta.icon("mdi.close", color=colors.text_tertiary))
        self.remove_btn.setFixedSize(CTRL_H, CTRL_H)
        self.remove_btn.setToolTip(S.block.tooltip_remove)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba(239, 68, 68, 0.15);
            }}
            QPushButton:hover QIcon {{
                color: {colors.danger};
            }}
        """)
        control_layout.addWidget(self.remove_btn)

        layout.addWidget(self.control_bar)

        # === Editor Container (resizable) ===
        self.editor_container = QWidget()
        self.editor_container.setObjectName("editorContainer")
        self.editor_container.setMinimumHeight(80)
        self.editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self.editor_body = QWidget()
        editor_body_layout = QHBoxLayout(self.editor_body)
        editor_body_layout.setContentsMargins(0, 0, 0, 0)
        editor_body_layout.setSpacing(0)

        self.sql_parameters_panel = SqlParametersPanel()
        self.sql_parameters_panel.hide()
        editor_body_layout.addWidget(self.sql_parameters_panel)

        # Monaco Editor with Copilot inline completions
        EditorClass = get_code_editor_class()
        self.editor = EditorClass(theme_manager=self.theme_manager)
        editor_body_layout.addWidget(self.editor.get_widget(), 1)
        editor_layout.addWidget(self.editor_body)

        layout.addWidget(self.editor_container, 1)  # stretch=1 to expand

        # === Download progress (below editor, above resize handle) ===
        self.download_progress_container = QWidget()
        self.download_progress_container.setObjectName("downloadProgressContainer")
        self._download_progress_layout = QVBoxLayout(self.download_progress_container)
        self._download_progress_layout.setContentsMargins(8, 4, 8, 4)
        self._download_progress_layout.setSpacing(4)
        self.download_progress_container.setStyleSheet(f"""
            QWidget#downloadProgressContainer {{
                background: {colors.bg_tertiary};
                border-top: 1px solid {colors.border_default};
            }}
        """)
        self.download_progress_container.hide()
        self._download_bars: dict[int, object] = {}
        layout.addWidget(self.download_progress_container)


        # === Resize handle ===
        self.resize_handle = QFrame()
        self.resize_handle.setFixedHeight(6)
        self.resize_handle.setCursor(Qt.CursorShape.SizeVerCursor)
        self.resize_handle.setStyleSheet(f"""
            QFrame {{ background: transparent; }}
            QFrame:hover {{ background: {colors.border_strong}; }}
        """)
        self.resize_handle.mousePressEvent = self._resize_start
        self.resize_handle.mouseMoveEvent = self._resize_move
        self.resize_handle.mouseReleaseEvent = self._resize_end
        layout.addWidget(self.resize_handle)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _connect_signals(self):
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.conn_panel.connection_clicked.connect(self._on_connection_panel_clicked)
        self.conn_panel.connection_dropped.connect(self._on_connection_dropped)
        self.db_panel.database_clicked.connect(self._on_database_panel_clicked)
        self.db_panel.database_dropped.connect(self._on_database_dropped)
        self.db_panel.database_selected.connect(self._on_database_selected)
        self.run_btn.clicked.connect(self._on_run_btn_clicked)
        self.maximize_btn.clicked.connect(lambda: self.maximize_requested.emit(self))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        self.editor.execute_requested.connect(lambda sel: self.execute_requested.emit(self, sel))
        self.editor.SCN_FOCUSIN.connect(self._on_focus_in)
        self.editor.SCN_FOCUSOUT.connect(self._on_focus_out)
        self.editor.textChanged.connect(self._schedule_sql_parameter_sync)
        self.editor.textChanged.connect(self._schedule_lsp_document_sync)
        self._sync_syntax_dialect_to_editor()
        self.sql_parameters_panel.parameters_changed.connect(self._on_sql_parameters_panel_changed)
        self.sql_parameters_panel.close_requested.connect(self._on_sql_parameters_panel_close_requested)
        self.show_sql_parameters_btn.clicked.connect(lambda: self.set_sql_parameters_enabled(True))
        
        # Setup inline completion service for Copilot
        if hasattr(self.editor, 'completion_requested'):
            self._setup_monaco_completion()

    def _on_focus_in(self):
        self._is_focused = True
        self._update_style()
        self.focus_changed.emit(self, True)
        # Re-sync LSP document for this block (several blocks share one client).
        if hasattr(self, "_completion_service"):
            self._update_document_info()
            text = self.get_code()
            lang = self.get_language()
            uri = f"file:///datapyn/block_{id(self)}.{self._get_extension()}"
            self._completion_service.open_document(uri, lang, text)

    def _on_focus_out(self):
        self._is_focused = False
        self._update_style()
        self.focus_changed.emit(self, False)

    def set_maximized(self, maximized: bool):
        """Update visual state for maximized/normal mode."""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        self._is_maximized = maximized
        if maximized:
            self.maximize_btn.setIcon(qta.icon("mdi.arrow-collapse", color=colors.text_tertiary))
            self.maximize_btn.setToolTip(S.block.tooltip_restore)
            # Remove fixed height so editor fills all available space
            self.editor_container.setMinimumHeight(0)
            self.editor_container.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            self.editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.resize_handle.hide()
        else:
            self.maximize_btn.setIcon(qta.icon("mdi.arrow-expand", color=colors.text_tertiary))
            self.maximize_btn.setToolTip(S.block.tooltip_maximize)
            self.editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.resize_handle.show()
        self._apply_block_chrome()

    @property
    def is_maximized(self) -> bool:
        return self._is_maximized

    def _on_run_btn_clicked(self):
        """Handle run button click - execute or cancel depending on state"""
        state = self.__dict__
        if state.get("_is_cancelling", False):
            return
        if state.get("_is_running", False):
            self.cancel_requested.emit(self)
        elif hasattr(self.editor, "request_execute"):
            self.editor.request_execute()
        else:
            self.execute_requested.emit(self, "")

    def _on_run_btn_context_menu(self, pos: QPoint) -> None:
        """Right-click: run query and stream results to a local file."""
        if self.get_language() != "sql":
            return
        if self.__dict__.get("_is_running") or self.__dict__.get("_is_cancelling"):
            return

        menu = QMenu(self)
        download_menu = menu.addMenu(
            getattr(S.block, "ctx_run_and_download", "Run and Download")
        )
        csv_action = download_menu.addAction(
            getattr(S.block, "download_csv", "CSV…")
        )
        parquet_action = download_menu.addAction(
            getattr(S.block, "download_parquet", "Parquet…")
        )
        chosen = menu.exec(self.run_btn.mapToGlobal(pos))
        if chosen is csv_action:
            self.download_requested.emit(self, "csv")
        elif chosen is parquet_action:
            self.download_requested.emit(self, "parquet")

    def _setup_monaco_completion(self):
        """Setup inline completion for Monaco editor."""
        from src.editors.monaco import InlineCompletionService
        
        self._completion_service = InlineCompletionService(self)
        self._completion_request_line = 1
        self._completion_request_column = 1

        # Connect completion request from Monaco to service
        self.editor.completion_requested.connect(self._on_completion_requested)
        
        # Connect force completion request (Ctrl+.)
        self.editor.force_completion_requested.connect(self._on_force_completion_requested)

        bridge = getattr(self.editor, "_bridge", None)
        if bridge is not None:
            bridge.cancel_inline_completion.connect(self._cancel_noisy_completions)
        
        # Connect service completion ready to Monaco with logging
        def on_completion_ready(text):
            if text:
                self.completion_log.emit(
                    f"[CodeBlock] Forwarding {len(text)} chars to Monaco", "info"
                )
            self.editor.provide_completion(
                text,
                getattr(self, "_completion_request_line", 1),
                getattr(self, "_completion_request_column", 1),
            )
        
        self._completion_service.completion_ready.connect(on_completion_ready)
        
        # Forward log messages from completion service
        self._completion_service.log_message.connect(self.completion_log.emit)
        
        # Set document info for LSP
        self._update_document_info()
    
    def _update_document_info(self):
        """Update document info for LSP completions."""
        if not hasattr(self, '_completion_service'):
            return
        
        # Generate a unique URI for this block
        # Use object id to ensure uniqueness within the session
        uri = f"file:///datapyn/block_{id(self)}.{self._get_extension()}"
        language = self.get_language()
        
        self._completion_service.set_document_info(uri, language)
        
        # Open document in LSP if available
        text = self.get_code()
        self._completion_service.open_document(uri, language, text)
    
    def set_block_editor(self, editor) -> None:
        """Attach parent BlockEditor for session-scoped completions."""
        self._block_editor = editor

    def _completion_namespace(self) -> dict:
        if self._block_editor is not None and hasattr(
            self._block_editor, "_get_completion_namespace"
        ):
            return self._block_editor._get_completion_namespace()
        return ApplicationState.instance().get_namespace()

    def _update_python_completions(self):
        """Update Python completions with current session namespace."""
        self.set_python_namespace(self._completion_namespace())
    
    def _get_extension(self) -> str:
        """Get file extension for current language."""
        lang = self.get_language()
        if lang == "python":
            return "py"
        elif lang == "sql":
            return "sql"
        return "txt"
    
    def set_pynia_client(self, client):
        """Set Pynia agent client for AI inline autocomplete (Monaco only)."""
        if hasattr(self, "_completion_service"):
            self._completion_service.set_pynia_client(client)

    def set_copilot_client(self, client):
        """Backward-compatible alias for set_pynia_client."""
        self.set_pynia_client(client)

    def set_lsp_client(self, client):
        """Attach GitHub Copilot LSP for ghost-text completions."""
        if hasattr(self, "_completion_service"):
            self._completion_service.set_lsp_client(client)
            self._update_document_info()

    def _cancel_noisy_completions(self) -> None:
        """Drop in-flight ghost-text while the user is still typing."""
        if hasattr(self, "_completion_service"):
            self._completion_service.cancel_request()

    def _schedule_lsp_document_sync(self):
        if not hasattr(self, "_completion_service") or not self._completion_service.has_lsp:
            return
        self._lsp_document_sync_timer.start()

    def _sync_lsp_document(self):
        if not hasattr(self, "_completion_service") or not self._completion_service.has_lsp:
            return
        text = self.editor.get_text() if hasattr(self.editor, "get_text") else ""
        self._completion_service.notify_document_changed(text)
    
    def set_database_context(self, context: str):
        """Set database schema context for SQL completions (Monaco only)."""
        if hasattr(self, '_completion_service'):
            self._completion_service.set_database_context(context)

    def get_sql_schema(self) -> dict:
        """Return this block's SQL schema (tables/columns for autocomplete)."""
        return dict(self._sql_schema) if self._sql_schema else {}

    def set_sql_schema(self, schema: dict):
        """Set SQL schema for completions and parameter type inference."""
        self._sql_schema = schema or {}
        if hasattr(self.editor, "set_sql_schema"):
            self.editor.set_sql_schema(self._sql_schema)
        if self.get_language() == "sql":
            self.sync_sql_parameters_from_query()
    
    def set_python_namespace(self, namespace: dict):
        """Set Python namespace for completions (Monaco only).

        Args:
            namespace: Runtime variables (objects) or name -> type-name strings.
        """
        if hasattr(self, "_completion_service"):
            self._completion_service.set_python_namespace(namespace)
        if hasattr(self.editor, "set_python_namespace"):
            self.editor.set_python_namespace(namespace)
    
    def set_blocks_code_context(self, code_context: str):
        """Set code context from other blocks for completions (Monaco only).

        Args:
            code_context: Combined code from other blocks
        """
        if hasattr(self, "_completion_service"):
            self._completion_service.set_blocks_code_context(code_context)

    def set_lsp_completion_preamble(self, preamble: str, line_offset: int) -> None:
        """Session preamble for Copilot LSP (full tab context, not shown in Monaco)."""
        if hasattr(self, "_completion_service"):
            self._completion_service.set_lsp_preamble(preamble, line_offset)

    def apply_session_completion_context(
        self,
        *,
        namespace: Optional[dict] = None,
        global_imports: str = "",
        blocks_code_context: str = "",
        lsp_preamble: str = "",
        lsp_line_offset: int = 0,
    ) -> None:
        """Push in-memory session context into Monaco + LSP for this block."""
        self.set_blocks_code_context(blocks_code_context)
        self.set_lsp_completion_preamble(lsp_preamble, lsp_line_offset)
        if namespace is not None:
            self.set_python_namespace(namespace)
        if hasattr(self.editor, "set_global_imports"):
            self.editor.set_global_imports(global_imports)
    
    def _on_completion_requested(self, prefix: str, suffix: str, line: int, column: int):
        """Handle completion request from Monaco editor."""
        if hasattr(self, "_completion_service"):
            self._completion_request_line = line
            self._completion_request_column = column
            language = self.get_language()

            self._completion_service.request_completion(
                prefix, suffix, language, line, column
            )
    
    def _on_force_completion_requested(self, prefix: str, suffix: str, line: int, column: int):
        """Handle force completion request (Ctrl+.) from Monaco editor."""
        if hasattr(self, "_completion_service"):
            self._completion_request_line = line
            self._completion_request_column = column
            language = self.get_language()

            self._completion_service.force_completion(
                prefix, suffix, language, line, column
            )
    
    def force_autocomplete(self):
        """Force trigger autocomplete (Ctrl+. shortcut).
        
        Bypasses throttling and minimum prefix checks, sending the full
        block content to the LSP for completion.
        """
        # Monaco editor handles everything internally: gets cursor position,
        # calculates prefix/suffix, and calls requestCompletion
        if hasattr(self.editor, 'force_request_completion'):
            self.editor.force_request_completion()

    def _sync_syntax_dialect_to_editor(self) -> None:
        if hasattr(self.editor, "set_sql_dialect"):
            db_type = getattr(self.conn_panel, "_db_type", None) or ""
            self.editor.set_sql_dialect(db_type)

    def _on_language_changed(self):
        lang = self.lang_combo.currentData()
        self.editor.set_language(lang)
        self._sync_syntax_dialect_to_editor()
        self._update_connection_panel_visibility()
        self._update_style()
        self._schedule_sql_parameter_sync()
        
        # Update document info for LSP with new language
        self._update_document_info()
        
        # Update Python completions if switching to Python
        if lang == "python":
            self._update_python_completions()
        
        self.language_changed.emit(self, lang)

    def _on_connection_panel_clicked(self):
        """Connection panel was clicked - emit signal to open dialog"""
        self.select_connection_requested.emit(self)

    def _on_connection_dropped(self, connection_name: str, db_type: str, color: str):
        """Connection was dragged to panel"""
        self._connection_name = connection_name
        self.conn_panel.set_connection(connection_name, db_type or None, color or None)
        self._sync_syntax_dialect_to_editor()
        self.connection_name_changed.emit(self, connection_name)

    def _on_database_panel_clicked(self):
        """Database panel was clicked - emit signal (fallback when no db list)"""
        self.database_changed.emit(self, self._database_name or "")

    def _on_database_selected(self, database_name: str):
        """Database was selected from popup menu."""
        self._database_name = database_name or None
        self.database_changed.emit(self, database_name or "")

    def _on_database_dropped(self, database_name: str):
        """Database was dragged from Object Explorer to panel"""
        self._database_name = database_name
        self.db_panel.set_database(database_name)
        self.database_changed.emit(self, database_name or "")

    def _update_connection_panel_visibility(self):
        """Update connection and database panel visibility (SQL only)"""
        lang = self.lang_combo.currentData()
        is_sql = lang == "sql"
        self.conn_panel.setVisible(is_sql)
        self.db_panel.setVisible(is_sql)
        if not is_sql:
            self._refresh_sql_parameter_ui()
        else:
            self.sync_sql_parameters_from_query()

    def _schedule_sql_parameter_sync(self):
        """Debounce parameter detection while the user edits SQL."""
        if self.get_language() != "sql":
            self._refresh_sql_parameter_ui()
            return
        if self._query_removed_tracked_sql_parameters(self.get_code()):
            self.sync_sql_parameters_from_query()
            return
        self._sql_parameter_sync_timer.start()

    def _query_removed_tracked_sql_parameters(self, query: str) -> bool:
        """Return True when the current SQL no longer contains an existing tracked parameter."""
        if not self._sql_parameters:
            return False

        tracked_parameter_ids = {
            normalize_parameter_definition(parameter).get("id")
            for parameter in self._sql_parameters
            if isinstance(parameter, dict)
        }
        if not tracked_parameter_ids:
            return False

        query_parameter_ids = {token.id for token in extract_sql_parameter_tokens(query)}
        return bool(tracked_parameter_ids - query_parameter_ids)

    def _on_sql_parameters_panel_close_requested(self):
        self.set_sql_parameters_enabled(False)

    def _on_sql_parameters_panel_changed(self, parameters: list):
        """Receive edited parameter definitions from the side panel."""
        self._sql_parameters = [
            normalize_parameter_definition(parameter, index)
            for index, parameter in enumerate(parameters or [])
        ]
        self._refresh_sql_parameter_ui()

    def _refresh_sql_parameter_ui(self):
        is_sql = self.get_language() == "sql"
        has_parameters = bool(self._sql_parameters)
        self.sql_parameters_panel.setVisible(is_sql and self._sql_parameters_enabled and has_parameters)
        self.show_sql_parameters_btn.setVisible(is_sql and (not self._sql_parameters_enabled) and has_parameters)

    def sync_sql_parameters_from_query(self):
        """Detect @parameters in SQL and merge them with existing settings."""
        if not hasattr(self, "sql_parameters_panel"):
            return
        if self.get_language() != "sql":
            self._refresh_sql_parameter_ui()
            return

        merged = merge_parameter_definitions(self.get_code(), self._sql_parameters, self._sql_schema)
        self._sql_parameters = [
            normalize_parameter_definition(parameter, index)
            for index, parameter in enumerate(merged)
        ]
        self.sql_parameters_panel.set_parameters(self._sql_parameters)
        self._refresh_sql_parameter_ui()

    def _update_style(self):
        lang = self.get_language()
        color = self.LANGUAGE_COLORS.get(lang, "#888")

        from src.design_system.tokens import get_colors
        colors = get_colors()

        # Play button - fundo escuro, icone colorido (ou stop vermelho quando running)
        self._current_lang_color = color
        if not self._is_running:
            self.run_btn.setEnabled(True)
            self.run_btn.setToolTip(S.block.tooltip_run)
            self.run_btn.setIcon(qta.icon("mdi.play", color=color))
            self.run_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {colors.bg_tertiary};
                    border: 1px solid {colors.border_default};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {colors.bg_elevated};
                    border-color: {color};
                }}
                QPushButton:pressed {{
                    background: {colors.bg_primary};
                }}
            """)

        self._apply_block_chrome()

    def _apply_block_chrome(self) -> None:
        """Unified card border, radius, and focus accent aligned with the block shell."""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        lang = self.get_language()
        accent = self.LANGUAGE_COLORS.get(lang, "#888")
        radius = 0 if self._is_maximized else self.BLOCK_RADIUS

        if self._is_copilot_editing:
            accent_left = "#b48ead"
        elif self._is_focused:
            accent_left = colors.interactive_primary
        else:
            accent_left = "transparent"

        self.setStyleSheet(f"""
            CodeBlock {{
                background-color: {colors.bg_secondary};
                border: none;
                border-left: 3px solid {accent_left};
                border-radius: {radius}px;
            }}
        """)

        self.control_bar.setStyleSheet(f"""
            QWidget#controlBar {{
                background: {colors.bg_secondary};
                border: none;
                border-bottom: 1px solid {colors.border_muted};
                border-top-left-radius: {radius}px;
                border-top-right-radius: {radius}px;
            }}
        """)

        bottom_r = radius
        self.editor_container.setStyleSheet(f"""
            QWidget#editorContainer {{
                background: {colors.editor_bg};
                border: none;
                border-bottom-left-radius: {bottom_r}px;
                border-bottom-right-radius: {bottom_r}px;
            }}
        """)

        handle_r = max(0, radius - 2)
        self.resize_handle.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border-bottom-left-radius: {handle_r}px;
                border-bottom-right-radius: {handle_r}px;
            }}
            QFrame:hover {{
                background: {colors.border_strong};
            }}
        """)
        self._update_inactive_visual()

    def _on_active_toggled(self, checked: bool):
        self._is_active = checked
        self._update_inactive_visual()

    def _update_inactive_visual(self):
        """Dim inactive blocks without QGraphicsOpacityEffect (breaks QWebEngine/Monaco)."""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        active = self._is_active
        editor = getattr(self, "editor", None)
        if editor is not None and hasattr(editor, "set_read_only"):
            editor.set_read_only(not active)
        self.editor_container.setGraphicsEffect(None)
        self.editor_container.setEnabled(True)
        bottom_r = 0 if self._is_maximized else self.BLOCK_RADIUS
        bg = colors.bg_primary if active else colors.bg_tertiary
        self.editor_container.setStyleSheet(f"""
            QWidget#editorContainer {{
                background: {bg};
                border: none;
                border-bottom-left-radius: {bottom_r}px;
                border-bottom-right-radius: {bottom_r}px;
            }}
        """)
        self.control_bar.setEnabled(True)
        bar_bg = colors.bg_secondary if active else colors.bg_tertiary
        radius = 0 if self._is_maximized else self.BLOCK_RADIUS
        self.control_bar.setStyleSheet(f"""
            QWidget#controlBar {{
                background: {bar_bg};
                border: none;
                border-bottom: 1px solid {colors.border_muted};
                border-top-left-radius: {radius}px;
                border-top-right-radius: {radius}px;
            }}
        """)

    # === Public API ===

    def is_active(self) -> bool:
        """Return whether this block is active (included in execute all)"""
        return self._is_active

    def set_active(self, active: bool):
        """Set active state"""
        self._is_active = active
        self.active_toggle.setChecked(active, animate=False)
        self._update_inactive_visual()

    def get_language(self) -> str:
        return self.lang_combo.currentData()

    def set_language(self, lang: str):
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
            # Ensure the editor is updated even on programmatic changes
            self._on_language_changed()

    def get_code(self) -> str:
        return self.editor.get_text()

    def set_code(self, code: str):
        self.editor.set_text(code)
        self.sync_sql_parameters_from_query()

    def get_selected_text(self) -> str:
        return self.editor.get_selected_text()

    def has_selection(self) -> bool:
        return self.editor.has_selection()

    def get_block_key(self) -> str:
        """Unique id for this block's isolated database session."""
        return self._block_key

    def get_block_name(self) -> str:
        """Return block name (used as namespace prefix)"""
        return self.name_input.text().strip()

    def set_block_name(self, name: str):
        """Set block name"""
        self._block_name = name
        self.name_input.setText(name)

    def get_sql_parameters(self) -> list:
        """Return persisted SQL parameter definitions for this block."""
        self.sync_sql_parameters_from_query()
        return [dict(parameter) for parameter in self._sql_parameters]

    def is_sql_parameters_enabled(self) -> bool:
        """Return whether this block uses the custom SQL parameter panel."""
        return bool(self._sql_parameters_enabled)

    def set_sql_parameters_enabled(self, enabled: bool):
        """Enable or disable the custom SQL parameter panel for this block."""
        self._sql_parameters_enabled = bool(enabled)
        self._refresh_sql_parameter_ui()

    def set_sql_parameters(self, parameters: list):
        """Set SQL parameter definitions and sync with current SQL text."""
        self._sql_parameters = [
            normalize_parameter_definition(parameter, index)
            for index, parameter in enumerate(parameters or [])
            if isinstance(parameter, dict)
        ]
        self.sync_sql_parameters_from_query()

    def get_sql_parameters_for_query(self, query: str) -> list:
        """Return parameter definitions used by a full or selected SQL query."""
        self.sync_sql_parameters_from_query()
        if not self._sql_parameters_enabled:
            return []
        return filter_parameters_for_query(query, self._sql_parameters)

    def get_connection_name(self) -> str:
        """Return custom connection name or None (uses tab default)"""
        return self._connection_name

    def set_connection_name(self, conn_name: str, db_type: str = None, color: str = None):
        """Set custom connection for this block"""
        self._connection_name = conn_name
        self.conn_panel.set_connection(conn_name, db_type, color)
        self._sync_syntax_dialect_to_editor()
        self.connection_name_changed.emit(self, conn_name)

    def set_connection_locked(self, locked: bool):
        """Lock/unlock connection changes (first block cannot change connection)"""
        self.conn_panel.set_locked(locked)

    def is_connection_locked(self) -> bool:
        """Return whether connection changes are locked"""
        return self.conn_panel.is_locked()

    def get_database_name(self) -> str:
        """Return custom database name or None (uses connection default)"""
        return self._database_name

    def uses_tab_default_database(self) -> bool:
        """True when this block follows the session tab database (not a per-block override)."""
        return not self._database_name

    def set_database_name(self, database_name: str):
        """Set custom database for this block"""
        self._database_name = database_name
        self.db_panel.set_database(database_name)
        self.database_changed.emit(self, database_name or "")

    def set_available_databases(self, databases: list):
        """Set list of databases available for this block's connection."""
        self.db_panel.set_available_databases(databases)

    def is_focused(self) -> bool:
        return self._is_focused

    def set_pynia_editing(self, editing: bool):
        """Highlight block while Pynia edits it."""
        self.set_copilot_editing(editing)

    def set_copilot_editing(self, editing: bool):
        """Show/hide Copilot editing indicator on this block.
        
        When editing=True, shows a pulsing sparkle icon and purple left border.
        Auto-dismisses after 2 seconds if not explicitly turned off.
        """
        from PyQt6.QtCore import QTimer
        self._is_copilot_editing = editing
        self._copilot_indicator.setVisible(editing)
        
        if self._copilot_animation is not None:
            self._copilot_animation.stop()
            self._copilot_animation = None
        if editing and hasattr(self._copilot_icon, "setPixmap"):
            from src.assets.pynia_branding import load_pynia_logo

            logo = load_pynia_logo(16)
            if logo:
                self._copilot_icon.setPixmap(logo.pixmap(16, 16))
        
        self._update_style()
        
        # Cancel any pending auto-dismiss timer
        if self._copilot_editing_timer is not None:
            self._copilot_editing_timer.stop()
            self._copilot_editing_timer = None
        
        if editing:
            # Auto-dismiss after 2 seconds
            self._copilot_editing_timer = QTimer(self)
            self._copilot_editing_timer.setSingleShot(True)
            self._copilot_editing_timer.timeout.connect(
                lambda: self.set_copilot_editing(False)
            )
            self._copilot_editing_timer.start(2000)

    def is_copilot_editing(self) -> bool:
        return self._is_copilot_editing

    def set_waiting(self, waiting: bool):
        """Set waiting in queue state"""
        self._is_waiting = waiting
        if waiting:
            self.run_btn.setIcon(qta.icon("mdi.pause", color="#95a5a6"))
            self.status_label.setText(S.block.status_waiting)
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #95a5a6;
                    font-size: 11px;
                    padding: 2px 6px;
                    background: rgba(149, 165, 166, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            if not self._is_running:
                self._update_style()

    def _set_spinner_spinning(self, color: str, *, counter_clockwise: bool = False) -> None:
        """Show animated spinner; clockwise when executing, CCW when cancelling."""
        step = -1 if counter_clockwise else 1
        if self._spinner_animation is not None:
            self._spinner_animation.stop()
        self._spinner_animation = qta.Spin(self._spinner_widget, step=step)
        spin_icon = qta.icon("fa5s.spinner", animation=self._spinner_animation, color=color)
        self._spinner_widget.setIcon(spin_icon)
        self._spinner_widget.show()

    def set_running_status(self, message: str):
        """Show a busy state on the block while work runs off the UI thread."""
        self._is_running = True
        self._is_waiting = False
        self._custom_running_status = str(message or "")
        if self._execution_start_time <= 0:
            self._execution_start_time = time.time()
        self.run_btn.setIcon(qta.icon("mdi.stop", color="#ef4444"))
        from src.design_system.tokens import get_colors
        colors = get_colors()
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {colors.bg_tertiary};
                border: 1px solid #ef4444;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba(239, 68, 68, 0.15);
            }}
        """)
        self.status_label.setText(self._custom_running_status)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #3498db;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(52, 152, 219, 0.12);
                border-radius: 4px;
            }
        """)
        self._set_spinner_spinning("#3498db", counter_clockwise=False)
        if not self._execution_tick_timer.isActive():
            self._execution_tick_timer.start()

    def set_running(self, running: bool):
        self._is_running = running
        self._is_waiting = False
        if running:
            self._is_cancelling = False
            self._custom_running_status = ""
            self._execution_start_time = time.time()
            # Stop icon vermelho quando executando
            self.run_btn.setIcon(qta.icon("mdi.stop", color="#ef4444"))
            from src.design_system.tokens import get_colors
            colors = get_colors()
            self.run_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {colors.bg_tertiary};
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: rgba(239, 68, 68, 0.15);
                }}
            """)
            self.status_label.setText(S.block.status_running)
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f39c12;
                    font-size: 11px;
                    padding: 2px 6px;
                    background: rgba(243, 156, 18, 0.1);
                    border-radius: 4px;
                }
            """)
            self._set_spinner_spinning("#f39c12", counter_clockwise=False)
            self._execution_tick_timer.start()
        else:
            self._custom_running_status = ""
            self._execution_tick_timer.stop()
            if self._spinner_animation is not None:
                self._spinner_animation.stop()
                self._spinner_animation = None
            self._spinner_widget.setIcon(qta.icon("fa5s.check", color="#2ecc71"))
            self._spinner_widget.show()
            self._update_style()  # Restore play icon with language color
            if self._execution_start_time > 0:
                elapsed = time.time() - self._execution_start_time
                self._last_execution_time = elapsed
                self._execution_start_time = 0
                self.status_label.setText(f"{self._format_execution_time(elapsed)}")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #2ecc71;
                        font-size: 11px;
                        padding: 2px 6px;
                        background: rgba(46, 204, 113, 0.1);
                        border-radius: 4px;
                    }
                """)
            elif self._last_execution_time and self._last_execution_time > 0:
                # Already finished before (double call) - keep existing time
                pass

    def set_cancelled(self):
        """Set cancelled state"""
        self._is_running = False
        self._is_waiting = False
        self._is_cancelling = False
        self._custom_running_status = ""
        self._execution_tick_timer.stop()
        if self._spinner_animation is not None:
            self._spinner_animation.stop()
            self._spinner_animation = None
        self._spinner_widget.setIcon(qta.icon("fa5s.spinner", color="#888"))
        self._spinner_widget.hide()
        self._update_style()
        self.status_label.setText(S.block.status_cancelled)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(231, 76, 60, 0.1);
                border-radius: 4px;
            }
        """)
        self._execution_start_time = 0

    def set_cancelling(self):
        """Set cancelling state while the SQL worker is still stopping."""
        self._is_running = True
        self._is_waiting = False
        self._is_cancelling = True
        self._custom_running_status = S.block.status_cancelling
        self.run_btn.setIcon(qta.icon("mdi.stop", color="#ef4444"))
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip(S.block.tooltip_cancelling)
        self.status_label.setText(S.block.status_cancelling)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e67e22;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(230, 126, 34, 0.12);
                border-radius: 4px;
            }
        """)
        self._set_spinner_spinning("#e67e22", counter_clockwise=True)
        if not self._execution_tick_timer.isActive():
            self._execution_tick_timer.start()

    def set_error(self):
        """Set error state"""
        self._is_running = False
        self._is_waiting = False
        self._custom_running_status = ""
        self._execution_tick_timer.stop()
        if self._spinner_animation is not None:
            self._spinner_animation.stop()
            self._spinner_animation = None
        self._spinner_widget.setIcon(qta.icon("fa5s.spinner", color="#888"))
        self._spinner_widget.hide()
        self._update_style()
        self.status_label.setText(S.block.status_error)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(231, 76, 60, 0.15);
                border-radius: 4px;
            }
        """)
        self._execution_start_time = 0

    def _format_execution_time(self, seconds: float) -> str:
        """Format execution time for display"""
        if seconds < 0.001:
            return f"{seconds * 1000000:.0f}µs"
        elif seconds < 1:
            return f"{seconds * 1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        else:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins}m {secs:.1f}s"

    def _update_running_elapsed(self):
        """Update the status label with elapsed time while running."""
        if not self._is_running or self._execution_start_time <= 0:
            self._execution_tick_timer.stop()
            return
        elapsed = time.time() - self._execution_start_time
        elapsed_str = self._format_execution_time(elapsed)
        if self._custom_running_status:
            self.status_label.setText(f"{self._custom_running_status} · {elapsed_str}")
            return
        running_text = getattr(S.block, 'status_running_elapsed', '{status} {elapsed}')
        self.status_label.setText(
            running_text.format(status=S.block.status_running, elapsed=elapsed_str)
        )

    def focus_editor(self):
        self.editor.setFocus()

    def apply_theme(self):
        self.editor.apply_theme()
        self._update_style()

    def to_dict(self) -> dict:
        data = {
            "language": self.get_language(),
            "code": self.get_code(),
            "height": self.editor_container.height(),
            "block_name": self.get_block_name(),
            "block_key": self._block_key,
            "is_active": self._is_active,
        }
        if self._connection_name:
            data["connection_name"] = self._connection_name
            # Save db_type to restore correct icon
            if hasattr(self, "conn_panel") and self.conn_panel._db_type:
                data["db_type"] = self.conn_panel._db_type
            if hasattr(self, "conn_panel") and getattr(self.conn_panel, "_color", None):
                data["connection_color"] = self.conn_panel._color
        if self._database_name:
            data["database_name"] = self._database_name
        sql_parameters = self.get_sql_parameters()
        if sql_parameters:
            data["sql_parameters"] = sql_parameters
        if not self._sql_parameters_enabled:
            data["sql_parameters_enabled"] = False
        return data

    @classmethod
    def from_dict(cls, data: dict, theme_manager=None) -> "CodeBlock":
        block = cls(theme_manager=theme_manager)
        block.set_language(data.get("language", "python"))
        block.set_code(data.get("code", ""))
        # Restore height if saved
        if "height" in data and data["height"]:
            block._set_editor_height(data["height"])
        # Restore block name
        if "block_name" in data and data["block_name"]:
            block.set_block_name(data["block_name"])
        if data.get("block_key"):
            block._block_key = str(data["block_key"])
        # Restore custom connection (with visual panel)
        if "connection_name" in data:
            db_type = data.get("db_type")
            color = data.get("connection_color")
            block.set_connection_name(data["connection_name"], db_type, color)
        # Restore custom database
        if "database_name" in data and data["database_name"]:
            block.set_database_name(data["database_name"])
        # Restore SQL custom parameters
        if "sql_parameters" in data:
            block.set_sql_parameters(data.get("sql_parameters") or [])
        if "sql_parameters_enabled" in data:
            block.set_sql_parameters_enabled(data.get("sql_parameters_enabled", True))
        # Restore active state
        if "is_active" in data:
            block.set_active(data["is_active"])
        return block

    # === Drag ===

    def _start_drag(self):
        self.drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"block:{id(self)}")
        drag.setMimeData(mime_data)

        pixmap = QPixmap(self.size())
        pixmap.fill(QColor(60, 60, 60, 200))
        painter = QPainter(pixmap)
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(10, 20, S.block.drag_label.format(lang=self.get_language().upper()))
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, 10))

        self.move_requested.emit(self, -1)
        drag.exec(Qt.DropAction.MoveAction)

        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)


    def start_download(self, file_index: int, label: str) -> None:
        from src.ui.components.download_progress_bar import DownloadProgressBar

        if file_index in self._download_bars:
            self._download_bars[file_index].title_label.setText(label)
        else:
            bar = DownloadProgressBar(file_index, label, self.download_progress_container)
            bar.cancel_clicked.connect(self._on_download_bar_cancel)
            bar.reveal_clicked.connect(self.reveal_file_requested.emit)
            self._download_bars[file_index] = bar
            self._download_progress_layout.addWidget(bar)
        self.download_progress_container.show()

    def update_download_progress(self, file_index: int, rows: int, bytes_written: int, rate_mbps: float) -> None:
        bar = self._download_bars.get(file_index)
        if bar is not None:
            bar.update_stats(rows, bytes_written, rate_mbps)

    def set_download_total(self, file_index: int, total: Optional[int]) -> None:
        bar = self._download_bars.get(file_index)
        if bar is not None:
            bar.set_total(total)

    def finish_download(self, file_index: int, file_path: str = "", total_rows: int = 0) -> None:
        bar = self._download_bars.get(file_index)
        if bar is not None and file_path:
            bar.finish(file_path, total_rows)

    def clear_downloads(self) -> None:
        for file_index in list(self._download_bars.keys()):
            bar = self._download_bars.pop(file_index, None)
            if bar is not None:
                self._download_progress_layout.removeWidget(bar)
                bar.deleteLater()
        self.download_progress_container.hide()

    def _on_download_bar_cancel(self, _file_index: int) -> None:
        self.cancel_download_requested.emit(self)

    # === Resize (editor_container only) ===

    def _resize_start(self, event):
        self._is_resizing = True
        self._resize_start_y = event.globalPosition().y()
        self._resize_start_height = self.editor_container.height()

    def _resize_move(self, event):
        if not self._is_resizing:
            return
        delta = event.globalPosition().y() - self._resize_start_y
        new_height = max(80, self._resize_start_height + delta)
        self._set_editor_height(int(new_height))

    def _resize_end(self, event):
        if self._is_resizing:
            self._is_resizing = False

    def _set_editor_height(self, height: int):
        """Set fixed height for editor container"""
        self.editor_container.setFixedHeight(height)
        # Internal editor auto-expands via layout
