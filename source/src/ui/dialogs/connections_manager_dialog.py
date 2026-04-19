"""
Dialog for managing saved connections
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QWidget,
    QLabel,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QColorDialog,
    QFrame,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QAction
from typing import Optional

from src.core.theme_manager import ThemeManager
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class DraggableTreeWidget(QTreeWidget):
    """TreeWidget with drag-and-drop support for connections to groups"""

    item_dropped = pyqtSignal(str, str)  # connection_name, target_group ('' for root)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def dropEvent(self, event):
        """Processes connection drop into group"""
        # Gets item being dragged
        dragged_item = self.currentItem()
        if not dragged_item:
            event.ignore()
            return

        dragged_data = dragged_item.data(0, Qt.ItemDataRole.UserRole)
        if not dragged_data or dragged_data.get("type") != "connection":
            # Only allows dragging connections, not groups
            event.ignore()
            return

        connection_name = dragged_data.get("name", "")

        # Gets target item (where dropped)
        target_item = self.itemAt(event.position().toPoint())
        target_group = ""

        if target_item:
            target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
            if target_data:
                if target_data.get("type") == "group":
                    # Dropped on a group
                    target_group = target_data.get("name", "")
                elif target_data.get("type") == "connection":
                    # Dropped on another connection - checks if inside a group
                    parent = target_item.parent()
                    if parent:
                        parent_data = parent.data(0, Qt.ItemDataRole.UserRole)
                        if parent_data and parent_data.get("type") == "group":
                            target_group = parent_data.get("name", "")

        # Emits signal to process the change
        self.item_dropped.emit(connection_name, target_group)

        # Ignores the default event (we'll reload the tree manually)
        event.ignore()


class ConnectionsManagerDialog(QDialog):
    """Dialog for managing saved connections"""

    connection_selected = pyqtSignal(str, dict)  # name, config

    def __init__(self, connection_manager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.theme_manager = theme_manager or ThemeManager()
        self.selected_connection = None
        self.selected_group = None

        self.setWindowTitle(S.connections_manager.title)
        self.resize(900, 600)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)

        self._setup_ui()
        self._load_connections()

    def _setup_ui(self):
        """Sets up the UI"""
        layout = QVBoxLayout(self)

        # Apply theme
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

        # Splitter for tree and details
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: connections tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Groups toolbar
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)
        
        # Compact toolbar button style (use object name for specificity)
        toolbar_btn_style = """
            QPushButton#toolbarBtn {
                padding: 4px 10px;
                font-size: 11px;
                min-height: 22px;
                max-height: 22px;
                font-weight: 500;
            }
        """

        btn_new_group = QPushButton(S.connections_manager.btn_new_group)
        btn_new_group.setObjectName("toolbarBtn")
        if HAS_QTAWESOME:
            btn_new_group.setIcon(qta.icon("mdi.folder-plus", color="white"))
        btn_new_group.setStyleSheet(toolbar_btn_style)
        btn_new_group.clicked.connect(self._new_group)
        toolbar_layout.addWidget(btn_new_group)

        btn_new_conn = QPushButton(S.connections_manager.btn_new_connection)
        btn_new_conn.setObjectName("toolbarBtn")
        if HAS_QTAWESOME:
            btn_new_conn.setIcon(qta.icon("mdi.database-plus", color="white"))
        btn_new_conn.setStyleSheet(toolbar_btn_style)
        btn_new_conn.clicked.connect(self._new_connection)
        toolbar_layout.addWidget(btn_new_conn)

        btn_import_export = QPushButton(S.connections_manager.btn_import_export)
        btn_import_export.setObjectName("toolbarBtn")
        if HAS_QTAWESOME:
            btn_import_export.setIcon(qta.icon("mdi.code-json", color="white"))
        btn_import_export.setStyleSheet(toolbar_btn_style)
        btn_import_export.clicked.connect(self._open_import_export)
        toolbar_layout.addWidget(btn_import_export)

        toolbar_layout.addStretch()
        left_layout.addLayout(toolbar_layout)

        # Connections tree with drag-and-drop support
        self.tree = DraggableTreeWidget()
        self.tree.setHeaderLabels([S.connections_manager.header_connections])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.item_dropped.connect(self._on_connection_dropped)
        # Double click should EDIT connection or rename group inline
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        left_layout.addWidget(self.tree)

        splitter.addWidget(left_panel)

        # Right panel: connection details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Information group
        info_group = QFrame()
        info_group.setFrameShape(QFrame.Shape.StyledPanel)
        info_group_layout = QVBoxLayout(info_group)
        info_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.information", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connections_manager.section_details)
        title.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {colors.text_tertiary};")
        header.addWidget(title)
        header.addStretch()
        info_group_layout.addLayout(header)

        info_layout = QFormLayout()
        info_group_layout.addLayout(info_layout)

        self.lbl_name = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_host = QLabel("-")
        self.lbl_database = QLabel("-")
        self.lbl_username = QLabel("-")
        self.lbl_group = QLabel("-")
        self.lbl_created = QLabel("-")
        self.lbl_last_used = QLabel("-")

        info_layout.addRow(S.connections_manager.detail_name, self.lbl_name)
        info_layout.addRow(S.connections_manager.detail_type, self.lbl_type)
        info_layout.addRow(S.connections_manager.detail_host, self.lbl_host)
        info_layout.addRow(S.connections_manager.detail_database, self.lbl_database)
        info_layout.addRow(S.connections_manager.detail_user, self.lbl_username)
        info_layout.addRow(S.connections_manager.detail_group, self.lbl_group)
        info_layout.addRow(S.connections_manager.detail_created_at, self.lbl_created)
        info_layout.addRow(S.connections_manager.detail_last_used, self.lbl_last_used)

        right_layout.addWidget(info_group)

        # Action buttons
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        # Compact button style (use object name for specificity)
        compact_btn_style = """
            QPushButton#compactBtn {
                padding: 4px 14px;
                font-size: 11px;
                min-height: 24px;
                max-height: 24px;
                font-weight: 500;
            }
        """

        self.btn_connect = QPushButton(S.connections_manager.btn_connect)
        self.btn_connect.setObjectName("compactBtn")
        if HAS_QTAWESOME:
            self.btn_connect.setIcon(qta.icon("mdi.lan-connect", color="white"))
        self.btn_connect.setStyleSheet(compact_btn_style)
        self.btn_connect.clicked.connect(self._connect_selected)
        self.btn_connect.setEnabled(False)
        actions_layout.addWidget(self.btn_connect)

        self.btn_edit = QPushButton(S.connections_manager.btn_edit)
        self.btn_edit.setObjectName("compactBtn")
        if HAS_QTAWESOME:
            self.btn_edit.setIcon(qta.icon("mdi.pencil", color="white"))
        self.btn_edit.setStyleSheet(compact_btn_style)
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_edit.setEnabled(False)
        actions_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton(S.connections_manager.btn_delete)
        self.btn_delete.setObjectName("compactBtn")
        if HAS_QTAWESOME:
            self.btn_delete.setIcon(qta.icon("mdi.delete", color="white"))
        self.btn_delete.setStyleSheet(compact_btn_style)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_delete.setEnabled(False)
        actions_layout.addWidget(self.btn_delete)

        right_layout.addLayout(actions_layout)
        right_layout.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([400, 500])

        layout.addWidget(splitter)

    def _load_connections(self):
        """Loads connections into the tree"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self.tree.clear()

        # Load groups
        groups = self.connection_manager.get_groups()
        group_items = {}

        # Create group items
        for group_name, group_data in groups.items():
            item = QTreeWidgetItem([group_name])
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "name": group_name})

            if HAS_QTAWESOME:
                item.setIcon(0, qta.icon("mdi.folder", color=colors.warning))

            # Apply color if set
            if group_data.get("color"):
                color = QColor(group_data["color"])
                item.setForeground(0, QBrush(color))

            group_items[group_name] = item
            self.tree.addTopLevelItem(item)

        # Load connections
        all_connections = self.connection_manager.saved_configs.get("connections", {})

        for conn_name, conn_config in all_connections.items():
            group = conn_config.get("group", "")

            item = QTreeWidgetItem([conn_name])
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "connection", "name": conn_name})

            if HAS_QTAWESOME:
                db_type = conn_config.get("db_type", "")
                icon_color = "#569cd6"
                # Uses configured color or database type color
                if conn_config.get("color"):
                    icon_color = conn_config["color"]
                elif db_type == "sqlserver":
                    icon_color = "#cc3e44"
                elif db_type == "mysql":
                    icon_color = "#00758f"
                elif db_type == "postgresql":
                    icon_color = "#336791"
                elif db_type == "databricks":
                    icon_color = "#ff3621"

                item.setIcon(0, qta.icon("mdi.database", color=icon_color))

            # Apply color if set
            if conn_config.get("color"):
                color = QColor(conn_config["color"])
                item.setForeground(0, QBrush(color))

            # Add to group or root
            if group and group in group_items:
                group_items[group].addChild(item)
                group_items[group].setExpanded(True)
            else:
                self.tree.addTopLevelItem(item)

        self.tree.expandAll()

    def _on_item_clicked(self, item, column):
        """When clicking an item"""
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if data and data["type"] == "connection":
            self.selected_connection = data["name"]
            self.selected_group = None
            self._show_connection_details(data["name"])
            self.btn_connect.setEnabled(True)
            self.btn_edit.setEnabled(True)
            self.btn_delete.setEnabled(True)
        elif data and data["type"] == "group":
            self.selected_group = data["name"]
            self.selected_connection = None
            self._clear_connection_details()
            self.btn_connect.setEnabled(False)
            self.btn_edit.setEnabled(True)
            self.btn_delete.setEnabled(True)

    def _on_connection_dropped(self, connection_name: str, target_group: str):
        """Processes when a connection is dragged to a group"""
        if not connection_name:
            return

        # Gets current connection configuration
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return

        # Checks if the group changed
        current_group = config.get("group", "")
        if current_group == target_group:
            return  # Nothing changed

        # Updates the connection's group
        config["group"] = target_group

        # Saves the connection with the new group
        self.connection_manager.save_connection_config(
            connection_name,
            config.get("db_type", "sqlserver"),
            config.get("host", ""),
            config.get("port", 1433),
            config.get("database", ""),
            config.get("username", ""),
            config.get("save_password", False),
            config.get("password", ""),
            target_group,  # New group
            config.get("use_windows_auth", False),
            config.get("color", ""),
            config.get("trust_server_certificate", False),
            config.get("http_path", ""),
        )

        # Reloads the tree
        self._load_connections()

        # Visual feedback
        if target_group:
            print(f"Connection '{connection_name}' moved to group '{target_group}'")
        else:
            print(f"Connection '{connection_name}' removed from group")

    def _on_item_double_clicked(self, item, column):
        """On double click - edits connection or renames group inline"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data["type"] == "connection":
            # Connection: open edit
            self._edit_selected()
        elif data["type"] == "group":
            # Group: edit inline (like tabs)
            self._rename_group_inline(item)

    def _show_connection_details(self, name: str):
        """Shows connection details"""
        config = self.connection_manager.get_connection_config(name)
        if not config:
            return

        self.lbl_name.setText(name)
        self.lbl_type.setText(config.get("db_type", "-").upper())
        self.lbl_host.setText(f"{config.get('host', '-')}:{config.get('port', '-')}")
        self.lbl_database.setText(config.get("database", "-"))

        username = config.get("username", "-")
        if config.get("use_windows_auth"):
            username = S.connections_manager.windows_auth
        self.lbl_username.setText(username)

        self.lbl_group.setText(config.get("group", "") or S.connections_manager.no_group)

        created = config.get("created_at", "-")
        if created and created != "-":
            created = created.split("T")[0] + " " + created.split("T")[1][:8]
        self.lbl_created.setText(created)

        last_used = config.get("last_used") or S.connections_manager.never_used
        if last_used and last_used != S.connections_manager.never_used:
            last_used = last_used.split("T")[0] + " " + last_used.split("T")[1][:8]
        self.lbl_last_used.setText(last_used)

    def _clear_connection_details(self):
        """Clears details"""
        self.lbl_name.setText("-")
        self.lbl_type.setText("-")
        self.lbl_host.setText("-")
        self.lbl_database.setText("-")
        self.lbl_username.setText("-")
        self.lbl_group.setText("-")
        self.lbl_created.setText("-")
        self.lbl_last_used.setText("-")

    def _show_context_menu(self, position):
        """Shows context menu"""
        item = self.tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        menu = QMenu(self)

        if data["type"] == "connection":
            act_connect = QAction(S.connections_manager.ctx_connect, self)
            if HAS_QTAWESOME:
                act_connect.setIcon(qta.icon("fa5s.plug"))
            act_connect.triggered.connect(self._connect_selected)
            menu.addAction(act_connect)

            menu.addSeparator()

            act_edit = QAction(S.connections_manager.ctx_edit, self)
            if HAS_QTAWESOME:
                act_edit.setIcon(qta.icon("fa5s.edit"))
            act_edit.triggered.connect(self._edit_selected)
            menu.addAction(act_edit)

            act_duplicate = QAction(S.connections_manager.ctx_duplicate, self)
            if HAS_QTAWESOME:
                act_duplicate.setIcon(qta.icon("fa5s.copy"))
            act_duplicate.triggered.connect(self._duplicate_connection)
            menu.addAction(act_duplicate)

            menu.addSeparator()

            act_delete = QAction(S.connections_manager.ctx_delete, self)
            if HAS_QTAWESOME:
                act_delete.setIcon(qta.icon("fa5s.trash"))
            act_delete.triggered.connect(self._delete_selected)
            menu.addAction(act_delete)

        elif data["type"] == "group":
            act_color = QAction(S.connections_manager.ctx_change_color, self)
            if HAS_QTAWESOME:
                act_color.setIcon(qta.icon("fa5s.palette"))
            act_color.triggered.connect(self._change_group_color)
            menu.addAction(act_color)

            menu.addSeparator()

            act_delete = QAction(S.connections_manager.ctx_delete_group, self)
            if HAS_QTAWESOME:
                act_delete.setIcon(qta.icon("fa5s.trash"))
            act_delete.triggered.connect(self._delete_selected)
            menu.addAction(act_delete)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _new_group(self):
        """Creates a new group"""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(S.connections_manager.dialog_new_group_title)
        dialog.setLabelText(S.connections_manager.dialog_new_group_prompt)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        dialog.resize(400, 150)

        if dialog.exec() == QInputDialog.DialogCode.Accepted:
            name = dialog.textValue()
            if name:
                if name in self.connection_manager.get_groups():
                    QMessageBox.warning(self, S.dialogs.warning, S.connections_manager.dialog_group_exists)
                    return

                self.connection_manager.create_group(name)
                self._load_connections()

    def _rename_group_inline(self, item: QTreeWidgetItem):
        """Renames group inline (editable directly on the item)"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data["type"] != "group":
            return

        old_name = data["name"]

        # Make item editable
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.tree.editItem(item, 0)

        # Connect signal to validate after editing
        def on_item_changed(changed_item, column):
            if changed_item != item:
                return

            new_name = changed_item.text(0).strip()

            # Disconnect signal to avoid loop
            try:
                self.tree.itemChanged.disconnect(on_item_changed)
            except (TypeError, RuntimeError):
                pass

            # Validate new name
            if not new_name or new_name == old_name:
                # Restore old name
                changed_item.setText(0, old_name)
                changed_item.setFlags(changed_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return

            if new_name in self.connection_manager.get_groups():
                QMessageBox.warning(self, S.dialogs.warning, S.connections_manager.dialog_group_exists)
                changed_item.setText(0, old_name)
                changed_item.setFlags(changed_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return

            # Rename group
            self.connection_manager.rename_group(old_name, new_name)
            self.selected_group = new_name
            changed_item.setFlags(changed_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            # Update item data
            changed_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "name": new_name})

        self.tree.itemChanged.connect(on_item_changed)

    def _change_group_color(self):
        """Changes group color"""
        if not self.selected_group:
            return

        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            groups = self.connection_manager.get_groups()
            if self.selected_group in groups:
                groups[self.selected_group]["color"] = color.name()
                self.connection_manager._save_configs()
                self._load_connections()

    def _open_import_export(self):
        """Opens the JSON import/export dialog."""
        from .connection_import_export_dialog import ConnectionImportExportDialog

        dialog = ConnectionImportExportDialog(
            connection_manager=self.connection_manager,
            theme_manager=self.theme_manager,
            parent=self,
        )
        dialog.exec()
        if dialog.imported:
            self._load_connections()

    def _new_connection(self):
        """Creates a new connection"""
        from .connection_edit_dialog import ConnectionEditDialog

        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            name, config = dialog.get_result()

            # Check if connection already exists and ask for confirmation
            existing_connections = self.connection_manager.saved_configs.get("connections", {})
            if name in existing_connections:
                reply = QMessageBox.question(
                    self,
                    S.connections_manager.dialog_confirm_replace_title,
                    S.connections_manager.dialog_confirm_replace_msg.format(name=name),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

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
                config.get("trust_server_certificate", False),
                config.get("http_path", ""),
            )

            self._load_connections()
            QMessageBox.information(self, S.dialogs.success, S.connections_manager.dialog_connection_saved.format(name=name))

    def _edit_selected(self):
        """Edits selected connection or group"""
        if self.selected_connection:
            self._edit_connection()
        elif self.selected_group:
            self._rename_group()

    def _edit_connection(self):
        """Edits selected connection"""
        if not self.selected_connection:
            return

        from .connection_edit_dialog import ConnectionEditDialog

        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return

        dialog = ConnectionEditDialog(
            self.selected_connection,
            config,
            self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self,
        )

        if dialog.exec():
            new_name, new_config = dialog.get_result()

            self.connection_manager.update_connection_config(
                self.selected_connection,
                new_name,
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
                new_config.get("trust_server_certificate", False),
                new_config.get("http_path", ""),
            )

            self.selected_connection = new_name
            self._load_connections()
            QMessageBox.information(self, S.dialogs.success, S.connections_manager.dialog_connection_updated)

    def _duplicate_connection(self):
        """Duplicates selected connection"""
        if not self.selected_connection:
            return

        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return

        new_name, ok = QInputDialog.getText(
            self, S.connections_manager.dialog_duplicate_title, S.connections_manager.dialog_duplicate_prompt, text=S.connections_manager.dialog_duplicate_default.format(name=self.selected_connection)
        )

        if ok and new_name:
            if new_name in self.connection_manager.saved_configs.get("connections", {}):
                QMessageBox.warning(self, S.dialogs.warning, S.connections_manager.dialog_duplicate_exists)
                return

            self.connection_manager.save_connection_config(
                new_name,
                config["db_type"],
                config["host"],
                config["port"],
                config["database"],
                config.get("username", ""),
                False,  # Don't duplicate password
                "",
                config.get("group", ""),
                config.get("use_windows_auth", False),
                config.get("color", ""),
                config.get("trust_server_certificate", False),
                config.get("http_path", ""),
            )

            self._load_connections()
            QMessageBox.information(self, S.dialogs.success, S.connections_manager.dialog_connection_duplicated.format(name=new_name))

    def _delete_selected(self):
        """Deletes selected connection or group"""
        if self.selected_connection:
            reply = QMessageBox.question(
                self,
                S.connections_manager.dialog_confirm_delete_title,
                S.connections_manager.dialog_confirm_delete_conn.format(name=self.selected_connection),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.connection_manager.delete_connection_config(self.selected_connection)
                self.selected_connection = None
                self._load_connections()
                self._clear_connection_details()
                self.btn_connect.setEnabled(False)
                self.btn_edit.setEnabled(False)
                self.btn_delete.setEnabled(False)

        elif self.selected_group:
            reply = QMessageBox.question(
                self,
                S.connections_manager.dialog_confirm_delete_title,
                S.connections_manager.dialog_confirm_delete_group.format(name=self.selected_group),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.connection_manager.delete_group(self.selected_group)
                self.selected_group = None
                self._load_connections()
                self.btn_connect.setEnabled(False)
                self.btn_edit.setEnabled(False)
                self.btn_delete.setEnabled(False)

    def _connect_selected(self):
        """Connects to the selected connection"""
        if not self.selected_connection:
            return

        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return

        # Emit signal with the selected connection
        self.connection_selected.emit(self.selected_connection, config)
        self.accept()
