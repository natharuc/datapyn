"""
Unified dialog for creating and editing connections
"""

import logging

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QFormLayout,
    QFrame,
    QLabel,
    QColorDialog,
    QScrollArea,
    QWidget,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor

from src.database import DatabaseConnector
from src.database.database_connector import (
    SQLSERVER_AUTH_ENTRA_MFA,
    SQLSERVER_AUTH_SQL_PASSWORD,
    SQLSERVER_AUTH_WINDOWS,
    _is_unicode_decode_error,
    _safe_exception_text,
    normalize_sqlserver_auth_mode,
)
from src.core.theme_manager import ThemeManager
from src.language import S
from src.design_system.tokens import get_colors

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


class ConnectionTestWorker(QThread):
    """Worker to test connection in background"""

    finished = pyqtSignal(bool, str)  # success, message

    def __init__(
        self,
        db_type,
        host,
        port,
        database,
        username,
        password,
        use_windows_auth=False,
        sqlserver_auth_mode="",
        trust_server_certificate=True,
        http_path="",
        schema="",
    ):
        super().__init__()
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth
        self.sqlserver_auth_mode = sqlserver_auth_mode
        self.trust_server_certificate = trust_server_certificate
        self.http_path = http_path
        self.schema = schema

    def run(self):
        try:
            connector = DatabaseConnector()

            kwargs = {}
            if self.db_type == "sqlserver":
                kwargs["sqlserver_auth_mode"] = normalize_sqlserver_auth_mode(
                    self.sqlserver_auth_mode,
                    self.use_windows_auth,
                )
            if self.use_windows_auth:
                kwargs["use_windows_auth"] = True
            kwargs["trust_server_certificate"] = self.trust_server_certificate
            if self.http_path:
                kwargs["http_path"] = self.http_path
            if self.schema:
                kwargs["schema"] = self.schema

            connector.connect(
                db_type=self.db_type,
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                **kwargs,
            )

            connector.disconnect()
            self.finished.emit(True, S.connection_edit.test_success)

        except Exception as e:
            self.finished.emit(False, S.connection_edit.test_error.format(error=_format_connection_test_error(e)))


def _format_connection_test_error(error: Exception) -> str:
    if _is_unicode_decode_error(error):
        return S.connection_edit.error_postgresql_encoding
    return _safe_exception_text(error)


