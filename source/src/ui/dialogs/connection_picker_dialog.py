"""
Simple dialog for selecting a saved connection.

Uses the shared SavedConnectionsListView (search + same row layout as the sidebar).
Double-click to select.
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

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
        self.selected_group = ""
        self.selected_connection = None
        self._selected_config = None

        self.setWindowTitle(S.connection_picker.title)
        self.resize(420, 480)

        self._setup_ui()
        self._load_connections()

    def _setup_ui(self):
        """Sets up the UI"""
        from src.design_system.frameless_dialog import install_frameless_shell
        from src.design_system.tokens import get_colors
        from src.ui.components.saved_connections_list import SavedConnectionsListView

        colors = get_colors()

        layout = install_frameless_shell(
            self,
            S.connection_picker.title,
            min_width=400,
            min_height=460,
            content_margins=(16, 12, 16, 16),
            content_spacing=12,
        )

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

        hint = QLabel(S.connection_picker.hint)
        hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px; font-style: italic;")
        layout.addWidget(hint)

        self._connections_list = SavedConnectionsListView(
            show_search=True,
            drag_enabled=False,
            list_min_height=280,
            bordered=True,
        )
        self._connections_list.connection_activated.connect(self._on_connection_selected)
        layout.addWidget(self._connections_list, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton(S.connection_picker.btn_cancel)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _load_connections(self):
        """Loads saved connections into the shared list widget."""
        self._connections_list.refresh(self.connection_manager.iter_saved_connections())

    def _on_connection_selected(self, group: str, conn_name: str):
        self.selected_group = group or ""
        self.selected_connection = conn_name
        self._selected_config = self.connection_manager.get_connection_config(group, conn_name)
        self.accept()

    def get_result(self):
        """Returns (group, connection_name, config) or ("", None, None)"""
        return self.selected_group, self.selected_connection, self._selected_config
