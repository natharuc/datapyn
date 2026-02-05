"""
DockIndicators - Indicadores visuais de posicionamento

Mostra onde a aba será posicionada durante o drag, 
igual aos indicadores do Visual Studio.
"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, QTimer
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPixmap
from typing import Optional
from .dockable_widget import DockPosition


class DockIndicators(QWidget):
    """Indicadores visuais para docking"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.target_widget = None
        self.current_position = None
        self.indicator_rects = {}
        
        self.setFixedSize(200, 200)
        self._calculate_indicators()
    
    def _calculate_indicators(self):
        """Calcula posições dos indicadores"""
        center = QPoint(100, 100)
        size = 40
        
        # Indicadores em cruz
        self.indicator_rects = {
            DockPosition.TOP: QRect(center.x() - size//2, center.y() - size - 10, size, size),
            DockPosition.BOTTOM: QRect(center.x() - size//2, center.y() + 10, size, size),
            DockPosition.LEFT: QRect(center.x() - size - 10, center.y() - size//2, size, size),
            DockPosition.RIGHT: QRect(center.x() + 10, center.y() - size//2, size, size),
            DockPosition.CENTER: QRect(center.x() - size//2, center.y() - size//2, size, size)
        }
    
    def show_at_widget(self, widget: QWidget, cursor_pos: QPoint):
        """Mostra indicadores próximos ao widget"""
        self.target_widget = widget
        
        # Posiciona no centro do widget
        widget_center = widget.rect().center()
        global_center = widget.mapToGlobal(widget_center)
        
        # Ajusta para manter na tela
        screen = QApplication.screenAt(global_center)
        if screen:
            screen_rect = screen.geometry()
            x = max(0, min(global_center.x() - 100, screen_rect.width() - 200))
            y = max(0, min(global_center.y() - 100, screen_rect.height() - 200))
            self.move(x, y)
        
        self.show()
        self.update()
    
    def update_highlight(self, cursor_pos: QPoint) -> Optional[DockPosition]:
        """Atualiza destaque baseado na posição do cursor"""
        if not self.target_widget:
            return None
        
        # Converte posição do cursor para coordenadas locais dos indicadores
        local_pos = self.mapFromGlobal(cursor_pos)
        
        # Verifica qual indicador está sob o cursor
        new_position = None
        for position, rect in self.indicator_rects.items():
            if rect.contains(local_pos):
                new_position = position
                break
        
        # Atualiza se mudou
        if new_position != self.current_position:
            self.current_position = new_position
            self.update()
        
        return self.current_position
    
    def hide_indicators(self):
        """Esconde indicadores"""
        self.current_position = None
        self.target_widget = None
        self.hide()
    
    def paintEvent(self, event):
        """Desenha os indicadores"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fundo semi-transparente
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        # Desenha cada indicador
        for position, rect in self.indicator_rects.items():
            self._draw_indicator(painter, position, rect)
        
        painter.end()
    
    def _draw_indicator(self, painter: QPainter, position: DockPosition, rect: QRect):
        """Desenha um indicador"""
        # Cores
        if position == self.current_position:
            bg_color = QColor(0, 122, 204, 200)  # Azul VS Code
            border_color = QColor(0, 122, 204)
            text_color = QColor(255, 255, 255)
        else:
            bg_color = QColor(60, 60, 60, 150)
            border_color = QColor(100, 100, 100)
            text_color = QColor(204, 204, 204)
        
        # Desenha fundo
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 2))
        painter.drawRoundedRect(rect, 6, 6)
        
        # Desenha ícone/texto
        painter.setPen(QPen(text_color))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        
        icon_text = self._get_icon_text(position)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, icon_text)
    
    def _get_icon_text(self, position: DockPosition) -> str:
        """Retorna texto/ícone para cada posição"""
        icons = {
            DockPosition.TOP: "↑",
            DockPosition.BOTTOM: "↓", 
            DockPosition.LEFT: "←",
            DockPosition.RIGHT: "→",
            DockPosition.CENTER: "⊞"
        }
        return icons.get(position, "?")


class DockPreview(QWidget):
    """Preview visual de onde o painel será posicionado"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.preview_rect = QRect()
    
    def show_preview(self, rect: QRect):
        """Mostra preview na área especificada"""
        self.preview_rect = rect
        self.setGeometry(rect)
        self.show()
        self.update()
    
    def hide_preview(self):
        """Esconde preview"""
        self.hide()
    
    def paintEvent(self, event):
        """Desenha o preview"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fundo azul semi-transparente
        bg_color = QColor(0, 122, 204, 80)
        border_color = QColor(0, 122, 204, 160)
        
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 2))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
        
        painter.end()