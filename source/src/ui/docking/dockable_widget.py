"""
DockableWidget - Classe base para widgets que podem ser movidos/agrupados

Similar às dock windows do Visual Studio, permite arrastar abas para
diferentes posições com indicadores visuais.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, 
    QFrame, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect, QMimeData, QSize
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QDrag, QPixmap, QFont
import qtawesome as qta
from typing import Optional, List, Dict, Any
from enum import Enum


class DockPosition(Enum):
    """Posições possíveis para docking"""
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"
    TAB = "tab"


class DockableWidget(QWidget):
    """Widget base que pode ser movido e agrupado"""
    
    # Sinais
    tab_detached = pyqtSignal(str, QWidget)  # (title, widget)
    tab_dropped = pyqtSignal(str, QWidget, int, QPoint)  # (title, widget, position, pos)
    dock_request = pyqtSignal(object, int)  # (widget, position)
    visibilityChanged = pyqtSignal(bool)  # (visible)
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        
        self.title = title
        self.widgets: Dict[str, QWidget] = {}  # título -> widget
        self.is_floating = False
        self.drag_start_position = QPoint()
        
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self):
        """Configura UI"""
        self.setMinimumSize(200, 150)
        
        # Layout principal
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Header com título e controles
        self.header = self._create_header()
        self.layout.addWidget(self.header)
        
        # Container de abas
        self.tab_widget = DragDropTabWidget(self)
        self.tab_widget.tab_detached.connect(self.tab_detached.emit)
        self.tab_widget.tab_dropped.connect(self.tab_dropped.emit)
        self.layout.addWidget(self.tab_widget)
    
    def _create_header(self) -> QFrame:
        """Cria header com título e controles"""
        header = QFrame()
        header.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        header.setFixedHeight(28)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 4, 4, 4)
        
        # Título
        self.title_label = QLabel(self.title)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Botões de controle
        self.float_btn = QPushButton()
        self.float_btn.setIcon(qta.icon('mdi.window-restore', color='#888'))
        self.float_btn.setFixedSize(20, 20)
        self.float_btn.setFlat(True)
        self.float_btn.setToolTip("Tornar flutuante")
        self.float_btn.clicked.connect(self._toggle_floating)
        layout.addWidget(self.float_btn)
        
        self.close_btn = QPushButton()
        self.close_btn.setIcon(qta.icon('mdi.close', color='#888'))
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setFlat(True)
        self.close_btn.setToolTip("Fechar painel")
        self.close_btn.clicked.connect(self.hide)
        layout.addWidget(self.close_btn)
        
        return header
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            DockableWidget {
                background-color: #2d2d30;
                border: 1px solid #404040;
                border-radius: 4px;
            }
            QFrame {
                background-color: #3c3c3c;
                border: none;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #404040;
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: #505050;
            }
        """)
    
    def add_tab(self, widget: QWidget, title: str, icon=None):
        """Adiciona uma aba"""
        index = self.tab_widget.addTab(widget, title)
        if icon:
            self.tab_widget.setTabIcon(index, icon)
        self.widgets[title] = widget
        
        # Atualiza título do painel se for a primeira aba
        if len(self.widgets) == 1:
            self.set_title(title)
    
    def remove_tab(self, title: str):
        """Remove uma aba"""
        if title in self.widgets:
            widget = self.widgets[title]
            index = self.tab_widget.indexOf(widget)
            if index >= 0:
                self.tab_widget.removeTab(index)
            del self.widgets[title]
    
    def set_title(self, title: str):
        """Define título do painel"""
        self.title = title
        self.title_label.setText(title)
    
    def _toggle_floating(self):
        """Alterna entre flutuante e ancorado"""
        self.is_floating = not self.is_floating
        
        if self.is_floating:
            self.setParent(None)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            self.show()
            self.float_btn.setIcon(qta.icon('mdi.dock-window', color='#888'))
            self.float_btn.setToolTip("Ancorar painel")
        else:
            self.float_btn.setIcon(qta.icon('mdi.window-restore', color='#888'))
            self.float_btn.setToolTip("Tornar flutuante")
    
    def get_current_widget(self) -> Optional[QWidget]:
        """Retorna widget da aba atual"""
        return self.tab_widget.currentWidget()
    
    def get_tab_count(self) -> int:
        """Retorna número de abas"""
        return self.tab_widget.count()
    
    def isEmpty(self) -> bool:
        """Verifica se painel está vazio"""
        return self.get_tab_count() == 0
    
    def show(self):
        """Override show para emitir signal"""
        was_visible = self.isVisible()
        super().show()
        if not was_visible:
            self.visibilityChanged.emit(True)
    
    def hide(self):
        """Override hide para emitir signal"""
        was_visible = self.isVisible()
        super().hide()
        if was_visible:
            self.visibilityChanged.emit(False)
    
    def setVisible(self, visible: bool):
        """Override setVisible para emitir signal"""
        was_visible = self.isVisible()
        super().setVisible(visible)
        if was_visible != visible:
            self.visibilityChanged.emit(visible)


