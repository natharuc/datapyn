"""
DataPyn Dialogs

Dialogs are modal windows for user interaction.
"""

from .connection_edit_dialog import ConnectionEditDialog
from .connections_manager_dialog import ConnectionsManagerDialog
from .settings_dialog import SettingsDialog
from .package_manager_dialog import PackageManagerDialog
from .copilot_download_dialog import CopilotDownloadDialog

__all__ = [
    "ConnectionEditDialog",
    "ConnectionsManagerDialog",
    "SettingsDialog",
    "PackageManagerDialog",
    "CopilotDownloadDialog",
]
