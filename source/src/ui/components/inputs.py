"""
Inputs estilizados reutilizáveis

Componentes de entrada de dados com estilos consistentes.
"""
from PyQt6.QtWidgets import (QLineEdit, QTextEdit, QSpinBox, QComboBox, 
                             QCheckBox, QLabel, QWidget, QHBoxLayout,
                             QVBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class StyledLineEdit(QLineEdit):
    """Campo de texto estilizado"""
    
    STYLE = """
        QLineEdit {
            background-color: #3c3c3c;
            color: #cccccc;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 6px 10px;
            selection-background-color: #094771;
        }
        QLineEdit:focus {
            border-color: #0e639c;
        }
        QLineEdit:disabled {
            background-color: #2d2d30;
            color: #6e6e6e;
        }
        QLineEdit::placeholder {
            color: #6e6e6e;
        }
    """
    
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)
        if placeholder:
            self.setPlaceholderText(placeholder)


class StyledTextEdit(QTextEdit):
    """Área de texto estilizada"""
    
    STYLE = """
        QTextEdit {
            background-color: #1e1e1e;
            color: #d4d4d4;
            border: 1px solid #3e3e42;
            border-radius: 3px;
            padding: 8px;
            selection-background-color: #094771;
        }
        QTextEdit:focus {
            border-color: #0e639c;
        }
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)
        self.setFont(QFont("Consolas", 10))


class StyledSpinBox(QSpinBox):
    """SpinBox estilizado"""
    
    STYLE = """
        QSpinBox {
            background-color: #3c3c3c;
            color: #cccccc;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 4px 8px;
        }
        QSpinBox:focus {
            border-color: #0e639c;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            background-color: #4a4a4a;
            border: none;
            width: 20px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #5a5a5a;
        }
        QSpinBox::up-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 6px solid #cccccc;
            width: 0;
            height: 0;
        }
        QSpinBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid #cccccc;
            width: 0;
            height: 0;
        }
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)


class StyledComboBox(QComboBox):
    """ComboBox estilizado"""
    
    STYLE = """
        QComboBox {
            background-color: #3c3c3c;
            color: #cccccc;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 6px 10px;
            min-width: 100px;
        }
        QComboBox:focus {
            border-color: #0e639c;
        }
        QComboBox::drop-down {
            border: none;
            width: 25px;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #cccccc;
            width: 0;
            height: 0;
        }
        QComboBox QAbstractItemView {
            background-color: #2d2d30;
            color: #cccccc;
            border: 1px solid #3e3e42;
            selection-background-color: #094771;
        }
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)


class StyledCheckBox(QCheckBox):
    """CheckBox estilizado"""
    
    STYLE = """
        QCheckBox {
            color: #cccccc;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 1px solid #555555;
            border-radius: 3px;
            background-color: #3c3c3c;
        }
        QCheckBox::indicator:checked {
            background-color: #0e639c;
            border-color: #0e639c;
        }
        QCheckBox::indicator:hover {
            border-color: #0e639c;
        }
        QCheckBox:disabled {
            color: #6e6e6e;
        }
    """
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(self.STYLE)


class StyledLabel(QLabel):
    """Label estilizado"""
    
    STYLES = {
        'default': "color: #cccccc;",
        'title': "color: #ffffff; font-size: 14px; font-weight: bold;",
        'subtitle': "color: #9cdcfe; font-size: 12px;",
        'hint': "color: #6e6e6e; font-size: 11px;",
        'success': "color: #4ec9b0;",
        'warning': "color: #dcdcaa;",
        'error': "color: #f48771;",
        'info': "color: #569cd6;"
    }
    
    def __init__(self, text: str = "", style: str = 'default', parent=None):
        super().__init__(text, parent)
        self.set_style(style)
    
    def set_style(self, style: str):
        """Muda o estilo do label"""
        self.setStyleSheet(self.STYLES.get(style, self.STYLES['default']))


class FormField(QWidget):
    """Campo de formulário com label"""
    
    valueChanged = pyqtSignal()
    
    def __init__(self, label: str, widget: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        
        # Label
        self.label = StyledLabel(label, 'default')
        layout.addWidget(self.label)
        
        # Widget de entrada
        self.input_widget = widget
        layout.addWidget(widget)
        
        # Hint (opcional)
        if hint:
            self.hint_label = StyledLabel(hint, 'hint')
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
