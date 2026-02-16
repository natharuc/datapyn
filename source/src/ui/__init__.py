"""
DataPyn UI

Componentized structure:
- components/: Reusable widgets (ResultsViewer, SessionWidget)
- dialogs/: Modal dialogs (ConnectionEditDialog, SettingsDialog)
- main_window.py: Main window
"""

from .main_window import MainWindow
from .components import ResultsViewer, SessionWidget
from .dialogs import ConnectionEditDialog, ConnectionsManagerDialog, SettingsDialog

__all__ = [
    "MainWindow",
    "ResultsViewer",
    "SessionWidget",
    "ConnectionEditDialog",
    "ConnectionsManagerDialog",
    "SettingsDialog",
]
