"""
Painel de conexoes - Material Design Flat
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMenu,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QByteArray, QMimeData, QRectF
from PyQt6.QtGui import QAction, QFont, QIcon, QPixmap, QPainter, QDrag
from PyQt6.QtSvg import QSvgRenderer
import qtawesome as qta
import os
import re
import logging

from src.language import S
from src.design_system.tokens import get_colors

logger = logging.getLogger(__name__)


# Custom icons folder
ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "assets", "icons", "db")

# Icon and color mapping by database type (fallback to qtawesome)
DB_TYPE_ICONS = {
    "sqlserver": {"icon": "mdi.database", "color": "#CC2927"},
    "mssql": {"icon": "mdi.database", "color": "#CC2927"},
    "mysql": {"icon": "mdi.database-outline", "color": "#00758F"},
    "mariadb": {"icon": "mdi.database-marker", "color": "#C0765A"},
    "postgresql": {"icon": "mdi.database-cog", "color": "#336791"},
    "postgres": {"icon": "mdi.database-cog", "color": "#336791"},
    "sqlite": {"icon": "mdi.file-document-outline", "color": "#003B57"},
    "databricks": {"icon": "mdi.cloud-braces", "color": "#FF3621"},
}

_CONNECTION_ROW_HEIGHT = 52
_CONNECTION_ICON_SIZE = 28


def _normalize_db_type(db_type: str) -> str:
    """Normalize database type name"""
    db_type_lower = (db_type or "").lower().replace(" ", "").replace("_", "")

    if "sql" in db_type_lower and "server" in db_type_lower:
        return "sqlserver"
    elif "maria" in db_type_lower:
        return "mariadb"
    elif "postgre" in db_type_lower:
        return "postgresql"
    elif "mysql" in db_type_lower:
        return "mysql"
    elif "sqlite" in db_type_lower:
        return "sqlite"
    elif "databricks" in db_type_lower:
        return "databricks"

    return db_type_lower


def _load_svg_with_color(svg_path: str, color: str, size: int = 32) -> QIcon | None:
    """Load SVG and apply custom color."""
    try:
        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        svg_content = re.sub(r"fill\s*:\s*#[0-9a-fA-F]{3,6}", f"fill:{color}", svg_content)
        svg_content = re.sub(r"stroke\s*:\s*#[0-9a-fA-F]{3,6}", f"stroke:{color}", svg_content)
        svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)
        svg_content = re.sub(r'stroke="[^"]*"', f'stroke="{color}"', svg_content)

        if "fill=" not in svg_content and "fill:" not in svg_content:
            svg_content = re.sub(
                r"<(path|circle|rect|polygon)", f'<\\1 fill="{color}"', svg_content
            )

        renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
        if not renderer.isValid():
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        view_box = renderer.viewBoxF()
        if view_box.width() > 0 and view_box.height() > 0:
            inset = size * 0.1
            target = size - (2 * inset)
            scale = min(target / view_box.width(), target / view_box.height())
            draw_w = view_box.width() * scale
            draw_h = view_box.height() * scale
            x = (size - draw_w) / 2
            y = (size - draw_h) / 2
            renderer.render(painter, QRectF(x, y, draw_w, draw_h))
        else:
            renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception as e:
        logger.warning(f"Error loading SVG {svg_path}: {e}")
        return None


def get_db_icon(db_type: str, custom_color: str = None, size: int = 32) -> QIcon:
    """Return icon for database type.

    Priority:
    1. Custom SVG in assets/icons/db/{db_type}.svg
    2. Default qtawesome icon
    """
    db_type_normalized = _normalize_db_type(db_type)
    config = DB_TYPE_ICONS.get(db_type_normalized, {"icon": "mdi.database", "color": "#64b5f6"})
    color = custom_color if custom_color else config["color"]

    svg_path = os.path.join(ICONS_DIR, f"{db_type_normalized}.svg")
    if os.path.exists(svg_path):
        icon = _load_svg_with_color(svg_path, color, size=size)
        if icon is not None:
            return icon

    return qta.icon(config["icon"], color=color)


class ConnectionItemWidget(QWidget):
    """Custom widget for connection item with name and group in separate lines"""

    def __init__(self, name: str, group: str = "", icon: QIcon = None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_CONNECTION_ROW_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        if icon:
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(_CONNECTION_ICON_SIZE, _CONNECTION_ICON_SIZE))
            icon_label.setFixedSize(_CONNECTION_ICON_SIZE, _CONNECTION_ICON_SIZE)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text_container = QWidget()
        text_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        colors = get_colors()
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {colors.text_primary};"
        )
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        text_layout.addStretch(1)
        text_layout.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignLeft)
        if group:
            self.group_label = QLabel(group)
            self.group_label.setStyleSheet(
                f"font-size: 10px; color: {colors.text_secondary};"
            )
            self.group_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
            )
            text_layout.addWidget(self.group_label, 0, Qt.AlignmentFlag.AlignLeft)
        text_layout.addStretch(1)

        layout.addWidget(text_container, 1, Qt.AlignmentFlag.AlignVCenter)


class DraggableConnectionList(QListWidget):
    """QListWidget that allows dragging connections"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supportedActions):
        """Start connection drag"""
        item = self.currentItem()
        if not item:
            return

        # Get connection data
        conn_name = None
        db_type = "mysql"

        if isinstance(item, ConnectionItem):
            conn_name = item.connection_name
            db_type = item.config.get("db_type", "mysql")
        else:
            conn_name = item.data(Qt.ItemDataRole.UserRole)

        if not conn_name:
            return

        # Create MimeData with connection info
        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", conn_name.encode("utf-8"))
        mime_data.setData("application/x-db-type", db_type.encode("utf-8"))

        # Include connection color if available
        conn_color = ""
        if isinstance(item, ConnectionItem):
            conn_color = item.config.get("color", "") or ""
        if conn_color:
            mime_data.setData("application/x-connection-color", conn_color.encode("utf-8"))

        # Create drag
        drag = QDrag(self)
        drag.setMimeData(mime_data)

        # Drag icon
        icon = get_db_icon(db_type)
        drag.setPixmap(icon.pixmap(32, 32))

        # Execute drag
        drag.exec(Qt.DropAction.CopyAction)


