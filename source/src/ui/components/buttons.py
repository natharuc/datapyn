"""
Botões estilizados reutilizáveis

DEPRECATED: Use src.design_system.Button ao invés deste
Mantido para compatibilidade com código legado.
"""
from src.design_system import (
    Button as NewButton,
    PrimaryButton as NewPrimaryButton,
    SecondaryButton as NewSecondaryButton,
    DangerButton as NewDangerButton,
    SuccessButton as NewSuccessButton,
    GhostButton as NewGhostButton,
)

# Aliases para compatibilidade
Button = NewButton
PrimaryButton = NewPrimaryButton
SecondaryButton = NewSecondaryButton
DangerButton = NewDangerButton
SuccessButton = NewSuccessButton
GhostButton = NewGhostButton

from PyQt6.QtWidgets import QPushButton, QToolButton
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

from src.design_system.tokens import get_colors

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


def _get_styles():
    """Retorna estilos usando cores do design system"""
    colors = get_colors()
    return {
        'primary': f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_elevated};
                color: {colors.text_disabled};
            }}
        """,
        'secondary': f"""
            QPushButton {{
                background-color: {colors.interactive_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_strong};
                padding: 6px 16px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_secondary_hover};
                border-color: {colors.border_strong};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_secondary_active};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_disabled};
                border-color: {colors.border_default};
            }}
        """,
        'danger': f"""
            QPushButton {{
                background-color: {colors.danger};
                color: {colors.text_inverse};
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.danger_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.danger_active};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_elevated};
                color: {colors.text_disabled};
            }}
        """,
        'success': f"""
            QPushButton {{
                background-color: {colors.success};
                color: {colors.text_inverse};
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.success_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.success_active};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_elevated};
                color: {colors.text_disabled};
            }}
        """,
        'ghost': f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_primary};
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
            QPushButton:pressed {{
                background-color: {colors.bg_secondary};
            }}
        """,
        'toolbar': f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_primary};
                border: none;
                padding: 5px 12px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_elevated};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
        """
    }


class StyledButton(QPushButton):
    """Botao estilizado base - DEPRECATED"""
    
    def __init__(self, text: str = "", icon_name: str = None, 
                 style: str = 'primary', parent=None):
        super().__init__(text, parent)
        
        self._style_type = style
        styles = _get_styles()
        self.setStyleSheet(styles.get(style, styles['primary']))
        
        if icon_name and HAS_QTAWESOME:
            self.setIcon(qta.icon(icon_name, color='white'))
    
    def set_style(self, style: str):
        """Muda o estilo do botao"""
        self._style_type = style
        styles = _get_styles()
        self.setStyleSheet(styles.get(style, styles['primary']))


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
