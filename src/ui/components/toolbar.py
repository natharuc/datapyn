"""
Toolbar principal da aplicação

Barra de ferramentas simplificada.
"""
from PyQt6.QtWidgets import QToolBar, QWidget
from PyQt6.QtCore import pyqtSignal

from .buttons import ToolbarButton

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class MainToolbar(QToolBar):
    """Toolbar principal simplificada"""
    
    # Sinais emitidos quando botões são clicados
    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()  # Executar (F5)
    
    def __init__(self, theme_manager=None, parent=None):
        super().__init__("Principal", parent)
        
        self.theme_manager = theme_manager
        self.setMovable(False)
        self._setup_style()
        self._setup_buttons()
    
    def _setup_style(self):
        """Configura estilo da toolbar"""
        self.setStyleSheet("""
            QToolBar {
                background-color: #2d2d30;
                border-bottom: 1px solid #3e3e42;
                spacing: 5px;
                padding: 3px 8px;
            }
            QToolBar::separator {
                background-color: #3e3e42;
                width: 1px;
                margin: 5px 8px;
            }
        """)
    
    def _setup_buttons(self):
        """Configura botões da toolbar"""
        # Botão Nova Aba
        self.btn_new_tab = ToolbarButton("+ Nova Aba")
        if HAS_QTAWESOME:
            self.btn_new_tab.setIcon(qta.icon('fa5s.plus', color='#4ec9b0'))
        self.btn_new_tab.clicked.connect(self.new_tab_clicked.emit)
        self.addWidget(self.btn_new_tab)
        
        self.addSeparator()
        
        # Botão Nova Conexão
        self.btn_new_conn = ToolbarButton("Conexão")
        if HAS_QTAWESOME:
            self.btn_new_conn.setIcon(qta.icon('fa5s.plug', color='#569cd6'))
        self.btn_new_conn.clicked.connect(self.new_connection_clicked.emit)
        self.addWidget(self.btn_new_conn)
        
        self.addSeparator()
        
        # Botão Executar (F5)
        self.btn_run = ToolbarButton("▶ Executar (F5)")
        if HAS_QTAWESOME:
            self.btn_run.setIcon(qta.icon('fa5s.play', color='#4ec9b0'))
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.addWidget(self.btn_run)
        
        # Spacer para empurrar resto para direita
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        self.addWidget(spacer)
    
    def apply_theme(self):
        """Aplica tema à toolbar"""
        # TODO: Adaptar cores ao tema
        pass
