"""
Painel de conexões

Sidebar lateral com gerenciamento de conexões ao banco de dados.
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QListWidget, QListWidgetItem, QPushButton,
                             QDockWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from .buttons import PrimaryButton, SecondaryButton, DangerButton
from .inputs import StyledLabel

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class ConnectionItem(QListWidgetItem):
    """Item de conexão na lista"""
    
    def __init__(self, name: str, config: dict):
        super().__init__()
        
        self.connection_name = name
        self.config = config
        
        # Texto e tooltip
        self.setText(name)
        
        db_type = config.get('db_type', 'SQL Server')
        host = config.get('host', '')
        database = config.get('database', '')
        self.setToolTip(f"{db_type}\n{host}/{database}")
        
        # Cor personalizada
        color = config.get('color', '')
        if color:
            self.setForeground(QColor(color))


class ActiveConnectionWidget(QGroupBox):
    """Widget mostrando conexão ativa"""
    
    disconnect_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("Conexão Ativa", parent)
        
        self._setup_ui()
        self._setup_style()
        self.set_disconnected()
    
    def _setup_ui(self):
        """Configura UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(8)
        
        # Nome da conexão
        self.name_label = StyledLabel("Nenhuma", 'title')
        layout.addWidget(self.name_label)
        
        # Info (servidor/banco)
        self.info_label = StyledLabel("", 'hint')
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        
        # Botão desconectar
        self.btn_disconnect = DangerButton("Desconectar", 'fa5s.unlink')
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        layout.addWidget(self.btn_disconnect)
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QGroupBox {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #9cdcfe;
                font-weight: bold;
            }
        """)
    
    def set_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Define conexão ativa"""
        self.name_label.setText(name)
        self.name_label.set_style('success')
        
        info_parts = []
        if host:
            info_parts.append(host)
        if database:
            info_parts.append(database)
        if db_type:
            info_parts.append(f"({db_type})")
        
        self.info_label.setText(" / ".join(info_parts))
        self.btn_disconnect.setEnabled(True)
    
    def set_disconnected(self):
        """Define como desconectado"""
        self.name_label.setText("Nenhuma")
        self.name_label.set_style('hint')
        self.info_label.setText("")
        self.btn_disconnect.setEnabled(False)


class ConnectionsList(QGroupBox):
    """Lista de conexões salvas"""
    
    connection_double_clicked = pyqtSignal(str)  # connection_name
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("Conexões Salvas", parent)
        
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self):
        """Configura UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(8)
        
        # Lista de conexões
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #2d2d30;
                border: 1px solid #3e3e42;
                border-radius: 3px;
                color: #cccccc;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #3e3e42;
            }
            QListWidget::item:hover {
                background-color: #3e3e42;
            }
            QListWidget::item:selected {
                background-color: #094771;
            }
        """)
        layout.addWidget(self.list_widget)
        
        # Botões
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)
        
        self.btn_new = PrimaryButton("+ Nova", 'fa5s.plus')
        self.btn_new.clicked.connect(self.new_connection_clicked.emit)
        btn_layout.addWidget(self.btn_new)
        
        self.btn_manage = SecondaryButton("Gerenciar")
        self.btn_manage.clicked.connect(self.manage_connections_clicked.emit)
        btn_layout.addWidget(self.btn_manage)
        
        layout.addLayout(btn_layout)
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QGroupBox {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #9cdcfe;
                font-weight: bold;
            }
        """)
    
    def _on_item_double_clicked(self, item: QListWidgetItem):
        """Emite sinal quando item é clicado duas vezes"""
        if isinstance(item, ConnectionItem):
            self.connection_double_clicked.emit(item.connection_name)
        else:
            conn_name = item.data(Qt.ItemDataRole.UserRole)
            if conn_name:
                self.connection_double_clicked.emit(conn_name)
    
    def refresh(self, connections: list):
        """Atualiza lista de conexões
        
        Args:
            connections: Lista de tuplas (name, config)
        """
        self.list_widget.clear()
        
        for name, config in connections:
            item = ConnectionItem(name, config)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)


class ConnectionPanel(QWidget):
    """Painel de conexões (widget para dock)"""
    
    # Sinais
    connection_requested = pyqtSignal(str)  # connection_name
    disconnect_clicked = pyqtSignal()
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    
    def __init__(self, connection_manager=None, theme_manager=None, parent=None):
        super().__init__(parent)
        
        self.connection_manager = connection_manager
        self.theme_manager = theme_manager
        
        self._setup_ui()
        self._setup_style()
        self._connect_signals()
        
        # Carregar conexões se tiver manager
        if self.connection_manager:
            self.refresh_connections()
    
    def _setup_ui(self):
        """Configura UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        
        # Widget de conexão ativa
        self.active_widget = ActiveConnectionWidget()
        layout.addWidget(self.active_widget)
        
        # Lista de conexões
        self.connections_list = ConnectionsList()
        layout.addWidget(self.connections_list)
        
        layout.addStretch()
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QWidget {
                background-color: #252526;
                color: #cccccc;
            }
        """)
    
    def _connect_signals(self):
        """Conecta sinais internos aos externos"""
        self.active_widget.disconnect_clicked.connect(
            self.disconnect_clicked.emit
        )
        self.connections_list.connection_double_clicked.connect(
            self.connection_requested.emit
        )
        self.connections_list.new_connection_clicked.connect(
            self.new_connection_clicked.emit
        )
        self.connections_list.manage_connections_clicked.connect(
            self.manage_connections_clicked.emit
        )
    
    def set_active_connection(self, name: str, host: str = "", 
                              database: str = "", db_type: str = ""):
        """Define conexão ativa"""
        self.active_widget.set_connection(name, host, database, db_type)
    
    def set_disconnected(self):
        """Define como desconectado"""
        self.active_widget.set_disconnected()
    
    def refresh_connections(self, connections: list = None):
        """Atualiza lista de conexões
        
        Args:
            connections: Lista de tuplas (name, config) ou None para usar connection_manager
        """
        if connections is None and self.connection_manager:
            # Buscar do connection manager
            connections = []
            for conn_name in self.connection_manager.get_saved_connections():
                config = self.connection_manager.get_connection_config(conn_name)
                if config:
                    connections.append((conn_name, config))
        
        if connections:
            self.connections_list.refresh(connections)
