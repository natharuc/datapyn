"""
DockingMainWindow - Janela principal com sistema de docking integrado

Esta classe estende QMainWindow para fornecer capacidades de
docking no estilo Visual Studio.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QSplitter, QTabWidget, QApplication
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QAction, QKeySequence
from typing import Dict, Optional, Any

from .docking_manager import DockingManager
from .dockable_widget import DockableWidget


class DockingMainWindow(QMainWindow):
    """Janela principal com sistema de docking integrado"""
    
    # Sinais
    panel_visibility_changed = pyqtSignal(str, bool)  # nome, visível
    layout_restored = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        
        # Configurações
        self.settings = QSettings('DataPyn', 'DockingLayout')
        
        # Sistema de docking
        self.docking_manager = DockingManager(self)
        
        # Painéis registrados
        self.panels: Dict[str, DockableWidget] = {}
        
        # Área central padrão (editores)
        self.central_content = QWidget()
        
        self._setup_ui()
        self._setup_menu_actions()
        self._connect_signals()
        
        # Timer para salvar layout automaticamente
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self._auto_save_layout)
        self.auto_save_timer.setSingleShot(True)
    
    def _setup_ui(self):
        """Configura interface base"""
        self.setWindowTitle("DataPyn - Docking System")
        self.resize(1200, 800)
        
        # Área central será gerenciada externamente
        # (editores, etc.)
        self.set_central_content(self.central_content)
        
        # Carrega layout salvo
        self.restore_layout()
    
    def _setup_menu_actions(self):
        """Configura ações do menu para painéis"""
        # Menu View para controlar painéis
        view_menu = self.menuBar().addMenu("&View")
        
        # Ação para resetar layout
        reset_action = QAction("&Reset Layout", self)
        reset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        reset_action.triggered.connect(self.reset_layout)
        view_menu.addAction(reset_action)
        
        view_menu.addSeparator()
        
        # Submenu para painéis
        self.panels_menu = view_menu.addMenu("&Panels")
    
    def _connect_signals(self):
        """Conecta sinais"""
        self.docking_manager.layout_changed.connect(self._on_layout_changed)
    
    def _on_layout_changed(self):
        """Chamado quando layout muda"""
        # Agenda salvamento automático
        self.auto_save_timer.start(2000)  # Salva após 2s de inatividade
    
    def _auto_save_layout(self):
        """Salva layout automaticamente"""
        self.save_layout()
    
    def set_central_content(self, widget: QWidget):
        """Define conteúdo da área central"""
        if widget:
            # Remove do layout anterior se necessário
            if widget.parent():
                widget.setParent(None)
            
            # Adiciona à área central
            central_area = self.docking_manager.layout_areas['center']
            
            # Limpa layout anterior
            layout = central_area.layout()
            if layout:
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None)
            else:
                layout = QVBoxLayout(central_area)
                layout.setContentsMargins(0, 0, 0, 0)
            
            layout.addWidget(widget)
            self.central_content = widget
    
    def add_dockable_panel(self, name: str, widget: QWidget, 
                          title: str = "", 
                          position: str = "bottom",
                          visible: bool = True) -> DockableWidget:
        """
        Adiciona um painel dockable
        
        Args:
            name: Nome único do painel
            widget: Widget conteúdo do painel  
            title: Título do painel (usa name se vazio)
            position: Posição inicial ('left', 'right', 'top', 'bottom')
            visible: Se deve mostrar inicialmente
        """
        if name in self.panels:
            # Painel já existe, apenas adiciona como aba
            existing_panel = self.panels[name]
            existing_panel.add_tab(widget, title or name)
            return existing_panel
        
        # Cria novo painel dockable
        panel = self.docking_manager.create_dockable_panel(name, title or name)
        panel.add_tab(widget, title or name)
        
        # Registra e ancora
        self.panels[name] = panel
        
        if visible:
            self.docking_manager.dock_widget(panel, position, show=True)
        
        # Adiciona ao menu
        self._add_panel_menu_action(name, panel)
        
        return panel
    
    def _add_panel_menu_action(self, name: str, panel: DockableWidget):
        """Adiciona ação do painel ao menu"""
        action = QAction(f"&{panel.title}", self)
        action.setCheckable(True)
        action.setChecked(panel.isVisible())
        
        # Conecta toggle
        def toggle_panel():
            if panel.isVisible():
                panel.hide()
            else:
                panel.show()
            action.setChecked(panel.isVisible())
            self.panel_visibility_changed.emit(name, panel.isVisible())
        
        action.triggered.connect(toggle_panel)
        self.panels_menu.addAction(action)
        
        # Atualiza ação quando visibilidade muda
        def update_action():
            action.setChecked(panel.isVisible())
        
        panel.visibilityChanged.connect(update_action)
    
    def get_panel(self, name: str) -> Optional[DockableWidget]:
        """Obtém painel pelo nome"""
        return self.panels.get(name)
    
    def show_panel(self, name: str):
        """Mostra painel específico"""
        panel = self.panels.get(name)
        if panel:
            panel.show()
            panel.raise_()
            self.panel_visibility_changed.emit(name, True)
    
    def hide_panel(self, name: str):
        """Esconde painel específico"""
        panel = self.panels.get(name)
        if panel:
            panel.hide()
            self.panel_visibility_changed.emit(name, False)
    
    def toggle_panel(self, name: str):
        """Alterna visibilidade do painel"""
        panel = self.panels.get(name)
        if panel:
            if panel.isVisible():
                self.hide_panel(name)
            else:
                self.show_panel(name)
    
    def reset_layout(self):
        """Reseta layout para configuração padrão"""
        # Esconde todos os painéis
        for panel in self.panels.values():
            panel.hide()
        
        # Esconde áreas
        for area in self.docking_manager.layout_areas.values():
            if area != self.docking_manager.center_area:
                area.setVisible(False)
        
        # Reajusta splitters
        self.docking_manager._adjust_splitter_sizes()
        
        # Salva o reset
        self.save_layout()
    
    def save_layout(self):
        """Salva layout atual"""
        config = self.docking_manager.save_layout()
        
        # Adiciona configurações da janela
        config['window'] = {
            'geometry': self.saveGeometry().data().hex(),
            'state': self.saveState().data().hex() if hasattr(self, 'saveState') else None
        }
        
        # Salva visibilidade dos painéis
        config['panels_visibility'] = {}
        for name, panel in self.panels.items():
            config['panels_visibility'][name] = panel.isVisible()
        
        # Salva nas configurações
        self.settings.setValue('layout', config)
        self.settings.sync()
    
    def restore_layout(self):
        """Restaura layout salvo"""
        config = self.settings.value('layout', {})
        
        if not config:
            return
        
        # Restaura configurações da janela
        if 'window' in config:
            window_config = config['window']
            if 'geometry' in window_config and window_config['geometry']:
                try:
                    geometry = bytes.fromhex(window_config['geometry'])
                    self.restoreGeometry(geometry)
                except:
                    pass
            
            if 'state' in window_config and window_config['state']:
                try:
                    state = bytes.fromhex(window_config['state'])
                    if hasattr(self, 'restoreState'):
                        self.restoreState(state)
                except:
                    pass
        
        # Restaura layout do docking manager
        self.docking_manager.load_layout(config)
        
        # Restaura visibilidade dos painéis
        if 'panels_visibility' in config:
            visibility = config['panels_visibility']
            for name, is_visible in visibility.items():
                if name in self.panels:
                    panel = self.panels[name]
                    panel.setVisible(is_visible)
        
        self.layout_restored.emit()
    
    def closeEvent(self, event):
        """Salva layout ao fechar"""
        self.save_layout()
        super().closeEvent(event)
    
    def showEvent(self, event):
        """Evento ao mostrar janela"""
        super().showEvent(event)
        # Força reajuste dos splitters
        QTimer.singleShot(100, self.docking_manager._adjust_splitter_sizes)
    
    def resizeEvent(self, event):
        """Evento de redimensionamento"""
        super().resizeEvent(event)
        # Reajusta splitters quando redimensiona
        if hasattr(self, 'docking_manager'):
            QTimer.singleShot(10, self.docking_manager._adjust_splitter_sizes)