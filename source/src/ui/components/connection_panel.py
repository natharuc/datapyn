"""
Painel de conexoes - Material Design Flat
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QListWidget, QListWidgetItem, QPushButton, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QByteArray
from PyQt6.QtGui import QAction, QFont, QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
import qtawesome as qta
import os
import re


# Pasta de icones customizados
ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'assets', 'icons', 'db')

# Mapeamento de icones e cores por tipo de banco (fallback para qtawesome)
DB_TYPE_ICONS = {
    'sqlserver': {'icon': 'mdi.database', 'color': '#CC2927'},           # SQL Server - vermelho Microsoft
    'mssql': {'icon': 'mdi.database', 'color': '#CC2927'},               # Alias
    'mysql': {'icon': 'mdi.database-outline', 'color': '#00758F'},       # MySQL - azul
    'mariadb': {'icon': 'mdi.database-marker', 'color': '#C0765A'},      # MariaDB - marrom/coral
    'postgresql': {'icon': 'mdi.database-cog', 'color': '#336791'},      # PostgreSQL - azul
    'postgres': {'icon': 'mdi.database-cog', 'color': '#336791'},        # Alias
    'sqlite': {'icon': 'mdi.file-document-outline', 'color': '#003B57'}, # SQLite - azul escuro
}


def _normalize_db_type(db_type: str) -> str:
    """Normaliza o nome do tipo de banco"""
    db_type_lower = (db_type or '').lower().replace(' ', '').replace('_', '')
    
    if 'sql' in db_type_lower and 'server' in db_type_lower:
        return 'sqlserver'
    elif 'maria' in db_type_lower:
        return 'mariadb'
    elif 'postgre' in db_type_lower:
        return 'postgresql'
    elif 'mysql' in db_type_lower:
        return 'mysql'
    elif 'sqlite' in db_type_lower:
        return 'sqlite'
    
    return db_type_lower


def _load_svg_with_color(svg_path: str, color: str, size: int = 32) -> QIcon:
    """Carrega SVG e aplica cor customizada
    
    Args:
        svg_path: Caminho para o arquivo SVG
        color: Cor em formato hex (#RRGGBB)
        size: Tamanho do icone em pixels
    
    Returns:
        QIcon com a cor aplicada
    """
    try:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Substitui cores no CSS (dentro de <style> ou atributo style)
        # Padroes: fill:#XXXXXX ou fill: #XXXXXX ou fill:rgb(...) etc
        svg_content = re.sub(r'fill\s*:\s*#[0-9a-fA-F]{3,6}', f'fill:{color}', svg_content)
        svg_content = re.sub(r'stroke\s*:\s*#[0-9a-fA-F]{3,6}', f'stroke:{color}', svg_content)
        
        # Substitui cores em atributos (fill="..." e stroke="...")
        svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)
        svg_content = re.sub(r'stroke="[^"]*"', f'stroke="{color}"', svg_content)
        
        # Se nao tinha fill, adiciona no primeiro elemento de path/circle/rect
        if 'fill=' not in svg_content and 'fill:' not in svg_content:
            svg_content = re.sub(r'<(path|circle|rect|polygon)', f'<\\1 fill="{color}"', svg_content)
        
        # Renderiza o SVG
        svg_bytes = QByteArray(svg_content.encode('utf-8'))
        renderer = QSvgRenderer(svg_bytes)
        
        if not renderer.isValid():
            return None
        
        # Cria pixmap e pinta o SVG
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)
        
    except Exception as e:
        print(f"Erro ao carregar SVG {svg_path}: {e}")
        return None


def get_db_icon(db_type: str, custom_color: str = None) -> QIcon:
    """Retorna icone para o tipo de banco
    
    Prioridade:
    1. SVG customizado em assets/icons/db/{db_type}.svg
    2. Icone padrao do qtawesome
    
    Args:
        db_type: Tipo do banco (sqlserver, mysql, etc)
        custom_color: Cor customizada (opcional, sobrescreve padrao)
    
    Returns:
        QIcon com icone do banco
    """
    db_type_normalized = _normalize_db_type(db_type)
    
    # Pega cor padrao ou customizada
    config = DB_TYPE_ICONS.get(db_type_normalized, {'icon': 'mdi.database', 'color': '#64b5f6'})
    color = custom_color if custom_color else config['color']
    
    # Tenta carregar SVG customizado
    svg_path = os.path.join(ICONS_DIR, f'{db_type_normalized}.svg')
    if os.path.exists(svg_path):
        icon = _load_svg_with_color(svg_path, color)
        if icon:
            return icon
    
    # Fallback para qtawesome
    return qta.icon(config['icon'], color=color)


class ConnectionItemWidget(QWidget):
    """Widget customizado para item de conexao com nome e grupo em linhas separadas"""
    
    def __init__(self, name: str, group: str = '', icon: QIcon = None, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # Icone
        if icon:
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(24, 24))
            icon_label.setFixedSize(28, 28)
            layout.addWidget(icon_label)
        
        # Container para textos
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        
        # Nome da conexao (linha principal)
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        text_layout.addWidget(self.name_label)
        
        # Grupo (linha secundaria - menor e cinza)
        if group:
            self.group_label = QLabel(group)
            self.group_label.setStyleSheet("font-size: 10px;")
            text_layout.addWidget(self.group_label)
        
        layout.addWidget(text_container)
        layout.addStretch()


class ConnectionItem(QListWidgetItem):
    """Item de conexao com icone especifico por banco"""
    
    def __init__(self, name: str, config: dict):
        super().__init__()
        self.connection_name = name
        self.config = config
        
        db_type = config.get('db_type', 'SQL Server')
        host = config.get('host', '')
        database = config.get('database', '')
        group = config.get('group', '')
        custom_color = config.get('color', '')
        
        # Icone especifico por tipo de banco (SVG customizado ou qtawesome)
        self.icon = get_db_icon(db_type, custom_color if custom_color else None)
        self.group = group
        
        # Tooltip completo
        self.setToolTip(f"{db_type}\n{host}\n{database}")
        
        # Tamanho para acomodar 2 linhas se tiver grupo
        self.setSizeHint(QSize(250, 48 if group else 36))


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
        self.list_widget.setIconSize(QSize(28, 28))  # Icones maiores
        self.list_widget.setSpacing(2)  # Espacamento entre itens
        self.list_widget.setWordWrap(True)  # Permite quebra de linha
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)  # Nao trunca com "..."
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
            
            # Widget customizado com nome e grupo separados
            widget = ConnectionItemWidget(name, item.group, item.icon)
            self.list_widget.setItemWidget(item, widget)


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
