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

from PyQt6.QtCore import QObject, QEventLoop, QTimer

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


class MCPToolRegistry(QObject):
    """
    Registry of all MCP tools available for Copilot.

    Tools operate on a reference to the main window to access
    sessions, blocks, connections, and schema.

    This class is thread-safe: execute() can be called from any thread
    and will execute on the main thread.

    Usage:
        registry = MCPToolRegistry()
        registry.set_main_window(main_window)
        result = registry.execute("create_tab", {"title": "My Tab"})
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tools: Dict[str, MCPTool] = {}
        self._main_window = None
        self._pinned_session_id: Optional[str] = None  # Per-tab tool isolation
        self._register_tools()

    def set_main_window(self, main_window) -> None:
        """Set reference to the main window for tool operations."""
        self._main_window = main_window

    def pin_session(self, session_id: str):
        """Pin tools to a specific session (tab). While pinned,
        _get_active_session_widget returns that session's widget
        regardless of which tab is visually active."""
        self._pinned_session_id = session_id

    def unpin_session(self):
        """Remove session pinning. Tools will use currentIndex() again."""
        self._pinned_session_id = None

    def _register_tools(self) -> None:
        """Register all available tools."""
        # === META ===
        self._register(MCPTool(
            name="think",
            description=(
                "Plan and reason about your approach BEFORE acting. "
                "Decide: silent tools for exploration, visible tools for user-facing code."
            ),
            parameters={
                "thought": {
                    "type": "string",
                    "description": "Your reasoning about how to approach the task.",
                },
            },
            handler=self._think,
        ))

        self._register(MCPTool(
            name="create_tab",
            description="Create a new editor tab (session).",
            parameters={
                "title": {
                    "type": "string",
                    "description": "Title for the new tab.",
                },
            },
            handler=self._create_tab,
        ))

        self._register(MCPTool(
            name="notify_user",
            description="Show a toast notification. Use when task is complete or needs attention.",
            parameters={
                "title": {
                    "type": "string",
                    "description": "Short title (e.g., 'Analysis Complete').",
                },
                "message": {
                    "type": "string",
                    "description": "The notification message.",
                },
                "success": {
                    "type": "boolean",
                    "description": "True for success (green), False for error (red). Default: True.",
                    "optional": True,
                },
            },
            handler=self._notify_user,
        ))

        # === OBSERVE (read state) ===
        self._register(MCPTool(
            name="get_context",
            description="Get current state: all blocks (with full code, name, language, index), connection, variables, schema. Use FIRST to orient yourself.",
            parameters={},
            handler=self._get_context,
        ))

        self._register(MCPTool(
            name="get_block_code",
            description="Get the FULL code of a block by name or index. If neither given, returns focused block.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name (e.g., 'vendas'). Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based). Use block_name instead when possible.",
                    "optional": True,
                },
            },
            handler=self._get_block_code,
        ))

        self._register(MCPTool(
            name="get_execution_results",
            description="Get execution output: printed text, DataFrame preview, errors. Use after running a block.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name. Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based). Omit to get last execution results.",
                    "optional": True,
                },
            },
            handler=self._get_execution_results,
        ))

        self._register(MCPTool(
            name="get_variables",
            description="List all Python variables in the session namespace with types and shapes.",
            parameters={},
            handler=self._get_variables,
        ))

        self._register(MCPTool(
            name="inspect_variable",
            description="Get the actual VALUE of a variable (DataFrame: first N rows, others: repr).",
            parameters={
                "name": {
                    "type": "string",
                    "description": "Variable name (e.g., 'vendas', 'df').",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Max rows for DataFrames (default: 20).",
                    "optional": True,
                },
            },
            handler=self._inspect_variable,
        ))

        self._register(MCPTool(
            name="get_dataframe_info",
            description="Get DataFrame structure: columns, dtypes, shape, nulls, sample values.",
            parameters={
                "name": {
                    "type": "string",
                    "description": "DataFrame variable name.",
                },
            },
            handler=self._get_dataframe_info,
        ))

        self._register(MCPTool(
            name="get_selection",
            description="Get the currently selected text in the focused block.",
            parameters={},
            handler=self._get_selection,
        ))

        self._register(MCPTool(
            name="search_in_code",
            description="Search for text across ALL blocks. Returns matching lines with block index and line numbers.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive).",
                },
            },
            handler=self._search_in_code,
        ))

        # === EXECUTE SILENTLY (invisible to user) ===
        self._register(MCPTool(
            name="run_silent_query",
            description=(
                "Execute SQL WITHOUT creating a visible block. Returns results directly. "
                "Use for: row counts, checking values, exploring data, validating queries."
            ),
            parameters={
                "query": {
                    "type": "string",
                    "description": "SQL query to execute.",
                },
            },
            handler=self._run_silent_query,
        ))

        self._register(MCPTool(
            name="run_silent_python",
            description=(
                "Execute Python WITHOUT creating a visible block. Runs in session namespace "
                "(accesses existing DataFrames/variables). Returns stdout + result. "
                "Use for: data exploration, calculations, type checks, testing code."
            ),
            parameters={
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() for output.",
                },
            },
            handler=self._run_silent_python,
        ))

        # === EXECUTE VISIBLY (user sees the block) ===
        self._register(MCPTool(
            name="write_and_run",
            description="Create a new block, write code, execute, and return results - all in one call. Block NAME becomes the DataFrame variable for SQL. MOST COMMON tool.",
            parameters={
                "language": {
                    "type": "string",
                    "description": "'python' or 'sql'.",
                    "enum": ["python", "sql", "cross"],
                },
                "code": {
                    "type": "string",
                    "description": "Complete executable code.",
                },
                "name": {
                    "type": "string",
                    "description": "Semantic block name (e.g., 'vendas', 'grafico'). For SQL: becomes DataFrame variable.",
                    "optional": True,
                },
            },
            handler=self._write_and_run,
        ))

        self._register(MCPTool(
            name="create_block",
            description="Create a new block and write code WITHOUT executing. Use for multi-block setup before running all.",
            parameters={
                "language": {
                    "type": "string",
                    "description": "'python' or 'sql'.",
                    "enum": ["python", "sql", "cross"],
                },
                "code": {
                    "type": "string",
                    "description": "Code to write in the block.",
                },
                "name": {
                    "type": "string",
                    "description": "Semantic block name. For SQL: becomes DataFrame variable.",
                    "optional": True,
                },
            },
            handler=self._create_block,
        ))

        self._register(MCPTool(
            name="execute_block",
            description="Run an existing block by name or index and return results. If neither given, runs focused block.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name (e.g., 'vendas'). Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based). Use block_name instead when possible.",
                    "optional": True,
                },
            },
            handler=self._execute_block,
        ))

        self._register(MCPTool(
            name="run_all_blocks",
            description="Execute ALL blocks in sequence and return combined results.",
            parameters={},
            handler=self._run_all_blocks,
        ))

        # === EDIT (modify existing blocks) ===
        self._register(MCPTool(
            name="edit_block",
            description="Replace ALL code in an existing block. Identify by name or index. If neither given, edits focused block. PREFER this over create_block when the block already exists.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "New code (replaces entire block content).",
                },
                "block_name": {
                    "type": "string",
                    "description": "Block name (e.g., 'vendas'). Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based). Use block_name instead when possible.",
                    "optional": True,
                },
            },
            handler=self._edit_block,
        ))

        # === EDIT continued ===
        self._register(MCPTool(
            name="edit_block_lines",
            description="Edit specific lines in a block. Modes: 'replace' (default), 'insert', 'delete'. Line numbers are 1-based.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name. Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based).",
                    "optional": True,
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line number (1-based).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line (1-based, inclusive). For 'replace' and 'delete'.",
                    "optional": True,
                },
                "new_code": {
                    "type": "string",
                    "description": "Replacement or insertion text.",
                    "optional": True,
                },
                "mode": {
                    "type": "string",
                    "description": "Edit mode.",
                    "enum": ["replace", "insert", "delete"],
                    "optional": True,
                },
            },
            handler=self._edit_block_lines,
        ))

        self._register(MCPTool(
            name="replace_selection",
            description="Replace selected text with new code. If nothing selected, inserts at cursor.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The code to insert/replace.",
                },
            },
            handler=self._replace_selection,
        ))

        self._register(MCPTool(
            name="rename_block",
            description="Rename a block. For SQL blocks, the name becomes the DataFrame variable.",
            parameters={
                "name": {
                    "type": "string",
                    "description": "New name (snake_case).",
                },
                "block_name": {
                    "type": "string",
                    "description": "Current block name to rename. Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based). Omit to rename focused block.",
                    "optional": True,
                },
            },
            handler=self._rename_block,
        ))

        self._register(MCPTool(
            name="set_block_language",
            description="Change the language of a block.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name (e.g., 'vendas'). Preferred over block_index.",
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based).",
                },
                "language": {
                    "type": "string",
                    "description": "New language.",
                    "enum": ["python", "sql", "cross"],
                },
            },
            handler=self._set_block_language,
        ))

        self._register(MCPTool(
            name="delete_block",
            description="Delete a block by name or index. NEVER delete unless user explicitly asks.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name to delete. Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based).",
                    "optional": True,
                },
            },
            handler=self._delete_block,
        ))

        self._register(MCPTool(
            name="move_focus",
            description="Move focus to a specific block by name or index.",
            parameters={
                "block_name": {
                    "type": "string",
                    "description": "Block name. Preferred over block_index.",
                    "optional": True,
                },
                "block_index": {
                    "type": "integer",
                    "description": "Block index (0-based).",
                    "optional": True,
                },
            },
            handler=self._move_focus,
        ))

        # === DATABASE ===
        self._register(MCPTool(
            name="connect_database",
            description="Connect the current session to a saved database connection.",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Name of the saved connection.",
                },
            },
            handler=self._connect_database,
        ))

        self._register(MCPTool(
            name="create_connection",
            description="Create and save a new database connection.",
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
                    "description": "Database host.",
                },
                "port": {
                    "type": "integer",
                    "description": "Database port.",
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
            description="Open a saved connection in a NEW tab.",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Connection name to open.",
                },
            },
            handler=self._open_connection,
        ))

        self._register(MCPTool(
            name="list_connections",
            description="List all saved database connections.",
            parameters={},
            handler=self._list_connections,
        ))

        self._register(MCPTool(
            name="read_schema",
            description="Read the database schema (tables, columns, types).",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Connection name. Uses current if omitted.",
                    "optional": True,
                },
            },
            handler=self._read_schema,
        ))

        self._register(MCPTool(
            name="list_tables",
            description="List all tables in the connected database.",
            parameters={},
            handler=self._list_tables,
        ))

        self._register(MCPTool(
            name="describe_table",
            description="Describe a table: columns, types, and nullability.",
            parameters={
                "table_name": {
                    "type": "string",
                    "description": "Table name.",
                },
            },
            handler=self._describe_table,
        ))

        self._register(MCPTool(
            name="sample_data",
            description="Get sample rows from a table.",
            parameters={
                "table_name": {
                    "type": "string",
                    "description": "Table name.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of rows (default: 5).",
                    "optional": True,
                },
            },
            handler=self._sample_data,
        ))

        # === DATABASE Intelligence (legacy alias kept) ===
        self._register(MCPTool(
            name="get_database_schema",
            description="Get complete database schema (all tables and columns). Same as read_schema.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive substring match).",
                },
            },
            handler=self._search_in_code,
        ))

        # === Database Intelligence Tools ===
        self._register(MCPTool(
            name="get_database_schema",
            description="GET the complete database schema (all tables and columns) from the currently connected database. Use this to understand available tables before writing queries. Returns tables with their columns and types.",
            parameters={},
            handler=self._get_database_schema,
        ))

        self._register(MCPTool(
            name="list_tables",
            description="LIST all tables in the connected database. Quick way to see what tables exist.",
            parameters={},
            handler=self._list_tables,
        ))

        self._register(MCPTool(
            name="describe_table",
            description="DESCRIBE a specific table: columns, types, and sample data. Use to understand table structure before writing queries.",
            parameters={
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to describe.",
                },
            },
            handler=self._describe_table,
        ))

        self._register(MCPTool(
            name="run_silent_query",
            description=(
                "QUICK EXECUTE a SQL query WITHOUT creating a visible block. Returns results directly. "
                "USE THIS for: data exploration, row counts, checking values, validating queries before "
                "showing code to user. For code the user should see, use write_and_run with language='sql' instead."
            ),
            parameters={
                "query": {
                    "type": "string",
                    "description": "SQL query to execute.",
                },
            },
            handler=self._run_silent_query,
        ))

        self._register(MCPTool(
            name="sample_data",
            description="GET sample rows from a table. Quick preview of what data looks like.",
            parameters={
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to sample.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of rows to return (default: 5).",
                    "optional": True,
                },
            },
            handler=self._sample_data,
        ))

    def _register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def _get_known_table_names(self) -> set:
        """Get set of known table names from cached schema (case-insensitive)."""
        mw = self._main_window
        session = self._get_active_session()
        if not session or not session.connection_name:
            return set()

        schema_service = getattr(mw, "_schema_service", None)
        if not schema_service:
            return set()

        cached = schema_service.get_cached_schema(session.connection_name)
        if not cached:
            return set()

        tables = cached.get("tables", [])
        # Include both simple names and schema-qualified names
        names = set()
        for t in tables:
            name = t.get("name", "")
            schema_name = t.get("schema", "")
            if name:
                names.add(name.lower())
                if schema_name:
                    names.add(f"{schema_name}.{name}".lower())
        return names

    def _quote_identifier(self, identifier: str, db_type: str = "mssql") -> str:
        """Quote SQL identifier to prevent injection.
        
        Args:
            identifier: Table or column name (may include schema: schema.table)
            db_type: Database type (mssql, postgres, mysql, etc.)
        
        Returns:
            Properly quoted identifier
        """
        db_type = db_type.lower()
        
        # Split schema.table if present
        parts = identifier.split(".", 1)
        
        if db_type in ("sqlserver", "mssql"):
            # SQL Server uses [brackets]
            quoted_parts = [f"[{p}]" for p in parts]
        elif db_type in ("postgres", "postgresql"):
            # PostgreSQL uses "double quotes"
            quoted_parts = [f'"{p}"' for p in parts]
        elif db_type in ("mysql", "mariadb"):
            # MySQL uses `backticks`
            quoted_parts = [f"`{p}`" for p in parts]
        else:
            # Default to double quotes (ANSI SQL)
            quoted_parts = [f'"{p}"' for p in parts]
        
        return ".".join(quoted_parts)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return list of all tool schemas for MCP protocol."""
        return [tool.to_schema() for tool in self._tools.values()]

    def list_tools_openai(self) -> List[Dict[str, Any]]:
        """
        Return list of tools in OpenAI function calling format.
        This is the format expected by the Copilot SDK.
        """
        tools = []
        for tool in self._tools.values():
            # Build required list from parameters
            required = [
                name for name, props in tool.parameters.items()
                if not props.get("optional", False)
            ]
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.parameters,
                        "required": required,
                    },
                },
            })
        return tools

    def execute(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a tool by name with the given arguments.
        Thread-safe: can be called from any thread.

        Returns:
            Dict with "content" (list of text results) or "error" key.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        if not self._main_window:
            return {"error": "Main window not available. Cannot execute tools."}

        # Execute directly - the SDK may call from async context
        # For GUI-safe execution, tools should use QMetaObject.invokeMethod internally
        return self._execute_directly(tool_name, arguments or {})

    def _execute_directly(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool directly."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            logger.info(f"Executing tool '{tool_name}' with args: {arguments}")
            result = tool.handler(arguments)
            logger.info(f"Tool '{tool_name}' result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return {"error": str(e)}

    # === Tool Implementations ===

    def _think(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Process a thinking/reasoning step - helps Copilot plan before acting.
        
        This tool doesn't perform any action, it just returns the thought
        back to Copilot so it can reason through its approach.
        """
        thought = args.get("thought", "")
        if not thought:
            return {"error": "No thought provided. Use this tool to reason about your approach."}
        
        logger.info(f"think: {thought}")
        
        # Return the thought back - this helps Copilot "think out loud"
        # The thought is shown in the UI via the ToolCallWidget
        return {
            "content": [{
                "type": "text", 
                "text": f"Thought recorded. Now proceed with your plan:\n{thought}"
            }]
        }

    def _create_tab(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new tab/session."""
        title = args.get("title")
        mw = self._main_window
        
        logger.info(f"create_tab called: title={title}, mw={mw}")

        if hasattr(mw, "session_manager") and mw.session_manager:
            session = mw.session_manager.create_session(title=title)
            logger.info(f"create_tab: Created session id={session.session_id}, title={session.title}")
            return {
                "content": [{"type": "text", "text": f"Tab created: '{session.title}' (id: {session.session_id})"}]
            }

        logger.error("create_tab: Session manager not available")
        return {"error": "Session manager not available."}

    def _create_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new code block in the current session."""
        language = args.get("language", "python")
        code = args.get("code", "")
        name = args.get("name", "")
        mw = self._main_window
        
        logger.info(f"create_block called: language={language}, code_len={len(code)}, name={name}")

        session_widget = self._get_active_session_widget()
        if not session_widget:
            logger.error("create_block: No active session widget")
            return {"error": "No active session. Create a tab first."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            logger.error(f"create_block: No editor on session_widget {type(session_widget)}")
            return {"error": "Block editor not available."}

        logger.info(f"create_block: Adding block with language={language}")
        block = block_editor.add_block(language=language)
        if code and block:
            # Show copilot editing indicator
            self._signal_copilot_editing(block, block_editor)
            block.set_code(code)
            logger.info(f"create_block: Set code on block")
        
        # Set block name if provided
        if name and block:
            block.set_block_name(name)
            logger.info(f"create_block: Set block name to '{name}'")

        block_count = len(block_editor.blocks)
        block_index = block_count - 1
        actual_name = block.get_block_name() if block else f"block{block_index + 1}"
        logger.info(f"create_block: Success, total blocks={block_count}, name={actual_name}")
        
        msg_parts = [f"Block created (language: {language}, index: {block_index}, name: '{actual_name}')"]
        if language == "sql":
            msg_parts.append(f"When executed, the result will be stored as DataFrame `{actual_name}`.")
        return {
            "content": [{"type": "text", "text": " ".join(msg_parts)}]
        }

    def _edit_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Edit code in a block. Resolved by name, index, or focused block."""
        code = args.get("code", "")

        target_block, block_editor, idx, error = self._resolve_block(args)
        if error:
            return {"error": error}

        self._signal_copilot_editing(target_block, block_editor)
        target_block.set_code(code)
        # Move cursor to top of block
        editor = getattr(target_block, "editor", None)
        if editor and hasattr(editor, "go_to_line"):
            editor.go_to_line(0)
        name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{idx}"
        return {"content": [{"type": "text", "text": f"Block {idx} ('{name}') updated with {len(code)} characters."}]}

    def _rename_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Rename a block. The name determines the DataFrame variable name for SQL blocks."""
        name = args.get("name", "")
        if not name:
            return {"error": "name is required."}

        target_block, block_editor, idx, error = self._resolve_block(args)
        if error:
            return {"error": error}

        if target_block:
            old_name = target_block.get_block_name()
            target_block.set_block_name(name)
            language = target_block.language
            msg = f"Block renamed from '{old_name}' to '{name}'."
            if language == "sql":
                msg += f" When executed, result will be stored as DataFrame `{name}`."
            return {"content": [{"type": "text", "text": msg}]}

        return {"error": "No block found to rename."}

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
        """Open a saved connection in a NEW TAB."""
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

        # Use _connect_new_tab which always creates a new tab
        if hasattr(mw, "_connect_new_tab"):
            mw._connect_new_tab(connection_name)
            return {
                "content": [{"type": "text", "text": f"New tab created and connecting to '{connection_name}'."}]
            }

        return {"error": "MainWindow does not support _connect_new_tab."}

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
        
        logger.info(f"_get_context: main_window={mw}")

        session = self._get_active_session()
        if session:
            context["session_id"] = session.session_id
            context["session_title"] = session.title
            context["connection_name"] = session.connection_name or ""
            # is_connected is a property, call it to get bool value
            try:
                context["is_connected"] = bool(session.is_connected)
            except Exception:
                context["is_connected"] = False

        session_widget = self._get_active_session_widget()
        logger.info(f"_get_context: session_widget={session_widget}, type={type(session_widget)}")
        
        if session_widget:
            block_editor = self._get_block_editor(session_widget)
            logger.info(f"_get_context: block_editor={block_editor}")
            
            if block_editor:
                blocks_info = []
                blocks = getattr(block_editor, "blocks", [])
                logger.info(f"_get_context: {len(blocks)} blocks found")
                
                for i, block in enumerate(blocks):
                    try:
                        lang = block.get_language() if hasattr(block, "get_language") else "unknown"
                        code = block.get_code() if hasattr(block, "get_code") else ""
                        is_focused = block == block_editor.focused_block
                        name = block.get_block_name() if hasattr(block, "get_block_name") else f"block{i + 1}"
                        # Return full code (up to 800 chars) for orientation
                        code_preview = code[:800] + "..." if len(code) > 800 else code
                        blocks_info.append({
                            "index": i,
                            "name": name,
                            "language": lang,
                            "lines": len(code.split("\n")),
                            "focused": is_focused,
                            "code": code_preview,
                        })
                    except Exception as e:
                        logger.warning(f"Error getting block {i} info: {e}")
                        blocks_info.append({
                            "index": i,
                            "language": "unknown",
                            "code": "",
                            "is_focused": False,
                        })
                context["blocks"] = blocks_info
                context["total_blocks"] = len(blocks_info)
                # Quick reference: name -> index mapping
                if blocks_info:
                    context["block_map"] = {
                        b["name"]: b["index"] for b in blocks_info
                    }
            else:
                logger.warning("_get_context: No block_editor on session_widget!")
                context["blocks"] = []
                context["debug"] = f"No block_editor. widget attrs: {dir(session_widget)[:10]}"
        else:
            logger.warning("_get_context: No session_widget!")

        # Add schema from ObjectExplorer if available
        if session:
            try:
                session_explorers = getattr(mw, "_session_explorers", None)
                if isinstance(session_explorers, dict):
                    explorer = session_explorers.get(session.session_id)
                    if explorer and hasattr(explorer, "_current_schema"):
                        schema = explorer._current_schema
                        if isinstance(schema, dict):
                            context["database"] = schema.get("database", "")
                            tables = schema.get("tables", [])
                            if isinstance(tables, list):
                                context["tables"] = [t.get("name", "") for t in tables if isinstance(t, dict)]
                                # Include column info for each table (helpful for queries)
                                tables_with_cols = {}
                                columns = schema.get("columns", {})
                                if isinstance(columns, dict):
                                    for table in tables:
                                        if isinstance(table, dict):
                                            tname = table.get("name", "")
                                            tcols = columns.get(tname, [])
                                            if isinstance(tcols, list):
                                                tables_with_cols[tname] = [c.get("name", "") for c in tcols if isinstance(c, dict)]
                                context["table_columns"] = tables_with_cols
            except Exception as e:
                logger.debug(f"Error getting schema from ObjectExplorer: {e}")

        # Add tool usage guide for smart tool selection
        context["tool_guide"] = (
            "IMPORTANT: Check block_map above before creating blocks. "
            "If a block with that name/purpose exists, use edit_block(block_name=...) to UPDATE it. "
            "Only use write_and_run to CREATE new blocks. "
            "Use block_name (not block_index) to target blocks. "
            "Use run_silent_query/run_silent_python for exploration (invisible to user)."
        )

        # Add namespace variables summary
        if session_widget:
            namespace = getattr(session_widget, "namespace", None)
            if namespace is None:
                session_obj = self._get_active_session()
                if session_obj:
                    namespace = getattr(session_obj, "namespace", None)
            if namespace:
                variables = {}
                for name, value in namespace.items():
                    if name.startswith("_") or isinstance(value, type) or callable(value):
                        continue
                    if name in ("pd", "np", "plt"):
                        continue
                    try:
                        type_name = type(value).__name__
                        if hasattr(value, "shape"):
                            variables[name] = f"{type_name}{value.shape}"
                        elif hasattr(value, "__len__"):
                            variables[name] = f"{type_name}(len={len(value)})"
                        else:
                            variables[name] = type_name
                    except Exception:
                        variables[name] = "?"
                if variables:
                    context["variables"] = variables

        return {"content": [{"type": "text", "text": json.dumps(context, indent=2)}]}

    # === Helper methods ===

    def _get_active_session(self) -> Optional[Any]:
        """Get the active session object."""
        mw = self._main_window
        if hasattr(mw, "session_manager") and mw.session_manager:
            return mw.session_manager.focused_session
        return None

    def _get_active_session_widget(self) -> Optional[Any]:
        """Get the active session widget.
        If a session is pinned (during chat), returns that session's widget
        regardless of which tab is visually focused."""
        mw = self._main_window
        if not mw:
            logger.warning("_get_active_session_widget: No main_window")
            return None

        # If pinned, find widget by session_id (tab-safe)
        if self._pinned_session_id and hasattr(mw, "_session_widgets"):
            widget = mw._session_widgets.get(self._pinned_session_id)
            if widget:
                logger.info(f"_get_active_session_widget: pinned to {self._pinned_session_id}")
                return widget

        # Fallback: use current tab
        if hasattr(mw, "session_tabs") and mw.session_tabs:
            idx = mw.session_tabs.currentIndex()
            widget = mw.session_tabs.widget(idx) if idx >= 0 else None
            logger.info(f"_get_active_session_widget: idx={idx}, widget={widget}, type={type(widget)}")
            return widget
        logger.warning(f"_get_active_session_widget: No session_tabs on mw={mw}")
        return None
    
    def _get_block_editor(self, session_widget) -> Optional[Any]:
        """Get the BlockEditor from a session widget.
        
        SessionWidget uses 'editor' attribute (which is a BlockEditor).
        Some test mocks might use 'block_editor'.
        """
        if not session_widget:
            return None
        
        # Check if widget has 'editor' attribute and it looks like a BlockEditor
        # (must have add_block method or blocks attribute)
        editor = getattr(session_widget, "editor", None)
        if editor and hasattr(editor, "add_block"):
            logger.info(f"_get_block_editor: Found 'editor' attr with add_block")
            return editor
        
        # Fallback for test mocks that use 'block_editor'
        editor = getattr(session_widget, "block_editor", None)
        if editor and hasattr(editor, "add_block"):
            logger.info(f"_get_block_editor: Found 'block_editor' attr (fallback)")
            return editor
        
        logger.warning(f"_get_block_editor: No valid editor found on {type(session_widget)}")
        return None

    def _resolve_block(self, args: Dict[str, Any], require=False):
        """Resolve a block by name, index, or focused block.

        Lookup order:
        1. block_name  -- find block whose name matches (case-insensitive)
        2. block_index -- 0-based integer index
        3. focused / last block (if neither is given and require=False)

        Returns:
            (block, block_editor, block_index, error_string)
        """
        block_name = args.get("block_name")
        block_index = args.get("block_index")

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return None, None, -1, "No active session."

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return None, None, -1, "Block editor not available."

        blocks = block_editor.blocks
        if not blocks:
            return None, block_editor, -1, "No blocks in the current session."

        # 1. Resolve by name
        if block_name is not None:
            name_lower = str(block_name).strip().lower()
            for i, blk in enumerate(blocks):
                blk_name = ""
                if hasattr(blk, "get_block_name"):
                    blk_name = blk.get_block_name()
                if blk_name.lower() == name_lower:
                    return blk, block_editor, i, None
            # Not found -- build helpful error
            available = [
                f"  [{i}] '{blk.get_block_name() if hasattr(blk, 'get_block_name') else '?'}'"
                for i, blk in enumerate(blocks)
            ]
            return None, block_editor, -1, (
                f"No block named '{block_name}'. "
                f"Available blocks:\n" + "\n".join(available)
            )

        # 2. Resolve by index
        if block_index is not None:
            if 0 <= block_index < len(blocks):
                return blocks[block_index], block_editor, block_index, None
            return None, block_editor, -1, (
                f"Block index {block_index} out of range (0-{len(blocks) - 1})."
            )

        # 3. No identifier -- use focused or last block
        if require:
            return None, block_editor, -1, (
                "block_name or block_index is required."
            )
        target, be2, error = self._get_focused_block()
        if error:
            return None, block_editor, -1, error
        idx = blocks.index(target) if target in blocks else -1
        return target, block_editor, idx, None

    def _signal_copilot_editing(self, block, block_editor=None):
        """Show Copilot editing indicator on a block and scroll it into view.
        
        Sets the purple sparkle indicator on the block, and ensures
        the block is visible to the user by scrolling to it.
        """
        try:
            if hasattr(block, "set_copilot_editing"):
                block.set_copilot_editing(True)
            # Scroll block into view
            if block_editor and hasattr(block_editor, "ensureWidgetVisible"):
                block_editor.ensureWidgetVisible(block)
        except Exception as e:
            logger.debug(f"_signal_copilot_editing failed: {e}")

    def _highlight_edited_lines(self, block, start_line, end_line):
        """Highlight edited lines and move cursor to the edit location.
        
        Moves the Monaco editor cursor to the start of the edited region
        and adds a temporary visual highlight on the affected lines.
        """
        try:
            editor = getattr(block, "editor", None)
            if not editor:
                return
            # Move cursor (go_to_line is 0-based)
            if hasattr(editor, "go_to_line"):
                editor.go_to_line(start_line - 1)
            # Highlight the edited lines (1-based)
            if hasattr(editor, "highlight_lines"):
                editor.highlight_lines(start_line, end_line, 2000)
        except Exception as e:
            logger.debug(f"_highlight_edited_lines failed: {e}")

    def _get_output_snapshot(self) -> str:
        """Capture current output panel text (used before execution to diff later)."""
        mw = self._main_window
        if not mw:
            return ""
        output_panel = getattr(mw, "global_output_panel", None)
        if output_panel and hasattr(output_panel, "get_text"):
            return output_panel.get_text() or ""
        return ""

    def _wait_for_block_execution(self, block, timeout_ms: int = 30000) -> bool:
        """Wait for a block to finish executing using QEventLoop.

        Polls block._is_running every 100ms. Returns True if execution
        completed within the timeout, False if timed out.
        This does NOT block the event loop - QEventLoop.exec() still
        processes Qt events so the background thread signals are delivered.
        """
        if not hasattr(block, "_is_running"):
            return True

        if not block._is_running:
            return True

        loop = QEventLoop()
        elapsed = 0
        interval = 100

        timer = QTimer()
        timer.setInterval(interval)

        def _check():
            nonlocal elapsed
            elapsed += interval
            if not block._is_running or elapsed >= timeout_ms:
                timer.stop()
                loop.quit()

        timer.timeout.connect(_check)
        timer.start()
        loop.exec()
        timer.stop()

        return not block._is_running

    def _collect_execution_result(self, block, block_index: int, output_before: str) -> Dict[str, Any]:
        """Collect execution result after a block finished running.

        Reads new output (diff from output_before), the results viewer DataFrame,
        and block status to build a comprehensive result dict.
        """
        parts = []

        # 1. New output text (diff from before execution)
        output_after = self._get_output_snapshot()
        new_output = output_after[len(output_before):].strip() if output_after else ""
        if new_output:
            # Limit to avoid token overflow
            if len(new_output) > 5000:
                new_output = "... (truncated)\n" + new_output[-5000:]
            parts.append(f"Output:\n```\n{new_output}\n```")

        # 2. DataFrame in results viewer
        mw = self._main_window
        results_viewer = getattr(mw, "global_results_viewer", None) if mw else None
        if results_viewer:
            current_df = getattr(results_viewer, "current_df", None)
            if current_df is not None and hasattr(current_df, "empty") and not current_df.empty:
                rows_total = len(current_df)
                cols_total = len(current_df.columns)
                preview_df = current_df.head(30)
                parts.append(f"Results ({rows_total} rows x {cols_total} columns):\n```\n{preview_df.to_string()}\n```")
                if rows_total > 30:
                    parts.append(f"(showing first 30 of {rows_total} rows)")

        # 3. Check for errors via block status
        has_error = False
        if hasattr(block, "status_label"):
            status_text = block.status_label.text()
            if "error" in status_text.lower() or "erro" in status_text.lower():
                has_error = True

        if not parts:
            if has_error:
                parts.append("Execution finished with errors (check output panel for details).")
            else:
                parts.append("Execution completed (no visible output).")

        text = f"Block {block_index} execution finished.\n\n" + "\n\n".join(parts)
        return {"content": [{"type": "text", "text": text}]}

    def _execute_block_with_result(self, block, block_editor, block_index: int) -> Dict[str, Any]:
        """Execute a block, wait for completion, and return results.

        This is the unified execution helper used by all execute tools.
        1. Snapshots output panel text
        2. Calls block_editor.execute_block(block)
        3. Waits for block to stop running (up to 30s)
        4. Collects and returns execution output + DataFrame preview
        """
        # Snapshot before
        output_before = self._get_output_snapshot()

        # Execute
        try:
            block_editor.execute_block(block)
        except Exception as e:
            return {"error": f"Execution failed: {e}"}

        # Wait for block to finish (processes Qt events meanwhile)
        completed = self._wait_for_block_execution(block, timeout_ms=30000)

        if not completed:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Block {block_index} execution started but did not finish within 30 seconds. Use get_execution_results to check the output later."
                }]
            }

        # Collect results
        return self._collect_execution_result(block, block_index, output_before)

    def _execute_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a block by name, index, or focused block, wait for completion, and return results."""
        target_block, block_editor, block_index, error = self._resolve_block(args)
        if error:
            return {"error": error}

        return self._execute_block_with_result(target_block, block_editor, block_index)

    def _run_current_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the currently focused block, wait for completion, and return results."""
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        focused_block = block_editor.focused_block
        if not focused_block:
            blocks = block_editor.blocks
            if blocks:
                focused_block = blocks[-1]
            else:
                return {"error": "No blocks to execute."}

        block_index = block_editor.blocks.index(focused_block) if focused_block in block_editor.blocks else -1
        return self._execute_block_with_result(focused_block, block_editor, block_index)

    def _list_connections(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all saved database connections."""
        mw = self._main_window
        conn_manager = getattr(mw, "connection_manager", None)
        if not conn_manager:
            return {"error": "Connection manager not available."}

        saved_configs = conn_manager.saved_configs.get("connections", {})
        if not saved_configs:
            return {"content": [{"type": "text", "text": "No saved connections."}]}

        connections = []
        for name, config in saved_configs.items():
            db_type = config.get("db_type", "unknown")
            host = config.get("host", "")
            database = config.get("database", "")
            connections.append(f"- {name} ({db_type}): {host}/{database}")

        text = "Saved connections:\n" + "\n".join(connections)
        return {"content": [{"type": "text", "text": text}]}

    def _get_variables(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get Python variables from the session namespace."""
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        namespace = getattr(session_widget, "namespace", None)
        if namespace is None and hasattr(session_widget, "_namespace"):
            namespace = session_widget._namespace

        if not namespace:
            return {"content": [{"type": "text", "text": "No namespace available."}]}

        # Filter out private/internal variables and modules
        variables = {}
        for name, value in namespace.items():
            if name.startswith("_"):
                continue
            if isinstance(value, type) or callable(value):
                continue
            try:
                type_name = type(value).__name__
                # For DataFrames, include shape
                if hasattr(value, "shape"):
                    variables[name] = f"{type_name} {value.shape}"
                elif hasattr(value, "__len__"):
                    variables[name] = f"{type_name} (len={len(value)})"
                else:
                    variables[name] = type_name
            except Exception:
                variables[name] = "?"

        if not variables:
            return {"content": [{"type": "text", "text": "No user variables defined."}]}

        lines = [f"- {name}: {vtype}" for name, vtype in variables.items()]
        text = "Session variables:\n" + "\n".join(lines)
        return {"content": [{"type": "text", "text": text}]}

    def _inspect_variable(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the actual value of a variable."""
        var_name = args.get("name")
        if not var_name:
            return {"error": "name is required."}

        max_rows = args.get("max_rows", 20)

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        namespace = getattr(session_widget, "namespace", None)
        if namespace is None and hasattr(session_widget, "_namespace"):
            namespace = session_widget._namespace

        if not namespace:
            return {"error": "No namespace available."}

        if var_name not in namespace:
            available = [k for k in namespace.keys() if not k.startswith("_")]
            return {"error": f"Variable '{var_name}' not found. Available: {', '.join(available[:10])}"}

        value = namespace[var_name]
        type_name = type(value).__name__

        try:
            # Handle DataFrames specially
            if hasattr(value, "to_string") and hasattr(value, "shape"):
                # It's a DataFrame or Series
                import io
                buf = io.StringIO()
                # Print head with max_rows
                if hasattr(value, "head"):
                    preview = value.head(max_rows)
                else:
                    preview = value
                preview.to_string(buf, max_rows=max_rows)
                text = f"{type_name} {value.shape}:\n\n{buf.getvalue()}"
            elif isinstance(value, (list, dict)):
                import json
                try:
                    json_str = json.dumps(value, indent=2, default=str, ensure_ascii=False)
                    if len(json_str) > 3000:
                        json_str = json_str[:3000] + "\n... (truncated)"
                    text = f"{type_name}:\n{json_str}"
                except Exception:
                    text = f"{type_name}: {repr(value)[:3000]}"
            else:
                # Simple repr for other types
                text = f"{type_name}: {repr(value)[:3000]}"
        except Exception as e:
            text = f"{type_name}: (could not display: {e})"

        return {"content": [{"type": "text", "text": text}]}

    def _get_dataframe_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed info about a DataFrame."""
        var_name = args.get("name")
        if not var_name:
            return {"error": "name is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        namespace = getattr(session_widget, "namespace", None)
        if namespace is None and hasattr(session_widget, "_namespace"):
            namespace = session_widget._namespace

        if not namespace:
            return {"error": "No namespace available."}

        if var_name not in namespace:
            return {"error": f"Variable '{var_name}' not found."}

        df = namespace[var_name]
        if not hasattr(df, "dtypes") or not hasattr(df, "shape"):
            return {"error": f"'{var_name}' is not a DataFrame."}

        try:
            lines = [
                f"DataFrame: {var_name}",
                f"Shape: {df.shape[0]} rows x {df.shape[1]} columns",
                "",
                "Columns:",
            ]

            for col in df.columns:
                dtype = df[col].dtype
                null_count = df[col].isnull().sum()
                sample = df[col].dropna().head(3).tolist()
                sample_str = ", ".join(str(s)[:30] for s in sample)
                lines.append(f"  - {col} ({dtype}): nulls={null_count}, sample=[{sample_str}]")

            text = "\n".join(lines)
        except Exception as e:
            text = f"Error inspecting DataFrame: {e}"

        return {"content": [{"type": "text", "text": text}]}

    def _set_block_language(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Change the language of a block."""
        language = args.get("language", "python")

        target_block, block_editor, block_index, error = self._resolve_block(args, require=True)
        if error:
            return {"error": error}

        if hasattr(target_block, "set_language"):
            name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{block_index}"
            target_block.set_language(language)
            return {
                "content": [{"type": "text", "text": f"Block {block_index} ('{name}') language changed to {language}."}]
            }

        return {"error": "Block does not support set_language."}

    def _delete_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a block by name or index."""
        target_block, block_editor, block_index, error = self._resolve_block(args, require=True)
        if error:
            return {"error": error}

        if hasattr(block_editor, "remove_block"):
            name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{block_index}"
            block_editor.remove_block(target_block)
            return {
                "content": [{"type": "text", "text": f"Block {block_index} ('{name}') deleted."}]
            }

        return {"error": "Block editor does not support remove_block."}

    def _get_block_result(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the last execution result from the output panel."""
        # Results go to the global output/results panel, not per-block
        return self._get_execution_results(args)

    def _write_and_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a block, write code, and execute it - all in one step."""
        language = args.get("language", "python")
        code = args.get("code", "")
        name = args.get("name", "")
        
        logger.info(f"write_and_run called: language={language}, code_len={len(code)}, name={name}")

        if not code:
            return {"error": "code is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            logger.error("write_and_run: No active session widget")
            return {"error": "No active session. Create a tab first."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            logger.error(f"write_and_run: No block_editor on {type(session_widget)}")
            return {"error": "Block editor not available."}

        # 1. Create the block
        logger.info("write_and_run: Creating block...")
        block = block_editor.add_block(language=language)
        if not block:
            logger.error("write_and_run: add_block returned None")
            return {"error": "Failed to create block."}

        # 2. Set block name if provided
        if name:
            block.set_block_name(name)
            logger.info(f"write_and_run: Set block name to '{name}'")

        # 3. Write the code
        logger.info("write_and_run: Setting code...")
        # Show copilot editing indicator and scroll into view
        self._signal_copilot_editing(block, block_editor)
        block.set_code(code)
        block_index = len(block_editor.blocks) - 1
        actual_name = block.get_block_name()
        logger.info(f"write_and_run: Block {block_index} ('{actual_name}') created with {len(code)} chars")

        # 4. Execute the block and wait for results
        return self._execute_block_with_result(block, block_editor, block_index)

    # === Focused Block Tool Implementations ===

    def _get_focused_block(self):
        """Helper to get the currently focused block.
        
        Uses get_last_focused_block() to handle the case where user
        clicked on Copilot chat panel (focus moved away from editor).
        
        Returns:
            Tuple of (block, block_editor, error_string)
            If error_string is set, block and block_editor may be None.
        """
        session_widget = self._get_active_session_widget()
        if not session_widget:
            logger.warning("_get_focused_block: No active session widget")
            return None, None, "No active session."

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            logger.warning("_get_focused_block: No block editor available")
            return None, None, "Block editor not available."

        # Use get_last_focused_block() - preserves focus even when user clicks on chat
        if hasattr(block_editor, "get_last_focused_block"):
            focused_block = block_editor.get_last_focused_block()
            logger.info(f"_get_focused_block: get_last_focused_block() returned {focused_block}")
        else:
            # Fallback to property
            focused_block = block_editor.focused_block
            logger.info(f"_get_focused_block: focused_block property = {focused_block}")
        
        if not focused_block:
            # Fallback: use last block in session
            blocks = block_editor.blocks
            logger.info(f"_get_focused_block: No focused block, {len(blocks)} blocks available")
            if blocks:
                focused_block = blocks[-1]
                logger.info(f"_get_focused_block: Using last block as fallback")
            else:
                return None, block_editor, "No blocks in session."

        return focused_block, block_editor, None

    def _get_focused_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get code from the currently focused block."""
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        code = ""
        if hasattr(block, "get_code"):
            code = block.get_code()
        elif hasattr(block, "code"):
            code = block.code

        language = getattr(block, "language", "python")
        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} ({language}):\n```{language}\n{code}\n```"
            }]
        }

    def _edit_focused_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Edit/replace code in the currently focused block."""
        code = args.get("code", "")
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        self._signal_copilot_editing(block, block_editor)
        block.set_code(code)
        # Move cursor to top
        editor = getattr(block, "editor", None)
        if editor and hasattr(editor, "go_to_line"):
            editor.go_to_line(0)
        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} updated with {len(code)} characters."
            }]
        }

    def _execute_focused(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the currently focused block, wait for completion, and return results."""
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1
        return self._execute_block_with_result(block, block_editor, block_index)

    def _get_focused_result(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the last execution result from the output panel."""
        # Results go to the global output panel, not per-block
        return self._get_execution_results(args)

    # === Selection Tool Implementations ===

    def _get_selection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the currently selected text."""
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        selected_text = ""
        if hasattr(block, "editor"):
            editor = block.editor
            if hasattr(editor, "selectedText"):
                selected_text = editor.selectedText()
            elif hasattr(editor, "textCursor"):
                cursor = editor.textCursor()
                selected_text = cursor.selectedText()

        if not selected_text:
            return {"content": [{"type": "text", "text": "(no text selected)"}]}

        return {"content": [{"type": "text", "text": selected_text}]}

    def _replace_selection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Replace the selected text with new code."""
        code = args.get("code", "")
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        if hasattr(block, "editor"):
            editor = block.editor
            if hasattr(editor, "replaceSelectedText"):
                editor.replaceSelectedText(code)
                return {"content": [{"type": "text", "text": f"Replaced selection with {len(code)} characters."}]}
            elif hasattr(editor, "textCursor"):
                cursor = editor.textCursor()
                cursor.insertText(code)
                return {"content": [{"type": "text", "text": f"Inserted {len(code)} characters."}]}

        return {"error": "Cannot replace selection in this editor."}

    def _insert_at_cursor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Insert code at the current cursor position."""
        code = args.get("code", "")
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        if hasattr(block, "editor"):
            editor = block.editor
            if hasattr(editor, "insert"):
                editor.insert(code)
                return {"content": [{"type": "text", "text": f"Inserted {len(code)} characters at cursor."}]}
            elif hasattr(editor, "insertPlainText"):
                editor.insertPlainText(code)
                return {"content": [{"type": "text", "text": f"Inserted {len(code)} characters at cursor."}]}

        return {"error": "Cannot insert text in this editor."}

    # === Batch/Multi-block Tool Implementations ===

    def _get_all_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get all blocks with their code."""
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks:
            return {"content": [{"type": "text", "text": "No blocks in session."}]}

        parts = []
        for i, block in enumerate(blocks):
            language = getattr(block, "language", "python")
            code = ""
            if hasattr(block, "get_code"):
                code = block.get_code()
            elif hasattr(block, "code"):
                code = block.code
            name = block.get_block_name() if hasattr(block, "get_block_name") else f"block{i + 1}"
            parts.append(f"## Block {i} - '{name}' ({language}):\n```{language}\n{code}\n```")

        return {"content": [{"type": "text", "text": "\n\n".join(parts)}]}

    def _run_all_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all blocks in sequence, wait for all, return results."""
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks:
            return {"error": "No blocks to execute."}

        # Use execute_all_blocks which handles queuing properly
        if hasattr(block_editor, "execute_all_blocks"):
            output_before = self._get_output_snapshot()
            try:
                block_editor.execute_all_blocks()
            except Exception as e:
                return {"error": f"Execution failed: {e}"}

            # Wait for ALL blocks to finish
            for block in blocks:
                self._wait_for_block_execution(block, timeout_ms=30000)

            return self._collect_execution_result(blocks[-1], len(blocks) - 1, output_before)

        return {"error": "Block editor does not support execute_all_blocks."}

    def _fix_and_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fix code in the focused block and re-execute."""
        fixed_code = args.get("fixed_code", "")
        if not fixed_code:
            return {"error": "fixed_code is required."}

        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        # Update the code
        self._signal_copilot_editing(block, block_editor)
        block.set_code(fixed_code)
        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        # Execute and wait for result
        return self._execute_block_with_result(block, block_editor, block_index)

    def _append_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Append code to the end of the focused block."""
        code = args.get("code", "")
        if not code:
            return {"error": "code is required."}

        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        # Get current code
        current_code = ""
        if hasattr(block, "get_code"):
            current_code = block.get_code()
        elif hasattr(block, "code"):
            current_code = block.code

        # Append new code
        new_code = current_code + "\n" + code if current_code else code
        block.set_code(new_code)

        return {
            "content": [{
                "type": "text",
                "text": f"Appended {len(code)} characters to block."
            }]
        }

    def _move_focus(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Move focus to a specific block by name or index."""
        target_block, block_editor, block_index, error = self._resolve_block(args, require=True)
        if error:
            return {"error": error}

        # Try to focus the block
        if hasattr(block_editor, "focus_block"):
            block_editor.focus_block(target_block)
        elif hasattr(target_block, "setFocus"):
            target_block.setFocus()
        elif hasattr(target_block, "editor") and hasattr(target_block.editor, "setFocus"):
            target_block.editor.setFocus()

        name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{block_index}"
        return {
            "content": [{
                "type": "text",
                "text": f"Focused block {block_index} ('{name}')."
            }]
        }

    # === Database Intelligence Tool Implementations ===

    def _get_connector(self):
        """Get the database connector for the current session."""
        session = self._get_active_session()
        if not session or not session.connection_name:
            return None, "No database connection in current session."

        mw = self._main_window
        conn_manager = getattr(mw, "_connection_manager", None)
        if not conn_manager:
            # Try to import and get
            try:
                from ...database import ConnectionManager
                conn_manager = ConnectionManager()
            except Exception as e:
                return None, f"Cannot access connection manager: {e}"

        connector = conn_manager.get_connection(session.connection_name)
        if not connector:
            return None, f"Connection '{session.connection_name}' not found."

        if not connector.is_connected:
            return None, f"Connection '{session.connection_name}' is not connected."

        return connector, None

    def _get_database_schema(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the complete database schema from cache or live."""
        mw = self._main_window
        session = self._get_active_session()

        if not session or not session.connection_name:
            return {"error": "No database connection. Connect to a database first."}

        connection_name = session.connection_name

        # Try to get from schema service (cached)
        schema_service = getattr(mw, "_schema_service", None)
        if schema_service:
            cached = schema_service.get_cached_schema(connection_name)
            if cached:
                schema_info = []
                schema_info.append(f"Database: {cached.get('database', 'unknown')}")
                schema_info.append(f"Connection: {connection_name}")
                schema_info.append("")

                tables = cached.get("tables", [])
                columns_map = cached.get("columns", {})

                for table in tables:
                    table_name = table.get("name", "")
                    schema_name = table.get("schema", "")
                    full_name = f"{schema_name}.{table_name}" if schema_name else table_name

                    cols = columns_map.get(table_name, [])
                    col_info = []
                    for col in cols:
                        col_name = col.get("name", "")
                        col_type = col.get("type", "")
                        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                        col_info.append(f"    - {col_name}: {col_type} {nullable}")

                    schema_info.append(f"TABLE {full_name}:")
                    if col_info:
                        schema_info.extend(col_info)
                    else:
                        schema_info.append("    (no columns loaded)")
                    schema_info.append("")

                return {
                    "content": [{
                        "type": "text",
                        "text": "\n".join(schema_info)
                    }]
                }

        return {"error": f"No schema loaded for '{connection_name}'. Wait for schema to load after connecting."}

    def _list_tables(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all tables in the connected database."""
        mw = self._main_window
        session = self._get_active_session()

        if not session or not session.connection_name:
            return {"error": "No database connection."}

        connection_name = session.connection_name
        schema_service = getattr(mw, "_schema_service", None)

        if schema_service:
            cached = schema_service.get_cached_schema(connection_name)
            if cached:
                tables = cached.get("tables", [])
                table_names = [t.get("name", "") for t in tables]

                return {
                    "content": [{
                        "type": "text",
                        "text": f"Tables ({len(table_names)}):\n" + "\n".join(f"  - {t}" for t in table_names)
                    }]
                }

        return {"error": "No schema loaded. Connect to database first."}

    def _describe_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Describe a specific table's structure."""
        table_name = args.get("table_name", "")
        if not table_name:
            return {"error": "table_name is required."}

        mw = self._main_window
        session = self._get_active_session()

        if not session or not session.connection_name:
            return {"error": "No database connection."}

        connection_name = session.connection_name
        schema_service = getattr(mw, "_schema_service", None)

        if schema_service:
            cached = schema_service.get_cached_schema(connection_name)
            if cached:
                columns_map = cached.get("columns", {})
                cols = columns_map.get(table_name, [])

                if not cols:
                    # Try case-insensitive match
                    for key in columns_map.keys():
                        if key.lower() == table_name.lower():
                            cols = columns_map[key]
                            table_name = key
                            break

                if cols:
                    col_info = []
                    for col in cols:
                        col_name = col.get("name", "")
                        col_type = col.get("type", "")
                        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                        col_info.append(f"  {col_name}: {col_type} {nullable}")

                    return {
                        "content": [{
                            "type": "text",
                            "text": f"Table: {table_name}\nColumns:\n" + "\n".join(col_info)
                        }]
                    }
                else:
                    return {"error": f"Table '{table_name}' not found in schema."}

        return {"error": "No schema loaded."}

    def _run_silent_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run a SQL query without creating a visible block."""
        query = args.get("query", "")
        if not query:
            return {"error": "query is required."}

        connector, error = self._get_connector()
        if error:
            return {"error": error}

        try:
            result = connector.execute_query(query)

            # Format result
            if isinstance(result, list):
                # Multiple results
                output = []
                for i, df in enumerate(result):
                    if df is not None and not df.empty:
                        output.append(f"Result {i + 1}:\n{df.to_string(max_rows=20, max_cols=10)}")
                return {
                    "content": [{
                        "type": "text",
                        "text": "\n\n".join(output) if output else "Query executed. No results."
                    }]
                }
            elif result is not None and hasattr(result, 'empty'):
                # Single DataFrame
                if result.empty:
                    return {
                        "content": [{
                            "type": "text",
                            "text": f"Query executed. {len(result)} rows returned (empty result)."
                        }]
                    }
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Rows: {len(result)}\n\n{result.to_string(max_rows=30, max_cols=15)}"
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": "Query executed successfully."
                    }]
                }

        except Exception as e:
            return {"error": f"Query error: {str(e)}"}

    def _run_silent_python(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code without creating a visible block.

        Runs in the active session's namespace so existing DataFrames
        and variables are accessible. Captures stdout and returns it
        along with the result of the last expression (if any).
        """
        code = args.get("code", "")
        if not code:
            return {"error": "code is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        # Get session namespace
        session = self._get_active_session()
        namespace = {}
        if session and hasattr(session, "namespace"):
            namespace = session.namespace.copy()

        # Inject standard libraries
        try:
            import pandas as _pd
            namespace.setdefault("pd", _pd)
        except ImportError:
            pass
        try:
            import numpy as _np
            namespace.setdefault("np", _np)
        except ImportError:
            pass

        # Execute with stdout capture
        import io
        import sys
        import traceback

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        result_value = None

        try:
            sys.stdout = stdout_capture

            # Try as expression first (returns a value)
            try:
                compiled = compile(code, "<silent>", "eval")
                result_value = eval(compiled, namespace)
            except SyntaxError:
                # Execute as statements
                compiled = compile(code, "<silent>", "exec")
                exec(compiled, namespace)

            # Update session namespace with new variables
            if session and hasattr(session, "update_namespace"):
                session.update_namespace(namespace)

        except Exception:
            error_text = traceback.format_exc()
            return {"error": f"Python error:\n{error_text}"}
        finally:
            sys.stdout = old_stdout

        # Build result
        parts = []
        stdout_text = stdout_capture.getvalue().strip()
        if stdout_text:
            if len(stdout_text) > 5000:
                stdout_text = stdout_text[:5000] + "\n... (truncated)"
            parts.append(f"Output:\n```\n{stdout_text}\n```")

        if result_value is not None:
            try:
                # Format DataFrames nicely
                if hasattr(result_value, "to_string") and hasattr(result_value, "shape"):
                    preview = result_value.head(30).to_string()
                    parts.append(f"Result ({type(result_value).__name__} {result_value.shape}):\n```\n{preview}\n```")
                else:
                    val_str = repr(result_value)
                    if len(val_str) > 3000:
                        val_str = val_str[:3000] + "..."
                    parts.append(f"Result: {val_str}")
            except Exception:
                parts.append(f"Result: {type(result_value).__name__}")

        if not parts:
            parts.append("Code executed successfully (no output).")

        return {"content": [{"type": "text", "text": "\n\n".join(parts)}]}

    def _sample_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get sample rows from a table."""
        table_name = args.get("table_name", "")
        limit = args.get("limit", 5)

        if not table_name:
            return {"error": "table_name is required."}

        # Validate limit is a positive integer
        try:
            limit = int(limit)
            if limit <= 0 or limit > 10000:
                limit = 5
        except (TypeError, ValueError):
            limit = 5

        connector, error = self._get_connector()
        if error:
            return {"error": error}

        # Validate table_name against known tables (SQL injection prevention)
        known_tables = self._get_known_table_names()
        if known_tables and table_name.lower() not in known_tables:
            return {"error": f"Unknown table: '{table_name}'. Use list_tables to see available tables."}

        try:
            # Build sample query based on db type with proper quoting
            db_type = getattr(connector, "db_type", "").lower()
            quoted_table = self._quote_identifier(table_name, db_type)
            
            if db_type in ("sqlserver", "mssql"):
                query = f"SELECT TOP {limit} * FROM {quoted_table}"
            else:
                query = f"SELECT * FROM {quoted_table} LIMIT {limit}"

            result = connector.execute_query(query)

            if result is not None and hasattr(result, 'empty') and not result.empty:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Sample from {table_name} ({len(result)} rows):\n\n{result.to_string()}"
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Table {table_name} appears to be empty."
                    }]
                }

        except Exception as e:
            return {"error": f"Error sampling table: {str(e)}"}

    def _get_execution_results(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get execution results: output text, DataFrame preview, and errors."""
        mw = self._main_window
        if not mw:
            return {"error": "Main window not available"}

        parts = []

        # Get output panel text
        output_panel = getattr(mw, "global_output_panel", None)
        if output_panel and hasattr(output_panel, "get_text"):
            output_text = output_panel.get_text()
            if output_text and output_text.strip():
                # Limit output to last 5000 chars to avoid token overflow
                if len(output_text) > 5000:
                    output_text = "... (truncated)\n" + output_text[-5000:]
                parts.append(f"## Output:\n```\n{output_text}\n```")
            else:
                parts.append("## Output:\n(empty)")

        # Get results viewer DataFrame
        results_viewer = getattr(mw, "global_results_viewer", None)
        if results_viewer:
            current_df = getattr(results_viewer, "current_df", None)
            if current_df is not None and hasattr(current_df, "empty") and not current_df.empty:
                # Show preview (first 50 rows)
                preview_rows = 50
                rows_total = len(current_df)
                cols_total = len(current_df.columns)
                preview_df = current_df.head(preview_rows)
                parts.append(f"## Results Grid ({rows_total} rows x {cols_total} columns):")
                parts.append(f"```\n{preview_df.to_string()}\n```")
                if rows_total > preview_rows:
                    parts.append(f"(showing first {preview_rows} of {rows_total} rows)")
            else:
                parts.append("## Results Grid:\n(no data)")

        if not parts:
            return {
                "content": [{
                    "type": "text",
                    "text": "No execution results available. Make sure to run a block first."
                }]
            }

        return {
            "content": [{
                "type": "text",
                "text": "\n\n".join(parts)
            }]
        }

    def _notify_user(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show a notification to the user."""
        title = args.get("title", "Notification")
        message = args.get("message", "")
        success = args.get("success", True)

        if not message:
            return {"error": "Message is required"}

        mw = self._main_window
        if not mw:
            return {"error": "Main window not available"}

        # Use the toast notification system
        if hasattr(mw, "_send_notification"):
            mw._send_notification(title, message, success)
        else:
            logger.warning("MainWindow does not have _send_notification method")
            return {"error": "Notification system not available"}

        return {
            "content": [{
                "type": "text",
                "text": f"Notification sent: {title}"
            }]
        }

    # === Granular Editing Tool Implementations ===

    def _edit_block_lines(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Edit specific lines in a block (replace, insert, or delete)."""
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        new_code = args.get("new_code", "")
        mode = args.get("mode", "replace")

        if start_line is None:
            return {"error": "start_line is required."}

        if mode not in ("replace", "insert", "delete"):
            return {"error": f"Invalid mode '{mode}'. Use 'replace', 'insert', or 'delete'."}

        target_block, block_editor, block_index, error = self._resolve_block(args, require=True)
        if error:
            return {"error": error}
        current_code = ""
        if hasattr(target_block, "get_code"):
            current_code = target_block.get_code()
        elif hasattr(target_block, "code"):
            current_code = target_block.code

        lines = current_code.split("\n")
        total_lines = len(lines)

        if mode == "insert":
            if start_line < 1 or start_line > total_lines + 1:
                return {"error": f"start_line {start_line} out of range (1-{total_lines + 1})."}
        else:
            if start_line < 1 or start_line > total_lines:
                return {"error": f"start_line {start_line} out of range (1-{total_lines})."}

        if mode == "replace":
            if end_line is None:
                end_line = start_line
            if end_line < start_line or end_line > total_lines:
                return {"error": f"end_line {end_line} out of range ({start_line}-{total_lines})."}
            new_lines = new_code.split("\n") if new_code else []
            lines[start_line - 1:end_line] = new_lines
            action = f"Replaced lines {start_line}-{end_line}"

        elif mode == "insert":
            new_lines = new_code.split("\n") if new_code else []
            insert_pos = start_line - 1
            lines[insert_pos:insert_pos] = new_lines
            action = f"Inserted {len(new_lines)} lines before line {start_line}"

        elif mode == "delete":
            if end_line is None:
                end_line = start_line
            if end_line < start_line or end_line > total_lines:
                return {"error": f"end_line {end_line} out of range ({start_line}-{total_lines})."}
            del lines[start_line - 1:end_line]
            action = f"Deleted lines {start_line}-{end_line}"

        result_code = "\n".join(lines)
        # Show copilot editing indicator and scroll into view
        self._signal_copilot_editing(target_block, block_editor)
        target_block.set_code(result_code)
        # Highlight the edited region and move cursor there
        if mode == "replace":
            highlight_end = start_line + len(new_lines) - 1 if new_lines else start_line
            self._highlight_edited_lines(target_block, start_line, max(highlight_end, start_line))
        elif mode == "insert":
            highlight_end = start_line + len(new_lines) - 1 if new_lines else start_line
            self._highlight_edited_lines(target_block, start_line, max(highlight_end, start_line))
        elif mode == "delete":
            # After deletion, highlight the line where content was removed
            hl_line = min(start_line, len(lines)) if lines else 1
            self._highlight_edited_lines(target_block, hl_line, hl_line)

        block_name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{block_index}"
        return {
            "content": [{
                "type": "text",
                "text": f"{action} in block {block_index} ('{block_name}'). Block now has {len(lines)} lines."
            }]
        }

    def _get_block_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the full code from a block by name, index, or focused block."""
        target_block, block_editor, block_index, error = self._resolve_block(args)
        if error:
            return {"error": error}

        code = ""
        if hasattr(target_block, "get_code"):
            code = target_block.get_code()
        elif hasattr(target_block, "code"):
            code = target_block.code

        language = target_block.get_language() if hasattr(target_block, "get_language") else "unknown"
        name = target_block.get_block_name() if hasattr(target_block, "get_block_name") else f"block{block_index + 1}"
        total_lines = len(code.split("\n"))

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} ('{name}', {language}, {total_lines} lines):\n```{language}\n{code}\n```"
            }]
        }

    def _search_in_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search for text across all blocks."""
        query = args.get("query", "")
        if not query:
            return {"error": "query is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks:
            return {"content": [{"type": "text", "text": "No blocks in session."}]}

        query_lower = query.lower()
        matches = []
        for i, block in enumerate(blocks):
            code = ""
            if hasattr(block, "get_code"):
                code = block.get_code()
            elif hasattr(block, "code"):
                code = block.code

            for line_num, line in enumerate(code.split("\n"), start=1):
                if query_lower in line.lower():
                    matches.append(f"  Block {i}, line {line_num}: {line.strip()}")

        if not matches:
            return {"content": [{"type": "text", "text": f"No matches found for '{query}'."}]}

        return {
            "content": [{
                "type": "text",
                "text": f"Found {len(matches)} matches for '{query}':\n" + "\n".join(matches)
            }]
        }

    # === Output Reading Tool Implementation ===

    def _read_output(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read the last N lines from the output panel."""
        last_n = args.get("last_n_lines", 50)
        try:
            last_n = int(last_n)
            if last_n < 0:
                last_n = 50
        except (TypeError, ValueError):
            last_n = 50

        mw = self._main_window
        if not mw:
            return {"error": "Main window not available."}

        output_panel = getattr(mw, "global_output_panel", None)
        if not output_panel:
            return {"error": "Output panel not available."}

        text = ""
        if hasattr(output_panel, "get_text"):
            text = output_panel.get_text() or ""
        elif hasattr(output_panel, "text_edit"):
            text = output_panel.text_edit.toPlainText() or ""

        if not text.strip():
            return {"content": [{"type": "text", "text": "(output panel is empty)"}]}

        lines = text.strip().split("\n")

        if last_n == 0:
            # Return all
            output = "\n".join(lines)
        else:
            output = "\n".join(lines[-last_n:])
            if len(lines) > last_n:
                output = f"... ({len(lines) - last_n} earlier lines omitted)\n{output}"

        if len(output) > 8000:
            output = output[-8000:] + "\n... (truncated)"

        return {"content": [{"type": "text", "text": f"Output ({len(lines)} total lines):\n```\n{output}\n```"}]}

