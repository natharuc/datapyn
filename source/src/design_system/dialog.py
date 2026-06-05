"""
BaseDialog - Base dialog component with automatic styling

Provides a standardized dialog with:
- Automatic dark/light theme styling
- Optional header with icon, title and subtitle  
- Content area
- Standard button bar (Cancel/OK pattern)
- Soft shadow effect for modern look
"""

from typing import Optional, Callable
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QSizePolicy,
)
from PyQt6.QtCore import Qt

from src.design_system.tokens import get_colors, get_dialog_base_stylesheet, SPACING
from src.design_system.button import PrimaryButton, SecondaryButton
from src.design_system.headers import DialogHeader, ButtonBar, Divider
from src.design_system.effects import shadow_xl
from src.design_system.frameless_dialog import install_frameless_shell

try:
    from src.core.theme_manager import ThemeManager
except ImportError:
    ThemeManager = None


class BaseDialog(QDialog):
    """
    Base dialog with automatic styling and standard layout.
    
    Replaces the duplicated pattern:
    ```
    class MyDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle(...)
            self.setStyleSheet(theme_manager.get_dialog_stylesheet())
            
            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 16, 16, 16)
            
            # Header
            header = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon("mdi.xxx", ...).pixmap(20, 20))
            header.addWidget(icon_label)
            ...
            
            # Content
            ...
            
            # Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            ok_btn = QPushButton("OK")
            ok_btn.clicked.connect(self.accept)
            btn_layout.addWidget(cancel_btn)
            btn_layout.addWidget(ok_btn)
    ```
    
    Usage:
    ```
    class MyDialog(BaseDialog):
        def __init__(self, parent=None):
            super().__init__(
                title="My Dialog",
                subtitle="Optional description",
                icon_name="mdi.settings",
                width=400,
                height=300,
                parent=parent,
            )
            
            # Add content to self.content_layout
            self.content_layout.addWidget(my_widget)
    ```
    
    Args:
        title: Dialog title (shown in header and window title)
        subtitle: Optional subtitle text
        icon_name: Optional QtAwesome icon name for header
        width: Dialog width (default: 400)
        height: Dialog height (default: 300)
        show_header: Whether to show the header section (default: True)
        show_buttons: Whether to show the button bar (default: True)
        ok_text: Text for OK button (default: "OK")
        cancel_text: Text for Cancel button (default: "Cancel")
        show_ok: Whether to show OK button (default: True)
        show_cancel: Whether to show Cancel button (default: True)
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str = "",
        subtitle: str = None,
        icon_name: str = None,
        width: int = 400,
        height: int = 300,
        show_header: bool = True,
        show_buttons: bool = True,
        ok_text: str = "OK",
        cancel_text: str = "Cancel",
        show_ok: bool = True,
        show_cancel: bool = True,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        
        self._icon_name = icon_name
        self._show_header = show_header
        self._show_buttons = show_buttons
        self._ok_text = ok_text
        self._cancel_text = cancel_text
        self._show_ok = show_ok
        self._show_cancel = show_cancel
        
        # Window setup (frameless shell with custom title bar)
        self.setWindowTitle(title)
        self.resize(width, height)
        self._apply_styling()
        self._body_layout = install_frameless_shell(
            self,
            title or "Dialog",
            min_width=width,
            min_height=height,
            outer_margins=(14, 14, 14, 14),
            content_margins=(
                SPACING.space_4,
                SPACING.space_3,
                SPACING.space_4,
                SPACING.space_4,
            ),
            content_spacing=SPACING.space_3,
        )
        
        # Header (optional)
        if show_header and title:
            self._header = DialogHeader(
                title=title,
                subtitle=subtitle,
                icon_name=icon_name,
                parent=self,
            )
            self._body_layout.addWidget(self._header)
            self._body_layout.addWidget(Divider())
        else:
            self._header = None
        
        # Content area
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(SPACING.space_3)
        self._body_layout.addWidget(self._content_widget, 1)
        
        # Button bar (optional)
        if show_buttons:
            self._body_layout.addWidget(Divider())
            self._setup_buttons()
        else:
            self._button_bar = None
            self._ok_button = None
            self._cancel_button = None
    
    def _apply_styling(self):
        """Apply dialog stylesheet and shadow effect"""
        self.setStyleSheet(get_dialog_base_stylesheet())
        # Note: Drop shadow on QDialog may not work on all platforms
        # It works best on frameless dialogs. For windowed dialogs,
        # the window manager typically handles shadows.
    
    def _setup_buttons(self):
        """Setup the standard button bar"""
        self._button_bar = ButtonBar()
        
        # Cancel button (secondary style)
        if self._show_cancel:
            self._cancel_button = SecondaryButton(self._cancel_text)
            self._cancel_button.clicked.connect(self.reject)
            self._button_bar.add_button(self._cancel_button)
        else:
            self._cancel_button = None
        
        # OK button (primary style)
        if self._show_ok:
            self._ok_button = PrimaryButton(self._ok_text)
            self._ok_button.clicked.connect(self.accept)
            self._button_bar.add_button(self._ok_button)
        else:
            self._ok_button = None
        
        self._body_layout.addWidget(self._button_bar)
    
    @property
    def content_layout(self) -> QVBoxLayout:
        """Layout for adding dialog content"""
        return self._content_layout
    
    @property
    def content_widget(self) -> QWidget:
        """Widget containing the content area"""
        return self._content_widget
    
    @property 
    def ok_button(self) -> Optional[QPushButton]:
        """The OK button (None if show_ok=False)"""
        return self._ok_button
    
    @property
    def cancel_button(self) -> Optional[QPushButton]:
        """The Cancel button (None if show_cancel=False)"""
        return self._cancel_button
    
    def set_ok_enabled(self, enabled: bool):
        """Enable/disable the OK button"""
        if self._ok_button:
            self._ok_button.setEnabled(enabled)
    
    def set_ok_text(self, text: str):
        """Change the OK button text"""
        if self._ok_button:
            self._ok_button.setText(text)
    
    def set_cancel_text(self, text: str):
        """Change the Cancel button text"""
        if self._cancel_button:
            self._cancel_button.setText(text)
    
    def add_button(self, button: QPushButton, before_ok: bool = True):
        """
        Add a custom button to the button bar.
        
        Args:
            button: The button to add
            before_ok: If True, add before OK button; if False, add after
        """
        if self._button_bar:
            self._button_bar.add_button(button)


class ConfirmDialog(BaseDialog):
    """
    A simple confirmation dialog with Yes/No buttons.
    
    Args:
        title: Dialog title
        message: Confirmation message
        yes_text: Text for Yes button
        no_text: Text for No button
        icon_name: Optional icon name
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        message: str,
        yes_text: str = "Yes",
        no_text: str = "No",
        icon_name: str = "mdi.help-circle-outline",
        parent: QWidget = None,
    ):
        super().__init__(
            title=title,
            subtitle=message,
            icon_name=icon_name,
            width=350,
            height=150,
            ok_text=yes_text,
            cancel_text=no_text,
            parent=parent,
        )


