"""
DataPyn IDE main window package.

Provides MainWindow composed of multiple mixins for maintainability.
"""

from src.ui.main_window._main import MainWindow
from src.ui.main_window._workers import SqlWorker, PythonWorker, _read_file_with_encoding_fallback

# Re-export names that were previously accessible as src.ui.main_window.XXX
# (needed for mock.patch targets in tests and external references)
from src.database import ConnectionManager
from PyQt6.QtWidgets import QMessageBox

__all__ = [
    "MainWindow",
    "SqlWorker",
    "PythonWorker",
    "_read_file_with_encoding_fallback",
    "ConnectionManager",
    "QMessageBox",
]
