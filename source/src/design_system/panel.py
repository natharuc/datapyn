"""
Panel Component - Painel estilizado para agrupamento visual

Similar ao Card do shadcn/ui.
Usado para agrupar conteúdo relacionado.
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..design_system import get_colors, TYPOGRAPHY, SPACING, RADIUS, SHADOW


class Panel(QFrame):
    """
    Painel estilizado para agrupamento visual

    Exemplo:
        panel = Panel(title="Resultados")
        panel.set_content(my_widget)
    """

    def __init__(
        self, *, title: str = None, padding: int = None, has_border: bool = True, elevated: bool = False, parent=None
    ):
        super().__init__(parent)

        self.title_text = title
        self.has_border = has_border
        self.elevated = elevated
        self._padding = padding or SPACING.space_4

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        """Configura UI do painel"""
        # Layout principal
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header (se tiver título)
        if self.title_text:
            self._create_header()

        # Content container
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        self.content_layout.setSpacing(SPACING.space_2)

        self.main_layout.addWidget(self.content_container)

    def _create_header(self):
        """Cria header do painel"""
        colors = get_colors()

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(self._padding, SPACING.space_3, self._padding, SPACING.space_3)

        # Título
        title_font = QFont(TYPOGRAPHY.font_family_primary)
        title_font.setPixelSize(TYPOGRAPHY.text_lg)
        title_font.setWeight(TYPOGRAPHY.font_semibold)

        self.title_label = QLabel(self.title_text)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {colors.text_primary};")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        # Estilo do header
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-bottom: 1px solid {colors.border_default};
            }}
        """)

        self.main_layout.addWidget(header)
        self.header = header

    def _apply_styles(self):
        """Aplica estilos ao painel"""
        colors = get_colors()

        bg_color = colors.bg_elevated if self.elevated else colors.bg_primary
        border_style = f"1px solid {colors.border_default}" if self.has_border else "none"

        stylesheet = f"""
            Panel {{
                background-color: {bg_color};
                border: {border_style};
                border-radius: {RADIUS.radius_md}px;
            }}
        """

        self.setStyleSheet(stylesheet)

    def set_content(self, widget: QWidget):
        """Define widget de conteúdo"""
        # Remove widgets anteriores
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Adiciona novo widget
        self.content_layout.addWidget(widget)

    def add_content(self, widget: QWidget):
        """Adiciona widget ao conteúdo (sem remover anteriores)"""
        self.content_layout.addWidget(widget)

    def update_theme(self):
        """Atualiza estilos quando tema muda"""
        self._apply_styles()

        if self.title_text:
            colors = get_colors()
            self.title_label.setStyleSheet(f"color: {colors.text_primary};")
            self.header.setStyleSheet(f"""
                QWidget {{
                    background-color: {colors.bg_secondary};
                    border-bottom: 1px solid {colors.border_default};
                }}
            """)


class PanelGroup(QWidget):
    """
    Grupo de painéis com espaçamento consistente

    Exemplo:
        group = PanelGroup(orientation="vertical")
        group.add_panel(panel1)
        group.add_panel(panel2)
    """

    def __init__(self, *, orientation: str = "vertical", spacing: int = None, parent=None):
        super().__init__(parent)

        self.orientation = orientation
        self._spacing = spacing or SPACING.space_4

        self._setup_ui()

    def _setup_ui(self):
        """Configura UI do grupo"""
        if self.orientation == "vertical":
            self.layout = QVBoxLayout(self)
        else:
            self.layout = QHBoxLayout(self)

        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(self._spacing)

    def add_panel(self, panel: Panel):
        """Adiciona painel ao grupo"""
        self.layout.addWidget(panel)

    def add_widget(self, widget: QWidget):
        """Adiciona widget qualquer ao grupo"""
        self.layout.addWidget(widget)
