"""
Tests for Copilot MCP tools, MCP server, and CopilotClient.
"""

import pytest
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

# Shared test data
MOCK_SCHEMA = {
    "database": "testdb",
    "tables": [{"name": "users"}],
    "columns": {"users": [{"name": "id"}, {"name": "email"}]},
}


# ==================== MCPToolRegistry Tests ====================


class TestMCPToolRegistry:
    """Tests for MCPToolRegistry - tool registration and execution."""

    def setup_method(self):
        from src.services.copilot.mcp_tools import MCPToolRegistry
        self.registry = MCPToolRegistry()

    def test_list_tools_returns_all_tools(self):
        """All expected tools should be registered."""
        tools = self.registry.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "create_tab" in tool_names
        assert "create_block" in tool_names
        assert "edit_block" in tool_names
        assert "connect_database" in tool_names
        assert "create_connection" in tool_names
        assert "open_connection" in tool_names
        assert "read_schema" in tool_names
        assert "get_context" in tool_names
        assert "list_visualizations" in tool_names
        assert "create_visualization" in tool_names
        assert "edit_visualization" in tool_names
        assert "resolve_reference" in tool_names
        assert "get_tab_context" in tool_names
        assert "get_block_result" in tool_names

    def _make_reference_main_window(self):
        block = MagicMock()
        block.get_block_name.return_value = "orders"
        block.get_language.return_value = "sql"
        block.get_code.return_value = "SELECT * FROM orders"

        editor = MagicMock()
        editor.get_blocks.return_value = [block]
        editor.blocks = [block]

        widget = SimpleNamespace(
            session=SimpleNamespace(title="Sales", session_id="sales-tab", connection_name="prod"),
            editor=editor,
            namespace={"orders": [{"id": 1}]},
        )

        tabs = MagicMock()
        tabs.count.return_value = 1
        tabs.currentIndex.return_value = 0
        tabs.widget.return_value = widget
        tabs.tabText.return_value = "Sales"

        return SimpleNamespace(session_tabs=tabs)

    def _tool_json_payload(self, result):
        return json.loads(result["content"][0]["text"])

    def test_resolve_reference_tool_resolves_block(self):
        self.registry.set_main_window(self._make_reference_main_window())

        result = self.registry.execute("resolve_reference", {"reference": "#block1"})
        payload = self._tool_json_payload(result)

        assert payload["ok"] is True
        assert payload["type"] == "block"
        assert payload["name"] == "orders"

    def test_get_tab_context_tool_resolves_tab_index(self):
        self.registry.set_main_window(self._make_reference_main_window())

        result = self.registry.execute("get_tab_context", {"tab_index": 0})
        payload = self._tool_json_payload(result)

        assert payload["ok"] is True
        assert payload["type"] == "tab"
        assert payload["title"] == "Sales"

    def test_get_block_result_returns_block_and_result_preview(self):
        self.registry.set_main_window(self._make_reference_main_window())

        result = self.registry.execute("get_block_result", {"block_name": "orders"})
        payload = self._tool_json_payload(result)

        assert payload["block"]["ok"] is True
        assert payload["block"]["name"] == "orders"
        assert payload["result_preview"]["type"] == "list"

    def test_list_tools_has_correct_schema(self):
        """Each tool should have name, description, and inputSchema."""
        tools = self.registry.list_tools()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_execute_unknown_tool_returns_error(self):
        """Executing an unknown tool should return an error."""
        self.registry.set_main_window(MagicMock())
        result = self.registry.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_without_main_window_returns_error(self):
        """Executing a tool without main_window should return an error."""
        result = self.registry.execute("create_tab", {})
        assert "error" in result
        assert "Main window not available" in result["error"]

    def test_create_tab_creates_session(self):
        """create_tab should create a new session via session_manager."""
        mock_session = MagicMock()
        mock_session.title = "Test Tab"
        mock_session.session_id = "abc123"

        mock_mw = MagicMock()
        mock_mw.session_manager.create_session.return_value = mock_session

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("create_tab", {"title": "Test Tab"})

        assert "content" in result
        assert "Test Tab" in result["content"][0]["text"]
        mock_mw.session_manager.create_session.assert_called_once_with(title="Test Tab")

    def test_create_tab_pins_new_session_for_followup_tools(self):
        """After creating a tab, later tools in the same turn should target it."""
        mock_session = MagicMock()
        mock_session.title = "Produtos"
        mock_session.session_id = "new-session-id"

        mock_mw = MagicMock()
        mock_mw.session_manager.create_session.return_value = mock_session

        self.registry.set_main_window(mock_mw)
        self.registry.execute("create_tab", {"title": "Produtos"})

        assert self.registry._pinned_session_id == "new-session-id"

    def test_create_block_without_session_returns_error(self):
        """create_block without active session should return an error."""
        mock_mw = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = -1

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("create_block", {"language": "python", "code": "x = 1"})

        assert "error" in result

    def test_create_block_success(self):
        """create_block should add a block to the block editor."""
        mock_block = MagicMock()
        mock_editor = MagicMock(spec=["add_block", "blocks"])
        mock_editor.add_block.return_value = mock_block
        mock_editor.blocks = [mock_block]

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("create_block", {"language": "sql", "code": "SELECT 1"})

        assert "content" in result
        assert "sql" in result["content"][0]["text"]
        mock_editor.add_block.assert_called_once_with(language="sql")
        mock_block.set_code.assert_called_once_with("SELECT 1")

    def test_create_block_updates_existing_named_block(self):
        """create_block should update a named block instead of duplicating it."""
        mock_block = MagicMock()
        mock_block.get_block_name.return_value = "produtos"
        mock_editor = MagicMock(spec=["add_block", "blocks"])
        mock_editor.blocks = [mock_block]

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("create_block", {
            "language": "sql",
            "code": "SELECT * FROM produtos",
            "name": "produtos",
        })

        assert "content" in result
        mock_editor.add_block.assert_not_called()
        mock_block.set_code.assert_called_once_with("SELECT * FROM produtos")

    def test_edit_block_with_index(self):
        """edit_block should update the specified block's code."""
        mock_block = MagicMock()
        mock_editor = MagicMock(spec=["add_block", "blocks"])
        mock_editor.blocks = [mock_block]

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("edit_block", {"code": "print('hello')", "block_index": 0})

        assert "content" in result
        mock_block.set_code.assert_called_once_with("print('hello')")

    def test_edit_block_invalid_index(self):
        """edit_block with invalid index should return an error."""
        mock_editor = MagicMock()
        mock_editor.blocks = [MagicMock()]

        mock_widget = MagicMock()
        mock_widget.block_editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("edit_block", {"code": "x", "block_index": 99})

        assert "error" in result
        assert "out of range" in result["error"]

    def test_create_connection_saves_config(self):
        """create_connection should save connection configuration."""
        mock_conn_manager = MagicMock()
        mock_mw = MagicMock()
        mock_mw.connection_manager = mock_conn_manager

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("create_connection", {
            "name": "test_db",
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "mydb",
            "username": "user",
        })

        assert "content" in result
        assert "test_db" in result["content"][0]["text"]
        mock_conn_manager.save_connection_config.assert_called_once()

    def test_create_connection_missing_required_fields(self):
        """create_connection without required fields should error."""
        mock_mw = MagicMock()
        self.registry.set_main_window(mock_mw)

        result = self.registry.execute("create_connection", {"name": ""})
        assert "error" in result

    def test_read_schema_cached(self):
        """read_schema should return cached schema data."""
        mock_schema_service = MagicMock()
        mock_schema_service.get_cached_schema.return_value = MOCK_SCHEMA

        mock_session = MagicMock()
        mock_session.connection_name = "my_conn"

        mock_mw = MagicMock()
        mock_mw._schema_service = mock_schema_service
        mock_mw.session_manager.focused_session = mock_session

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("read_schema", {})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "testdb" in text
        assert "users" in text

    def test_read_schema_no_cache(self):
        """read_schema without cache should inform the user."""
        mock_schema_service = MagicMock()
        mock_schema_service.get_cached_schema.return_value = None

        mock_session = MagicMock()
        mock_session.connection_name = "my_conn"

        mock_mw = MagicMock()
        mock_mw._schema_service = mock_schema_service
        mock_mw.session_manager.focused_session = mock_session

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("read_schema", {})

        assert "content" in result
        assert "No schema cached" in result["content"][0]["text"]

    def test_get_context_returns_session_info(self):
        """get_context should return current session and block information."""
        mock_session = MagicMock()
        mock_session.session_id = "sess1"
        mock_session.title = "Script 1"
        mock_session.connection_name = "my_db"
        mock_session.is_connected = True

        mock_block = MagicMock()
        mock_block.get_language.return_value = "python"
        mock_block.get_code.return_value = "x = 1"
        mock_block.get_block_name.return_value = "block1"

        mock_editor = MagicMock(spec=["add_block", "blocks", "focused_block"])
        mock_editor.blocks = [mock_block]
        mock_editor.focused_block = mock_block

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("get_context", {})

        assert "content" in result
        context = json.loads(result["content"][0]["text"])
        assert context["session_id"] == "sess1"
        assert context["session_title"] == "Script 1"
        assert context["is_connected"] is True
        assert len(context["blocks"]) == 1
        assert context["blocks"][0]["language"] == "python"
        assert context["blocks"][0]["name"] == "block1"

    def test_inspect_variable_returns_value(self):
        """inspect_variable should return the actual value of a variable."""
        import pandas as pd
        
        mock_session = MagicMock()
        mock_widget = MagicMock()
        mock_widget.namespace = {
            "my_var": 42,
            "my_list": [1, 2, 3],
            "my_df": pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        }
        mock_widget.editor = MagicMock()

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        
        # Test simple int
        result = self.registry.execute("inspect_variable", {"name": "my_var"})
        assert "content" in result
        assert "42" in result["content"][0]["text"]
        
        # Test list
        result = self.registry.execute("inspect_variable", {"name": "my_list"})
        assert "content" in result
        assert "1" in result["content"][0]["text"]
        
        # Test DataFrame
        result = self.registry.execute("inspect_variable", {"name": "my_df"})
        assert "content" in result
        assert "DataFrame" in result["content"][0]["text"]

    def test_inspect_variable_not_found(self):
        """inspect_variable should error when variable doesn't exist."""
        mock_widget = MagicMock()
        mock_widget.namespace = {"x": 1}
        mock_widget.editor = MagicMock()

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("inspect_variable", {"name": "nonexistent"})
        assert "error" in result
        assert "not found" in result["error"]

    def test_get_dataframe_info_returns_structure(self):
        """get_dataframe_info should return DataFrame structure info."""
        import pandas as pd
        
        mock_widget = MagicMock()
        mock_widget.namespace = {
            "df": pd.DataFrame({"col_a": [1, 2, None], "col_b": ["x", "y", "z"]}),
        }
        mock_widget.editor = MagicMock()

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("get_dataframe_info", {"name": "df"})
        
        assert "content" in result
        text = result["content"][0]["text"]
        assert "col_a" in text
        assert "col_b" in text
        assert "3 rows" in text

    # === Tests for new tools ===

    def _make_mock_with_code(self, code, language="python", name="test_block"):
        """Helper to create a mock block with code."""
        mock_block = MagicMock()
        mock_block.get_code.return_value = code
        mock_block.get_language.return_value = language
        mock_block.get_block_name.return_value = name
        mock_block.language = language
        return mock_block

    def _make_mock_env(self, blocks):
        """Helper to create a mock environment with blocks."""
        mock_editor = MagicMock(spec=["add_block", "blocks", "focused_block"])
        mock_editor.blocks = blocks
        mock_editor.focused_block = blocks[0] if blocks else None

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        return mock_editor

    def test_edit_block_lines_replace(self):
        """edit_block_lines in replace mode should replace specific lines."""
        code = "line1\nline2\nline3\nline4\nline5"
        mock_block = self._make_mock_with_code(code)
        self._make_mock_env([mock_block])

        result = self.registry.execute("edit_block_lines", {
            "block_index": 0,
            "start_line": 2,
            "end_line": 3,
            "new_code": "replaced_line2\nreplaced_line3",
            "mode": "replace",
        })

        assert "content" in result
        assert "Replaced lines 2-3" in result["content"][0]["text"]
        # Verify the set_code call
        new_code = mock_block.set_code.call_args[0][0]
        assert "line1\nreplaced_line2\nreplaced_line3\nline4\nline5" == new_code

    def test_edit_block_lines_insert(self):
        """edit_block_lines in insert mode should insert before the specified line."""
        code = "line1\nline2\nline3"
        mock_block = self._make_mock_with_code(code)
        self._make_mock_env([mock_block])

        result = self.registry.execute("edit_block_lines", {
            "block_index": 0,
            "start_line": 2,
            "new_code": "inserted_a\ninserted_b",
            "mode": "insert",
        })

        assert "content" in result
        assert "Inserted 2 lines" in result["content"][0]["text"]
        new_code = mock_block.set_code.call_args[0][0]
        assert "line1\ninserted_a\ninserted_b\nline2\nline3" == new_code

    def test_edit_block_lines_delete(self):
        """edit_block_lines in delete mode should remove specified lines."""
        code = "line1\nline2\nline3\nline4\nline5"
        mock_block = self._make_mock_with_code(code)
        self._make_mock_env([mock_block])

        result = self.registry.execute("edit_block_lines", {
            "block_index": 0,
            "start_line": 2,
            "end_line": 4,
            "mode": "delete",
        })

        assert "content" in result
        assert "Deleted lines 2-4" in result["content"][0]["text"]
        new_code = mock_block.set_code.call_args[0][0]
        assert "line1\nline5" == new_code

    def test_edit_block_lines_invalid_range(self):
        """edit_block_lines with invalid line range should return error."""
        code = "line1\nline2"
        mock_block = self._make_mock_with_code(code)
        self._make_mock_env([mock_block])

        result = self.registry.execute("edit_block_lines", {
            "block_index": 0,
            "start_line": 5,
            "mode": "replace",
        })
        assert "error" in result
        assert "out of range" in result["error"]

    def test_edit_block_lines_missing_params(self):
        """edit_block_lines without required params should return error."""
        mock_mw = MagicMock()
        self.registry.set_main_window(mock_mw)

        result = self.registry.execute("edit_block_lines", {"block_index": 0})
        assert "error" in result
        assert "start_line" in result["error"]

    def test_get_block_code_returns_full_code(self):
        """get_block_code should return full code without truncation."""
        long_code = "\n".join([f"line_{i} = {i}" for i in range(200)])
        mock_block = self._make_mock_with_code(long_code, name="my_data")
        self._make_mock_env([mock_block])

        result = self.registry.execute("get_block_code", {"block_index": 0})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "my_data" in text
        assert "line_199" in text  # Full code, not truncated
        assert "200 lines" in text

    def test_get_block_code_invalid_index(self):
        """get_block_code with invalid index should return error."""
        mock_block = self._make_mock_with_code("x = 1")
        self._make_mock_env([mock_block])

        result = self.registry.execute("get_block_code", {"block_index": 5})
        assert "error" in result
        assert "out of range" in result["error"]

    def test_get_block_code_uses_focused_when_no_index(self):
        """get_block_code without block_index should use focused block."""
        code = "x = 42\ny = 10"
        mock_block = self._make_mock_with_code(code, name="focused_block")
        self._make_mock_env([mock_block])

        result = self.registry.execute("get_block_code", {})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "focused_block" in text
        assert "x = 42" in text

    def test_search_in_code_finds_matches(self):
        """search_in_code should find matching lines across blocks."""
        block1 = self._make_mock_with_code("import pandas as pd\ndf = pd.read_csv('data.csv')")
        block2 = self._make_mock_with_code("SELECT * FROM vendas\nWHERE valor > 100", language="sql")
        self._make_mock_env([block1, block2])

        result = self.registry.execute("search_in_code", {"query": "pandas"})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "1 matches" in text or "1 match" in text
        assert "test_block" in text or "Block 0" in text

    def test_search_in_code_case_insensitive(self):
        """search_in_code should be case-insensitive."""
        block = self._make_mock_with_code("SELECT * FROM Vendas")
        self._make_mock_env([block])

        result = self.registry.execute("search_in_code", {"query": "vendas"})

        assert "content" in result
        assert "1 match" in result["content"][0]["text"]

    def test_search_in_code_no_matches(self):
        """search_in_code with no matches should inform the user."""
        block = self._make_mock_with_code("x = 1")
        self._make_mock_env([block])

        result = self.registry.execute("search_in_code", {"query": "nonexistent"})

        assert "content" in result
        assert "No matches" in result["content"][0]["text"]

    def test_search_in_code_empty_query(self):
        """search_in_code with empty query should return error."""
        mock_mw = MagicMock()
        self.registry.set_main_window(mock_mw)

        result = self.registry.execute("search_in_code", {"query": ""})
        assert "error" in result

    def test_get_context_includes_block_name(self):
        """get_context should include block name in block info."""
        mock_session = MagicMock()
        mock_session.session_id = "sess1"
        mock_session.title = "Script 1"
        mock_session.connection_name = ""
        mock_session.is_connected = False

        mock_block = MagicMock()
        mock_block.get_language.return_value = "sql"
        mock_block.get_code.return_value = "SELECT 1"
        mock_block.get_block_name.return_value = "vendas"

        mock_editor = MagicMock(spec=["add_block", "blocks", "focused_block"])
        mock_editor.blocks = [mock_block]
        mock_editor.focused_block = mock_block

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("get_context", {})

        assert "content" in result
        context = json.loads(result["content"][0]["text"])
        assert context["blocks"][0]["name"] == "vendas"

    def test_run_silent_python_basic(self):
        """run_silent_python should execute code and return output."""
        mock_widget = MagicMock()
        mock_widget.namespace = {"x": 10}
        mock_widget.editor = MagicMock()

        mock_session = MagicMock()
        mock_session.namespace = {"x": 10}
        mock_session.update_namespace = MagicMock()

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("run_silent_python", {"code": "print(x + 5)"})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "15" in text

    def test_run_silent_python_error(self):
        """run_silent_python should capture errors."""
        mock_widget = MagicMock()
        mock_widget.namespace = {}
        mock_widget.editor = MagicMock()

        mock_session = MagicMock()
        mock_session.namespace = {}

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("run_silent_python", {"code": "1/0"})

        assert "error" in result
        assert "ZeroDivisionError" in result["error"]

    def test_run_silent_python_missing_code(self):
        """run_silent_python without code should error."""
        mock_mw = MagicMock()
        self.registry.set_main_window(mock_mw)

        result = self.registry.execute("run_silent_python", {})
        assert "error" in result

    def test_new_tools_are_registered(self):
        """New tools should appear in tools list."""
        tools = self.registry.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "edit_block_lines" in tool_names
        assert "get_block_code" in tool_names
        assert "inspect_block" in tool_names
        assert "search_in_code" in tool_names
        assert "run_silent_python" in tool_names
        assert "run_silent_query" in tool_names
        assert "write_and_run" in tool_names

    def test_inspect_block_returns_structure(self):
        html_block = self._make_mock_with_code(
            'html = """<div id="calendarGrid" class="calendar-panel">'
            '<script>function renderCalendar(){}</script>"""',
            "python",
            "calendario",
        )
        self._make_mock_env([html_block])

        result = self.registry.execute("inspect_block", {"block_name": "calendario"})
        assert "content" in result
        text = result["content"][0]["text"]
        assert "calendarGrid" in text
        assert "renderCalendar" in text
        assert "calendar-panel" in text

    def test_get_block_code_around_anchor(self):
        lines = [f"line_{i} = {i}" for i in range(1, 120)]
        lines[50] = "function updateSummary() { return 1; }"
        code = "\n".join(lines)
        block = self._make_mock_with_code(code, "python", "calendario")
        self._make_mock_env([block])

        result = self.registry.execute(
            "get_block_code",
            {"block_name": "calendario", "around": "updateSummary", "context_lines": 5},
        )
        assert "content" in result
        text = result["content"][0]["text"]
        assert "updateSummary" in text
        assert "line_1" not in text

    def test_duplicate_tool_calls_are_deduplicated(self):
        block = self._make_mock_with_code("x = 1", "python", "analise")
        self._make_mock_env([block])

        args = {"block_name": "analise"}
        first = self.registry.execute("get_block_code", args)
        second = self.registry.execute("get_block_code", args)
        assert first == second

    # === Tests for _resolve_block (block_name support) ===

    def test_resolve_block_by_name(self):
        """Tools should resolve blocks by name (case-insensitive)."""
        block1 = self._make_mock_with_code("SELECT 1", "sql", "vendas")
        block2 = self._make_mock_with_code("SELECT 2", "sql", "clientes")
        self._make_mock_env([block1, block2])

        result = self.registry.execute("get_block_code", {"block_name": "clientes"})
        assert "content" in result
        assert "SELECT 2" in result["content"][0]["text"]

    def test_resolve_block_by_name_case_insensitive(self):
        """Block name resolution should be case-insensitive."""
        block = self._make_mock_with_code("SELECT * FROM sales", "sql", "Vendas")
        self._make_mock_env([block])

        result = self.registry.execute("get_block_code", {"block_name": "VENDAS"})
        assert "content" in result
        assert "SELECT * FROM sales" in result["content"][0]["text"]

    def test_resolve_block_by_name_not_found(self):
        """Resolving a non-existent block name should return error with available blocks."""
        block = self._make_mock_with_code("x = 1", "python", "analise")
        self._make_mock_env([block])

        result = self.registry.execute("get_block_code", {"block_name": "inexistente"})
        assert "error" in result
        assert "analise" in result["error"]

    def test_resolve_block_by_index_fallback(self):
        """When block_name is not given, block_index should still work."""
        block1 = self._make_mock_with_code("code_a", "python", "a")
        block2 = self._make_mock_with_code("code_b", "python", "b")
        self._make_mock_env([block1, block2])

        result = self.registry.execute("get_block_code", {"block_index": 1})
        assert "content" in result
        assert "code_b" in result["content"][0]["text"]

    def test_edit_block_by_name(self):
        """edit_block should work with block_name."""
        block = self._make_mock_with_code("old code", "python", "transformacao")
        self._make_mock_env([block])

        result = self.registry.execute("edit_block", {
            "block_name": "transformacao",
            "code": "new code",
        })
        assert "content" in result
        assert "transformacao" in result["content"][0]["text"]
        block.set_code.assert_called_once_with("new code")

    def test_edit_block_lines_by_name(self):
        """edit_block_lines should work with block_name."""
        code = "line1\nline2\nline3"
        block = self._make_mock_with_code(code, "python", "grafico")
        self._make_mock_env([block])

        result = self.registry.execute("edit_block_lines", {
            "block_name": "grafico",
            "start_line": 2,
            "end_line": 2,
            "new_code": "replaced",
            "mode": "replace",
        })
        assert "content" in result
        assert "grafico" in result["content"][0]["text"]
        new_code = block.set_code.call_args[0][0]
        assert new_code == "line1\nreplaced\nline3"

    def test_execute_block_by_name(self):
        """execute_block should work with block_name."""
        block = self._make_mock_with_code("print('hi')", "python", "output")
        block._is_running = False
        editor = self._make_mock_env([block])
        editor.execute_block = MagicMock()

        result = self.registry.execute("execute_block", {"block_name": "output"})
        assert "content" in result
        editor.execute_block.assert_called_once_with(block)

    def test_get_context_includes_block_map(self):
        """get_context should include block_map for quick name->index lookup."""
        mock_session = MagicMock()
        mock_session.session_id = "sess1"
        mock_session.title = "Test"
        mock_session.connection_name = ""
        mock_session.is_connected = False

        block1 = self._make_mock_with_code("SELECT 1", "sql", "vendas")
        block2 = self._make_mock_with_code("x = 1", "python", "analise")

        mock_editor = MagicMock(spec=["add_block", "blocks", "focused_block"])
        mock_editor.blocks = [block1, block2]
        mock_editor.focused_block = block1

        mock_widget = MagicMock(spec=["editor"])
        mock_widget.editor = mock_editor

        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = mock_session
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget

        self.registry.set_main_window(mock_mw)
        result = self.registry.execute("get_context", {})

        context = json.loads(result["content"][0]["text"])
        assert "block_map" in context
        assert context["block_map"]["vendas"] == 0
        assert context["block_map"]["analise"] == 1
        assert context["total_blocks"] == 2

    def test_list_visualizations_uses_results_viewer(self):
        """list_visualizations should return the ResultsViewer payload as JSON."""
        mock_viewer = MagicMock()
        mock_viewer.list_visualizations.return_value = {
            "visualizations": [],
            "sources": [{"label": "df", "columns": ["month", "sales"]}],
        }
        mock_mw = MagicMock()
        mock_mw.global_results_viewer = mock_viewer
        self.registry.set_main_window(mock_mw)

        result = self.registry.execute("list_visualizations", {})

        assert "content" in result
        payload = json.loads(result["content"][0]["text"])
        assert payload["sources"][0]["columns"] == ["month", "sales"]
        mock_viewer.list_visualizations.assert_called_once_with()

    def test_create_and_edit_visualization_call_results_viewer(self):
        """create_visualization and edit_visualization should delegate to ResultsViewer."""
        mock_viewer = MagicMock()
        mock_viewer.create_visualization.return_value = {"index": 0, "config": {"type": "bar"}}
        mock_viewer.update_visualization.return_value = {"index": 0, "config": {"type": "line"}}
        mock_mw = MagicMock()
        mock_mw.global_results_viewer = mock_viewer
        self.registry.set_main_window(mock_mw)

        created = self.registry.execute("create_visualization", {"config": {"type": "bar"}})
        edited = self.registry.execute("edit_visualization", {"chart_index": 0, "config": {"type": "line"}})

        assert json.loads(created["content"][0]["text"])["config"]["type"] == "bar"
        assert json.loads(edited["content"][0]["text"])["config"]["type"] == "line"
        mock_viewer.create_visualization.assert_called_once_with({"type": "bar"})
        mock_viewer.update_visualization.assert_called_once_with(0, {"type": "line"})

    def test_export_visualization_requires_chart_index_and_path(self):
        """export_visualization should validate required arguments before delegation."""
        mock_viewer = MagicMock()
        mock_mw = MagicMock()
        mock_mw.global_results_viewer = mock_viewer
        self.registry.set_main_window(mock_mw)

        missing_index = self.registry.execute("export_visualization", {"file_path": "chart.png"})
        missing_path = self.registry.execute("export_visualization", {"chart_index": 0})

        assert "chart_index" in missing_index["error"]
        assert "file_path" in missing_path["error"]
        mock_viewer.export_visualization.assert_not_called()


