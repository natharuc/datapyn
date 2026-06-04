"""Shared tab control helpers."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, QEvent, Qt, QSize, QRect
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QTabBar, QToolButton, QWidget
import qtawesome as qta

from src.design_system.tokens import get_colors


TAB_CLOSE_BUTTON_SIZE = 20
TAB_CLOSE_ICON_SIZE = 14
TAB_ACCESSORY_BUTTON_SIZE = 24
TAB_ACCESSORY_ICON_SIZE = 14
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


def tab_accessory_button_stylesheet() -> str:
    colors = get_colors()
    radius = TAB_ACCESSORY_BUTTON_SIZE // 2
    return f"""
        QToolButton {{
            background: transparent;
            border: none;
            border-radius: {radius}px;
            padding: 0px;
        }}
        QToolButton:hover {{
            background-color: {colors.bg_tertiary};
        }}
    """


def reposition_tab_bar_accessories(root: QWidget) -> None:
    """Reposition every TabBarAccessoryStrip under root (e.g. after dock resize)."""
    from PyQt6.QtWidgets import QTabBar

    for tab_bar in root.findChildren(QTabBar):
        strip = getattr(tab_bar, "_datapyn_tab_accessory_strip", None)
        if strip is not None:
            strip.reposition()


class TabBarAccessoryStrip(QObject):
    """Chrome-style icon buttons placed immediately after the last tab."""

    def __init__(self, tab_bar: QTabBar, *, host: QWidget | None = None):
        super().__init__(tab_bar)
        self._tab_bar = tab_bar
        tab_bar._datapyn_tab_accessory_strip = self
        self._host = host or tab_bar
        self._strip = QWidget(self._host)
        self._strip.setObjectName("tabBarAccessoryStrip")
        layout = QHBoxLayout(self._strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        tab_bar.installEventFilter(self)
        self._host.installEventFilter(self)
        for signal_name in ("tabLayoutChanged", "currentChanged"):
            signal = getattr(tab_bar, signal_name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(self.reposition)
        tab_moved = getattr(tab_bar, "tabMoved", None)
        if tab_moved is not None and hasattr(tab_moved, "connect"):
            tab_moved.connect(lambda *_: self.reposition())
        self.reposition()

    def set_visible(self, visible: bool) -> None:
        self._strip.setVisible(visible)
        if visible:
            self.reposition()

    def add_button(
        self,
        icon_name: str,
        *,
        tooltip: str = "",
        callback: Callable[[], None] | None = None,
        object_name: str = "",
        icon_color: str | None = None,
        icon_scale: float = 0.8,
    ) -> QToolButton:
        colors = get_colors()
        button = QToolButton(self._strip)
        if object_name:
            button.setObjectName(object_name)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(TAB_ACCESSORY_BUTTON_SIZE, TAB_ACCESSORY_BUTTON_SIZE)
        button.setIconSize(QSize(TAB_ACCESSORY_ICON_SIZE, TAB_ACCESSORY_ICON_SIZE))
        button.setIcon(
            qta.icon(icon_name, color=icon_color or colors.text_secondary, scale_factor=icon_scale)
        )
        button.setStyleSheet(tab_accessory_button_stylesheet())
        if tooltip:
            button.setToolTip(tooltip)
        if callback is not None:
            button.clicked.connect(callback)
        self._strip.layout().addWidget(button)
        self.reposition()
        return button

    def reposition(self):
        bar = self._tab_bar
        if not bar.isVisible() or bar.count() <= 0:
            self._strip.hide()
            return

        rect = bar.tabRect(bar.count() - 1)
        if rect.isValid():
            anchor = bar.mapTo(self._host, rect.topRight())
            x = anchor.x() + 8
            y = anchor.y() + max(0, (rect.height() - self._strip.height()) // 2)
        else:
            x = 8
            y = max(0, (bar.height() - self._strip.height()) // 2)

        self._strip.adjustSize()
        self._strip.move(x, y)
        self._strip.show()
        self._strip.raise_()

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
            QEvent.Type.ParentChange,
        ):
            if watched in (self._tab_bar, self._host):
                self.reposition()
        return False