"""
Painel de conexões - Material Design Flat
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QListWidget, QListWidgetItem, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal
import qtawesome as qta


class ConnectionItem(QListWidgetItem):
    """Item de conexão"""
    
    def __init__(self, name: str, config: dict):
        super().__init__()
        self.connection_name = name
        self.config = config
        
        # Ícone + texto
        icon = qta.icon('mdi.database', color='#64b5f6')
        self.setIcon(icon)
        self.setText(name)
        
        db_type = config.get('db_type', 'SQL Server')
        host = config.get('host', '')
        database = config.get('database', '')
        self.setToolTip(f"{db_type}\n{host}/{database}")


class ActiveConnectionWidget(QFrame):
    """Widget de conexão ativa - flat design"""
    
    disconnect_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()
        self.set_disconnected()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header com ícone
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('mdi.connection', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("CONEXÃO ATIVA")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Nome
        self.name_label = QLabel("Nenhuma")
        self.name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.name_label)
        
        # Info
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.info_label)
        
        # Botão
        self.btn_disconnect = QPushButton(" Desconectar")
        self.btn_disconnect.setIcon(qta.icon('mdi.link-off', color='white'))
        self.btn_disconnect.setObjectName("danger")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        layout.addWidget(self.btn_disconnect)
    
    def set_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Define conexão"""
        self.name_label.setText(name)
        
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
        self.info_label.setText("")
        self.btn_disconnect.setEnabled(False)


class ConnectionsList(QFrame):
    """Lista de conexões - flat design"""
    
    connection_double_clicked = pyqtSignal(str)
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('mdi.database-cog', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("CONEXÕES SALVAS")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Lista
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)
        
        # Botões
        btn_layout = QHBoxLayout()
        
        self.btn_new = QPushButton(" Nova")
        self.btn_new.setIcon(qta.icon('mdi.plus-circle', color='white'))
        self.btn_new.setObjectName("primary")
        self.btn_new.clicked.connect(self.new_connection_clicked.emit)
        btn_layout.addWidget(self.btn_new)
        
        self.btn_manage = QPushButton(" Gerenciar")
        self.btn_manage.setIcon(qta.icon('mdi.cog', color='white'))
        self.btn_manage.clicked.connect(self.manage_connections_clicked.emit)
        btn_layout.addWidget(self.btn_manage)
        
        layout.addLayout(btn_layout)
    
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
        self._connect_signals()
        
        if self.connection_manager:
            self.refresh_connections()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.active_widget = ActiveConnectionWidget()
        layout.addWidget(self.active_widget)
        
        self.connections_list = ConnectionsList()
        layout.addWidget(self.connections_list)
        
        layout.addStretch()
    
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
