"""
Dialog for configuring application settings (language + keyboard shortcuts)
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
    QTabWidget,
    QWidget,
    QComboBox,
    QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager
from src.language import S, get_available_languages


class SettingsDialog(QDialog):
    """Settings dialog with tabs for General and Shortcuts"""

    shortcuts_changed = pyqtSignal()  # Signal emitted when shortcuts are saved

    def __init__(self, shortcut_manager: ShortcutManager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._original_language = S.language_code
        self._setup_ui()
        self._load_shortcuts()

    def _setup_ui(self):
        """Sets up the UI with tabs"""
        self.setWindowTitle(S.settings.title)
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

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3e3e42;
                border-radius: 0px;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 20px;
                border: 1px solid #3e3e42;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                border-bottom: 2px solid #007acc;
            }
            QTabBar::tab:hover:!selected {
                background-color: #383838;
            }
        """)

        # General tab
        self._setup_general_tab()

        # Shortcuts tab
        self._setup_shortcuts_tab()

        layout.addWidget(self.tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_reset = QPushButton(S.settings.btn_restore_defaults)
        btn_reset.setFixedHeight(32)
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_cancel = QPushButton(S.settings.btn_cancel)
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton(S.settings.btn_save)
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 0px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        btn_save.clicked.connect(self._save_all)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _setup_general_tab(self):
        """Sets up the General tab with language selector"""
        general_widget = QWidget()
        general_layout = QVBoxLayout(general_widget)
        general_layout.setSpacing(20)
        general_layout.setContentsMargins(20, 20, 20, 20)

        # Language section
        lang_group = QGroupBox(S.settings.section_language)
        lang_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                color: #cccccc;
                border: 1px solid #3e3e42;
                border-radius: 0px;
                margin-top: 12px;
                padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
        """)
        lang_layout = QVBoxLayout(lang_group)
        lang_layout.setSpacing(10)

        # Language combo
        lang_row = QHBoxLayout()
        lang_label = QLabel(S.settings.label_language)
        lang_label.setStyleSheet("color: #cccccc; font-size: 11px; font-weight: normal;")
        lang_row.addWidget(lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(250)
        self.lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3e3e42;
                border-radius: 0px;
                padding: 6px 10px;
                font-size: 11px;
            }
            QComboBox:hover {
                border-color: #007acc;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d30;
                color: #cccccc;
                selection-background-color: #094771;
                border: 1px solid #3e3e42;
            }
        """)

        # Load available languages
        languages = get_available_languages()
        current_idx = 0
        for i, lang in enumerate(languages):
            self.lang_combo.addItem(lang["name"], lang["code"])
            if lang["code"] == S.language_code:
                current_idx = i
        self.lang_combo.setCurrentIndex(current_idx)

        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        lang_layout.addLayout(lang_row)

        # Restart hint
        hint_label = QLabel(S.settings.language_restart_hint)
        hint_label.setStyleSheet("color: #6e6e6e; font-size: 10px; font-style: italic; font-weight: normal;")
        lang_layout.addWidget(hint_label)

        general_layout.addWidget(lang_group)

        # Display section - Grid row limit
        display_group = QGroupBox(
            S.settings.section_display if hasattr(S.settings, 'section_display') else "DISPLAY"
        )
        display_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                color: #cccccc;
                border: 1px solid #3e3e42;
                border-radius: 0px;
                margin-top: 12px;
                padding-top: 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
        """)
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(10)

        # Row limit
        row_limit_row = QHBoxLayout()
        row_limit_label = QLabel(
            S.settings.label_grid_row_limit if hasattr(S.settings, 'label_grid_row_limit')
            else "Default grid display limit (rows):"
        )
        row_limit_label.setStyleSheet("color: #cccccc; font-size: 11px; font-weight: normal;")
        row_limit_row.addWidget(row_limit_label)

        self.grid_row_limit_spin = QSpinBox()
        self.grid_row_limit_spin.setRange(10, 1000000)
        self.grid_row_limit_spin.setSingleStep(100)
        settings = QSettings("DataPyn", "DataPyn")
        self.grid_row_limit_spin.setValue(int(settings.value("grid/display_row_limit", 100)))
        self.grid_row_limit_spin.setFixedWidth(120)
        self.grid_row_limit_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3e3e42;
                border-radius: 0px;
                padding: 6px 10px;
                font-size: 11px;
            }
            QSpinBox:hover {
                border-color: #007acc;
            }
        """)
        row_limit_row.addWidget(self.grid_row_limit_spin)
        row_limit_row.addStretch()
        display_layout.addLayout(row_limit_row)

        # Hint
        display_hint = QLabel(
            S.settings.grid_row_limit_hint if hasattr(S.settings, 'grid_row_limit_hint')
            else "Only affects display. Exports always include all data."
        )
        display_hint.setStyleSheet("color: #6e6e6e; font-size: 10px; font-style: italic; font-weight: normal;")
        display_layout.addWidget(display_hint)

        general_layout.addWidget(display_group)
        general_layout.addStretch()

        self.tabs.addTab(general_widget, S.settings.tab_general)

    def _setup_shortcuts_tab(self):
        """Sets up the Shortcuts tab"""
        shortcuts_widget = QWidget()
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        shortcuts_layout.setSpacing(15)
        shortcuts_layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(5)

        title = QLabel(S.settings.header_shortcuts)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        subtitle = QLabel(S.settings.subtitle_shortcuts)
        subtitle.setStyleSheet("color: #999999; font-size: 11px;")
        header_layout.addWidget(subtitle)

        shortcuts_layout.addLayout(header_layout)

        # Instructions
        instructions = QLabel(S.settings.tip_shortcuts)
        instructions.setStyleSheet("""
            background-color: #2d2d30;
            color: #cccccc;
            padding: 10px;
            border-radius: 0px;
            border-left: 3px solid #007acc;
            font-size: 10px;
        """)
        shortcuts_layout.addWidget(instructions)

        # Shortcuts table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([S.settings.header_action, S.settings.header_shortcut])
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

        shortcuts_layout.addWidget(self.table)

        self.tabs.addTab(shortcuts_widget, S.settings.tab_shortcuts)

    def _load_shortcuts(self):
        """Loads shortcuts into the table"""
        shortcuts = self.shortcut_manager.get_all_shortcuts()

        # Friendly descriptions for ALL shortcuts
        descriptions = {
            # Execution
            "execute_sql": "Run Current Block",
            "execute_all": "Run All Blocks",
            "execute_block_advance": "Run Block & Advance",
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
            # Editing (additional)
            "format_code": "Format Code",
            "toggle_comment": "Toggle Comment",
            # Editor (QScintilla)
            "editor_newline": "[Editor] Newline (Shift+Enter)",
            "editor_duplicate_line": "[Editor] Duplicate Line/Selection",
            "editor_cut_line": "[Editor] Cut Line",
            "editor_transpose_line": "[Editor] Transpose Lines",
            "editor_lowercase": "[Editor] Lowercase",
            "editor_uppercase": "[Editor] Uppercase",
            "editor_delete_line": "[Editor] Delete Line",
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
        key_dialog.setWindowTitle(S.settings.edit_shortcut_title)
        key_dialog.setModal(True)
        key_dialog.setFixedSize(400, 150)

        layout = QVBoxLayout(key_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        label = QLabel(S.settings.edit_shortcut_msg.format(action=action_name))
        layout.addWidget(label)

        key_edit = QKeySequenceEdit(QKeySequence(current_shortcut))
        key_edit.setFocus()
        layout.addWidget(key_edit)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton(S.settings.btn_cancel)
        btn_cancel.setFixedHeight(28)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(key_dialog.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton(S.settings.btn_ok)
        btn_ok.setFixedHeight(28)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 0px;
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
                            S.settings.conflict_title,
                            S.settings.conflict_msg.format(
                                shortcut=new_sequence, action=other_action_name
                            ),
                        )
                        return

                self.table.item(row, 1).setText(new_sequence)

    def _save_all(self):
        """Saves all settings (language + shortcuts)"""
        # Save language preference
        selected_lang = self.lang_combo.currentData()
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("language", selected_lang)

        # Save grid display row limit
        settings.setValue("grid/display_row_limit", self.grid_row_limit_spin.value())

        # Save shortcuts
        for row in range(self.table.rowCount()):
            shortcut_item = self.table.item(row, 1)
            action = shortcut_item.data(Qt.ItemDataRole.UserRole)
            shortcut = shortcut_item.text()
            self.shortcut_manager.set_shortcut(action, shortcut)

        # Emit signal for MainWindow to re-register shortcuts
        self.shortcuts_changed.emit()

        QMessageBox.information(self, S.settings.success_title, S.settings.success_msg)

        # If language changed, prompt restart
        if selected_lang != self._original_language:
            reply = QMessageBox.question(
                self,
                S.dialogs.language_restart_title,
                S.dialogs.language_restart_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                import sys
                import os
                from PyQt6.QtWidgets import QApplication
                QApplication.quit()
                os.execl(sys.executable, sys.executable, *sys.argv)
                return

        self.accept()

    def _reset_defaults(self):
        """Restores default shortcuts"""
        reply = QMessageBox.question(
            self,
            S.settings.confirm_restore_title,
            S.settings.confirm_restore_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.shortcut_manager.reset_to_defaults()
            self._load_shortcuts()
