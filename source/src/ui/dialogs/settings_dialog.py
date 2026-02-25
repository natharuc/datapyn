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
    QCheckBox,
    QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager
from src.language import S, get_available_languages
from src.design_system.tokens import get_colors, RADIUS
from src.services.copilot.copilot_settings import get_copilot_settings


class SettingsDialog(QDialog):
    """Settings dialog with tabs for General and Shortcuts"""

    shortcuts_changed = pyqtSignal()  # Signal emitted when shortcuts are saved
    copilot_chat_login_requested = pyqtSignal()  # User wants to login to Chat
    copilot_chat_logout_requested = pyqtSignal()  # User wants to logout from Chat
    copilot_lsp_login_requested = pyqtSignal()  # User wants to login to LSP/Autocomplete
    copilot_lsp_logout_requested = pyqtSignal()  # User wants to logout from LSP/Autocomplete

    def __init__(self, shortcut_manager: ShortcutManager, theme_manager: ThemeManager = None, parent=None, initial_tab: str = None):
        """
        Initialize settings dialog.
        
        Args:
            shortcut_manager: Shortcut manager instance
            theme_manager: Theme manager instance
            parent: Parent widget
            initial_tab: Tab to show initially ("general", "shortcuts", "copilot", "workspace")
        """
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._original_language = S.language_code
        self._initial_tab = initial_tab
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

        # Get design tokens
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                background-color: {colors.bg_primary};
            }}
            QTabBar::tab {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                padding: 10px 24px;
                border: 1px solid {colors.border_default};
                border-bottom: none;
                border-top-left-radius: {RADIUS.radius_sm}px;
                border-top-right-radius: {RADIUS.radius_sm}px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {colors.bg_primary};
                border-bottom: 2px solid {colors.interactive_primary};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {colors.bg_elevated};
            }}
        """)

        # General tab
        self._setup_general_tab()

        # Shortcuts tab
        self._setup_shortcuts_tab()

        # Copilot tab
        self._setup_copilot_tab()

        # Workspace tab
        self._setup_workspace_tab()

        layout.addWidget(self.tabs)

        # Select initial tab if specified
        if self._initial_tab:
            tab_map = {"general": 0, "shortcuts": 1, "copilot": 2, "workspace": 3}
            if self._initial_tab in tab_map:
                self.tabs.setCurrentIndex(tab_map[self._initial_tab])

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_reset = QPushButton(S.settings.btn_restore_defaults)
        btn_reset.setFixedHeight(32)
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_cancel = QPushButton(S.settings.btn_cancel)
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton(S.settings.btn_save)
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary}dd;
            }}
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
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        lang_group = QGroupBox(S.settings.section_language)
        lang_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        lang_layout = QVBoxLayout(lang_group)
        lang_layout.setSpacing(10)

        # Language combo
        lang_row = QHBoxLayout()
        lang_label = QLabel(S.settings.label_language)
        lang_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        lang_row.addWidget(lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(250)
        self.lang_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }}
            QComboBox:hover {{
                border-color: {colors.interactive_primary};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors.bg_secondary};
                color: {colors.text_secondary};
                selection-background-color: {colors.interactive_primary};
                border: 1px solid {colors.border_default};
            }}
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
        hint_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        lang_layout.addWidget(hint_label)

        general_layout.addWidget(lang_group)

        # Display section - Grid row limit
        display_group = QGroupBox(
            S.settings.section_display if hasattr(S.settings, 'section_display') else "DISPLAY"
        )
        display_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(10)

        # Row limit
        row_limit_row = QHBoxLayout()
        row_limit_label = QLabel(
            S.settings.label_grid_row_limit if hasattr(S.settings, 'label_grid_row_limit')
            else "Default grid display limit (rows):"
        )
        row_limit_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        row_limit_row.addWidget(row_limit_label)

        self.grid_row_limit_spin = QSpinBox()
        self.grid_row_limit_spin.setRange(10, 1000000)
        self.grid_row_limit_spin.setSingleStep(100)
        settings = QSettings("DataPyn", "DataPyn")
        self.grid_row_limit_spin.setValue(int(settings.value("grid/display_row_limit", 100)))
        self.grid_row_limit_spin.setFixedWidth(120)
        self.grid_row_limit_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }}
            QSpinBox:hover {{
                border-color: {colors.interactive_primary};
            }}
        """)
        row_limit_row.addWidget(self.grid_row_limit_spin)
        row_limit_row.addStretch()
        display_layout.addLayout(row_limit_row)

        # Hint
        display_hint = QLabel(
            S.settings.grid_row_limit_hint if hasattr(S.settings, 'grid_row_limit_hint')
            else "Only affects display. Exports always include all data."
        )
        display_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        display_layout.addWidget(display_hint)

        general_layout.addWidget(display_group)

        # Editor section - Monaco Editor info
        editor_group = QGroupBox(
            S.settings.section_editor if hasattr(S.settings, 'section_editor') else "CODE EDITOR"
        )
        editor_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setSpacing(10)

        # Monaco Editor info
        editor_info = QLabel(
            S.settings.editor_monaco if hasattr(S.settings, 'editor_monaco')
            else "Monaco Editor with Copilot inline completions"
        )
        editor_info.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        editor_layout.addWidget(editor_info)

        # Editor hint
        editor_hint = QLabel(
            "Powered by Monaco (VS Code editor engine)"
        )
        editor_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        editor_layout.addWidget(editor_hint)

        general_layout.addWidget(editor_group)
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
        from src.design_system.tokens import get_colors
        colors = get_colors()
        subtitle.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        header_layout.addWidget(subtitle)

        shortcuts_layout.addLayout(header_layout)

        # Instructions
        instructions = QLabel(S.settings.tip_shortcuts)
        instructions.setStyleSheet(f"""
            background-color: {colors.bg_secondary};
            color: {colors.text_secondary};
            padding: 10px;
            border-radius: 4px;
            border-left: 3px solid {colors.interactive_primary};
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
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {colors.border_default};
                font-size: 11px;
            }}
            QTableWidget::item {{
                padding: 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {colors.interactive_primary};
            }}
            QHeaderView::section {{
                background-color: {colors.bg_secondary};
                color: {colors.text_secondary};
                padding: 8px;
                border: none;
                font-weight: bold;
            }}
        """)

        shortcuts_layout.addWidget(self.table)

        self.tabs.addTab(shortcuts_widget, S.settings.tab_shortcuts)

    def _setup_copilot_tab(self):
        """Sets up the Copilot tab with Chat and Autocomplete settings."""
        copilot_widget = QWidget()
        copilot_layout = QVBoxLayout(copilot_widget)
        copilot_layout.setSpacing(20)
        copilot_layout.setContentsMargins(20, 20, 20, 20)

        colors = get_colors()
        self._copilot_settings = get_copilot_settings()

        # ========================
        # COPILOT CHAT SECTION
        # ========================
        chat_group = QGroupBox(
            S.settings.section_copilot_chat if hasattr(S.settings, 'section_copilot_chat')
            else "COPILOT CHAT"
        )
        chat_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        chat_layout = QVBoxLayout(chat_group)
        chat_layout.setSpacing(10)

        # Chat status row
        chat_status_row = QHBoxLayout()
        chat_status_label = QLabel(
            S.settings.copilot_status if hasattr(S.settings, 'copilot_status')
            else "Status:"
        )
        chat_status_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        chat_status_row.addWidget(chat_status_label)

        self._chat_status_value = QLabel()
        self._chat_status_value.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: normal;")
        self._update_chat_status_label()
        chat_status_row.addWidget(self._chat_status_value)
        chat_status_row.addStretch()

        # Chat login/logout button
        self._chat_auth_btn = QPushButton()
        self._chat_auth_btn.setFixedHeight(28)
        self._chat_auth_btn.setFixedWidth(100)
        self._update_chat_button_state()
        self._chat_auth_btn.clicked.connect(self._on_chat_auth_clicked)
        chat_status_row.addWidget(self._chat_auth_btn)

        chat_layout.addLayout(chat_status_row)

        # Chat auto-connect hint
        chat_hint = QLabel(self._get_chat_auth_hint())
        chat_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        chat_layout.addWidget(chat_hint)
        self._chat_hint_label = chat_hint

        copilot_layout.addWidget(chat_group)

        # ========================
        # AUTOCOMPLETE SECTION
        # ========================
        lsp_group = QGroupBox(
            S.settings.section_copilot_autocomplete if hasattr(S.settings, 'section_copilot_autocomplete')
            else "AUTOCOMPLETE"
        )
        lsp_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        lsp_layout = QVBoxLayout(lsp_group)
        lsp_layout.setSpacing(10)

        # LSP status row
        lsp_status_row = QHBoxLayout()
        lsp_status_label = QLabel(
            S.settings.copilot_status if hasattr(S.settings, 'copilot_status')
            else "Status:"
        )
        lsp_status_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        lsp_status_row.addWidget(lsp_status_label)

        self._lsp_status_value = QLabel()
        self._lsp_status_value.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: normal;")
        self._update_lsp_status_label()
        lsp_status_row.addWidget(self._lsp_status_value)
        lsp_status_row.addStretch()

        # LSP login/logout button
        self._lsp_auth_btn = QPushButton()
        self._lsp_auth_btn.setFixedHeight(28)
        self._lsp_auth_btn.setFixedWidth(100)
        self._update_lsp_button_state()
        self._lsp_auth_btn.clicked.connect(self._on_lsp_auth_clicked)
        lsp_status_row.addWidget(self._lsp_auth_btn)

        lsp_layout.addLayout(lsp_status_row)

        # LSP auto-connect hint
        lsp_hint = QLabel(self._get_lsp_auth_hint())
        lsp_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        lsp_layout.addWidget(lsp_hint)
        self._lsp_hint_label = lsp_hint

        copilot_layout.addWidget(lsp_group)
        copilot_layout.addStretch()

        tab_title = S.settings.tab_copilot if hasattr(S.settings, 'tab_copilot') else "Copilot"
        self.tabs.addTab(copilot_widget, tab_title)

        # Connect to auth service signals for real-time updates
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        auth_service.chat_authenticated.connect(self._on_auth_service_chat_updated)
        auth_service.chat_logged_out.connect(self._on_auth_service_chat_updated)
        auth_service.lsp_authenticated.connect(self._on_auth_service_lsp_updated)
        auth_service.lsp_logged_out.connect(self._on_auth_service_lsp_updated)

    def _update_chat_status_label(self):
        """Update the Chat status label based on current state."""
        settings = self._copilot_settings
        if settings.chat_user_logged_out:
            text = S.settings.copilot_logged_out if hasattr(S.settings, 'copilot_logged_out') else "Logged out by user"
        elif settings.chat_was_authenticated:
            username = settings.chat_username or "GitHub User"
            template = S.settings.copilot_authenticated_as if hasattr(S.settings, 'copilot_authenticated_as') else "Authenticated as {user}"
            text = template.format(user=username)
        else:
            text = S.settings.copilot_never_authenticated if hasattr(S.settings, 'copilot_never_authenticated') else "Never authenticated"
        self._chat_status_value.setText(text)

    def _update_lsp_status_label(self):
        """Update the LSP status label based on current state."""
        settings = self._copilot_settings
        if settings.lsp_user_logged_out:
            text = S.settings.copilot_logged_out if hasattr(S.settings, 'copilot_logged_out') else "Logged out by user"
        elif settings.lsp_was_authenticated:
            username = settings.lsp_username or "GitHub User"
            template = S.settings.copilot_authenticated_as if hasattr(S.settings, 'copilot_authenticated_as') else "Authenticated as {user}"
            text = template.format(user=username)
        else:
            text = S.settings.copilot_never_authenticated if hasattr(S.settings, 'copilot_never_authenticated') else "Never authenticated"
        self._lsp_status_value.setText(text)

    def _on_auth_service_chat_updated(self, *args):
        """Handle chat auth state change from auth service."""
        self._update_chat_status_label()
        self._update_chat_button_state()
        self._chat_hint_label.setText(self._get_chat_auth_hint())

    def _on_auth_service_lsp_updated(self, *args):
        """Handle LSP auth state change from auth service."""
        self._update_lsp_status_label()
        self._update_lsp_button_state()
        self._lsp_hint_label.setText(self._get_lsp_auth_hint())

    def _update_chat_button_state(self):
        """Update Chat button text based on auth state."""
        colors = get_colors()
        settings = self._copilot_settings
        if settings.chat_was_authenticated and not settings.chat_user_logged_out:
            text = S.settings.copilot_logout if hasattr(S.settings, 'copilot_logout') else "Sign Out"
            self._chat_auth_btn.setText(text)
            self._chat_auth_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.bg_elevated};
                    color: {colors.text_secondary};
                    border: 1px solid {colors.border_default};
                    border-radius: 4px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {colors.danger};
                    color: white;
                }}
            """)
        else:
            text = S.settings.copilot_login if hasattr(S.settings, 'copilot_login') else "Sign In"
            self._chat_auth_btn.setText(text)
            self._chat_auth_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.interactive_primary};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {colors.interactive_primary}dd;
                }}
            """)

    def _update_lsp_button_state(self):
        """Update LSP button text based on auth state."""
        colors = get_colors()
        settings = self._copilot_settings
        if settings.lsp_was_authenticated and not settings.lsp_user_logged_out:
            text = S.settings.copilot_logout if hasattr(S.settings, 'copilot_logout') else "Sign Out"
            self._lsp_auth_btn.setText(text)
            self._lsp_auth_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.bg_elevated};
                    color: {colors.text_secondary};
                    border: 1px solid {colors.border_default};
                    border-radius: 4px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {colors.danger};
                    color: white;
                }}
            """)
        else:
            text = S.settings.copilot_login if hasattr(S.settings, 'copilot_login') else "Sign In"
            self._lsp_auth_btn.setText(text)
            self._lsp_auth_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.interactive_primary};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {colors.interactive_primary}dd;
                }}
            """)

    def _get_chat_auth_hint(self) -> str:
        """Get hint text for Chat auto-auth status."""
        settings = self._copilot_settings
        hint_template = S.settings.copilot_auto_connect_hint if hasattr(S.settings, 'copilot_auto_connect_hint') else "Only if you have authenticated before"
        if settings.should_auto_auth_chat():
            return f"Auto-connect: ON - {hint_template}"
        elif settings.chat_user_logged_out:
            return "Auto-connect: OFF - User logged out"
        else:
            return "Auto-connect: OFF - Never authenticated"

    def _get_lsp_auth_hint(self) -> str:
        """Get hint text for LSP auto-auth status."""
        settings = self._copilot_settings
        hint_template = S.settings.copilot_auto_connect_hint if hasattr(S.settings, 'copilot_auto_connect_hint') else "Only if you have authenticated before"
        if settings.should_auto_auth_lsp():
            return f"Auto-connect: ON - {hint_template}"
        elif settings.lsp_user_logged_out:
            return "Auto-connect: OFF - User logged out"
        else:
            return "Auto-connect: OFF - Never authenticated"

    def _on_chat_auth_clicked(self):
        """Handle Chat login/logout button click."""
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        if auth_service.is_chat_authenticated or (auth_service.chat_was_authenticated and not auth_service.chat_user_logged_out):
            # Logout
            auth_service.logout_chat()
            self.copilot_chat_logout_requested.emit()  # Notify MainWindow
        else:
            # Login
            if auth_service.login_chat():
                self.copilot_chat_login_requested.emit()  # Notify MainWindow
            # else: login blocked - auth already in progress
        
        self._update_chat_status_label()
        self._update_chat_button_state()
        self._chat_hint_label.setText(self._get_chat_auth_hint())

    def _on_lsp_auth_clicked(self):
        """Handle LSP login/logout button click."""
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        if auth_service.is_lsp_authenticated or (auth_service.lsp_was_authenticated and not auth_service.lsp_user_logged_out):
            # Logout
            auth_service.logout_lsp()
            self.copilot_lsp_logout_requested.emit()  # Notify MainWindow
        else:
            # Login
            if auth_service.login_lsp():
                self.copilot_lsp_login_requested.emit()  # Notify MainWindow
            # else: login blocked - auth already in progress
        
        self._update_lsp_status_label()
        self._update_lsp_button_state()
        self._lsp_hint_label.setText(self._get_lsp_auth_hint())

    def _setup_workspace_tab(self):
        """Setup Workspace tab for workspace/profile management."""
        from src.core.workspace_service import get_workspace_service
        colors = get_colors()
        
        workspace_widget = QWidget()
        workspace_layout = QVBoxLayout(workspace_widget)
        workspace_layout.setSpacing(15)
        workspace_layout.setContentsMargins(15, 15, 15, 15)
        
        # Store workspace service reference
        self._workspace_service = get_workspace_service()
        
        # ========================
        # CURRENT WORKSPACE SECTION
        # ========================
        current_group = QGroupBox(
            S.settings.section_workspace_current if hasattr(S.settings, 'section_workspace_current')
            else "CURRENT WORKSPACE"
        )
        current_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        current_layout = QVBoxLayout(current_group)
        current_layout.setSpacing(8)
        
        # Workspace name
        name_row = QHBoxLayout()
        name_label = QLabel(
            S.settings.workspace_name if hasattr(S.settings, 'workspace_name')
            else "Name:"
        )
        name_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        name_label.setFixedWidth(60)
        name_row.addWidget(name_label)
        
        self._workspace_name_label = QLabel(self._workspace_service.current_workspace_name)
        self._workspace_name_label.setStyleSheet(f"color: {colors.text_primary}; font-size: 12px; font-weight: bold;")
        name_row.addWidget(self._workspace_name_label)
        name_row.addStretch()
        current_layout.addLayout(name_row)
        
        # Workspace path
        path_row = QHBoxLayout()
        path_label = QLabel(
            S.settings.workspace_path if hasattr(S.settings, 'workspace_path')
            else "Folder:"
        )
        path_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;")
        path_label.setFixedWidth(60)
        path_row.addWidget(path_label)
        
        self._workspace_path_label = QLabel(str(self._workspace_service.current_workspace))
        self._workspace_path_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-weight: normal;")
        self._workspace_path_label.setWordWrap(True)
        path_row.addWidget(self._workspace_path_label, 1)
        current_layout.addLayout(path_row)
        
        # Hint
        hint_label = QLabel(
            S.settings.workspace_hint if hasattr(S.settings, 'workspace_hint')
            else "All configurations are stored in this folder"
        )
        hint_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        current_layout.addWidget(hint_label)
        
        workspace_layout.addWidget(current_group)
        
        # ========================
        # SAVED WORKSPACES SECTION
        # ========================
        saved_group = QGroupBox(
            S.settings.section_workspaces if hasattr(S.settings, 'section_workspaces')
            else "SAVED WORKSPACES"
        )
        saved_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: 11px;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
        """)
        saved_layout = QVBoxLayout(saved_group)
        saved_layout.setSpacing(10)
        
        # Workspace list
        self._workspace_list = QListWidget()
        self._workspace_list.setFixedHeight(120)
        self._workspace_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 11px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {colors.border_muted};
            }}
            QListWidget::item:selected {{
                background-color: {colors.interactive_primary};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background-color: {colors.bg_elevated};
            }}
        """)
        
        # Store colors for button state updates (must be before _refresh_workspace_list)
        self._workspace_colors = colors
        
        self._refresh_workspace_list()
        saved_layout.addWidget(self._workspace_list)
        
        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        add_btn = QPushButton(
            S.settings.workspace_add if hasattr(S.settings, 'workspace_add')
            else "Add..."
        )
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary}dd;
            }}
        """)
        add_btn.clicked.connect(self._on_add_workspace)
        btn_row.addWidget(add_btn)
        
        duplicate_btn = QPushButton(
            S.settings.workspace_duplicate if hasattr(S.settings, 'workspace_duplicate')
            else "Duplicate..."
        )
        duplicate_btn.setFixedHeight(28)
        duplicate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 11px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary};
                color: white;
            }}
        """)
        duplicate_btn.clicked.connect(self._on_duplicate_workspace)
        btn_row.addWidget(duplicate_btn)
        
        self._remove_btn = QPushButton(
            S.settings.workspace_remove if hasattr(S.settings, 'workspace_remove')
            else "Remove"
        )
        self._remove_btn.setFixedHeight(28)
        self._remove_btn.clicked.connect(self._on_remove_workspace)
        btn_row.addWidget(self._remove_btn)
        
        # Connect list selection to update button state
        self._workspace_list.currentItemChanged.connect(self._update_remove_button_state)
        
        btn_row.addStretch()
        saved_layout.addLayout(btn_row)
        
        # Switch hint
        switch_hint = QLabel(
            S.settings.workspace_switch_hint if hasattr(S.settings, 'workspace_switch_hint')
            else "Switching workspace requires restarting the app"
        )
        switch_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;")
        saved_layout.addWidget(switch_hint)
        
        workspace_layout.addWidget(saved_group)
        workspace_layout.addStretch()
        
        # Add tab
        tab_title = S.settings.tab_workspace if hasattr(S.settings, 'tab_workspace') else "Workspace"
        self.tabs.addTab(workspace_widget, tab_title)
    
    def _refresh_workspace_list(self):
        """Refresh the workspace list widget."""
        self._workspace_list.clear()
        workspaces = self._workspace_service.list_workspaces()
        current = self._workspace_service.current_workspace
        
        for name, path in workspaces:
            item_text = f"{name}"
            if path == current:
                item_text += " (current)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self._workspace_list.addItem(item)
        
        # Update remove button state
        self._update_remove_button_state()
    
    def _update_remove_button_state(self, current_item=None):
        """Update remove button enabled/disabled state based on selection."""
        # Skip if button or colors not yet created
        if not hasattr(self, '_remove_btn') or not hasattr(self, '_workspace_colors'):
            return
        
        from pathlib import Path
        colors = self._workspace_colors
        
        current_item = current_item or self._workspace_list.currentItem()
        can_remove = False
        
        if current_item:
            path_str = current_item.data(Qt.ItemDataRole.UserRole)
            path = Path(path_str)
            
            # Can remove if: not default workspace AND not current workspace
            is_default = (path == self._workspace_service.current_workspace and 
                         self._workspace_service.is_default_workspace)
            is_current = (path == self._workspace_service.current_workspace)
            
            # Check if it's the default workspace path
            from src.core.workspace_service import DEFAULT_WORKSPACE_PATH
            is_default_path = (path == DEFAULT_WORKSPACE_PATH)
            
            can_remove = not is_current and not is_default_path
        
        if can_remove:
            # Enable with red danger style
            self._remove_btn.setEnabled(True)
            self._remove_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.danger};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {colors.danger}dd;
                }}
            """)
        else:
            # Disable with muted style
            self._remove_btn.setEnabled(False)
            self._remove_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.bg_tertiary};
                    color: {colors.text_tertiary};
                    border: 1px solid {colors.border_muted};
                    border-radius: 4px;
                    font-size: 11px;
                    padding: 0 12px;
                }}
            """)
    
    def _on_add_workspace(self):
        """Handle add workspace button click."""
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path
        
        title = (S.settings.workspace_browse_title 
                 if hasattr(S.settings, 'workspace_browse_title') 
                 else "Select Workspace Folder")
        
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            str(Path.home()),
        )
        
        if folder:
            path = Path(folder)
            if self._workspace_service.add_workspace(path):
                self._refresh_workspace_list()
    
    def _on_remove_workspace(self):
        """Handle remove workspace button click - deletes the folder."""
        from pathlib import Path
        from PyQt6.QtWidgets import QMessageBox
        import shutil
        
        current_item = self._workspace_list.currentItem()
        if not current_item:
            return
        
        path_str = current_item.data(Qt.ItemDataRole.UserRole)
        path = Path(path_str)
        
        # Can't remove default or current
        from src.core.workspace_service import DEFAULT_WORKSPACE_PATH
        if path == DEFAULT_WORKSPACE_PATH:
            return
        if path == self._workspace_service.current_workspace:
            return
        
        # Ask for confirmation
        reply = QMessageBox.warning(
            self,
            S.settings.workspace_remove_title if hasattr(S.settings, 'workspace_remove_title')
            else "Remove Workspace",
            (S.settings.workspace_remove_confirm if hasattr(S.settings, 'workspace_remove_confirm')
             else f"Are you sure you want to permanently delete this workspace and all its files?\n\n{path}\n\nThis action cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # Remove from workspace list first
            self._workspace_service.remove_workspace(path)
            
            # Delete the folder
            if path.exists():
                shutil.rmtree(path)
            
            self._refresh_workspace_list()
            
            QMessageBox.information(
                self,
                "Success",
                S.settings.workspace_remove_success if hasattr(S.settings, 'workspace_remove_success')
                else "Workspace removed successfully."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                (S.settings.workspace_remove_error if hasattr(S.settings, 'workspace_remove_error')
                 else f"Failed to remove workspace:\n{str(e)}")
            )

    def _on_duplicate_workspace(self):
        """Handle duplicate workspace button click."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox, QApplication
        from pathlib import Path
        import shutil
        
        # Get selected workspace or use current
        current_item = self._workspace_list.currentItem()
        if current_item:
            source_path = Path(current_item.data(Qt.ItemDataRole.UserRole))
        else:
            source_path = self._workspace_service.current_workspace
        
        if not source_path.exists():
            return
        
        # Ask for destination folder
        title = (S.settings.workspace_duplicate_title 
                 if hasattr(S.settings, 'workspace_duplicate_title') 
                 else "Select Destination Folder for Duplicate")
        
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            str(Path.home()),
        )
        
        if not folder:
            return
        
        dest_path = Path(folder)
        
        # Check if destination is not same as source
        if dest_path == source_path:
            QMessageBox.warning(
                self,
                "Error",
                S.settings.workspace_duplicate_same_folder if hasattr(S.settings, 'workspace_duplicate_same_folder')
                else "Destination folder cannot be the same as source."
            )
            return
        
        # Check if destination already has files
        if any(dest_path.iterdir()) if dest_path.exists() else False:
            reply = QMessageBox.question(
                self,
                "Confirm",
                S.settings.workspace_duplicate_not_empty if hasattr(S.settings, 'workspace_duplicate_not_empty')
                else "Destination folder is not empty. Files may be overwritten. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Copy files
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            
            # Ensure destination exists
            dest_path.mkdir(parents=True, exist_ok=True)
            
            # Copy each file/folder from source to dest
            for item in source_path.iterdir():
                src_item = source_path / item.name
                dst_item = dest_path / item.name
                
                if src_item.is_dir():
                    if dst_item.exists():
                        shutil.rmtree(dst_item)
                    shutil.copytree(src_item, dst_item)
                else:
                    shutil.copy2(src_item, dst_item)
            
            QApplication.restoreOverrideCursor()
            
            # Add the new workspace
            if self._workspace_service.add_workspace(dest_path):
                self._refresh_workspace_list()
                QMessageBox.information(
                    self,
                    "Success",
                    S.settings.workspace_duplicate_success if hasattr(S.settings, 'workspace_duplicate_success')
                    else f"Workspace duplicated successfully to:\n{dest_path}"
                )
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self,
                "Error",
                S.settings.workspace_duplicate_error if hasattr(S.settings, 'workspace_duplicate_error')
                else f"Failed to duplicate workspace:\n{str(e)}"
            )

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
        from src.design_system.tokens import get_colors
        colors = get_colors()
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        btn_cancel.clicked.connect(key_dialog.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton(S.settings.btn_ok)
        btn_ok.setFixedHeight(28)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary}dd;
            }}
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
        needs_restart = selected_lang != self._original_language
        if needs_restart:
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
