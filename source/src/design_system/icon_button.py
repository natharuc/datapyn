"""
IconButton - A standardized icon button component

Commonly used for toolbars, action buttons, and control bars.
Size: 24x24 (compact) or 32x32 (normal)
"""

from typing import Optional, Callable
from PyQt6.QtWidgets import QPushButton, QWidget
from PyQt6.QtCore import Qt, QSize

from src.design_system.tokens import get_colors, SPACING, RADIUS

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class IconButton(QPushButton):
    """
    A compact button with only an icon.
    
    Args:
        icon_name: QtAwesome icon name (e.g., "mdi.play")
        tooltip: Tooltip text
        size: "compact" (24x24) or "normal" (32x32)
        variant: "ghost", "primary", "danger"
        parent: Parent widget
    """
    
    SIZES = {
        "compact": 24,
        "normal": 32,
        "small": 20,
    }
    
    def __init__(
        self,
        icon_name: str = "",
        tooltip: str = "",
        size: str = "compact",
        variant: str = "ghost",
        icon_color: str = None,
        parent: QWidget = None
    ):
        super().__init__(parent)
        
        self._icon_name = icon_name
        self._variant = variant
        self._size_name = size
        self._icon_color = icon_color
        
        # Set size
        btn_size = self.SIZES.get(size, 24)
        self.setFixedSize(btn_size, btn_size)
        
        # Set icon
        self._apply_icon()
        
        # Set tooltip
        if tooltip:
            self.setToolTip(tooltip)
        
        # Set cursor
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Apply style
        self._apply_style()
    
    def _apply_icon(self, color: str = None):
        """Apply the icon with given color"""
        if not HAS_QTAWESOME or not self._icon_name:
            return
        
        colors = get_colors()
        icon_color = color or self._icon_color or colors.text_secondary
        
        btn_size = self.SIZES.get(self._size_name, 24)
        icon_size = int(btn_size * 0.7)  # Icon is 70% of button
        
        icon = qta.icon(self._icon_name, color=icon_color)
        self.setIcon(icon)
        self.setIconSize(QSize(icon_size, icon_size))
    
    def _apply_style(self):
        """Apply stylesheet based on variant"""
        colors = get_colors()
        
        variants = {
            "ghost": {
                "bg": "transparent",
                "bg_hover": colors.bg_tertiary,
                "bg_pressed": colors.interactive_secondary_active,
            },
            "primary": {
                "bg": colors.interactive_primary,
                "bg_hover": colors.interactive_primary_hover,
                "bg_pressed": colors.interactive_primary_active,
            },
            "danger": {
                # Soft tint keeps a colored icon readable (solid danger wash
                # fights a red icon and looks like a harsh square).
                "bg": "transparent",
                "bg_hover": "rgba(239, 68, 68, 0.16)",
                "bg_pressed": "rgba(239, 68, 68, 0.28)",
                "radius": RADIUS.radius_sm,
            },
            "success": {
                "bg": colors.success,
                "bg_hover": colors.success_hover,
                "bg_pressed": colors.success_active,
            },
        }
        
        v = variants.get(self._variant, variants["ghost"])
        radius = v.get("radius", RADIUS.radius_none)
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {v["bg"]};
                border: none;
                border-radius: {radius}px;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {v["bg_hover"]};
            }}
            QPushButton:pressed {{
                background-color: {v["bg_pressed"]};
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)
    
    def set_icon(self, icon_name: str, color: str = None):
        """Change the icon"""
        self._icon_name = icon_name
        self._apply_icon(color)
    
    def set_variant(self, variant: str):
        """Change the variant"""
        self._variant = variant
        self._apply_style()
    
    def set_icon_color(self, color: str):
        """Change icon color"""
        self._icon_color = color
        self._apply_icon(color)


class PlayButton(IconButton):
    """Specialized play/run button"""
    
    def __init__(self, tooltip: str = "Run", parent: QWidget = None):
        colors = get_colors()
        super().__init__(
            icon_name="mdi.play",
            tooltip=tooltip,
            size="compact",
            variant="ghost",
            icon_color=colors.success,
            parent=parent
        )


class StopButton(IconButton):
    """Specialized stop/cancel button"""
    
    def __init__(self, tooltip: str = "Stop", parent: QWidget = None):
        colors = get_colors()
        super().__init__(
            icon_name="mdi.stop",
            tooltip=tooltip,
            size="compact",
            variant="ghost",
            icon_color=colors.danger,
            parent=parent
        )


class CloseButton(IconButton):
    """Specialized close button"""
    
    def __init__(self, tooltip: str = "Close", parent: QWidget = None):
        super().__init__(
            icon_name="mdi.close",
            tooltip=tooltip,
            size="small",
            variant="ghost",
            parent=parent
        )


class AddButton(IconButton):
    """Specialized add/plus button"""
    
    def __init__(self, tooltip: str = "Add", parent: QWidget = None):
        super().__init__(
            icon_name="mdi.plus",
            tooltip=tooltip,
            size="compact",
            variant="ghost",
            parent=parent
        )


class RefreshButton(IconButton):
    """Specialized refresh button"""
    
    def __init__(self, tooltip: str = "Refresh", parent: QWidget = None):
        super().__init__(
            icon_name="mdi.refresh",
            tooltip=tooltip,
            size="compact",
            variant="ghost",
            parent=parent
        )


class SettingsButton(IconButton):
    """Specialized settings button"""
    
    def __init__(self, tooltip: str = "Settings", parent: QWidget = None):
        super().__init__(
            icon_name="mdi.cog",
            tooltip=tooltip,
            size="compact",
            variant="ghost",
            parent=parent
        )
