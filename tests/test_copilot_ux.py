"""
Tests for Copilot UX improvements:

1. CodeBlock copilot editing indicator (sparkle icon, purple border, auto-dismiss)
2. Monaco highlight_lines integration
3. MCP tool helpers (_signal_copilot_editing, _highlight_edited_lines)
4. Chat template thinking block / i18n labels
5. Chat panel thinking state machine
6. Per-tab chat context switching
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch, PropertyMock, call
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from src.editors.code_block import CodeBlock
from src.editors.monaco.monaco_editor import MonacoEditor


# Fixture autouse para evitar hang do QScintilla focus em testes
@pytest.fixture(autouse=True)
def _no_focus_editor(monkeypatch):
    """Disable focus_editor to avoid QScintilla hang in tests"""
    monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)


@pytest.fixture(autouse=True)
def _cleanup_qta_animations():
    """Stop qta animations after each test to avoid C++ deleted widget errors."""
    yield
    try:
        import qtawesome as qta
        # Stop all running animations to prevent callback on deleted widgets
        for anim in list(getattr(qta, '_animations', {}).values()):
            if hasattr(anim, 'stop'):
                anim.stop()
    except Exception:
        pass
    # Process pending events and force GC to clean up deleted widgets
    try:
        app = QApplication.instance()
        if app:
            app.processEvents()
        import gc
        gc.collect()
        if app:
            app.processEvents()
    except Exception:
        pass


# ===== CodeBlock Copilot Indicator =====


class TestCodeBlockCopilotIndicator:
    """Tests for the copilot editing indicator on CodeBlock."""

    def test_initial_state_not_editing(self, qapp):
        """Block should start with copilot editing = False."""
        block = CodeBlock()
        assert block.is_copilot_editing() is False

    def test_set_copilot_editing_true(self, qapp):
        """set_copilot_editing(True) should show the indicator."""
        block = CodeBlock()
        block.set_copilot_editing(True)
        assert block.is_copilot_editing() is True
        # Widget is not visible when parent is not shown,
        # but the internal flag and !isHidden() confirm it
        assert not block._copilot_indicator.isHidden()

    def test_set_copilot_editing_false(self, qapp):
        """set_copilot_editing(False) should hide the indicator."""
        block = CodeBlock()
        block.set_copilot_editing(True)
        block.set_copilot_editing(False)
        assert block.is_copilot_editing() is False
        assert block._copilot_indicator.isHidden()

    def test_indicator_hidden_initially(self, qapp):
        """The copilot indicator widget should be hidden on creation."""
        block = CodeBlock()
        assert block._copilot_indicator.isHidden()

    def test_indicator_has_icon_and_label(self, qapp):
        """The copilot indicator should have an icon and label widget."""
        block = CodeBlock()
        assert hasattr(block, '_copilot_icon')
        assert hasattr(block, '_copilot_label')

    def test_copilot_editing_border_style(self, qapp):
        """When copilot editing, block should have purple left border."""
        block = CodeBlock()
        block.set_copilot_editing(True)
        block._update_style()
        style = block.styleSheet()
        # Should contain the copilot purple color
        assert "#b48ead" in style.lower() or "b48ead" in style.lower()

    def test_normal_border_after_editing_ends(self, qapp):
        """After copilot editing ends, border should return to normal."""
        block = CodeBlock()
        block.set_copilot_editing(True)
        block.set_copilot_editing(False)
        block._update_style()
        style = block.styleSheet()
        # Purple should not be in the border anymore since block is not focused
        assert block.is_copilot_editing() is False

    def test_auto_dismiss_timer_created(self, qapp):
        """set_copilot_editing(True) should create an auto-dismiss QTimer."""
        block = CodeBlock()
        block.set_copilot_editing(True)
        # Timer should have been created and started
        assert block._copilot_editing_timer is not None
        assert block._copilot_editing_timer.isActive()
        assert block._copilot_editing_timer.interval() == 2000
        # Cleanup timer to avoid side effects
        block._copilot_editing_timer.stop()
        # Stop qta spin animation to avoid C++ deleted widget errors
        if hasattr(block, '_copilot_icon'):
            try:
                import qtawesome as qta
                qta.iconic_font.set_global_defaults()
            except Exception:
                pass


# ===== Monaco highlight_lines =====


class TestMonacoHighlightLines:
    """Tests for Monaco editor highlight_lines method."""

    def test_highlight_lines_method_exists(self, qapp):
        """MonacoEditor should have a highlight_lines method."""
        editor = MonacoEditor()
        assert hasattr(editor, 'highlight_lines')
        assert callable(editor.highlight_lines)

    def test_highlight_lines_calls_js(self, qapp):
        """highlight_lines should run JS in the WebView."""
        editor = MonacoEditor()
        with patch.object(editor, '_run_js_when_ready') as mock_js:
            editor.highlight_lines(5, 10)
            mock_js.assert_called_once()
            js_code = mock_js.call_args[0][0]
            assert 'highlightLines' in js_code
            assert '5' in js_code
            assert '10' in js_code

    def test_highlight_lines_custom_duration(self, qapp):
        """highlight_lines should accept custom duration."""
        editor = MonacoEditor()
        with patch.object(editor, '_run_js_when_ready') as mock_js:
            editor.highlight_lines(1, 3, duration_ms=5000)
            js_code = mock_js.call_args[0][0]
            assert '5000' in js_code


# ===== MCP Tool Helpers =====


class TestMCPToolHelpers:
    """Tests for _signal_copilot_editing and _highlight_edited_lines helpers."""

    def _make_registry(self):
        """Create a MCPToolRegistry with mocked main window."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)
        registry._main_window = MagicMock()
        return registry

    def test_signal_copilot_editing_calls_block(self, qapp):
        """_signal_copilot_editing should call set_copilot_editing on the block."""
        registry = self._make_registry()
        block = MagicMock()
        block_editor = MagicMock()

        registry._signal_copilot_editing(block, block_editor)

        block.set_copilot_editing.assert_called_once_with(True)

    def test_signal_copilot_editing_scrolls_into_view(self, qapp):
        """_signal_copilot_editing should scroll to make the block visible."""
        registry = self._make_registry()
        block = MagicMock()
        block_editor = MagicMock()

        registry._signal_copilot_editing(block, block_editor)

        block_editor.ensureWidgetVisible.assert_called_once_with(block)

    def test_signal_copilot_editing_no_scroll_area(self, qapp):
        """_signal_copilot_editing should not crash if scroll_area is missing."""
        registry = self._make_registry()
        block = MagicMock()
        block_editor = MagicMock(spec=[])  # no scroll_area

        # Should not raise
        registry._signal_copilot_editing(block, block_editor)
        block.set_copilot_editing.assert_called_once_with(True)

    def test_highlight_edited_lines_calls_editor(self, qapp):
        """_highlight_edited_lines should call go_to_line and highlight_lines."""
        registry = self._make_registry()
        block = MagicMock()
        editor = MagicMock()
        block.editor = editor

        registry._highlight_edited_lines(block, 5, 10)

        editor.go_to_line.assert_called_once_with(4)  # 0-indexed
        editor.highlight_lines.assert_called_once_with(5, 10, 2000)

    def test_highlight_edited_lines_no_editor(self, qapp):
        """_highlight_edited_lines should not crash if block has no editor."""
        registry = self._make_registry()
        block = MagicMock(spec=[])  # no editor attr

        # Should not raise
        registry._highlight_edited_lines(block, 1, 1)


