"""
Simple dialog for selecting a saved connection.

Reuses the connection list (DraggableConnectionList + ConnectionItem)
from the sidebar panel. The user double-clicks to select.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidgetItem,
    QFrame,
)
from PyQt6.QtCore import Qt, QSize

from src.core.theme_manager import ThemeManager
from src.language import S

try:
    import qtawesome as qta
except ImportError:
    qta = None


class ConnectionPickerDialog(QDialog):
    """Dialog for selecting a saved connection (double click)"""

    def __init__(self, connection_manager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.theme_manager = theme_manager or ThemeManager()
        self.selected_connection = None
        self._selected_config = None

        self.setWindowTitle(S.connection_picker.title)
        self.resize(380, 420)

        self._setup_ui()
        self._load_connections()

    def _setup_ui(self):
        """Sets up the UI"""
        from src.design_system.frameless_dialog import install_frameless_shell

        layout = install_frameless_shell(
            self,
            S.connection_picker.title,
            min_width=380,
            min_height=420,
            content_margins=(16, 12, 16, 16),
            content_spacing=12,
        )

        # Header
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        header = QHBoxLayout()
        if qta:
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon("mdi.database-search", color=colors.info).pixmap(20, 20))
            header.addWidget(icon_label)
        title = QLabel(S.connection_picker.header)
        title.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {colors.text_tertiary};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Instruction
        hint = QLabel(S.connection_picker.hint)
        hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px; font-style: italic;")
        layout.addWidget(hint)

        # Connection list - reuses components from connection_panel
        from src.ui.components.connection_panel import (
            DraggableConnectionList,
            ConnectionItem,
            ConnectionItemWidget,
        )

        self.list_widget = DraggableConnectionList()
        self.list_widget.setDragEnabled(False)  # No drag in this context
        self.list_widget.setMinimumHeight(250)
        self.list_widget.setIconSize(QSize(28, 28))
        self.list_widget.setSpacing(2)
        self.list_widget.setWordWrap(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        # Estilo com selecao suave
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {colors.bg_primary};
                border: 1px solid {colors.border_muted};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 6px;
                margin: 2px 0px;
            }}
            QListWidget::item:selected {{
                background: rgba(59, 130, 246, 0.2);
            }}
            QListWidget::item:hover {{
                background: {colors.bg_elevated};
            }}
        """)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton(S.connection_picker.btn_cancel)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _load_connections(self):
        """Loads saved connections into the list"""
        from src.ui.components.connection_panel import ConnectionItem, ConnectionItemWidget

        self.list_widget.clear()

        for conn_name in self.connection_manager.get_saved_connections():
            config = self.connection_manager.get_connection_config(conn_name)
            if not config:
                continue

            item = ConnectionItem(conn_name, config)
            item.setData(Qt.ItemDataRole.UserRole, conn_name)
            self.list_widget.addItem(item)

            widget = ConnectionItemWidget(conn_name, item.group, item.icon)
            self.list_widget.setItemWidget(item, widget)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """Double click selects the connection and closes the dialog"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self.selected_connection = conn_name
            self._selected_config = self.connection_manager.get_connection_config(conn_name)
            self.accept()

    def get_result(self):
        """Returns (connection_name, config) or (None, None)"""
        return self.selected_connection, self._selected_config
