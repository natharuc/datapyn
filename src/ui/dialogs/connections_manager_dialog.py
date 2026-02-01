"""
Diálogo de gerenciamento de conexões salvas
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, 
    QTreeWidgetItem, QMenu, QInputDialog, QMessageBox, QSplitter,
    QWidget, QLabel, QFormLayout, QLineEdit, QSpinBox, QComboBox,
    QCheckBox, QColorDialog, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QAction
from typing import Optional

from src.core.theme_manager import ThemeManager

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class ConnectionsManagerDialog(QDialog):
    """Diálogo para gerenciar conexões salvas"""
    
    connection_selected = pyqtSignal(str, dict)  # nome, config
    
    def __init__(self, connection_manager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.theme_manager = theme_manager or ThemeManager()
        self.selected_connection = None
        self.selected_group = None
        
        self.setWindowTitle("Gerenciar Conexões")
        self.resize(900, 600)
        
        self._setup_ui()
        self._load_connections()
    
    def _setup_ui(self):
        """Configura interface"""
        layout = QVBoxLayout(self)
        
        # Aplicar tema
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())
        
        # Splitter para árvore e detalhes
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Painel esquerdo: árvore de conexões
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar de grupos
        toolbar_layout = QHBoxLayout()
        
        btn_new_group = QPushButton("Novo Grupo")
        if HAS_QTAWESOME:
            btn_new_group.setIcon(qta.icon('fa5s.folder-plus', color='#4ec9b0'))
        btn_new_group.clicked.connect(self._new_group)
        toolbar_layout.addWidget(btn_new_group)
        
        btn_new_conn = QPushButton("Nova Conexão")
        if HAS_QTAWESOME:
            btn_new_conn.setIcon(qta.icon('fa5s.plus-circle', color='#569cd6'))
        btn_new_conn.clicked.connect(self._new_connection)
        toolbar_layout.addWidget(btn_new_conn)
        
        toolbar_layout.addStretch()
        left_layout.addLayout(toolbar_layout)
        
        # Árvore de conexões
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Conexões"])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        left_layout.addWidget(self.tree)
        
        splitter.addWidget(left_panel)
        
        # Painel direito: detalhes da conexão
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Grupo de informações
        info_group = QGroupBox("Detalhes da Conexão")
        info_layout = QFormLayout(info_group)
        
        self.lbl_name = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_host = QLabel("-")
        self.lbl_database = QLabel("-")
        self.lbl_username = QLabel("-")
        self.lbl_group = QLabel("-")
        self.lbl_created = QLabel("-")
        self.lbl_last_used = QLabel("-")
        
        info_layout.addRow("Nome:", self.lbl_name)
        info_layout.addRow("Tipo:", self.lbl_type)
        info_layout.addRow("Host:", self.lbl_host)
        info_layout.addRow("Database:", self.lbl_database)
        info_layout.addRow("Usuário:", self.lbl_username)
        info_layout.addRow("Grupo:", self.lbl_group)
        info_layout.addRow("Criado em:", self.lbl_created)
        info_layout.addRow("Último uso:", self.lbl_last_used)
        
        right_layout.addWidget(info_group)
        
        # Botões de ação
        actions_layout = QHBoxLayout()
        
        self.btn_connect = QPushButton("Conectar")
        if HAS_QTAWESOME:
            self.btn_connect.setIcon(qta.icon('fa5s.plug', color='#4ec9b0'))
        self.btn_connect.clicked.connect(self._connect_selected)
        self.btn_connect.setEnabled(False)
        actions_layout.addWidget(self.btn_connect)
        
        self.btn_edit = QPushButton("Editar")
        if HAS_QTAWESOME:
            self.btn_edit.setIcon(qta.icon('fa5s.edit', color='#569cd6'))
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_edit.setEnabled(False)
        actions_layout.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("Excluir")
        if HAS_QTAWESOME:
            self.btn_delete.setIcon(qta.icon('fa5s.trash', color='#f48771'))
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_delete.setEnabled(False)
        actions_layout.addWidget(self.btn_delete)
        
        right_layout.addLayout(actions_layout)
        right_layout.addStretch()
        
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 500])
        
        layout.addWidget(splitter)
        
        # Botões do diálogo
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.reject)
        buttons_layout.addWidget(btn_close)
        
        layout.addLayout(buttons_layout)
    
    def _load_connections(self):
        """Carrega conexões na árvore"""
        self.tree.clear()
        
        # Carregar grupos
        groups = self.connection_manager.get_groups()
        group_items = {}
        
        # Criar items de grupos
        for group_name, group_data in groups.items():
            item = QTreeWidgetItem([group_name])
            item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'group', 'name': group_name})
            
            if HAS_QTAWESOME:
                item.setIcon(0, qta.icon('fa5s.folder', color='#dcdcaa'))
            
            # Aplicar cor se definida
            if group_data.get('color'):
                color = QColor(group_data['color'])
                item.setForeground(0, QBrush(color))
            
            group_items[group_name] = item
            self.tree.addTopLevelItem(item)
        
        # Carregar conexões
        all_connections = self.connection_manager.saved_configs.get('connections', {})
        
        for conn_name, conn_config in all_connections.items():
            group = conn_config.get('group', '')
            
            item = QTreeWidgetItem([conn_name])
            item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'connection', 'name': conn_name})
            
            if HAS_QTAWESOME:
                db_type = conn_config.get('db_type', '')
                icon_color = '#569cd6'
                if db_type == 'sqlserver':
                    icon_color = '#cc3e44'
                elif db_type == 'mysql':
                    icon_color = '#00758f'
                elif db_type == 'postgresql':
                    icon_color = '#336791'
                
                item.setIcon(0, qta.icon('fa5s.database', color=icon_color))
            
            # Aplicar cor se definida
            if conn_config.get('color'):
                color = QColor(conn_config['color'])
                item.setForeground(0, QBrush(color))
            
            # Adicionar ao grupo ou raiz
            if group and group in group_items:
                group_items[group].addChild(item)
                group_items[group].setExpanded(True)
            else:
                self.tree.addTopLevelItem(item)
        
        self.tree.expandAll()
    
    def _on_item_clicked(self, item, column):
        """Ao clicar em um item"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        if data and data['type'] == 'connection':
            self.selected_connection = data['name']
            self.selected_group = None
            self._show_connection_details(data['name'])
            self.btn_connect.setEnabled(True)
            self.btn_edit.setEnabled(True)
            self.btn_delete.setEnabled(True)
        elif data and data['type'] == 'group':
            self.selected_group = data['name']
            self.selected_connection = None
            self._clear_connection_details()
            self.btn_connect.setEnabled(False)
            self.btn_edit.setEnabled(True)
            self.btn_delete.setEnabled(True)
    
    def _on_item_double_clicked(self, item, column):
        """Ao dar duplo clique"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data['type'] == 'connection':
            self._connect_selected()
    
    def _show_connection_details(self, name: str):
        """Mostra detalhes de uma conexão"""
        config = self.connection_manager.get_connection_config(name)
        if not config:
            return
        
        self.lbl_name.setText(name)
        self.lbl_type.setText(config.get('db_type', '-').upper())
        self.lbl_host.setText(f"{config.get('host', '-')}:{config.get('port', '-')}")
        self.lbl_database.setText(config.get('database', '-'))
        
        username = config.get('username', '-')
        if config.get('use_windows_auth'):
            username = '[Windows Authentication]'
        self.lbl_username.setText(username)
        
        self.lbl_group.setText(config.get('group', '[Sem grupo]'))
        
        created = config.get('created_at', '-')
        if created and created != '-':
            created = created.split('T')[0] + ' ' + created.split('T')[1][:8]
        self.lbl_created.setText(created)
        
        last_used = config.get('last_used') or 'Nunca'
        if last_used and last_used != 'Nunca':
            last_used = last_used.split('T')[0] + ' ' + last_used.split('T')[1][:8]
        self.lbl_last_used.setText(last_used)
    
    def _clear_connection_details(self):
        """Limpa detalhes"""
        self.lbl_name.setText("-")
        self.lbl_type.setText("-")
        self.lbl_host.setText("-")
        self.lbl_database.setText("-")
        self.lbl_username.setText("-")
        self.lbl_group.setText("-")
        self.lbl_created.setText("-")
        self.lbl_last_used.setText("-")
    
    def _show_context_menu(self, position):
        """Mostra menu de contexto"""
        item = self.tree.itemAt(position)
        if not item:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        menu = QMenu(self)
        
        if data['type'] == 'connection':
            act_connect = QAction("Conectar", self)
            if HAS_QTAWESOME:
                act_connect.setIcon(qta.icon('fa5s.plug'))
            act_connect.triggered.connect(self._connect_selected)
            menu.addAction(act_connect)
            
            menu.addSeparator()
            
            act_edit = QAction("Editar", self)
            if HAS_QTAWESOME:
                act_edit.setIcon(qta.icon('fa5s.edit'))
            act_edit.triggered.connect(self._edit_selected)
            menu.addAction(act_edit)
            
            act_duplicate = QAction("Duplicar", self)
            if HAS_QTAWESOME:
                act_duplicate.setIcon(qta.icon('fa5s.copy'))
            act_duplicate.triggered.connect(self._duplicate_connection)
            menu.addAction(act_duplicate)
            
            menu.addSeparator()
            
            act_delete = QAction("Excluir", self)
            if HAS_QTAWESOME:
                act_delete.setIcon(qta.icon('fa5s.trash'))
            act_delete.triggered.connect(self._delete_selected)
            menu.addAction(act_delete)
        
        elif data['type'] == 'group':
            act_rename = QAction("Renomear Grupo", self)
            if HAS_QTAWESOME:
                act_rename.setIcon(qta.icon('fa5s.i-cursor'))
            act_rename.triggered.connect(self._rename_group)
            menu.addAction(act_rename)
            
            act_color = QAction("Mudar Cor", self)
            if HAS_QTAWESOME:
                act_color.setIcon(qta.icon('fa5s.palette'))
            act_color.triggered.connect(self._change_group_color)
            menu.addAction(act_color)
            
            menu.addSeparator()
            
            act_delete = QAction("Excluir Grupo", self)
            if HAS_QTAWESOME:
                act_delete.setIcon(qta.icon('fa5s.trash'))
            act_delete.triggered.connect(self._delete_selected)
            menu.addAction(act_delete)
        
        menu.exec(self.tree.viewport().mapToGlobal(position))
    
    def _new_group(self):
        """Cria novo grupo"""
        name, ok = QInputDialog.getText(self, "Novo Grupo", "Nome do grupo:")
        if ok and name:
            if name in self.connection_manager.get_groups():
                QMessageBox.warning(self, "Aviso", "Já existe um grupo com este nome!")
                return
            
            self.connection_manager.create_group(name)
            self._load_connections()
    
    def _rename_group(self):
        """Renomeia grupo selecionado"""
        if not self.selected_group:
            return
        
        new_name, ok = QInputDialog.getText(
            self, "Renomear Grupo", "Novo nome:", text=self.selected_group
        )
        if ok and new_name and new_name != self.selected_group:
            if new_name in self.connection_manager.get_groups():
                QMessageBox.warning(self, "Aviso", "Já existe um grupo com este nome!")
                return
            
            self.connection_manager.rename_group(self.selected_group, new_name)
            self.selected_group = new_name
            self._load_connections()
    
    def _change_group_color(self):
        """Muda cor do grupo"""
        if not self.selected_group:
            return
        
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            groups = self.connection_manager.get_groups()
            if self.selected_group in groups:
                groups[self.selected_group]['color'] = color.name()
                self.connection_manager._save_configs()
                self._load_connections()
    
    def _new_connection(self):
        """Cria nova conexão"""
        from .connection_edit_dialog import ConnectionEditDialog
        
        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self
        )
        
        if dialog.exec():
            name, config = dialog.get_result()
            
            self.connection_manager.save_connection_config(
                name,
                config['db_type'],
                config['host'],
                config['port'],
                config['database'],
                config.get('username', ''),
                config.get('save_password', False),
                config.get('password', ''),
                config.get('group', ''),
                config.get('use_windows_auth', False),
                config.get('color', '')
            )
            
            self._load_connections()
            QMessageBox.information(self, "Sucesso", f"Conexão '{name}' salva com sucesso!")
    
    def _edit_selected(self):
        """Edita conexão ou grupo selecionado"""
        if self.selected_connection:
            self._edit_connection()
        elif self.selected_group:
            self._rename_group()
    
    def _edit_connection(self):
        """Edita conexão selecionada"""
        if not self.selected_connection:
            return
        
        from .connection_edit_dialog import ConnectionEditDialog
        
        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return
        
        dialog = ConnectionEditDialog(
            self.selected_connection, 
            config, 
            self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self
        )
        
        if dialog.exec():
            new_name, new_config = dialog.get_result()
            
            self.connection_manager.update_connection_config(
                self.selected_connection,
                new_name,
                new_config['db_type'],
                new_config['host'],
                new_config['port'],
                new_config['database'],
                new_config.get('username', ''),
                new_config.get('save_password', False),
                new_config.get('password', ''),
                new_config.get('group', ''),
                new_config.get('use_windows_auth', False),
                new_config.get('color', '')
            )
            
            self.selected_connection = new_name
            self._load_connections()
            QMessageBox.information(self, "Sucesso", "Conexão atualizada com sucesso!")
    
    def _duplicate_connection(self):
        """Duplica conexão selecionada"""
        if not self.selected_connection:
            return
        
        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return
        
        new_name, ok = QInputDialog.getText(
            self, "Duplicar Conexão", 
            "Nome da nova conexão:", 
            text=f"{self.selected_connection} (cópia)"
        )
        
        if ok and new_name:
            if new_name in self.connection_manager.saved_configs.get('connections', {}):
                QMessageBox.warning(self, "Aviso", "Já existe uma conexão com este nome!")
                return
            
            self.connection_manager.save_connection_config(
                new_name,
                config['db_type'],
                config['host'],
                config['port'],
                config['database'],
                config.get('username', ''),
                False,  # Não duplicar senha
                '',
                config.get('group', ''),
                config.get('use_windows_auth', False),
                config.get('color', '')
            )
            
            self._load_connections()
            QMessageBox.information(self, "Sucesso", f"Conexão '{new_name}' criada!")
    
    def _delete_selected(self):
        """Exclui conexão ou grupo selecionado"""
        if self.selected_connection:
            reply = QMessageBox.question(
                self, "Confirmar Exclusão",
                f"Deseja realmente excluir a conexão '{self.selected_connection}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.connection_manager.delete_connection_config(self.selected_connection)
                self.selected_connection = None
                self._load_connections()
                self._clear_connection_details()
                self.btn_connect.setEnabled(False)
                self.btn_edit.setEnabled(False)
                self.btn_delete.setEnabled(False)
        
        elif self.selected_group:
            reply = QMessageBox.question(
                self, "Confirmar Exclusão",
                f"Deseja realmente excluir o grupo '{self.selected_group}'?\n"
                "As conexões dentro dele serão movidas para a raiz.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.connection_manager.delete_group(self.selected_group)
                self.selected_group = None
                self._load_connections()
                self.btn_connect.setEnabled(False)
                self.btn_edit.setEnabled(False)
                self.btn_delete.setEnabled(False)
    
    def _connect_selected(self):
        """Conecta à conexão selecionada"""
        if not self.selected_connection:
            return
        
        config = self.connection_manager.get_connection_config(self.selected_connection)
        if not config:
            return
        
        # Emitir sinal com a conexão selecionada
        self.connection_selected.emit(self.selected_connection, config)
        self.accept()
