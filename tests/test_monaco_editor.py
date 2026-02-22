"""
Tests for Monaco Editor integration.

Tests the MonacoEditor widget, MonacoBridge, and InlineCompletionService.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

# Skip if QWebEngineView not available
pytest.importorskip("PyQt6.QtWebEngineWidgets")


class TestMonacoBridge:
    """Tests for the MonacoBridge class."""
    
    def test_bridge_signals_exist(self):
        """Bridge should have all required signals."""
        from src.editors.monaco.monaco_bridge import MonacoBridge
        
        bridge = MonacoBridge()
        
        # Check all signals exist
        assert hasattr(bridge, "editor_ready")
        assert hasattr(bridge, "text_changed")
        assert hasattr(bridge, "focus_in")
        assert hasattr(bridge, "focus_out")
        assert hasattr(bridge, "cursor_changed")
        assert hasattr(bridge, "execute_requested")
        assert hasattr(bridge, "completion_requested")
    
    def test_bridge_slots_callable(self):
        """Bridge slots should be callable."""
        from src.editors.monaco.monaco_bridge import MonacoBridge
        
        bridge = MonacoBridge()
        
        # Test slots can be called
        bridge.onEditorReady()
        bridge.onTextChanged("test")
        bridge.onFocusIn()
        bridge.onFocusOut()
        bridge.onCursorChanged(1, 1)
        bridge.onExecuteRequested()
        bridge.requestCompletion("prefix", "suffix", 1, 1)
    
    def test_bridge_emits_signals(self, qtbot):
        """Bridge slots should emit corresponding signals."""
        from src.editors.monaco.monaco_bridge import MonacoBridge
        
        bridge = MonacoBridge()
        
        # Test editor_ready signal
        with qtbot.waitSignal(bridge.editor_ready, timeout=100):
            bridge.onEditorReady()
        
        # Test text_changed signal
        with qtbot.waitSignal(bridge.text_changed, timeout=100):
            bridge.onTextChanged("test content")
        
        # Test focus signals
        with qtbot.waitSignal(bridge.focus_in, timeout=100):
            bridge.onFocusIn()
        
        with qtbot.waitSignal(bridge.focus_out, timeout=100):
            bridge.onFocusOut()
        
        # Test execute_requested
        with qtbot.waitSignal(bridge.execute_requested, timeout=100):
            bridge.onExecuteRequested()


class TestMonacoEditorBasic:
    """Basic tests for MonacoEditor widget."""
    
    def test_editor_creates(self, qtbot):
        """Editor should create without errors."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        assert editor is not None
        assert editor._web_view is not None
        assert editor._bridge is not None
    
    def test_editor_has_required_signals(self):
        """Editor should have ICodeEditor signals."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        
        assert hasattr(editor, "text_changed")
        assert hasattr(editor, "execute_requested")
        assert hasattr(editor, "focus_in")
        assert hasattr(editor, "focus_out")
        assert hasattr(editor, "SCN_FOCUSIN")
        assert hasattr(editor, "SCN_FOCUSOUT")
        assert hasattr(editor, "textChanged")
    
    def test_editor_get_widget_returns_self(self, qtbot):
        """get_widget should return the editor itself."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        assert editor.get_widget() is editor
    
    def test_editor_set_text_updates_cache(self, qtbot):
        """set_text should update the internal cache."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        editor.set_text("hello world")
        
        assert editor._text_cache == "hello world"
        assert editor.get_text() == "hello world"
    
    def test_editor_clear_empties_text(self, qtbot):
        """clear should empty the text."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        editor.set_text("some content")
        editor.clear()
        
        assert editor.get_text() == ""
    
    def test_editor_language_setting(self, qtbot):
        """Language setting should work."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        editor.set_language("python")
        assert editor.get_language() == "python"
        
        editor.set_language("sql")
        assert editor.get_language() == "sql"
    
    def test_editor_line_count(self, qtbot):
        """get_line_count should return correct count."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        editor.set_text("line1\nline2\nline3")
        
        assert editor.get_line_count() == 3


