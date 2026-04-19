"""
Session tabs

Manages session tabs in the IDE.
"""

from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog, QMenu, QLineEdit, QToolButton
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
                padding-right: 8px;
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

    # Spinner colors - use warning for visibility
    _SPINNER_COLOR = QColor("#fbbf24")  # warning/amber from tokens
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
        """Configure tab right-side widget: [timer icon] [close button]

        Design matches the code block control bar buttons (26px, rounded,
        subtle hover with red tint for close, teal tint for timer).
        """
        from src.design_system.tokens import get_colors
        from PyQt6.QtWidgets import QToolButton, QWidget, QHBoxLayout
        from PyQt6.QtCore import Qt, QSize

        colors = get_colors()
        BTN_SIZE = 20  # compact for tab bar
        H_MARGIN = 4   # horizontal margins (2 each side)

        # --- Resizable container ---
        # QTabBar caches the button sizeHint at setTabButton time, so we
        # use a wrapper whose sizeHint/minimumSizeHint change dynamically
        # when the timer icon is shown/hidden.
        class _TabButtonContainer(QWidget):
            """Container that reports correct sizeHint depending on
            whether the timer icon is visible."""
            def __init__(self, btn_size, h_margin, parent=None):
                super().__init__(parent)
                self._btn_size = btn_size
                self._h_margin = h_margin
                self._timer_visible = False

            def set_timer_visible(self, visible):
                self._timer_visible = visible
                self.updateGeometry()          # tell QTabBar to re-layout

            def sizeHint(self):
                n = 2 if self._timer_visible else 1
                w = self._btn_size * n + self._h_margin
                return QSize(w, self._btn_size)

            def minimumSizeHint(self):
                return self.sizeHint()

        container = _TabButtonContainer(BTN_SIZE, H_MARGIN)
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(2, 0, 2, 0)
        container_layout.setSpacing(0)

        # Timer icon (hidden by default, shown when periodic is active)
        timer_icon = QToolButton()
        timer_icon.setIcon(qta.icon("mdi.timer-outline", color="#4ec9b0", scale_factor=0.7))
        timer_icon.setFixedSize(BTN_SIZE, BTN_SIZE)
        timer_icon.setVisible(False)
        timer_icon.setObjectName("timer_icon")
        timer_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        timer_icon.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: {BTN_SIZE // 2}px;
                padding: 0px;
            }}
            QToolButton:hover {{
                background: rgba(78, 201, 176, 0.2);
            }}
        """)
        container_layout.addWidget(timer_icon)

        # Close button
        close_btn = QToolButton()
        close_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setIcon(qta.icon("mdi.close", color=colors.text_tertiary, scale_factor=0.65))
        close_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: {BTN_SIZE // 2}px;
                padding: 0px;
            }}
            QToolButton:hover {{
                background: rgba(239, 68, 68, 0.2);
            }}
        """)

        # Swap icon color on hover for close button
        _normal_icon = qta.icon("mdi.close", color=colors.text_tertiary, scale_factor=0.65)
        _hover_icon = qta.icon("mdi.close", color="#ef4444", scale_factor=0.65)

        def on_hover_enter(event):
            close_btn.setIcon(_hover_icon)
            QToolButton.enterEvent(close_btn, event)

        def on_hover_leave(event):
            close_btn.setIcon(_normal_icon)
            QToolButton.leaveEvent(close_btn, event)

        close_btn.enterEvent = on_hover_enter
        close_btn.leaveEvent = on_hover_leave

        # IMPORTANT: Find index dynamically at click time
        # because indices change when tabs are removed
        def request_close():
            for i in range(self.count()):
                btn = self.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn == container:
                    self.tabCloseRequested.emit(i)
                    return

        close_btn.clicked.connect(request_close)

        # Timer icon click: stop periodic on that tab
        def toggle_timer():
            for i in range(self.count()):
                btn = self.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn == container:
                    widget = self.widget(i)
                    if hasattr(widget, "stop_periodic"):
                        widget.stop_periodic()
                    return

        timer_icon.clicked.connect(toggle_timer)

        container_layout.addWidget(close_btn)

        # Replace default button with container
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, container)

    def set_tab_timer_icon(self, index: int, visible: bool, interval: int = 0):
        """Show or hide the timer icon on a tab.

        Dynamically resizes the container so the tab grows/shrinks to fit.
        """
        container = self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        if not container:
            return
        from PyQt6.QtWidgets import QToolButton
        timer_icon = container.findChild(QToolButton, "timer_icon")
        if timer_icon:
            timer_icon.setVisible(visible)
            if visible and interval > 0:
                timer_icon.setToolTip(f"{interval}s")
            else:
                timer_icon.setToolTip("")

        # Tell the container its size changed so QTabBar re-lays out
        if hasattr(container, "set_timer_visible"):
            container.set_timer_visible(visible)

        # Force QTabBar to recalculate tab sizes by toggling the button
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, container)

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
