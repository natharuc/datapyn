"""
Python Package Manager Dialog (pip)

Allows the user to search, install, update and
uninstall Python packages directly in DataPyn.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QHeaderView,
    QMessageBox,
    QWidget,
    QProgressBar,
    QAbstractItemView,
    QSizePolicy,
    QFrame,
    QApplication,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QFormLayout,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QIcon
import logging

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

from src.services.package_manager_service import PackageManagerService, PackageInfo, PackageOperationResult
from src.core.theme_manager import ThemeManager
from src.language import S

logger = logging.getLogger(__name__)


class _ListWorker(QThread):
    """Worker to list packages in background"""

    finished = pyqtSignal(list)

    def __init__(self, service: PackageManagerService):
        super().__init__()
        self.service = service

    def run(self):
        packages = self.service.list_installed()
        self.finished.emit(packages)


class _SearchWorker(QThread):
    """Worker to search packages in background"""

    finished = pyqtSignal(list)

    def __init__(self, service: PackageManagerService, query: str):
        super().__init__()
        self.service = service
        self.query = query

    def run(self):
        results = self.service.search_pypi(self.query)
        self.finished.emit(results)


class _InstallWorker(QThread):
    """Worker to install/uninstall/update in background"""

    finished = pyqtSignal(object)  # PackageOperationResult

    def __init__(self, service: PackageManagerService, operation: str, package_name: str, version: str = ""):
        super().__init__()
        self.service = service
        self.operation = operation
        self.package_name = package_name
        self.version = version

    def run(self):
        if self.operation == "install":
            result = self.service.install_package(self.package_name, self.version)
        elif self.operation == "uninstall":
            result = self.service.uninstall_package(self.package_name)
        elif self.operation == "update":
            result = self.service.update_package(self.package_name)
        else:
            result = PackageOperationResult(
                success=False,
                package_name=self.package_name,
                operation=self.operation,
                error=f"Unknown operation: {self.operation}",
            )
        self.finished.emit(result)


class _AddSourceDialog(QDialog):
    """Dialog for adding a package source with optional authentication."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.package_manager.add_source_title)
        self.setMinimumWidth(500)

        # Inherit theme from parent PackageManagerDialog
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        c = parent.theme_manager.get_app_colors() if parent and hasattr(parent, "theme_manager") else {}
        bg = c.get("background", colors.bg_primary)
        fg = c.get("foreground", colors.text_primary)
        border = c.get("border", colors.border_default)
        accent = c.get("accent", colors.interactive_primary)

        from src.design_system.frameless_dialog import install_frameless_shell

        self.setStyleSheet(f"""
            QDialog {{
                background-color: transparent;
                color: {fg};
            }}
            QLabel {{
                color: {fg};
                font-size: 12px;
            }}
            QLineEdit {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {accent};
            }}
        """)

        layout = install_frameless_shell(
            self,
            S.package_manager.add_source_title,
            min_width=500,
            content_margins=(16, 12, 16, 16),
            content_spacing=12,
        )

        # URL field
        lbl_url = QLabel(S.package_manager.add_source_prompt)
        layout.addWidget(lbl_url)
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("https://pkgs.dev.azure.com/org/_packaging/feed/pypi/simple/")
        layout.addWidget(self.txt_url)

        # Auth section
        auth_label = QLabel(S.package_manager.auth_section_title)
        auth_font = QFont()
        auth_font.setBold(True)
        auth_label.setFont(auth_font)
        layout.addWidget(auth_label)

        auth_desc = QLabel(S.package_manager.auth_section_description)
        auth_desc.setWordWrap(True)
        auth_desc.setStyleSheet(f"color: {fg}; font-size: 10px; opacity: 0.7;")
        layout.addWidget(auth_desc)

        form = QFormLayout()
        form.setSpacing(8)

        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText(S.package_manager.auth_username_placeholder)
        form.addRow(S.package_manager.auth_username_label, self.txt_username)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText(S.package_manager.auth_token_placeholder)
        form.addRow(S.package_manager.auth_token_label, self.txt_password)

        layout.addLayout(form)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.reject)
        btn_box.setStyleSheet(f"""
            QPushButton {{
                padding: 6px 18px;
                border-radius: 8px;
                font-size: 11px;
                min-width: 70px;
            }}
        """)
        layout.addWidget(btn_box)

    def _validate_and_accept(self):
        """Validate fields before accepting."""
        url = self.txt_url.text().strip()
        if not url:
            return
        username = self.txt_username.text().strip()
        if username and ("://" in username or username.startswith("http")):
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                S.package_manager.add_source_title,
                S.package_manager.auth_username_invalid,
            )
            self.txt_username.setFocus()
            self.txt_username.selectAll()
            return
        self.accept()

    def get_source(self) -> dict:
        """Return the source dict with url, username, password."""
        return {
            "url": self.txt_url.text().strip(),
            "username": self.txt_username.text().strip(),
            "password": self.txt_password.text(),
        }