class TestInlineCompletionService:
    """Tests for InlineCompletionService."""
    
    def test_service_creates(self):
        """Service should create without errors."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        assert service is not None
        assert hasattr(service, "completion_ready")
    
    def test_service_set_copilot_client(self):
        """Service should accept copilot client."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        mock_client = Mock()
        
        service.set_copilot_client(mock_client)
        
        assert service._copilot_client is mock_client
    
    def test_service_debounce_timer(self, qtbot):
        """Service should have debounce timer configured."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        assert service._debounce_timer.isSingleShot()
        assert service._debounce_timer.interval() == 300  # 300ms (fast for Copilot)
    
    def test_service_cancel_request(self):
        """cancel_request should stop pending requests."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        # Request then cancel
        service.request_completion("prefix", "suffix", "python", 1, 1)
        service.cancel_request()
        
        assert service._pending_request is None
        assert not service._debounce_timer.isActive()
    
    def test_python_def_completion(self):
        """Service should complete Python def statements."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        completion = service._python_completion("def foo", "", "def foo")
        
        assert "(self):" in completion or "():" in completion
    
    def test_python_class_completion(self):
        """Service should complete Python class statements."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        completion = service._python_completion("class Foo", "", "class Foo")
        
        assert ":" in completion
        assert "__init__" in completion
    
    def test_python_for_completion(self):
        """Service should complete Python for statements."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        completion = service._python_completion("for i", "", "for i")
        
        assert "in range" in completion
    
    def test_sql_select_completion(self):
        """Service should complete SQL SELECT statements."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        completion = service._sql_completion("SELECT", "", "SELECT")
        
        assert "FROM" in completion
    
    def test_sql_from_completion(self):
        """Service should complete SQL FROM clause."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        
        completion = service._sql_completion("SELECT * FROM ", "", "SELECT * FROM ")
        
        assert "table" in completion.lower()
    
    def test_skips_short_prefix(self):
        """Service should skip completion for very short prefix."""
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        
        service = InlineCompletionService()
        results = []
        service.completion_ready.connect(lambda x: results.append(x))
        
        # Very short prefix should be skipped
        service.request_completion("ab", "", "python", 1, 3)
        
        # Should emit empty immediately (not debounced)
        assert len(results) == 1
        assert results[0] == ""


class TestEditorConfig:
    """Tests for editor configuration (Monaco only)."""
    
    def test_backend_is_always_monaco(self):
        """Editor backend should always be monaco."""
        from src.editors.editor_config import get_editor_backend
        
        assert get_editor_backend() == "monaco"
    
    def test_is_monaco_enabled_always_true(self):
        """is_monaco_enabled should always return True."""
        from src.editors.editor_config import is_monaco_enabled
        
        assert is_monaco_enabled() is True
    
    def test_set_backend_ignores_non_monaco(self):
        """Setting non-monaco backend should be ignored."""
        from src.editors.editor_config import set_editor_backend, get_editor_backend
        
        # Should not raise, just ignore
        set_editor_backend("scintilla")
        
        # Backend should still be monaco
        assert get_editor_backend() == "monaco"
    
    def test_get_code_editor_class_returns_monaco(self):
        """get_code_editor_class should always return MonacoEditor."""
        from src.editors.editor_config import get_code_editor_class
        from src.editors.monaco import MonacoEditor
        
        EditorClass = get_code_editor_class()
        
        assert EditorClass is MonacoEditor


class TestMonacoEditorInterface:
    """Tests that MonacoEditor implements ICodeEditor interface."""
    
    def test_implements_icode_editor_protocol(self, qtbot):
        """MonacoEditor should satisfy ICodeEditor protocol."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        from src.editors.interfaces.code_editor_interface import ICodeEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        # Check protocol compliance
        assert isinstance(editor, ICodeEditor)
    
    def test_has_all_required_methods(self, qtbot):
        """MonacoEditor should have all ICodeEditor methods."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        # Text methods
        assert callable(getattr(editor, "get_text", None))
        assert callable(getattr(editor, "set_text", None))
        assert callable(getattr(editor, "get_selected_text", None))
        assert callable(getattr(editor, "has_selection", None))
        assert callable(getattr(editor, "clear", None))
        
        # Language/theme
        assert callable(getattr(editor, "set_language", None))
        assert callable(getattr(editor, "get_language", None))
        assert callable(getattr(editor, "set_theme", None))
        assert callable(getattr(editor, "apply_theme", None))
        
        # Visual settings
        assert callable(getattr(editor, "set_font", None))
        assert callable(getattr(editor, "set_read_only", None))
        assert callable(getattr(editor, "set_line_numbers_visible", None))
        
        # Navigation
        assert callable(getattr(editor, "get_line_count", None))
        assert callable(getattr(editor, "get_current_line", None))
        assert callable(getattr(editor, "go_to_line", None))
        
        # Widget
        assert callable(getattr(editor, "get_widget", None))


class TestMonacoThemeIntegration:
    """Tests for Monaco theme support."""
    
    def test_theme_data_dark_detection(self, qtbot):
        """Should correctly detect dark themes."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        assert editor._is_dark_color("#1e1e1e") is True
        assert editor._is_dark_color("#ffffff") is False
        assert editor._is_dark_color("#272822") is True  # Monokai bg
    
    def test_theme_manager_integration(self, qtbot):
        """Should integrate with ThemeManager."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        from src.core.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        editor = MonacoEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        
        assert editor.theme_manager is theme_manager


class TestMonacoCompletionIntegration:
    """Tests for Monaco inline completion integration."""
    
    def test_completion_signal_exists(self, qtbot):
        """Editor should have completion_requested signal."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        assert hasattr(editor, "completion_requested")
    
    def test_provide_completion_method(self, qtbot):
        """Editor should have provide_completion method."""
        from src.editors.monaco.monaco_editor import MonacoEditor
        
        editor = MonacoEditor()
        qtbot.addWidget(editor)
        
        assert callable(getattr(editor, "provide_completion", None))
