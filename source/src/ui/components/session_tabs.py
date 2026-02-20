"""
Session tabs

Manages session tabs in the IDE.
"""

from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog, QMenu, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_colors: Dict[int, str] = {}  # Store color by tab index

        self._setup_style()
        self._setup_context_menu()

    def _setup_style(self):
        """Configure style"""
        self.setStyleSheet("""
            QTabBar {
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #999999;
                padding: 6px 16px;
                padding-right: 28px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 1px;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
                border-bottom: 2px solid #3369FF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #37373d;
                color: #cccccc;
            }
            QTabBar::close-button {
                subcontrol-position: right;
                margin-right: 4px;
                padding: 0px;
            }
            QTabBar::close-button:hover {
                background-color: rgba(231, 76, 60, 0.9);
                border-radius: 3px;
            }
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

        # 6. Close
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
            # Close from back to front to avoid index changes
            for i in range(tab_widget.count() - 1, -1, -1):
                tab_widget.session_closed.emit(i)

    def _close_other_tabs(self, keep_index):
        """Close all tabs except the specified one"""
        tab_widget = self.parent()
        if tab_widget:
            # Close from back to front
            for i in range(tab_widget.count() - 1, -1, -1):
                if i != keep_index:
                    tab_widget.session_closed.emit(i)

    def _rename_tab_inline(self, index):
        """Rename tab using inline input"""
        if index < 0:
            return

        # Create QLineEdit for inline editing
        line_edit = QLineEdit(self)
        line_edit.setText(self.tabText(index))
        line_edit.selectAll()
        line_edit.setStyleSheet("""
            QLineEdit {
                background-color: #3e3e42;
                color: #ffffff;
                border: 1px solid #007acc;
                padding: 4px 8px;
                font-size: 11px;
            }
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
        line_edit.setGeometry(tab_rect.adjusted(8, 6, -60, -6))
        line_edit.show()
        line_edit.setFocus()

    def _duplicate_tab(self, index):
        """Duplicate tab"""
        tab_widget = self.parent()
        if tab_widget and hasattr(tab_widget, "duplicate_session"):
            tab_widget.duplicate_session.emit(index)

    def _close_tab(self, index):
        """Close a tab"""
        tab_widget = self.parent()
        if tab_widget:
            tab_widget.session_closed.emit(index)

    def mouseDoubleClickEvent(self, event):
        """Rename tab on double-click using inline input"""
        index = self.tabAt(event.pos())
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

    def paintEvent(self, event):
        """Override to paint colored borders on tabs"""
        # Pintar normalmente primeiro
        super().paintEvent(event)

        # Pintar bordas coloridas
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for index, color in self._tab_colors.items():
            if index < self.count():  # Check if index is still valid
                rect = self.tabRect(index)
                if rect.isValid():
                    # Paint colored line at bottom of tab
                    pen = QPen(QColor(color))
                    pen.setWidth(3)
                    painter.setPen(pen)
                    painter.drawLine(rect.left() + 2, rect.bottom() - 1, rect.right() - 2, rect.bottom() - 1)


class SessionTabs(QTabWidget):
    """Session tabs widget"""

    # Signals
    session_changed = pyqtSignal(int)  # index
    session_closed = pyqtSignal(int)  # index
    session_renamed = pyqtSignal(int, str)  # index, new_name
    new_session_requested = pyqtSignal()
    duplicate_session = pyqtSignal(int)  # index - duplicate session

    # Spinner colors
    _SPINNER_COLOR = QColor("#FFD700")
    _SPINNER_BG = QColor(80, 80, 80, 60)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Execution state by widget id (not index, to survive tab reordering)
        self._running_widgets: Dict[int, bool] = {}
        self._spinner_angle = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._setup_ui()
        self._setup_style()
        self._connect_signals()

    def _setup_ui(self):
        """Configure UI"""
        # Custom TabBar
        self.tab_bar = SessionTabBar()
        self.setTabBar(self.tab_bar)

        # Settings
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)

    def _setup_close_button(self, index):
        """Configure X icon on tab close button - elegant and compact"""
        from PyQt6.QtWidgets import QToolButton
        from PyQt6.QtCore import Qt

        # Create compact and elegant custom button with X icon
        close_btn = QToolButton()
        close_btn.setIcon(qta.icon("mdi.close", color="#999999", scale_factor=0.7))
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                margin-right: 0px;
                border-radius: 0px;
            }
            QToolButton:hover {
                background-color: rgba(231, 76, 60, 0.8);
            }
        """)

        # Atualizar icone no hover para branco
        def on_hover_enter(event):
            close_btn.setIcon(qta.icon("mdi.close", color="#ffffff", scale_factor=0.7))
            QToolButton.enterEvent(close_btn, event)

        def on_hover_leave(event):
            close_btn.setIcon(qta.icon("mdi.close", color="#999999", scale_factor=0.7))
            QToolButton.leaveEvent(close_btn, event)

        close_btn.enterEvent = on_hover_enter
        close_btn.leaveEvent = on_hover_leave

        # IMPORTANT: Find index dynamically at click time
        # because indices change when tabs are removed
        def request_close():
            # Find current index of this tab by button
            for i in range(self.count()):
                btn = self.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn == close_btn:
                    self.tabCloseRequested.emit(i)
                    return

        close_btn.clicked.connect(request_close)

        # Replace default button
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_btn)

    def _setup_style(self):
        """Configure style"""
        self.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                border-top: 1px solid #3e3e42;
                background-color: #1e1e1e;
            }
            QTabWidget::tab-bar {
                alignment: left;
            }
        """)

    def _connect_signals(self):
        """Connect signals"""
        self.currentChanged.connect(self.session_changed.emit)
        self.tabCloseRequested.connect(self._on_close_requested)
        self.tab_bar.tab_renamed.connect(self.session_renamed.emit)

    def _on_close_requested(self, index: int):
        """Trata pedido de fechar aba"""
        # Emite sinal para o main_window tratar (pode fechar todas as abas)
        self.session_closed.emit(index)

    def add_session(self, widget: QWidget, name: str, make_current: bool = True) -> int:
        """Add new session

        Returns:
            Index of new tab
        """
        # Adicionar aba normalmente
        index = self.addTab(widget, name)

        # Configure custom close button
        self._setup_close_button(index)

        if make_current:
            self.setCurrentIndex(index)

        return index

    def remove_session(self, index: int):
        """Remove session (allows closing last tab)"""
        # Clear tab color before removing
        self.tab_bar.clear_tab_connection_color(index)
        self.removeTab(index)

    def rename_session(self, index: int, name: str):
        """Rename session"""
        self.setTabText(index, name)

    def set_tab_color(self, index: int, color: str):
        """Set tab color (to indicate status)"""
        self.tabBar().setTabTextColor(index, QColor(color))

    def set_tab_connection_color(self, index: int, color: str):
        """Set colored strip on tab to indicate active connection"""
        self.tab_bar.set_tab_connection_color(index, color)

    def set_tab_running(self, index: int, is_running: bool):
        """Indicate if session is running with animated spinner."""
        widget = self.widget(index)
        if widget is None:
            return
        widget_id = id(widget)

        if is_running:
            self._running_widgets[widget_id] = True
            # Iniciar timer de animacao se necessario
            if not self._spinner_timer.isActive():
                self._spinner_angle = 0
                self._spinner_timer.start(80)  # ~12 FPS
        else:
            self._running_widgets.pop(widget_id, None)
            # Parar timer se nenhuma aba esta rodando
            if not self._running_widgets:
                self._spinner_timer.stop()
            # Limpar icone
            self.setTabIcon(index, QIcon())

    def _tick_spinner(self):
        """Advance spinner animation and update icons."""
        self._spinner_angle = (self._spinner_angle + 30) % 360
        icon = self._make_spinner_icon()
        # Update only tabs whose widgets are in _running_widgets
        for i in range(self.count()):
            widget = self.widget(i)
            if widget and id(widget) in self._running_widgets:
                self.setTabIcon(i, icon)

    def _make_spinner_icon(self) -> QIcon:
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
        start = int(self._spinner_angle * 16)
        span = 90 * 16  # 90 graus
        painter.drawArc(rect, start, span)

        painter.end()
        return QIcon(pixmap)

    def get_session_name(self, index: int) -> str:
        """Retorna nome da sessao"""
        return self.tabText(index)

    def refresh_close_buttons(self):
        """Reapply custom close button to all tabs (except last 'new tab').

        Use this when style has been changed at runtime to force button update.
        """
        total = self.count()
        # Don't touch last tab which is the new tab button (index = total-1)
        for i in range(total - 1):
            # Reapply custom button
            try:
                self._setup_close_button(i)
            except Exception:
                # Don't fail if a tab is being removed
                continue
