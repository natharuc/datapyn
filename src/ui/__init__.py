"""
UI do DataPyn

Estrutura componentizada:
- components/: Widgets reutilizáveis (ResultsViewer, SessionWidget)
- dialogs/: Diálogos modais (ConnectionEditDialog, SettingsDialog)
- main_window.py: Janela principal
"""
from .main_window import MainWindow
from .components import ResultsViewer, SessionWidget
from .dialogs import ConnectionEditDialog, ConnectionsManagerDialog, SettingsDialog

__all__ = [
    'MainWindow',
    'ResultsViewer',
    'SessionWidget', 
    'ConnectionEditDialog',
    'ConnectionsManagerDialog',
    'SettingsDialog'
]