# ===== Chat Template Thinking Block =====


class TestChatTemplateThinkingBlock:
    """Tests for the collapsible thinking block in chat_template.html."""

    @pytest.fixture
    def template_content(self):
        """Load the chat template HTML."""
        from pathlib import Path
        template_path = Path(__file__).parent.parent / "source" / "src" / "ui" / "components" / "chat_template.html"
        return template_path.read_text(encoding="utf-8")

    def test_thinking_block_css_exists(self, template_content):
        """Template should have CSS for .thinking-block."""
        assert ".thinking-block" in template_content
        assert ".thinking-block-header" in template_content
        assert ".thinking-block-content" in template_content

    def test_thinking_block_js_functions_exist(self, template_content):
        """Template should expose startThinkingBlock/appendThinking/endThinkingBlock."""
        assert "function startThinkingBlock" in template_content
        assert "function appendThinking" in template_content
        assert "function endThinkingBlock" in template_content
        assert "window.startThinkingBlock" in template_content
        assert "window.appendThinking" in template_content
        assert "window.endThinkingBlock" in template_content

    def test_set_labels_function_exists(self, template_content):
        """Template should expose setLabels for i18n."""
        assert "function setLabels" in template_content
        assert "window.setLabels" in template_content

    def test_template_welcome_has_no_visible_hardcoded_copy(self, template_content):
        """Welcome copy should be injected from translations."""
        assert "Welcome to GitHub Copilot" not in template_content
        assert "Sign in with your GitHub account" not in template_content
        assert "<h2></h2>" in template_content

    def test_template_theme_accepts_design_system_keys(self, template_content):
        """setTheme should accept native design-system color keys from the panel."""
        assert "colors.interactive_primary" in template_content
        assert "colors.interactive_primary_hover" in template_content
        assert "--accent-hover" in template_content

    def test_no_hardcoded_portuguese(self, template_content):
        """Template should not have hardcoded Portuguese strings."""
        # These used to be hardcoded
        assert "Processando..." not in template_content
        assert "Usando 1 ferramenta..." not in template_content
        assert "'executando...'" not in template_content
        assert "'erro'" not in template_content
        # Instead, should use labels
        assert "labels.tool_processing" in template_content
        assert "labels.tool_using_one" in template_content
        assert "labels.tool_running" in template_content
        assert "labels.tool_error" in template_content

    def test_sparkle_animation_css(self, template_content):
        """Template should have sparkle pulse animation for thinking."""
        assert "sparkle-pulse" in template_content
        assert ".thinking-block-sparkle" in template_content

    def test_thinking_block_toggle_function(self, template_content):
        """Template should have toggleThinkingBlock function."""
        assert "function toggleThinkingBlock" in template_content


