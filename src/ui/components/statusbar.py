"""
StatusBar da aplicação

Barra de status com informações de conexão, timer e mensagens.
"""
from PyQt6.QtWidgets import QStatusBar, QLabel, QWidget, QHBoxLayout
from PyQt6.QtCore import QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtGui import QFont


class MainStatusBar(QStatusBar):
    """StatusBar principal com informações da IDE"""
    
    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        
        self.theme_manager = theme_manager
        self._setup_style()
        self._setup_widgets()
        self._setup_timer()
    
    def _setup_style(self):
        """Configura estilo da statusbar"""
        self.setStyleSheet("""
            QStatusBar {
                background-color: #007acc;
                color: white;
                font-size: 12px;
            }
            QStatusBar::item {
                border: none;
            }
            QLabel {
                color: white;
                padding: 0 10px;
            }
        """)
    
    def _setup_widgets(self):
        """Configura widgets da statusbar"""
        # Label de ação (lado esquerdo)
        self.action_label = QLabel("Pronto")
        self.action_label.setStyleSheet("color: white; padding: 0 15px;")
        self.addWidget(self.action_label, 1)  # stretch=1 para ocupar espaço
        
        # Label de conexão
        self.connection_label = QLabel("Desconectado")
        self.connection_label.setStyleSheet("color: white; padding: 0 10px;")
        self.addPermanentWidget(self.connection_label)
        
        # Label do timer de execução
        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet("color: white; padding: 0 10px; font-family: monospace;")
        self.addPermanentWidget(self.timer_label)
        
        # Label de posição do cursor
        self.cursor_label = QLabel("Ln 1, Col 1")
        self.cursor_label.setStyleSheet("color: white; padding: 0 10px;")
        self.addPermanentWidget(self.cursor_label)
    
    def _setup_timer(self):
        """Configura timer de execução"""
        self.elapsed_timer = QElapsedTimer()
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_timer_display)
        self.update_timer.setInterval(100)  # Atualiza a cada 100ms
    
    def set_action(self, text: str):
        """Define texto de ação"""
        self.action_label.setText(text)
    
    def set_connection(self, connection_name: str = None, db_type: str = None):
        """Define informação de conexão"""
        if connection_name:
            db_info = f" ({db_type})" if db_type else ""
            self.connection_label.setText(f"🔗 {connection_name}{db_info}")
        else:
            self.connection_label.setText("Desconectado")
    
    def set_cursor_position(self, line: int, column: int):
        """Define posição do cursor"""
        self.cursor_label.setText(f"Ln {line}, Col {column}")
    
    def start_timer(self):
        """Inicia timer de execução"""
        self.elapsed_timer.start()
        self.update_timer.start()
        self.timer_label.setText("⏱ 0.0s")
    
    def stop_timer(self):
        """Para timer e retorna tempo decorrido"""
        self.update_timer.stop()
        elapsed = self.elapsed_timer.elapsed() / 1000.0
        self.timer_label.setText(f"⏱ {elapsed:.2f}s")
        return elapsed
    
    def _update_timer_display(self):
        """Atualiza display do timer"""
        elapsed = self.elapsed_timer.elapsed() / 1000.0
        self.timer_label.setText(f"⏱ {elapsed:.1f}s")
    
    def clear_timer(self):
        """Limpa o timer"""
        self.update_timer.stop()
        self.timer_label.setText("")
    
    def set_status_color(self, color: str):
        """Define cor da statusbar"""
        colors = {
            'default': '#007acc',
            'success': '#2e7d32',
            'warning': '#f9a825',
            'error': '#c62828',
            'connecting': '#4a4a4a'
        }
        bg_color = colors.get(color, color)
        self.setStyleSheet(f"""
            QStatusBar {{
                background-color: {bg_color};
                color: white;
                font-size: 12px;
            }}
            QStatusBar::item {{
                border: none;
            }}
            QLabel {{
                color: white;
                padding: 0 10px;
            }}
        """)
