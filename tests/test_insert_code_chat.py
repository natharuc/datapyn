"""
Tests for the "Insert into Editor" feature in Copilot chat code blocks.
"""

import pytest
import json
from unittest.mock import MagicMock, patch, PropertyMock
from PyQt6.QtCore import pyqtSignal, QObject


class TestChatBridgeInsertCode:
    """Tests for ChatBridge.insertCode slot."""

    def test_bridge_has_insert_code_signal(self):
        """ChatBridge must have insert_code_requested signal."""
        from src.ui.components.copilot_chat_panel import ChatBridge

        bridge = ChatBridge()
        assert hasattr(bridge, "insert_code_requested")

    def test_insert_code_slot_emits_signal(self, qtbot):
        """insertCode slot must emit insert_code_requested with the code."""
        from src.ui.components.copilot_chat_panel import ChatBridge

        bridge = ChatBridge()
        received = []
        bridge.insert_code_requested.connect(lambda code: received.append(code))

        bridge.insertCode("SELECT * FROM users;")

        assert len(received) == 1
        assert received[0] == "SELECT * FROM users;"

    def test_insert_code_preserves_multiline(self, qtbot):
        """Multiline code must be passed through intact."""
        from src.ui.components.copilot_chat_panel import ChatBridge

        bridge = ChatBridge()
        received = []
        bridge.insert_code_requested.connect(lambda code: received.append(code))

        code = "def hello():\n    print('world')\n\nhello()"
        bridge.insertCode(code)

        assert received[0] == code


class TestChatPanelInsertCodeSignal:
    """Tests for CopilotChatPanel.insert_code_requested signal propagation."""

    def test_panel_has_insert_code_signal(self):
        """CopilotChatPanel must expose insert_code_requested signal."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel

        assert hasattr(CopilotChatPanel, "insert_code_requested")

    @patch("src.ui.components.copilot_chat_panel.CopilotChatPanel._setup_ui")
    @patch("src.ui.components.copilot_chat_panel.CopilotChatPanel._connect_signals")
    @patch("src.ui.components.copilot_chat_panel.CopilotChatPanel._restore_last_session")
    def test_bridge_signal_propagates_to_panel(self, mock_restore, mock_signals, mock_ui, qtbot):
        """Bridge insert_code_requested must propagate to panel signal."""
        from src.ui.components.copilot_chat_panel import CopilotChatPanel, ChatBridge

        panel = CopilotChatPanel()
        qtbot.addWidget(panel)

        # Manually wire the bridge (since _setup_ui is mocked)
        panel._chat_bridge = ChatBridge(panel)
        panel._chat_bridge.insert_code_requested.connect(panel.insert_code_requested)

        received = []
        panel.insert_code_requested.connect(lambda code: received.append(code))

        panel._chat_bridge.insertCode("import pandas as pd")

        assert len(received) == 1
        assert received[0] == "import pandas as pd"


class TestInsertCodeTranslations:
    """Tests for translation keys used by the Insert button."""

    def test_en_us_has_insert_keys(self):
        """en-US.json must have copy/insert code translation keys."""
        with open("source/src/language/en-US.json", encoding="utf-8") as f:
            data = json.load(f)

        copilot = data.get("copilot", {})
        assert "copy_code" in copilot
        assert "copied_code" in copilot
        assert "insert_code" in copilot
        assert "inserted_code" in copilot

    def test_pt_br_has_insert_keys(self):
        """pt-BR.json must have copy/insert code translation keys."""
        with open("source/src/language/pt-BR.json", encoding="utf-8") as f:
            data = json.load(f)

        copilot = data.get("copilot", {})
        assert "copy_code" in copilot
        assert "copied_code" in copilot
        assert "insert_code" in copilot
        assert "inserted_code" in copilot


class TestMainWindowInsertCode:
    """Tests for _on_insert_code_from_chat in main window."""

    def test_insert_into_focused_block(self):
        """Code should be inserted into the focused block's editor."""
        from src.ui.main_window._copilot import CopilotMixin

        mixin = CopilotMixin()

        # Mock the chain: _get_current_session_widget -> widget.editor -> block.editor
        inner_editor = MagicMock()
        inner_editor.insert_text_at_cursor = MagicMock()

        block = MagicMock()
        block.editor = inner_editor

        editor = MagicMock()
        editor.get_last_focused_block.return_value = block

        widget = MagicMock()
        widget.editor = editor

        mixin._get_current_session_widget = MagicMock(return_value=widget)

        mixin._on_insert_code_from_chat("print('hello')")

        inner_editor.insert_text_at_cursor.assert_called_once_with("print('hello')")

    def test_insert_creates_new_block_when_none_focused(self):
        """If no block is focused, a new block should be created."""
        from src.ui.main_window._copilot import CopilotMixin

        mixin = CopilotMixin()

        inner_editor = MagicMock()
        inner_editor.insert_text_at_cursor = MagicMock()

        block = MagicMock()
        block.editor = inner_editor

        editor = MagicMock()
        # First call returns None (no focused block), second returns the new block
        editor.get_last_focused_block.side_effect = [None, block]
        editor.add_block = MagicMock()

        widget = MagicMock()
        widget.editor = editor

        mixin._get_current_session_widget = MagicMock(return_value=widget)

        mixin._on_insert_code_from_chat("x = 1")

        editor.add_block.assert_called_once()
        inner_editor.insert_text_at_cursor.assert_called_once_with("x = 1")

    def test_insert_noop_when_no_session(self):
        """Should not crash when there is no active session."""
        from src.ui.main_window._copilot import CopilotMixin

        mixin = CopilotMixin()
        mixin._get_current_session_widget = MagicMock(return_value=None)

        # Should not raise
        mixin._on_insert_code_from_chat("code")