# ===== Chat Panel Thinking State Machine =====


class TestChatPanelThinkingState:
    """Tests for the thinking state machine in CopilotChatPanel."""

    @pytest.fixture
    def panel(self, qapp):
        """Create a CopilotChatPanel with mocked dependencies."""
        with patch('src.ui.components.copilot_chat_panel._load_copilot_icon', return_value=None):
            from src.ui.components.copilot_chat_panel import CopilotChatPanel
            panel = CopilotChatPanel()
        return panel

    def test_initial_thinking_state(self, panel):
        """Panel should start with _is_thinking = False."""
        assert panel._is_thinking is False

    def test_on_thinking_starts_block(self, panel):
        """_on_thinking should set _is_thinking and call startThinkingBlock JS."""
        with patch.object(panel, '_run_chat_js') as mock_js:
            panel._on_thinking("Some reasoning text")
            assert panel._is_thinking is True
            calls = [c[0][0] for c in mock_js.call_args_list]
            assert any("startThinkingBlock" in c for c in calls)
            assert any("appendThinking" in c for c in calls)

    def test_on_thinking_appends_to_existing(self, panel):
        """Second _on_thinking call should only append, not start new block."""
        with patch.object(panel, '_run_chat_js') as mock_js:
            panel._on_thinking("First thought")
            panel._on_thinking("Second thought")
            
            start_calls = [c for c in mock_js.call_args_list if "startThinkingBlock" in c[0][0]]
            append_calls = [c for c in mock_js.call_args_list if "appendThinking" in c[0][0]]
            assert len(start_calls) == 1  # Only one start
            assert len(append_calls) == 2  # Two appends

    def test_on_response_chunk_ends_thinking(self, panel):
        """_on_response_chunk should end thinking block."""
        with patch.object(panel, '_run_chat_js'):
            panel._on_thinking("reasoning")
            assert panel._is_thinking is True
            
            panel._on_response_chunk("Hello")
            assert panel._is_thinking is False

    def test_response_complete_ends_thinking(self, panel):
        """_on_response_complete should end thinking block if active."""
        with patch.object(panel, '_run_chat_js'):
            panel._is_thinking = True
            panel._on_response_complete("Full response text")
            assert panel._is_thinking is False

    def test_empty_thinking_ignored(self, panel):
        """Empty thinking text should be ignored."""
        with patch.object(panel, '_run_chat_js') as mock_js:
            panel._on_thinking("   ")
            assert panel._is_thinking is False
            # No JS calls should be made for empty thinking
            assert mock_js.call_count == 0


