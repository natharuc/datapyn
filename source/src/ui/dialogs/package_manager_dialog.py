"""
Dialogo de Gerenciamento de Pacotes Python (pip)

Permite ao usuario pesquisar, instalar, atualizar e
desinstalar pacotes Python diretamente no DataPyn.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QLabel, QHeaderView, QMessageBox, QWidget,
                             QProgressBar, QAbstractItemView, QFrame,
                             QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QIcon
import logging

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

from src.services.package_manager_service import (
    PackageManagerService, PackageInfo, PackageOperationResult
)
from src.core.theme_manager import ThemeManager

logger = logging.getLogger(__name__)


class _ListWorker(QThread):
    """Worker para listar pacotes em background"""
    finished = pyqtSignal(list)

    def __init__(self, service: PackageManagerService):
        super().__init__()
        self.service = service

    def run(self):
        packages = self.service.list_installed()
        self.finished.emit(packages)


class _SearchWorker(QThread):
    """Worker para pesquisar pacotes em background"""
    finished = pyqtSignal(list)

    def __init__(self, service: PackageManagerService, query: str):
        super().__init__()
        self.service = service
        self.query = query

    def run(self):
        results = self.service.search_pypi(self.query)
        self.finished.emit(results)


class _InstallWorker(QThread):
    """Worker para instalar/desinstalar/atualizar em background"""
    finished = pyqtSignal(object)  # PackageOperationResult

    def __init__(self, service: PackageManagerService,
                 operation: str, package_name: str, version: str = ""):
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
                error=f"Operacao desconhecida: {self.operation}"
            )
        self.finished.emit(result)


class PackageManagerDialog(QDialog):
    """Dialogo para gerenciar pacotes Python via pip"""

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.service = PackageManagerService()
        self._worker = None
        self._installed_names = set()
        self._current_view = "installed"  # 'installed' ou 'search'
        self._setup_ui()
        self._load_installed()

    def _setup_ui(self):
        """Configura a interface"""
        self.setWindowTitle("Gerenciador de Pacotes")
        self.setModal(True)
        self.setMinimumSize(780, 560)
        self.resize(820, 600)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

        c = self.theme_manager.get_app_colors()
        dim_color = '#999999'  # cor secundaria para texto menos importante
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Cabecalho ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title = QLabel("Gerenciador de Pacotes")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        subtitle = QLabel("Pesquise, instale e gerencie pacotes Python (pip)")
        subtitle.setStyleSheet(f"color: {dim_color}; font-size: 11px;")
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        # --- Barra de pesquisa ---
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(
            "Digite o nome do pacote (ex: matplotlib, requests, scikit-learn)..."
        )
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: 1px solid {c['border']};
                padding: 10px 12px;
                border-radius: 4px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {c['accent']};
            }}
        """)
        self.txt_search.returnPressed.connect(self._on_search)
        search_row.addWidget(self.txt_search)

        self.btn_search = QPushButton("Pesquisar")
        if HAS_QTAWESOME:
            self.btn_search.setIcon(qta.icon("fa5s.search", color="white"))
        self.btn_search.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['accent']};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {c['accent']};
                opacity: 0.85;
            }}
            QPushButton:disabled {{
                background-color: {c['border']};
                color: {dim_color};
            }}
        """)
        self.btn_search.clicked.connect(self._on_search)
        search_row.addWidget(self.btn_search)

        self.btn_show_installed = QPushButton("Instalados")
        if HAS_QTAWESOME:
            self.btn_show_installed.setIcon(
                qta.icon("fa5s.list", color="white")
            )
        self.btn_show_installed.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['border']};
                color: {c['foreground']};
                border: none;
                padding: 10px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
        """)
        self.btn_show_installed.clicked.connect(self._load_installed)
        search_row.addWidget(self.btn_show_installed)

        layout.addLayout(search_row)

        # --- Info label ---
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(f"""
            background-color: {c['border']};
            color: {c['foreground']};
            padding: 8px 12px;
            border-radius: 4px;
            border-left: 3px solid {c['accent']};
            font-size: 11px;
        """)
        layout.addWidget(self.lbl_info)

        # --- Tabela de pacotes ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Pacote", "Versao Instalada", "Ultima Versao", "Acoes"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {c['border']};
                font-size: 11px;
                border: 1px solid {c['border']};
                background-color: {c['background']};
            }}
            QTableWidget::item {{
                padding: 6px 8px;
            }}
            QTableWidget::item:selected {{
                background-color: #094771;
            }}
            QHeaderView::section {{
                background-color: {c['border']};
                color: {c['foreground']};
                padding: 8px;
                border: none;
                border-right: 1px solid {c['background']};
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        layout.addWidget(self.table)

        # --- Barra de progresso ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {c['border']};
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {c['accent']};
                border-radius: 1px;
            }}
        """)
        self.progress.hide()
        layout.addWidget(self.progress)

        # --- Rodape ---
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.lbl_status = QLabel("Pronto")
        self.lbl_status.setStyleSheet(
            f"color: {dim_color}; font-size: 10px;"
        )
        footer.addWidget(self.lbl_status)
        footer.addStretch()

        btn_close = QPushButton("Fechar")
        btn_close.setObjectName("btnCancel")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        layout.addLayout(footer)

    # === Acoes ===

    def _on_search(self):
        """Pesquisa pacote no PyPI"""
        query = self.txt_search.text().strip()
        if not query:
            return
        if len(query) < 2:
            self.lbl_info.setText("Digite pelo menos 2 caracteres para pesquisar.")
            return

        self._current_view = "search"
        self._set_loading(True, f"Pesquisando '{query}' no PyPI...")

        self._worker = _SearchWorker(self.service, query)
        self._worker.finished.connect(self._on_search_results)
        self._worker.start()

    def _on_search_results(self, results: list):
        """Callback com resultados da pesquisa"""
        self._set_loading(False)
        query = self.txt_search.text().strip()

        if not results:
            self.lbl_info.setText(
                f"Nenhum pacote encontrado para '{query}'. "
                "Verifique o nome exato do pacote."
            )
            self.table.setRowCount(0)
            return

        self.lbl_info.setText(
            f"Resultado para '{query}' "
            "(use o nome exato do pacote no PyPI)"
        )
        self._populate_table(results)

    def _load_installed(self):
        """Carrega lista de pacotes instalados"""
        self._current_view = "installed"
        self.txt_search.clear()
        self._set_loading(True, "Carregando pacotes instalados...")

        self._worker = _ListWorker(self.service)
        self._worker.finished.connect(self._on_installed_loaded)
        self._worker.start()

    def _on_installed_loaded(self, packages: list):
        """Callback com pacotes instalados"""
        self._set_loading(False)
        self._installed_names = {p.name.lower() for p in packages}
        count = len(packages)
        self.lbl_info.setText(f"{count} pacotes instalados")
        self._populate_table(packages)

    def _populate_table(self, packages: list):
        """Preenche a tabela com os pacotes"""
        c = self.theme_manager.get_app_colors()
        dim_color = '#999999'
        self.table.setRowCount(len(packages))

        for row, pkg in enumerate(packages):
            # Nome
            name_item = QTableWidgetItem(pkg.name)
            name_font = QFont()
            name_font.setBold(True)
            name_item.setFont(name_font)

            # Descricao no tooltip
            if pkg.summary:
                name_item.setToolTip(pkg.summary)

            self.table.setItem(row, 0, name_item)

            # Versao instalada
            ver_item = QTableWidgetItem(pkg.version if pkg.version else "-")
            ver_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 1, ver_item)

            # Ultima versao
            latest = pkg.latest_version if pkg.latest_version else "-"
            latest_item = QTableWidgetItem(latest)
            latest_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            if pkg.has_update:
                latest_item.setForeground(QColor("#4ec9b0"))
            self.table.setItem(row, 2, latest_item)

            # Botoes de acao
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 2, 4, 2)
            actions_layout.setSpacing(4)

            if pkg.installed:
                # Botao atualizar
                if pkg.has_update:
                    btn_update = QPushButton("Atualizar")
                    if HAS_QTAWESOME:
                        btn_update.setIcon(
                            qta.icon("fa5s.arrow-up", color="white")
                        )
                    btn_update.setStyleSheet(f"""
                        QPushButton {{
                            background-color: #2e7d32;
                            color: white;
                            border: none;
                            padding: 4px 10px;
                            border-radius: 3px;
                            font-size: 10px;
                        }}
                        QPushButton:hover {{ background-color: #388e3c; }}
                        QPushButton:disabled {{
                            background-color: {c['border']};
                            color: {dim_color};
                        }}
                    """)
                    btn_update.clicked.connect(
                        lambda _, n=pkg.name: self._do_operation("update", n)
                    )
                    actions_layout.addWidget(btn_update)

                # Botao desinstalar
                btn_uninstall = QPushButton("Remover")
                if HAS_QTAWESOME:
                    btn_uninstall.setIcon(
                        qta.icon("fa5s.trash-alt", color="white")
                    )
                btn_uninstall.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #c5534d;
                        color: white;
                        border: none;
                        padding: 4px 10px;
                        border-radius: 3px;
                        font-size: 10px;
                    }}
                    QPushButton:hover {{ background-color: #e06060; }}
                    QPushButton:disabled {{
                        background-color: {c['border']};
                        color: {dim_color};
                    }}
                """)
                btn_uninstall.clicked.connect(
                    lambda _, n=pkg.name: self._confirm_uninstall(n)
                )
                actions_layout.addWidget(btn_uninstall)
            else:
                # Botao instalar
                btn_install = QPushButton("Instalar")
                if HAS_QTAWESOME:
                    btn_install.setIcon(
                        qta.icon("fa5s.download", color="white")
                    )
                btn_install.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent']};
                        color: white;
                        border: none;
                        padding: 4px 14px;
                        border-radius: 3px;
                        font-size: 10px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{ opacity: 0.85; }}
                    QPushButton:disabled {{
                        background-color: {c['border']};
                        color: {dim_color};
                    }}
                """)
                btn_install.clicked.connect(
                    lambda _, n=pkg.name: self._do_operation("install", n)
                )
                actions_layout.addWidget(btn_install)

            actions_layout.addStretch()
            self.table.setCellWidget(row, 3, actions_widget)
            self.table.setRowHeight(row, 38)

    def _confirm_uninstall(self, package_name: str):
        """Confirma desinstalacao de pacote"""
        reply = QMessageBox.question(
            self,
            "Confirmar Remocao",
            f"Tem certeza que deseja remover o pacote '{package_name}'?\n\n"
            "Outros pacotes que dependem dele podem parar de funcionar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_operation("uninstall", package_name)

    def _do_operation(self, operation: str, package_name: str,
                      version: str = ""):
        """Executa operacao de pacote em background"""
        op_labels = {
            "install": "Instalando",
            "uninstall": "Removendo",
            "update": "Atualizando",
        }
        label = op_labels.get(operation, operation)
        self._set_loading(True, f"{label} '{package_name}'...")
        self._set_buttons_enabled(False)

        self._worker = _InstallWorker(
            self.service, operation, package_name, version
        )
        self._worker.finished.connect(self._on_operation_done)
        self._worker.start()

    def _on_operation_done(self, result: PackageOperationResult):
        """Callback apos operacao concluida"""
        self._set_loading(False)
        self._set_buttons_enabled(True)

        if result.success:
            QMessageBox.information(
                self, "Sucesso", result.message
            )
            # Recarregar lista
            if self._current_view == "installed":
                self._load_installed()
            else:
                # Refazer pesquisa para atualizar status
                self._on_search()
        else:
            error_msg = result.error
            # Limitar tamanho do erro mostrado
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "\n..."
            QMessageBox.critical(
                self, "Erro",
                f"Falha ao {result.operation} '{result.package_name}':\n\n"
                f"{error_msg}"
            )

    # === Helpers ===

    def _set_loading(self, loading: bool, message: str = ""):
        """Mostra/esconde indicador de loading"""
        if loading:
            self.progress.show()
            self.lbl_status.setText(message or "Processando...")
            self.btn_search.setEnabled(False)
            self.btn_show_installed.setEnabled(False)
        else:
            self.progress.hide()
            self.lbl_status.setText("Pronto")
            self.btn_search.setEnabled(True)
            self.btn_show_installed.setEnabled(True)

    def _set_buttons_enabled(self, enabled: bool):
        """Habilita/desabilita botoes de acao na tabela"""
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 3)
            if widget:
                for btn in widget.findChildren(QPushButton):
                    btn.setEnabled(enabled)
