"""
Dialog for configuring keyboard shortcuts
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QHeaderView,
    QKeySequenceEdit,
    QMessageBox,
    QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager


class SettingsDialog(QDialog):
    """Settings dialog"""

    shortcuts_changed = pyqtSignal()  # Signal emitted when shortcuts are saved

    def __init__(self, shortcut_manager: ShortcutManager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._setup_ui()
        self._load_shortcuts()

    def _setup_ui(self):
        """Sets up the UI"""
        self.setWindowTitle("Settings - Shortcuts")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.resize(750, 550)

        # Remove maximize/minimize buttons
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)

        # Apply theme
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(5)

        title = QLabel("Keyboard Shortcuts")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        subtitle = QLabel("Customize DataPyn shortcuts")
        subtitle.setStyleSheet("color: #999999; font-size: 11px;")
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        # Instructions
        instructions = QLabel("Tip: Double-click a shortcut to edit")
        instructions.setStyleSheet("""
            background-color: #2d2d30;
            color: #cccccc;
            padding: 10px;
            border-radius: 4px;
            border-left: 3px solid #007acc;
            font-size: 10px;
        """)
        layout.addWidget(instructions)

        # Shortcuts table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._edit_shortcut)

        # Table style
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #3e3e42;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #094771;
            }
            QHeaderView::section {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)

        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_reset = QPushButton("Restore Defaults")
        btn_reset.setFixedHeight(32)
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("Save")
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        btn_save.clicked.connect(self._save_shortcuts)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _load_shortcuts(self):
        """Loads shortcuts into the table"""
        shortcuts = self.shortcut_manager.get_all_shortcuts()

        # Friendly descriptions for ALL shortcuts
        descriptions = {
            # Execution
            "execute_sql": "Run Current Block",
            "execute_all": "Run All Blocks",
            "clear_results": "Clear Results",
            # File
            "open_file": "Open File",
            "save_file": "Save File",
            "save_as": "Save As...",
            # Sessions
            "new_tab": "New Tab",
            "close_tab": "Close Tab",
            "add_block": "Add Block",
            # Editing
            "find": "Find",
            "replace": "Replace",
            # Connections
            "manage_connections": "Manage Connections",
            "new_connection": "New Connection",
            # Schema
            "reload_schema": "Reload SQL Schema",
            # Tools
            "settings": "Settings",
        }

        # Show ALL shortcuts
        filtered_shortcuts = shortcuts

        self.table.setRowCount(len(filtered_shortcuts))
        row = 0

        for action, key_sequence in sorted(filtered_shortcuts.items()):
            # Action (friendly name)
            item_desc = QTableWidgetItem(descriptions.get(action, action))
            item_desc.setFlags(item_desc.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_desc)

            # Shortcut (editable)
            item_shortcut = QTableWidgetItem(key_sequence)
            item_shortcut.setData(Qt.ItemDataRole.UserRole, action)  # Store action name
            self.table.setItem(row, 1, item_shortcut)

            row += 1

        # Adjust row heights
        for i in range(self.table.rowCount()):
            self.table.setRowHeight(i, 36)

    def _edit_shortcut(self, row, column):
        """Edits a shortcut"""
        if column != 1:  # Only shortcut column is editable (changed from 2 to 1)
            return

        # Get action from UserRole
        shortcut_item = self.table.item(row, 1)
        action = shortcut_item.data(Qt.ItemDataRole.UserRole)
        action_name = self.table.item(row, 0).text()
        current_shortcut = shortcut_item.text()

        # Create mini dialog to capture key
        key_dialog = QDialog(self)
        key_dialog.setWindowTitle("Edit Shortcut")
        key_dialog.setModal(True)
        key_dialog.setFixedSize(400, 150)

        layout = QVBoxLayout(key_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        label = QLabel(f"Press the new key combination for '{action_name}':")
        layout.addWidget(label)

        key_edit = QKeySequenceEdit(QKeySequence(current_shortcut))
        key_edit.setFocus()
        layout.addWidget(key_edit)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(28)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(key_dialog.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("OK")
        btn_ok.setFixedHeight(28)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        btn_ok.clicked.connect(key_dialog.accept)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)

        if key_dialog.exec():
            new_sequence = key_edit.keySequence().toString()
            if new_sequence:
                # Check for conflicts
                for r in range(self.table.rowCount()):
                    if r != row and self.table.item(r, 1).text() == new_sequence:
                        other_action_name = self.table.item(r, 0).text()
                        QMessageBox.warning(
                            self,
                            "Shortcut Conflict",
                            f"The shortcut '{new_sequence}' is already in use by action '{other_action_name}'.\n\n"
                            f"Please choose another shortcut.",
                        )
                        return

                self.table.item(row, 1).setText(new_sequence)

    def _save_shortcuts(self):
        """Saves shortcuts"""
        # Save shortcuts
        for row in range(self.table.rowCount()):
            shortcut_item = self.table.item(row, 1)
            action = shortcut_item.data(Qt.ItemDataRole.UserRole)
            shortcut = shortcut_item.text()
            self.shortcut_manager.set_shortcut(action, shortcut)

        # Emit signal for MainWindow to re-register shortcuts
        self.shortcuts_changed.emit()

        QMessageBox.information(self, "Success", "Settings saved successfully!")
        self.accept()

    def _reset_defaults(self):
        """Restores default shortcuts"""
        reply = QMessageBox.question(
            self,
            "Confirm",
            "Do you want to restore all shortcuts to default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.shortcut_manager.reset_to_defaults()
            self._load_shortcuts()