class TestCopilotModelMetadata:
    """Tests for Copilot model normalization and reasoning effort support."""

    def test_normalize_models_deduplicates_and_keeps_capabilities(self):
        from src.services.copilot.copilot_models import normalize_models

        models = normalize_models([
            {"id": "o3", "name": "o3", "supports_reasoning_effort": True, "multiplier": 10},
            {"id": "o3", "name": "duplicate"},
        ])

        assert len(models) == 1
        assert models[0]["id"] == "o3"
        assert models[0]["supports_reasoning_effort"] is True
        assert models[0]["multiplier"] == 10.0

    def test_reasoning_effort_aliases_and_model_support(self):
        from src.services.copilot.copilot_models import (
            model_supports_reasoning_effort,
            normalize_reasoning_effort,
        )

        assert normalize_reasoning_effort("medium-high") == "high"
        assert normalize_reasoning_effort("x-high") == "xhigh"
        assert model_supports_reasoning_effort([], "o4-mini") is True
        assert model_supports_reasoning_effort([], "gpt-4o") is False

    def test_usage_snapshot_for_model_reports_multiplier_without_quota(self):
        from src.services.copilot.copilot_models import fallback_models, usage_snapshot_for_model

        snapshot = usage_snapshot_for_model(fallback_models(), "o3")

        assert snapshot["available"] is False
        assert snapshot["model_id"] == "o3"
        assert snapshot["multiplier"] > 1
        assert "subscription_url" in snapshot

    def test_normalize_model_reads_sdk_reasoning_metadata(self):
        from dataclasses import dataclass

        from src.services.copilot.copilot_models import normalize_models

        @dataclass
        class Supports:
            reasoning_effort: bool

        @dataclass
        class Capabilities:
            supports: Supports

        @dataclass
        class Billing:
            multiplier: float

        @dataclass
        class SDKModel:
            id: str
            name: str
            capabilities: Capabilities
            billing: Billing
            supported_reasoning_efforts: list
            default_reasoning_effort: str

        models = normalize_models([
            SDKModel(
                id="claude-sonnet-4.5",
                name="Claude Sonnet 4.5",
                capabilities=Capabilities(Supports(reasoning_effort=True)),
                billing=Billing(multiplier=1.5),
                supported_reasoning_efforts=["low", "medium"],
                default_reasoning_effort="medium",
            )
        ])

        assert models[0]["supports_reasoning_effort"] is True
        assert models[0]["supported_reasoning_efforts"] == ["low", "medium"]
        assert models[0]["default_reasoning_effort"] == "medium"
        assert models[0]["multiplier"] == 1.5

    def test_parse_copilot_cli_version(self):
        from src.services.copilot.copilot_client_sdk import _parse_copilot_cli_version

        assert _parse_copilot_cli_version("GitHub Copilot CLI 1.0.36-0.") == (1, 0, 36)
        assert _parse_copilot_cli_version("GitHub Copilot CLI 0.0.411.") == (0, 0, 411)

    def test_get_sdk_options_uses_subprocess_config(self, monkeypatch):
        from src.services.copilot.copilot_client_sdk import _get_sdk_options

        try:
            from copilot import SubprocessConfig
        except ImportError:
            pytest.skip("github-copilot-sdk not installed")

        monkeypatch.setattr(
            "src.services.copilot.copilot_client_sdk._pick_newest_copilot_cli",
            lambda: (r"C:\copilot\copilot.exe", (1, 0, 36)),
        )
        options = _get_sdk_options()
        assert isinstance(options, SubprocessConfig)
        assert options.cli_path == r"C:\copilot\copilot.exe"

    def test_try_import_sdk_supports_copilot_tools_module(self):
        from src.services.copilot.copilot_client_sdk import _try_import_sdk

        SDKClient, SDKTool, EventType, import_err = _try_import_sdk()
        if import_err:
            pytest.skip(f"github-copilot-sdk not installed: {import_err}")

        assert SDKClient is not None
        assert SDKTool is not None
        assert EventType is not None
        assert SDKTool.__module__.endswith("tools") or SDKTool.__name__ == "Tool"

    def test_session_send_expects_plain_prompt_string(self):
        import inspect

        try:
            from copilot.session import CopilotSession
        except ImportError:
            pytest.skip("github-copilot-sdk not installed")

        prompt_param = inspect.signature(CopilotSession.send).parameters.get("prompt")
        assert prompt_param is not None
        assert prompt_param.annotation in (str, "str", inspect._empty)

    def test_sdk_create_session_uses_keyword_only_api(self):
        import asyncio
        import inspect

        from src.services.copilot.copilot_client_sdk import _sdk_create_session

        try:
            from copilot import CopilotClient
            from copilot.session import PermissionHandler
        except ImportError:
            pytest.skip("github-copilot-sdk not installed")

        captured = {}

        class FakeClient:
            async def create_session(self, **kwargs):
                captured.update(kwargs)
                return object()

        asyncio.run(_sdk_create_session(
            FakeClient(),
            model="gpt-4o",
            streaming=True,
            system_message="Be helpful.",
            reasoning_effort="medium",
            disabled_skills=["shell"],
            our_tool_names={"run_query"},
        ))

        assert captured["model"] == "gpt-4o"
        assert captured["streaming"] is True
        assert captured["on_permission_request"] is PermissionHandler.approve_all
        assert captured["system_message"] == {"mode": "append", "content": "Be helpful."}
        assert captured["reasoning_effort"] == "medium"
        assert captured["disabled_skills"] == ["shell"]
        assert "hooks" in captured

        sig = inspect.signature(CopilotClient.create_session)
        for name in sig.parameters:
            if name == "self":
                continue
            param = sig.parameters[name]
            assert param.kind != inspect.Parameter.POSITIONAL_ONLY

    def test_usage_snapshot_from_quota_reports_real_premium_usage(self):
        from dataclasses import dataclass

        from src.services.copilot.copilot_models import fallback_models, usage_snapshot_from_quota

        @dataclass
        class Quota:
            entitlement_requests: float
            used_requests: float
            remaining_percentage: float
            overage: float
            reset_date: str
            overage_allowed_with_exhausted_quota: bool = False

        @dataclass
        class QuotaResult:
            quota_snapshots: dict

        result = QuotaResult({
            "chat": Quota(1000, 10, 99, 0, "2026-06-01"),
            "premium_interactions": Quota(300, 42, 86, 0, "2026-06-01"),
        })

        snapshot = usage_snapshot_from_quota(result, fallback_models(), "o3")

        assert snapshot["available"] is True
        assert snapshot["quota_key"] == "premium_interactions"
        assert snapshot["used"] == 42
        assert snapshot["total"] == 300
        assert snapshot["remaining_percentage"] == 86
        assert snapshot["reset_date"] == "2026-06-01"

    def test_usage_snapshot_from_event_reports_partial_usage(self):
        from dataclasses import dataclass

        from src.services.copilot.copilot_models import fallback_models, usage_snapshot_from_event

        @dataclass
        class UsageEvent:
            model: str
            total_premium_requests: float
            input_tokens: float
            output_tokens: float
            cache_read_tokens: float = 0
            cache_write_tokens: float = 0

        snapshot = usage_snapshot_from_event(
            UsageEvent("o3", 1.5, 1200, 300),
            fallback_models(),
            "o3",
        )

        assert snapshot["available"] is True
        assert snapshot["source"] == "session_event"
        assert snapshot["status"] == "partial"
        assert snapshot["used"] == 1.5
        assert snapshot["input_tokens"] == 1200