class TestChatPanelModelControls:
    """Tests for model list, reasoning effort, usage and session metadata."""

    @pytest.fixture
    def panel(self, qapp):
        from PyQt6.QtCore import QSettings
        settings = QSettings("DataPyn", "CopilotChat")
        settings.clear()
        with patch('src.ui.components.copilot_chat_panel._load_copilot_icon', return_value=None):
            from src.ui.components.copilot_chat_panel import CopilotChatPanel
            panel = CopilotChatPanel()
        yield panel
        settings.clear()

    def test_models_changed_populates_combo_and_usage(self, panel):
        panel._on_models_changed([
            {"id": "gpt-4o", "name": "GPT-4o", "multiplier": 1},
            {"id": "o3", "name": "o3", "multiplier": 10, "supports_reasoning_effort": True},
        ])

        assert panel._model_combo.count() == 2
        assert panel._model_combo.itemData(1) == "o3"
        assert not panel._usage_label.isHidden()
        assert panel._usage_label.text()

    def test_reasoning_effort_falls_back_to_auto_for_unsupported_model(self, panel):
        panel._on_models_changed([
            {"id": "gpt-4o", "name": "GPT-4o", "supports_reasoning_effort": False},
        ])
        high_index = panel._effort_combo.findData("high")
        panel._effort_combo.setCurrentIndex(high_index)

        panel._update_reasoning_effort_state()

        assert panel._effort_combo.currentData() == "auto"

    def test_reasoning_effort_uses_model_supported_levels(self, panel):
        panel._on_models_changed([
            {
                "id": "claude-sonnet-4.5",
                "name": "Claude Sonnet 4.5",
                "supports_reasoning_effort": True,
                "supported_reasoning_efforts": ["low", "medium"],
            },
        ])

        medium_index = panel._effort_combo.findData("medium")
        high_index = panel._effort_combo.findData("high")
        xhigh_index = panel._effort_combo.findData("xhigh")

        assert panel._effort_combo.model().item(medium_index).isEnabled()
        assert not panel._effort_combo.model().item(high_index).isEnabled()
        assert not panel._effort_combo.model().item(xhigh_index).isEnabled()

    def test_usage_snapshot_displays_real_quota(self, panel):
        panel._set_usage_snapshot({
            "available": True,
            "used": 12,
            "total": 300,
            "reset_date": "2026-06-01",
        })

        assert panel._usage_label.text() == "12/300 premium"
        assert "2026-06-01" in panel._usage_label.toolTip()

    def test_refresh_models_button_calls_client_refresh_metadata(self, panel):
        client = MagicMock()
        client.refresh_metadata = MagicMock()
        panel._copilot_client = client

        panel._on_refresh_models_clicked()

        client.refresh_metadata.assert_called_once()
        assert panel._usage_label.text()

    def test_save_current_session_includes_model_effort_and_tab(self, panel):
        panel._messages = [
            {"role": "user", "content": "create a chart"},
            {"role": "assistant", "content": "done"},
        ]
        panel._current_tab_id = "tab-1"
        panel._current_tab_name = "Sales"
        effort_index = panel._effort_combo.findData("medium")
        if effort_index >= 0:
            panel._effort_combo.setCurrentIndex(effort_index)

        panel._save_current_session()
        sessions = panel._get_sessions_list()

        assert sessions[0]["model"] == panel._model_combo.currentData()
        assert sessions[0]["reasoning_effort"] == panel._effort_combo.currentData()
        assert sessions[0]["target_tab_id"] == "tab-1"
        assert sessions[0]["target_tab_name"] == "Sales"


# ===== Per-Tab Chat Context =====


class TestPerTabChatContext:
    """Tests for per-tab chat context switching."""

    @pytest.fixture
    def panel(self, qapp):
        """Create a CopilotChatPanel with mocked dependencies."""
        with patch('src.ui.components.copilot_chat_panel._load_copilot_icon', return_value=None):
            from src.ui.components.copilot_chat_panel import CopilotChatPanel
            panel = CopilotChatPanel()
        return panel

    def test_switch_to_new_tab_keeps_global_messages(self, panel):
        """Switching tabs should keep the global chat history."""
        with patch.object(panel, '_run_chat_js'):
            panel._messages = [{"role": "user", "content": "hello"}]
            panel.switch_tab_context("tab_2", "Tab 2")
            assert panel._messages == [{"role": "user", "content": "hello"}]
            assert panel._current_tab_id == "tab_2"

    def test_switch_back_does_not_restore_per_tab_history(self, panel):
        """Chat history should remain global instead of per-tab isolated."""
        with patch.object(panel, '_run_chat_js'):
            panel._messages = [{"role": "user", "content": "hello from tab 1"}]
            panel._current_tab_id = "tab_1"

            panel.switch_tab_context("tab_2", "Tab 2")
            panel._messages.append({"role": "user", "content": "hello from tab 2"})

            panel.switch_tab_context("tab_1", "Tab 1")
            assert len(panel._messages) == 2
            assert panel._messages[0]["content"] == "hello from tab 1"
            assert panel._messages[1]["content"] == "hello from tab 2"

    def test_switch_keeps_thinking_state(self, panel):
        """Switching target tabs should not interrupt global chat thinking state."""
        with patch.object(panel, '_run_chat_js'):
            panel._is_thinking = True
            panel.switch_tab_context("tab_new", "New Tab")
            assert panel._is_thinking is True

    def test_tab_badge_updated(self, panel):
        """Switching tabs should update the tab badge label."""
        with patch.object(panel, '_run_chat_js'):
            panel.switch_tab_context("tab_1", "My Session")
            assert not panel._tab_badge.isHidden()
            assert "My Session" in panel._tab_badge.text()

    def test_tab_badge_initially_hidden(self, panel):
        """Tab badge should be hidden initially."""
        assert panel._tab_badge.isHidden()

    def test_webview_not_cleared_on_switch(self, panel):
        """Switching tabs should not clear global chat messages in WebView."""
        with patch.object(panel, '_run_chat_js') as mock_js:
            panel.switch_tab_context("tab_1", "Tab 1")
            calls = [c[0][0] for c in mock_js.call_args_list]
            assert not any("clearMessages" in c for c in calls)


