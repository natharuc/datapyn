"""
Dialog for configuring application settings (language + keyboard shortcuts)
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
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
    QScrollArea,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager
from src.language import S, get_available_languages
from src.design_system.tokens import get_colors, RADIUS
from src.services.copilot.copilot_settings import get_copilot_settings
from src.services.notification_delivery_service import (
    EMAIL_PASSWORD_KEY,
    TELEGRAM_TOKEN_KEY,
    get_notification_delivery_service,
    load_notification_transport_settings,
    set_notification_secret,
)


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
        self._pending_notification_test = None
        self._notification_delivery_service = get_notification_delivery_service(self)
        self._setup_ui()
        self._load_shortcuts()
        self._notification_delivery_service.delivery_succeeded.connect(self._on_notification_delivery_success)
        self._notification_delivery_service.delivery_failed.connect(self._on_notification_delivery_failure)

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

        # Copilot tab (LSP autocomplete + Copilot connector sign-in)
        self._setup_copilot_tab()

        # Pynia tab (API token connectors)
        self._setup_pynia_tab()

        # Notifications tab
        self._setup_notifications_tab()

        # Workspace tab
        self._setup_workspace_tab()

        layout.addWidget(self.tabs)

        # Select initial tab if specified
        if self._initial_tab:
            tab_map = {
                "general": 0,
                "shortcuts": 1,
                "copilot": 2,
                "pynia": 3,
                "notifications": 4,
                "workspace": 5,
            }
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

    # ==================== SHARED STYLE HELPERS ====================

    def _get_group_style(self, colors) -> str:
        return f"""
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
        """

    def _get_label_style(self, colors) -> str:
        return f"color: {colors.text_secondary}; font-size: 11px; font-weight: normal;"

    def _get_hint_style(self, colors) -> str:
        return f"color: {colors.text_tertiary}; font-size: 10px; font-style: italic; font-weight: normal;"

    def _get_info_box_style(self, colors) -> str:
        return f"""
            background-color: {colors.bg_secondary};
            color: {colors.text_secondary};
            padding: 8px 8px 8px 12px;
            border-radius: 4px;
            border-left: 3px solid {colors.interactive_primary};
            font-size: 10px;
            font-weight: normal;
        """

    def _get_input_style(self, colors) -> str:
        return f"""
            QLineEdit, QSpinBox, QComboBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }}
            QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
                border-color: {colors.interactive_primary};
            }}
            QLineEdit:focus, QSpinBox:focus {{
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
        """

    def _get_checkbox_style(self, colors) -> str:
        return f"""
            QCheckBox {{
                color: {colors.text_secondary};
                font-size: 11px;
                font-weight: normal;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {colors.border_default};
                border-radius: 3px;
                background-color: {colors.bg_secondary};
            }}
            QCheckBox::indicator:checked {{
                background-color: {colors.interactive_primary};
                border-color: {colors.interactive_primary};
            }}
            QCheckBox::indicator:hover {{
                border-color: {colors.interactive_primary};
            }}
        """

    def _make_group(self, title: str, colors) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet(self._get_group_style(colors))
        return group

    def _make_label(self, text: str, colors, fixed_width: int = 0) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(self._get_label_style(colors))
        if fixed_width:
            lbl.setFixedWidth(fixed_width)
        return lbl

    def _make_hint(self, text: str, colors) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(self._get_hint_style(colors))
        return lbl

    def _make_info_box(self, text: str, colors) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(self._get_info_box_style(colors))
        return lbl

    def _make_field_row(self, label_text: str, widget, colors, label_width: int = 130) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = self._make_label(label_text, colors, fixed_width=label_width)
        row.addWidget(lbl)
        row.addWidget(widget)
        return row

    # ==================== TAB SETUP ====================

    def _setup_general_tab(self):
        """Sets up the General tab with language selector"""
        general_widget = QWidget()
        general_layout = QVBoxLayout(general_widget)
        general_layout.setSpacing(16)
        general_layout.setContentsMargins(20, 20, 20, 20)

        colors = get_colors()
        input_style = self._get_input_style(colors)

        # --- Language section ---
        lang_group = self._make_group(S.settings.section_language, colors)
        lang_layout = QVBoxLayout(lang_group)
        lang_layout.setSpacing(8)

        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(250)
        self.lang_combo.setStyleSheet(input_style)

        languages = get_available_languages()
        current_idx = 0
        for i, lang in enumerate(languages):
            self.lang_combo.addItem(lang["name"], lang["code"])
            if lang["code"] == S.language_code:
                current_idx = i
        self.lang_combo.setCurrentIndex(current_idx)

        lang_layout.addLayout(
            self._make_field_row(S.settings.label_language, self.lang_combo, colors, label_width=150)
        )
        lang_layout.addWidget(self._make_hint(S.settings.language_restart_hint, colors))
        general_layout.addWidget(lang_group)

        # --- Display section ---
        display_group = self._make_group(
            S.settings.section_display if hasattr(S.settings, 'section_display') else "DISPLAY",
            colors,
        )
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(8)

        self.grid_row_limit_spin = QSpinBox()
        self.grid_row_limit_spin.setRange(10, 1000000)
        self.grid_row_limit_spin.setSingleStep(100)
        settings = QSettings("DataPyn", "DataPyn")
        self.grid_row_limit_spin.setValue(int(settings.value("grid/display_row_limit", 100)))
        self.grid_row_limit_spin.setFixedWidth(120)
        self.grid_row_limit_spin.setStyleSheet(input_style)

        display_layout.addLayout(
            self._make_field_row(
                S.settings.label_grid_row_limit if hasattr(S.settings, 'label_grid_row_limit')
                else "Default grid display limit (rows):",
                self.grid_row_limit_spin, colors, label_width=250,
            )
        )
        display_layout.addWidget(self._make_hint(
            S.settings.grid_row_limit_hint if hasattr(S.settings, 'grid_row_limit_hint')
            else "Only affects display. Exports always include all data.",
            colors,
        ))
        general_layout.addWidget(display_group)

        # --- Editor section ---
        editor_group = self._make_group(
            S.settings.section_editor if hasattr(S.settings, 'section_editor') else "CODE EDITOR",
            colors,
        )
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setSpacing(8)

        editor_layout.addWidget(self._make_label(
            S.settings.editor_monaco if hasattr(S.settings, 'editor_monaco')
            else "Monaco Editor with Copilot inline completions",
            colors,
        ))
        editor_layout.addWidget(self._make_hint("Powered by Monaco (VS Code editor engine)", colors))
        general_layout.addWidget(editor_group)

        general_layout.addStretch()
        self.tabs.addTab(general_widget, S.settings.tab_general)

    def _setup_shortcuts_tab(self):
        """Sets up the Shortcuts tab"""
        shortcuts_widget = QWidget()
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        shortcuts_layout.setSpacing(16)
        shortcuts_layout.setContentsMargins(20, 20, 20, 20)

        colors = get_colors()

        # Info box
        shortcuts_layout.addWidget(self._make_info_box(S.settings.tip_shortcuts, colors))

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
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {colors.border_default};
                font-size: 11px;
                border: 1px solid {colors.border_default};
                border-radius: 4px;
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
        copilot_layout.setSpacing(16)
        copilot_layout.setContentsMargins(20, 20, 20, 20)

        colors = get_colors()
        self._copilot_settings = get_copilot_settings()

        # --- Copilot Chat section ---
        chat_group = self._make_group(
            S.settings.section_copilot_chat if hasattr(S.settings, 'section_copilot_chat')
            else "COPILOT CHAT",
            colors,
        )
        chat_layout = QVBoxLayout(chat_group)
        chat_layout.setSpacing(8)

        chat_status_row = QHBoxLayout()
        chat_status_row.setSpacing(8)
        chat_status_row.addWidget(self._make_label(
            S.settings.copilot_status if hasattr(S.settings, 'copilot_status') else "Status:",
            colors,
        ))

        self._chat_status_value = QLabel()
        self._chat_status_value.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: normal;")
        self._update_chat_status_label()
        chat_status_row.addWidget(self._chat_status_value)
        chat_status_row.addStretch()

        self._chat_auth_btn = QPushButton()
        self._chat_auth_btn.setFixedHeight(28)
        self._chat_auth_btn.setFixedWidth(100)
        self._update_chat_button_state()
        self._chat_auth_btn.clicked.connect(self._on_chat_auth_clicked)
        chat_status_row.addWidget(self._chat_auth_btn)
        chat_layout.addLayout(chat_status_row)

        chat_hint = QLabel(self._get_chat_auth_hint())
        chat_hint.setStyleSheet(self._get_hint_style(colors))
        chat_layout.addWidget(chat_hint)
        self._chat_hint_label = chat_hint
        copilot_layout.addWidget(chat_group)

        # --- Autocomplete section ---
        lsp_group = self._make_group(
            S.settings.section_copilot_autocomplete if hasattr(S.settings, 'section_copilot_autocomplete')
            else "AUTOCOMPLETE",
            colors,
        )
        lsp_layout = QVBoxLayout(lsp_group)
        lsp_layout.setSpacing(8)

        lsp_status_row = QHBoxLayout()
        lsp_status_row.setSpacing(8)
        lsp_status_row.addWidget(self._make_label(
            S.settings.copilot_status if hasattr(S.settings, 'copilot_status') else "Status:",
            colors,
        ))

        self._lsp_status_value = QLabel()
        self._lsp_status_value.setStyleSheet(f"color: {colors.text_primary}; font-size: 11px; font-weight: normal;")
        self._update_lsp_status_label()
        lsp_status_row.addWidget(self._lsp_status_value)
        lsp_status_row.addStretch()

        self._lsp_auth_btn = QPushButton()
        self._lsp_auth_btn.setFixedHeight(28)
        self._lsp_auth_btn.setFixedWidth(100)
        self._update_lsp_button_state()
        self._lsp_auth_btn.clicked.connect(self._on_lsp_auth_clicked)
        lsp_status_row.addWidget(self._lsp_auth_btn)
        lsp_layout.addLayout(lsp_status_row)

        lsp_hint = QLabel(self._get_lsp_auth_hint())
        lsp_hint.setStyleSheet(self._get_hint_style(colors))
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

    def _setup_pynia_tab(self):
        """Pynia connectors: OpenAI, Open Router, Claude API tokens."""
        from src.services.pynia import PROVIDERS, get_pynia_settings, get_provider_secret, set_provider_secret
        from src.services.pynia.types import ProviderId

        colors = get_colors()
        pynia_widget = QWidget()
        layout = QVBoxLayout(pynia_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        intro = QLabel(
            S.pynia.settings_intro if hasattr(S, "pynia") else "Configure Pynia AI connectors."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(self._get_hint_style(colors))
        layout.addWidget(intro)

        group = self._make_group(
            S.pynia.section_connectors if hasattr(S, "pynia") else "CONNECTORS",
            colors,
        )
        form = QFormLayout(group)
        form.setSpacing(10)

        self._pynia_provider_combo = QComboBox()
        labels = {
            "openai": S.pynia.provider_openai,
            "openrouter": S.pynia.provider_openrouter,
            "anthropic": S.pynia.provider_anthropic,
        }
        for pid in ("openai", "openrouter", "anthropic"):
            self._pynia_provider_combo.addItem(labels.get(pid, pid), pid)
        form.addRow(
            S.pynia.title if hasattr(S, "pynia") else "Connector",
            self._pynia_provider_combo,
        )

        self._pynia_token_edit = QLineEdit()
        self._pynia_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pynia_token_edit.setPlaceholderText(S.pynia.label_api_token if hasattr(S, "pynia") else "API token")
        form.addRow(S.pynia.label_api_token if hasattr(S, "pynia") else "API token", self._pynia_token_edit)

        self._pynia_base_url_edit = QLineEdit()
        form.addRow(
            S.pynia.label_base_url if hasattr(S, "pynia") else "Base URL",
            self._pynia_base_url_edit,
        )

        btn_row = QHBoxLayout()
        self._pynia_save_btn = QPushButton(S.pynia.btn_save_token if hasattr(S, "pynia") else "Save")
        self._pynia_verify_btn = QPushButton(S.pynia.btn_verify if hasattr(S, "pynia") else "Verify")
        self._pynia_save_btn.clicked.connect(self._on_pynia_save_token)
        self._pynia_verify_btn.clicked.connect(self._on_pynia_verify_token)
        btn_row.addWidget(self._pynia_save_btn)
        btn_row.addWidget(self._pynia_verify_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        self._pynia_status_label = QLabel("")
        self._pynia_status_label.setStyleSheet(self._get_hint_style(colors))
        form.addRow("", self._pynia_status_label)

        copilot_note = QLabel(S.pynia.copilot_hint if hasattr(S, "pynia") else "")
        copilot_note.setWordWrap(True)
        copilot_note.setStyleSheet(self._get_hint_style(colors))
        form.addRow("", copilot_note)

        layout.addWidget(group)
        layout.addStretch()

        self._pynia_settings = get_pynia_settings()
        self._pynia_provider_combo.currentIndexChanged.connect(self._load_pynia_connector_fields)
        self._load_pynia_connector_fields()

        tab_title = S.settings.tab_pynia if hasattr(S.settings, "tab_pynia") else "Pynia"
        self.tabs.addTab(pynia_widget, tab_title)

    def _current_pynia_connector_id(self) -> str:
        return self._pynia_provider_combo.currentData() or "openai"

    def _load_pynia_connector_fields(self):
        from src.services.pynia import get_provider_secret

        pid = self._current_pynia_connector_id()
        self._pynia_token_edit.setText(get_provider_secret(pid))
        self._pynia_base_url_edit.setText(self._pynia_settings.base_url(pid))
        self._pynia_status_label.setText("")

    def _on_pynia_save_token(self):
        from src.services.pynia import set_provider_secret

        pid = self._current_pynia_connector_id()
        token = self._pynia_token_edit.text().strip()
        set_provider_secret(pid, token)
        self._pynia_settings.set_base_url(pid, self._pynia_base_url_edit.text().strip())
        if token:
            self._pynia_settings.on_token_authenticated(pid, pid)
        self._pynia_status_label.setText(S.pynia.verify_ok if hasattr(S, "pynia") else "Saved.")

    def _on_pynia_verify_token(self):
        from src.services.pynia.agent_client import PyniaAgentClient
        from src.services.pynia.types import ProviderId

        pid: ProviderId = self._current_pynia_connector_id()
        self._on_pynia_save_token()
        client = PyniaAgentClient(parent=self)
        client.set_provider(pid)

        def _ok(username: str):
            template = S.pynia.verify_ok if hasattr(S, "pynia") else "OK"
            self._pynia_status_label.setText(template)
            client.deleteLater()

        def _fail(msg: str):
            template = S.pynia.verify_failed if hasattr(S, "pynia") else "Failed: {error}"
            self._pynia_status_label.setText(template.format(error=msg))
            client.deleteLater()

        client.authenticated.connect(_ok)
        client.auth_failed.connect(_fail)
        client.chat_error.connect(_fail)
        client.start_auth()

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

    def _setup_notifications_tab(self):
        """Sets up the Notifications tab with toggle and template config."""
        colors = get_colors()
        settings = QSettings("DataPyn", "DataPyn")
        transport = load_notification_transport_settings()
        input_style = self._get_input_style(colors)
        checkbox_style = self._get_checkbox_style(colors)

        notif_scroll = QScrollArea()
        notif_scroll.setWidgetResizable(True)
        notif_scroll.setFrameShape(QFrame.Shape.NoFrame)
        notif_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        notif_widget = QWidget()
        notif_scroll.setWidget(notif_widget)

        notif_layout = QVBoxLayout(notif_widget)
        notif_layout.setSpacing(16)
        notif_layout.setContentsMargins(20, 20, 20, 20)

        def _make_form_layout() -> QFormLayout:
            form = QFormLayout()
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return form

        # --- General notification settings ---
        general_group = self._make_group(S.settings.section_notifications, colors)
        general_layout = QVBoxLayout(general_group)
        general_layout.setSpacing(8)

        self.notif_enabled_cb = QCheckBox(S.settings.label_notifications_enabled)
        self.notif_enabled_cb.setChecked(
            settings.value("notifications/enabled", True, type=bool)
        )
        self.notif_enabled_cb.setStyleSheet(checkbox_style)
        general_layout.addWidget(self.notif_enabled_cb)

        self.notif_sound_cb = QCheckBox(S.settings.label_notifications_sound)
        self.notif_sound_cb.setChecked(
            settings.value("notifications/sound", True, type=bool)
        )
        self.notif_sound_cb.setStyleSheet(checkbox_style)
        general_layout.addWidget(self.notif_sound_cb)

        notif_layout.addWidget(general_group)

        # --- Template settings ---
        template_group = self._make_group(S.settings.section_notification_template, colors)
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(10)
        template_form = _make_form_layout()

        # Available variables hint
        template_layout.addWidget(self._make_info_box(
            S.settings.notification_variables_hint, colors,
        ))

        # Default templates from translations
        default_success_title = S.settings.notification_default_success_title
        default_success_msg = S.settings.notification_default_success_msg
        default_error_title = S.settings.notification_default_error_title
        default_error_msg = S.settings.notification_default_error_msg

        # Success title
        self.notif_success_title = QLineEdit()
        self.notif_success_title.setText(
            settings.value("notifications/success_title", default_success_title)
        )
        self.notif_success_title.setStyleSheet(input_style)
        template_form.addRow(self._make_label(S.settings.label_success_title, colors), self.notif_success_title)

        # Success message
        self.notif_success_msg = QLineEdit()
        self.notif_success_msg.setText(
            settings.value("notifications/success_message", default_success_msg)
        )
        self.notif_success_msg.setStyleSheet(input_style)
        template_form.addRow(self._make_label(S.settings.label_success_message, colors), self.notif_success_msg)

        # Error title
        self.notif_error_title = QLineEdit()
        self.notif_error_title.setText(
            settings.value("notifications/error_title", default_error_title)
        )
        self.notif_error_title.setStyleSheet(input_style)
        template_form.addRow(self._make_label(S.settings.label_error_title, colors), self.notif_error_title)

        # Error message
        self.notif_error_msg = QLineEdit()
        self.notif_error_msg.setText(
            settings.value("notifications/error_message", default_error_msg)
        )
        self.notif_error_msg.setStyleSheet(input_style)
        template_form.addRow(self._make_label(S.settings.label_error_message, colors), self.notif_error_msg)
        template_layout.addLayout(template_form)

        notif_layout.addWidget(template_group)

        telegram_group = self._make_group(S.settings.section_notification_telegram, colors)
        telegram_layout = QVBoxLayout(telegram_group)
        telegram_layout.setSpacing(10)
        telegram_form = _make_form_layout()

        self.notif_telegram_enabled_cb = QCheckBox(S.settings.label_notifications_telegram_enabled)
        self.notif_telegram_enabled_cb.setChecked(
            settings.value("notifications/telegram/enabled", False, type=bool)
        )
        self.notif_telegram_enabled_cb.setStyleSheet(checkbox_style)
        telegram_layout.addWidget(self.notif_telegram_enabled_cb)

        self.notif_telegram_token = QLineEdit()
        self.notif_telegram_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.notif_telegram_token.setText(transport["telegram"]["bot_token"])
        self.notif_telegram_token.setStyleSheet(input_style)
        telegram_form.addRow(self._make_label(S.settings.label_notification_telegram_token, colors), self.notif_telegram_token)

        self.notif_telegram_chat_id = QLineEdit()
        self.notif_telegram_chat_id.setText(transport["telegram"]["chat_id"])
        self.notif_telegram_chat_id.setStyleSheet(input_style)
        telegram_form.addRow(self._make_label(S.settings.label_notification_telegram_chat_id, colors), self.notif_telegram_chat_id)
        telegram_layout.addLayout(telegram_form)

        self.notif_telegram_status = self._make_hint("", colors)
        telegram_layout.addWidget(self.notif_telegram_status)

        telegram_btn_row = QHBoxLayout()
        telegram_btn_row.addStretch()
        self.notif_telegram_test_btn = QPushButton(S.settings.btn_notification_test_telegram)
        self.notif_telegram_test_btn.clicked.connect(self._send_test_telegram_notification)
        telegram_btn_row.addWidget(self.notif_telegram_test_btn)
        telegram_layout.addLayout(telegram_btn_row)

        notif_layout.addWidget(telegram_group)

        email_group = self._make_group(S.settings.section_notification_email, colors)
        email_layout = QVBoxLayout(email_group)
        email_layout.setSpacing(10)
        email_form = _make_form_layout()

        self.notif_email_enabled_cb = QCheckBox(S.settings.label_notifications_email_enabled)
        self.notif_email_enabled_cb.setChecked(
            settings.value("notifications/email/enabled", False, type=bool)
        )
        self.notif_email_enabled_cb.setStyleSheet(checkbox_style)
        email_layout.addWidget(self.notif_email_enabled_cb)

        self.notif_email_host = QLineEdit()
        self.notif_email_host.setText(transport["email"]["host"])
        self.notif_email_host.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_host, colors), self.notif_email_host)

        self.notif_email_port = QSpinBox()
        self.notif_email_port.setRange(1, 65535)
        self.notif_email_port.setValue(transport["email"]["port"])
        self.notif_email_port.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_port, colors), self.notif_email_port)

        self.notif_email_use_tls = QCheckBox(S.settings.label_notification_email_use_tls)
        self.notif_email_use_tls.setChecked(transport["email"]["use_tls"])
        self.notif_email_use_tls.setStyleSheet(checkbox_style)
        self.notif_email_use_tls.toggled.connect(self._on_notification_email_tls_toggled)

        self.notif_email_use_ssl = QCheckBox(S.settings.label_notification_email_use_ssl)
        self.notif_email_use_ssl.setChecked(transport["email"]["use_ssl"])
        self.notif_email_use_ssl.setStyleSheet(checkbox_style)
        self.notif_email_use_ssl.toggled.connect(self._on_notification_email_ssl_toggled)

        email_security = QWidget()
        email_security_layout = QHBoxLayout(email_security)
        email_security_layout.setContentsMargins(0, 0, 0, 0)
        email_security_layout.setSpacing(12)
        email_security_layout.addWidget(self.notif_email_use_tls)
        email_security_layout.addWidget(self.notif_email_use_ssl)
        email_security_layout.addStretch()
        email_form.addRow(self._make_label(S.settings.label_notification_email_security, colors), email_security)

        self.notif_email_username = QLineEdit()
        self.notif_email_username.setText(transport["email"]["username"])
        self.notif_email_username.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_username, colors), self.notif_email_username)

        self.notif_email_password = QLineEdit()
        self.notif_email_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.notif_email_password.setText(transport["email"]["password"])
        self.notif_email_password.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_password, colors), self.notif_email_password)

        self.notif_email_from = QLineEdit()
        self.notif_email_from.setText(transport["email"]["from_address"])
        self.notif_email_from.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_from, colors), self.notif_email_from)

        self.notif_email_to = QLineEdit()
        self.notif_email_to.setText(transport["email"]["to"])
        self.notif_email_to.setStyleSheet(input_style)
        email_form.addRow(self._make_label(S.settings.label_notification_email_to, colors), self.notif_email_to)
        email_layout.addLayout(email_form)

        self.notif_email_status = self._make_hint("", colors)
        email_layout.addWidget(self.notif_email_status)

        email_btn_row = QHBoxLayout()
        email_btn_row.addStretch()
        self.notif_email_test_btn = QPushButton(S.settings.btn_notification_test_email)
        self.notif_email_test_btn.clicked.connect(self._send_test_email_notification)
        email_btn_row.addWidget(self.notif_email_test_btn)
        email_layout.addLayout(email_btn_row)

        notif_layout.addWidget(email_group)
        notif_layout.addStretch()

        self._refresh_notification_transport_status()

        tab_title = S.settings.tab_notifications if hasattr(S.settings, 'tab_notifications') else "Notifications"
        self.tabs.addTab(notif_scroll, tab_title)

    def _persist_notification_transport_settings(self):
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/telegram/enabled", self.notif_telegram_enabled_cb.isChecked())
        settings.setValue("notifications/telegram/chat_id", self.notif_telegram_chat_id.text().strip())
        set_notification_secret(TELEGRAM_TOKEN_KEY, self.notif_telegram_token.text().strip())

        settings.setValue("notifications/email/enabled", self.notif_email_enabled_cb.isChecked())
        settings.setValue("notifications/email/host", self.notif_email_host.text().strip())
        settings.setValue("notifications/email/port", self.notif_email_port.value())
        settings.setValue("notifications/email/use_tls", self.notif_email_use_tls.isChecked())
        settings.setValue("notifications/email/use_ssl", self.notif_email_use_ssl.isChecked())
        settings.setValue("notifications/email/username", self.notif_email_username.text().strip())
        settings.setValue("notifications/email/from", self.notif_email_from.text().strip())
        settings.setValue("notifications/email/to", self.notif_email_to.text().strip())
        set_notification_secret(EMAIL_PASSWORD_KEY, self.notif_email_password.text())

    def _refresh_notification_transport_status(self):
        transport = load_notification_transport_settings()

        if transport["telegram"]["configured"]:
            self.notif_telegram_status.setText(S.settings.notification_telegram_status_ready)
        else:
            self.notif_telegram_status.setText(S.settings.notification_telegram_status_missing)

        if transport["email"]["configured"]:
            self.notif_email_status.setText(S.settings.notification_email_status_ready)
        else:
            self.notif_email_status.setText(S.settings.notification_email_status_missing)

    def _on_notification_email_ssl_toggled(self, checked: bool):
        if checked and self.notif_email_use_tls.isChecked():
            self.notif_email_use_tls.setChecked(False)

    def _on_notification_email_tls_toggled(self, checked: bool):
        if checked and self.notif_email_use_ssl.isChecked():
            self.notif_email_use_ssl.setChecked(False)

    def _send_test_telegram_notification(self):
        self._persist_notification_transport_settings()
        self._refresh_notification_transport_status()
        transport = load_notification_transport_settings()
        if not transport["telegram"]["enabled"] or not transport["telegram"]["configured"]:
            QMessageBox.warning(self, S.dialogs.warning, S.settings.notification_test_failure.format(channel=S.settings.notification_channel_telegram, error=S.settings.notification_telegram_status_missing))
            return

        self._pending_notification_test = "telegram"
        self._notification_delivery_service.send_test_telegram(
            title=S.settings.notification_test_title,
            message=S.settings.notification_test_message,
        )

    def _send_test_email_notification(self):
        self._persist_notification_transport_settings()
        self._refresh_notification_transport_status()
        transport = load_notification_transport_settings()
        if not transport["email"]["enabled"] or not transport["email"]["configured"]:
            QMessageBox.warning(self, S.dialogs.warning, S.settings.notification_test_failure.format(channel=S.settings.notification_channel_email, error=S.settings.notification_email_status_missing))
            return

        self._pending_notification_test = "email"
        self._notification_delivery_service.send_test_email(
            title=S.settings.notification_test_title,
            message=S.settings.notification_test_message,
        )

    def _on_notification_delivery_success(self, channel: str, _detail: str):
        if self._pending_notification_test != channel:
            return

        self._pending_notification_test = None
        channel_label = S.settings.notification_channel_telegram if channel == "telegram" else S.settings.notification_channel_email
        QMessageBox.information(
            self,
            S.settings.success_title,
            S.settings.notification_test_success.format(channel=channel_label),
        )

    def _on_notification_delivery_failure(self, channel: str, error_text: str):
        if self._pending_notification_test != channel:
            return

        self._pending_notification_test = None
        channel_label = S.settings.notification_channel_telegram if channel == "telegram" else S.settings.notification_channel_email
        QMessageBox.warning(
            self,
            S.dialogs.warning,
            S.settings.notification_test_failure.format(channel=channel_label, error=error_text),
        )

    def _setup_workspace_tab(self):
        """Setup Workspace tab for workspace/profile management."""
        from src.core.workspace_service import get_workspace_service
        colors = get_colors()

        workspace_widget = QWidget()
        workspace_layout = QVBoxLayout(workspace_widget)
        workspace_layout.setSpacing(16)
        workspace_layout.setContentsMargins(20, 20, 20, 20)

        self._workspace_service = get_workspace_service()

        # --- Current workspace section ---
        current_group = self._make_group(
            S.settings.section_workspace_current if hasattr(S.settings, 'section_workspace_current')
            else "CURRENT WORKSPACE",
            colors,
        )
        current_layout = QVBoxLayout(current_group)
        current_layout.setSpacing(8)

        self._workspace_name_label = QLabel(self._workspace_service.current_workspace_name)
        self._workspace_name_label.setStyleSheet(f"color: {colors.text_primary}; font-size: 12px; font-weight: bold;")
        current_layout.addLayout(
            self._make_field_row(
                S.settings.workspace_name if hasattr(S.settings, 'workspace_name') else "Name:",
                self._workspace_name_label, colors, label_width=60,
            )
        )

        self._workspace_path_label = QLabel(str(self._workspace_service.current_workspace))
        self._workspace_path_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-weight: normal;")
        self._workspace_path_label.setWordWrap(True)
        current_layout.addLayout(
            self._make_field_row(
                S.settings.workspace_path if hasattr(S.settings, 'workspace_path') else "Folder:",
                self._workspace_path_label, colors, label_width=60,
            )
        )

        current_layout.addWidget(self._make_hint(
            S.settings.workspace_hint if hasattr(S.settings, 'workspace_hint')
            else "All configurations are stored in this folder",
            colors,
        ))
        workspace_layout.addWidget(current_group)

        # --- Saved workspaces section ---
        saved_group = self._make_group(
            S.settings.section_workspaces if hasattr(S.settings, 'section_workspaces')
            else "SAVED WORKSPACES",
            colors,
        )
        saved_layout = QVBoxLayout(saved_group)
        saved_layout.setSpacing(10)

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

        self._workspace_colors = colors
        self._refresh_workspace_list()
        saved_layout.addWidget(self._workspace_list)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton(
            S.settings.workspace_add if hasattr(S.settings, 'workspace_add') else "Add..."
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
            S.settings.workspace_duplicate if hasattr(S.settings, 'workspace_duplicate') else "Duplicate..."
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
            S.settings.workspace_remove if hasattr(S.settings, 'workspace_remove') else "Remove"
        )
        self._remove_btn.setFixedHeight(28)
        self._remove_btn.clicked.connect(self._on_remove_workspace)
        btn_row.addWidget(self._remove_btn)

        self._workspace_list.currentItemChanged.connect(self._update_remove_button_state)

        btn_row.addStretch()
        saved_layout.addLayout(btn_row)

        saved_layout.addWidget(self._make_hint(
            S.settings.workspace_switch_hint if hasattr(S.settings, 'workspace_switch_hint')
            else "Switching workspace requires restarting the app",
            colors,
        ))

        workspace_layout.addWidget(saved_group)
        workspace_layout.addStretch()

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
            "execute_sql": S.settings.shortcut_actions.execute_sql,
            "execute_all": S.settings.shortcut_actions.execute_all,
            "execute_block_advance": S.settings.shortcut_actions.execute_block_advance,
            "clear_results": S.settings.shortcut_actions.clear_results,
            # File
            "open_file": S.settings.shortcut_actions.open_file,
            "save_file": S.settings.shortcut_actions.save_file,
            "save_as": S.settings.shortcut_actions.save_as,
            "export_script": S.settings.shortcut_actions.export_script,
            # Sessions
            "new_tab": S.settings.shortcut_actions.new_tab,
            "new_session": S.settings.shortcut_actions.new_session,
            "close_tab": S.settings.shortcut_actions.close_tab,
            "add_block": S.settings.shortcut_actions.add_block,
            # Editing
            "find": S.settings.shortcut_actions.find,
            "replace": S.settings.shortcut_actions.replace,
            "format_code": S.settings.shortcut_actions.format_code,
            "show_entity_info": S.settings.shortcut_actions.show_entity_info,
            # Autocomplete
            "force_autocomplete": S.settings.shortcut_actions.force_autocomplete,
            # Connections
            "manage_connections": S.settings.shortcut_actions.manage_connections,
            "new_connection": S.settings.shortcut_actions.new_connection,
            # Schema
            "reload_schema": S.settings.shortcut_actions.reload_schema,
            # Tools
            "settings": S.settings.shortcut_actions.settings,
            # Results grid
            "copy_with_headers": S.settings.shortcut_actions.copy_with_headers,
            # View / Layout
            "exit_app": S.settings.shortcut_actions.exit_app,
            "restore_view": S.settings.shortcut_actions.restore_view,
            "reset_layout": S.settings.shortcut_actions.reset_layout,
            # Editor (QScintilla)
            "editor_newline": S.settings.shortcut_actions.editor_newline,
            "editor_duplicate_line": S.settings.shortcut_actions.editor_duplicate_line,
            "editor_cut_line": S.settings.shortcut_actions.editor_cut_line,
            "editor_transpose_line": S.settings.shortcut_actions.editor_transpose_line,
            "editor_lowercase": S.settings.shortcut_actions.editor_lowercase,
            "editor_uppercase": S.settings.shortcut_actions.editor_uppercase,
            "editor_delete_line": S.settings.shortcut_actions.editor_delete_line,
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

        # Save notification settings
        settings.setValue("notifications/enabled", self.notif_enabled_cb.isChecked())
        settings.setValue("notifications/sound", self.notif_sound_cb.isChecked())
        settings.setValue("notifications/success_title", self.notif_success_title.text())
        settings.setValue("notifications/success_message", self.notif_success_msg.text())
        settings.setValue("notifications/error_title", self.notif_error_title.text())
        settings.setValue("notifications/error_message", self.notif_error_msg.text())
        self._persist_notification_transport_settings()
        self._refresh_notification_transport_status()

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