# ==================== MCPServer Tests ====================


class TestMCPServer:
    """Tests for MCP server JSON-RPC message handling."""

    def setup_method(self):
        from src.services.copilot.mcp_server import MCPServer
        self.server = MCPServer()
        self.server.set_main_window(MagicMock())

    def test_handle_initialize(self):
        """Initialize request should return protocol version and capabilities."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        response = self.server.handle_message(msg)
        data = json.loads(response)
        assert data["id"] == 1
        assert "protocolVersion" in data["result"]
        assert "capabilities" in data["result"]
        assert data["result"]["serverInfo"]["name"] == "datapyn-mcp"

    def test_handle_tools_list(self):
        """tools/list should return all registered tools."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = self.server.handle_message(msg)
        data = json.loads(response)
        assert "tools" in data["result"]
        assert len(data["result"]["tools"]) >= 8

    def test_handle_tools_call(self):
        """tools/call should execute the specified tool."""
        mock_session = MagicMock()
        mock_session.title = "New"
        mock_session.session_id = "x"
        mock_mw = MagicMock()
        mock_mw.session_manager.create_session.return_value = mock_session
        self.server.set_main_window(mock_mw)

        msg = json.dumps({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "create_tab", "arguments": {"title": "Test"}},
        })
        response = self.server.handle_message(msg)
        data = json.loads(response)
        assert "content" in data["result"]

    def test_handle_invalid_json(self):
        """Invalid JSON should return parse error."""
        response = self.server.handle_message("not json")
        data = json.loads(response)
        assert data["error"]["code"] == -32700

    def test_handle_unknown_method(self):
        """Unknown method should return method not found error."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 4, "method": "unknown/method", "params": {}})
        response = self.server.handle_message(msg)
        data = json.loads(response)
        assert data["error"]["code"] == -32601

    def test_handle_notification_returns_none(self):
        """Notifications (no id) should return None."""
        msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        response = self.server.handle_message(msg)
        assert response is None

    def test_handle_ping(self):
        """Ping should succeed."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}})
        response = self.server.handle_message(msg)
        data = json.loads(response)
        assert data["id"] == 5
        assert "result" in data