class DragDropTabWidget(QTabWidget):
    """TabWidget com suporte a drag/drop de abas"""
    
    # Sinais
    tab_detached = pyqtSignal(str, QWidget)  # (title, widget)
    tab_dropped = pyqtSignal(str, QWidget, int, QPoint)  # (title, widget, position, pos)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setAcceptDrops(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        
        # Personalizar barra de abas
        self.tabBar().setMouseTracking(True)
        
        self._setup_style()
    
    def _setup_style(self):
        """Configura estilo das abas"""
        self.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #404040;
                background-color: #2d2d30;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #cccccc;
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #404040;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #505050;
            }
            QTabBar::close-button {
                image: url(icon:mdi.close);
                subcontrol-position: right;
            }
        """)
    
    def mousePressEvent(self, event):
        """Inicia drag se for botão esquerdo"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Detecta início do drag"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
            
        # Verifica distância mínima para iniciar drag
        if ((event.pos() - self.drag_start_position).manhattanLength() < 
            QApplication.startDragDistance()):
            return super().mouseMoveEvent(event)
        
        # Obtém aba sob o cursor
        tab_index = self.tabBar().tabAt(self.drag_start_position)
        if tab_index < 0:
            return super().mouseMoveEvent(event)
        
        self._start_drag(tab_index)
    
    def _start_drag(self, tab_index: int):
        """Inicia operação de drag"""
        tab_text = self.tabText(tab_index)
        tab_widget = self.widget(tab_index)
        
        if not tab_widget:
            return
        
        # Criar dados do drag
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"datapyn_tab:{tab_text}")
        drag.setMimeData(mime_data)
        
        # Criar pixmap da aba
        tab_rect = self.tabBar().tabRect(tab_index)
        pixmap = QPixmap(tab_rect.size())
        pixmap.fill(QColor(60, 60, 60, 200))
        
        painter = QPainter(pixmap)
        painter.setPen(QColor(204, 204, 204))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, tab_text)
        painter.end()
        
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        
        # Executar drag
        result = drag.exec(Qt.DropAction.MoveAction)
        
        if result == Qt.DropAction.MoveAction:
            # Emitir sinal de aba destacada
            self.tab_detached.emit(tab_text, tab_widget)
    
    def dragEnterEvent(self, event):
        """Aceita drops de abas"""
        if event.mimeData().hasText() and event.mimeData().text().startswith("datapyn_tab:"):
            event.acceptProposedAction()
    
    def dropEvent(self, event):
        """Processa drop de aba"""
        if not (event.mimeData().hasText() and event.mimeData().text().startswith("datapyn_tab:")):
            return
        
        tab_title = event.mimeData().text().replace("datapyn_tab:", "")
        position = self._get_drop_position(event.pos())
        
        self.tab_dropped.emit(tab_title, None, position.value, event.pos())
        event.acceptProposedAction()
    
    def _get_drop_position(self, pos: QPoint):
        """Determina posição de drop baseada na posição do cursor"""
        rect = self.rect()
        
        # Dividir em áreas
        left_area = QRect(0, 0, rect.width() // 4, rect.height())
        right_area = QRect(3 * rect.width() // 4, 0, rect.width() // 4, rect.height())
        top_area = QRect(0, 0, rect.width(), rect.height() // 4)
        bottom_area = QRect(0, 3 * rect.height() // 4, rect.width(), rect.height() // 4)
        
        if left_area.contains(pos):
            return DockPosition.LEFT
        elif right_area.contains(pos):
            return DockPosition.RIGHT
        elif top_area.contains(pos):
            return DockPosition.TOP
        elif bottom_area.contains(pos):
            return DockPosition.BOTTOM
        else:
            return DockPosition.TAB