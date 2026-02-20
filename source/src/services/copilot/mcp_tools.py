"""
MCP Tools - Tools exposed to Copilot via the Model Context Protocol.

Each tool maps to a DataPyn operation:
- create_tab: Creates a new session tab
- create_block: Creates a new code block in the current session
- edit_block: Edits the content of a block
- connect_database: Connects the current session to a database
- create_connection: Creates a new saved database connection
- open_connection: Opens an existing saved connection
- read_schema: Reads the loaded database schema
- get_context: Gets current editor context (active code, language, etc.)
"""

import json
import logging
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class MCPTool:
    """Represents a single MCP tool with metadata and handler."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_schema(self) -> Dict[str, Any]:
        """Return MCP-compatible tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
            },
        }


class MCPToolRegistry:
    """
    Registry of all MCP tools available for Copilot.

    Tools operate on a reference to the main window to access
    sessions, blocks, connections, and schema.

    Usage:
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)
        result = registry.execute("create_tab", {"title": "My Tab"})
    """

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._main_window = None
        self._register_tools()

    def set_main_window(self, main_window) -> None:
        """Set reference to the main window for tool operations."""
        self._main_window = main_window

    def _register_tools(self) -> None:
        """Register all available tools."""
        self._register(MCPTool(
            name="create_tab",
            description="Create a new editor tab (session) in DataPyn.",
            parameters={
                "title": {
                    "type": "string",
                    "description": "Title for the new tab.",
                },
            },
            handler=self._create_tab,
        ))

        self._register(MCPTool(
            name="create_block",
            description="Create a new code block in the current session.",
            parameters={
                "language": {
                    "type": "string",
                    "description": "Block language: python, sql, or cross.",
                    "enum": ["python", "sql", "cross"],
                },
                "code": {
                    "type": "string",
                    "description": "Initial code content for the block.",
                },
            },
            handler=self._create_block,
        ))

        self._register(MCPTool(
            name="edit_block",
            description="Edit the code content of the currently focused block.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "New code content for the block.",
                },
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to edit (0-based). If not provided, edits the focused block.",
                },
            },
            handler=self._edit_block,
        ))

        self._register(MCPTool(
            name="connect_database",
            description="Connect the current session to a saved database connection.",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Name of the saved connection to use.",
                },
            },
            handler=self._connect_database,
        ))

        self._register(MCPTool(
            name="create_connection",
            description="Create and save a new database connection configuration.",
            parameters={
                "name": {
                    "type": "string",
                    "description": "Connection name.",
                },
                "db_type": {
                    "type": "string",
                    "description": "Database type.",
                    "enum": ["mssql", "mysql", "postgresql", "mariadb", "sqlite", "databricks"],
                },
                "host": {
                    "type": "string",
                    "description": "Database host address.",
                },
                "port": {
                    "type": "integer",
                    "description": "Database port number.",
                },
                "database": {
                    "type": "string",
                    "description": "Database name.",
                },
                "username": {
                    "type": "string",
                    "description": "Database username.",
                },
            },
            handler=self._create_connection,
        ))

        self._register(MCPTool(
            name="open_connection",
            description="Open (activate) an existing saved connection by name.",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Name of the saved connection to open.",
                },
            },
            handler=self._open_connection,
        ))

        self._register(MCPTool(
            name="read_schema",
            description="Read the loaded database schema (tables, columns, types).",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Connection name to read schema from. Uses current connection if not provided.",
                },
            },
            handler=self._read_schema,
        ))

        self._register(MCPTool(
            name="get_context",
            description="Get the current editor context: active session, blocks, code, language, connection.",
            parameters={},
            handler=self._get_context,
        ))

    def _register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of all tool schemas for MCP protocol."""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a tool by name with the given arguments.

        Returns:
            Dict with "content" (list of text results) or "error" key.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        if not self._main_window:
            return {"error": "Main window not available. Cannot execute tools."}

        try:
            result = tool.handler(arguments or {})
            return result
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return {"error": str(e)}

    # === Tool Implementations ===

    def _create_tab(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new tab/session."""
        title = args.get("title")
        mw = self._main_window

        if hasattr(mw, "session_manager") and mw.session_manager:
            session = mw.session_manager.create_session(title=title)
            return {
                "content": [{"type": "text", "text": f"Tab created: '{session.title}' (id: {session.session_id})"}]
            }

        return {"error": "Session manager not available."}

    def _create_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new code block in the current session."""
        language = args.get("language", "python")
        code = args.get("code", "")
        mw = self._main_window

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session. Create a tab first."}

        block_editor = session_widget.block_editor
        if not block_editor:
            return {"error": "Block editor not available."}

        block = block_editor.add_block(language=language)
        if code and block:
            block.set_code(code)

        block_count = len(block_editor.blocks)
        return {
            "content": [{"type": "text", "text": f"Block created (language: {language}, index: {block_count - 1})"}]
        }

    def _edit_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Edit code in a block."""
        code = args.get("code", "")
        block_index = args.get("block_index")
        mw = self._main_window

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = session_widget.block_editor
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks:
            return {"error": "No blocks in the current session."}

        if block_index is not None:
            if 0 <= block_index < len(blocks):
                target_block = blocks[block_index]
            else:
                return {"error": f"Block index {block_index} out of range (0-{len(blocks) - 1})."}
        else:
            target_block = block_editor.focused_block
            if not target_block and blocks:
                target_block = blocks[-1]

        if target_block:
            target_block.set_code(code)
            return {"content": [{"type": "text", "text": f"Block updated with {len(code)} characters."}]}

        return {"error": "No block found to edit."}

    def _connect_database(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Connect the current session to a database."""
        connection_name = args.get("connection_name", "")
        if not connection_name:
            return {"error": "connection_name is required."}

        mw = self._main_window
        conn_manager = getattr(mw, "connection_manager", None)
        if not conn_manager:
            return {"error": "Connection manager not available."}

        config = conn_manager.get_connection_config(connection_name)
        if not config:
            saved = list(conn_manager.saved_configs.get("connections", {}).keys())
            return {"error": f"Connection '{connection_name}' not found. Available: {saved}"}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        if hasattr(session_widget, "connect_to_database"):
            session_widget.connect_to_database(connection_name)
            return {
                "content": [{"type": "text", "text": f"Connection request sent for '{connection_name}'."}]
            }

        return {"error": "Session widget does not support connect_to_database."}

    def _create_connection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new saved connection configuration."""
        name = args.get("name", "")
        db_type = args.get("db_type", "")
        host = args.get("host", "")
        port = args.get("port", 0)
        database = args.get("database", "")
        username = args.get("username", "")

        if not name or not db_type:
            return {"error": "name and db_type are required."}

        mw = self._main_window
        conn_manager = getattr(mw, "connection_manager", None)
        if not conn_manager:
            return {"error": "Connection manager not available."}

        conn_manager.save_connection_config(
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            database=database,
            username=username,
        )

        return {
            "content": [{"type": "text", "text": f"Connection '{name}' ({db_type}) saved."}]
        }

    def _open_connection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Open an existing saved connection."""
        connection_name = args.get("connection_name", "")
        if not connection_name:
            return {"error": "connection_name is required."}

        return self._connect_database({"connection_name": connection_name})

    def _read_schema(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read the loaded database schema."""
        connection_name = args.get("connection_name", "")
        mw = self._main_window

        schema_service = getattr(mw, "_schema_service", None)
        if not schema_service:
            return {"error": "Schema service not available."}

        if not connection_name:
            session = self._get_active_session()
            if session and session.connection_name:
                connection_name = session.connection_name

        if not connection_name:
            return {"error": "No connection specified and no active connection found."}

        cached = schema_service.get_cached_schema(connection_name)
        if cached:
            tables_info = []
            for table in cached.get("tables", []):
                table_name = table.get("name", "")
                columns = cached.get("columns", {}).get(table_name, [])
                col_names = [c.get("name", "") for c in columns]
                tables_info.append(f"  {table_name}: {', '.join(col_names)}")

            schema_text = f"Database: {cached.get('database', 'unknown')}\n"
            schema_text += f"Tables ({len(cached.get('tables', []))}):\n"
            schema_text += "\n".join(tables_info) if tables_info else "  (no tables loaded)"

            return {"content": [{"type": "text", "text": schema_text}]}

        return {"content": [{"type": "text", "text": f"No schema cached for '{connection_name}'. Connect first."}]}

    def _get_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the current editor context."""
        mw = self._main_window
        context = {}

        session = self._get_active_session()
        if session:
            context["session_id"] = session.session_id
            context["session_title"] = session.title
            context["connection_name"] = session.connection_name or ""
            context["is_connected"] = session.is_connected

        session_widget = self._get_active_session_widget()
        if session_widget and hasattr(session_widget, "block_editor"):
            block_editor = session_widget.block_editor
            blocks_info = []
            for i, block in enumerate(block_editor.blocks):
                blocks_info.append({
                    "index": i,
                    "language": block.language,
                    "code": block.get_code(),
                    "is_focused": block == block_editor.focused_block,
                })
            context["blocks"] = blocks_info

        return {"content": [{"type": "text", "text": json.dumps(context, indent=2)}]}

    # === Helper methods ===

    def _get_active_session(self) -> Optional[Any]:
        """Get the active session object."""
        mw = self._main_window
        if hasattr(mw, "session_manager") and mw.session_manager:
            return mw.session_manager.focused_session
        return None

    def _get_active_session_widget(self) -> Optional[Any]:
        """Get the active session widget."""
        mw = self._main_window
        if hasattr(mw, "session_tabs") and mw.session_tabs:
            idx = mw.session_tabs.currentIndex()
            if idx >= 0:
                return mw.session_tabs.widget(idx)
        return None
