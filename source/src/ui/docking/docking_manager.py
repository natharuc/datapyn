"""
DockingManager - Gerenciador do sistema de docking

Coordena todo o sistema: indicadores, posicionamento,
persistência das configurações, etc.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QApplication, QMainWindow
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QCursor
from typing import Dict, List, Optional, Any
import json

from .dockable_widget import DockableWidget, DockPosition
from .dock_indicators import DockIndicators, DockPreview


class DockingManager(QObject):
    """Gerenciador central do sistema de docking"""

    # Sinais
    layout_changed = pyqtSignal()  # Quando layout muda

    def __init__(self, main_window: QMainWindow):
        super().__init__()

        self.main_window = main_window
        self.dockable_widgets: Dict[str, DockableWidget] = {}
        self.layout_areas: Dict[str, QWidget] = {}  # área -> container

        # Componentes visuais
        self.indicators = DockIndicators()
        self.preview = DockPreview()

        # Estado do drag
        self.is_dragging = False
        self.drag_widget = None
        self.drag_title = ""

        # Timer para atualizar indicadores
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_drag_state)
        self.update_timer.setSingleShot(False)

        self._setup_layout_areas()
        self._setup_event_filters()

    def _setup_layout_areas(self):
        """Configura áreas de layout principal"""
        central_widget = QWidget()
        self.main_window.setCentralWidget(central_widget)

        # Layout principal com splitters
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Splitter horizontal principal
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Áreas: Left, Center, Right
        self.left_area = QWidget()
        self.left_area.setMinimumWidth(200)
        self.left_area.setVisible(False)  # Inicialmente oculto

        # Área central com splitter vertical
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)

        self.top_area = QWidget()
        self.top_area.setMinimumHeight(150)
        self.top_area.setVisible(False)

        self.center_area = QWidget()  # Área principal (editores)

        self.bottom_area = QWidget()
        self.bottom_area.setMinimumHeight(150)
        self.bottom_area.setVisible(False)

        self.center_splitter.addWidget(self.top_area)
        self.center_splitter.addWidget(self.center_area)
        self.center_splitter.addWidget(self.bottom_area)

        self.right_area = QWidget()
        self.right_area.setMinimumWidth(200)
        self.right_area.setVisible(False)

        # Adiciona ao splitter principal
        self.main_splitter.addWidget(self.left_area)
        self.main_splitter.addWidget(self.center_splitter)
        self.main_splitter.addWidget(self.right_area)

        # Proporções iniciais
        self.main_splitter.setSizes([0, 800, 0])  # Center expanded
        self.center_splitter.setSizes([0, 600, 0])  # Center expanded

        # Mapear áreas
        self.layout_areas = {
            "left": self.left_area,
            "right": self.right_area,
            "top": self.top_area,
            "bottom": self.bottom_area,
            "center": self.center_area,
        }

        # Layouts para cada área
        for area_name, area_widget in self.layout_areas.items():
            if area_name != "center":  # Center é gerenciado externamente
                layout = QVBoxLayout(area_widget)
                layout.setContentsMargins(2, 2, 2, 2)

    def _setup_event_filters(self):
        """Configura filtros de eventos para drag global"""
        self.main_window.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

    def register_dockable(self, name: str, widget: DockableWidget):
        """Registra um widget dockable"""
        self.dockable_widgets[name] = widget

        # Conecta sinais
        widget.tab_detached.connect(self._on_tab_detached)
        widget.tab_dropped.connect(self._on_tab_dropped)

    def create_dockable_panel(self, name: str, title: str = "", show_header: bool = False) -> DockableWidget:
        """Cria um novo painel dockable"""
        panel = DockableWidget(title or name, show_header=show_header)
        self.register_dockable(name, panel)
        return panel

    def dock_widget(self, widget: DockableWidget, position: str, show: bool = True):
        """Ancora um widget em uma posição específica"""
        if position not in self.layout_areas:
            return

        area = self.layout_areas[position]
        area.layout().addWidget(widget)

        if show:
            area.setVisible(True)
            self._adjust_splitter_sizes()

    def _adjust_splitter_sizes(self):
        """Ajusta tamanhos dos splitters baseado nas áreas visíveis"""
        # Splitter horizontal
        left_size = 250 if self.left_area.isVisible() else 0
        right_size = 250 if self.right_area.isVisible() else 0
        center_size = max(400, self.main_window.width() - left_size - right_size)

        self.main_splitter.setSizes([left_size, center_size, right_size])

        # Splitter vertical
        top_size = 200 if self.top_area.isVisible() else 0
        bottom_size = 200 if self.bottom_area.isVisible() else 0
        center_v_size = max(300, self.main_window.height() - top_size - bottom_size)

        self.center_splitter.setSizes([top_size, center_v_size, bottom_size])

    def _on_tab_detached(self, title: str, widget: QWidget):
        """Quando uma aba é destacada"""
        self.drag_title = title
        self.drag_widget = widget
        self.is_dragging = True

        print(f"DEBUG: Aba destacada - {title}")

        # Mostra indicadores
        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)
        if target_widget:
            self.indicators.show_at_widget(target_widget, cursor_pos)

        # Inicia timer para atualizar estado
        self.update_timer.start(50)  # 20 FPS

    def _on_tab_dropped(self, title: str, widget: QWidget, position: int, pos: QPoint):
        """Quando uma aba é solta"""
        # Encontra o widget sob o cursor
        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)

        # Verifica se foi solto sobre um painel dockable existente
        target_panel = self._find_target_dockable_panel(target_widget)

        self._finish_drag()

        # Converte int de volta para DockPosition
        dock_position = DockPosition(position)

        if target_panel and dock_position == DockPosition.CENTER:
            # Adiciona diretamente ao painel existente como nova aba
            target_panel.add_tab(widget, title)
        else:
            # Processa o drop baseado na posição
            target_area = self._position_to_area(dock_position)
            if target_area:
                self._create_or_add_to_panel(title, widget, target_area, target_panel)

    def _find_target_dockable_panel(self, widget: QWidget) -> Optional[DockableWidget]:
        """Encontra painel dockable mais próximo do widget"""
        if not widget:
            return None

        # Percorre hierarquia para cima procurando DockableWidget
        current = widget
        while current:
            if isinstance(current, DockableWidget):
                return current
            current = current.parent()

        return None

    def _update_drag_state(self):
        """Atualiza estado durante o drag"""
        if not self.is_dragging:
            self.update_timer.stop()
            return

        cursor_pos = QCursor.pos()
        target_widget = QApplication.widgetAt(cursor_pos)

        # Encontra painel dockable sob o cursor
        target_panel = self._find_target_dockable_panel(target_widget)

        if target_panel:
            # Mostra indicadores específicos do painel
            self.indicators.show_at_widget(target_panel, cursor_pos)
            highlighted_position = self.indicators.update_highlight(cursor_pos)

            if highlighted_position:
                preview_rect = self._calculate_preview_rect_for_panel(highlighted_position, target_panel)
                if preview_rect.isValid():
                    self.preview.show_preview(preview_rect)
                else:
                    self.preview.hide_preview()
            else:
                self.preview.hide_preview()
        else:
            # Fallback para áreas gerais
            if target_widget:
                self.indicators.show_at_widget(target_widget, cursor_pos)
                highlighted_position = self.indicators.update_highlight(cursor_pos)

                if highlighted_position:
                    preview_rect = self._calculate_preview_rect(highlighted_position, cursor_pos)
                    if preview_rect.isValid():
                        self.preview.show_preview(preview_rect)
                    else:
                        self.preview.hide_preview()
                else:
                    self.preview.hide_preview()
            else:
                self.indicators.hide_indicators()
                self.preview.hide_preview()

    def _calculate_preview_rect_for_panel(self, position: DockPosition, panel: DockableWidget) -> QRect:
        """Calcula retângulo do preview para um painel específico"""
        if not panel.isVisible():
            return QRect()

        panel_rect = panel.geometry()
        global_rect = QRect(panel.mapToGlobal(panel_rect.topLeft()), panel_rect.size())

        if position == DockPosition.CENTER:
            # Aba - destaca área de abas
            tab_height = 30
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), tab_height)
        elif position == DockPosition.LEFT:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width() // 2, global_rect.height())
        elif position == DockPosition.RIGHT:
            return QRect(
                global_rect.x() + global_rect.width() // 2,
                global_rect.y(),
                global_rect.width() // 2,
                global_rect.height(),
            )
        elif position == DockPosition.TOP:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), global_rect.height() // 2)
        elif position == DockPosition.BOTTOM:
            return QRect(
                global_rect.x(),
                global_rect.y() + global_rect.height() // 2,
                global_rect.width(),
                global_rect.height() // 2,
            )

        return QRect()

    def _calculate_preview_rect(self, position: DockPosition, cursor_pos: QPoint) -> QRect:
        """Calcula retângulo do preview baseado na posição"""
        # Encontra widget sob o cursor
        widget = QApplication.widgetAt(cursor_pos)
        if not widget:
            return QRect()

        # Encontra área dockable mais próxima
        for area_name, area_widget in self.layout_areas.items():
            if area_widget.isAncestorOf(widget) or area_widget == widget:
                return self._get_preview_rect_for_area(position, area_widget)

        return QRect()

    def _get_preview_rect_for_area(self, position: DockPosition, area_widget: QWidget) -> QRect:
        """Calcula retângulo do preview para uma área específica"""
        if not area_widget.isVisible():
            return QRect()

        rect = area_widget.geometry()
        global_rect = QRect(area_widget.mapToGlobal(rect.topLeft()), rect.size())

        # Ajusta baseado na posição
        margin = 20

        if position == DockPosition.LEFT:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width() // 2, global_rect.height())
        elif position == DockPosition.RIGHT:
            return QRect(
                global_rect.x() + global_rect.width() // 2,
                global_rect.y(),
                global_rect.width() // 2,
                global_rect.height(),
            )
        elif position == DockPosition.TOP:
            return QRect(global_rect.x(), global_rect.y(), global_rect.width(), global_rect.height() // 2)
        elif position == DockPosition.BOTTOM:
            return QRect(
                global_rect.x(),
                global_rect.y() + global_rect.height() // 2,
                global_rect.width(),
                global_rect.height() // 2,
            )
        elif position == DockPosition.CENTER:
            return global_rect.adjusted(margin, margin, -margin, -margin)

        return QRect()

    def _position_to_area(self, position: DockPosition) -> Optional[str]:
        """Converte DockPosition para nome da área"""
        mapping = {
            DockPosition.LEFT: "left",
            DockPosition.RIGHT: "right",
            DockPosition.TOP: "top",
            DockPosition.BOTTOM: "bottom",
            DockPosition.CENTER: "center",
        }
        return mapping.get(position)

    def _create_or_add_to_panel(self, title: str, widget: QWidget, area_name: str, target_panel: DockableWidget = None):
        """Cria painel ou adiciona a painel existente"""
        area = self.layout_areas[area_name]

        # Se foi especificado um painel alvo, adiciona diretamente a ele
        if target_panel:
            target_panel.add_tab(widget, title)
            return target_panel

        # Procura painel existente na área
        existing_panel = None
        for i in range(area.layout().count()):
            item = area.layout().itemAt(i)
            if item and isinstance(item.widget(), DockableWidget):
                existing_panel = item.widget()
                break

        if existing_panel:
            # Adiciona como nova aba
            existing_panel.add_tab(widget, title)
            return existing_panel
        else:
            # Cria novo painel
            new_panel = DockableWidget(title, show_header=False)
            new_panel.add_tab(widget, title)
            self.dock_widget(new_panel, area_name)
            return new_panel

    def _finish_drag(self):
        """Finaliza operação de drag"""
        self.is_dragging = False
        self.drag_widget = None
        self.drag_title = ""

        # Esconde indicadores e preview
        self.indicators.hide_indicators()
        self.preview.hide_preview()

        # Para timer
        self.update_timer.stop()

        # Emite sinal de mudança de layout
        self.layout_changed.emit()

    def save_layout(self) -> Dict[str, Any]:
        """Salva configuração atual do layout"""
        layout_config = {
            "version": "1.0",
            "areas": {},
            "splitter_sizes": {"main": self.main_splitter.sizes(), "center": self.center_splitter.sizes()},
            "panels": {},
        }

        # Salva configuração de cada área
        for area_name, area_widget in self.layout_areas.items():
            if area_widget.isVisible() and area_widget.layout().count() > 0:
                panels_in_area = []
                for i in range(area_widget.layout().count()):
                    item = area_widget.layout().itemAt(i)
                    if item and isinstance(item.widget(), DockableWidget):
                        panel = item.widget()
                        panel_config = {"title": panel.title, "visible": panel.isVisible(), "tabs": []}

                        # Salva configuração das abas
                        for j in range(panel.tab_widget.count()):
                            tab_title = panel.tab_widget.tabText(j)
                            tab_widget = panel.tab_widget.widget(j)
                            panel_config["tabs"].append(
                                {
                                    "title": tab_title,
                                    "widget_class": tab_widget.__class__.__name__,
                                    "current": j == panel.tab_widget.currentIndex(),
                                }
                            )

                        panels_in_area.append(panel_config)

                if panels_in_area:
                    layout_config["areas"][area_name] = {"visible": True, "panels": panels_in_area}

        # Salva referências dos painéis registrados
        for name, widget in self.dockable_widgets.items():
            layout_config["panels"][name] = {"title": widget.title, "visible": widget.isVisible()}

        return layout_config

    def load_layout(self, config: Dict[str, Any]):
        """Carrega configuração do layout"""
        if not config or config.get("version") != "1.0":
            return False

        try:
            # Restaura tamanhos dos splitters
            if "splitter_sizes" in config:
                sizes = config["splitter_sizes"]
                if "main" in sizes and len(sizes["main"]) == 3:
                    self.main_splitter.setSizes(sizes["main"])
                if "center" in sizes and len(sizes["center"]) == 3:
                    self.center_splitter.setSizes(sizes["center"])

            # Restaura visibilidade das áreas
            for area_name, area_config in config.get("areas", {}).items():
                if area_name in self.layout_areas:
                    area_widget = self.layout_areas[area_name]
                    area_widget.setVisible(area_config.get("visible", False))

            return True

        except Exception as e:
            print(f"Erro ao carregar layout: {e}")
            return False

    def get_default_layout(self) -> Dict[str, Any]:
        """Retorna configuração de layout padrão"""
        return {
            "version": "1.0",
            "areas": {"bottom": {"visible": True}, "right": {"visible": True}},
            "splitter_sizes": {
                "main": [0, 800, 250],  # left, center, right
                "center": [0, 600, 200],  # top, center, bottom
            },
            "panels": {},
        }

    def restore_default_layout(self):
        """Restaura layout padrão"""
        default_config = self.get_default_layout()
        self.load_layout(default_config)

        # Força ajuste dos tamanhos
        self._adjust_splitter_sizes()

    def eventFilter(self, obj, event):
        """Filtro de eventos para capturar drags globais"""
        # Captura eventos de mouse para finalizar drag quando solto fora
        if getattr(self, "is_dragging", False) and event.type() in [event.Type.MouseButtonRelease, event.Type.Drop]:
            if hasattr(event, "button") and event.button() == Qt.MouseButton.LeftButton:
                print(f"DEBUG: Mouse release detectado durante drag - criando painel flutuante")
                # Drop fora de área válida - criar painel flutuante
                if self.drag_widget and self.drag_title:
                    self._create_floating_panel()
                self._finish_drag()
                return True

        return super().eventFilter(obj, event)

    def _create_floating_panel(self):
        """Cria painel flutuante quando drop é fora de área válida"""
        if not self.drag_widget or not self.drag_title:
            return

        print(f"DEBUG: Criando painel flutuante para {self.drag_title}")

        # Cria novo painel
        new_panel = DockableWidget(self.drag_title, show_header=True)
        new_panel.add_tab(self.drag_widget, self.drag_title)

        # Torna flutuante
        new_panel.setParent(None)
        new_panel.setWindowFlags(Qt.WindowType.Window)

        # Posiciona próximo ao cursor
        cursor_pos = QCursor.pos()
        new_panel.move(cursor_pos.x() - 100, cursor_pos.y() - 50)
        new_panel.resize(400, 300)
        new_panel.show()

        # Registra painel
        panel_name = f"floating_{len(self.dockable_widgets)}"
        self.register_dockable(panel_name, new_panel)

        print(f"DEBUG: Painel flutuante criado - {self.drag_title}")
