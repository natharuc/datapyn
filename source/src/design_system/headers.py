"""
Header Components - Reusable header components for dialogs and sections

These components eliminate the duplicated header patterns found across dialogs.
"""

from typing import Optional
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.design_system.tokens import get_colors, SPACING, TYPOGRAPHY

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class SectionHeader(QWidget):
    """
    A section header with icon and title.
    
    Replaces the duplicated pattern:
    ```
    header = QHBoxLayout()
    icon_label = QLabel()
    icon_label.setPixmap(qta.icon("mdi.xxx", color="#64b5f6").pixmap(20, 20))
    header.addWidget(icon_label)
    title = QLabel("Section Title")
    title.setStyleSheet("font-weight: bold; font-size: 11px; color: #888;")
    header.addWidget(title)
    header.addStretch()
    ```
    
    Args:
        title: Section title text
        icon_name: QtAwesome icon name (optional)
        icon_color: Icon color (default: info color)
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        icon_name: str = None,
        icon_color: str = None,
        parent: QWidget = None
    ):
        super().__init__(parent)
        
        colors = get_colors()
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING.space_2)
        
        # Icon (optional)
        if icon_name and HAS_QTAWESOME:
            icon_label = QLabel()
            color = icon_color or colors.info
            icon_label.setPixmap(qta.icon(icon_name, color=color).pixmap(16, 16))
            layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_secondary};
                font-size: {TYPOGRAPHY.text_sm}px;
                font-weight: {TYPOGRAPHY.font_semibold};
            }}
        """)
        layout.addWidget(title_label)
        
        layout.addStretch()


class DialogHeader(QWidget):
    """
    A dialog header with title and subtitle.
    
    Replaces the duplicated pattern:
    ```
    title = QLabel(S.xxx.title)
    title_font = QFont()
    title_font.setPointSize(14)
    title_font.setBold(True)
    title.setFont(title_font)
    layout.addWidget(title)

    subtitle = QLabel(S.xxx.subtitle)
    subtitle.setStyleSheet("color: #999999; font-size: 11px;")
    layout.addWidget(subtitle)
    ```
    
    Args:
        title: Main title text
        subtitle: Subtitle text (optional)
        icon_name: QtAwesome icon name (optional, shown before title)
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        subtitle: str = None,
        icon_name: str = None,
        parent: QWidget = None
    ):
        super().__init__(parent)
        
        colors = get_colors()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACING.space_4)
        layout.setSpacing(SPACING.space_1)
        
        # Title row (with optional icon)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(SPACING.space_2)
        
        if icon_name and HAS_QTAWESOME:
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon(icon_name, color=colors.interactive_primary).pixmap(24, 24))
            title_row.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(TYPOGRAPHY.text_lg)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {colors.text_primary};")
        title_row.addWidget(title_label)
        title_row.addStretch()
        
        layout.addLayout(title_row)
        
        # Subtitle (optional)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(f"""
                QLabel {{
                    color: {colors.text_tertiary};
                    font-size: {TYPOGRAPHY.text_sm}px;
                }}
            """)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)


class Divider(QFrame):
    """
    A horizontal divider line.
    
    Args:
        parent: Parent widget
    """
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        
        colors = get_colors()
        
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setStyleSheet(f"background-color: {colors.border_muted};")
        self.setFixedHeight(1)


class VerticalDivider(QFrame):
    """
    A vertical divider line.
    
    Args:
        parent: Parent widget
    """
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        
        colors = get_colors()
        
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setStyleSheet(f"background-color: {colors.border_muted};")
        self.setFixedWidth(1)


class ButtonBar(QWidget):
    """
    A footer button bar for dialogs.
    
    Provides consistent spacing and alignment for Cancel/OK buttons.
    
    Args:
        parent: Parent widget
    """
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, SPACING.space_4, 0, 0)
        self._layout.setSpacing(SPACING.space_2)
        
        # Add stretch to push buttons to the right
        self._layout.addStretch()
    
    def add_button(self, button: QWidget, stretch: bool = False):
        """Add a button to the bar"""
        if stretch:
            self._layout.insertWidget(0, button)
        else:
            self._layout.addWidget(button)
    
    def add_stretch(self):
        """Add stretch at current position"""
        self._layout.addStretch()


class Card(QFrame):
    """
    A card container with optional title.
    
    Args:
        title: Card title (optional)
        parent: Parent widget
    """
    
    def __init__(self, title: str = None, parent: QWidget = None):
        super().__init__(parent)
        
        colors = get_colors()
        
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_muted};
                border-radius: 12px;
            }}
        """)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACING.space_4, SPACING.space_4, SPACING.space_4, SPACING.space_4)
        self._layout.setSpacing(SPACING.space_3)
        
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(f"""
                QLabel {{
                    color: {colors.text_primary};
                    font-size: {TYPOGRAPHY.text_base}px;
                    font-weight: {TYPOGRAPHY.font_semibold};
                    border: none;
                    background: transparent;
                }}
            """)
            self._layout.addWidget(title_label)
            
            # Add divider after title
            self._layout.addWidget(Divider())
    
    def add_widget(self, widget: QWidget):
        """Add widget to card content"""
        self._layout.addWidget(widget)
    
    def add_layout(self, layout):
        """Add layout to card content"""
        self._layout.addLayout(layout)


class EmptyState(QWidget):
    """
    An empty state placeholder with icon, title and description.
    
    Args:
        title: Main message
        description: Secondary description
        icon_name: QtAwesome icon name
        parent: Parent widget
    """
    
    def __init__(
        self,
        title: str,
        description: str = None,
        icon_name: str = None,
        parent: QWidget = None
    ):
        super().__init__(parent)
        
        colors = get_colors()
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING.space_3)
        
        # Icon
        if icon_name and HAS_QTAWESOME:
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon(icon_name, color=colors.text_tertiary).pixmap(48, 48))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_secondary};
                font-size: {TYPOGRAPHY.text_base}px;
                font-weight: {TYPOGRAPHY.font_medium};
            }}
        """)
        layout.addWidget(title_label)
        
        # Description
        if description:
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"""
                QLabel {{
                    color: {colors.text_tertiary};
                    font-size: {TYPOGRAPHY.text_sm}px;
                }}
            """)
            layout.addWidget(desc_label)
