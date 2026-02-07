"""
Inputs estilizados reutilizaveis

Componentes de entrada de dados com estilos consistentes.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.design_system.tokens import get_colors


def _get_line_edit_style():
    colors = get_colors()
    return f"""
        QLineEdit {{
            background-color: {colors.interactive_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_strong};
            border-radius: 3px;
            padding: 6px 10px;
            selection-background-color: {colors.interactive_primary_active};
        }}
        QLineEdit:focus {{
            border-color: {colors.interactive_primary};
        }}
        QLineEdit:disabled {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_disabled};
        }}
        QLineEdit::placeholder {{
            color: {colors.text_disabled};
        }}
    """


def _get_text_edit_style():
    colors = get_colors()
    return f"""
        QTextEdit {{
            background-color: {colors.bg_primary};
            color: {colors.editor_fg};
            border: 1px solid {colors.border_default};
            border-radius: 3px;
            padding: 8px;
            selection-background-color: {colors.interactive_primary_active};
        }}
        QTextEdit:focus {{
            border-color: {colors.interactive_primary};
        }}
    """


def _get_spinbox_style():
    colors = get_colors()
    return f"""
        QSpinBox {{
            background-color: {colors.interactive_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_strong};
            border-radius: 3px;
            padding: 4px 8px;
        }}
        QSpinBox:focus {{
            border-color: {colors.interactive_primary};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            background-color: {colors.interactive_secondary_hover};
            border: none;
            width: 20px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: {colors.bg_elevated};
        }}
        QSpinBox::up-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 6px solid {colors.text_primary};
            width: 0;
            height: 0;
        }}
        QSpinBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid {colors.text_primary};
            width: 0;
            height: 0;
        }}
    """


def _get_combobox_style():
    colors = get_colors()
    return f"""
        QComboBox {{
            background-color: {colors.interactive_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_strong};
            border-radius: 3px;
            padding: 6px 10px;
            min-width: 100px;
        }}
        QComboBox:focus {{
            border-color: {colors.interactive_primary};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 25px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {colors.text_primary};
            width: 0;
            height: 0;
        }}
        QComboBox QAbstractItemView {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            selection-background-color: {colors.interactive_primary_active};
        }}
    """


def _get_checkbox_style():
    colors = get_colors()
    return f"""
        QCheckBox {{
            color: {colors.text_primary};
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {colors.border_strong};
            border-radius: 3px;
            background-color: {colors.interactive_secondary};
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors.interactive_primary};
            border-color: {colors.interactive_primary};
        }}
        QCheckBox::indicator:hover {{
            border-color: {colors.interactive_primary};
        }}
        QCheckBox:disabled {{
            color: {colors.text_disabled};
        }}
    """


class StyledLineEdit(QLineEdit):
    """Campo de texto estilizado"""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(_get_line_edit_style())
        if placeholder:
            self.setPlaceholderText(placeholder)


class StyledTextEdit(QTextEdit):
    """Area de texto estilizada"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_get_text_edit_style())
        self.setFont(QFont("Consolas", 10))


class StyledSpinBox(QSpinBox):
    """SpinBox estilizado"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_get_spinbox_style())


class StyledComboBox(QComboBox):
    """ComboBox estilizado"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_get_combobox_style())


class StyledCheckBox(QCheckBox):
    """CheckBox estilizado"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(_get_checkbox_style())


class StyledLabel(QLabel):
    """Label estilizado"""

    @staticmethod
    def _get_label_styles():
        colors = get_colors()
        return {
            "default": f"color: {colors.text_primary};",
            "title": f"color: {colors.text_inverse}; font-size: 14px; font-weight: bold;",
            "subtitle": f"color: {colors.info}; font-size: 12px;",
            "hint": f"color: {colors.text_disabled}; font-size: 11px;",
            "success": f"color: {colors.success};",
            "warning": f"color: {colors.warning};",
            "error": f"color: {colors.danger};",
            "info": f"color: {colors.info};",
        }

    def __init__(self, text: str = "", style: str = "default", parent=None):
        super().__init__(text, parent)
        self.set_style(style)

    def set_style(self, style: str):
        """Muda o estilo do label"""
        styles = self._get_label_styles()
        self.setStyleSheet(styles.get(style, styles["default"]))


class FormField(QWidget):
    """Campo de formulário com label"""

    valueChanged = pyqtSignal()

    def __init__(self, label: str, widget: QWidget, hint: str = "", parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        # Label
        self.label = StyledLabel(label, "default")
        layout.addWidget(self.label)

        # Widget de entrada
        self.input_widget = widget
        layout.addWidget(widget)

        # Hint (opcional)
        if hint:
            self.hint_label = StyledLabel(hint, "hint")
            layout.addWidget(self.hint_label)

    def get_value(self):
        """Retorna o valor do campo"""
        if isinstance(self.input_widget, QLineEdit):
            return self.input_widget.text()
        elif isinstance(self.input_widget, QTextEdit):
            return self.input_widget.toPlainText()
        elif isinstance(self.input_widget, QSpinBox):
            return self.input_widget.value()
        elif isinstance(self.input_widget, QComboBox):
            return self.input_widget.currentText()
        elif isinstance(self.input_widget, QCheckBox):
            return self.input_widget.isChecked()
        return None

    def set_value(self, value):
        """Define o valor do campo"""
        if isinstance(self.input_widget, QLineEdit):
            self.input_widget.setText(str(value))
        elif isinstance(self.input_widget, QTextEdit):
            self.input_widget.setPlainText(str(value))
        elif isinstance(self.input_widget, QSpinBox):
            self.input_widget.setValue(int(value))
        elif isinstance(self.input_widget, QComboBox):
            idx = self.input_widget.findText(str(value))
            if idx >= 0:
                self.input_widget.setCurrentIndex(idx)
        elif isinstance(self.input_widget, QCheckBox):
            self.input_widget.setChecked(bool(value))


class SearchInput(QWidget):
    """Campo de busca com ícone"""

    textChanged = pyqtSignal(str)

    def __init__(self, placeholder: str = "Buscar...", parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = StyledLineEdit(placeholder)
        self.input.textChanged.connect(self.textChanged.emit)

        layout.addWidget(self.input)

    def text(self) -> str:
        return self.input.text()

    def clear(self):
        self.input.clear()
