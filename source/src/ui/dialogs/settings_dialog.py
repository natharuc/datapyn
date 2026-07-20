"""
Dialog for configuring application settings (language + keyboard shortcuts)
"""

from src.design_system.app_dialogs import (
    confirm_yes_no,
    show_danger,
    show_information,
    show_success,
    show_warning,
)
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
    QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QObject, QThread, pyqtSlot
from PyQt6.QtGui import QKeySequence, QColor, QBrush
from src.core import ShortcutManager
from src.core.parameter_settings import (
    DEFAULT_SHARED_PARAMETER_DELIMITER,
    get_shared_parameter_delimiter,
    set_shared_parameter_delimiter,
)
from src.core.theme_manager import ThemeManager
from src.language import S, get_available_languages
import weakref

from src.design_system.frameless_dialog import widget_is_valid
from src.design_system.tokens import get_colors, RADIUS
from src.services.copilot.copilot_settings import get_copilot_settings
from src.ui.components.toggle_switch import LabeledToggleSwitch
from src.services.notification_delivery_service import (
    EMAIL_PASSWORD_KEY,
    TELEGRAM_TOKEN_KEY,
    get_notification_delivery_service,
    load_notification_transport_settings,
    set_notification_secret,
)


class _PyniaModelFetchWorker(QObject):
    """Fetch the connector's available model ids off the UI thread."""

    done = pyqtSignal(str, list)  # provider_id, [model_id, ...]

    def __init__(self, provider_id: str):
        super().__init__()
        self._provider_id = provider_id

    @pyqtSlot()
    def run(self):
        pid = self._provider_id
        ids: list = []
        try:
            from src.services.pynia.settings import get_pynia_settings, get_provider_secret
            from src.services.pynia.providers.token_worker import FALLBACK_MODELS
            from src.services.copilot.copilot_models import normalize_models

            token = get_provider_secret(pid)
            settings = get_pynia_settings()
            models = list(FALLBACK_MODELS.get(pid, []))
            if token and pid in ("openai", "openrouter"):
                from src.services.pynia.openai_agent_loop import fetch_openai_models
                from src.services.pynia.providers.token_worker import OPENROUTER_HEADERS

                extra = OPENROUTER_HEADERS if pid == "openrouter" else None
                fetched = fetch_openai_models(
                    settings.base_url(pid),
                    token,
                    extra_headers=extra,
                    provider_id=pid,
                )
                if fetched:
                    models = normalize_models(fetched) or models
            ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
        except Exception:
            ids = []
        self.done.emit(pid, ids)


