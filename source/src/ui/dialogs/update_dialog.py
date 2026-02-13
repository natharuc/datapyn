"""
Dialog para exibir informacoes sobre atualizacoes disponiveis
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
import logging

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """Dialog para informar sobre atualizacoes disponiveis"""

    def __init__(self, current_version: str, new_version: str, release_notes: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.new_version = new_version
        self.release_notes = release_notes
        self.should_download = False

        self.setWindowTitle("Atualizacao Disponivel")
        self.setMinimumSize(QSize(500, 400))
        self.setModal(True)

        self._init_ui()

    def _init_ui(self):
        """Inicializa a interface"""
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Titulo
        title_label = QLabel(f"Nova versao disponivel: {self.new_version}")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Versao atual
        current_label = QLabel(f"Versao atual: {self.current_version}")
        layout.addWidget(current_label)

        # Notas da release
        notes_label = QLabel("Novidades:")
        notes_label_font = QFont()
        notes_label_font.setBold(True)
        notes_label.setFont(notes_label_font)
        layout.addWidget(notes_label)

        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMarkdown(self.release_notes)
        self.notes_text.setMaximumHeight(200)
        layout.addWidget(self.notes_text)

        # Botoes
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.later_button = QPushButton("Mais Tarde")
        self.later_button.clicked.connect(self.reject)
        button_layout.addWidget(self.later_button)

        self.download_button = QPushButton("Baixar e Instalar")
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._on_download)
        button_layout.addWidget(self.download_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _on_download(self):
        """Usuario escolheu baixar a atualizacao"""
        self.should_download = True
        self.accept()


class UpdateDownloadDialog(QDialog):
    """Dialog para mostrar progresso do download"""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.version = version
        self.installer_path = None

        self.setWindowTitle("Baixando Atualizacao")
        self.setMinimumSize(QSize(400, 150))
        self.setModal(True)

        # Impedir fechamento durante download
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self._init_ui()

    def _init_ui(self):
        """Inicializa a interface"""
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Titulo
        title_label = QLabel(f"Baixando DataPyn {self.version}...")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Barra de progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Label de status
        self.status_label = QLabel("Iniciando download...")
        layout.addWidget(self.status_label)

        # Botao cancelar (inicialmente desabilitado)
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def update_progress(self, percentage: int):
        """Atualiza barra de progresso"""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"Baixando... {percentage}%")

    def download_complete(self, installer_path: str):
        """Marca download como completo"""
        self.installer_path = installer_path
        self.progress_bar.setValue(100)
        self.status_label.setText("Download concluido!")
        self.accept()

    def download_failed(self, error_message: str):
        """Marca download como falho"""
        self.status_label.setText(f"Erro: {error_message}")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Fechar")

        QMessageBox.critical(
            self, "Erro no Download", f"Falha ao baixar atualizacao:\n\n{error_message}"
        )
