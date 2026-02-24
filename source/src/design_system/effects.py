"""
Visual effects utilities for the design system.

Provides consistent shadow effects throughout the UI.
Qt doesn't support CSS box-shadow, so we use QGraphicsDropShadowEffect.
"""

from PyQt6.QtWidgets import QWidget, QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt


def apply_shadow(
    widget: QWidget,
    blur_radius: int = 12,
    offset_x: int = 0,
    offset_y: int = 2,
    color: str = "#000000",
    opacity: float = 0.15,
) -> QGraphicsDropShadowEffect:
    """
    Apply a drop shadow effect to a widget.
    
    Args:
        widget: The widget to apply shadow to
        blur_radius: Blur radius in pixels (larger = softer)
        offset_x: Horizontal offset
        offset_y: Vertical offset
        color: Shadow color as hex string
        opacity: Shadow opacity (0.0 to 1.0)
    
    Returns:
        The created shadow effect (for further customization)
    """
    shadow = QGraphicsDropShadowEffect(widget)
    shadow_color = QColor(color)
    shadow_color.setAlphaF(opacity)
    shadow.setColor(shadow_color)
    shadow.setBlurRadius(blur_radius)
    shadow.setOffset(offset_x, offset_y)
    widget.setGraphicsEffect(shadow)
    return shadow


def shadow_sm(widget: QWidget) -> QGraphicsDropShadowEffect:
    """Apply a small shadow (subtle elevation)."""
    return apply_shadow(widget, blur_radius=6, offset_y=1, opacity=0.08)


def shadow_md(widget: QWidget) -> QGraphicsDropShadowEffect:
    """Apply a medium shadow (moderate elevation)."""
    return apply_shadow(widget, blur_radius=12, offset_y=2, opacity=0.12)


def shadow_lg(widget: QWidget) -> QGraphicsDropShadowEffect:
    """Apply a large shadow (strong elevation)."""
    return apply_shadow(widget, blur_radius=20, offset_y=4, opacity=0.15)


def shadow_xl(widget: QWidget) -> QGraphicsDropShadowEffect:
    """Apply an extra large shadow (dialogs, overlays)."""
    return apply_shadow(widget, blur_radius=30, offset_y=6, opacity=0.20)


def shadow_none(widget: QWidget) -> None:
    """Remove shadow effect from widget."""
    widget.setGraphicsEffect(None)