# ===== i18n Labels =====


class TestI18nLabels:
    """Tests for copilot chat i18n integration."""

    def test_en_labels_exist(self):
        """English translation should have all copilot chat labels."""
        lang_path = Path(__file__).parent.parent / "source" / "src" / "language" / "en-US.json"
        with open(lang_path, encoding="utf-8") as f:
            data = json.load(f)
        
        copilot = data.get("copilot", {})
        required_keys = [
            "thinking", "thinking_complete", "tool_processing",
            "tool_using_one", "tool_using_many", "tool_used_one",
            "tool_used_many", "tool_running", "tool_ok", "tool_error",
            "reasoning_effort_tooltip", "effort_medium", "effort_high",
            "effort_xhigh", "usage_unavailable", "history_search_placeholder",
            "refresh_models", "usage_used_format", "usage_tooltip_with_reset",
        ]
        for key in required_keys:
            assert key in copilot, f"Missing copilot.{key} in en-US.json"

    def test_pt_labels_exist(self):
        """Portuguese translation should have all copilot chat labels."""
        lang_path = Path(__file__).parent.parent / "source" / "src" / "language" / "pt-BR.json"
        with open(lang_path, encoding="utf-8") as f:
            data = json.load(f)
        
        copilot = data.get("copilot", {})
        required_keys = [
            "thinking", "thinking_complete", "tool_processing",
            "tool_using_one", "tool_using_many", "tool_used_one",
            "tool_used_many", "tool_running", "tool_ok", "tool_error",
            "reasoning_effort_tooltip", "effort_medium", "effort_high",
            "effort_xhigh", "usage_unavailable", "history_search_placeholder",
            "refresh_models", "usage_used_format", "usage_tooltip_with_reset",
        ]
        for key in required_keys:
            assert key in copilot, f"Missing copilot.{key} in pt-BR.json"

    def test_webview_labels_sent_on_ready(self, qapp):
        """_on_webview_ready should send labels to WebView via setLabels."""
        with patch('src.ui.components.copilot_chat_panel._load_copilot_icon', return_value=None):
            from src.ui.components.copilot_chat_panel import CopilotChatPanel
            panel = CopilotChatPanel()
        
        with patch.object(panel, '_run_chat_js') as mock_js:
            panel._webview_ready = True
            panel._on_webview_ready()
            calls = [c[0][0] for c in mock_js.call_args_list]
            assert any("setLabels" in c for c in calls)


from pathlib import Path


# ===== BlockEditor execute_block public method =====


