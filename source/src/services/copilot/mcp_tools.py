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

from PyQt6.QtCore import QObject

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
        self._register_tools()

    def set_main_window(self, main_window) -> None:
        """Set reference to the main window for tool operations."""
        self._main_window = main_window

    def _register_tools(self) -> None:
        """Register all available tools."""
        # THINK tool - most important, should be used first
        self._register(MCPTool(
            name="think",
            description="Use this tool to PLAN and REASON about your approach BEFORE taking any action. Think step by step about: 1) What the user wants 2) How many blocks you need 3) The data flow (what SQL queries, what Python processing). This helps you avoid creating/deleting blocks repeatedly.",
            parameters={
                "thought": {
                    "type": "string",
                    "description": "Your reasoning about how to approach the task. Be specific: mention tables, columns, SQL queries, Python libraries you'll use.",
                },
            },
            handler=self._think,
        ))

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
            description="CREATE a new code block and WRITE code into it. IMPORTANT: The block NAME becomes the DataFrame variable name. Example: block named 'vendas' with SQL creates DataFrame `vendas` that Python can use.",
            parameters={
                "language": {
                    "type": "string",
                    "description": "Block language: 'python' for data analysis/pandas/matplotlib, 'sql' for database queries.",
                    "enum": ["python", "sql", "cross"],
                },
                "code": {
                    "type": "string",
                    "description": "The actual code to write in the block. SQL queries or Python code with imports.",
                },
                "name": {
                    "type": "string",
                    "description": "REQUIRED: Semantic name for the block (e.g., 'vendas', 'clientes', 'grafico'). This becomes the DataFrame variable name for SQL blocks. Use snake_case, no spaces.",
                    "optional": True,
                },
            },
            handler=self._create_block,
        ))

        self._register(MCPTool(
            name="edit_block",
            description="MODIFY/REWRITE the code in an existing block. Use this to fix errors, improve code, or completely replace the content. The new code you provide will replace the current code in the block.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The new code to write in the block. This REPLACES all existing code.",
                },
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to edit (0-based). Use get_context to see block indices.",
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
            description="Open a saved connection in a NEW TAB. Creates a fresh tab and connects to the specified database. Use this when user wants to start working with a different database without losing current work.",
            parameters={
                "connection_name": {
                    "type": "string",
                    "description": "Name of the saved connection to open in new tab.",
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
            description="GET CURRENT STATE: all blocks with their code, languages, indices, current connection, available tables. Use this first to understand what code exists and what block indices to use.",
            parameters={},
            handler=self._get_context,
        ))

        self._register(MCPTool(
            name="execute_block",
            description="RUN/EXECUTE a code block and GET THE RESULT. This actually runs the Python or SQL code and returns the output (printed text, dataframes, query results, errors). Use after create_block or edit_block to see results.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to execute (0-based). Block 0 is the first block.",
                },
            },
            handler=self._execute_block,
        ))

        self._register(MCPTool(
            name="run_current_block",
            description="RUN the currently focused block and GET THE RESULT. Same as execute_block but for the active block.",
            parameters={},
            handler=self._run_current_block,
        ))

        self._register(MCPTool(
            name="list_connections",
            description="List all saved database connections.",
            parameters={},
            handler=self._list_connections,
        ))

        self._register(MCPTool(
            name="get_variables",
            description="Get all Python variables available in the current session's namespace.",
            parameters={},
            handler=self._get_variables,
        ))

        self._register(MCPTool(
            name="set_block_language",
            description="Change the language of a block.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block (0-based).",
                },
                "language": {
                    "type": "string",
                    "description": "New language: python, sql, or cross.",
                    "enum": ["python", "sql", "cross"],
                },
            },
            handler=self._set_block_language,
        ))

        self._register(MCPTool(
            name="delete_block",
            description="Delete a block by index.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to delete (0-based).",
                },
            },
            handler=self._delete_block,
        ))

        self._register(MCPTool(
            name="get_block_result",
            description="GET the output/result from a previously executed block. Use to check what a block printed, returned, or if it had errors.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block (0-based).",
                },
            },
            handler=self._get_block_result,
        ))

        # Most useful tool - does everything in one call
        self._register(MCPTool(
            name="write_and_run",
            description="CREATE a new block, WRITE code, and EXECUTE immediately. IMPORTANT: The block NAME becomes the DataFrame variable. Example: name='vendas' with SQL query creates `vendas` DataFrame accessible in Python blocks.",
            parameters={
                "language": {
                    "type": "string",
                    "description": "'python' for data analysis/pandas/matplotlib, 'sql' for database queries.",
                    "enum": ["python", "sql", "cross"],
                },
                "code": {
                    "type": "string",
                    "description": "Complete executable code. Python: include imports, use print() for output. SQL: write the query.",
                },
                "name": {
                    "type": "string",
                    "description": "REQUIRED: Semantic name for the block (e.g., 'vendas', 'clientes', 'grafico'). For SQL blocks, this becomes the DataFrame variable name. Use snake_case, no spaces.",
                    "optional": True,
                },
            },
            handler=self._write_and_run,
        ))

        # Rename block tool
        self._register(MCPTool(
            name="rename_block",
            description="RENAME a block. The name determines the DataFrame variable name for SQL blocks. Example: renaming to 'vendas' means the SQL result becomes `vendas` DataFrame.",
            parameters={
                "name": {
                    "type": "string",
                    "description": "New name for the block (e.g., 'vendas', 'clientes'). Use snake_case, no spaces.",
                },
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to rename (0-based). If omitted, renames the focused block.",
                    "optional": True,
                },
            },
            handler=self._rename_block,
        ))

        # === Focused Block Tools ===
        self._register(MCPTool(
            name="get_focused_code",
            description="GET the code from the currently focused block. Use this to see what code the user is working on right now.",
            parameters={},
            handler=self._get_focused_code,
        ))

        self._register(MCPTool(
            name="edit_focused_code",
            description="EDIT/REPLACE the code in the currently focused block. Use to fix errors, improve code, or rewrite what the user is working on.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The new code to write. This REPLACES all existing code in the focused block.",
                },
            },
            handler=self._edit_focused_code,
        ))

        # Alias for edit_focused_code - more intuitive name
        self._register(MCPTool(
            name="edit_current_block",
            description="EDIT the current/focused block. Use this to modify the user's existing code instead of creating a new block. Preferred when user wants to change existing code.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The new code to write. This REPLACES all existing code in the current block.",
                },
            },
            handler=self._edit_focused_code,
        ))

        self._register(MCPTool(
            name="execute_focused",
            description="EXECUTE the currently focused block and return the result.",
            parameters={},
            handler=self._execute_focused,
        ))

        self._register(MCPTool(
            name="get_focused_result",
            description="GET the execution result/output from the currently focused block.",
            parameters={},
            handler=self._get_focused_result,
        ))

        # === Selection Tools ===
        self._register(MCPTool(
            name="get_selection",
            description="GET the currently selected text in the focused block. Returns empty if nothing is selected.",
            parameters={},
            handler=self._get_selection,
        ))

        self._register(MCPTool(
            name="replace_selection",
            description="REPLACE the selected text with new code. If nothing is selected, inserts at cursor position.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The code to insert/replace.",
                },
            },
            handler=self._replace_selection,
        ))

        self._register(MCPTool(
            name="insert_at_cursor",
            description="INSERT code at the current cursor position in the focused block.",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The code to insert.",
                },
            },
            handler=self._insert_at_cursor,
        ))

        # === Batch/Multi-block Tools ===
        self._register(MCPTool(
            name="get_all_code",
            description="GET all blocks with their code, language, and index. Use to understand the full session.",
            parameters={},
            handler=self._get_all_code,
        ))

        self._register(MCPTool(
            name="run_all_blocks",
            description="EXECUTE all blocks in the current tab/session in sequence (block1, block2, ...). Use this after creating multiple blocks to run the complete analysis workflow. SQL blocks store results as block1, block2 etc. that Python blocks can then use.",
            parameters={},
            handler=self._run_all_blocks,
        ))

        self._register(MCPTool(
            name="fix_and_run",
            description="FIX errors in the focused block and re-execute. Provide the corrected code.",
            parameters={
                "fixed_code": {
                    "type": "string",
                    "description": "The corrected code to replace the current code.",
                },
            },
            handler=self._fix_and_run,
        ))

        self._register(MCPTool(
            name="append_code",
            description="APPEND code to the end of the focused block (adds after existing code).",
            parameters={
                "code": {
                    "type": "string",
                    "description": "The code to append.",
                },
            },
            handler=self._append_code,
        ))

        self._register(MCPTool(
            name="move_focus",
            description="MOVE focus to a specific block by index.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to focus (0-based).",
                },
            },
            handler=self._move_focus,
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
            description="RUN a SQL query silently (without creating a visible block). Returns query results directly. Use for data exploration, counts, or when you need data to answer a question but don't need to show code to user.",
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

        # === Results & Notifications ===
        self._register(MCPTool(
            name="get_execution_results",
            description="GET the complete execution results: output text (print statements, logs), DataFrame in the results grid (first 50 rows as preview), and any errors. Use this AFTER executing a block to verify it worked and see the data.",
            parameters={
                "block_index": {
                    "type": "integer",
                    "description": "Index of the block to get results from (0-based). If omitted, gets results from the last executed block.",
                    "optional": True,
                },
            },
            handler=self._get_execution_results,
        ))

        self._register(MCPTool(
            name="notify_user",
            description="SHOW a notification to get the user's attention. Use when: task is complete, need user input, or found something important. Shows a toast popup in the corner of the screen.",
            parameters={
                "title": {
                    "type": "string",
                    "description": "Short title for the notification (e.g., 'Analysis Complete', 'Action Required').",
                },
                "message": {
                    "type": "string",
                    "description": "The notification message with details.",
                },
                "success": {
                    "type": "boolean",
                    "description": "True for success (green), False for error/warning (red). Default: True.",
                    "optional": True,
                },
            },
            handler=self._notify_user,
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
        """Edit code in a block."""
        code = args.get("code", "")
        block_index = args.get("block_index")
        mw = self._main_window

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
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

    def _rename_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Rename a block. The name determines the DataFrame variable name for SQL blocks."""
        name = args.get("name", "")
        block_index = args.get("block_index")

        if not name:
            return {"error": "name is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
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
                        # Use get_language() method, not language attribute
                        lang = block.get_language() if hasattr(block, "get_language") else "unknown"
                        code = block.get_code() if hasattr(block, "get_code") else ""
                        is_focused = block == block_editor.focused_block
                        blocks_info.append({
                            "index": i,
                            "language": lang,
                            "code": code[:100] + "..." if len(code) > 100 else code,
                            "is_focused": is_focused,
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

    def _execute_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a block by index."""
        block_index = args.get("block_index")
        if block_index is None:
            return {"error": "block_index is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks or block_index < 0 or block_index >= len(blocks):
            return {"error": f"Block index {block_index} out of range (0-{len(blocks) - 1})."}

        target_block = blocks[block_index]

        # Execute the block
        if hasattr(block_editor, "execute_block"):
            try:
                block_editor.execute_block(target_block)
                return {
                    "content": [{"type": "text", "text": f"Block {block_index} execution started."}]
                }
            except Exception as e:
                return {"error": f"Execution failed: {e}"}

        return {"error": "Block editor does not support execute_block."}

    def _run_current_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the currently focused block."""
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

        if hasattr(block_editor, "execute_block"):
            try:
                block_editor.execute_block(focused_block)
                return {
                    "content": [{"type": "text", "text": "Current block execution started."}]
                }
            except Exception as e:
                return {"error": f"Execution failed: {e}"}

        return {"error": "Block editor does not support execute_block."}

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

    def _set_block_language(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Change the language of a block."""
        block_index = args.get("block_index")
        language = args.get("language", "python")

        if block_index is None:
            return {"error": "block_index is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks or block_index < 0 or block_index >= len(blocks):
            return {"error": f"Block index {block_index} out of range."}

        target_block = blocks[block_index]
        if hasattr(target_block, "set_language"):
            target_block.set_language(language)
            return {
                "content": [{"type": "text", "text": f"Block {block_index} language changed to {language}."}]
            }

        return {"error": "Block does not support set_language."}

    def _delete_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a block by index."""
        block_index = args.get("block_index")
        if block_index is None:
            return {"error": "block_index is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks or block_index < 0 or block_index >= len(blocks):
            return {"error": f"Block index {block_index} out of range."}

        if hasattr(block_editor, "remove_block"):
            target_block = blocks[block_index]
            block_editor.remove_block(target_block)
            return {
                "content": [{"type": "text", "text": f"Block {block_index} deleted."}]
            }

        return {"error": "Block editor does not support remove_block."}

    def _get_block_result(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the last execution result of a block."""
        block_index = args.get("block_index")
        if block_index is None:
            return {"error": "block_index is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks or block_index < 0 or block_index >= len(blocks):
            return {"error": f"Block index {block_index} out of range."}

        target_block = blocks[block_index]

        # Try to get the result from the block's result panel
        result_text = ""
        if hasattr(target_block, "result_panel"):
            result_panel = target_block.result_panel
            if hasattr(result_panel, "get_text"):
                result_text = result_panel.get_text()
            elif hasattr(result_panel, "toPlainText"):
                result_text = result_panel.toPlainText()

        if not result_text:
            result_text = "(no result available)"

        return {"content": [{"type": "text", "text": result_text}]}

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
        block.set_code(code)
        block_index = len(block_editor.blocks) - 1
        actual_name = block.get_block_name()
        logger.info(f"write_and_run: Block {block_index} ('{actual_name}') created with {len(code)} chars")

        # 4. Execute the block
        if hasattr(block_editor, "execute_block"):
            try:
                logger.info(f"write_and_run: Executing block {block_index}...")
                block_editor.execute_block(block)
                logger.info(f"write_and_run: Execution started for block {block_index}")
                
                # Build response message
                msg_parts = [f"Block '{actual_name}' (index {block_index}, {language}) created and execution started."]
                if language == "sql":
                    msg_parts.append(f"Result will be stored as DataFrame `{actual_name}`.")
                msg_parts.append(f"\nCode:\n```{language}\n{code}\n```")
                msg_parts.append("Use get_execution_results() to see the output after execution completes.")
                
                return {
                    "content": [{
                        "type": "text",
                        "text": "\n".join(msg_parts)
                    }]
                }
            except Exception as e:
                logger.exception(f"write_and_run: Execution failed: {e}")
                return {"error": f"Block created but execution failed: {e}"}

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} created with code but could not execute automatically."
            }]
        }

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

        block.set_code(code)
        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} updated with {len(code)} characters."
            }]
        }

    def _execute_focused(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the currently focused block."""
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        if hasattr(block_editor, "execute_block"):
            try:
                block_editor.execute_block(block)
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Block {block_index} execution started."
                    }]
                }
            except Exception as e:
                return {"error": f"Execution failed: {e}"}

        return {"error": "Cannot execute block."}

    def _get_focused_result(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get the result from the currently focused block."""
        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        result_text = ""
        if hasattr(block, "result_panel"):
            result_panel = block.result_panel
            if hasattr(result_panel, "get_text"):
                result_text = result_panel.get_text()
            elif hasattr(result_panel, "toPlainText"):
                result_text = result_panel.toPlainText()

        if not result_text:
            result_text = "(no result available)"

        return {"content": [{"type": "text", "text": result_text}]}

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
            parts.append(f"## Block {i} ({language}):\n```{language}\n{code}\n```")

        return {"content": [{"type": "text", "text": "\n\n".join(parts)}]}

    def _run_all_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all blocks in sequence."""
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks:
            return {"error": "No blocks to execute."}

        if not hasattr(block_editor, "execute_block"):
            return {"error": "Block editor does not support execute_block."}

        executed = 0
        for block in blocks:
            try:
                block_editor.execute_block(block)
                executed += 1
            except Exception as e:
                logger.error(f"Error executing block: {e}")

        return {
            "content": [{
                "type": "text",
                "text": f"Started execution of {executed} blocks."
            }]
        }

    def _fix_and_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fix code in the focused block and re-execute."""
        fixed_code = args.get("fixed_code", "")
        if not fixed_code:
            return {"error": "fixed_code is required."}

        block, block_editor, error = self._get_focused_block()
        if error:
            return {"error": error}

        # Update the code
        block.set_code(fixed_code)
        block_index = block_editor.blocks.index(block) if block in block_editor.blocks else -1

        # Execute
        if hasattr(block_editor, "execute_block"):
            try:
                block_editor.execute_block(block)
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Block {block_index} fixed and execution started."
                    }]
                }
            except Exception as e:
                return {"error": f"Code updated but execution failed: {e}"}

        return {
            "content": [{
                "type": "text",
                "text": f"Block {block_index} fixed but could not execute."
            }]
        }

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
        """Move focus to a specific block."""
        block_index = args.get("block_index")
        if block_index is None:
            return {"error": "block_index is required."}

        session_widget = self._get_active_session_widget()
        if not session_widget:
            return {"error": "No active session."}

        block_editor = self._get_block_editor(session_widget)
        if not block_editor:
            return {"error": "Block editor not available."}

        blocks = block_editor.blocks
        if not blocks or block_index < 0 or block_index >= len(blocks):
            return {"error": f"Block index {block_index} out of range (0-{len(blocks) - 1})."}

        target_block = blocks[block_index]

        # Try to focus the block
        if hasattr(block_editor, "focus_block"):
            block_editor.focus_block(target_block)
        elif hasattr(target_block, "setFocus"):
            target_block.setFocus()
        elif hasattr(target_block, "editor") and hasattr(target_block.editor, "setFocus"):
            target_block.editor.setFocus()

        return {
            "content": [{
                "type": "text",
                "text": f"Focused block {block_index}."
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

