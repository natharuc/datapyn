"""The ACP agent's stdio MCP process uses the existing bounded proxy."""

def main():
    from src.services.pynia.acp.mcp_stdio import _main
    return _main()