class SettingsDialog(QDialog):
    """Settings dialog with tabs for General and Shortcuts"""

    shortcuts_changed = pyqtSignal()  # Signal emitted when shortcuts are saved
    pynia_connector_changed = pyqtSignal(str)  # Active Pynia connector saved (provider_id)
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
            initial_tab: Tab to show initially ("general", "shortcuts", "pynia", "workspace")
        """
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._original_language = S.language_code
        self._initial_tab = initial_tab
        self._pending_notification_test = None
        self._pynia_model_cache: dict[str, list] = {}
        self._pynia_model_thread = None
        self._pynia_model_worker = None
        self._notification_delivery_service = get_notification_delivery_service(self)
        self._setup_ui()
        self._load_shortcuts()
        self._notification_delivery_service.delivery_succeeded.connect(self._on_notification_delivery_success)
        self._notification_delivery_service.delivery_failed.connect(self._on_notification_delivery_failure)

    def _setup_ui(self):
        """Sets up the UI with tabs"""
        self.setWindowTitle(S.settings.title)
        self.resize(750, 550)

        from src.design_system.frameless_dialog import install_frameless_shell

        colors = get_colors()

        layout = install_frameless_shell(
            self,
            S.settings.title,
            min_width=700,
            min_height=500,
            content_margins=(20, 16, 20, 20),
            content_spacing=15,
        )

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                border-top: 1px solid {colors.border_default};
                background-color: {colors.bg_primary};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {colors.text_secondary};
                padding: 10px 22px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                color: {colors.text_primary};
                border-bottom: 2px solid {colors.interactive_primary};
            }}
            QTabBar::tab:hover:!selected {{
                color: {colors.text_primary};
                background-color: {colors.bg_elevated};
            }}
        """)

        # General tab
        self._setup_general_tab()

        # Shortcuts tab
        self._setup_shortcuts_tab()

        # Pynia tab (connectors + inline autocomplete)
        self._setup_pynia_tab()

        # Notifications tab
        self._setup_notifications_tab()

        # Session variables / Parquet storage tab
        self._setup_variables_storage_tab()

        # Workspace tab
        self._setup_workspace_tab()

        layout.addWidget(self.tabs)

        # Select initial tab if specified
        if self._initial_tab:
            tab_map = {
                "general": 0,
                "shortcuts": 1,
                "pynia": 2,
                "notifications": 3,
                "variables": 4,
                "variables_storage": 4,
                "workspace": 5,
                "copilot": 2,
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
                background-color: {colors.interactive_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: {colors.interactive_primary};
                color: {colors.text_primary};
            }}
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)

        btn_layout.addStretch()

        btn_cancel = QPushButton(S.settings.btn_cancel)
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: {colors.interactive_primary};
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
                background-color: {colors.interactive_primary_hover};
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
        row.addWidget(widget, 1)
        return row

    def _wrap_scroll_tab(self, content: QWidget) -> QScrollArea:
        """Scrollable tab body — keeps long settings pages usable."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _make_section_card(self, title: str, colors) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsSectionCard")
        card.setStyleSheet(f"""
            QFrame#settingsSectionCard {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_md}px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        if title:
            heading = QLabel(title)
            heading.setStyleSheet(
                f"color: {colors.text_primary}; font-size: 12px; font-weight: 600; "
                f"background: transparent; border: none;"
            )
            layout.addWidget(heading)
        return card, layout

    def _get_switch_style(self, colors) -> str:
        return f"""
            QCheckBox {{
                color: {colors.text_secondary};
                font-size: 11px;
                spacing: 10px;
            }}
            QCheckBox::indicator {{
                width: 40px;
                height: 22px;
                border-radius: 11px;
                border: 1px solid {colors.border_default};
                background: {colors.bg_tertiary};
            }}
            QCheckBox::indicator:checked {{
                background: {colors.interactive_primary};
                border-color: {colors.interactive_primary};
            }}
            QCheckBox::indicator:hover {{
                border-color: {colors.interactive_primary};
            }}
        """

    # ==================== TAB SETUP ====================

    def _setup_general_tab(self):
        """Sets up the General tab with language selector"""
        page = QWidget()
        general_layout = QVBoxLayout(page)
        general_layout.setSpacing(14)
        general_layout.setContentsMargins(4, 4, 4, 12)

        colors = get_colors()
        input_style = self._get_input_style(colors)

        lang_card, lang_layout = self._make_section_card(S.settings.section_language, colors)
        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(220)
        self.lang_combo.setStyleSheet(input_style)
        languages = get_available_languages()
        current_idx = 0
        for i, lang in enumerate(languages):
            self.lang_combo.addItem(lang["name"], lang["code"])
            if lang["code"] == S.language_code:
                current_idx = i
        self.lang_combo.setCurrentIndex(current_idx)
        lang_layout.addLayout(
            self._make_field_row(S.settings.label_language, self.lang_combo, colors, label_width=140)
        )
        lang_layout.addWidget(self._make_hint(S.settings.language_restart_hint, colors))
        general_layout.addWidget(lang_card)

        display_card, display_layout = self._make_section_card(
            S.settings.section_display if hasattr(S.settings, "section_display") else "DISPLAY",
            colors,
        )
        self.grid_row_limit_spin = QSpinBox()
        self.grid_row_limit_spin.setRange(10, 1000000)
        self.grid_row_limit_spin.setSingleStep(100)
        settings = QSettings("DataPyn", "DataPyn")
        self.grid_row_limit_spin.setValue(int(settings.value("grid/display_row_limit", 100)))
        self.grid_row_limit_spin.setMinimumWidth(120)
        self.grid_row_limit_spin.setStyleSheet(input_style)
        display_layout.addLayout(
            self._make_field_row(
                S.settings.label_grid_row_limit if hasattr(S.settings, "label_grid_row_limit")
                else "Default grid display limit (rows):",
                self.grid_row_limit_spin,
                colors,
                label_width=220,
            )
        )
        display_layout.addWidget(self._make_hint(
            S.settings.grid_row_limit_hint if hasattr(S.settings, "grid_row_limit_hint")
            else "Only affects display. Exports always include all data.",
            colors,
        ))

        general_layout.addWidget(display_card)

        connections_card, connections_layout = self._make_section_card(
            S.settings.section_connections if hasattr(S.settings, "section_connections") else "CONNECTIONS",
            colors,
        )
        self.idle_timeout_spin = QSpinBox()
        self.idle_timeout_spin.setRange(0, 86400)
        self.idle_timeout_spin.setSingleStep(60)
        self.idle_timeout_spin.setSuffix(" s")
        self.idle_timeout_spin.setValue(
            int(settings.value("connections/idle_timeout_sec", 300))
        )
        self.idle_timeout_spin.setMinimumWidth(120)
        self.idle_timeout_spin.setStyleSheet(input_style)
        connections_layout.addLayout(
            self._make_field_row(
                S.settings.label_idle_timeout if hasattr(S.settings, "label_idle_timeout")
                else "Close idle DB connections after:",
                self.idle_timeout_spin,
                colors,
                label_width=220,
            )
        )
        connections_layout.addWidget(self._make_hint(
            S.settings.idle_timeout_hint if hasattr(S.settings, "idle_timeout_hint")
            else "0 disables auto-close. Block connectors reconnect on next run.",
            colors,
        ))
        general_layout.addWidget(connections_card)

        params_card, params_layout = self._make_section_card(
            S.settings.section_parameters if hasattr(S.settings, "section_parameters")
            else "PARAMETERS",
            colors,
        )
        self.shared_delimiter_edit = QLineEdit()
        self.shared_delimiter_edit.setMinimumWidth(220)
        self.shared_delimiter_edit.setStyleSheet(input_style)
        self.shared_delimiter_edit.setText(get_shared_parameter_delimiter())
        self.shared_delimiter_edit.setPlaceholderText(DEFAULT_SHARED_PARAMETER_DELIMITER)
        params_layout.addLayout(
            self._make_field_row(
                S.settings.label_shared_delimiter if hasattr(S.settings, "label_shared_delimiter")
                else "Shared parameter delimiter:",
                self.shared_delimiter_edit,
                colors,
                label_width=220,
            )
        )
        params_layout.addWidget(self._make_hint(
            S.settings.shared_delimiter_hint if hasattr(S.settings, "shared_delimiter_hint")
            else "Use name as the parameter placeholder (e.g. {{name}}, {name}, ::name::). Notifications still use {{...}}.",
            colors,
        ))
        general_layout.addWidget(params_card)

        editor_card, editor_layout = self._make_section_card(
            S.settings.section_editor if hasattr(S.settings, "section_editor") else "CODE EDITOR",
            colors,
        )
        editor_layout.addWidget(self._make_label(
            S.settings.editor_monaco if hasattr(S.settings, "editor_monaco")
            else "Monaco Editor with Pynia AI inline autocomplete",
            colors,
        ))
        editor_layout.addWidget(self._make_hint("Powered by Monaco (VS Code editor engine)", colors))
        general_layout.addWidget(editor_card)

        general_layout.addStretch()
        self.tabs.addTab(self._wrap_scroll_tab(page), S.settings.tab_general)

    def _setup_shortcuts_tab(self):
        """Sets up the Shortcuts tab"""
        page = QWidget()
        shortcuts_layout = QVBoxLayout(page)
        shortcuts_layout.setSpacing(16)
        shortcuts_layout.setContentsMargins(4, 4, 4, 12)

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

        self.tabs.addTab(self._wrap_scroll_tab(page), S.settings.tab_shortcuts)

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

        # Chat auth runs through PyniaAuthService; LSP stays on CopilotAuthService.
        from src.services.copilot import get_copilot_auth_service
        from src.services.pynia import get_pynia_auth_service

        pynia_auth = get_pynia_auth_service()
        pynia_auth.chat_authenticated.connect(self._on_auth_service_chat_updated)
        pynia_auth.chat_logged_out.connect(self._on_auth_service_chat_updated)
        pynia_auth.chat_auth_failed.connect(self._on_auth_service_chat_updated)
        copilot_auth = get_copilot_auth_service()
        copilot_auth.lsp_authenticated.connect(self._on_auth_service_lsp_updated)
        copilot_auth.lsp_logged_out.connect(self._on_auth_service_lsp_updated)

    def _setup_pynia_tab(self):
        """Pynia connectors: OpenAI, Open Router, Claude API tokens."""
        from src.services.pynia import PROVIDERS, get_pynia_settings, get_provider_secret, set_provider_secret
        from src.services.pynia.types import ProviderId

        colors = get_colors()
        input_style = self._get_input_style(colors)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 12)
        layout.setSpacing(14)

        from src.assets.pynia_branding import load_pynia_logo

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        logo_label = QLabel()
        logo_label.setFixedSize(40, 40)
        logo_icon = load_pynia_logo(40)
        if logo_icon:
            logo_label.setPixmap(logo_icon.pixmap(40, 40))
        header_row.addWidget(logo_label)
        title_label = QLabel(
            S.pynia.title if hasattr(S, "pynia") else "Pynia"
        )
        title_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 18px; font-weight: 600;"
        )
        header_row.addWidget(title_label, 1)
        layout.addLayout(header_row)

        intro = QLabel(
            S.pynia.settings_intro if hasattr(S, "pynia") else "Configure Pynia AI connectors."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(self._get_info_box_style(colors))
        layout.addWidget(intro)

        self._pynia_settings = get_pynia_settings()

        conn_card, form = self._make_section_card(
            S.pynia.section_connectors if hasattr(S, "pynia") else "CONNECTORS",
            colors,
        )
        form.addWidget(self._make_label(
            S.pynia.title if hasattr(S, "pynia") else "Connector", colors
        ))
        self._pynia_provider_combo = QComboBox()
        self._pynia_provider_combo.setStyleSheet(input_style)
        labels = {
            "copilot": getattr(S.pynia, "provider_copilot", "GitHub Copilot") if hasattr(S, "pynia") else "GitHub Copilot",
            "openai": S.pynia.provider_openai,
            "openrouter": S.pynia.provider_openrouter,
            "anthropic": S.pynia.provider_anthropic,
        }
        for pid in ("copilot", "openai", "openrouter", "anthropic"):
            self._pynia_provider_combo.addItem(labels.get(pid, pid), pid)
        form.addWidget(self._pynia_provider_combo)

        # --- API-token connectors (OpenAI / OpenRouter / Anthropic) ---
        self._pynia_token_section = QWidget()
        token_layout = QVBoxLayout(self._pynia_token_section)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(6)
        token_layout.addWidget(self._make_label(
            S.pynia.label_api_token if hasattr(S, "pynia") else "API token", colors
        ))
        self._pynia_token_edit = QLineEdit()
        self._pynia_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pynia_token_edit.setPlaceholderText(S.pynia.label_api_token if hasattr(S, "pynia") else "API token")
        self._pynia_token_edit.setStyleSheet(input_style)
        token_layout.addWidget(self._pynia_token_edit)
        token_layout.addWidget(self._make_label(
            S.pynia.label_base_url if hasattr(S, "pynia") else "API base URL (optional)", colors
        ))
        self._pynia_base_url_edit = QLineEdit()
        self._pynia_base_url_edit.setStyleSheet(input_style)
        token_layout.addWidget(self._pynia_base_url_edit)
        btn_row = QHBoxLayout()
        self._pynia_save_btn = QPushButton(S.pynia.btn_save_token if hasattr(S, "pynia") else "Save")
        self._pynia_verify_btn = QPushButton(S.pynia.btn_verify if hasattr(S, "pynia") else "Verify")
        self._pynia_save_btn.clicked.connect(self._on_pynia_save_token)
        self._pynia_verify_btn.clicked.connect(self._on_pynia_verify_token)
        btn_row.addWidget(self._pynia_save_btn)
        btn_row.addWidget(self._pynia_verify_btn)
        btn_row.addStretch()
        token_layout.addSpacing(4)
        token_layout.addLayout(btn_row)

        # --- GitHub Copilot connector (GitHub sign-in, no API token) ---
        self._copilot_settings = get_copilot_settings()
        self._pynia_copilot_section = QWidget()
        copilot_layout = QVBoxLayout(self._pynia_copilot_section)
        copilot_layout.setContentsMargins(0, 0, 0, 0)
        copilot_layout.setSpacing(6)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self._make_label(
            S.settings.copilot_status if hasattr(S.settings, "copilot_status") else "Status:", colors
        ))
        self._chat_status_value = QLabel()
        self._chat_status_value.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 11px; font-weight: normal;"
        )
        status_row.addWidget(self._chat_status_value)
        status_row.addStretch()
        self._chat_auth_btn = QPushButton()
        self._chat_auth_btn.setFixedHeight(28)
        self._chat_auth_btn.setMinimumWidth(100)
        self._chat_auth_btn.clicked.connect(self._on_chat_auth_clicked)
        status_row.addWidget(self._chat_auth_btn)
        copilot_layout.addLayout(status_row)
        self._chat_hint_label = QLabel(self._get_chat_auth_hint())
        self._chat_hint_label.setWordWrap(True)
        self._chat_hint_label.setStyleSheet(self._get_hint_style(colors))
        copilot_layout.addWidget(self._chat_hint_label)
        self._update_chat_status_label()
        self._update_chat_button_state()

        # One page shown at a time — a stack avoids the overlap that
        # show/hide of sibling widgets produced when switching providers.
        self._pynia_connector_stack = QStackedWidget()
        self._pynia_connector_stack.addWidget(self._pynia_token_section)    # index 0
        self._pynia_connector_stack.addWidget(self._pynia_copilot_section)  # index 1
        form.addWidget(self._pynia_connector_stack)

        self._pynia_status_label = QLabel("")
        self._pynia_status_label.setStyleSheet(self._get_hint_style(colors))
        form.addWidget(self._pynia_status_label)

        layout.addWidget(conn_card)

        # Reflect the active connector + live Copilot auth updates.
        active_index = self._pynia_provider_combo.findData(self._pynia_settings.active_provider)
        if active_index >= 0:
            self._pynia_provider_combo.setCurrentIndex(active_index)
        try:
            # The live Copilot login runs through the Pynia auth service (it
            # wraps the agent), so listen there to refresh the status row.
            from src.services.pynia import get_pynia_auth_service

            pynia_auth = get_pynia_auth_service()
            pynia_auth.chat_authenticated.connect(self._on_auth_service_chat_updated)
            pynia_auth.chat_logged_out.connect(self._on_auth_service_chat_updated)
            pynia_auth.chat_auth_failed.connect(self._on_auth_service_chat_updated)
        except Exception:
            pass  # Auth service not available — live status updates disabled.

        auto_card, auto_layout = self._make_section_card(
            S.pynia.section_autocomplete if hasattr(S, "pynia") else "INLINE AUTOCOMPLETE",
            colors,
        )

        self._pynia_autocomplete_cb = LabeledToggleSwitch(
            S.pynia.autocomplete_enable
            if hasattr(S, "pynia")
            else "Enable AI inline autocomplete in code blocks",
            checked=self._pynia_settings.autocomplete_enabled,
        )
        auto_layout.addWidget(self._pynia_autocomplete_cb)

        auto_hint = QLabel(
            S.pynia.autocomplete_hint if hasattr(S, "pynia") else ""
        )
        auto_hint.setWordWrap(True)
        auto_hint.setStyleSheet(self._get_hint_style(colors))
        auto_layout.addWidget(auto_hint)

        # Autocomplete model picker (editable — blank = use the chat model).
        model_row = QHBoxLayout()
        model_label = QLabel(
            getattr(S.pynia, "autocomplete_model_label", "Autocomplete model:")
            if hasattr(S, "pynia")
            else "Autocomplete model:"
        )
        model_label.setStyleSheet(self._get_hint_style(colors))
        self._pynia_completion_model_combo = QComboBox()
        self._pynia_completion_model_combo.setEditable(True)
        self._pynia_completion_model_combo.setMinimumWidth(240)
        self._pynia_completion_model_combo.setStyleSheet(input_style)
        model_row.addWidget(model_label)
        model_row.addWidget(self._pynia_completion_model_combo, 1)
        auto_layout.addLayout(model_row)

        model_hint = QLabel(
            getattr(
                S.pynia,
                "autocomplete_model_hint",
                "Leave blank to use your chat model. Pick a smaller/faster model for snappier suggestions.",
            )
            if hasattr(S, "pynia")
            else "Leave blank to use your chat model."
        )
        model_hint.setWordWrap(True)
        model_hint.setStyleSheet(self._get_hint_style(colors))
        auto_layout.addWidget(model_hint)

        self._pynia_autocomplete_status = QLabel("")
        self._pynia_autocomplete_status.setStyleSheet(self._get_hint_style(colors))
        auto_layout.addWidget(self._pynia_autocomplete_status)
        self._refresh_pynia_autocomplete_status()

        layout.addWidget(auto_card)
        layout.addStretch()

        self._pynia_provider_combo.currentIndexChanged.connect(self._load_pynia_connector_fields)
        self._pynia_provider_combo.currentIndexChanged.connect(self._refresh_pynia_autocomplete_status)
        self._load_pynia_connector_fields()
        self._refresh_pynia_autocomplete_status()

        tab_title = S.settings.tab_pynia if hasattr(S.settings, "tab_pynia") else "Pynia"
        tab_index = self.tabs.addTab(self._wrap_scroll_tab(page), tab_title)
        if logo_icon:
            self.tabs.setTabIcon(tab_index, logo_icon)

    def _refresh_pynia_autocomplete_status(self) -> None:
        from src.services.pynia.settings import get_provider_secret

        if not hasattr(self, "_pynia_autocomplete_status"):
            return
        pid = self._current_pynia_connector_id() if hasattr(self, "_pynia_provider_combo") else "openai"
        if pid == "copilot":
            settings = getattr(self, "_copilot_settings", None)
            ready = bool(
                settings
                and settings.chat_was_authenticated
                and not settings.chat_user_logged_out
            )
            self._pynia_autocomplete_status.setText(
                (S.pynia.autocomplete_ready.format(provider="copilot")
                 if hasattr(S, "pynia") and hasattr(S.pynia, "autocomplete_ready")
                 else "Autocomplete will use GitHub Copilot when enabled.")
                if ready
                else "Sign in to GitHub Copilot above to enable AI autocomplete."
            )
            return
        if get_provider_secret(pid):
            text = (
                S.pynia.autocomplete_ready.format(provider=pid)
                if hasattr(S, "pynia") and hasattr(S.pynia, "autocomplete_ready")
                else f"Autocomplete will use the {pid} connector when enabled."
            )
        else:
            text = (
                S.pynia.autocomplete_need_token
                if hasattr(S, "pynia")
                else "Save an API token above to enable AI autocomplete."
            )
        self._pynia_autocomplete_status.setText(text)

    def _current_pynia_connector_id(self) -> str:
        return self._pynia_provider_combo.currentData() or "openai"

    def _load_pynia_connector_fields(self):
        from src.services.pynia import get_provider_secret

        pid = self._current_pynia_connector_id()
        is_copilot = pid == "copilot"

        # Copilot authenticates via GitHub (no API token), so swap the token
        # fields for the sign-in UI instead of showing an irrelevant token box.
        if hasattr(self, "_pynia_connector_stack"):
            self._pynia_connector_stack.setCurrentWidget(
                self._pynia_copilot_section if is_copilot else self._pynia_token_section
            )

        if is_copilot:
            self._update_chat_status_label()
            self._update_chat_button_state()
            self._chat_hint_label.setText(self._get_chat_auth_hint())
        else:
            self._pynia_token_edit.setText(get_provider_secret(pid))
            self._pynia_base_url_edit.setText(self._pynia_settings.base_url(pid))
        self._pynia_status_label.setText("")
        self._load_pynia_completion_model()
        self._fetch_pynia_models(pid)

    def _load_pynia_completion_model(self):
        """Populate the autocomplete model picker for the current connector.

        Order: fast suggestions first (easy to pick), then the chat model, then
        every model fetched from the connector. Editable so a model that isn't
        listed can still be typed.
        """
        if not hasattr(self, "_pynia_completion_model_combo"):
            return
        from src.services.pynia.completion import COMPLETION_MODEL_SUGGESTIONS

        pid = self._current_pynia_connector_id()
        combo = self._pynia_completion_model_combo

        ordered: list[str] = []
        seen: set[str] = set()

        def _add(model_id: str) -> None:
            mid = (model_id or "").strip()
            if mid and mid not in seen:
                seen.add(mid)
                ordered.append(mid)

        for mid in COMPLETION_MODEL_SUGGESTIONS.get(pid, []):
            _add(mid)
        _add(self._pynia_settings.selected_model(pid))
        for mid in self._pynia_model_cache.get(pid, []):
            _add(mid)

        current = self._pynia_completion_model_combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(ordered)
        combo.setEditText(current or self._pynia_settings.completion_model_override(pid))
        line_edit = combo.lineEdit()
        if line_edit is not None:
            placeholder = (
                getattr(S.pynia, "autocomplete_model_placeholder", "Auto (use chat model)")
                if hasattr(S, "pynia")
                else "Auto (use chat model)"
            )
            line_edit.setPlaceholderText(placeholder)
        combo.blockSignals(False)

    def _fetch_pynia_models(self, pid: str):
        """Fetch the connector's real model list in the background (best-effort)."""
        from src.services.pynia import get_provider_secret

        if pid in self._pynia_model_cache:
            return
        if not get_provider_secret(pid):
            return  # no token → nothing to fetch; suggestions are shown instead
        if self._pynia_model_thread is not None:
            return  # one fetch at a time is enough for a settings dialog

        dialog_ref = weakref.ref(self)
        main_window = self.window()
        thread = QThread()
        thread.setObjectName("PyniaModelFetch")
        worker = _PyniaModelFetchWorker(pid)
        worker.moveToThread(thread)

        def _on_models_fetched(provider_id: str, model_ids: list) -> None:
            dialog = dialog_ref()
            if dialog is not None and widget_is_valid(dialog):
                dialog._on_pynia_models_fetched(provider_id, model_ids)

        def _clear_thread_ref() -> None:
            dialog = dialog_ref()
            if dialog is not None and widget_is_valid(dialog):
                dialog._clear_pynia_model_thread()

        thread.started.connect(worker.run)
        worker.done.connect(_on_models_fetched)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(_clear_thread_ref)
        adopted = False
        if main_window is not None and hasattr(main_window, "_adopt_background_thread"):
            adopted = main_window._adopt_background_thread(thread, worker)
        if not adopted:
            thread.finished.connect(thread.deleteLater)
        self._pynia_model_thread = thread
        self._pynia_model_worker = worker
        thread.start()

    def _clear_pynia_model_thread(self):
        self._pynia_model_thread = None
        self._pynia_model_worker = None

    def _stop_pynia_model_thread(self) -> None:
        thread = self._pynia_model_thread
        worker = self._pynia_model_worker
        if thread is None:
            return
        self._pynia_model_thread = None
        self._pynia_model_worker = None
        from src.utils.qt_threading import detach_qthread

        detach_qthread(thread, worker)

    def closeEvent(self, event):
        self._stop_pynia_model_thread()
        try:
            self._notification_delivery_service.delivery_succeeded.disconnect(
                self._on_notification_delivery_success
            )
            self._notification_delivery_service.delivery_failed.disconnect(
                self._on_notification_delivery_failure
            )
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)

    def _on_pynia_models_fetched(self, pid: str, model_ids: list):
        self._pynia_model_cache[pid] = list(model_ids or [])
        # Repopulate only if the user is still looking at this connector.
        if hasattr(self, "_pynia_provider_combo") and self._current_pynia_connector_id() == pid:
            self._load_pynia_completion_model()

    def _save_pynia_completion_model(self):
        if not hasattr(self, "_pynia_completion_model_combo"):
            return
        pid = self._current_pynia_connector_id()
        self._pynia_settings.set_completion_model(
            pid, self._pynia_completion_model_combo.currentText().strip()
        )

    def _persist_pynia_connector_settings(self, *, emit_live_update: bool = True) -> bool:
        """Save the active API connector token/URL from the form (no-op for Copilot)."""
        from src.services.pynia import set_provider_secret
        from src.services.pynia.types import PROVIDERS

        if not hasattr(self, "_pynia_provider_combo"):
            return False
        pid = self._current_pynia_connector_id()
        info = PROVIDERS.get(pid)
        if not info or info.auth_kind != "api_token":
            if emit_live_update and pid == "copilot":
                self._pynia_settings.set_active_provider("copilot")
                self.pynia_connector_changed.emit("copilot")
            return False

        token = self._pynia_token_edit.text().strip()
        set_provider_secret(pid, token)
        self._pynia_settings.set_base_url(pid, self._pynia_base_url_edit.text().strip())
        self._save_pynia_completion_model()
        if token:
            self._pynia_settings.on_token_authenticated(pid, pid)
        else:
            self._pynia_settings.on_logout(pid)
        self._pynia_settings.set_active_provider(pid)
        self._pynia_model_cache.pop(pid, None)
        if emit_live_update:
            self._fetch_pynia_models(pid)
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(0, lambda p=pid: self.pynia_connector_changed.emit(p))
        return bool(token)

    def _on_pynia_save_token(self):
        saved = self._persist_pynia_connector_settings(emit_live_update=True)
        from src.services.ai_autocomplete_circuit_breaker import reset_ai_autocomplete_circuit_breaker

        reset_ai_autocomplete_circuit_breaker()
        if saved:
            self._pynia_status_label.setText(S.pynia.verify_ok if hasattr(S, "pynia") else "Saved.")
        self._refresh_pynia_autocomplete_status()

    def _on_pynia_verify_token(self):
        from PyQt6.QtCore import QThread
        from src.services.pynia.providers.token_worker import TokenAgentWorker
        from src.services.pynia.types import ProviderId

        pid: ProviderId = self._current_pynia_connector_id()
        if not self._persist_pynia_connector_settings(emit_live_update=False):
            show_danger(
                self,
                getattr(S.pynia, "verify_failed_title", "Verification failed"),
                getattr(S.pynia, "token_required_message", "API token required."),
            )
            return

        verifying = getattr(S.pynia, "verifying", "Verifying…") if hasattr(S, "pynia") else "Verifying…"
        self._pynia_status_label.setText(verifying)
        self._pynia_verify_btn.setEnabled(False)

        thread = QThread()
        thread.setObjectName("PyniaVerify")
        worker = TokenAgentWorker(pid)
        worker.moveToThread(thread)

        dialog_ref = weakref.ref(self)

        def _ok() -> None:
            dialog = dialog_ref()
            if dialog is None or not widget_is_valid(dialog):
                return
            dialog._pynia_verify_btn.setEnabled(True)
            template = S.pynia.verify_ok if hasattr(S, "pynia") else "OK"
            dialog._pynia_status_label.setText(template)
            title = (
                getattr(S.pynia, "verify_ok_title", None)
                or getattr(S.pynia, "verify_ok", "Connection verified")
            )
            detail = getattr(
                S.pynia,
                "verify_ok_detail",
                "Your API token is valid and the connector is ready to use.",
            )
            show_success(dialog, title, detail)
            dialog.pynia_connector_changed.emit(pid)

        def _fail(msg: str) -> None:
            dialog = dialog_ref()
            if dialog is None or not widget_is_valid(dialog):
                return
            dialog._pynia_verify_btn.setEnabled(True)
            template = S.pynia.verify_failed if hasattr(S, "pynia") else "Failed: {error}"
            dialog._pynia_status_label.setText(template.format(error=msg))
            show_danger(
                dialog,
                getattr(S.pynia, "verify_failed_title", "Verification failed"),
                template.format(error=msg),
            )

        thread.started.connect(worker.run_verify)
        worker.auth_ok.connect(_ok)
        worker.error.connect(_fail)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        main_window = self.window()
        adopted = False
        if main_window is not None and hasattr(main_window, "_adopt_background_thread"):
            adopted = main_window._adopt_background_thread(thread, worker)
        if not adopted:
            thread.finished.connect(thread.deleteLater)
        thread.start()

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
        """Handle the GitHub Copilot sign in/out button.

        Routes through the Pynia auth service (which wraps the live agent) and
        makes Copilot the active connector first — otherwise login takes the
        API-token path and fails with "API token not configured".
        """
        from src.services.pynia import get_pynia_auth_service

        auth_service = get_pynia_auth_service()
        settings = self._copilot_settings
        signed_in = settings.chat_was_authenticated and not settings.chat_user_logged_out

        # Switch the live agent to the Copilot connector for both login & logout.
        self._pynia_settings.set_active_provider("copilot")
        self.pynia_connector_changed.emit("copilot")

        if signed_in:
            auth_service.logout_chat()
            self.copilot_chat_logout_requested.emit()  # Notify MainWindow
        else:
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

        self.notif_enabled_cb = LabeledToggleSwitch(
            S.settings.label_notifications_enabled,
            checked=settings.value("notifications/enabled", True, type=bool),
        )
        general_layout.addWidget(self.notif_enabled_cb)

        self.notif_sound_cb = LabeledToggleSwitch(
            S.settings.label_notifications_sound,
            checked=settings.value("notifications/sound", True, type=bool),
        )
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

    def _setup_variables_storage_tab(self):
        """Session DataFrame variables — auto-persist and disk usage."""
        colors = get_colors()
        input_style = self._get_input_style(colors)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        layout.setContentsMargins(4, 4, 4, 12)

        from src.core.session_result_storage import (
            DEFAULT_MAX_SIZE_MB,
            format_storage_size,
            get_session_result_max_size_mb,
            is_session_result_restore_enabled,
        )

        policy_card, policy_layout = self._make_section_card(
            S.settings.section_variables_storage if hasattr(S.settings, "section_variables_storage")
            else "VARIABLE PERSISTENCE",
            colors,
        )

        self.session_results_restore_cb = LabeledToggleSwitch(
            S.settings.label_session_results_restore,
            checked=is_session_result_restore_enabled(),
        )
        policy_layout.addWidget(self.session_results_restore_cb)
        policy_layout.addWidget(self._make_hint(S.settings.session_results_restore_warning, colors))

        self.session_results_max_mb_spin = QSpinBox()
        self.session_results_max_mb_spin.setRange(1, 10000)
        self.session_results_max_mb_spin.setSingleStep(10)
        self.session_results_max_mb_spin.setValue(get_session_result_max_size_mb() or DEFAULT_MAX_SIZE_MB)
        self.session_results_max_mb_spin.setMinimumWidth(120)
        self.session_results_max_mb_spin.setStyleSheet(input_style)
        self.session_results_max_mb_spin.setEnabled(self.session_results_restore_cb.isChecked())
        policy_layout.addLayout(
            self._make_field_row(
                S.settings.label_session_results_max_mb,
                self.session_results_max_mb_spin,
                colors,
                label_width=220,
            )
        )
        policy_layout.addWidget(self._make_hint(S.settings.session_results_max_mb_hint, colors))
        self.session_results_restore_cb.toggled.connect(self.session_results_max_mb_spin.setEnabled)
        layout.addWidget(policy_card)

        usage_card, usage_layout = self._make_section_card(
            S.settings.section_variables_disk_usage if hasattr(S.settings, "section_variables_disk_usage")
            else "DISK USAGE",
            colors,
        )

        self._vars_storage_total_label = QLabel()
        self._vars_storage_total_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 12px; font-weight: 600;"
        )
        usage_layout.addWidget(self._vars_storage_total_label)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self._vars_storage_refresh_btn = QPushButton(
            S.settings.btn_refresh_variables_storage if hasattr(S.settings, "btn_refresh_variables_storage")
            else "Refresh"
        )
        self._vars_storage_refresh_btn.clicked.connect(self._refresh_variables_storage_inventory)
        refresh_row.addWidget(self._vars_storage_refresh_btn)
        usage_layout.addLayout(refresh_row)

        self._vars_storage_table = QTableWidget()
        self._vars_storage_table.setColumnCount(4)
        header_ns = getattr(S.settings, "variables_storage_headers", None)
        def _storage_header(key: str, default: str) -> str:
            if header_ns is None:
                return default
            return getattr(header_ns, key, default)

        self._vars_storage_table.setHorizontalHeaderLabels([
            _storage_header("session", "Session"),
            _storage_header("session_id", "ID"),
            _storage_header("variables", "Variables"),
            _storage_header("size", "Size"),
        ])
        self._vars_storage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._vars_storage_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._vars_storage_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._vars_storage_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._vars_storage_table.verticalHeader().setVisible(False)
        self._vars_storage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._vars_storage_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._vars_storage_table.setAlternatingRowColors(True)
        usage_layout.addWidget(self._vars_storage_table)

        from src.core.session_result_storage import get_session_snapshots_root

        usage_layout.addWidget(
            self._make_hint(
                S.settings.variables_storage_disk_hint.format(
                    path=str(get_session_snapshots_root()),
                ),
                colors,
            )
        )
        layout.addWidget(usage_card)
        layout.addStretch()

        tab_title = (
            S.settings.tab_variables_storage if hasattr(S.settings, "tab_variables_storage")
            else "Variables"
        )
        self.tabs.addTab(self._wrap_scroll_tab(page), tab_title)
        self._refresh_variables_storage_inventory()

    def _refresh_variables_storage_inventory(self):
        from src.core.session_result_storage import (
            format_storage_size,
            get_total_storage_bytes,
            list_session_snapshots,
        )

        if not hasattr(self, "_vars_storage_table"):
            return

        entries = list_session_snapshots()
        total_bytes = get_total_storage_bytes()
        self._vars_storage_total_label.setText(
            S.settings.variables_storage_total.format(size=format_storage_size(total_bytes))
        )

        session_titles: dict[str, str] = {}
        parent = self.parent()
        if parent is not None and hasattr(parent, "session_manager"):
            for session in parent.session_manager.sessions:
                session_titles[session.session_id] = session.title

        self._vars_storage_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            session_id = str(entry.get("session_id", ""))
            title = session_titles.get(session_id, session_id)
            self._vars_storage_table.setItem(row, 0, QTableWidgetItem(title))
            self._vars_storage_table.setItem(row, 1, QTableWidgetItem(session_id))
            self._vars_storage_table.setItem(
                row, 2, QTableWidgetItem(str(entry.get("variable_count", 0)))
            )
            self._vars_storage_table.setItem(
                row, 3,
                QTableWidgetItem(format_storage_size(int(entry.get("size_bytes", 0)))),
            )

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
        """Refresh transport hints from the form (avoid slow keyring reads on save)."""
        telegram_ready = bool(
            self.notif_telegram_chat_id.text().strip()
            and self.notif_telegram_token.text().strip()
        )
        email_ready = bool(
            self.notif_email_host.text().strip()
            and self.notif_email_username.text().strip()
            and self.notif_email_password.text().strip()
            and self.notif_email_from.text().strip()
            and self.notif_email_to.text().strip()
        )
        self.notif_telegram_status.setText(
            S.settings.notification_telegram_status_ready
            if telegram_ready
            else S.settings.notification_telegram_status_missing
        )
        self.notif_email_status.setText(
            S.settings.notification_email_status_ready
            if email_ready
            else S.settings.notification_email_status_missing
        )

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
            show_warning(self, S.dialogs.warning, S.settings.notification_test_failure.format(channel=S.settings.notification_channel_telegram, error=S.settings.notification_telegram_status_missing))
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
            show_warning(self, S.dialogs.warning, S.settings.notification_test_failure.format(channel=S.settings.notification_channel_email, error=S.settings.notification_email_status_missing))
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
        show_success(
            self,
            S.settings.success_title,
            S.settings.notification_test_success.format(channel=channel_label),
        )

    def _on_notification_delivery_failure(self, channel: str, error_text: str):
        if self._pending_notification_test != channel:
            return

        self._pending_notification_test = None
        channel_label = S.settings.notification_channel_telegram if channel == "telegram" else S.settings.notification_channel_email
        show_warning(
            self,
            S.dialogs.warning,
            S.settings.notification_test_failure.format(channel=channel_label, error=error_text),
        )

    def _setup_workspace_tab(self):
        """Setup Workspace tab for workspace/profile management."""
        from src.core.workspace_service import get_workspace_service
        colors = get_colors()

        page = QWidget()
        workspace_layout = QVBoxLayout(page)
        workspace_layout.setSpacing(14)
        workspace_layout.setContentsMargins(4, 4, 4, 12)

        self._workspace_service = get_workspace_service()

        # --- Current workspace section ---
        current_group, current_layout = self._make_section_card(
            S.settings.section_workspace_current if hasattr(S.settings, 'section_workspace_current')
            else "CURRENT WORKSPACE",
            colors,
        )
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
        saved_group, saved_layout = self._make_section_card(
            S.settings.section_workspaces if hasattr(S.settings, 'section_workspaces')
            else "SAVED WORKSPACES",
            colors,
        )
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

        add_label = S.settings.workspace_add if hasattr(S.settings, "workspace_add") else "Add..."
        add_btn = self._make_workspace_action_button(add_label, colors, variant="primary")
        add_btn.clicked.connect(self._on_add_workspace)
        btn_row.addWidget(add_btn)

        dup_label = (
            S.settings.workspace_duplicate if hasattr(S.settings, "workspace_duplicate") else "Duplicate..."
        )
        duplicate_btn = self._make_workspace_action_button(dup_label, colors, variant="secondary")
        duplicate_btn.clicked.connect(self._on_duplicate_workspace)
        btn_row.addWidget(duplicate_btn)

        remove_label = S.settings.workspace_remove if hasattr(S.settings, "workspace_remove") else "Remove"
        self._remove_btn = self._make_workspace_action_button(remove_label, colors, variant="muted")
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
        self.tabs.addTab(self._wrap_scroll_tab(page), tab_title)
    
    def _workspace_button_stylesheet(self, colors, variant: str) -> str:
        if variant == "primary":
            return f"""
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
                QPushButton:disabled {{
                    background-color: {colors.bg_tertiary};
                    color: {colors.text_tertiary};
                }}
            """
        if variant == "danger":
            return f"""
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
                QPushButton:disabled {{
                    background-color: {colors.bg_tertiary};
                    color: {colors.text_tertiary};
                    border: 1px solid {colors.border_muted};
                }}
            """
        return f"""
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
            QPushButton:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 1px solid {colors.border_muted};
            }}
        """

    def _make_workspace_action_button(self, label: str, colors, *, variant: str = "secondary") -> QPushButton:
        """Fixed-size toolbar button so disabled Remove does not stretch in the row."""
        from PyQt6.QtWidgets import QSizePolicy

        btn = QPushButton(label)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        text_w = btn.fontMetrics().horizontalAdvance(label)
        btn.setFixedSize(max(72, text_w + 24), 28)
        btn.setStyleSheet(self._workspace_button_stylesheet(colors, variant))
        return btn

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
        
        label = (
            S.settings.workspace_remove if hasattr(S.settings, "workspace_remove") else "Remove"
        )
        text_w = self._remove_btn.fontMetrics().horizontalAdvance(label)
        self._remove_btn.setFixedSize(max(72, text_w + 24), 28)

        if can_remove:
            self._remove_btn.setEnabled(True)
            self._remove_btn.setStyleSheet(self._workspace_button_stylesheet(colors, "danger"))
        else:
            self._remove_btn.setEnabled(False)
            self._remove_btn.setStyleSheet(self._workspace_button_stylesheet(colors, "muted"))
    
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
        if not confirm_yes_no(
            self,
            S.settings.workspace_remove_title if hasattr(S.settings, 'workspace_remove_title')
            else "Remove Workspace",
            (S.settings.workspace_remove_confirm if hasattr(S.settings, 'workspace_remove_confirm')
             else f"Are you sure you want to permanently delete this workspace and all its files?\n\n{path}\n\nThis action cannot be undone."),
        ):
            return
        
        try:
            # Remove from workspace list first
            self._workspace_service.remove_workspace(path)
            
            # Delete the folder
            if path.exists():
                shutil.rmtree(path)
            
            self._refresh_workspace_list()
            
            show_success(
                self,
                "Success",
                S.settings.workspace_remove_success if hasattr(S.settings, 'workspace_remove_success')
                else "Workspace removed successfully.",
            )
        except Exception as e:
            show_danger(
                self,
                "Error",
                (S.settings.workspace_remove_error if hasattr(S.settings, 'workspace_remove_error')
                 else f"Failed to remove workspace:\n{str(e)}"),
            )

    def _on_duplicate_workspace(self):
        """Handle duplicate workspace button click."""
        from PyQt6.QtWidgets import QFileDialog, QApplication
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
            show_warning(
                self,
                "Error",
                S.settings.workspace_duplicate_same_folder if hasattr(S.settings, 'workspace_duplicate_same_folder')
                else "Destination folder cannot be the same as source.",
            )
            return
        
        # Check if destination already has files
        if any(dest_path.iterdir()) if dest_path.exists() else False:
            if not confirm_yes_no(
                self,
                "Confirm",
                S.settings.workspace_duplicate_not_empty if hasattr(S.settings, 'workspace_duplicate_not_empty')
                else "Destination folder is not empty. Files may be overwritten. Continue?",
            ):
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
                show_success(
                    self,
                    "Success",
                    S.settings.workspace_duplicate_success if hasattr(S.settings, 'workspace_duplicate_success')
                    else f"Workspace duplicated successfully to:\n{dest_path}",
                )
        except Exception as e:
            QApplication.restoreOverrideCursor()
            show_danger(
                self,
                "Error",
                S.settings.workspace_duplicate_error if hasattr(S.settings, 'workspace_duplicate_error')
                else f"Failed to duplicate workspace:\n{str(e)}",
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

        # Surface any pre-existing conflicts (e.g. from an old saved config)
        self._highlight_shortcut_conflicts()

    def _highlight_shortcut_conflicts(self) -> list:
        """Flag rows whose shortcut is bound to more than one action.

        Returns a list of (shortcut, [action_names]) for the conflicts found.
        The per-edit check prevents new conflicts, but a stale shortcuts.json
        could still carry duplicates — this makes them visible (red) instead
        of silently ambiguous.
        """
        from collections import defaultdict

        colors = get_colors()
        normal = QBrush(QColor(colors.text_primary))
        danger = QBrush(QColor(colors.danger))

        by_key: dict[str, list[int]] = defaultdict(list)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            key = (item.text() or "").strip() if item else ""
            if key:
                by_key[key].append(r)

        conflicts = []
        for r in range(self.table.rowCount()):
            sc_item = self.table.item(r, 1)
            ac_item = self.table.item(r, 0)
            if sc_item is None:
                continue
            rows = by_key.get((sc_item.text() or "").strip(), [])
            if len(rows) > 1:
                sc_item.setForeground(danger)
                others = ", ".join(
                    self.table.item(x, 0).text() for x in rows if x != r
                )
                tip = S.settings.conflict_msg.format(
                    shortcut=sc_item.text(), action=others
                )
                sc_item.setToolTip(tip)
                if ac_item is not None:
                    ac_item.setToolTip(tip)
            else:
                sc_item.setForeground(normal)
                sc_item.setToolTip("")
                if ac_item is not None:
                    ac_item.setToolTip("")

        seen = set()
        for key, rows in by_key.items():
            if len(rows) > 1 and key not in seen:
                seen.add(key)
                conflicts.append((key, [self.table.item(x, 0).text() for x in rows]))
        return conflicts

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
                        show_warning(
                            self,
                            S.settings.conflict_title,
                            S.settings.conflict_msg.format(
                                shortcut=new_sequence, action=other_action_name
                            ),
                        )
                        return

                self.table.item(row, 1).setText(new_sequence)
                self._highlight_shortcut_conflicts()

    def _save_all(self):
        """Saves all settings (language + shortcuts)"""
        # Save language preference
        selected_lang = self.lang_combo.currentData()
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("language", selected_lang)

        # Save grid display row limit
        settings.setValue("grid/display_row_limit", self.grid_row_limit_spin.value())
        settings.setValue("connections/idle_timeout_sec", self.idle_timeout_spin.value())

        if hasattr(self, "shared_delimiter_edit"):
            set_shared_parameter_delimiter(self.shared_delimiter_edit.text())

        if hasattr(self, "session_results_restore_cb"):
            from src.core.session_result_storage import (
                set_session_result_max_size_mb,
                set_session_result_restore_enabled,
            )

            set_session_result_restore_enabled(self.session_results_restore_cb.isChecked())
            set_session_result_max_size_mb(self.session_results_max_mb_spin.value())

        # Save notification settings
        settings.setValue("notifications/enabled", self.notif_enabled_cb.isChecked())
        settings.setValue("notifications/sound", self.notif_sound_cb.isChecked())
        settings.setValue("notifications/success_title", self.notif_success_title.text())
        settings.setValue("notifications/success_message", self.notif_success_msg.text())
        settings.setValue("notifications/error_title", self.notif_error_title.text())
        settings.setValue("notifications/error_message", self.notif_error_msg.text())
        self._persist_notification_transport_settings()

        if hasattr(self, "_pynia_autocomplete_cb"):
            from src.services.pynia.settings import get_pynia_settings

            get_pynia_settings().set_autocomplete_enabled(
                self._pynia_autocomplete_cb.isChecked()
            )
            self._save_pynia_completion_model()
            from src.services.ai_autocomplete_circuit_breaker import reset_ai_autocomplete_circuit_breaker

            reset_ai_autocomplete_circuit_breaker()
            # Persist token/settings only — live connector switch runs after dialog closes.
            self._persist_pynia_connector_settings(emit_live_update=False)

        # Surface conflicting shortcuts before persisting (e.g. duplicates
        # carried over from an old config). Let the user go back and fix them.
        conflicts = self._highlight_shortcut_conflicts()
        if conflicts:
            details = "\n".join(
                f"• {key} → {', '.join(actions)}" for key, actions in conflicts
            )
            if not confirm_yes_no(
                self,
                S.settings.conflict_title,
                f"{details}\n\n{S.settings.conflict_save_anyway}"
                if hasattr(S.settings, "conflict_save_anyway")
                else f"{details}\n\nSave anyway?",
            ):
                return

        # Save shortcuts (one disk write)
        shortcut_updates = {}
        for row in range(self.table.rowCount()):
            shortcut_item = self.table.item(row, 1)
            action = shortcut_item.data(Qt.ItemDataRole.UserRole)
            shortcut_updates[action] = shortcut_item.text()
        self.shortcut_manager.update_shortcuts(shortcut_updates)

        needs_restart = selected_lang != self._original_language
        pynia_pid = ""
        if hasattr(self, "_pynia_provider_combo"):
            pynia_pid = self._current_pynia_connector_id()
        parent = self.parent()

        self.shortcuts_changed.emit()
        if pynia_pid:
            self.pynia_connector_changed.emit(pynia_pid)

        self.accept()
        SettingsDialog._schedule_post_save_ui(parent, needs_restart=needs_restart)

    @staticmethod
    def _schedule_post_save_ui(parent, *, needs_restart: bool) -> None:
        """Toast and optional restart prompt after the dialog has closed."""
        from PyQt6.QtCore import QTimer

        def _toast() -> None:
            try:
                from src.ui.components.toast_notification import ToastManager

                ToastManager.notify(
                    S.settings.success_title,
                    S.settings.success_msg,
                    success=True,
                )
            except Exception:
                pass

        QTimer.singleShot(0, _toast)
        if needs_restart and parent is not None:
            QTimer.singleShot(150, lambda: SettingsDialog._prompt_language_restart(parent))

    @staticmethod
    def _prompt_language_restart(parent) -> None:
        if confirm_yes_no(
            parent,
            S.dialogs.language_restart_title,
            S.dialogs.language_restart_msg,
        ):
            import os
            import sys

            from PyQt6.QtWidgets import QApplication

            QApplication.quit()
            os.execl(sys.executable, sys.executable, *sys.argv)

    def _reset_defaults(self):
        """Restores default shortcuts"""
        from src.design_system.message_box import ask_yes_no

        if ask_yes_no(
            self,
            S.settings.confirm_restore_title,
            S.settings.confirm_restore_msg,
        ):
            self.shortcut_manager.reset_to_defaults()
            self._load_shortcuts()
