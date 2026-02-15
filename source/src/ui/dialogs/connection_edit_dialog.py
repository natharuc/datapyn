"""
Unified dialog for creating and editing connections
"""

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
    QMessageBox,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from src.database import DatabaseConnector
from src.core.theme_manager import ThemeManager

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class ConnectionTestWorker(QThread):
    """Worker to test connection in background"""

    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, db_type, host, port, database, username, password, use_windows_auth=False, trust_server_certificate=True):
        super().__init__()
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth
        self.trust_server_certificate = trust_server_certificate

    def run(self):
        try:
            connector = DatabaseConnector()

            kwargs = {}
            if self.use_windows_auth:
                kwargs["use_windows_auth"] = True
            kwargs["trust_server_certificate"] = self.trust_server_certificate

            connector.connect(
                db_type=self.db_type,
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username if not self.use_windows_auth else "",
                password=self.password if not self.use_windows_auth else "",
                **kwargs,
            )

            connector.disconnect()
            self.finished.emit(True, "Connection tested successfully!")

        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")


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

        title = "New Connection" if self.is_new else f"Edit Connection: {connection_name}"
        self.setWindowTitle(title)
        self.resize(500, 650)

        self._setup_ui()
        if not self.is_new:
            self._load_config()

    def _setup_ui(self):
        """Sets up the UI"""
        layout = QVBoxLayout(self)

        # Apply theme
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

        # Basic information group
        basic_group = QFrame()
        basic_group.setFrameShape(QFrame.Shape.StyledPanel)
        basic_group_layout = QVBoxLayout(basic_group)
        basic_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.database-cog", color="#64b5f6").pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("CONNECTION INFORMATION")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        basic_group_layout.addLayout(header)

        basic_layout = QFormLayout()
        basic_group_layout.addLayout(basic_layout)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Name to identify the connection")
        basic_layout.addRow("Name:", self.txt_name)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["sqlserver", "mysql", "mariadb", "postgresql"])
        self.cmb_type.currentTextChanged.connect(self._on_db_type_changed)
        basic_layout.addRow("Database Type:", self.cmb_type)

        self.txt_host = QLineEdit()
        self.txt_host.setPlaceholderText("localhost or server IP")
        basic_layout.addRow("Host:", self.txt_host)

        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(1433)
        basic_layout.addRow("Port:", self.spin_port)

        self.txt_database = QLineEdit()
        self.txt_database.setPlaceholderText("Database name (optional)")
        basic_layout.addRow("Database:", self.txt_database)

        layout.addWidget(basic_group)

        # Authentication group
        auth_group = QFrame()
        auth_group.setFrameShape(QFrame.Shape.StyledPanel)
        auth_group_layout = QVBoxLayout(auth_group)
        auth_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.lock", color="#64b5f6").pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("AUTHENTICATION")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        auth_group_layout.addLayout(header)

        auth_layout = QFormLayout()
        auth_group_layout.addLayout(auth_layout)

        self.chk_windows_auth = QCheckBox("Use Windows Authentication")
        self.chk_windows_auth.stateChanged.connect(self._toggle_windows_auth)
        auth_layout.addRow(self.chk_windows_auth)

        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("Database user")
        auth_layout.addRow("User:", self.txt_username)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("Password")
        auth_layout.addRow("Password:", self.txt_password)

        self.chk_save_password = QCheckBox("Save password (not recommended)")
        auth_layout.addRow(self.chk_save_password)

        # SSL option (SQL Server only)
        self.chk_trust_cert = QCheckBox("Trust server certificate (TrustServerCertificate)")
        self.chk_trust_cert.setChecked(False)  # Default: don't trust (more secure)
        self.chk_trust_cert.setToolTip(
            "Check this option if the server does not have a valid SSL certificate.\n"
            "Common in development environments or internal servers."
        )
        auth_layout.addRow(self.chk_trust_cert)

        layout.addWidget(auth_group)

        # Organization group
        org_group = QFrame()
        org_group.setFrameShape(QFrame.Shape.StyledPanel)
        org_group_layout = QVBoxLayout(org_group)
        org_group_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.folder-cog", color="#64b5f6").pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("ORGANIZATION")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        org_group_layout.addLayout(header)

        org_layout = QFormLayout()
        org_group_layout.addLayout(org_layout)

        self.cmb_group = QComboBox()
        self.cmb_group.addItem("[No group]", "")
        for group_name in self.groups.keys():
            self.cmb_group.addItem(group_name, group_name)
        org_layout.addRow("Group:", self.cmb_group)

        # Color
        color_layout = QHBoxLayout()
        self.lbl_color = QLabel("None")
        self.lbl_color.setMinimumWidth(100)
        self.lbl_color.setStyleSheet("border: 1px solid #555; padding: 3px;")
        btn_choose_color = QPushButton("Choose Color")
        btn_choose_color.clicked.connect(self._choose_color)
        btn_clear_color = QPushButton("Clear")
        btn_clear_color.clicked.connect(self._clear_color)
        color_layout.addWidget(self.lbl_color)
        color_layout.addWidget(btn_choose_color)
        color_layout.addWidget(btn_clear_color)
        org_layout.addRow("Color:", color_layout)

        layout.addWidget(org_group)

        # Buttons
        buttons_layout = QHBoxLayout()

        btn_test = QPushButton(" Test Connection")
        btn_test.setObjectName("btnTest")
        if HAS_QTAWESOME:
            btn_test.setIcon(qta.icon("mdi.lan-connect", color="white"))
        btn_test.clicked.connect(self._test_connection)
        buttons_layout.addWidget(btn_test)

        buttons_layout.addStretch()

        btn_save = QPushButton(" Save")
        if HAS_QTAWESOME:
            btn_save.setIcon(qta.icon("mdi.content-save", color="white"))
        btn_save.clicked.connect(self._on_save)
        buttons_layout.addWidget(btn_save)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(btn_cancel)

        layout.addLayout(buttons_layout)

        # Initial adjustments
        self._toggle_windows_auth_visibility()

    def _load_config(self):
        """Loads current configuration"""
        self.txt_name.setText(self.connection_name)

        db_type = self.config.get("db_type", "sqlserver")
        index = self.cmb_type.findText(db_type)
        if index >= 0:
            self.cmb_type.setCurrentIndex(index)

        self.txt_host.setText(self.config.get("host", ""))
        self.spin_port.setValue(self.config.get("port", 1433))
        self.txt_database.setText(self.config.get("database", ""))

        use_windows_auth = self.config.get("use_windows_auth", False)
        self.chk_windows_auth.setChecked(use_windows_auth)

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
        db_type = self.cmb_type.currentText()

        # Adjust default port
        default_ports = {"sqlserver": 1433, "mysql": 3306, "mariadb": 3306, "postgresql": 5432}
        self.spin_port.setValue(default_ports.get(db_type, 1433))

        self._toggle_windows_auth_visibility()

    def _toggle_windows_auth(self):
        """Toggle authentication fields"""
        is_windows_auth = self.chk_windows_auth.isChecked()
        self.txt_username.setEnabled(not is_windows_auth)
        self.txt_password.setEnabled(not is_windows_auth)
        self.chk_save_password.setEnabled(not is_windows_auth)

    def _toggle_windows_auth_visibility(self):
        """Shows/hides Windows Auth and Trust Cert based on database type"""
        is_sqlserver = self.cmb_type.currentText() == "sqlserver"
        self.chk_windows_auth.setVisible(is_sqlserver)
        self.chk_trust_cert.setVisible(is_sqlserver)
        if not is_sqlserver:
            self.chk_windows_auth.setChecked(False)

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
        self.lbl_color.setText("None")
        self.lbl_color.setStyleSheet("border: 1px solid #555; padding: 3px;")

    def _update_color_label(self):
        """Updates color label"""
        if self.selected_color:
            self.lbl_color.setText(self.selected_color)
            self.lbl_color.setStyleSheet(
                f"background-color: {self.selected_color}; border: 1px solid #555; padding: 3px; color: white;"
            )

    def _test_connection(self):
        """Tests the connection with current settings in background"""
        # Create loading dialog with cancel button
        db_name = self.txt_database.text() or self.txt_host.text()
        self.loading_dialog = QProgressDialog(self)
        self.loading_dialog.setWindowTitle("Testing Connection")
        self.loading_dialog.setLabelText(f"Testing connection to {db_name}...")
        self.loading_dialog.setCancelButtonText("Cancel")
        self.loading_dialog.setRange(0, 0)  # Indeterminate progress
        self.loading_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.loading_dialog.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint
        )
        self.loading_dialog.setMinimumWidth(300)
        self.loading_dialog.canceled.connect(self._cancel_test_connection)
        self.loading_dialog.show()

        # Create and start worker
        self._test_cancelled = False
        self.test_worker = ConnectionTestWorker(
            db_type=self.cmb_type.currentText(),
            host=self.txt_host.text(),
            port=self.spin_port.value(),
            database=self.txt_database.text(),
            username=self.txt_username.text(),
            password=self.txt_password.text(),
            use_windows_auth=self.chk_windows_auth.isChecked(),
            trust_server_certificate=self.chk_trust_cert.isChecked(),
        )
        self.test_worker.finished.connect(self._on_test_finished)
        self.test_worker.start()

    def _cancel_test_connection(self):
        """Cancels the ongoing connection test"""
        self._test_cancelled = True
        if hasattr(self, 'test_worker') and self.test_worker.isRunning():
            self.test_worker.terminate()
            self.test_worker.wait(2000)

    def _on_test_finished(self, success: bool, message: str):
        """Callback when connection test finishes"""
        if self._test_cancelled:
            return  # Ignore result if cancelled

        self.loading_dialog.close()

        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

    def _on_save(self):
        """Validates and saves"""
        name = self.txt_name.text().strip()

        if not name:
            QMessageBox.warning(self, "Warning", "Please enter a name for the connection.")
            return

        if not self.txt_host.text().strip():
            QMessageBox.warning(self, "Warning", "Please enter the host.")
            return

        self.accept()

    def get_result(self):
        """Returns edited name and configuration"""
        name = self.txt_name.text().strip()

        config = {
            "db_type": self.cmb_type.currentText(),
            "host": self.txt_host.text().strip(),
            "port": self.spin_port.value(),
            "database": self.txt_database.text().strip(),
            "username": self.txt_username.text().strip(),
            "use_windows_auth": self.chk_windows_auth.isChecked(),
            "trust_server_certificate": self.chk_trust_cert.isChecked(),
            "group": self.cmb_group.currentData(),
            "color": self.selected_color,
            "save_password": self.chk_save_password.isChecked(),
        }

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
