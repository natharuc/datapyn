"""
Docking System - Repositionable panels like Visual Studio

Allows dragging and repositioning tabs (Results, Output, Variables)
anywhere on screen with visual indicators.
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
