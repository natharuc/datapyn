"""
Diálogos do DataPyn

Diálogos são janelas modais para interação com o usuário.
"""
from .connection_edit_dialog import ConnectionEditDialog
from .connections_manager_dialog import ConnectionsManagerDialog
from .settings_dialog import SettingsDialog

__all__ = [
    'ConnectionEditDialog',
    'ConnectionsManagerDialog',
    'SettingsDialog'
]
