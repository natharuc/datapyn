"""
Sistema de Docking - Painéis repositionaveis como Visual Studio

Permite arrastar e reposicionar abas (Resultados, Output, Variáveis)
em qualquer área da tela com indicadores visuais.
"""

from .dock_indicators import DockIndicators, DockPreview
from .dockable_widget import DockableWidget, DockPosition, DragDropTabWidget
from .docking_main_window import DockingMainWindow
from .docking_manager import DockingManager

__all__ = [
    "DockableWidget",
    "DragDropTabWidget",
    "DockPosition",
    "DockIndicators",
    "DockPreview",
    "DockingManager",
    "DockingMainWindow",
]
