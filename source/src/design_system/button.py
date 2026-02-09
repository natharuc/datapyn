"""
Button Component - Botão estilizado seguindo padrões do design system

Tipos de botões:
- primary: Ação principal
- secondary: Ação secundária
- danger: Ação destrutiva
- success: Ação positiva
- ghost: Sem background

Tamanhos:
- sm: Pequeno
- md: Médio (padrão)
- lg: Grande

Estados:
- normal, hover, active, disabled, loading
"""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont, QCursor

from ..design_system import get_colors, TYPOGRAPHY, SPACING, RADIUS

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class Button(QPushButton):
    """
    Botão estilizado seguindo design system

    Exemplo:
        btn = Button("Executar", variant="primary", size="md")
        btn.set_loading(True)
    """

    clicked_safe = pyqtSignal()  # Emitido apenas se não estiver disabled/loading

    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "secondary",
        size: str = "md",
        icon: str = None,
        full_width: bool = False,
        parent=None,
    ):
        super().__init__(text, parent)

        self.variant = variant
        self.size = size
        self.icon_name = icon
        self._is_loading = False
        self._full_width = full_width

        self._setup_ui()
        self._apply_styles()

        # Conectar clique seguro
        self.clicked.connect(self._on_clicked)

    def _setup_ui(self):
        """Configura UI do botão"""
        # Icon
        if self.icon_name and HAS_QTAWESOME:
            icon = qta.icon(self.icon_name, color=self._get_icon_color())
            self.setIcon(icon)

        # Cursor via stylesheet
        # self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))  # Removido - causa warning

        # Font
        font = QFont(TYPOGRAPHY.font_family_primary)
        font.setPixelSize(self._get_font_size())
        font.setWeight(TYPOGRAPHY.font_medium)
        self.setFont(font)

        # Size
        size_map = {
            "sm": (None, 28),
            "md": (None, 32),
            "lg": (None, 40),
        }
        min_w, height = size_map.get(self.size, (None, 32))
        if min_w:
            self.setMinimumWidth(min_w)
        self.setFixedHeight(height)

    def _get_font_size(self) -> int:
        """Retorna tamanho da fonte baseado no size"""
        size_map = {
            "sm": TYPOGRAPHY.text_sm,
            "md": TYPOGRAPHY.text_base,
            "lg": TYPOGRAPHY.text_lg,
        }
        return size_map.get(self.size, TYPOGRAPHY.text_base)

    def _get_padding(self) -> str:
        """Retorna padding baseado no size"""
        size_map = {
            "sm": f"{SPACING.space_1}px {SPACING.space_3}px",
            "md": f"{SPACING.space_2}px {SPACING.space_4}px",
            "lg": f"{SPACING.space_3}px {SPACING.space_5}px",
        }
        return size_map.get(self.size, f"{SPACING.space_2}px {SPACING.space_4}px")

    def _get_icon_color(self) -> str:
        """Retorna cor do ícone baseado no variant"""
        colors = get_colors()
        if self.variant == "ghost":
            return colors.text_secondary
        elif self.variant in ("primary", "success", "danger"):
            return colors.text_inverse
        return colors.text_primary

    def _apply_styles(self):
        """Aplica stylesheet baseado em variant e state"""
        colors = get_colors()

        # Mapa de cores por variant
        variant_colors = {
            "primary": (
                colors.interactive_primary,
                colors.interactive_primary_hover,
                colors.interactive_primary_active,
                colors.text_inverse,
            ),
            "secondary": (
                colors.interactive_secondary,
                colors.interactive_secondary_hover,
                colors.interactive_secondary_active,
                colors.text_primary,
            ),
            "danger": (colors.danger, colors.danger_hover, colors.danger_active, colors.text_inverse),
            "success": (colors.success, colors.success_hover, colors.success_active, colors.text_inverse),
            "ghost": ("transparent", colors.bg_tertiary, colors.bg_secondary, colors.text_primary),
        }

        bg, bg_hover, bg_active, text_color = variant_colors.get(self.variant, variant_colors["secondary"])

        # Border para secondary e ghost
        border_style = ""
        if self.variant in ("secondary", "ghost"):
            border_style = f"border: 1px solid {colors.border_default};"
        else:
            border_style = "border: none;"

        # Width
        width_style = "width: 100%;" if self._full_width else ""

        stylesheet = f"""
            QPushButton {{
                background-color: {bg};
                color: {text_color};
                {border_style}
                padding: {self._get_padding()};
                border-radius: {RADIUS.radius_sm}px;
                font-weight: {TYPOGRAPHY.font_medium};
                {width_style}
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
            QPushButton:pressed {{
                background-color: {bg_active};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_disabled};
                border-color: {colors.border_muted};
                cursor: not-allowed;
            }}
        """

        self.setStyleSheet(stylesheet)

    def set_loading(self, loading: bool):
        """Define estado de loading"""
        self._is_loading = loading
        self.setEnabled(not loading)

        if loading:
            original_text = self.text()
            self.setText(f"{original_text}...")
            # TODO: Adicionar spinner icon quando disponível
        else:
            # Remove "..." do final
            text = self.text()
            if text.endswith("..."):
                self.setText(text[:-3])

    def is_loading(self) -> bool:
        """Retorna se está em loading"""
        return self._is_loading

    def _on_clicked(self):
        """Handler interno de click - emite clicked_safe apenas se válido"""
        if not self._is_loading and self.isEnabled():
            self.clicked_safe.emit()

    def set_variant(self, variant: str):
        """Altera variant dinamicamente"""
        self.variant = variant
        self._apply_styles()

    def update_theme(self):
        """Atualiza estilos quando tema muda"""
        self._apply_styles()
        if self.icon_name and HAS_QTAWESOME:
            icon = qta.icon(self.icon_name, color=self._get_icon_color())
            self.setIcon(icon)


# Aliases para conveniência
class PrimaryButton(Button):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, variant="primary", **kwargs)


class SecondaryButton(Button):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, variant="secondary", **kwargs)


class DangerButton(Button):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, variant="danger", **kwargs)


class SuccessButton(Button):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, variant="success", **kwargs)


class GhostButton(Button):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, variant="ghost", **kwargs)