class InputDialog(BaseDialog):
    """
    Dialog with a single input field.
    
    Args:
        title: Dialog title
        prompt: Prompt text
        default_value: Default input value
        placeholder: Input placeholder
        icon_name: Optional icon name
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        prompt: str = "",
        default_value: str = "",
        placeholder: str = "",
        icon_name: str = None,
        parent: QWidget = None,
    ):
        from src.design_system.input import Input
        
        super().__init__(
            title=title,
            subtitle=prompt,
            icon_name=icon_name,
            width=350,
            height=160,
            parent=parent,
        )
        
        self._input = Input(placeholder=placeholder)
        self._input.setText(default_value)
        self.content_layout.addWidget(self._input)
        self.content_layout.addStretch()
    
    @property
    def value(self) -> str:
        """Get the input value"""
        return self._input.text()
    
    @value.setter
    def value(self, text: str):
        """Set the input value"""
        self._input.setText(text)


class MessageDialog(BaseDialog):
    """
    Simple message dialog (alert/info).
    
    Args:
        title: Dialog title
        message: Message text
        icon_name: Icon name (default: info icon)
        ok_text: Button text
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        message: str,
        icon_name: str = "mdi.information-outline",
        ok_text: str = "OK",
        parent: QWidget = None,
    ):
        from PyQt6.QtWidgets import QLabel
        from src.design_system.tokens import get_colors, TYPOGRAPHY
        
        super().__init__(
            title=title,
            icon_name=icon_name,
            width=350,
            height=150,
            show_cancel=False,
            ok_text=ok_text,
            parent=parent,
        )
        
        colors = get_colors()
        
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_secondary};
                font-size: {TYPOGRAPHY.text_base}px;
            }}
        """)
        self.content_layout.addWidget(message_label)
        self.content_layout.addStretch()
