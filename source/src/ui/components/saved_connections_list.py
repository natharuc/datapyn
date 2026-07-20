"""
Reusable saved-connections tree with optional search filter.

Used by the connections sidebar panel and the connection picker dialog.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QSettings
from PyQt6.QtGui import QDrag, QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QSizePolicy,
)

from src.design_system.tokens import get_colors, get_tree_stylesheet, SPACING
from src.language import S

MIME_CONNECTION_NAME = "application/x-connection-name"
MIME_CONNECTION_GROUP = "application/x-connection-group"
MIME_DB_TYPE = "application/x-db-type"
MIME_CONNECTION_COLOR = "application/x-connection-color"

ConnectionTuple = Tuple[str, str, dict]  # group, name, config


def build_connection_search_text(group: str, name: str, config: dict) -> str:
    """Lowercase blob used to match connection picker / sidebar search."""
    if not config:
        return (name or "").lower()

    parts: list[str] = [
        name or "",
        group or "",
        str(config.get("group", "") or ""),
        str(config.get("host", "") or ""),
        str(config.get("database", "") or ""),
        str(config.get("db_type", "") or ""),
        str(config.get("username", "") or ""),
        str(config.get("port", "") or ""),
        str(config.get("http_path", "") or ""),
        str(config.get("color", "") or ""),
    ]
    if config.get("use_windows_auth"):
        parts.append("windows auth")
    if config.get("trust_server_certificate"):
        parts.append("trust server certificate")
    sql_mode = config.get("sqlserver_auth_mode", "")
    if sql_mode:
        parts.append(str(sql_mode))

    return " ".join(p.strip() for p in parts if p and str(p).strip()).lower()


def _ungrouped_label() -> str:
    return getattr(S.connection_panel, "ungrouped_label", "(Ungrouped)")


def _connection_row_classes():
    from src.ui.components.connection_panel import (
        ConnectionItemWidget,
        get_db_icon,
        _CONNECTION_ICON_SIZE,
        _CONNECTION_ROW_HEIGHT,
    )

    return ConnectionItemWidget, get_db_icon, _CONNECTION_ICON_SIZE, _CONNECTION_ROW_HEIGHT


class DraggableConnectionTree(QTreeWidget):
    """QTreeWidget that allows dragging connection leaves."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(10)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "connection":
            return

        group = data.get("group", "")
        conn_name = data.get("name", "")
        config = data.get("config", {}) or {}
        db_type = config.get("db_type", "mysql")

        from PyQt6.QtCore import QMimeData

        mime_data = QMimeData()
        mime_data.setData(MIME_CONNECTION_NAME, conn_name.encode("utf-8"))
        mime_data.setData(MIME_CONNECTION_GROUP, group.encode("utf-8"))
        mime_data.setData(MIME_DB_TYPE, str(db_type).encode("utf-8"))
        conn_color = config.get("color", "") or ""
        if conn_color:
            mime_data.setData(MIME_CONNECTION_COLOR, conn_color.encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        _, get_db_icon, _, _ = _connection_row_classes()
        icon = get_db_icon(db_type, conn_color or None, size=32)
        drag.setPixmap(icon.pixmap(32, 32))
        drag.exec(Qt.DropAction.CopyAction)


class SavedConnectionsListView(QWidget):
    """Scrollable tree of saved connections grouped by folder with optional search."""

    connection_activated = pyqtSignal(str, str)  # group, name

    def __init__(
        self,
        parent=None,
        *,
        show_search: bool = True,
        drag_enabled: bool = True,
        list_min_height: int = 150,
        bordered: bool = False,
    ):
        super().__init__(parent)
        self._show_search = show_search
        self._drag_enabled = drag_enabled
        self._list_min_height = list_min_height
        self._bordered = bordered
        self._all_connections: List[ConnectionTuple] = []
        self._search_edit: Optional[QLineEdit] = None
        self._settings = QSettings("DataPyn", "DataPyn")
        self._setup_ui()

    def _setup_ui(self) -> None:
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if self._show_search:
            self._search_edit = QLineEdit()
            self._search_edit.setClearButtonEnabled(True)
            placeholder = getattr(S.connection_panel, "search_placeholder", "Search connections…")
            self._search_edit.setPlaceholderText(placeholder)
            self._search_edit.setStyleSheet(
                f"""
                QLineEdit {{
                    background: {colors.bg_primary};
                    border: 1px solid {colors.border_muted};
                    border-radius: 8px;
                    padding: 8px 10px;
                    color: {colors.text_primary};
                    font-size: 12px;
                }}
                QLineEdit:focus {{
                    border-color: {colors.interactive_primary};
                }}
                """
            )
            self._search_edit.textChanged.connect(self._apply_filter)
            layout.addWidget(self._search_edit)

        self.tree_widget = DraggableConnectionTree()
        self.tree_widget.setDragEnabled(self._drag_enabled)
        self.tree_widget.setMinimumHeight(self._list_min_height)
        self.tree_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.tree_widget.setStyleSheet(self._tree_stylesheet())
        self.tree_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree_widget, 1)

    def _tree_stylesheet(self) -> str:
        colors = get_colors()
        stylesheet = get_tree_stylesheet() + f"""
            QTreeWidget {{
                padding: {SPACING.space_2}px 0px {SPACING.space_1}px 0px;
            }}
            QTreeWidget::item {{
                padding: {SPACING.space_1}px {SPACING.space_2}px {SPACING.space_1}px 0px;
            }}
        """
        if self._bordered:
            stylesheet += f"""
            QTreeWidget {{
                border: 1px solid {colors.border_muted};
                border-radius: 8px;
            }}
            """
        return stylesheet

    def refresh(self, connections: List[ConnectionTuple]) -> None:
        """Replace the full connection set and re-apply the current search filter."""
        self._all_connections = list(connections)
        self._apply_filter()

    def clear_search(self) -> None:
        if self._search_edit is not None:
            self._search_edit.clear()

    def _expanded_key(self, group: str) -> str:
        return f"connections/tree_expanded/{group or '__ungrouped__'}"

    def _is_group_expanded(self, group: str, *, default: bool = True) -> bool:
        return self._settings.value(self._expanded_key(group), default, type=bool)

    def _set_group_expanded(self, group: str, expanded: bool) -> None:
        self._settings.setValue(self._expanded_key(group), expanded)

    def _apply_filter(self) -> None:
        query = ""
        if self._search_edit is not None:
            query = self._search_edit.text().strip().lower()

        if query:
            filtered = [
                (group, name, config)
                for group, name, config in self._all_connections
                if query in build_connection_search_text(group, name, config)
            ]
        else:
            filtered = list(self._all_connections)

        self._populate(filtered, force_expand=bool(query))

    def _populate(self, connections: List[ConnectionTuple], *, force_expand: bool = False) -> None:
        ConnectionItemWidget, get_db_icon, icon_size, row_height = _connection_row_classes()
        colors = get_colors()

        grouped: Dict[str, List[Tuple[str, dict]]] = defaultdict(list)
        for group, name, config in connections:
            if config:
                grouped[group or ""].append((name, config))

        self.tree_widget.clear()
        group_keys = sorted(grouped.keys(), key=lambda g: (g == "", g.lower()))

        group_font = QFont()
        group_font.setPixelSize(13)
        group_font.setWeight(QFont.Weight.DemiBold)

        for group in group_keys:
            label = _ungrouped_label() if not group else group
            group_item = QTreeWidgetItem([label])
            group_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "group": group})
            group_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            group_item.setFont(0, group_font)
            group_item.setForeground(0, QBrush(QColor(colors.text_secondary)))
            group_item.setSizeHint(0, QSize(250, 28))
            self.tree_widget.addTopLevelItem(group_item)

            expanded = force_expand or self._is_group_expanded(group)
            group_item.setExpanded(expanded)

            for name, config in sorted(grouped[group], key=lambda item: item[0].lower()):
                db_type = config.get("db_type", "SQL Server")
                host = config.get("host", "")
                database = config.get("database", "")
                custom_color = config.get("color", "")
                icon = get_db_icon(
                    db_type,
                    custom_color if custom_color else None,
                    size=icon_size,
                )

                conn_item = QTreeWidgetItem(group_item)
                conn_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {
                        "type": "connection",
                        "group": group,
                        "name": name,
                        "config": config,
                    },
                )
                conn_item.setToolTip(0, f"{db_type}\n{host}\n{database}")
                conn_item.setSizeHint(0, QSize(250, row_height))

                widget = ConnectionItemWidget(name, "", icon)
                self.tree_widget.setItemWidget(conn_item, 0, widget)

        self.tree_widget.itemExpanded.connect(self._on_group_expanded)
        self.tree_widget.itemCollapsed.connect(self._on_group_collapsed)

    def _on_group_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "group":
            self._set_group_expanded(data.get("group", ""), True)

    def _on_group_collapsed(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "group":
            self._set_group_expanded(data.get("group", ""), False)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "connection":
            self.connection_activated.emit(data.get("group", ""), data.get("name", ""))
