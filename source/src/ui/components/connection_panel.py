"""
Painel de conexoes - Material Design Flat
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QListWidget, QListWidgetItem, QPushButton, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
import qtawesome as qta


class ConnectionItem(QListWidgetItem):
    """Item de conexao"""
    
    def __init__(self, name: str, config: dict):
        super().__init__()
        self.connection_name = name
        self.config = config
        
        # Icone + texto - usa cor da conexao se definida
        icon_color = config.get('color', '#64b5f6')
        icon = qta.icon('mdi.database', color=icon_color)
        self.setIcon(icon)
        self.setText(name)
        
        db_type = config.get('db_type', 'SQL Server')
        host = config.get('host', '')
        database = config.get('database', '')
        self.setToolTip(f"{db_type}\n{host}/{database}")


class ActiveConnectionWidget(QFrame):
    """Widget de conexao ativa - flat design"""
    
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
        
        # Header com icone
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('mdi.connection', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("CONEXAO ATIVA")
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
        
        # Botao
        self.btn_disconnect = QPushButton(" Desconectar")
        self.btn_disconnect.setIcon(qta.icon('mdi.link-off', color='white'))
        self.btn_disconnect.setObjectName("danger")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        layout.addWidget(self.btn_disconnect)
    
    def set_connection(self, name: str, host: str = "", database: str = "", db_type: str = ""):
        """Define conexao"""
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
    """Lista de conexoes - flat design"""
    
    connection_double_clicked = pyqtSignal(str)
    new_tab_connection_requested = pyqtSignal(str)  # Conectar sempre em nova aba
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str)  # Sinal para editar conexão diretamente
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)  # Volta margem normal
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('mdi.database-cog', color='#64b5f6').pixmap(20, 20))
        header.addWidget(icon_label)
        title = QLabel("CONEXOES SALVAS")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Lista
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Context menu
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)
        
        # Botoes
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
        """Emite sinal quando item e clicado duas vezes"""
        from PyQt6.QtGui import QGuiApplication
        
        conn_name = None
        if isinstance(item, ConnectionItem):
            conn_name = item.connection_name
        else:
            conn_name = item.data(Qt.ItemDataRole.UserRole)
        
        if conn_name:
            # Verificar se CTRL está pressionado
            modifiers = QGuiApplication.keyboardModifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                # CTRL pressionado - sempre nova aba
                self.new_tab_connection_requested.emit(conn_name)
            else:
                # Comportamento normal
                self.connection_double_clicked.emit(conn_name)
    
    def _show_context_menu(self, pos):
        """Mostra menu de contexto na conexao"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if not conn_name:
            return
        
        menu = QMenu(self)
        
        connect_action = QAction(qta.icon('mdi.lan-connect', color='#4ec9b0'), " Conectar", self)
        connect_action.triggered.connect(lambda: self.connection_double_clicked.emit(conn_name))
        menu.addAction(connect_action)
        
        new_tab_action = QAction(qta.icon('mdi.tab-plus', color='#4ec9b0'), " Conectar em Nova Aba", self)
        new_tab_action.triggered.connect(lambda: self.new_tab_connection_requested.emit(conn_name))
        menu.addAction(new_tab_action)
        
        menu.addSeparator()
        
        edit_action = QAction(qta.icon('mdi.pencil', color='#569cd6'), " Editar", self)
        edit_action.triggered.connect(lambda: self._edit_connection(conn_name))
        menu.addAction(edit_action)
        
        menu.exec(self.list_widget.mapToGlobal(pos))
    
    def _edit_connection(self, conn_name: str):
        """Emite sinal para editar conexao diretamente"""
        self.edit_connection_clicked.emit(conn_name)
    
    def refresh(self, connections: list):
        """Atualiza lista de conexoes
        
        Args:
            connections: Lista de tuplas (name, config)
        """
        self.list_widget.clear()
        
        for name, config in connections:
            item = ConnectionItem(name, config)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)


class ConnectionPanel(QWidget):
    """Painel de conexoes (widget para dock)"""
    
    # Sinais
    connection_requested = pyqtSignal(str)  # connection_name
    new_tab_connection_requested = pyqtSignal(str)  # connection_name para nova aba
    disconnect_clicked = pyqtSignal()
    new_connection_clicked = pyqtSignal()
    manage_connections_clicked = pyqtSignal()
    edit_connection_clicked = pyqtSignal(str)  # connection_name para editar
    
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
        layout.setContentsMargins(10, 10, 10, 10)  # Padding geral de 10px em todos os lados
        
        self.active_widget = ActiveConnectionWidget()
        self.active_widget.setMaximumHeight(150)  # Fixa altura da conexão ativa
        layout.addWidget(self.active_widget)
        
        self.connections_list = ConnectionsList()
        # Faz a lista ocupar todo espaço restante
        layout.addWidget(self.connections_list, 1)  # stretch=1
        
        # Remove addStretch() para deixar connections_list ocupar tudo
    
    def _connect_signals(self):
        """Conecta sinais internos aos externos"""
        self.active_widget.disconnect_clicked.connect(
            self.disconnect_clicked.emit
        )
        self.connections_list.connection_double_clicked.connect(
            self.connection_requested.emit
        )
        self.connections_list.new_tab_connection_requested.connect(
            self.new_tab_connection_requested.emit
        )
        self.connections_list.new_connection_clicked.connect(
            self.new_connection_clicked.emit
        )
        self.connections_list.manage_connections_clicked.connect(
            self.manage_connections_clicked.emit
        )
        self.connections_list.edit_connection_clicked.connect(
            self.edit_connection_clicked.emit
        )
    
    def set_active_connection(self, name: str, host: str = "", 
                              database: str = "", db_type: str = ""):
        """Define conexao ativa"""
        self.active_widget.set_connection(name, host, database, db_type)
    
    def set_disconnected(self):
        """Define como desconectado"""
        self.active_widget.set_disconnected()
    
    def refresh_connections(self, connections: list = None):
        """Atualiza lista de conexoes
        
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