# ==================== CopilotClient Tests ====================


class TestCopilotClient:
    """Tests for CopilotClient authentication and chat."""

    def setup_method(self):
        # Clear any saved tokens before each test
        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

        from src.services.copilot.copilot_client import CopilotClient
        self.client = CopilotClient()

    def teardown_method(self):
        self.client.cleanup()
        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

    def test_initial_state(self):
        """Client should start unauthenticated."""
        assert self.client.is_authenticated is False

    def test_default_model(self):
        """Default model should be gpt-4o."""
        assert self.client.model == "gpt-4o"

    def test_model_setter(self):
        """Model should be settable."""
        self.client.model = "claude-3.5-sonnet"
        assert self.client.model == "claude-3.5-sonnet"

    def test_available_models(self):
        """Should return a list of available models."""
        models = self.client.available_models()
        assert len(models) >= 4
        model_ids = [m["id"] for m in models]
        assert "gpt-4o" in model_ids
        assert "gpt-4o-mini" in model_ids

    def test_sign_out_clears_tokens(self):
        """sign_out should clear all tokens."""
        self.client._github_token = "test_token"
        self.client._copilot_token = "test_copilot"
        self.client.sign_out()
        assert self.client.is_authenticated is False
        assert self.client._copilot_token == ""

    def test_send_chat_without_auth_emits_error(self, qtbot):
        """Sending chat without auth should emit error."""
        with qtbot.waitSignal(self.client.chat_error, timeout=2000):
            self.client.send_chat([{"role": "user", "content": "hello"}])


