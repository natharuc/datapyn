"""Qt signal adapter for the reusable ACP stdio transport."""
from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal
from .client_transport import AcpTransport

# Kept public for existing desktop imports.
PROTOCOL_VERSION = 1


class AcpClient(QObject, AcpTransport):
    session_update = pyqtSignal(str, dict)
    permission_request = pyqtSignal(object, dict)
    rpc_error = pyqtSignal(str)
    stderr_line = pyqtSignal(str)
    process_exited = pyqtSignal(int)
    initialized = pyqtSignal(dict)

    def __init__(self, agent_id: str, parent: Optional[QObject] = None):
        QObject.__init__(self, parent)
        AcpTransport.__init__(self, agent_id)
