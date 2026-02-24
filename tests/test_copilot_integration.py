"""
Tests for Copilot MCP tools, MCP server, and CopilotClient.
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QSettings

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


# ==================== CopilotChatPanel Tests ====================


class TestCopilotChatPanel:
    """Tests for the CopilotChatPanel UI component."""

    def test_panel_creates(self, qtbot):
        """Panel should be created without errors."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        assert panel is not None

    def test_panel_has_input(self, qtbot):
        """Panel should have an input widget."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        assert panel._input is not None

    def test_panel_has_send_button(self, qtbot):
        """Panel should have a send button."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        assert panel._send_btn is not None

    def test_panel_has_model_combo(self, qtbot):
        """Panel should have model selection combo."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        assert panel._model_combo.count() >= 4

    def test_panel_mode_is_agent_only(self, qtbot):
        """Panel should always use agent mode (mode_combo removed)."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        # Mode combo was removed - always agent mode for tool support
        assert panel._mode_combo is None

    def test_panel_has_auth_button(self, qtbot):
        """Panel should have auth button."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        assert panel._auth_btn is not None

    def test_clear_chat(self, qtbot):
        """clear_chat should remove all messages."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        panel._add_message("user", "Hello")
        panel._add_message("assistant", "Hi there")
        assert len(panel._messages) == 2
        panel.clear_chat()
        assert len(panel._messages) == 0

    def test_add_message(self, qtbot):
        """_add_message should add to messages list."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        panel._add_message("user", "Test message")
        assert len(panel._messages) == 1
        assert panel._messages[0]["role"] == "user"
        assert panel._messages[0]["content"] == "Test message"

    def test_set_copilot_client(self, qtbot):
        """Setting a copilot client should connect signals."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        from src.services.copilot.copilot_client import CopilotClient

        # Clear settings first
        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        client = CopilotClient()
        panel.set_copilot_client(client)
        assert panel._copilot_client is client
        client.cleanup()

    def test_send_without_text_does_nothing(self, qtbot):
        """Pressing send with empty input should not add a message."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        panel = CopilotChatPanel()
        qtbot.addWidget(panel)
        panel._input.clear()
        panel._on_send()
        assert len(panel._messages) == 0

    def test_model_change_updates_client(self, qtbot):
        """Changing the model combo should update the client."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        from src.services.copilot.copilot_client import CopilotClient

        settings = QSettings("DataPyn", "CopilotAuth")
        settings.clear()
        settings.sync()

        client = CopilotClient()
        panel = CopilotChatPanel(copilot_client=client)
        panel.set_copilot_client(client)
        qtbot.addWidget(panel)

        # Select the second model
        panel._model_combo.setCurrentIndex(1)
        model_id = panel._model_combo.currentData()
        assert client.model == model_id
        client.cleanup()

    def test_delete_session_removes_from_list(self, qtbot):
        """_delete_session should remove the session from saved sessions."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = CopilotChatPanel()
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
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = CopilotChatPanel()
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
        from src.ui.components.copilot_chat_panel import CopilotChatPanel
        from PyQt6.QtWidgets import QMenu

        panel = CopilotChatPanel()
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


# ==================== ChatMessageWidget Tests ====================


class TestChatMessageWidget:
    """Tests for individual chat message widgets."""

    def test_user_message(self, qtbot):
        """User messages should display correctly."""
        from src.ui.components.copilot_chat_panel import ChatMessageWidget
        widget = ChatMessageWidget("user", "Hello")
        qtbot.addWidget(widget)
        assert widget.role == "user"
        assert widget.content == "Hello"

    def test_assistant_message(self, qtbot):
        """Assistant messages should display correctly."""
        from src.ui.components.copilot_chat_panel import ChatMessageWidget
        widget = ChatMessageWidget("assistant", "Hi there!")
        qtbot.addWidget(widget)
        assert widget.role == "assistant"
        assert widget.content == "Hi there!"

    def test_append_content(self, qtbot):
        """append_content should update message text (streaming)."""
        from src.ui.components.copilot_chat_panel import ChatMessageWidget
        widget = ChatMessageWidget("assistant", "Hello")
        qtbot.addWidget(widget)
        widget.append_content(" World")
        assert widget.content == "Hello World"
