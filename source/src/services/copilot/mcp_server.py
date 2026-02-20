"""
MCP Server - Model Context Protocol server for DataPyn.

Implements the MCP protocol (JSON-RPC 2.0) to expose DataPyn tools
to external clients like GitHub Copilot.

The server runs in a background thread and processes requests via
signal/slot communication with the main UI thread.
"""

import json
import logging
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .mcp_tools import MCPToolRegistry

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPServer(QObject):
    """
    MCP server that processes JSON-RPC requests and dispatches to tools.

    This server operates within the Qt event loop, using signals/slots
    to communicate between the processing layer and the UI thread.

    Signals:
        response_ready(str): Emitted when a response is ready to send.
        tool_executed(str, dict): Emitted when a tool is executed (name, result).
    """

    response_ready = pyqtSignal(str)
    tool_executed = pyqtSignal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_registry = MCPToolRegistry()
        self._initialized = False

    @property
    def tool_registry(self) -> MCPToolRegistry:
        return self._tool_registry

    def set_main_window(self, main_window) -> None:
        """Set the main window reference for tool operations."""
        self._tool_registry.set_main_window(main_window)

    def handle_message(self, message: str) -> Optional[str]:
        """
        Process an incoming JSON-RPC message and return a response.

        Args:
            message: JSON-RPC 2.0 message string.

        Returns:
            JSON-RPC response string, or None for notifications.
        """
        try:
            request = json.loads(message)
        except json.JSONDecodeError as e:
            return self._error_response(None, -32700, f"Parse error: {e}")

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        # Route to handler
        if method == "initialize":
            result = self._handle_initialize(params)
        elif method == "tools/list":
            result = self._handle_tools_list(params)
        elif method == "tools/call":
            result = self._handle_tools_call(params)
        elif method == "notifications/initialized":
            self._initialized = True
            return None  # Notifications have no response
        elif method == "ping":
            result = {}
        else:
            return self._error_response(req_id, -32601, f"Method not found: {method}")

        if req_id is not None:
            return self._success_response(req_id, result)
        return None

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "datapyn-mcp",
                "version": "1.0.0",
            },
        }

    def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        return {"tools": self._tool_registry.list_tools()}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        result = self._tool_registry.execute(tool_name, arguments)
        self.tool_executed.emit(tool_name, result)

        if "error" in result:
            return {
                "content": [{"type": "text", "text": result["error"]}],
                "isError": True,
            }

        return result

    def _success_response(self, req_id: Any, result: Dict[str, Any]) -> str:
        """Build a JSON-RPC success response."""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }
        return json.dumps(response)

    def _error_response(self, req_id: Any, code: int, message: str) -> str:
        """Build a JSON-RPC error response."""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
        return json.dumps(response)