# ==================== PyniaChatPanel Tests ====================


class TestPyniaChatPanel:
    """Tests for the PyniaChatPanel UI component."""

    class FakeCopilotClient(QObject):
        chat_response_chunk = pyqtSignal(str)
        chat_response_complete = pyqtSignal(str)
        chat_error = pyqtSignal(str)
        authenticated = pyqtSignal(str)
        auth_failed = pyqtSignal(str)
        auth_started = pyqtSignal(str)
        gh_not_found = pyqtSignal()
        license_warning = pyqtSignal(str)
        tool_called = pyqtSignal(str, dict, str)
        tool_result = pyqtSignal(str, str, str)
        thinking = pyqtSignal(str)
        models_changed = pyqtSignal(list)

        def __init__(self):
            super().__init__()
            self.system_message = ""
            self.is_authenticated = True
            self.sent_messages = None
            self.sent_attachments = None
            self.cancel_called = False

        def send_chat(self, messages, attachments=None):
            self.sent_messages = messages
            self.sent_attachments = attachments

        def cancel(self):
            self.cancel_called = True

        def available_models(self):
            return []

        @property
        def model(self):
            return "gpt-4o"

        @model.setter
        def model(self, value):
            self._model = value

    def _make_panel_with_fake_client(self, qtbot):
        from src.ui.components.copilot_chat_panel import PyniaChatPanel

        client = self.FakeCopilotClient()
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        panel.set_copilot_client(client)

        registry = MagicMock()
        registry.list_tools.return_value = []
        registry._main_window = None
        server = MagicMock()
        server.tool_registry = registry
        panel.set_mcp_server(server)
        return panel, client, registry

    def test_panel_creates(self, qtbot):
        """Panel should be created without errors."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        assert panel is not None

    def test_panel_has_input(self, qtbot):
        """Panel should have an input widget."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        assert panel._input is not None

    def test_panel_has_send_button(self, qtbot):
        """Panel should have a send button."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        assert panel._send_btn is not None

    def test_panel_has_model_combo(self, qtbot):
        """Panel should have model selection combo."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        assert panel._model_combo.count() >= 4

    def test_panel_mode_is_agent_only(self, qtbot):
        """Panel should always use agent mode (mode_combo removed)."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        # Mode combo was removed - always agent mode for tool support
        assert panel._mode_combo is None

    def test_panel_has_auth_button(self, qtbot):
        """Panel should have auth button."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        assert panel._auth_btn is not None

    def test_clear_chat(self, qtbot):
        """clear_chat should remove all messages."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        panel._add_message("user", "Hello")
        panel._add_message("assistant", "Hi there")
        assert len(panel._messages) == 2
        panel.clear_chat()
        assert len(panel._messages) == 0

    def test_add_message(self, qtbot):
        """_add_message should add to messages list."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        panel._add_message("user", "Test message")
        assert len(panel._messages) == 1
        assert panel._messages[0]["role"] == "user"
        assert panel._messages[0]["content"] == "Test message"

    def test_set_copilot_client(self, qtbot):
        """Setting a copilot client should connect signals."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        from src.services.copilot.copilot_client import CopilotClient

        # Clear settings first
        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        client = CopilotClient()
        panel.set_copilot_client(client)
        assert panel._agent_client is client
        client.cleanup()

    def test_send_without_text_does_nothing(self, qtbot):
        """Pressing send with empty input should not add a message."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        panel = PyniaChatPanel()
        qtbot.addWidget(panel)
        panel._input.clear()
        panel._on_send()
        assert len(panel._messages) == 0

    def test_send_passes_static_system_and_contextual_user_prompt(self, qtbot):
        """Sending should pass static rules separately from hidden turn context."""
        panel, client, _ = self._make_panel_with_fake_client(qtbot)
        panel._current_tab_id = "tab_green"
        panel._current_tab_name = "Green"

        panel._input.setPlainText("lista os produtos da base green")
        with patch.object(panel, '_run_chat_js'):
            panel._on_send()

        assert client.sent_messages is not None
        assert client.sent_messages[0]["role"] == "system"
        assert "SILENT vs VISIBLE" in client.system_message
        assert "lista os produtos da base green" in client.sent_messages[-1]["content"]
        assert '"target_session_id": "tab_green"' in client.sent_messages[-1]["content"]
        assert panel._messages[-1]["content"] == "lista os produtos da base green"

    def test_send_pins_active_tab_at_submit_time(self, qtbot):
        """Tool calls should target the tab active when the user sends the prompt."""
        panel, _, registry = self._make_panel_with_fake_client(qtbot)
        panel._current_tab_id = "tab_a"

        panel._input.setPlainText("crie a analise")
        with patch.object(panel, '_run_chat_js'):
            panel._on_send()

        registry.pin_session.assert_called_once_with("tab_a")
        assert panel._active_tool_target_id == "tab_a"

    def test_stop_cancels_client_and_unpins_target(self, qtbot):
        """Stop should cancel the client and clear the pinned tool target."""
        panel, client, registry = self._make_panel_with_fake_client(qtbot)
        panel._active_tool_target_id = "tab_a"
        editor = MagicMock()
        connector = MagicMock()
        widget = MagicMock()
        widget.editor = editor
        widget.session.connector = connector
        registry._get_active_session_widget.return_value = widget

        panel._on_stop()

        assert client.cancel_called is True
        editor.cancel_all_executions.assert_called_once()
        connector.cancel_query.assert_not_called()
        registry.unpin_session.assert_called_once()
        assert panel._active_tool_target_id is None

    def test_model_change_updates_client(self, qtbot):
        """Changing the model combo should update the client."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        from src.services.copilot.copilot_client import CopilotClient

        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

        client = CopilotClient()
        panel = PyniaChatPanel(copilot_client=client)
        panel.set_copilot_client(client)
        qtbot.addWidget(panel)

        # Select the second model
        panel._model_combo.setCurrentIndex(1)
        model_id = panel._model_combo.currentData()
        assert client.model == model_id
        client.cleanup()

    def test_delete_session_removes_from_list(self, qtbot):
        """_delete_session should remove the session from saved sessions."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = PyniaChatPanel()
        qtbot.addWidget(panel)

        # Add some test sessions
        test_sessions = [
            {"id": "session1", "title": "Test 1", "messages": [], "timestamp": "2026-01-01"},
            {"id": "session2", "title": "Test 2", "messages": [], "timestamp": "2026-01-02"},
            {"id": "session3", "title": "Test 3", "messages": [], "timestamp": "2026-01-03"},
        ]
        panel._settings.setValue("sessions", json.dumps(test_sessions))

        # Delete session2
        menu = QMenu()
        panel._delete_session("session2", menu)

        # Verify session2 is gone
        sessions = panel._get_sessions_list()
        session_ids = [s["id"] for s in sessions]
        assert "session2" not in session_ids
        assert "session1" in session_ids
        assert "session3" in session_ids

    def test_delete_session_clears_current_if_deleted(self, qtbot):
        """_delete_session should clear current session if it's the one deleted."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = PyniaChatPanel()
        qtbot.addWidget(panel)

        # Setup: current session is session1
        panel._current_session_id = "session1"
        test_sessions = [
            {"id": "session1", "title": "Test 1", "messages": [], "timestamp": "2026-01-01"},
        ]
        panel._settings.setValue("sessions", json.dumps(test_sessions))

        # Delete the current session
        menu = QMenu()
        panel._delete_session("session1", menu)

        # Verify current_session_id is cleared
        assert panel._current_session_id == ""

    def test_delete_session_keeps_current_if_different(self, qtbot):
        """_delete_session should not change current session if deleting another."""
        from src.ui.components.copilot_chat_panel import PyniaChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = PyniaChatPanel()
        qtbot.addWidget(panel)

        # Setup: current session is session1, deleting session2
        panel._current_session_id = "session1"
        test_sessions = [
            {"id": "session1", "title": "Test 1", "messages": [], "timestamp": "2026-01-01"},
            {"id": "session2", "title": "Test 2", "messages": [], "timestamp": "2026-01-02"},
        ]
        panel._settings.setValue("sessions", json.dumps(test_sessions))

        # Delete session2 (not the current one)
        menu = QMenu()
        panel._delete_session("session2", menu)

        # Verify current_session_id is unchanged
        assert panel._current_session_id == "session1"


# ChatMessageWidget tests removed - class was removed in dead code cleanup
# (chat rendering now uses WebView exclusively)


class TestThreadSafeToolExecutor:
    """Ensure MCP tools dispatch correctly from background threads."""

    def test_dispatches_from_background_thread(self, qapp):
        import threading
        import time
        from unittest.mock import MagicMock

        from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor
        from src.services.copilot.mcp_tools import MCPToolRegistry

        registry = MCPToolRegistry()
        mock_widget = MagicMock()
        mock_widget.editor = MagicMock()
        mock_widget.editor.blocks = []
        mock_mw = MagicMock()
        mock_mw.session_manager.focused_session = MagicMock()
        mock_mw.session_tabs.currentIndex.return_value = 0
        mock_mw.session_tabs.widget.return_value = mock_widget
        registry.set_main_window(mock_mw)

        executor = ThreadSafeToolExecutor(registry, parent=qapp)
        result_holder = {}
        errors = []

        def run_in_thread():
            try:
                result_holder["text"] = executor.execute("list_blocks", {})
            except Exception as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        deadline = time.time() + 5
        while thread.is_alive() and time.time() < deadline:
            qapp.processEvents()
            thread.join(0.05)

        assert not errors, errors
        assert "text" in result_holder
        assert "Could not run" not in result_holder["text"]
