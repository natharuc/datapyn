"""
CodeBlock - An individual code block with language selector

Similar to a Jupyter notebook cell.
Uses configurable editor via editor_config (QScintilla or Monaco).
"""

import time
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
from PyQt6.QtCore import pyqtSignal, Qt, QMimeData, QPoint
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor
import qtawesome as qta

from src.core.theme_manager import ThemeManager
from src.editors.editor_config import get_code_editor_class
from src.language import S


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
        self._setup_ui()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setStyleSheet("""
            BlockConnectionPanel {
                background: #2d2d2d;
                border: 1px solid #3e3e42;
                border-radius: 3px;
            }
            BlockConnectionPanel:hover {
                border-color: #555;
            }
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
        self.name_label.setStyleSheet("color: #aaa; font-size: 11px;")
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
            self.name_label.setStyleSheet("color: #fff; font-size: 11px; font-weight: 500;")

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
            self.name_label.setStyleSheet("color: #aaa; font-size: 11px;")
            self.icon_label.setPixmap(qta.icon("mdi.link-variant", color="#888").pixmap(16, 16))

    def get_connection_name(self):
        """Return current connection name (None = tab default)"""
        return self._connection_name

    def mousePressEvent(self, event):
        """Click on panel"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.connection_clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        """Accept connection drag"""
        if event.mimeData().hasFormat("application/x-connection-name"):
            event.acceptProposedAction()
            self.setStyleSheet("""
                BlockConnectionPanel {
                    background: #353535;
                    border: 1px solid #64b5f6;
                    border-radius: 3px;
                }
            """)

    def dragLeaveEvent(self, event):
        """Remove highlight on exit"""
        self.setStyleSheet("""
            BlockConnectionPanel {
                background: #2d2d2d;
                border: 1px solid #3e3e42;
                border-radius: 3px;
            }
            BlockConnectionPanel:hover {
                border-color: #555;
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
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setStyleSheet("""
            BlockDatabasePanel {
                background: #2d2d2d;
                border: 1px solid #3e3e42;
                border-radius: 3px;
            }
            BlockDatabasePanel:hover {
                border-color: #555;
            }
        """)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setScaledContents(True)
        self.icon_label.setPixmap(qta.icon("mdi.database-outline", color="#888").pixmap(16, 16))
        layout.addWidget(self.icon_label)

        # Database name
        self.name_label = QLabel(S.block.db_default)
        self.name_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self.name_label.setMinimumWidth(40)
        layout.addWidget(self.name_label, 1)

    def set_database(self, database_name: str = None):
        """Set the database to display"""
        self._database_name = database_name

        if database_name:
            self.name_label.setText(database_name)
            self.name_label.setStyleSheet("color: #fff; font-size: 11px; font-weight: 500;")
            self.icon_label.setPixmap(qta.icon("mdi.database", color="#569cd6").pixmap(16, 16))
        else:
            self.name_label.setText(S.block.db_default)
            self.name_label.setStyleSheet("color: #aaa; font-size: 11px;")
            self.icon_label.setPixmap(qta.icon("mdi.database-outline", color="#888").pixmap(16, 16))

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
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d30;
                border: 1px solid #3e3e42;
                padding: 4px 0;
            }
            QMenu::item {
                padding: 4px 24px 4px 8px;
                color: #cccccc;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #094771;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #3e3e42;
                margin: 4px 8px;
            }
        """)

        # Option to reset to connection default
        default_action = menu.addAction(
            qta.icon("mdi.database-outline", color="#888"),
            S.block.db_default,
        )
        default_action.setData(None)
        menu.addSeparator()

        # Add each database
        for db in sorted(self._available_databases):
            icon_name = "mdi.database"
            icon_color = "#569cd6"
            if db == self._database_name:
                icon_name = "mdi.database-check"
                icon_color = "#4ec9b0"
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
        if event.mimeData().hasFormat("application/x-database-name"):
            event.acceptProposedAction()
            self.setStyleSheet("""
                BlockDatabasePanel {
                    background: #353535;
                    border: 1px solid #569cd6;
                    border-radius: 3px;
                }
            """)

    def dragLeaveEvent(self, event):
        """Remove highlight on exit"""
        self.setStyleSheet("""
            BlockDatabasePanel {
                background: #2d2d2d;
                border: 1px solid #3e3e42;
                border-radius: 3px;
            }
            BlockDatabasePanel:hover {
                border-color: #555;
            }
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

    execute_requested = pyqtSignal(object)  # self
    remove_requested = pyqtSignal(object)  # self
    move_requested = pyqtSignal(object, int)  # self, new_index (-1 = drag started)
    language_changed = pyqtSignal(object, str)  # self, new_language
    focus_changed = pyqtSignal(object, bool)  # self, has_focus
    cancel_requested = pyqtSignal(object)  # self - to cancel execution
    select_connection_requested = pyqtSignal(object)  # self - to open connection dialog
    connection_name_changed = pyqtSignal(object, str)  # self, connection_name - when block connection changes
    database_changed = pyqtSignal(object, str)  # self, database_name - when block database changes

    LANGUAGE_COLORS = {"python": "#3572A5", "sql": "#E38C00", "cross": "#6B4C9A"}

    def __init__(self, theme_manager: ThemeManager = None, parent=None, default_language="sql"):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._is_focused = False
        self._is_running = False
        self._is_waiting = False
        self._is_resizing = False
        self._resize_start_y = 0
        self._resize_start_height = 0
        self._execution_start_time = 0
        self._last_execution_time = None
        self._default_language = default_language
        self._connection_name = None  # None = use session connection
        self._database_name = None  # None = use connection default database
        self._block_name = ""  # Block name (namespace prefix)

        self._setup_ui()
        self._connect_signals()
        # Set initial language explicitly (setCurrentIndex doesn't fire signal during init)
        self.editor.set_language(self._default_language)
        self._update_style()
        self._update_connection_panel_visibility()  # Update connection panel visibility (after language)

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setLineWidth(2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Default height for all header controls
        CTRL_H = 24

        # Shared base style for header inputs/combos
        _input_base_style = f"""
            background: #2d2d2d;
            color: #ccc;
            border: 1px solid #3e3e42;
            border-radius: 3px;
            padding: 2px 6px;
            font-size: 11px;
            min-height: {CTRL_H - 4}px;
            max-height: {CTRL_H - 4}px;
        """

        # === Control bar ===
        self.control_bar = QWidget()
        self.control_bar.setFixedHeight(34)
        self.control_bar.setStyleSheet("""
            QWidget#controlBar {
                background: #252526;
                border-bottom: 1px solid #3e3e42;
            }
        """)
        self.control_bar.setObjectName("controlBar")
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setContentsMargins(6, 4, 6, 4)
        control_layout.setSpacing(6)

        # Drag handle
        self.drag_handle = QPushButton()
        self.drag_handle.setFixedSize(CTRL_H, CTRL_H)
        self.drag_handle.setToolTip(S.block.tooltip_drag)
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_handle.setIcon(qta.icon("mdi.drag-horizontal-variant", color="#666"))
        self.drag_handle.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #37373d;
            }
        """)
        self.drag_handle.pressed.connect(self._start_drag)
        control_layout.addWidget(self.drag_handle)

        # Language indicator (colored vertical bar)
        self.lang_indicator = QFrame()
        self.lang_indicator.setFixedWidth(3)
        self.lang_indicator.setFixedHeight(CTRL_H - 4)
        self.lang_indicator.setStyleSheet("border-radius: 1px;")
        control_layout.addWidget(self.lang_indicator)

        # Language selector
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Python", "python")
        self.lang_combo.addItem("SQL", "sql")
        self.lang_combo.addItem("Cross-Syntax", "cross")
        if self._default_language == "sql":
            self.lang_combo.setCurrentIndex(1)
        elif self._default_language == "cross":
            self.lang_combo.setCurrentIndex(2)
        else:
            self.lang_combo.setCurrentIndex(0)
        self.lang_combo.setFixedWidth(110)
        self.lang_combo.setFixedHeight(CTRL_H)
        self.lang_combo.setStyleSheet(f"""
            QComboBox {{
                {_input_base_style}
            }}
            QComboBox:hover {{
                border-color: #555;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 18px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #888;
                margin-right: 4px;
            }}
            QComboBox QAbstractItemView {{
                background: #2d2d2d;
                color: #ccc;
                border: 1px solid #555;
                selection-background-color: #094771;
            }}
        """)
        control_layout.addWidget(self.lang_combo)

        # Block name field
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(S.block.placeholder_name)
        self.name_input.setFixedWidth(120)
        self.name_input.setFixedHeight(CTRL_H)
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                {_input_base_style}
            }}
            QLineEdit:focus {{
                border-color: #007ACC;
                color: #fff;
            }}
            QLineEdit::placeholder {{
                color: #666;
            }}
        """)
        control_layout.addWidget(self.name_input)

        # Connection panel (only visible for SQL)
        self.conn_panel = BlockConnectionPanel()
        self.conn_panel.setFixedHeight(CTRL_H)
        self.conn_panel.setMinimumWidth(100)
        self.conn_panel.setMaximumWidth(220)
        control_layout.addWidget(self.conn_panel)

        # Database panel (only visible for SQL, next to connection panel)
        self.db_panel = BlockDatabasePanel()
        self.db_panel.setFixedHeight(CTRL_H)
        self.db_panel.setMinimumWidth(80)
        self.db_panel.setMaximumWidth(180)
        control_layout.addWidget(self.db_panel)

        # Status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                padding: 2px 6px;
                background: transparent;
            }
        """)
        control_layout.addWidget(self.status_label)

        # Cancel button (only visible during execution)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(qta.icon("mdi.stop-circle-outline", color="#e74c3c"))
        self.cancel_btn.setText(S.block.btn_cancel)
        self.cancel_btn.setFixedHeight(CTRL_H)
        self.cancel_btn.setToolTip(S.block.tooltip_cancel)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(231, 76, 60, 0.15);
            }
        """)
        self.cancel_btn.hide()
        control_layout.addWidget(self.cancel_btn)

        control_layout.addStretch()

        # Run button (with icon)
        self.run_btn = QPushButton()
        self.run_btn.setFixedSize(CTRL_H, CTRL_H)
        self.run_btn.setToolTip(S.block.tooltip_run)
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_icon_play = True  # Track icon state
        control_layout.addWidget(self.run_btn)

        # Remove button (discrete X icon)
        self.remove_btn = QPushButton()
        self.remove_btn.setIcon(qta.icon("mdi.close", color="#666"))
        self.remove_btn.setFixedSize(CTRL_H, CTRL_H)
        self.remove_btn.setToolTip(S.block.tooltip_remove)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: rgba(231, 76, 60, 0.2);
            }
        """)
        control_layout.addWidget(self.remove_btn)

        layout.addWidget(self.control_bar)

        # === Editor Container (resizable) ===
        self.editor_container = QWidget()
        self.editor_container.setMinimumHeight(80)
        self.editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        # Code Editor (configurable via editor_config - implements ICodeEditor)
        EditorClass = get_code_editor_class()
        self.editor = EditorClass(theme_manager=self.theme_manager)

        # Compatibility: get_widget() for QScintilla, direct for Monaco
        editor_widget = self.editor.get_widget() if hasattr(self.editor, "get_widget") else self.editor
        editor_layout.addWidget(editor_widget)

        layout.addWidget(self.editor_container, 1)  # stretch=1 to expand

        # === Resize handle ===
        self.resize_handle = QFrame()
        self.resize_handle.setFixedHeight(6)
        self.resize_handle.setCursor(Qt.CursorShape.SizeVerCursor)
        self.resize_handle.setStyleSheet("""
            QFrame { background: transparent; }
            QFrame:hover { background: #555; }
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
        self.run_btn.clicked.connect(lambda: self.execute_requested.emit(self))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self))
        self.editor.execute_requested.connect(lambda: self.execute_requested.emit(self))
        self.editor.SCN_FOCUSIN.connect(self._on_focus_in)
        self.editor.SCN_FOCUSOUT.connect(self._on_focus_out)

    def _on_focus_in(self):
        self._is_focused = True
        self._update_style()
        self.focus_changed.emit(self, True)

    def _on_focus_out(self):
        self._is_focused = False
        self._update_style()
        self.focus_changed.emit(self, False)

    def _on_language_changed(self):
        lang = self.lang_combo.currentData()
        self.editor.set_language(lang)
        self._update_connection_panel_visibility()
        self._update_style()
        self.language_changed.emit(self, lang)

    def _on_connection_panel_clicked(self):
        """Connection panel was clicked - emit signal to open dialog"""
        self.select_connection_requested.emit(self)

    def _on_connection_dropped(self, connection_name: str, db_type: str, color: str):
        """Connection was dragged to panel"""
        self._connection_name = connection_name
        self.conn_panel.set_connection(connection_name, db_type or None, color or None)
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

    def _update_style(self):
        lang = self.get_language()
        color = self.LANGUAGE_COLORS.get(lang, "#888")

        self.lang_indicator.setStyleSheet(f"background-color: {color}; border-radius: 1px;")

        # Botao executar com icone (sem texto unicode)
        self.run_btn.setIcon(qta.icon("mdi.play", color=color))
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {color};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {color};
            }}
        """)

        if self._is_focused:
            self.setStyleSheet(f"CodeBlock {{ border: 2px solid {color}; border-radius: 4px; }}")
        else:
            self.setStyleSheet("CodeBlock { border: 1px solid #3e3e42; border-radius: 4px; }")

    # === Public API ===

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

    def get_selected_text(self) -> str:
        return self.editor.get_selected_text()

    def has_selection(self) -> bool:
        return self.editor.has_selection()

    def get_block_name(self) -> str:
        """Return block name (used as namespace prefix)"""
        return self.name_input.text().strip()

    def set_block_name(self, name: str):
        """Set block name"""
        self._block_name = name
        self.name_input.setText(name)

    def get_connection_name(self) -> str:
        """Return custom connection name or None (uses tab default)"""
        return self._connection_name

    def set_connection_name(self, conn_name: str, db_type: str = None, color: str = None):
        """Set custom connection for this block"""
        self._connection_name = conn_name
        self.conn_panel.set_connection(conn_name, db_type, color)
        self.connection_name_changed.emit(self, conn_name)

    def get_database_name(self) -> str:
        """Return custom database name or None (uses connection default)"""
        return self._database_name

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
                    border-radius: 3px;
                }
            """)
            self.cancel_btn.hide()
        else:
            if not self._is_running:
                self._update_style()

    def set_running(self, running: bool):
        self._is_running = running
        self._is_waiting = False
        if running:
            self._execution_start_time = time.time()
            self.run_btn.setIcon(qta.icon("mdi.stop", color="#f39c12"))
            self.status_label.setText(S.block.status_running)
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f39c12;
                    font-size: 11px;
                    padding: 2px 6px;
                    background: rgba(243, 156, 18, 0.1);
                    border-radius: 3px;
                }
            """)
            self.cancel_btn.show()
        else:
            self._update_style()  # Restore play icon with language color
            self.cancel_btn.hide()
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
                        border-radius: 3px;
                    }
                """)
            else:
                self.status_label.setText("")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #888;
                        font-size: 11px;
                        padding: 2px 6px;
                        background: transparent;
                    }
                """)

    def set_cancelled(self):
        """Set cancelled state"""
        self._is_running = False
        self._is_waiting = False
        self._update_style()
        self.cancel_btn.hide()
        self.status_label.setText(S.block.status_cancelled)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(231, 76, 60, 0.1);
                border-radius: 3px;
            }
        """)
        self._execution_start_time = 0

    def set_error(self):
        """Set error state"""
        self._is_running = False
        self._is_waiting = False
        self._update_style()
        self.cancel_btn.hide()
        self.status_label.setText(S.block.status_error)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 2px 6px;
                background: rgba(231, 76, 60, 0.15);
                border-radius: 3px;
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
        # Restore custom connection (with visual panel)
        if "connection_name" in data:
            db_type = data.get("db_type")
            color = data.get("connection_color")
            block.set_connection_name(data["connection_name"], db_type, color)
        # Restore custom database
        if "database_name" in data and data["database_name"]:
            block.set_database_name(data["database_name"])
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
