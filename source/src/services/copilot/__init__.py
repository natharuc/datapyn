"""DataPyn MCP server used by Pynia ACP agents."""

try:
    from .mcp_server import MCPServer
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning("MCPServer import failed: %s", e)
    MCPServer = None

__all__ = ["MCPServer"]
