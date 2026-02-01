"""
Header do editor

Exibe atalhos e informações do editor.
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt


class EditorHeader(QWidget):
    """Header com informações de atalhos"""
    
    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        
        self.theme_manager = theme_manager
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self):
        """Configura UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        layout.addStretch()
        
        # Indicador de modo (opcional)
        self.mode_label = QLabel("")
        layout.addWidget(self.mode_label)
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2d2d30;
                border-bottom: 1px solid #3e3e42;
            }
            QLabel {
                color: #569cd6;
                font-weight: bold;
                padding: 2px;
            }
        """)
    
    def set_mode(self, mode: str):
        """Define modo atual (SQL, Python, etc)"""
        colors = {
            'sql': '#569cd6',
            'python': '#4ec9b0',
            'cross': '#9cdcfe',
        }
        color = colors.get(mode.lower(), '#cccccc')
        
        self.mode_label.setText(mode.upper())
        self.mode_label.setStyleSheet(f"color: {color}; font-weight: bold;")
    
    def clear_mode(self):
        """Limpa indicador de modo"""
        self.mode_label.setText("")