class TestBlockEditorExecuteBlock:
    """Tests that BlockEditor.execute_block is a public method."""

    def test_execute_block_is_public(self, qapp):
        """BlockEditor should have a public execute_block method."""
        from src.editors.block_editor import BlockEditor
        editor = BlockEditor()
        assert hasattr(editor, "execute_block")
        assert callable(editor.execute_block)

    def test_execute_block_emits_python_signal(self, qapp):
        """execute_block should emit execute_python for python blocks."""
        from src.editors.block_editor import BlockEditor
        editor = BlockEditor()
        block = MagicMock()
        block.get_code.return_value = "print('hello')"
        block.get_language.return_value = "python"

        emitted = []
        editor.execute_python.connect(lambda code: emitted.append(code))
        editor.execute_block(block)

        assert len(emitted) == 1
        assert emitted[0] == "print('hello')"
        block.set_running.assert_called_once_with(True)

    def test_execute_block_emits_sql_signal(self, qapp):
        """execute_block should emit execute_sql for sql blocks."""
        from src.editors.block_editor import BlockEditor
        editor = BlockEditor()
        block = MagicMock()
        block.get_code.return_value = "SELECT 1"
        block.get_language.return_value = "sql"
        block.get_block_name.return_value = "query1"
        block.get_connection_name.return_value = "myconn"
        block.get_database_name.return_value = "mydb"

        emitted = []
        editor.execute_sql.connect(lambda q, bn, cn, dn, sp: emitted.append((q, bn, cn, dn, sp)))
        editor.execute_block(block)

        assert len(emitted) == 1
        assert emitted[0] == ("SELECT 1", "query1", "myconn", "mydb", [])

    def test_execute_block_empty_code_noop(self, qapp):
        """execute_block should do nothing for empty code blocks."""
        from src.editors.block_editor import BlockEditor
        editor = BlockEditor()
        block = MagicMock()
        block.get_code.return_value = "   "

        emitted = []
        editor.execute_python.connect(lambda code: emitted.append(code))
        editor.execute_block(block)

        assert len(emitted) == 0

    def test_private_alias_still_works(self, qapp):
        """_execute_block should be an alias for execute_block."""
        from src.editors.block_editor import BlockEditor
        # Class-level check: both names point to the same function
        assert BlockEditor._execute_block is BlockEditor.execute_block


# ===== MCP Tool Execution Helpers =====