class ConnectionItem(QListWidgetItem):
    """Connection item with database-specific icon"""

    def __init__(self, name: str, config: dict):
        super().__init__()
        self.connection_name = name
        self.config = config

        db_type = config.get("db_type", "SQL Server")
        host = config.get("host", "")
        database = config.get("database", "")
        group = config.get("group", "")
        custom_color = config.get("color", "")

        # Database-specific icon (custom SVG or qtawesome)
        self.icon = get_db_icon(
            db_type,
            custom_color if custom_color else None,
            size=_CONNECTION_ICON_SIZE,
        )
        self.group = group

        # Complete tooltip
        self.setToolTip(f"{db_type}\n{host}\n{database}")

        self.setSizeHint(QSize(250, _CONNECTION_ROW_HEIGHT))


class ActiveConnectionWidget(QFrame):
    """Active connection widget - flat design"""

    disconnect_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()
        self.set_disconnected()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header with icon
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("mdi.connection", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_panel.section_active)
        title.setStyleSheet(f"font-weight: 500; font-size: 11px; color: {colors.text_secondary};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Name
        self.name_label = QLabel(S.connection_panel.label_none)
        self.name_label.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {colors.text_primary};")
        layout.addWidget(self.name_label)

        # Info
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        layout.addWidget(self.info_label)

        # Button
        self.btn_disconnect = QPushButton(f" {S.connection_panel.btn_disconnect}")
        self.btn_disconnect.setIcon(qta.icon("mdi.link-off", color="white"))
        self.btn_disconnect.setObjectName("danger")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        layout.addWidget(self.btn_disconnect)

    def set_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Set connection"""
        self.name_label.setText(name)

        info_parts = []
        if host:
            info_parts.append(host)
        if database:
            info_parts.append(database)
        if db_type:
            info_parts.append(f"({db_type})")

        self.info_label.setText(" / ".join(info_parts))
        self.btn_disconnect.setEnabled(True)

    def set_disconnected(self):
        """Set as disconnected"""
        self.name_label.setText(S.connection_panel.label_none)
        self.info_label.setText("")
        self.btn_disconnect.setEnabled(False)


class ConnectionsList(QFrame):
    """Connections list - flat design"""

    connection_double_clicked = pyqtSignal(str)
    new_tab_connection_requested = pyqtSignal(str)  # Always connect in new tab
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str)  # Signal to edit connection directly

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)  # Back to normal margin
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("mdi.database-cog", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_panel.section_saved)
        title.setStyleSheet(f"font-weight: 500; font-size: 11px; color: {colors.text_secondary};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # List (with drag enabled)
        self.list_widget = DraggableConnectionList()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.setIconSize(QSize(_CONNECTION_ICON_SIZE, _CONNECTION_ICON_SIZE))
        self.list_widget.setSpacing(4)  # Spacing between items
        self.list_widget.setWordWrap(True)  # Allow line break
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)  # Don't truncate with "..."
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {colors.bg_primary};
                border: none;
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 0px 6px;
                border-radius: 6px;
                margin: 2px 0px;
            }}
            QListWidget::item:selected {{
                background: rgba(59, 130, 246, 0.25);
            }}
            QListWidget::item:hover {{
                background: {colors.bg_elevated};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::handle:vertical:pressed {{
                background: rgba(128, 128, 128, 0.7);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Context menu
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

        # Buttons
        btn_layout = QHBoxLayout()

        self.btn_new = QPushButton(f" {S.connection_panel.btn_new}")
        self.btn_new.setIcon(qta.icon("mdi.plus-circle", color="white"))
        self.btn_new.setObjectName("primary")
        self.btn_new.clicked.connect(self.new_connection_clicked.emit)
        btn_layout.addWidget(self.btn_new)

        self.btn_manage = QPushButton(f" {S.connection_panel.btn_manage}")
        self.btn_manage.setIcon(qta.icon("mdi.cog", color="white"))
        self.btn_manage.clicked.connect(self.manage_connections_clicked.emit)
        btn_layout.addWidget(self.btn_manage)

        layout.addLayout(btn_layout)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """Emit signal when item is double-clicked"""
        from PyQt6.QtGui import QGuiApplication

        conn_name = None
        if isinstance(item, ConnectionItem):
            conn_name = item.connection_name
        else:
            conn_name = item.data(Qt.ItemDataRole.UserRole)

        if conn_name:
            # Check if CTRL is pressed
            modifiers = QGuiApplication.keyboardModifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                # CTRL pressed - always new tab
                self.new_tab_connection_requested.emit(conn_name)
            else:
                # Normal behavior
                self.connection_double_clicked.emit(conn_name)

    def _show_context_menu(self, pos):
        """Show context menu on connection"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if not conn_name:
            return

        menu = QMenu(self)
        colors = get_colors()

        connect_action = QAction(qta.icon("mdi.lan-connect", color=colors.interactive_primary), f" {S.connection_panel.ctx_connect}", self)
        connect_action.triggered.connect(lambda: self.connection_double_clicked.emit(conn_name))
        menu.addAction(connect_action)

        new_tab_action = QAction(qta.icon("mdi.tab-plus", color=colors.interactive_primary), f" {S.connection_panel.ctx_connect_new_tab}", self)
        new_tab_action.triggered.connect(lambda: self.new_tab_connection_requested.emit(conn_name))
        menu.addAction(new_tab_action)

        menu.addSeparator()

        edit_action = QAction(qta.icon("mdi.pencil", color=colors.info), f" {S.connection_panel.ctx_edit}", self)
        edit_action.triggered.connect(lambda: self._edit_connection(conn_name))
        menu.addAction(edit_action)

        menu.exec(self.list_widget.mapToGlobal(pos))

    def _edit_connection(self, conn_name: str):
        """Emit signal to edit connection directly"""
        self.edit_connection_clicked.emit(conn_name)

    def refresh(self, connections: list):
        """Refresh connections list

        Args:
            connections: List of tuples (name, config)
        """
        self.list_widget.clear()

        for name, config in connections:
            item = ConnectionItem(name, config)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)

            # Custom widget with name and group separated
            widget = ConnectionItemWidget(name, item.group, item.icon)
            self.list_widget.setItemWidget(item, widget)


