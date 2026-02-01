"""
Diálogo para configurar atalhos de teclado
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QHeaderView,
                             QKeySequenceEdit, QMessageBox, QGroupBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence
from src.core import ShortcutManager
from src.core.theme_manager import ThemeManager


class SettingsDialog(QDialog):
    """Diálogo de configurações"""
    
    def __init__(self, shortcut_manager: ShortcutManager, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.theme_manager = theme_manager or ThemeManager()
        self._setup_ui()
        self._load_shortcuts()
    
    def _setup_ui(self):
        """Configura a interface"""
        self.setWindowTitle("Configurações")
        self.setModal(True)
        self.setMinimumSize(650, 600)
        
        # Aplicar tema
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())
        
        layout = QVBoxLayout(self)
        
        # Título
        title = QLabel("Configurações")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Instruções de atalhos
        instructions = QLabel("Atalhos de Teclado - Clique duas vezes no atalho para editar")
        instructions.setStyleSheet("color: #cccccc; padding: 5px; margin-top: 10px;")
        layout.addWidget(instructions)
        
        # Tabela de atalhos
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Ação", "Descrição", "Atalho"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self._edit_shortcut)
        
        layout.addWidget(self.table)
        
        # Botões
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_reset = QPushButton("Restaurar Padrões")
        btn_reset.setObjectName("btnReset")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("Salvar")
        btn_save.clicked.connect(self._save_shortcuts)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)
    
    def _load_shortcuts(self):
        """Carrega atalhos na tabela"""
        shortcuts = self.shortcut_manager.get_all_shortcuts()
        
        # Descrições amigáveis
        descriptions = {
            'execute_sql': 'Executar SQL',
            'execute_python': 'Executar Python',
            'execute_cross_syntax': 'Executar Cross-Syntax ({{ SQL }})',
            'new_tab': 'Nova aba',
            'close_tab': 'Fechar aba',
            'save_file': 'Salvar arquivo',
            'open_file': 'Abrir arquivo',
            'find': 'Buscar',
            'replace': 'Substituir',
            'comment': 'Comentar/descomentar',
            'format_code': 'Formatar código',
            'clear_results': 'Limpar resultados',
            'focus_editor': 'Focar no editor',
            'focus_results': 'Focar nos resultados',
            'toggle_fullscreen': 'Alternar tela cheia',
        }
        
        self.table.setRowCount(len(shortcuts))
        row = 0
        
        for action, key_sequence in shortcuts.items():
            # Ação
            item_action = QTableWidgetItem(action)
            item_action.setFlags(item_action.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_action)
            
            # Descrição
            desc = descriptions.get(action, action)
            item_desc = QTableWidgetItem(desc)
            item_desc.setFlags(item_desc.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, item_desc)
            
            # Atalho
            item_shortcut = QTableWidgetItem(key_sequence)
            self.table.setItem(row, 2, item_shortcut)
            
            row += 1
    
    def _edit_shortcut(self, row, column):
        """Edita um atalho"""
        if column != 2:  # Apenas coluna de atalho é editável
            return
        
        action = self.table.item(row, 0).text()
        current_shortcut = self.table.item(row, 2).text()
        
        # Criar mini dialog para capturar tecla
        key_dialog = QDialog(self)
        key_dialog.setWindowTitle(f"Editar Atalho: {action}")
        key_dialog.setModal(True)
        
        layout = QVBoxLayout(key_dialog)
        
        label = QLabel(f"Pressione a nova combinação de teclas para '{action}':")
        layout.addWidget(label)
        
        key_edit = QKeySequenceEdit(QKeySequence(current_shortcut))
        key_edit.setFocus()
        layout.addWidget(key_edit)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancelar")
        
        btn_ok.clicked.connect(key_dialog.accept)
        btn_cancel.clicked.connect(key_dialog.reject)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
        if key_dialog.exec():
            new_sequence = key_edit.keySequence().toString()
            if new_sequence:
                # Verificar conflitos
                for r in range(self.table.rowCount()):
                    if r != row and self.table.item(r, 2).text() == new_sequence:
                        other_action = self.table.item(r, 0).text()
                        QMessageBox.warning(
                            self,
                            "Conflito de Atalho",
                            f"O atalho '{new_sequence}' já está em uso pela ação '{other_action}'.\n\n"
                            f"Por favor, escolha outro atalho."
                        )
                        return
                
                self.table.item(row, 2).setText(new_sequence)
    
    def _save_shortcuts(self):
        """Salva os atalhos"""
        # Salvar atalhos
        for row in range(self.table.rowCount()):
            action = self.table.item(row, 0).text()
            shortcut = self.table.item(row, 2).text()
            self.shortcut_manager.set_shortcut(action, shortcut)
        
        QMessageBox.information(
            self,
            "Sucesso",
            "Configurações salvas com sucesso!\n\nReinicie o DataPyn para aplicar todas as mudanças."
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