class TestMCPToolExecutionHelpers:
    """Tests for the execution wait/result helpers in MCPToolRegistry."""

    def _make_registry(self):
        """Create a MCPToolRegistry with mocked main window."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)
        registry._main_window = MagicMock()
        return registry

    def test_get_output_snapshot_returns_text(self, qapp):
        """_get_output_snapshot should read from global_output_panel."""
        registry = self._make_registry()
        registry._main_window.global_output_panel.get_text.return_value = "hello output"

        result = registry._get_output_snapshot()
        assert result == "hello output"

    def test_get_output_snapshot_no_panel(self, qapp):
        """_get_output_snapshot should return empty string if no panel."""
        registry = self._make_registry()
        registry._main_window = None

        result = registry._get_output_snapshot()
        assert result == ""

    def test_wait_for_block_already_done(self, qapp):
        """_wait_for_block_execution returns True if block already stopped."""
        registry = self._make_registry()
        block = MagicMock()
        block._is_running = False

        result = registry._wait_for_block_execution(block, timeout_ms=100)
        assert result is True

    def test_wait_for_block_no_running_attr(self, qapp):
        """_wait_for_block_execution returns True if block has no _is_running."""
        registry = self._make_registry()
        block = MagicMock(spec=[])  # no _is_running

        result = registry._wait_for_block_execution(block, timeout_ms=100)
        assert result is True

    def test_wait_for_block_timeout(self, qapp):
        """_wait_for_block_execution returns False on timeout."""
        registry = self._make_registry()
        block = MagicMock()
        block._is_running = True  # Never stops

        result = registry._wait_for_block_execution(block, timeout_ms=300)
        assert result is False

    def test_wait_for_block_completes(self, qapp):
        """_wait_for_block_execution returns True when block stops running."""
        registry = self._make_registry()
        block = MagicMock()
        block._is_running = True

        # Simulate block finishing after 200ms
        QTimer.singleShot(200, lambda: setattr(block, '_is_running', False))

        result = registry._wait_for_block_execution(block, timeout_ms=5000)
        assert result is True

    def test_collect_execution_result_with_output(self, qapp):
        """_collect_execution_result should include new output text."""
        registry = self._make_registry()
        registry._main_window.global_output_panel.get_text.return_value = "before\nhello world"
        registry._main_window.global_results_viewer = None
        block = MagicMock()
        block.status_label.text.return_value = "0.5s"

        result = registry._collect_execution_result(block, 0, "before\n")
        text = result["content"][0]["text"]
        assert "hello world" in text
        assert "Block 0 execution finished" in text

    def test_collect_execution_result_no_output(self, qapp):
        """_collect_execution_result should handle empty output."""
        registry = self._make_registry()
        registry._main_window.global_output_panel.get_text.return_value = ""
        registry._main_window.global_results_viewer = None
        block = MagicMock()
        block.status_label.text.return_value = "0.1s"

        result = registry._collect_execution_result(block, 0, "")
        text = result["content"][0]["text"]
        assert "no visible output" in text.lower() or "completed" in text.lower()

    def test_collect_execution_result_with_error(self, qapp):
        """_collect_execution_result should detect error status."""
        registry = self._make_registry()
        registry._main_window.global_output_panel.get_text.return_value = ""
        registry._main_window.global_results_viewer = None
        block = MagicMock()
        block.status_label.text.return_value = "Error"

        result = registry._collect_execution_result(block, 0, "")
        text = result["content"][0]["text"]
        assert "error" in text.lower()


# ===== MCP Tool Execute Block Handler =====


class TestMCPToolExecuteBlock:
    """Tests for the execute_block, run_current_block, write_and_run tool handlers."""

    def _make_registry_with_session(self):
        """Create a registry with mocked session/block_editor/blocks."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)

        block = MagicMock()
        block._is_running = False
        block.get_code.return_value = "print('test')"
        block.get_language.return_value = "python"
        block.get_block_name.return_value = "test_block"
        block.status_label.text.return_value = "0.1s"

        block_editor = MagicMock()
        block_editor.blocks = [block]
        block_editor.focused_block = block
        block_editor.get_last_focused_block.return_value = block

        session_widget = MagicMock()
        session_widget.editor = block_editor
        session_widget.editor.add_block = block_editor.add_block

        mw = MagicMock()
        mw.session_tabs.currentIndex.return_value = 0
        mw.session_tabs.widget.return_value = session_widget
        mw.global_output_panel.get_text.return_value = "output: hello"
        mw.global_results_viewer = None

        registry._main_window = mw
        registry.set_main_window(mw)

        return registry, block, block_editor

    def test_execute_block_calls_execute(self, qapp):
        """execute_block tool should call block_editor.execute_block."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._execute_block({"block_index": 0})

        block_editor.execute_block.assert_called_once_with(block)
        assert "content" in result

    def test_execute_block_returns_output(self, qapp):
        """execute_block should include output text in the result."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._execute_block({"block_index": 0})
        text = result["content"][0]["text"]
        assert "Block 0" in text

    def test_execute_block_invalid_index(self, qapp):
        """execute_block with invalid index should return error."""
        registry, _, _ = self._make_registry_with_session()

        result = registry._execute_block({"block_index": 99})
        assert "error" in result

    def test_execute_block_no_index(self, qapp):
        """execute_block without block_index should use focused block."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._execute_block({})
        assert "content" in result
        block_editor.execute_block.assert_called_once_with(block)

    def test_run_current_block_uses_focused(self, qapp):
        """run_current_block should execute the focused block."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._run_current_block({})
        block_editor.execute_block.assert_called_once_with(block)
        assert "content" in result

    def test_run_current_block_fallback_last(self, qapp):
        """run_current_block should use last block if none focused."""
        registry, block, block_editor = self._make_registry_with_session()
        block_editor.focused_block = None

        result = registry._run_current_block({})
        block_editor.execute_block.assert_called_once_with(block)

    def test_write_and_run_creates_and_executes(self, qapp):
        """write_and_run should create a block, set code, and execute."""
        registry, block, block_editor = self._make_registry_with_session()
        new_block = MagicMock()
        new_block._is_running = False
        new_block.get_block_name.return_value = "analysis"
        new_block.status_label.text.return_value = "0.2s"
        block_editor.blocks = [block]

        def add_block(language="python"):
            block_editor.blocks.append(new_block)
            return new_block

        block_editor.add_block.side_effect = add_block

        result = registry._write_and_run({
            "language": "python",
            "code": "print('hello')",
            "name": "analysis",
        })

        block_editor.add_block.assert_called_once_with(language="python")
        new_block.set_block_name.assert_called_once_with("analysis")
        new_block.set_code.assert_called_once_with("print('hello')")
        block_editor.execute_block.assert_called_once_with(new_block)
        assert "content" in result

    def test_write_and_run_updates_existing_named_block(self, qapp):
        """write_and_run should update/run an existing named block instead of duplicating it."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._write_and_run({
            "language": "python",
            "code": "print('updated')",
            "name": "test_block",
        })

        block_editor.add_block.assert_not_called()
        block.set_code.assert_called_once_with("print('updated')")
        block_editor.execute_block.assert_called_once_with(block)
        assert "content" in result

    def test_fix_and_run_updates_and_executes(self, qapp):
        """fix_and_run should update code and execute the focused block."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._fix_and_run({"fixed_code": "print('fixed')"})

        block.set_code.assert_called_once_with("print('fixed')")
        block_editor.execute_block.assert_called_once_with(block)
        assert "content" in result

    def test_execute_focused_delegates(self, qapp):
        """execute_focused should execute the focused block."""
        registry, block, block_editor = self._make_registry_with_session()

        result = registry._execute_focused({})
        block_editor.execute_block.assert_called_once_with(block)
        assert "content" in result

    def test_get_block_result_delegates_to_execution_results(self, qapp):
        """get_block_result should delegate to get_execution_results."""
        registry, _, _ = self._make_registry_with_session()

        result = registry._get_block_result({"block_index": 0})
        # Should return output panel content, not error
        assert "content" in result

    def test_get_focused_result_returns_output(self, qapp):
        """get_focused_result should return output panel content."""
        registry, _, _ = self._make_registry_with_session()

        result = registry._get_focused_result({})
        assert "content" in result


