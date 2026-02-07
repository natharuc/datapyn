"""
Sistema de Docking - Painéis repositionaveis como Visual Studio

Permite arrastar e reposicionar abas (Resultados, Output, Variáveis)
em qualquer área da tela com indicadores visuais.
"""

from .dockable_widget import DockableWidget, DragDropTabWidget, DockPosition
from .dock_indicators import DockIndicators, DockPreview
from .docking_manager import DockingManager
from .docking_main_window import DockingMainWindow

__all__ = [
    "DockableWidget",
    "DragDropTabWidget",
    "DockPosition",
    "DockIndicators",
    "DockPreview",
    "DockingManager",
    "DockingMainWindow",
]
