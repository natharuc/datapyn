"""
Input Component - Campo de entrada estilizado

Tipos:
- text: Input de texto simples
- password: Input de senha
- number: Input numérico
- search: Input de busca

Estados:
- normal, focus, disabled, error
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from ..design_system import RADIUS, SPACING, TYPOGRAPHY, get_colors


class Input(QLineEdit):
    """
    Input estilizado seguindo design system

    Exemplo:
        input = Input(placeholder="Digite seu nome")
        input.set_error(True)
    """

    def __init__(self, *, placeholder: str = "", input_type: str = "text", parent=None):
        super().__init__(parent)

        self.input_type = input_type
        self._has_error = False

        if placeholder:
            self.setPlaceholderText(placeholder)

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        """Configura UI do input"""
        # Font
        font = QFont(TYPOGRAPHY.font_family_primary)
        font.setPixelSize(TYPOGRAPHY.text_base)
        self.setFont(font)

        # Height
        self.setFixedHeight(32)

        # Input type
        if self.input_type == "password":
            self.setEchoMode(QLineEdit.EchoMode.Password)

    def _apply_styles(self):
        """Aplica stylesheet"""
        colors = get_colors()

        border_color = colors.danger if self._has_error else colors.border_default

        stylesheet = f"""
            QLineEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {border_color};
                padding: {SPACING.space_2}px {SPACING.space_3}px;
                border-radius: {RADIUS.radius_sm}px;
                selection-background-color: {colors.interactive_primary};
            }}
            QLineEdit:focus {{
                border-color: {colors.interactive_primary};
                outline: none;
            }}
            QLineEdit:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_disabled};
                border-color: {colors.border_muted};
            }}
            QLineEdit::placeholder {{
                color: {colors.text_tertiary};
            }}
        """

        self.setStyleSheet(stylesheet)

    def set_error(self, has_error: bool):
        """Define estado de erro"""
        self._has_error = has_error
        self._apply_styles()

    def update_theme(self):
        """Atualiza estilos quando tema muda"""
        self._apply_styles()


class FormField(QWidget):
    """
    Campo de formulário com label e input

    Exemplo:
        field = FormField("Nome", placeholder="Digite seu nome")
        field.set_error("Campo obrigatório")
    """

    value_changed = pyqtSignal(str)

    def __init__(
        self, label: str, *, placeholder: str = "", input_type: str = "text", required: bool = False, parent=None
    ):
        super().__init__(parent)

        self.label_text = label
        self.required = required

        self._setup_ui(placeholder, input_type)

    def _setup_ui(self, placeholder: str, input_type: str):
        """Configura UI do campo"""
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING.space_1)

        # Label
        label_font = QFont(TYPOGRAPHY.font_family_primary)
        label_font.setPixelSize(TYPOGRAPHY.text_sm)
        label_font.setWeight(TYPOGRAPHY.font_medium)

        label_text = self.label_text
        if self.required:
            label_text += " *"

        self.label = QLabel(label_text)
        self.label.setFont(label_font)
        self.label.setStyleSheet(f"color: {colors.text_primary};")
        layout.addWidget(self.label)

        # Input
        self.input = Input(placeholder=placeholder, input_type=input_type)
        self.input.textChanged.connect(self.value_changed.emit)
        layout.addWidget(self.input)

        # Error label (inicialmente invisível)
        error_font = QFont(TYPOGRAPHY.font_family_primary)
        error_font.setPixelSize(TYPOGRAPHY.text_xs)

        self.error_label = QLabel()
        self.error_label.setFont(error_font)
        self.error_label.setStyleSheet(f"color: {colors.danger};")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

    def set_error(self, error_message: str = None):
        """Define mensagem de erro"""
        has_error = error_message is not None
        self.input.set_error(has_error)

        if has_error:
            self.error_label.setText(error_message)
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)

    def value(self) -> str:
        """Retorna valor do input"""
        return self.input.text()

    def set_value(self, value: str):
        """Define valor do input"""
        self.input.setText(value)

    def clear(self):
        """Limpa input e erro"""
        self.input.clear()
        self.set_error(None)

    def update_theme(self):
        """Atualiza tema"""
        colors = get_colors()
        self.label.setStyleSheet(f"color: {colors.text_primary};")
        self.error_label.setStyleSheet(f"color: {colors.danger};")
        self.input.update_theme()
