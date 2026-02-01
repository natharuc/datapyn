"""
Botões estilizados reutilizáveis

Componentes de botões com estilos consistentes.
"""
from PyQt6.QtWidgets import QPushButton, QToolButton
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class StyledButton(QPushButton):
    """Botão estilizado base"""
    
    STYLES = {
        'primary': """
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #094771;
            }
            QPushButton:disabled {
                background-color: #3e3e42;
                color: #6e6e6e;
            }
        """,
        'secondary': """
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555555;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #666666;
            }
            QPushButton:pressed {
                background-color: #333333;
            }
            QPushButton:disabled {
                background-color: #2d2d30;
                color: #6e6e6e;
                border-color: #3e3e42;
            }
        """,
        'danger': """
            QPushButton {
                background-color: #8b0000;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #a52a2a;
            }
            QPushButton:pressed {
                background-color: #5c0000;
            }
            QPushButton:disabled {
                background-color: #3e3e42;
                color: #6e6e6e;
            }
        """,
        'success': """
            QPushButton {
                background-color: #2e7d32;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
            QPushButton:pressed {
                background-color: #1b5e20;
            }
            QPushButton:disabled {
                background-color: #3e3e42;
                color: #6e6e6e;
            }
        """,
        'ghost': """
            QPushButton {
                background-color: transparent;
                color: #cccccc;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """,
        'toolbar': """
            QPushButton {
                background-color: transparent;
                color: #cccccc;
                border: none;
                padding: 5px 12px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
            }
            QPushButton:pressed {
                background-color: #094771;
            }
        """
    }
    
    def __init__(self, text: str = "", icon_name: str = None, 
                 style: str = 'primary', parent=None):
        super().__init__(text, parent)
        
        self._style_type = style
        self.setStyleSheet(self.STYLES.get(style, self.STYLES['primary']))
        
        if icon_name and HAS_QTAWESOME:
            self.setIcon(qta.icon(icon_name, color='white'))
    
    def set_style(self, style: str):
        """Muda o estilo do botão"""
        self._style_type = style
        self.setStyleSheet(self.STYLES.get(style, self.STYLES['primary']))


class PrimaryButton(StyledButton):
    """Botão primário (ação principal)"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'primary', parent)


class SecondaryButton(StyledButton):
    """Botão secundário"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'secondary', parent)


class DangerButton(StyledButton):
    """Botão de perigo (ações destrutivas)"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'danger', parent)


class SuccessButton(StyledButton):
    """Botão de sucesso"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'success', parent)


class GhostButton(StyledButton):
    """Botão fantasma (sem background)"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'ghost', parent)


class ToolbarButton(StyledButton):
    """Botão para toolbar"""
    def __init__(self, text: str = "", icon_name: str = None, parent=None):
        super().__init__(text, icon_name, 'toolbar', parent)


class IconButton(QToolButton):
    """Botão apenas com ícone"""
    
    def __init__(self, icon_name: str, tooltip: str = "", size: int = 24, parent=None):
        super().__init__(parent)
        
        if HAS_QTAWESOME:
            self.setIcon(qta.icon(icon_name, color='#cccccc'))
        
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                padding: 4px;
                border-radius: 3px;
            }
            QToolButton:hover {
                background-color: #3e3e42;
            }
            QToolButton:pressed {
                background-color: #094771;
            }
        """)