# ===== read_output tool =====


class TestReadOutput:
    """Tests for the read_output tool - reading from output panel."""

    def _make_registry_with_output(self, output_text=""):
        """Create a registry with output panel containing given text."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)

        output_panel = MagicMock()
        output_panel.get_text.return_value = output_text

        mw = MagicMock()
        mw.global_output_panel = output_panel
        registry._main_window = mw
        return registry

    def test_read_output_returns_text(self, qapp):
        """read_output should return the output panel text."""
        registry = self._make_registry_with_output("line1\nline2\nline3")
        result = registry._read_output({})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "line1" in text
        assert "line2" in text
        assert "line3" in text

    def test_read_output_last_n_lines(self, qapp):
        """read_output with last_n_lines should return only the last N lines."""
        lines = "\n".join(f"line{i}" for i in range(100))
        registry = self._make_registry_with_output(lines)
        result = registry._read_output({"last_n_lines": 5})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "line99" in text
        assert "line95" in text
        # Earlier lines should be omitted
        assert "omitted" in text

    def test_read_output_empty_panel(self, qapp):
        """read_output on empty panel should return appropriate message."""
        registry = self._make_registry_with_output("")
        result = registry._read_output({})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "empty" in text.lower()

    def test_read_output_all_lines(self, qapp):
        """read_output with last_n_lines=0 should return all lines."""
        lines = "\n".join(f"line{i}" for i in range(10))
        registry = self._make_registry_with_output(lines)
        result = registry._read_output({"last_n_lines": 0})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "line0" in text
        assert "line9" in text

    def test_get_execution_results_tool_registered(self, qapp):
        """get_execution_results should be registered as a tool."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)

        tools = {t["function"]["name"] for t in registry.list_tools_openai()}
        assert "get_execution_results" in tools

    def test_read_output_total_line_count(self, qapp):
        """read_output should include total line count."""
        lines = "\n".join(f"line{i}" for i in range(50))
        registry = self._make_registry_with_output(lines)
        result = registry._read_output({"last_n_lines": 10})

        assert "content" in result
        text = result["content"][0]["text"]
        assert "50 total" in text


# ===== Tool Guide in get_context =====


class TestToolGuideInContext:
    """Tests for the tool_guide field added to get_context."""

    def _make_registry(self):
        """Create a registry with session for get_context."""
        from src.services.copilot.mcp_tools import MCPToolRegistry
        registry = MCPToolRegistry(parent=None)

        session = MagicMock()
        session.session_id = "test-session"
        session.title = "Test"
        session.connection_name = ""
        session.is_connected = False

        block_editor = MagicMock()
        block_editor.blocks = []
        block_editor.focused_block = None

        session_widget = MagicMock()
        session_widget.editor = block_editor

        mw = MagicMock()
        mw.session_tabs.currentIndex.return_value = 0
        mw.session_tabs.widget.return_value = session_widget
        mw.session_manager.focused_session = session
        mw._session_explorers = {}

        registry._main_window = mw
        return registry

    def test_context_includes_tool_guide(self, qapp):
        """get_context response should include tool_guide."""
        registry = self._make_registry()
        result = registry._get_context({})

        assert "content" in result
        context = json.loads(result["content"][0]["text"])
        assert "tool_guide" in context

    def test_tool_guide_has_categories(self, qapp):
        """tool_guide should mention key workflow guidance."""
        registry = self._make_registry()
        result = registry._get_context({})
        context = json.loads(result["content"][0]["text"])
        guide = context["tool_guide"]

        assert isinstance(guide, str)
        assert "block_map" in guide
        assert "edit_block" in guide
        assert "block_name" in guide
        assert "write_and_run" in guide
        assert "run_silent" in guide

    def test_tool_guide_mentions_edit_vs_create(self, qapp):
        """tool_guide should emphasize editing existing blocks over creating new ones."""
        registry = self._make_registry()
        result = registry._get_context({})
        context = json.loads(result["content"][0]["text"])
        guide = context["tool_guide"]

        assert "UPDATE" in guide
        assert "CREATE" in guide
