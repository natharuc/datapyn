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
from src.design_system.icon_button import IconButton

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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("mdi.connection", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_panel.section_active)
        title.setStyleSheet(f"font-weight: 500; font-size: 11px; color: {colors.text_secondary};")
        header.addWidget(title)
        header.addStretch()
        self.btn_disconnect = IconButton(
            icon_name="mdi.power-plug-off",
            tooltip=S.connection_panel.btn_disconnect,
            size="compact",
            variant="danger",
            icon_color=colors.danger,
            parent=self,
        )
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        header.addWidget(self.btn_disconnect)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(10)
        self._db_icon_label = QLabel()
        self._db_icon_label.setFixedSize(28, 28)
        self._db_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._db_icon_label.hide()
        body.addWidget(self._db_icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.name_label = QLabel(S.connection_panel.label_none)
        self.name_label.setStyleSheet(
            f"font-size: 14px; font-weight: 500; color: {colors.text_primary};"
        )
        text.addWidget(self.name_label)

        self.host_label = QLabel("")
        self.host_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        self.host_label.hide()
        text.addWidget(self.host_label)

        self.database_label = QLabel("")
        self.database_label.setWordWrap(True)
        self.database_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        self.database_label.hide()
        text.addWidget(self.database_label)
        body.addLayout(text, 1)
        layout.addLayout(body)

        # Compatibility alias used by MainWindow._setup_connection_panel_compat.
        self.info_label = self.database_label

    def set_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Set connection"""
        self.name_label.setText(name)
        self.host_label.setText(host or "")
        self.host_label.setVisible(bool(host))
        self.database_label.setText(database or "")
        self.database_label.setVisible(bool(database))
        if db_type:
            icon = get_db_icon(db_type, size=28)
            self._db_icon_label.setPixmap(icon.pixmap(28, 28))
            self._db_icon_label.show()
        else:
            self._db_icon_label.clear()
            self._db_icon_label.hide()
        self.btn_disconnect.setEnabled(True)

    def set_disconnected(self):
        """Set as disconnected"""
        self.name_label.setText(S.connection_panel.label_none)
        self.host_label.setText("")
        self.host_label.hide()
        self.database_label.setText("")
        self.database_label.hide()
        self._db_icon_label.clear()
        self._db_icon_label.hide()
        self.btn_disconnect.setEnabled(False)


class ConnectionsList(QFrame):
    """Connections list grouped by folder."""

    connection_double_clicked = pyqtSignal(str, str)  # group, name
    new_tab_connection_requested = pyqtSignal(str, str)  # group, name
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str, str)  # group, name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("mdi.database-cog", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_panel.section_saved)
        title.setStyleSheet(f"font-weight: 500; font-size: 11px; color: {colors.text_secondary};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        from src.ui.components.saved_connections_list import SavedConnectionsListView

        self._saved_list = SavedConnectionsListView(
            self,
            show_search=True,
            drag_enabled=True,
            list_min_height=150,
        )
        self.tree_widget = self._saved_list.tree_widget
        self._saved_list.connection_activated.connect(self._on_connection_activated)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._saved_list, 1)

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

    def _on_connection_activated(self, group: str, name: str) -> None:
        from PyQt6.QtGui import QGuiApplication

        modifiers = QGuiApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.new_tab_connection_requested.emit(group, name)
        else:
            self.connection_double_clicked.emit(group, name)

    def _connection_at_pos(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return None, None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "connection":
            return data.get("group", ""), data.get("name", "")
        return None, None

    def _show_context_menu(self, pos):
        group, conn_name = self._connection_at_pos(pos)
        if not conn_name:
            return

        menu = QMenu(self)
        colors = get_colors()

        connect_action = QAction(qta.icon("mdi.lan-connect", color=colors.interactive_primary), f" {S.connection_panel.ctx_connect}", self)
        connect_action.triggered.connect(lambda: self.connection_double_clicked.emit(group, conn_name))
        menu.addAction(connect_action)

        new_tab_action = QAction(qta.icon("mdi.tab-plus", color=colors.interactive_primary), f" {S.connection_panel.ctx_connect_new_tab}", self)
        new_tab_action.triggered.connect(lambda: self.new_tab_connection_requested.emit(group, conn_name))
        menu.addAction(new_tab_action)

        menu.addSeparator()

        edit_action = QAction(qta.icon("mdi.pencil", color=colors.info), f" {S.connection_panel.ctx_edit}", self)
        edit_action.triggered.connect(lambda: self.edit_connection_clicked.emit(group, conn_name))
        menu.addAction(edit_action)

        menu.exec(self.tree_widget.mapToGlobal(pos))

    def refresh(self, connections: list):
        """Refresh connections list.

        Args:
            connections: List of tuples (group, name, config)
        """
        self._saved_list.refresh(connections)

    def highlight_connection(self, group: str, name: str) -> None:
        """Select and expand the tree item for (group, name)."""
        tree = self.tree_widget
        target_group = group or ""
        for i in range(tree.topLevelItemCount()):
            group_item = tree.topLevelItem(i)
            gdata = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not gdata or gdata.get("type") != "group":
                continue
            if (gdata.get("group") or "") != target_group:
                continue
            group_item.setExpanded(True)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                cdata = child.data(0, Qt.ItemDataRole.UserRole)
                if (
                    cdata
                    and cdata.get("type") == "connection"
                    and cdata.get("name") == name
                ):
                    tree.setCurrentItem(child)
                    return


class ConnectionPanel(QWidget):
    """Connection panel (dock widget)"""

    # Signals
    connection_requested = pyqtSignal(str, str)  # group, name
    new_tab_connection_requested = pyqtSignal(str, str)  # group, name
    disconnect_clicked = pyqtSignal()
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str, str)  # group, name

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
        """Refresh connections list.

        Args:
            connections: List of tuples (group, name, config) or None to use connection_manager
        """
        if connections is None and self.connection_manager:
            connections = self.connection_manager.iter_saved_connections()

        if connections is not None:
            self.connections_list.refresh(connections)
