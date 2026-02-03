"""
Diálogo para configurar atalhos de teclado
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QHeaderView,
                             QKeySequenceEdit, QMessageBox, QGroupBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager


class SettingsDialog(QDialog):
    """Diálogo de configurações"""
    
    shortcuts_changed = pyqtSignal()  # Sinal emitido quando atalhos são salvos
    
    def __init__(self, shortcut_manager: ShortcutManager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._setup_ui()
        self._load_shortcuts()
    
    def _setup_ui(self):
        """Configura a interface"""
        self.setWindowTitle("Configurações - Atalhos")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.resize(750, 550)
        
        # Remover botões de maximizar/minimizar
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        
        # Aplicar tema
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Cabeçalho
        header_layout = QVBoxLayout()
        header_layout.setSpacing(5)
        
        title = QLabel("Atalhos de Teclado")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)
        
        subtitle = QLabel("Personalize os atalhos do DataPyn")
        subtitle.setStyleSheet("color: #999999; font-size: 11px;")
        header_layout.addWidget(subtitle)
        
        layout.addLayout(header_layout)
        
        # Instruções
        instructions = QLabel("💡 Dica: Clique duas vezes no atalho para editar")
        instructions.setStyleSheet("""
            background-color: #2d2d30;
            color: #cccccc;
            padding: 10px;
            border-radius: 4px;
            border-left: 3px solid #007acc;
            font-size: 10px;
        """)
        layout.addWidget(instructions)
        
        # Tabela de atalhos
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Ação", "Atalho"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._edit_shortcut)
        
        # Estilo da tabela
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #3e3e42;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #094771;
            }
            QHeaderView::section {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        
        layout.addWidget(self.table)
        
        # Botões
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        btn_reset = QPushButton("Restaurar Padrões")
        btn_reset.setFixedHeight(32)
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)
        
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("Salvar")
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        btn_save.clicked.connect(self._save_shortcuts)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)
    
    def _load_shortcuts(self):
        """Carrega atalhos na tabela"""
        shortcuts = self.shortcut_manager.get_all_shortcuts()
        
        # Descrições amigáveis para TODOS os atalhos
        descriptions = {
            # Execução
            'execute_sql': 'Executar Bloco Atual',
            'execute_all': 'Executar Todos os Blocos',
            'clear_results': 'Limpar Resultados',
            
            # Arquivo
            'open_file': 'Abrir Arquivo',
            'save_file': 'Salvar Arquivo',
            'save_as': 'Salvar Como...',
            
            # Sessões
            'new_tab': 'Nova Aba',
            'close_tab': 'Fechar Aba',
            'add_block': 'Adicionar Bloco',
            
            # Edição
            'find': 'Localizar',
            'replace': 'Substituir',
            
            # Conexões
            'manage_connections': 'Gerenciar Conexões',
            'new_connection': 'Nova Conexão',
            
            # Ferramentas
            'settings': 'Configurações',
        }
        
        # Mostrar TODOS os atalhos
        filtered_shortcuts = shortcuts
        
        self.table.setRowCount(len(filtered_shortcuts))
        row = 0
        
        for action, key_sequence in sorted(filtered_shortcuts.items()):
            # Ação (nome amigável)
            item_desc = QTableWidgetItem(descriptions.get(action, action))
            item_desc.setFlags(item_desc.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_desc)
            
            # Atalho (editável)
            item_shortcut = QTableWidgetItem(key_sequence)
            item_shortcut.setData(Qt.ItemDataRole.UserRole, action)  # Guardar nome da ação
            self.table.setItem(row, 1, item_shortcut)
            
            row += 1
        
        # Ajustar altura das linhas
        for i in range(self.table.rowCount()):
            self.table.setRowHeight(i, 36)
    
    def _edit_shortcut(self, row, column):
        """Edita um atalho"""
        if column != 1:  # Apenas coluna de atalho é editável (mudou de 2 para 1)
            return
        
        # Pegar ação do UserRole
        shortcut_item = self.table.item(row, 1)
        action = shortcut_item.data(Qt.ItemDataRole.UserRole)
        action_name = self.table.item(row, 0).text()
        current_shortcut = shortcut_item.text()
        
        # Criar mini dialog para capturar tecla
        key_dialog = QDialog(self)
        key_dialog.setWindowTitle(f"Editar Atalho")
        key_dialog.setModal(True)
        key_dialog.setFixedSize(400, 150)
        
        layout = QVBoxLayout(key_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        label = QLabel(f"Pressione a nova combinação de teclas para '{action_name}':")
        layout.addWidget(label)
        
        key_edit = QKeySequenceEdit(QKeySequence(current_shortcut))
        key_edit.setFocus()
        layout.addWidget(key_edit)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(28)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3e3e42;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        btn_cancel.clicked.connect(key_dialog.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_ok = QPushButton("OK")
        btn_ok.setFixedHeight(28)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 4px 16px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        btn_ok.clicked.connect(key_dialog.accept)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
        
        if key_dialog.exec():
            new_sequence = key_edit.keySequence().toString()
            if new_sequence:
                # Verificar conflitos
                for r in range(self.table.rowCount()):
                    if r != row and self.table.item(r, 1).text() == new_sequence:
                        other_action_name = self.table.item(r, 0).text()
                        QMessageBox.warning(
                            self,
                            "Conflito de Atalho",
                            f"O atalho '{new_sequence}' já está em uso pela ação '{other_action_name}'.\n\n"
                            f"Por favor, escolha outro atalho."
                        )
                        return
                
                self.table.item(row, 1).setText(new_sequence)
    
    def _save_shortcuts(self):
        """Salva os atalhos"""
        # Salvar atalhos
        for row in range(self.table.rowCount()):
            shortcut_item = self.table.item(row, 1)
            action = shortcut_item.data(Qt.ItemDataRole.UserRole)
            shortcut = shortcut_item.text()
            self.shortcut_manager.set_shortcut(action, shortcut)
        
        # Emitir sinal para MainWindow re-registrar atalhos
        self.shortcuts_changed.emit()
        
        QMessageBox.information(
            self,
            "Sucesso",
            "Configurações salvas com sucesso!"
        )
        self.accept()
    
    def _reset_defaults(self):
        """Restaura atalhos padrão"""
        reply = QMessageBox.question(
            self,
            "Confirmar",
            "Deseja restaurar todos os atalhos para os valores padrão?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.shortcut_manager.reset_to_defaults()
            self._load_shortcuts()
