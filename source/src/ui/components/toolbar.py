"""
Toolbar principal da aplicacao
"""

import qtawesome as qta
from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QToolBar, QWidget


class MainToolbar(QToolBar):
    """Toolbar principal"""

    new_connection_clicked = pyqtSignal()
    new_tab_clicked = pyqtSignal()
    run_clicked = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__("Principal", parent)
        self.theme_manager = theme_manager
        self.setMovable(False)
        self.setIconSize(QSize(18, 18))
        self._setup_style()
        self._setup_buttons()

    def _setup_style(self):
        """Configura estilo da toolbar"""
        self.setStyleSheet("""
            QToolBar {
                background-color: #252526;
                border: none;
                border-bottom: 1px solid #3e3e42;
                padding: 2px 4px;
                spacing: 2px;
            }
            QToolBar::separator {
                background-color: #3e3e42;
                width: 1px;
                margin: 4px 2px;
            }
            QPushButton {
                background-color: transparent;
                color: #cccccc;
                border: none;
                padding: 4px 10px;
                font-size: 12px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #37373d;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #2d2d30;
            }
            QPushButton#success {
                color: #4caf50;
            }
            QPushButton#success:hover {
                background-color: rgba(76, 175, 80, 0.15);
                color: #66bb6a;
            }
        """)

    def _setup_buttons(self):
        """Botoes com icones"""
        # Nova Aba
        self.btn_new_tab = QPushButton(" Nova Aba")
        self.btn_new_tab.setIcon(qta.icon("mdi.tab-plus", color="#cccccc"))
        self.btn_new_tab.clicked.connect(self.new_tab_clicked.emit)
        self.addWidget(self.btn_new_tab)

        self.addSeparator()

        # Nova Conexao
        self.btn_new_conn = QPushButton(" Conexao")
        self.btn_new_conn.setIcon(qta.icon("mdi.database-plus", color="#cccccc"))
        self.btn_new_conn.clicked.connect(self.new_connection_clicked.emit)
        self.addWidget(self.btn_new_conn)

        self.addSeparator()

        # Executar (destaque verde)
        self.btn_run = QPushButton(" Executar (F5)")
        self.btn_run.setIcon(qta.icon("mdi.play-circle", color="#4caf50"))
        self.btn_run.setObjectName("success")
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.addWidget(self.btn_run)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

    def apply_theme(self):
        pass
