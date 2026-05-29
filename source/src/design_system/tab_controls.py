"""Shared tab control helpers."""

from PyQt6.QtCore import QObject, QEvent, Qt, QSize, QRect
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QToolButton
import qtawesome as qta

from src.design_system.tokens import get_colors


TAB_CLOSE_BUTTON_SIZE = 20
TAB_CLOSE_ICON_SIZE = 14
TAB_CLOSE_HOVER_BG = "rgba(239, 68, 68, 0.20)"
TAB_CLOSE_HOVER_COLOR = "#ef4444"


class _TabCloseHoverFilter(QObject):
    def __init__(self, button, normal_icon, hover_icon):
        super().__init__(button)
        self._button = button
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon

    def eventFilter(self, watched, event):
        if watched is self._button and event.type() == QEvent.Type.Enter:
            watched.setIcon(self._hover_icon)
        elif watched is self._button and event.type() == QEvent.Type.Leave:
            watched.setIcon(self._normal_icon)
        return super().eventFilter(watched, event)


def tab_close_button_stylesheet(size: int = TAB_CLOSE_BUTTON_SIZE) -> str:
    radius = max(1, size // 2)
    return f"""
        * {{
            background: transparent;
            border: none;
            border-radius: {radius}px;
            padding: 0px;
        }}
        *:hover {{
            background: {TAB_CLOSE_HOVER_BG};
        }}
    """


def tab_close_subcontrol_stylesheet(size: int = TAB_CLOSE_BUTTON_SIZE, margin_right: int = 7) -> str:
    radius = max(1, size // 2)
    return f"""
        QTabBar::close-button {{
            subcontrol-position: right;
            width: {size}px;
            height: {size}px;
            margin-right: {margin_right}px;
            border-radius: {radius}px;
            background: transparent;
        }}
        QTabBar::close-button:hover {{
            background-color: {TAB_CLOSE_HOVER_BG};
        }}
    """


def tab_close_icon(color: str | None = None):
    colors = get_colors()
    icon_color = color or colors.text_tertiary
    return qta.icon("mdi.close", color=icon_color, scale_factor=0.65)


def tab_close_rect(tab_rect: QRect, size: int = TAB_CLOSE_BUTTON_SIZE, margin_right: int = 7) -> QRect:
    if not tab_rect.isValid():
        return QRect()
    x = tab_rect.right() - margin_right - size + 1
    y = tab_rect.center().y() - (size // 2)
    return QRect(x, y, size, size)


def paint_tab_close_control(painter, rect: QRect, hovered: bool = False, size: int = TAB_CLOSE_BUTTON_SIZE):
    if not rect.isValid():
        return

    painter.save()
    if hovered:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TAB_CLOSE_HOVER_COLOR))
        painter.setOpacity(0.20)
        painter.drawRoundedRect(rect, size // 2, size // 2)
        painter.setOpacity(1.0)

    icon = tab_close_icon(TAB_CLOSE_HOVER_COLOR if hovered else None)
    icon_size = QSize(TAB_CLOSE_ICON_SIZE, TAB_CLOSE_ICON_SIZE)
    icon_rect = QRect(
        rect.center().x() - (TAB_CLOSE_ICON_SIZE // 2),
        rect.center().y() - (TAB_CLOSE_ICON_SIZE // 2),
        TAB_CLOSE_ICON_SIZE,
        TAB_CLOSE_ICON_SIZE,
    )
    painter.drawPixmap(icon_rect, icon.pixmap(icon_size))
    painter.restore()


def style_tab_close_button(button, size: int = TAB_CLOSE_BUTTON_SIZE):
    normal_icon = tab_close_icon()
    hover_icon = tab_close_icon(TAB_CLOSE_HOVER_COLOR)

    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(size, size)
    button.setIconSize(QSize(TAB_CLOSE_ICON_SIZE, TAB_CLOSE_ICON_SIZE))
    button.setIcon(normal_icon)
    button.setStyleSheet(tab_close_button_stylesheet(size))
    button.setProperty("datapynTabCloseButton", True)

    old_filter = getattr(button, "_datapyn_tab_close_filter", None)
    if old_filter is not None:
        button.removeEventFilter(old_filter)
    hover_filter = _TabCloseHoverFilter(button, normal_icon, hover_icon)
    button.installEventFilter(hover_filter)
    button._datapyn_tab_close_filter = hover_filter
    return button


def create_tab_close_button(parent=None, size: int = TAB_CLOSE_BUTTON_SIZE) -> QToolButton:
    button = QToolButton(parent)
    return style_tab_close_button(button, size)