class ConnectionPanel(QWidget):
    """Connection panel (dock widget)"""

    # Signals
    connection_requested = pyqtSignal(str)  # connection_name
    new_tab_connection_requested = pyqtSignal(str)  # connection_name for new tab
    disconnect_clicked = pyqtSignal()
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str)  # connection_name to edit

    def __init__(self, connection_manager=None, theme_manager=None, parent=None):
        super().__init__(parent)

        self.connection_manager = connection_manager
        self.theme_manager = theme_manager

        self._setup_ui()
        self._connect_signals()

        if self.connection_manager:
            self.refresh_connections()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)  # Overall padding of 10px on all sides

        self.active_widget = ActiveConnectionWidget()
        self.active_widget.setMaximumHeight(150)  # Fix active connection height
        layout.addWidget(self.active_widget)

        self.connections_list = ConnectionsList()
        # Make list occupy all remaining space
        layout.addWidget(self.connections_list, 1)  # stretch=1

        # Remove addStretch() to let connections_list occupy everything

    def _connect_signals(self):
        """Connect internal signals to external ones"""
        self.active_widget.disconnect_clicked.connect(self.disconnect_clicked.emit)
        self.connections_list.connection_double_clicked.connect(self.connection_requested.emit)
        self.connections_list.new_tab_connection_requested.connect(self.new_tab_connection_requested.emit)
        self.connections_list.new_connection_clicked.connect(self.new_connection_clicked.emit)
        self.connections_list.manage_connections_clicked.connect(self.manage_connections_clicked.emit)
        self.connections_list.edit_connection_clicked.connect(self.edit_connection_clicked.emit)

    def set_active_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Set active connection"""
        self.active_widget.set_connection(name, host, database, db_type)

    def set_disconnected(self):
        """Set as disconnected"""
        self.active_widget.set_disconnected()

    def refresh_connections(self, connections: list = None):
        """Refresh connections list

        Args:
            connections: List of tuples (name, config) or None to use connection_manager
        """
        if connections is None and self.connection_manager:
            # Fetch from connection manager
            connections = []
            for conn_name in self.connection_manager.get_saved_connections():
                config = self.connection_manager.get_connection_config(conn_name)
                if config:
                    connections.append((conn_name, config))

        if connections:
            self.connections_list.refresh(connections)
