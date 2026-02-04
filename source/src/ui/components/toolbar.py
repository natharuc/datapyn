"""
Toolbar principal da aplicação - Material Design
"""
from PyQt6.QtWidgets import QToolBar, QWidget, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, QSize
import qtawesome as qta


class MainToolbar(QToolBar):
    """Toolbar Material Design"""
    
    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()
    
    def __init__(self, theme_manager=None, parent=None):
        super().__init__("Principal", parent)
        self.theme_manager = theme_manager
        self.setMovable(False)
        self.setIconSize(QSize(20, 20))
        self._setup_buttons()
    
    def _setup_buttons(self):
        """Botões com ícones Material"""
        # Nova Aba
        self.btn_new_tab = QPushButton(" Nova Aba")
        self.btn_new_tab.setIcon(qta.icon('mdi.tab-plus', color='white'))
        self.btn_new_tab.clicked.connect(self.new_tab_clicked.emit)
        self.addWidget(self.btn_new_tab)
        
        self.addSeparator()
        
        # Nova Conexão
        self.btn_new_conn = QPushButton(" Conexão")
        self.btn_new_conn.setIcon(qta.icon('mdi.database-plus', color='white'))
        self.btn_new_conn.clicked.connect(self.new_connection_clicked.emit)
        self.addWidget(self.btn_new_conn)
        
        self.addSeparator()
        
        # Executar (destaque verde)
        self.btn_run = QPushButton(" Executar (F5)")
        self.btn_run.setIcon(qta.icon('mdi.play-circle', color='#4caf50'))
        self.btn_run.setObjectName("success")
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.addWidget(self.btn_run)
        
        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)
    
    def apply_theme(self):
        pass