class ConnectionEditDialog(QDialog):
    """Unified dialog for creating and editing connections"""

    def __init__(
        self,
        connection_name: str = None,
        config: dict = None,
        groups: dict = None,
        theme_manager: ThemeManager = None,
        parent=None,
    ):
        super().__init__(parent)
        self.connection_name = connection_name or ""
        self.config = config or {}
        self.groups = groups or {}
        self.theme_manager = theme_manager or ThemeManager()
        self.selected_color = self.config.get("color", "")
        self.is_new = connection_name is None or connection_name == ""
        self.connector = None  # For connection test

        self._frameless_title = (
            S.connection_edit.title_new
            if self.is_new
            else S.connection_edit.title_edit.format(name=connection_name)
        )
        self.setWindowTitle(self._frameless_title)
        self.resize(520, 720)

        self._setup_ui()
        if not self.is_new:
            self._load_config()

    def _populate_db_type_combo(self) -> None:
        """Fill database type combo with branded SVG icons and readable labels."""
        from src.design_system.tokens import apply_combobox_style
        from src.ui.components.connection_panel import get_db_icon

        db_types = (
            ("sqlserver", S.connection_edit.combo_sqlserver),
            ("mysql", S.connection_edit.combo_mysql),
            ("mariadb", S.connection_edit.combo_mariadb),
            ("postgresql", S.connection_edit.combo_postgresql),
            ("databricks", getattr(S.connection_edit, "combo_databricks", "Databricks")),
        )
        icon_size = 18
        self.cmb_type.clear()
        for db_id, label in db_types:
            self.cmb_type.addItem(
                get_db_icon(db_id, size=icon_size), label, db_id
            )
        apply_combobox_style(self.cmb_type, icon_size=icon_size, list_item_height=48)

    def _current_db_type(self) -> str:
        data = self.cmb_type.currentData()
        if data:
            return str(data)
        return (self.cmb_type.currentText() or "sqlserver").strip().lower()

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

    def _setup_ui(self):
        """Sets up the UI"""
        from src.design_system.frameless_dialog import install_frameless_shell

        layout = install_frameless_shell(
            self,
            self._frameless_title,
            min_width=520,
            min_height=480,
            content_margins=(16, 12, 16, 12),
            content_spacing=10,
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(12)

        # Basic information group
        basic_group = QFrame()
        basic_group.setObjectName("sectionPanel")
        basic_group.setFrameShape(QFrame.Shape.NoFrame)
        basic_group_layout = QVBoxLayout(basic_group)
        basic_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        colors = get_colors()
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.database-cog", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_edit.section_connection_info)
        title.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {colors.text_secondary};")
        header.addWidget(title)
        header.addStretch()
        basic_group_layout.addLayout(header)

        basic_layout = QFormLayout()
        self._configure_form(basic_layout)
        basic_group_layout.addLayout(basic_layout)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText(S.connection_edit.placeholder_name)
        basic_layout.addRow(S.connection_edit.label_name, self.txt_name)

        self.cmb_type = QComboBox()
        self._populate_db_type_combo()
        self.cmb_type.currentIndexChanged.connect(self._on_db_type_changed)
        basic_layout.addRow(S.connection_edit.label_db_type, self.cmb_type)

        self.txt_host = QLineEdit()
        self.txt_host.setPlaceholderText(S.connection_edit.placeholder_host)
        basic_layout.addRow(S.connection_edit.label_host, self.txt_host)

        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(1433)
        basic_layout.addRow(S.connection_edit.label_port, self.spin_port)

        self.txt_database = QLineEdit()
        self.txt_database.setPlaceholderText(S.connection_edit.placeholder_database)
        self.lbl_database = QLabel(S.connection_edit.label_database)
        basic_layout.addRow(self.lbl_database, self.txt_database)

        self.txt_schema = QLineEdit()
        self.txt_schema.setPlaceholderText(S.connection_edit.placeholder_schema)
        self.lbl_schema = QLabel(S.connection_edit.label_schema)
        basic_layout.addRow(self.lbl_schema, self.txt_schema)
        self.txt_schema.hide()
        self.lbl_schema.hide()

        # HTTP Path (Databricks only)
        self.txt_http_path = QLineEdit()
        self.txt_http_path.setPlaceholderText("/sql/1.0/warehouses/xxx or /sql/protocolv1/o/xxx/xxx-xxx")
        self.lbl_http_path = QLabel("HTTP Path:")
        basic_layout.addRow(self.lbl_http_path, self.txt_http_path)

        scroll_layout.addWidget(basic_group)

        # Authentication group
        auth_group = QFrame()
        auth_group.setObjectName("sectionPanel")
        auth_group.setFrameShape(QFrame.Shape.NoFrame)
        auth_group_layout = QVBoxLayout(auth_group)
        auth_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header (colors already imported at top of file)
        
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.lock", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_edit.section_authentication)
        title.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {colors.text_tertiary};")
        header.addWidget(title)
        header.addStretch()
        auth_group_layout.addLayout(header)

        auth_layout = QFormLayout()
        self._configure_form(auth_layout)
        auth_group_layout.addLayout(auth_layout)

        self.chk_windows_auth = QCheckBox(S.connection_edit.checkbox_windows_auth)
        self.chk_windows_auth.stateChanged.connect(self._toggle_windows_auth)
        self.chk_windows_auth.hide()
        auth_layout.addRow(self.chk_windows_auth)

        self.cmb_sqlserver_auth = QComboBox()
        self.cmb_sqlserver_auth.addItem(S.connection_edit.combo_auth_sql_password, SQLSERVER_AUTH_SQL_PASSWORD)
        self.cmb_sqlserver_auth.addItem(S.connection_edit.combo_auth_windows, SQLSERVER_AUTH_WINDOWS)
        self.cmb_sqlserver_auth.addItem(S.connection_edit.combo_auth_entra_mfa, SQLSERVER_AUTH_ENTRA_MFA)
        self.cmb_sqlserver_auth.currentIndexChanged.connect(self._on_sqlserver_auth_changed)
        self.lbl_sqlserver_auth = QLabel(S.connection_edit.label_sqlserver_auth)
        auth_layout.addRow(self.lbl_sqlserver_auth, self.cmb_sqlserver_auth)

        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText(S.connection_edit.placeholder_username)
        self.lbl_username = QLabel(S.connection_edit.label_username)
        auth_layout.addRow(self.lbl_username, self.txt_username)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText(S.connection_edit.placeholder_password)
        self.lbl_password = QLabel(S.connection_edit.label_password)
        auth_layout.addRow(self.lbl_password, self.txt_password)

        self.chk_save_password = QCheckBox(S.connection_edit.checkbox_save_password)
        auth_layout.addRow(self.chk_save_password)

        # SSL option (SQL Server only)
        self.chk_trust_cert = QCheckBox(S.connection_edit.checkbox_trust_cert)
        self.chk_trust_cert.setChecked(False)  # Default: don't trust (more secure)
        self.chk_trust_cert.setToolTip(S.connection_edit.tooltip_trust_cert)
        auth_layout.addRow(self.chk_trust_cert)

        scroll_layout.addWidget(auth_group)

        # Organization group
        org_group = QFrame()
        org_group.setObjectName("sectionPanel")
        org_group.setFrameShape(QFrame.Shape.NoFrame)
        org_group_layout = QVBoxLayout(org_group)
        org_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.folder-cog", color=colors.info).pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel(S.connection_edit.section_organization)
        title.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {colors.text_tertiary};")
        header.addWidget(title)
        header.addStretch()
        org_group_layout.addLayout(header)

        org_layout = QFormLayout()
        self._configure_form(org_layout)
        org_group_layout.addLayout(org_layout)

        self.cmb_group = QComboBox()
        self.cmb_group.addItem(S.connection_edit.combo_no_group, "")
        for group_name in self.groups.keys():
            self.cmb_group.addItem(group_name, group_name)
        org_layout.addRow(S.connection_edit.label_group, self.cmb_group)

        # Color
        color_layout = QHBoxLayout()
        color_layout.setSpacing(10)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_color = QLabel(S.connection_edit.combo_none_color)
        self.lbl_color.setMinimumWidth(72)
        self.lbl_color.setMaximumWidth(120)
        self.lbl_color.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.lbl_color.setStyleSheet(
            f"border: 1px solid {colors.border_default}; padding: 6px 8px;"
            f" border-radius: 4px; color: {colors.text_secondary};"
        )
        from src.design_system.button import SecondaryButton

        btn_choose_color = SecondaryButton(S.connection_edit.btn_choose_color, size="sm")
        if HAS_QTAWESOME:
            btn_choose_color.setIcon(qta.icon("mdi.palette", color="white"))
        btn_choose_color.clicked.connect(self._choose_color)
        btn_clear_color = SecondaryButton(S.connection_edit.btn_clear_color, size="sm")
        btn_clear_color.clicked.connect(self._clear_color)
        color_layout.addWidget(self.lbl_color, 1)
        color_layout.addWidget(btn_choose_color, 0)
        color_layout.addWidget(btn_clear_color, 0)
        org_layout.addRow(S.connection_edit.label_color, color_layout)

        scroll_layout.addWidget(org_group)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        from src.design_system.button import PrimaryButton, SecondaryButton

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        btn_test = SecondaryButton(S.connection_edit.btn_test_connection, size="sm")
        if HAS_QTAWESOME:
            btn_test.setIcon(qta.icon("mdi.lan-connect", color="white"))
        btn_test.clicked.connect(self._test_connection)
        buttons_layout.addWidget(btn_test)

        buttons_layout.addStretch()

        btn_save = PrimaryButton(S.connection_edit.btn_save, size="sm")
        if HAS_QTAWESOME:
            btn_save.setIcon(qta.icon("mdi.content-save", color="white"))
        btn_save.clicked.connect(self._on_save)
        buttons_layout.addWidget(btn_save)

        btn_cancel = SecondaryButton(S.connection_edit.btn_cancel, size="sm")
        btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(btn_cancel)

        layout.addLayout(buttons_layout)

        from src.design_system.tokens import polish_combobox_popups

        polish_combobox_popups(self)

        # Initial adjustments
        self._toggle_windows_auth_visibility()

    def _load_config(self):
        """Loads current configuration"""
        self.txt_name.setText(self.connection_name)

        db_type = self.config.get("db_type", "sqlserver")
        index = self.cmb_type.findData(db_type)
        if index >= 0:
            self.cmb_type.setCurrentIndex(index)

        self.txt_host.setText(self.config.get("host", ""))
        self.spin_port.setValue(self.config.get("port", 1433))
        self.txt_database.setText(self.config.get("database", ""))

        # Databricks / PostgreSQL schema field
        self.txt_http_path.setText(self.config.get("http_path", ""))
        if db_type == "postgresql":
            self.txt_schema.setText(
                self.config.get("schema")
                or self.config.get("postgresql_schema")
                or "public"
            )
        else:
            self.txt_schema.setText(
                self.config.get("schema") or self.config.get("databricks_schema") or "default"
            )

        use_windows_auth = self.config.get("use_windows_auth", False)
        self.chk_windows_auth.setChecked(use_windows_auth)
        self._set_sqlserver_auth_mode(self.config.get("sqlserver_auth_mode", ""), use_windows_auth)

        # Trust Server Certificate (default: False for security)
        trust_cert = self.config.get("trust_server_certificate", False)
        self.chk_trust_cert.setChecked(trust_cert)

        self.txt_username.setText(self.config.get("username", ""))

        if "password" in self.config:
            self.txt_password.setText(self.config.get("password", ""))
            self.chk_save_password.setChecked(True)

        # Group
        group = self.config.get("group", "")
        index = self.cmb_group.findData(group)
        if index >= 0:
            self.cmb_group.setCurrentIndex(index)

        # Color
        if self.selected_color:
            self._update_color_label()

        self._toggle_windows_auth()
        self._toggle_windows_auth_visibility()

    def _on_db_type_changed(self):
        """When database type changes"""
        db_type = self._current_db_type()

        # Adjust default port
        default_ports = {"sqlserver": 1433, "mysql": 3306, "mariadb": 3306, "postgresql": 5432, "databricks": 443}
        self.spin_port.setValue(default_ports.get(db_type, 1433))

        self._toggle_windows_auth_visibility()

    def _on_sqlserver_auth_changed(self, _index=None):
        """Refresh auth-dependent UI when SQL Server auth mode changes."""
        self._toggle_windows_auth_visibility()

    def _current_sqlserver_auth_mode(self) -> str:
        """Return the normalized SQL Server auth mode for the dialog state."""
        return normalize_sqlserver_auth_mode(
            self.cmb_sqlserver_auth.currentData(),
            self.chk_windows_auth.isChecked(),
        )

    def _set_sqlserver_auth_mode(self, auth_mode: str, use_windows_auth: bool = False):
        """Apply a SQL Server auth mode to the combo box."""
        normalized = normalize_sqlserver_auth_mode(auth_mode, use_windows_auth)
        index = self.cmb_sqlserver_auth.findData(normalized)
        if index < 0:
            index = self.cmb_sqlserver_auth.findData(SQLSERVER_AUTH_SQL_PASSWORD)
        if index >= 0:
            self.cmb_sqlserver_auth.setCurrentIndex(index)

    def _toggle_windows_auth(self):
        """Toggle authentication fields"""
        db_type = self._current_db_type()
        auth_mode = self._current_sqlserver_auth_mode()
        is_windows_auth = db_type == "sqlserver" and auth_mode == SQLSERVER_AUTH_WINDOWS
        is_mfa_auth = db_type == "sqlserver" and auth_mode == SQLSERVER_AUTH_ENTRA_MFA

        self.chk_windows_auth.setChecked(is_windows_auth)
        self.txt_username.setEnabled(not is_windows_auth)
        self.txt_password.setEnabled(not is_windows_auth and not is_mfa_auth)
        self.chk_save_password.setEnabled(not is_windows_auth and not is_mfa_auth)
        if db_type == "sqlserver" and (is_windows_auth or is_mfa_auth):
            self.chk_save_password.setChecked(False)

    def _toggle_windows_auth_visibility(self):
        """Shows/hides Windows Auth and Trust Cert based on database type"""
        db_type = self._current_db_type()
        is_sqlserver = db_type == "sqlserver"
        is_databricks = db_type == "databricks"
        auth_mode = self._current_sqlserver_auth_mode()
        is_mfa_auth = is_sqlserver and auth_mode == SQLSERVER_AUTH_ENTRA_MFA
        
        self.chk_windows_auth.setVisible(False)
        self.lbl_sqlserver_auth.setVisible(is_sqlserver)
        self.cmb_sqlserver_auth.setVisible(is_sqlserver)
        self.chk_trust_cert.setVisible(is_sqlserver)
        if not is_sqlserver:
            self.chk_windows_auth.setChecked(False)
        
        # Databricks-specific fields
        is_postgresql = db_type == "postgresql"
        self.txt_http_path.setVisible(is_databricks)
        self.lbl_http_path.setVisible(is_databricks)
        # Schema is meaningful for Databricks (catalog schema) and PostgreSQL (search_path).
        self.txt_schema.setVisible(is_databricks or is_postgresql)
        self.lbl_schema.setVisible(is_databricks or is_postgresql)
        if is_databricks:
            self.lbl_database.setText(S.connection_edit.label_catalog)
            self.txt_database.setPlaceholderText(S.connection_edit.placeholder_catalog)
            self.txt_schema.setPlaceholderText(S.connection_edit.placeholder_schema)
            if not self.txt_schema.text().strip():
                self.txt_schema.setText("default")
        else:
            self.lbl_database.setText(S.connection_edit.label_database)
            self.txt_database.setPlaceholderText(S.connection_edit.placeholder_database)
            if is_postgresql:
                self.txt_schema.setPlaceholderText("public")
                if not self.txt_schema.text().strip():
                    self.txt_schema.setText("public")
            else:
                self.txt_schema.clear()
        
        # For Databricks, adjust username/password labels for token auth
        if is_databricks:
            self.txt_username.setEnabled(False)
            self.txt_username.setPlaceholderText("(not used - token auth)")
            self.lbl_username.setVisible(False)
            self.txt_username.setVisible(False)
            self.lbl_password.setText("Access Token (optional):")
            self.txt_password.setPlaceholderText("dapi... or leave empty for OAuth")
            self.chk_save_password.setText("Save token")
            self.chk_save_password.setChecked(True)  # Recommend saving token
        else:
            self.txt_username.setPlaceholderText(
                S.connection_edit.placeholder_username_mfa if is_mfa_auth else S.connection_edit.placeholder_username
            )
            self.lbl_username.setVisible(True)
            self.txt_username.setVisible(True)
            self.lbl_password.setText(S.connection_edit.label_password)
            self.txt_password.setPlaceholderText(
                S.connection_edit.placeholder_password_mfa if is_mfa_auth else S.connection_edit.placeholder_password
            )
            self.chk_save_password.setText(S.connection_edit.checkbox_save_password)
            self._toggle_windows_auth()

    def _choose_color(self):
        """Chooses color for the connection"""
        current_color = QColor(self.selected_color) if self.selected_color else QColor()
        color = QColorDialog.getColor(current_color, self, "Choose Color")

        if color.isValid():
            self.selected_color = color.name()
            self._update_color_label()

    def _clear_color(self):
        """Removes color"""
        self.selected_color = ""
        self.lbl_color.setText(S.connection_edit.combo_none_color)
        colors = get_colors()
        self.lbl_color.setStyleSheet(
            f"border: 1px solid {colors.border_default}; padding: 6px 8px;"
            f" border-radius: 4px; color: {colors.text_secondary};"
        )

    def _update_color_label(self):
        """Updates color label"""
        if self.selected_color:
            self.lbl_color.setText(self.selected_color)
            self.lbl_color.setStyleSheet(
                f"background-color: {self.selected_color}; border: 1px solid #555; padding: 3px; color: white;"
            )

    def _test_connection(self):
        """Tests the connection with current settings in background"""
        if not self._validate_inputs(require_name=False):
            return

        from src.design_system.app_dialogs import FramelessProgressDialog

        db_name = self.txt_database.text() or self.txt_host.text()
        self.loading_dialog = FramelessProgressDialog(
            self,
            S.connection_edit.dialog_testing_title,
            S.connection_edit.dialog_testing_msg.format(name=db_name),
            cancel_text=S.connection_edit.btn_cancel,
            on_cancel=self._cancel_test_connection,
        )
        self.loading_dialog.show()

        # Create and start worker
        self._test_cancelled = False
        current_type = self._current_db_type()
        http_path = self.txt_http_path.text() if current_type == "databricks" else ""
        schema = ""
        if current_type == "databricks":
            schema = self.txt_schema.text().strip() or "default"
        elif current_type == "postgresql":
            schema = self.txt_schema.text().strip() or "public"
        self.test_worker = ConnectionTestWorker(
            db_type=self._current_db_type(),
            host=self.txt_host.text(),
            port=self.spin_port.value(),
            database=self.txt_database.text(),
            username=self.txt_username.text(),
            password=self.txt_password.text(),
            use_windows_auth=self.chk_windows_auth.isChecked(),
            sqlserver_auth_mode=self._current_sqlserver_auth_mode(),
            trust_server_certificate=self.chk_trust_cert.isChecked(),
            http_path=http_path,
            schema=schema,
        )
        self.test_worker.finished.connect(self._on_test_finished)
        self.test_worker.start()

    def _cancel_test_connection(self):
        """Cancels the ongoing connection test"""
        self._test_cancelled = True
        if hasattr(self, 'test_worker') and self.test_worker.isRunning():
            self.test_worker.quit()
            if not self.test_worker.wait(2000):
                logger.warning(
                    "Connection test QThread did not stop after quit(); terminating as last resort"
                )
                self.test_worker.terminate()
                self.test_worker.wait(2000)

    def _on_test_finished(self, success: bool, message: str):
        """Callback when connection test finishes"""
        if self._test_cancelled:
            return  # Ignore result if cancelled

        self.loading_dialog.close()

        from src.design_system.app_dialogs import show_danger, show_success

        if success:
            show_success(self, S.dialogs.success, message)
        else:
            show_danger(self, S.dialogs.error, message)

    def _on_save(self):
        """Validates and saves"""
        if not self._validate_inputs(require_name=True):
            return

        self.accept()

    def _validate_inputs(self, require_name: bool) -> bool:
        """Validate connection fields before save/test."""
        from src.design_system.app_dialogs import show_warning

        if require_name and not self.txt_name.text().strip():
            show_warning(self, S.dialogs.warning, S.connection_edit.validation_name_required)
            return False

        if not self.txt_host.text().strip():
            show_warning(self, S.dialogs.warning, S.connection_edit.validation_host_required)
            return False

        return True

    def get_result(self):
        """Returns edited name and configuration"""
        name = self.txt_name.text().strip()
        db_type = self._current_db_type()
        sqlserver_auth_mode = self._current_sqlserver_auth_mode() if db_type == "sqlserver" else ""
        use_windows_auth = db_type == "sqlserver" and sqlserver_auth_mode == SQLSERVER_AUTH_WINDOWS

        config = {
            "db_type": db_type,
            "host": self.txt_host.text().strip(),
            "port": self.spin_port.value(),
            "database": self.txt_database.text().strip(),
            "username": self.txt_username.text().strip(),
            "use_windows_auth": use_windows_auth,
            "trust_server_certificate": self.chk_trust_cert.isChecked(),
            "group": self.cmb_group.currentData(),
            "color": self.selected_color,
            "save_password": self.chk_save_password.isChecked(),
        }

        if db_type == "sqlserver":
            config["sqlserver_auth_mode"] = sqlserver_auth_mode

        # Databricks-specific field
        if db_type == "databricks":
            config["http_path"] = self.txt_http_path.text().strip()
            config["schema"] = self.txt_schema.text().strip() or "default"
        elif db_type == "postgresql":
            config["schema"] = self.txt_schema.text().strip() or "public"

        if self.chk_save_password.isChecked():
            config["password"] = self.txt_password.text()

        return name, config

    def get_connection_name(self) -> str:
        """Returns the connection name (compatibility)"""
        return self.txt_name.text().strip()

    def get_config(self) -> dict:
        """Returns the configuration (compatibility)"""
        _, config = self.get_result()
        return config
