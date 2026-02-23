"""
UI Controllers - Extracted from MainWindow God Class

Each controller handles a specific domain of functionality,
following the Single Responsibility Principle.

Controllers:
- SessionController: Session/tab management
- ConnectionController: Database connections
- ExecutionController: SQL/Python execution
- FileController: File operations
- LayoutController: Layout/docking management
"""

from src.ui.controllers.session_controller import SessionController
from src.ui.controllers.connection_controller import ConnectionController
from src.ui.controllers.execution_controller import ExecutionController

__all__ = [
    "SessionController",
    "ConnectionController",
    "ExecutionController",
]
