"""
Dialog for importing/exporting connections as JSON.
Passwords are stripped on export for security.
"""

import json
from typing import Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.core.theme_manager import ThemeManager
from src.language import S

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

# Fields to strip from exported connections (secrets)
_SECRET_FIELDS = {"password"}

# Required fields every connection must have
_REQUIRED_FIELDS = {"db_type", "host", "port", "database"}


def export_connections(connection_manager) -> dict:
    """Build a JSON-safe dict of all connections and groups, without secrets."""
    data = connection_manager.saved_configs
    connections = {}
    for name, config in data.get("connections", {}).items():
        clean = {k: v for k, v in config.items() if k not in _SECRET_FIELDS}
        connections[name] = clean

    result = {"connections": connections}
    groups = data.get("groups", {})
    if groups:
        result["groups"] = dict(groups)
    return result


def validate_import_json(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """Parse and validate JSON for import.

    Returns (parsed_dict, None) on success, or (None, error_message) on failure.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, S.connections_manager.import_export_invalid_json.format(error=str(exc))

    if not isinstance(data, dict) or "connections" not in data:
        return None, S.connections_manager.import_export_invalid_structure

    if not isinstance(data["connections"], dict):
        return None, S.connections_manager.import_export_invalid_structure

    if "groups" in data and not isinstance(data["groups"], dict):
        return None, S.connections_manager.import_export_invalid_structure

    for name, config in data["connections"].items():
        if not isinstance(config, dict):
            return None, S.connections_manager.import_export_invalid_connection.format(
                name=name, field="(object)"
            )
        for field in _REQUIRED_FIELDS:
            if field not in config:
                return None, S.connections_manager.import_export_invalid_connection.format(
                    name=name, field=field
                )

    return data, None


def apply_import(connection_manager, data: dict) -> int:
    """Apply validated import data to the connection manager.

    Merges connections and groups; existing names are overwritten.
    Returns number of connections imported.
    """
    # Import groups first
    for group_name, group_config in data.get("groups", {}).items():
        existing = connection_manager.get_groups()
        if group_name not in existing:
            connection_manager.create_group(
                group_name,
                color=group_config.get("color", ""),
                parent=group_config.get("parent", ""),
            )

    # Import connections (without passwords)
    count = 0
    for name, config in data["connections"].items():
        connection_manager.save_connection_config(
            name=name,
            db_type=config.get("db_type", "sqlserver"),
            host=config.get("host", ""),
            port=int(config.get("port", 1433)),
            database=config.get("database", ""),
            username=config.get("username", ""),
            save_password=False,
            password="",
            group=config.get("group", ""),
            use_windows_auth=config.get("use_windows_auth", False),
            color=config.get("color", ""),
            trust_server_certificate=config.get("trust_server_certificate", False),
            http_path=config.get("http_path", ""),
            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
        )
        count += 1

    return count


class ConnectionImportExportDialog(QDialog):
    """JSON editor dialog for importing / exporting connections."""

    def __init__(
        self,
        connection_manager,
        theme_manager: ThemeManager = None,
        parent=None,
    ):
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._imported = False

        self.setWindowTitle(S.connections_manager.import_export_title)
        self.resize(700, 520)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._setup_ui()

    @property
    def imported(self) -> bool:
        """True if connections were imported during this dialog session."""
        return self._imported

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

        from src.design_system.tokens import get_colors
        colors = get_colors()

        # Description
        desc = QLabel(S.connections_manager.import_export_description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px; padding: 4px 0;")
        layout.addWidget(desc)

        # JSON editor
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_muted};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {colors.interactive_primary};
            }}
        """)
        layout.addWidget(self.editor, 1)

        # Error label (hidden by default)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {colors.danger}; font-size: 11px; padding: 2px 0;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_copy = QPushButton(S.connections_manager.import_export_copy)
        if HAS_QTAWESOME:
            btn_copy.setIcon(qta.icon("mdi.content-copy", color="white"))
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()

        btn_cancel = QPushButton(S.connections_manager.import_export_cancel)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton(S.connections_manager.import_export_save)
        if HAS_QTAWESOME:
            btn_save.setIcon(qta.icon("mdi.content-save", color="white"))
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

        # Populate with current connections
        self._load_current()

    def _load_current(self):
        """Fill editor with current connections (no passwords)."""
        data = export_connections(self.connection_manager)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self.editor.setPlainText(text)

    def _copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.editor.toPlainText())

    def _on_save(self):
        """Validate JSON, confirm, and import."""
        text = self.editor.toPlainText().strip()
        self.error_label.setVisible(False)

        data, error = validate_import_json(text)
        if error:
            self.error_label.setText(error)
            self.error_label.setVisible(True)
            return

        conn_count = len(data["connections"])
        group_count = len(data.get("groups", {}))

        reply = QMessageBox.question(
            self,
            S.connections_manager.import_export_confirm_title,
            S.connections_manager.import_export_confirm_msg.format(
                count=conn_count, groups=group_count
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        count = apply_import(self.connection_manager, data)
        self._imported = True

        QMessageBox.information(
            self,
            S.connections_manager.import_export_title,
            S.connections_manager.import_export_success.format(count=count),
        )
        self.accept()