class PackageManagerDialog(QDialog):
    """Dialog for managing Python packages via pip"""

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.service = PackageManagerService()
        self._worker = None
        self._installed_names = set()
        self._current_view = "installed"  # 'installed' or 'search'
        self._pending_query = ""  # query used in current search
        self._setup_ui()
        self._load_installed()

    def _make_icon_action_button(
        self,
        label: str,
        icon_name: str,
        bg: str,
        hover_bg: str,
        on_click,
        *,
        disabled_bg: str,
        disabled_fg: str,
    ) -> QPushButton:
        """Compact icon-only button for table action cells."""
        btn = QPushButton()
        btn.setToolTip(label)
        btn.setFixedSize(34, 30)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            btn.setIcon(qta.icon(icon_name, color="white"))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0;
            }}
            QPushButton:hover {{ background-color: {hover_bg}; }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {disabled_fg};
            }}
        """)
        btn.clicked.connect(on_click)
        return btn

    def _make_actions_cell(self, *buttons: QPushButton) -> QWidget:
        """Build a fixed-size widget for the Actions column."""
        actions_widget = QWidget()
        actions_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(6, 0, 6, 0)
        actions_layout.setSpacing(6)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for btn in buttons:
            actions_layout.addWidget(btn)
        return actions_widget

    def _setup_ui(self):
        """Sets up the UI"""
        self.setWindowTitle(S.package_manager.title)
        self.resize(820, 600)

        from src.design_system.frameless_dialog import install_frameless_shell
        from src.design_system.tokens import get_colors
        from src.design_system.button import PrimaryButton, SecondaryButton

        colors = get_colors()
        dim_color = colors.text_tertiary
        layout = install_frameless_shell(
            self,
            S.package_manager.title,
            min_width=780,
            min_height=560,
            content_margins=(20, 16, 20, 20),
            content_spacing=12,
        )

        # --- Header ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title = QLabel(S.package_manager.title)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        subtitle = QLabel(S.package_manager.subtitle)
        subtitle.setStyleSheet(f"color: {dim_color}; font-size: 11px;")
        header_layout.addWidget(subtitle)

        # --- Venv indicator ---
        venv_text = S.package_manager.venv_label.format(path=self.service.venv_path)
        venv_label = QLabel(venv_text)
        venv_label.setStyleSheet(f"color: {dim_color}; font-size: 10px; font-style: italic;")
        venv_label.setToolTip(self.service.venv_path)
        header_layout.addWidget(venv_label)

        layout.addLayout(header_layout)

        # --- Search bar ---
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(S.package_manager.placeholder_search)
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: none;
                padding: 10px 12px;
                border-radius: 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                background-color: {colors.bg_elevated};
            }}
        """)
        self.txt_search.returnPressed.connect(self._on_search)
        search_row.addWidget(self.txt_search)

        self.btn_search = PrimaryButton(S.package_manager.btn_search, size="sm")
        if HAS_QTAWESOME:
            self.btn_search.setIcon(qta.icon("fa5s.search", color="white"))
        self.btn_search.clicked.connect(self._on_search)
        search_row.addWidget(self.btn_search)

        self.btn_show_installed = SecondaryButton(S.package_manager.btn_installed, size="sm")
        if HAS_QTAWESOME:
            self.btn_show_installed.setIcon(qta.icon("fa5s.list", color="white"))
        self.btn_show_installed.clicked.connect(self._load_installed)
        search_row.addWidget(self.btn_show_installed)

        layout.addLayout(search_row)

        # --- Info label ---
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(f"""
            background-color: {colors.bg_secondary};
            color: {colors.text_secondary};
            padding: 8px 12px;
            border-radius: 6px;
            border: none;
            border-left: 3px solid {colors.interactive_primary};
            font-size: 11px;
        """)
        layout.addWidget(self.lbl_info)

        # --- Packages table ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([S.package_manager.header_package, S.package_manager.header_installed_version, S.package_manager.header_latest_version, S.package_manager.header_actions])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 88)
        self.table.horizontalHeader().setMinimumSectionSize(88)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {colors.border_muted};
                font-size: 11px;
                border: none;
                background-color: {colors.bg_secondary};
            }}
            QTableWidget::item {{
                padding: 4px 6px;
            }}
            QTableWidget::item:selected {{
                background-color: {colors.interactive_primary};
            }}
            QHeaderView::section {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                padding: 8px;
                border: none;
                border-bottom: 1px solid {colors.border_muted};
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        layout.addWidget(self.table)

        # --- Progress bar ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {colors.bg_tertiary};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {colors.interactive_primary};
                border-radius: 4px;
            }}
        """)
        self.progress.hide()
        layout.addWidget(self.progress)

        # --- Footer ---
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.lbl_status = QLabel(S.package_manager.status_ready)
        self.lbl_status.setStyleSheet(f"color: {dim_color}; font-size: 10px;")
        footer.addWidget(self.lbl_status)
        footer.addStretch()

        self.btn_sources = SecondaryButton(S.package_manager.btn_sources, size="sm")
        if HAS_QTAWESOME:
            self.btn_sources.setIcon(qta.icon("fa5s.cog", color="white"))
        self.btn_sources.setCheckable(True)
        self.btn_sources.clicked.connect(self._toggle_sources_panel)
        footer.addWidget(self.btn_sources)

        btn_close = PrimaryButton(S.package_manager.btn_close, size="sm")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        layout.addLayout(footer)

        # --- Sources panel (collapsible) ---
        self.sources_frame = QFrame()
        self.sources_frame.setObjectName("sectionPanel")
        self.sources_frame.setStyleSheet(f"""
            QFrame#sectionPanel {{
                background-color: {colors.bg_secondary};
                border: none;
                border-radius: 8px;
            }}
        """)
        self.sources_frame.setVisible(False)
        sources_layout = QVBoxLayout(self.sources_frame)
        sources_layout.setContentsMargins(12, 10, 12, 10)
        sources_layout.setSpacing(8)

        sources_title = QLabel(S.package_manager.sources_title)
        sources_title_font = QFont()
        sources_title_font.setBold(True)
        sources_title.setFont(sources_title_font)
        sources_layout.addWidget(sources_title)

        sources_desc = QLabel(S.package_manager.sources_description)
        sources_desc.setStyleSheet(f"color: {dim_color}; font-size: 10px; border: none;")
        sources_desc.setWordWrap(True)
        sources_layout.addWidget(sources_desc)

        self.sources_list = QListWidget()
        self.sources_list.setMaximumHeight(100)
        self.sources_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }}
            QListWidget::item {{
                padding: 4px 8px;
            }}
            QListWidget::item:selected {{
                background-color: {colors.interactive_primary};
            }}
        """)
        sources_layout.addWidget(self.sources_list)

        sources_btn_row = QHBoxLayout()
        sources_btn_row.setSpacing(6)

        btn_add_source = QPushButton(S.package_manager.btn_add_source)
        if HAS_QTAWESOME:
            btn_add_source.setIcon(qta.icon("fa5s.plus", color="white"))
        btn_add_source.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 10px;
            }}
            QPushButton:hover {{ opacity: 0.85; }}
        """)
        btn_add_source.clicked.connect(self._add_source)
        sources_btn_row.addWidget(btn_add_source)

        btn_remove_source = QPushButton(S.package_manager.btn_remove_source)
        if HAS_QTAWESOME:
            btn_remove_source.setIcon(qta.icon("fa5s.trash-alt", color="white"))
        btn_remove_source.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.danger};
                color: white;
                border: none;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 10px;
            }}
            QPushButton:hover {{ background-color: {colors.danger}dd; }}
        """)
        btn_remove_source.clicked.connect(self._remove_source)
        sources_btn_row.addWidget(btn_remove_source)

        sources_btn_row.addStretch()
        sources_layout.addLayout(sources_btn_row)

        layout.addWidget(self.sources_frame)

        # Load saved sources
        self._load_sources()

    # === Sources management ===

    def _toggle_sources_panel(self, checked: bool):
        """Shows or hides the sources configuration panel."""
        self.sources_frame.setVisible(checked)

    def _load_sources(self):
        """Loads saved sources into the list widget."""
        self.sources_list.clear()
        for source in self.service.get_sources():
            url = source.get("url", "")
            username = source.get("username", "")
            has_auth = bool(username and source.get("password", ""))
            display = url
            if has_auth:
                display = f"{url}  [{username}]"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.sources_list.addItem(item)

    def _add_source(self):
        """Opens dialog to add a new package source with optional auth."""
        dlg = _AddSourceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            source = dlg.get_source()
            if not source.get("url"):
                return
            existing = self.service.get_sources()
            # Avoid duplicate URLs
            if any(s.get("url") == source["url"] for s in existing):
                return
            existing.append(source)
            self.service.set_sources(existing)
            self._load_sources()

    def _remove_source(self):
        """Removes the selected source."""
        item = self.sources_list.currentItem()
        if not item:
            return
        source = item.data(Qt.ItemDataRole.UserRole)
        sources = self.service.get_sources()
        sources = [s for s in sources if s.get("url") != source.get("url")]
        self.service.set_sources(sources)
        self._load_sources()

    # === Actions ===

    def _cleanup_worker(self):
        """Cleans up previous worker to avoid duplicate signals"""
        if self._worker is not None:
            try:
                self._worker.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            if self._worker.isRunning():
                self._worker.quit()
                self._worker.wait(2000)
            self._worker = None

    def _on_search(self):
        """Searches for package on PyPI"""
        query = self.txt_search.text().strip()
        if not query:
            return
        if len(query) < 2:
            self.lbl_info.setText(S.package_manager.search_min_chars)
            return

        self._current_view = "search"
        self._pending_query = query
        self._cleanup_worker()
        self._set_loading(True, S.package_manager.status_searching.format(query=query))

        self._worker = _SearchWorker(self.service, query)
        self._worker.finished.connect(self._on_search_results)
        self._worker.start()

    def _on_search_results(self, results: list):
        """Callback with search results"""
        self._set_loading(False)
        query = self._pending_query or self.txt_search.text().strip()

        if not results:
            self.lbl_info.setText(S.package_manager.pkg_not_found.format(query=query))
            self.table.setRowCount(0)
            return

        self.lbl_info.setText(S.package_manager.search_results.format(query=query))
        self._populate_table(results)

    def _show_direct_install_option(self, package_name: str):
        """Shows option to install package directly when not found"""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        self.table.setRowCount(1)

        name_item = QTableWidgetItem(package_name)
        name_font = QFont()
        name_font.setBold(True)
        name_item.setFont(name_font)
        name_item.setToolTip("Package not found - try direct install")
        self.table.setItem(0, 0, name_item)

        self.table.setItem(0, 1, QTableWidgetItem("-"))
        self.table.setItem(0, 2, QTableWidgetItem("-"))

        btn_install = self._make_icon_action_button(
            S.package_manager.btn_install_anyway,
            "fa5s.download",
            colors.interactive_primary,
            colors.interactive_primary_hover,
            lambda _, n=package_name: self._do_operation("install", n),
            disabled_bg=colors.bg_tertiary,
            disabled_fg=colors.text_tertiary,
        )

        self.table.setCellWidget(0, 3, self._make_actions_cell(btn_install))
        self.table.setRowHeight(0, 36)

    def _load_installed(self):
        """Loads list of installed packages"""
        self._current_view = "installed"
        self.txt_search.clear()
        self._cleanup_worker()
        self._set_loading(True, S.package_manager.status_loading_installed)

        self._worker = _ListWorker(self.service)
        self._worker.finished.connect(self._on_installed_loaded)
        self._worker.start()

    def _on_installed_loaded(self, packages: list):
        """Callback with installed packages"""
        self._set_loading(False)
        self._installed_names = {p.name.lower() for p in packages}
        count = len(packages)
        self.lbl_info.setText(S.package_manager.status_packages_installed.format(n=count))
        self._populate_table(packages)

    def _populate_table(self, packages: list):
        """Populates the table with packages"""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        dim_color = colors.text_tertiary
        self.table.setRowCount(len(packages))

        for row, pkg in enumerate(packages):
            # Name
            name_item = QTableWidgetItem(pkg.name)
            name_font = QFont()
            name_font.setBold(True)
            name_item.setFont(name_font)

            # Description in tooltip
            if pkg.summary:
                name_item.setToolTip(pkg.summary)

            self.table.setItem(row, 0, name_item)

            # Installed version
            ver_item = QTableWidgetItem(pkg.version if pkg.version else "-")
            ver_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 1, ver_item)

            # Latest version
            latest = pkg.latest_version if pkg.latest_version else "-"
            latest_item = QTableWidgetItem(latest)
            latest_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if pkg.has_update:
                latest_item.setForeground(QColor(colors.success))
            self.table.setItem(row, 2, latest_item)

            # Action buttons (icon-only — avoids clipping in narrow table cells)
            action_buttons: list[QPushButton] = []

            if pkg.installed:
                if pkg.has_update:
                    action_buttons.append(
                        self._make_icon_action_button(
                            S.package_manager.btn_update,
                            "fa5s.arrow-up",
                            colors.success,
                            f"{colors.success}dd",
                            lambda _, n=pkg.name: self._do_operation("update", n),
                            disabled_bg=colors.bg_tertiary,
                            disabled_fg=dim_color,
                        )
                    )
                action_buttons.append(
                    self._make_icon_action_button(
                        S.package_manager.btn_remove,
                        "fa5s.trash-alt",
                        colors.danger,
                        f"{colors.danger}dd",
                        lambda _, n=pkg.name: self._confirm_uninstall(n),
                        disabled_bg=colors.bg_tertiary,
                        disabled_fg=dim_color,
                    )
                )
            else:
                action_buttons.append(
                    self._make_icon_action_button(
                        S.package_manager.btn_install,
                        "fa5s.download",
                        colors.interactive_primary,
                        colors.interactive_primary_hover,
                        lambda _, n=pkg.name: self._do_operation("install", n),
                        disabled_bg=colors.bg_tertiary,
                        disabled_fg=dim_color,
                    )
                )

            actions_widget = self._make_actions_cell(*action_buttons)
            self.table.setCellWidget(row, 3, actions_widget)
            self.table.setRowHeight(row, 36)

        if packages:
            max_buttons = max(2 if p.installed and p.has_update else 1 for p in packages)
            self.table.setColumnWidth(3, min(140, 52 + 40 * max_buttons))

    def _confirm_uninstall(self, package_name: str):
        """Confirms package uninstall"""
        reply = QMessageBox.question(
            self,
            S.package_manager.dialog_confirm_removal_title,
            S.package_manager.dialog_confirm_removal_msg.format(name=package_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_operation("uninstall", package_name)

    def _do_operation(self, operation: str, package_name: str, version: str = ""):
        """Executes package operation in background"""
        op_labels = {
            "install": S.package_manager.op_installing,
            "uninstall": S.package_manager.op_removing,
            "update": S.package_manager.op_updating,
        }
        label = op_labels.get(operation, operation)
        self._cleanup_worker()
        self._set_loading(True, S.package_manager.status_operation.format(label=label, name=package_name))
        self._set_buttons_enabled(False)

        self._worker = _InstallWorker(self.service, operation, package_name, version)
        self._worker.finished.connect(self._on_operation_done)
        self._worker.start()

    def _on_operation_done(self, result: PackageOperationResult):
        """Callback after operation completed"""
        self._set_loading(False)
        self._set_buttons_enabled(True)

        if result.success:
            QMessageBox.information(self, S.package_manager.dialog_success_title, result.message)
            # Always reload installed list after operation
            # Use QTimer to avoid conflicts with still-active thread
            QTimer.singleShot(100, self._load_installed)
        else:
            error_msg = result.error
            # Limit displayed error size
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "\n..."
            QMessageBox.critical(self, S.package_manager.dialog_error_title, S.package_manager.dialog_error_msg.format(operation=result.operation, name=result.package_name, error=error_msg))

    # === Helpers ===

    def _set_loading(self, loading: bool, message: str = ""):
        """Shows/hides loading indicator"""
        if loading:
            self.progress.show()
            self.lbl_status.setText(message or S.package_manager.status_processing)
            self.btn_search.setEnabled(False)
            self.btn_show_installed.setEnabled(False)
        else:
            self.progress.hide()
            self.lbl_status.setText(S.package_manager.status_ready)
            self.btn_search.setEnabled(True)
            self.btn_show_installed.setEnabled(True)

    def _set_buttons_enabled(self, enabled: bool):
        """Enables/disables action buttons in the table"""
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 3)
            if widget:
                for btn in widget.findChildren(QPushButton):
                    btn.setEnabled(enabled)
