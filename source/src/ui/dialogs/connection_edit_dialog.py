"""
Diálogo unificado para criar e editar conexões
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QFormLayout, QFrame,
    QLabel, QColorDialog, QMessageBox, QProgressDialog
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
    """Worker para testar conexão em background"""
    
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, db_type, host, port, database, username, password, use_windows_auth=False):
        super().__init__()
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth
    
    def run(self):
        try:
            connector = DatabaseConnector()
            
            kwargs = {}
            if self.use_windows_auth:
                kwargs['use_windows_auth'] = True
            
            connector.connect(
                db_type=self.db_type,
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username if not self.use_windows_auth else '',
                password=self.password if not self.use_windows_auth else '',
                **kwargs
            )
            
            connector.disconnect()
            self.finished.emit(True, "Conexão testada com sucesso!")
            
        except Exception as e:
            self.finished.emit(False, f"Erro: {str(e)}")


class ConnectionEditDialog(QDialog):
    """Diálogo unificado para criar e editar conexões"""
    
    def __init__(self, connection_name: str = None, config: dict = None, 
                 groups: dict = None, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.connection_name = connection_name or ''
        self.config = config or {}
        self.groups = groups or {}
        self.theme_manager = theme_manager or ThemeManager()
        self.selected_color = self.config.get('color', '')
        self.is_new = connection_name is None or connection_name == ''
        self.connector = None  # Para teste de conexão
        
        title = "Nova Conexão" if self.is_new else f"Editar Conexão: {connection_name}"
        self.setWindowTitle(title)
        self.resize(500, 650)
        
        self._setup_ui()
        if not self.is_new:
            self._load_config()
    
    def _setup_ui(self):
        """Configura interface"""
        layout = QVBoxLayout(self)
        
        # Aplicar tema
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())
        
        # Grupo de informações básicas
        basic_group = QFrame()
        basic_group.setFrameShape(QFrame.Shape.StyledPanel)
        basic_group_layout = QVBoxLayout(basic_group)
        basic_group_layout.setContentsMargins(12, 12, 12, 12)
        
        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon('mdi.database-cog', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("INFORMAÇÕES DA CONEXÃO")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        basic_group_layout.addLayout(header)
        
        basic_layout = QFormLayout()
        basic_group_layout.addLayout(basic_layout)
        
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Nome para identificar a conexão")
        basic_layout.addRow("Nome:", self.txt_name)
        
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(['sqlserver', 'mysql', 'mariadb', 'postgresql'])
        self.cmb_type.currentTextChanged.connect(self._on_db_type_changed)
        basic_layout.addRow("Tipo de Banco:", self.cmb_type)
        
        self.txt_host = QLineEdit()
        self.txt_host.setPlaceholderText("localhost ou IP do servidor")
        basic_layout.addRow("Host:", self.txt_host)
        
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(1433)
        basic_layout.addRow("Porta:", self.spin_port)
        
        self.txt_database = QLineEdit()
        self.txt_database.setPlaceholderText("Nome do banco (opcional)")
        basic_layout.addRow("Database:", self.txt_database)
        
        layout.addWidget(basic_group)
        
        # Grupo de autenticação
        auth_group = QFrame()
        auth_group.setFrameShape(QFrame.Shape.StyledPanel)
        auth_group_layout = QVBoxLayout(auth_group)
        auth_group_layout.setContentsMargins(12, 12, 12, 12)
        
        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon('mdi.lock', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("AUTENTICAÇÃO")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        auth_group_layout.addLayout(header)
        
        auth_layout = QFormLayout()
        auth_group_layout.addLayout(auth_layout)
        
        self.chk_windows_auth = QCheckBox("Usar Windows Authentication")
        self.chk_windows_auth.stateChanged.connect(self._toggle_windows_auth)
        auth_layout.addRow(self.chk_windows_auth)
        
        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("Usuário do banco")
        auth_layout.addRow("Usuário:", self.txt_username)
        
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("Senha")
        auth_layout.addRow("Senha:", self.txt_password)
        
        self.chk_save_password = QCheckBox("Salvar senha (não recomendado)")
        auth_layout.addRow(self.chk_save_password)
        
        layout.addWidget(auth_group)
        
        # Grupo de organização
        org_group = QFrame()
        org_group.setFrameShape(QFrame.Shape.StyledPanel)
        org_group_layout = QVBoxLayout(org_group)
        org_group_layout.setContentsMargins(12, 12, 12, 12)
        
        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon('mdi.folder-cog', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("ORGANIZAÇÃO")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        org_group_layout.addLayout(header)
        
        org_layout = QFormLayout()
        org_group_layout.addLayout(org_layout)
        
        self.cmb_group = QComboBox()
        self.cmb_group.addItem('[Sem grupo]', '')
        for group_name in self.groups.keys():
            self.cmb_group.addItem(group_name, group_name)
        org_layout.addRow("Grupo:", self.cmb_group)
        
        # Cor
        color_layout = QHBoxLayout()
        self.lbl_color = QLabel("Nenhuma")
        self.lbl_color.setMinimumWidth(100)
        self.lbl_color.setStyleSheet("border: 1px solid #555; padding: 3px;")
        btn_choose_color = QPushButton("Escolher Cor")
        btn_choose_color.clicked.connect(self._choose_color)
        btn_clear_color = QPushButton("Limpar")
        btn_clear_color.clicked.connect(self._clear_color)
        color_layout.addWidget(self.lbl_color)
        color_layout.addWidget(btn_choose_color)
        color_layout.addWidget(btn_clear_color)
        org_layout.addRow("Cor:", color_layout)
        
        layout.addWidget(org_group)
        
        # Status de teste
        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)
        
        # Botões
        buttons_layout = QHBoxLayout()
        
        btn_test = QPushButton(" Testar Conexão")
        btn_test.setObjectName("btnTest")
        if HAS_QTAWESOME:
            btn_test.setIcon(qta.icon('mdi.lan-connect', color='white'))
        btn_test.clicked.connect(self._test_connection)
        buttons_layout.addWidget(btn_test)
        
        buttons_layout.addStretch()
        
        btn_save = QPushButton(" Salvar")
        if HAS_QTAWESOME:
            btn_save.setIcon(qta.icon('mdi.content-save', color='white'))
        btn_save.clicked.connect(self._on_save)
        buttons_layout.addWidget(btn_save)
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(btn_cancel)
        
        layout.addLayout(buttons_layout)
        
        # Ajustes iniciais
        self._toggle_windows_auth_visibility()
    
    def _load_config(self):
        """Carrega configuração atual"""
        self.txt_name.setText(self.connection_name)
        
        db_type = self.config.get('db_type', 'sqlserver')
        index = self.cmb_type.findText(db_type)
        if index >= 0:
            self.cmb_type.setCurrentIndex(index)
        
        self.txt_host.setText(self.config.get('host', ''))
        self.spin_port.setValue(self.config.get('port', 1433))
        self.txt_database.setText(self.config.get('database', ''))
        
        use_windows_auth = self.config.get('use_windows_auth', False)
        self.chk_windows_auth.setChecked(use_windows_auth)
        
        self.txt_username.setText(self.config.get('username', ''))
        
        if 'password' in self.config:
            self.txt_password.setText(self.config.get('password', ''))
            self.chk_save_password.setChecked(True)
        
        # Grupo
        group = self.config.get('group', '')
        index = self.cmb_group.findData(group)
        if index >= 0:
            self.cmb_group.setCurrentIndex(index)
        
        # Cor
        if self.selected_color:
            self._update_color_label()
        
        self._toggle_windows_auth()
        self._toggle_windows_auth_visibility()
    
    def _on_db_type_changed(self):
        """Ao mudar tipo de banco"""
        db_type = self.cmb_type.currentText()
        
        # Ajustar porta padrão
        default_ports = {
            'sqlserver': 1433,
            'mysql': 3306,
            'mariadb': 3306,
            'postgresql': 5432
        }
        self.spin_port.setValue(default_ports.get(db_type, 1433))
        
        self._toggle_windows_auth_visibility()
    
    def _toggle_windows_auth(self):
        """Toggle de campos de autenticação"""
        is_windows_auth = self.chk_windows_auth.isChecked()
        self.txt_username.setEnabled(not is_windows_auth)
        self.txt_password.setEnabled(not is_windows_auth)
        self.chk_save_password.setEnabled(not is_windows_auth)
    
    def _toggle_windows_auth_visibility(self):
        """Mostra/esconde Windows Auth baseado no tipo de banco"""
        is_sqlserver = self.cmb_type.currentText() == 'sqlserver'
        self.chk_windows_auth.setVisible(is_sqlserver)
        if not is_sqlserver:
            self.chk_windows_auth.setChecked(False)
    
    def _choose_color(self):
        """Escolhe cor para a conexão"""
        current_color = QColor(self.selected_color) if self.selected_color else QColor()
        color = QColorDialog.getColor(current_color, self, "Escolher Cor")
        
        if color.isValid():
            self.selected_color = color.name()
            self._update_color_label()
    
    def _clear_color(self):
        """Remove cor"""
        self.selected_color = ''
        self.lbl_color.setText("Nenhuma")
        self.lbl_color.setStyleSheet("border: 1px solid #555; padding: 3px;")
    
    def _update_color_label(self):
        """Atualiza label de cor"""
        if self.selected_color:
            self.lbl_color.setText(self.selected_color)
            self.lbl_color.setStyleSheet(
                f"background-color: {self.selected_color}; "
                f"border: 1px solid #555; padding: 3px; color: white;"
            )
    
    def _test_connection(self):
        """Testa a conexão com as configurações atuais em background"""
        # Criar loading dialog
        db_name = self.txt_database.text() or self.txt_host.text()
        self.loading_dialog = QProgressDialog(self)
        self.loading_dialog.setWindowTitle("Testando Conexão")
        self.loading_dialog.setLabelText(f"Testando conexão com {db_name}...")
        self.loading_dialog.setCancelButton(None)
        self.loading_dialog.setRange(0, 0)  # Indeterminate progress
        self.loading_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.loading_dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.loading_dialog.setMinimumWidth(300)
        self.loading_dialog.show()
        
        # Criar e iniciar worker
        self.test_worker = ConnectionTestWorker(
            db_type=self.cmb_type.currentText(),
            host=self.txt_host.text(),
            port=self.spin_port.value(),
            database=self.txt_database.text(),
            username=self.txt_username.text(),
            password=self.txt_password.text(),
            use_windows_auth=self.chk_windows_auth.isChecked()
        )
        self.test_worker.finished.connect(self._on_test_finished)
        self.test_worker.start()
    
    def _on_test_finished(self, success: bool, message: str):
        """Callback quando teste de conexão termina"""
        self.loading_dialog.close()
        
        if success:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        else:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #f48771;")
    
    def _on_save(self):
        """Valida e salva"""
        name = self.txt_name.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Atenção", "Por favor, informe um nome para a conexão.")
            return
        
        if not self.txt_host.text().strip():
            QMessageBox.warning(self, "Atenção", "Por favor, informe o host.")
            return
        
        self.accept()
    
    def get_result(self):
        """Retorna nome e configuração editados"""
        name = self.txt_name.text().strip()
        
        config = {
            'db_type': self.cmb_type.currentText(),
            'host': self.txt_host.text().strip(),
            'port': self.spin_port.value(),
            'database': self.txt_database.text().strip(),
            'username': self.txt_username.text().strip(),
            'use_windows_auth': self.chk_windows_auth.isChecked(),
            'group': self.cmb_group.currentData(),
            'color': self.selected_color,
            'save_password': self.chk_save_password.isChecked()
        }
        
        if self.chk_save_password.isChecked():
            config['password'] = self.txt_password.text()
        
        return name, config
    
    def get_connection_name(self) -> str:
        """Retorna o nome da conexão (compatibilidade)"""
        return self.txt_name.text().strip()
    
    def get_config(self) -> dict:
        """Retorna a configuração (compatibilidade)"""
        _, config = self.get_result()
        return config
