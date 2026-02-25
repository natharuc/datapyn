"""
GitHub Copilot integration for DataPyn.

This module provides MCP (Model Context Protocol) server and Copilot client
for integrating GitHub Copilot with DataPyn IDE.

Uses the official GitHub Copilot SDK (github-copilot-sdk) when available,
which communicates with the Copilot CLI via JSON-RPC.

For inline completions, uses the Copilot Language Server (LSP) when available,
which provides fast completions (<500ms).
"""

# Defensive imports for headless/CI environments
try:
    from .mcp_server import MCPServer
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"MCPServer import failed: {e}")
    MCPServer = None

try:
    from .copilot_server_manager import (
        CopilotServerManager,
        is_copilot_server_available,
        get_copilot_server_path,
    )
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"CopilotServerManager import failed: {e}")
    CopilotServerManager = None
    is_copilot_server_available = lambda: False
    get_copilot_server_path = lambda: None

try:
    from .copilot_lsp_client import CopilotLSPClient
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"CopilotLSPClient import failed: {e}")
    CopilotLSPClient = None

# Try to use SDK-based client first, fallback to legacy
try:
    from copilot import CopilotClient as _SDKClient
    # SDK available - use SDK-based wrapper
    from .copilot_client_sdk import CopilotClient
except ImportError:
    # SDK not available - use legacy HTTP client
    try:
        from .copilot_client import CopilotClient
    except ImportError as e:
        import logging
        logging.getLogger(__name__).warning(f"CopilotClient import failed: {e}")
        CopilotClient = None

# Auth service (centralized authentication)
try:
    from .copilot_auth_service import (
        CopilotAuthService,
        get_copilot_auth_service,
        reset_copilot_auth_service,
    )
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"CopilotAuthService import failed: {e}")
    CopilotAuthService = None
    get_copilot_auth_service = lambda: None
    reset_copilot_auth_service = lambda: None

__all__ = [
    "MCPServer",
    "CopilotClient",
    "CopilotServerManager",
    "CopilotLSPClient",
    "CopilotAuthService",
    "is_copilot_server_available",
    "get_copilot_server_path",
    "get_copilot_auth_service",
    "reset_copilot_auth_service",
]
