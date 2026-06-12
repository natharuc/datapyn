"""
Reusable saved-connections list with optional search filter.

Used by the connections sidebar panel and the connection picker dialog.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QSizePolicy,
)

from src.design_system.tokens import get_colors
from src.language import S


def build_connection_search_text(name: str, config: dict) -> str:
    """Lowercase blob used to match connection picker / sidebar search."""
    if not config:
        return (name or "").lower()

    parts: list[str] = [
        name or "",
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


def _connection_item_classes():
    from src.ui.components.connection_panel import (
        ConnectionItem,
        ConnectionItemWidget,
        DraggableConnectionList,
        _CONNECTION_ICON_SIZE,
    )

    return ConnectionItem, ConnectionItemWidget, DraggableConnectionList, _CONNECTION_ICON_SIZE


class SavedConnectionsListView(QWidget):
    """Scrollable list of saved connections with optional search."""

    connection_activated = pyqtSignal(str)

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
        self._all_connections: List[Tuple[str, dict]] = []
        self._search_edit: Optional[QLineEdit] = None
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

        (
            _ConnectionItem,
            _ConnectionItemWidget,
            _DraggableConnectionList,
            icon_size,
        ) = _connection_item_classes()

        self.list_widget = _DraggableConnectionList()
        self.list_widget.setDragEnabled(self._drag_enabled)
        self.list_widget.setMinimumHeight(self._list_min_height)
        self.list_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.list_widget.setIconSize(QSize(icon_size, icon_size))
        self.list_widget.setSpacing(4 if not self._bordered else 2)
        self.list_widget.setWordWrap(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)

        border_css = (
            f"border: 1px solid {colors.border_muted};"
            if self._bordered
            else "border: none;"
        )
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background: {colors.bg_primary};
                {border_css}
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
            """
        )
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

    def refresh(self, connections: List[Tuple[str, dict]]) -> None:
        """Replace the full connection set and re-apply the current search filter."""
        self._all_connections = list(connections)
        self._apply_filter()

    def clear_search(self) -> None:
        if self._search_edit is not None:
            self._search_edit.clear()

    def _apply_filter(self) -> None:
        query = ""
        if self._search_edit is not None:
            query = self._search_edit.text().strip().lower()

        if query:
            filtered = [
                (name, config)
                for name, config in self._all_connections
                if query in build_connection_search_text(name, config)
            ]
        else:
            filtered = list(self._all_connections)

        self._populate(filtered)

    def _populate(self, connections: List[Tuple[str, dict]]) -> None:
        ConnectionItem, ConnectionItemWidget, _, _ = _connection_item_classes()

        self.list_widget.clear()
        for name, config in connections:
            if not config:
                continue
            item = ConnectionItem(name, config)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
            widget = ConnectionItemWidget(name, item.group, item.icon)
            self.list_widget.setItemWidget(item, widget)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        conn_name = None
        if hasattr(item, "connection_name"):
            conn_name = item.connection_name
        else:
            conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self.connection_activated.emit(conn_name)
