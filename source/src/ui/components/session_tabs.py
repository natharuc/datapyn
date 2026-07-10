"""
Session tabs

Manages session tabs in the IDE.
"""

from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog, QMenu, QLineEdit, QToolButton
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QRect, QPoint
from PyQt6.QtGui import QColor, QAction, QPainter, QPen, QMovie, QIcon, QPixmap
import qtawesome as qta
from typing import Dict
import subprocess
import os
import math

from src.language import S


class SessionTabBar(QTabBar):
    """Custom TabBar for sessions"""

    tab_renamed = pyqtSignal(int, str)  # index, new_name
    closeRequested = pyqtSignal(int)
    close_multiple_requested = pyqtSignal(list)  # indices, back-to-front

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_colors: Dict[int, str] = {}  # Store color by tab index
        self._timer_tab_indices: set[int] = set()
        self._hovered_close_index = -1
        self._pressed_close_index = -1
        self.setMouseTracking(True)

        self._setup_style()
        self._setup_context_menu()

    def _setup_style(self):
        """Configure style - modern, clean, web-like"""
        from src.design_system.tokens import get_colors, RADIUS
        colors = get_colors()
        
        self.setStyleSheet(f"""
            QTabBar {{
                background-color: {colors.bg_secondary};
                border: none;
            }}
            QTabBar::tab {{
                background-color: transparent;
                color: {colors.text_secondary};
                padding: 10px 16px;
                padding-right: 28px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 2px;
                min-width: 80px;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                background-color: {colors.bg_primary};
                color: {colors.text_inverse};
                border-bottom: 2px solid {colors.interactive_primary};
                border-top-left-radius: {RADIUS.radius_sm}px;
                border-top-right-radius: {RADIUS.radius_sm}px;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
            }}
        """)

    def _setup_context_menu(self):
        """Configure context menu"""
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        """Show context menu"""
        index = self.tabAt(pos)
        if index < 0:
            return

        menu = QMenu(self)

        # Get file path if exists
        tab_widget = self.parent()
        widget = tab_widget.widget(index)
        file_path = getattr(widget, "file_path", None) if widget else None

        # 1. Open file location
        if file_path and os.path.exists(file_path):
            open_location_action = QAction(qta.icon("mdi.folder-open"), S.session_tabs.ctx_open_file_location, self)
            open_location_action.triggered.connect(lambda: self._open_file_location(file_path))
            menu.addAction(open_location_action)
            menu.addSeparator()

        # 2. Close all
        close_all_action = QAction(qta.icon("mdi.close-box-multiple"), S.session_tabs.ctx_close_all, self)
        close_all_action.triggered.connect(lambda: self._close_all_tabs())
        menu.addAction(close_all_action)

        # 3. Close all others
        close_others_action = QAction(qta.icon("mdi.close-box-outline"), S.session_tabs.ctx_close_all_others, self)
        close_others_action.triggered.connect(lambda: self._close_other_tabs(index))
        menu.addAction(close_others_action)

        menu.addSeparator()

        # 4. Rename
        rename_action = QAction(qta.icon("mdi.pencil"), S.session_tabs.ctx_rename, self)
        rename_action.triggered.connect(lambda: self._rename_tab_inline(index))
        menu.addAction(rename_action)

        # 5. Duplicate
        duplicate_action = QAction(qta.icon("mdi.content-copy"), S.session_tabs.ctx_duplicate, self)
        duplicate_action.triggered.connect(lambda: self._duplicate_tab(index))
        menu.addAction(duplicate_action)

        menu.addSeparator()

        # 6. Customize notification
        notif_label = (
            S.session_tabs.ctx_customize_notification
            if hasattr(S.session_tabs, 'ctx_customize_notification')
            else "Customize Notification"
        )
        notif_action = QAction(qta.icon("mdi.bell-ring-outline"), notif_label, self)
        notif_action.triggered.connect(lambda: self._customize_notification(index))
        menu.addAction(notif_action)

        menu.addSeparator()

        # 7. Close
        close_action = QAction(qta.icon("mdi.close"), S.session_tabs.ctx_close, self)
        close_action.triggered.connect(lambda: self._close_tab(index))
        menu.addAction(close_action)

        menu.exec(self.mapToGlobal(pos))

    def _open_file_location(self, file_path):
        """Open file location in explorer"""
        import os.path

        if os.path.exists(file_path):
            if os.name == "nt":  # Windows
                # Correct command: explorer.exe /select,"path"
                subprocess.run(["explorer.exe", f'/select,"{file_path}"'])
            elif os.name == "posix":  # Linux/Mac
                folder = os.path.dirname(file_path)
                subprocess.run(["xdg-open", folder])

    def _close_all_tabs(self):
        """Close all tabs"""
        tab_widget = self.parent()
        if tab_widget:
            indices = list(range(tab_widget.count() - 1, -1, -1))
            self.close_multiple_requested.emit(indices)

    def _close_other_tabs(self, keep_index):
        """Close all tabs except the specified one"""
        tab_widget = self.parent()
        if tab_widget:
            indices = [
                i for i in range(tab_widget.count() - 1, -1, -1) if i != keep_index
            ]
            if indices:
                self.close_multiple_requested.emit(indices)

    def _rename_tab_inline(self, index):
        """Rename tab using inline input"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        if index < 0:
            return

        # Create QLineEdit for inline editing
        line_edit = QLineEdit(self)
        line_edit.setText(self.tabText(index))
        line_edit.selectAll()
        line_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.interactive_primary};
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)

        # Function to save the new name
        def save_name():
            new_name = line_edit.text().strip()
            if new_name:
                self.setTabText(index, new_name)
                self.tab_renamed.emit(index, new_name)
            line_edit.deleteLater()

        # Connect Enter to save
        line_edit.returnPressed.connect(save_name)
        line_edit.editingFinished.connect(save_name)

        # Position line_edit over the tab (leave 60px on right for close button)
        tab_rect = self.tabRect(index)
        line_edit.setGeometry(tab_rect.adjusted(8, 6, -36, -6))
        line_edit.show()
        line_edit.setFocus()

    def _duplicate_tab(self, index):
        """Duplicate tab"""
        tab_widget = self.parent()
        if tab_widget and hasattr(tab_widget, "duplicate_session"):
            tab_widget.duplicate_session.emit(index)

    def _customize_notification(self, index):
        """Open per-tab notification config dialog"""
        tab_widget = self.parent()
        if not tab_widget:
            return
        widget = tab_widget.widget(index)
        if not widget or not hasattr(widget, 'get_tab_notification_config'):
            return

        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        current_config = widget.get_tab_notification_config()
        dialog = TabNotificationDialog(current_config, parent=self)
        if dialog.exec() == TabNotificationDialog.DialogCode.Accepted:
            config = dialog.get_config()
            if config is not None:
                widget.set_tab_notification_config(config)

    def _close_tab(self, index):
        """Close a tab"""
        tab_widget = self.parent()
        if tab_widget:
            tab_widget.session_closed.emit(index)

    def _timer_button_rect(self, index: int) -> QRect:
        close_rect = self._close_button_rect(index)
        if not close_rect.isValid():
            return QRect()
        size = close_rect.height()
        return QRect(close_rect.left() - size - 2, close_rect.top(), size, size)

    def mouseDoubleClickEvent(self, event):
        """Rename tab on double-click using inline input"""
        pos = event.position().toPoint()
        if self._close_index_at(pos) >= 0:
            super().mouseDoubleClickEvent(event)
            return
        index = self.tabAt(pos)
        if index >= 0:
            self._rename_tab_inline(index)
        else:
            super().mouseDoubleClickEvent(event)

    def set_tab_connection_color(self, index: int, color: str):
        """Set connection color for a specific tab"""
        self._tab_colors[index] = color
        self.update()  # Force repaint

    def clear_tab_connection_color(self, index: int):
        """Remove connection color from tab"""
        if index in self._tab_colors:
            del self._tab_colors[index]
            self.update()

    def _close_button_rect(self, index: int) -> QRect:
        if index < 0 or index >= self.count():
            return QRect()
        from src.design_system.tab_controls import tab_close_rect
        return tab_close_rect(self.tabRect(index))

    def _close_index_at(self, pos: QPoint) -> int:
        index = self.tabAt(pos)
        if index < 0:
            return -1
        return index if self._close_button_rect(index).contains(pos) else -1

    def set_tab_timer_visible(self, index: int, visible: bool) -> None:
        if visible:
            self._timer_tab_indices.add(index)
        else:
            self._timer_tab_indices.discard(index)
        self.update()

    def paintEvent(self, event):
        """Override to paint colored borders on tabs"""
        super().paintEvent(event)

        from src.design_system.tab_controls import paint_tab_close_control

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for index, color in self._tab_colors.items():
            if index < self.count():
                rect = self.tabRect(index)
                if rect.isValid():
                    pen = QPen(QColor(color))
                    pen.setWidth(3)
                    painter.setPen(pen)
                    painter.drawLine(rect.left() + 2, rect.bottom() - 1, rect.right() - 2, rect.bottom() - 1)

        for index in sorted(self._timer_tab_indices):
            if 0 <= index < self.count():
                close_rect = self._close_button_rect(index)
                if close_rect.isValid():
                    timer_rect = QRect(
                        close_rect.left() - close_rect.height() - 2,
                        close_rect.top(),
                        close_rect.height(),
                        close_rect.height(),
                    )
                    icon = qta.icon("mdi.timer-outline", color="#4ec9b0", scale_factor=0.65)
                    painter.drawPixmap(
                        timer_rect,
                        icon.pixmap(QSize(timer_rect.width(), timer_rect.height())),
                    )

        for index in range(self.count()):
            paint_tab_close_control(
                painter,
                self._close_button_rect(index),
                hovered=index == self._hovered_close_index,
            )

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        hovered = self._close_index_at(pos)
        if hovered != self._hovered_close_index:
            old_index = self._hovered_close_index
            self._hovered_close_index = hovered
            if old_index >= 0:
                self.update(self._close_button_rect(old_index))
            if hovered >= 0:
                self.update(self._close_button_rect(hovered))
        if hovered >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            close_index = self._close_index_at(event.position().toPoint())
            if close_index >= 0:
                self._pressed_close_index = close_index
                event.accept()
                return
        self._pressed_close_index = -1
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_close_index >= 0:
            pos = event.position().toPoint()
            close_index = self._close_index_at(pos)
            if close_index == self._pressed_close_index:
                self.closeRequested.emit(close_index)
                self._pressed_close_index = -1
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            for index in sorted(self._timer_tab_indices):
                if self._timer_button_rect(index).contains(pos):
                    tab_widget = self.parent()
                    if tab_widget is not None:
                        widget = tab_widget.widget(index)
                        if widget is not None and hasattr(widget, "stop_periodic"):
                            widget.stop_periodic()
                    event.accept()
                    return
        self._pressed_close_index = -1
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        old_index = self._hovered_close_index
        self._hovered_close_index = -1
        self._pressed_close_index = -1
        self.unsetCursor()
        if old_index >= 0:
            self.update(self._close_button_rect(old_index))
        super().leaveEvent(event)


class SessionTabs(QTabWidget):
    """Session tabs widget"""

    # Signals
    session_changed = pyqtSignal(int)  # index
    session_closed = pyqtSignal(int)  # index
    close_multiple_tabs = pyqtSignal(list)  # indices, back-to-front
    session_renamed = pyqtSignal(int, str)  # index, new_name
    new_session_requested = pyqtSignal()
    duplicate_session = pyqtSignal(int)  # index - duplicate session

    # Spinner colors - use warning for visibility
    _SPINNER_COLOR = QColor("#fbbf24")  # warning/amber from tokens
    _SPINNER_BG = QColor(80, 80, 80, 60)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Execution state by widget id (not index, to survive tab reordering)
        self._running_widgets: Dict[int, str] = {}  # widget_id -> "running" | "cancelling"
        self._spinner_angle_cw = 0
        self._spinner_angle_ccw = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._setup_ui()
        self._setup_style()
        self._connect_signals()
        self._sync_new_tab_button()

    def _has_session_widgets(self) -> bool:
        from src.ui.components.session_widget import SessionWidget

        return any(isinstance(self.widget(index), SessionWidget) for index in range(self.count()))

    def _sync_new_tab_button(self) -> None:
        accessory = getattr(self, "_new_tab_accessory", None)
        if accessory is None:
            return
        accessory.set_visible(self._has_session_widgets())

    def _on_new_tab_button_clicked(self) -> None:
        self.new_session_requested.emit()

    def _setup_ui(self):
        """Configure UI"""
        # Custom TabBar
        self.tab_bar = SessionTabBar()
        self.setTabBar(self.tab_bar)

        # Close control is painted on SessionTabBar (same as result tabs)
        self.setTabsClosable(False)
        self.setMovable(True)
        self.setDocumentMode(True)

        from src.design_system.tab_controls import TabBarAccessoryStrip

        self._new_tab_accessory = TabBarAccessoryStrip(self.tab_bar, host=self)
        self._new_tab_accessory.add_button(
            "mdi.plus",
            tooltip=S.session_tabs.new_tab_tooltip,
            callback=self._on_new_tab_button_clicked,
            object_name="sessionNewTabButton",
            icon_scale=0.85,
        )
        self._new_tab_accessory.set_visible(False)

    def set_tab_timer_icon(self, index: int, visible: bool, interval: int = 0):
        """Show or hide the periodic timer glyph painted on the tab."""
        self.tab_bar.set_tab_timer_visible(index, visible)
        if visible and interval > 0:
            self.setTabToolTip(index, f"Periodic: {interval}s")
        else:
            self.setTabToolTip(index, "")

    def _setup_style(self):
        """Configure style - modern, clean"""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        
        self.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                border-top: 1px solid {colors.border_muted};
                background-color: {colors.bg_primary};
            }}
            QTabWidget::tab-bar {{
                alignment: left;
            }}
        """)

    def _connect_signals(self):
        """Connect signals"""
        self.currentChanged.connect(self.session_changed.emit)
        self.currentChanged.connect(lambda _index: self._reposition_new_tab_button())
        self.tab_bar.closeRequested.connect(self._on_close_requested)
        self.tab_bar.close_multiple_requested.connect(self.close_multiple_tabs.emit)
        self.tab_bar.tab_renamed.connect(self.session_renamed.emit)

    def _reposition_new_tab_button(self) -> None:
        accessory = getattr(self, "_new_tab_accessory", None)
        if accessory is not None and self._has_session_widgets():
            accessory.reposition()

    def _on_close_requested(self, index: int):
        """Trata pedido de fechar aba"""
        # Emite sinal para o main_window tratar (pode fechar todas as abas)
        self.session_closed.emit(index)

    def add_session(self, widget: QWidget, name: str, make_current: bool = True) -> int:
        """Add new session

        Returns:
            Index of new tab
        """
        index = self.addTab(widget, name)

        self._sync_new_tab_button()
        self._reposition_new_tab_button()

        if make_current:
            self.setCurrentIndex(index)

        return index

    def remove_session(self, index: int):
        """Remove session (allows closing last tab)"""
        # Clear tab color before removing
        self.tab_bar.clear_tab_connection_color(index)
        self.removeTab(index)
        self._sync_new_tab_button()
        self._reposition_new_tab_button()

    def rename_session(self, index: int, name: str):
        """Rename session"""
        self.setTabText(index, name)

    def set_tab_color(self, index: int, color: str):
        """Set tab color (to indicate status)"""
        self.tabBar().setTabTextColor(index, QColor(color))

    def set_tab_connection_color(self, index: int, color: str):
        """Set colored strip on tab to indicate active connection"""
        self.tab_bar.set_tab_connection_color(index, color)

    def set_tab_running(self, index: int, is_running: bool, *, cancelling: bool = False):
        """Indicate if session is running with animated spinner.

        Executing uses clockwise rotation; cancelling uses counter-clockwise.
        """
        widget = self.widget(index)
        if widget is None:
            return
        widget_id = id(widget)

        if is_running or cancelling:
            self._running_widgets[widget_id] = "cancelling" if cancelling else "running"
            if not self._spinner_timer.isActive():
                self._spinner_angle_cw = 0
                self._spinner_angle_ccw = 0
                self._spinner_timer.start(80)  # ~12 FPS
        else:
            self._running_widgets.pop(widget_id, None)
            if not self._running_widgets:
                self._spinner_timer.stop()
            self.setTabIcon(index, QIcon())

    def set_tab_cancelling(self, index: int, is_cancelling: bool):
        """Switch tab spinner to counter-clockwise while SQL cancel finishes."""
        if is_cancelling:
            self.set_tab_running(index, True, cancelling=True)
        else:
            widget = self.widget(index)
            if widget is None:
                return
            widget_id = id(widget)
            if self._running_widgets.get(widget_id) == "cancelling":
                self._running_widgets[widget_id] = "running"

    def _tick_spinner(self):
        """Advance spinner animation and update icons."""
        self._spinner_angle_cw = (self._spinner_angle_cw - 30) % 360
        self._spinner_angle_ccw = (self._spinner_angle_ccw + 30) % 360
        for i in range(self.count()):
            widget = self.widget(i)
            if widget is None:
                continue
            state = self._running_widgets.get(id(widget))
            if not state:
                continue
            angle = self._spinner_angle_ccw if state == "cancelling" else self._spinner_angle_cw
            self.setTabIcon(i, self._make_spinner_icon(angle))

    def _make_spinner_icon(self, angle: int) -> QIcon:
        """Cria icone de spinner circular com o angulo atual."""
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = size / 2
        radius = size / 2 - 2

        # Arco de fundo
        pen_bg = QPen(self._SPINNER_BG, 2)
        painter.setPen(pen_bg)
        painter.drawEllipse(int(center - radius), int(center - radius),
                           int(radius * 2), int(radius * 2))

        # Arco animado (90 graus)
        pen_fg = QPen(self._SPINNER_COLOR, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        from PyQt6.QtCore import QRectF
        rect = QRectF(center - radius, center - radius, radius * 2, radius * 2)
        start = int(angle * 16)
        span = 90 * 16  # 90 graus
        painter.drawArc(rect, start, span)

        painter.end()
        return QIcon(pixmap)

    def get_session_name(self, index: int) -> str:
        """Retorna nome da sessao"""
        return self.tabText(index)

    def refresh_close_buttons(self):
        """Repaint tab chrome after a runtime style refresh."""
        self.tab_bar.update()
