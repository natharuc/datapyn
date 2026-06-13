"""
Tests for Monaco Editor integration.

Tests the MonacoEditor widget, MonacoBridge, and InlineCompletionService.
"""

import json
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

    @pytest.fixture
    def editor_zoom_settings(self):
        from PyQt6.QtCore import QSettings
        from src.editors.monaco.monaco_editor import MonacoEditor

        settings = QSettings("DataPyn", "DataPyn")
        key = MonacoEditor.SETTINGS_KEY_FONT_SIZE
        previous = settings.value(key, None)
        settings.remove(key)
        yield settings
        if previous is None:
            settings.remove(key)
        else:
            settings.setValue(key, previous)
    
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

    def test_editor_set_text_replaces_pending_text_before_ready(self, qtbot):
        """Only the latest pending full-text update should remain queued."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)

        editor.set_text("first value")
        editor.set_text("second value")

        pending_set_value = [
            entry for entry in editor._pending_operations if entry[2] == "editor:setValue"
        ]

        assert editor.get_text() == "second value"
        assert len(pending_set_value) == 1

    def test_editor_ready_runs_only_latest_pending_text(self, qtbot):
        """Ready transition should not replay stale queued set_text calls."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor.apply_theme = Mock()
        editor._run_js = Mock()

        editor.set_text("first value")
        editor.set_text("second value")
        editor._on_editor_ready()

        set_value_scripts = [
            call.args[0]
            for call in editor._run_js.call_args_list
            if call.args and call.args[0].startswith("setValue(")
        ]

        assert set_value_scripts == [f"setValue({json.dumps('second value')})"]

    def test_editor_set_text_keeps_other_pending_operations(self, qtbot):
        """Coalescing text updates should not discard unrelated queued JS."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor.apply_theme = Mock()
        editor._run_js = Mock()

        editor.set_language("sql")
        editor.set_text("first value")
        editor.set_text("second value")
        editor._on_editor_ready()

        scripts = [call.args[0] for call in editor._run_js.call_args_list if call.args]

        assert any(script.startswith("setLanguage(") for script in scripts)
        assert scripts.count(f"setValue({json.dumps('second value')})") == 1

    def test_editor_restores_persisted_font_size(self, qtbot, editor_zoom_settings):
        """Monaco should restore the saved user zoom/font preference."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor_zoom_settings.setValue(MonacoEditor.SETTINGS_KEY_FONT_SIZE, 18)

        editor = MonacoEditor()
        qtbot.addWidget(editor)

        assert editor.get_font_size() == 18

    def test_editor_font_size_persists_and_updates_monaco(self, qtbot, editor_zoom_settings):
        """Changing editor zoom should persist and call Monaco's font-size API."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._is_ready = True
        editor._run_js = Mock()

        editor.set_font_size(16)

        assert editor_zoom_settings.value(MonacoEditor.SETTINGS_KEY_FONT_SIZE, type=int) == 16
        editor._run_js.assert_called_with("setFontSize(16)", None)

    def test_editor_zoom_wheel_changes_font_size(self, qtbot, editor_zoom_settings):
        """Ctrl+wheel handler should zoom in and out in one-point steps."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._is_ready = True
        editor._run_js = Mock()
        editor.set_font_size(13, persist=False)

        assert editor._handle_zoom_wheel(120) is True
        assert editor.get_font_size() == 14
        assert editor_zoom_settings.value(MonacoEditor.SETTINGS_KEY_FONT_SIZE, type=int) == 14

        assert editor._handle_zoom_wheel(-120) is True
        assert editor.get_font_size() == 13
        assert editor._handle_zoom_wheel(0) is False
    
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
    """Tests for the rewritten (HTTP connector) InlineCompletionService."""

    def _service(self):
        from src.editors.monaco.inline_completion_service import InlineCompletionService
        return InlineCompletionService()

    def _patch_provider(self, monkeypatch, *, enabled=True, active="openrouter",
                        token_for=("openrouter",), model="openai/gpt-4.1-mini"):
        from src.editors.monaco import inline_completion_service as mod
        settings = Mock()
        settings.autocomplete_enabled = enabled
        settings.active_provider = active
        settings.completion_model = lambda pid: model
        monkeypatch.setattr(mod, "get_pynia_settings", lambda: settings)
        monkeypatch.setattr(mod, "get_provider_secret", lambda pid: "tok" if pid in token_for else "")

    def test_service_creates(self):
        service = self._service()
        assert service is not None
        assert hasattr(service, "completion_ready")
        assert service.has_lsp is False  # native LSP path removed

    def test_compat_setters_are_noops(self):
        service = self._service()
        # Old callers still invoke these — must not raise.
        service.set_pynia_client(Mock())
        service.set_copilot_client(Mock())
        service.set_lsp_client(Mock())
        service.set_blocks_code_context("other block code")  # focused-block only
        service.set_document_info("file:///x.py", "python")
        service.open_document("file:///x.py", "python", "x = 1")
        service.notify_document_changed("x = 1")

    def test_skips_short_prefix(self):
        service = self._service()
        results = []
        service.completion_ready.connect(results.append)
        service.request_completion("a", "", "python", 1, 2)
        assert results == [""]

    def test_cancel_request_clears_pending(self):
        service = self._service()
        service.request_completion("import pandas", "", "python", 1, 14)
        service.cancel_request()
        assert service._pending is None
        assert not service._debounce.isActive()

    def test_resolve_provider_prefers_active_api(self, monkeypatch):
        self._patch_provider(monkeypatch, active="openrouter", token_for=("openrouter",))
        service = self._service()
        assert service._resolve_provider() == ("openrouter", "openai/gpt-4.1-mini")
        assert service.has_pynia is True

    def test_resolve_provider_none_when_disabled(self, monkeypatch):
        self._patch_provider(monkeypatch, enabled=False)
        service = self._service()
        assert service._resolve_provider() == (None, None)
        assert service.has_pynia is False

    def test_resolve_provider_none_without_token(self, monkeypatch):
        self._patch_provider(monkeypatch, token_for=())  # no API token anywhere
        service = self._service()
        assert service._resolve_provider() == (None, None)

    def test_fire_without_provider_emits_empty(self, monkeypatch):
        self._patch_provider(monkeypatch, token_for=())
        service = self._service()
        results = []
        service.completion_ready.connect(results.append)
        service._pending = {"id": 1, "prefix": "x", "suffix": "", "language": "python", "line": 1, "column": 2}
        service._fire()
        assert results == [""]
        assert service._busy is False

    def test_fire_with_provider_starts_worker(self, monkeypatch):
        from src.services.ai_autocomplete_circuit_breaker import reset_ai_autocomplete_circuit_breaker

        reset_ai_autocomplete_circuit_breaker()
        self._patch_provider(monkeypatch, active="openrouter", token_for=("openrouter",))
        service = self._service()
        started = []
        service._start_worker = lambda pid, model, req: started.append((pid, model, req))
        service._pending = {"id": 1, "prefix": "x =", "suffix": "", "language": "python", "line": 1, "column": 3}
        service._fire()
        assert service._busy is True
        assert started and started[0][0] == "openrouter"
        assert started[0][1] == "openai/gpt-4.1-mini"

    def test_circuit_breaker_blocks_ai_fire(self, monkeypatch):
        from src.services.ai_autocomplete_circuit_breaker import get_ai_autocomplete_circuit_breaker

        self._patch_provider(monkeypatch, active="openrouter", token_for=("openrouter",))
        breaker = get_ai_autocomplete_circuit_breaker()
        breaker.reset()
        breaker.record_failure("e1")
        breaker.record_failure("e2")
        breaker.record_failure("e3")
        service = self._service()
        started = []
        service._start_worker = lambda *a: started.append(a)
        results = []
        service.completion_ready.connect(results.append)
        service._pending = {
            "id": 1, "prefix": "x =", "suffix": "", "language": "python", "line": 1, "column": 3,
        }
        service._fire()
        assert started == []
        assert results == [""]
        assert service._busy is False
        breaker.reset()

    def test_lsp_preferred_when_authenticated(self):
        """When the Copilot LSP is signed in, it serves completions (0-indexed)."""
        lsp = Mock()
        lsp.is_authenticated = True
        service = self._service()
        service.set_lsp_client(lsp)
        service.set_document_info("file:///x.py", "python")
        assert service.has_lsp is True

        service._pending = {
            "id": 1, "prefix": "def f():\n    ", "suffix": "",
            "language": "python", "line": 2, "column": 5,
        }
        service._fire()

        lsp.request_completion.assert_called_once()
        uri, _version, line, char = lsp.request_completion.call_args[0]
        assert uri == "file:///x.py"
        assert (line, char) == (1, 4)  # LSP is 0-indexed
        assert service._busy is True

    def test_lsp_result_ignored_for_other_block_uri(self):
        """Shared LSP client must not show one block's ghost-text in another."""
        lsp = Mock()
        lsp.is_authenticated = True
        service = self._service()
        service.set_lsp_client(lsp)
        service.set_document_info("file:///sql.sql", "sql")

        results = []
        service.completion_ready.connect(results.append)
        service._on_lsp_result("file:///python.py", "df.head()")
        assert results == []

        service._on_lsp_result("file:///sql.sql", "SELECT 1")
        assert results == ["SELECT 1"]

    def test_on_complete_emits_and_releases(self):
        service = self._service()
        results = []
        service.completion_ready.connect(results.append)
        service._busy = True
        service._deliver_completion("df.head()")
        assert results == ["df.head()"]
        assert service._busy is False

    def test_on_worker_error_emits_empty(self):
        from PyQt6.QtCore import QObject

        service = self._service()
        worker = QObject()
        service._worker = worker
        results = []
        service.completion_ready.connect(results.append)
        service._busy = True
        service._on_worker_error(worker, "HTTP 401")
        assert results == [""]
        assert service._busy is False

    def test_watchdog_releases_stuck_request(self):
        service = self._service()
        results = []
        service.completion_ready.connect(results.append)
        service._busy = True
        service._on_watchdog()
        assert service._busy is False
        assert results == [""]

    def test_context_for_sql_uses_schema(self):
        service = self._service()
        service.set_database_context("Tables: users(id, name)")
        assert "users" in service._context_for("sql")

    def test_context_for_python_uses_namespace(self):
        service = self._service()
        service.set_python_namespace({"df": "DataFrame"})
        ctx = service._context_for("python")
        assert "df: DataFrame" in ctx




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
        assert callable(getattr(editor, "request_execute", None))
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

    def test_get_theme_returns_syntax_colors(self):
        from src.core.theme_manager import ThemeManager

        theme_manager = ThemeManager(initial_theme="dark")
        theme = theme_manager.get_theme()
        assert theme["sql"]["keyword"] == "#569cd6"
        assert theme["python"]["keyword"] == "#569cd6"

    def test_monaco_surface_colors_from_theme(self):
        from src.editors.monaco.monaco_editor import MonacoEditor
        from src.core.theme_manager import ThemeManager

        editor = MonacoEditor(theme_manager=ThemeManager(initial_theme="dark"))
        surface = editor._get_editor_surface_colors()
        assert surface["background"] == "#121a2b"
        assert "syntax" not in surface


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


class TestMonacoSqlAutocompleteIntegration:
    """Tests for Monaco SQL autocomplete bridge behavior."""

    def test_register_completions_allows_empty_payload_to_clear_state(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._run_js_when_ready = Mock()

        editor.register_completions([])

        editor._run_js_when_ready.assert_called_once_with("registerCompletions([])")

    def test_set_sql_schema_empty_clears_monaco_completions(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._run_js_when_ready = Mock()

        editor.set_sql_schema({})

        qtbot.waitUntil(lambda: editor._run_js_when_ready.call_count > 0, timeout=5000)
        emitted = [call.args[0] for call in editor._run_js_when_ready.call_args_list]
        assert any(call == "registerCompletions([])" for call in emitted)

    def test_set_sql_schema_with_tables_registers_new_schema(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._run_js_when_ready = Mock()

        editor.set_sql_schema(
            {
                "database": "controleproducao",
                "tables": [{"name": "venda", "schema": "dbo", "type": "TABLE"}],
                "columns": {"dbo.venda": [{"name": "id", "type": "int"}]},
            }
        )

        def _emitted_js():
            return [call.args[0] for call in editor._run_js_when_ready.call_args_list]

        qtbot.waitUntil(lambda: editor._run_js_when_ready.call_count > 0, timeout=5000)
        schema_calls = [c for c in _emitted_js() if c.startswith("registerSqlSchemaIndex(")]
        assert schema_calls
        assert "venda" in schema_calls[-1]
        assert "id" in schema_calls[-1]

        qtbot.waitUntil(
            lambda: any(
                c.startswith("registerCompletions(") and '"label": "SELECT"' in c
                for c in _emitted_js()
            ),
            timeout=5000,
        )
        completion_calls = [c for c in _emitted_js() if c.startswith("registerCompletions(")]
        assert completion_calls
        assert '"label": "SELECT"' in completion_calls[-1]

    def test_set_sql_schema_is_idempotent_for_same_schema(self, qtbot):
        """Re-applying the SAME schema (every block focus did this) must NOT
        re-register completions in Monaco — that froze the editor."""
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)

        schema = {
            "database": "controleproducao",
            "tables": [{"name": "venda", "schema": "dbo", "type": "TABLE"}],
            "columns": {"dbo.venda": [{"name": "id", "type": "int"}]},
        }
        editor.set_sql_schema(schema)

        editor._run_js_when_ready = Mock()
        # Same object re-applied (the focus path): no JS work.
        editor.set_sql_schema(schema)
        assert editor._run_js_when_ready.call_count == 0

        # A genuinely different schema DOES re-register.
        editor.set_sql_schema(
            {
                "database": "controleproducao",
                "tables": [{"name": "cliente", "schema": "dbo", "type": "TABLE"}],
                "columns": {"dbo.cliente": [{"name": "nome", "type": "varchar"}]},
            }
        )
        qtbot.waitUntil(lambda: editor._run_js_when_ready.call_count > 0, timeout=5000)
        emitted = [c.args[0] for c in editor._run_js_when_ready.call_args_list]
        assert any(c.startswith("registerSqlSchemaIndex(") for c in emitted)

    def test_sql_completion_uses_zero_based_service_coordinates(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._run_js_when_ready = Mock()

        with patch("src.services.sql_autocomplete_service.SqlAutoCompleteService") as service_cls:
            service = service_cls.return_value
            service.get_completions.return_value = [("total", "column", "decimal(18,2)")]

            with qtbot.waitSignal(editor._completion_service.sql_completions_ready, timeout=3000):
                editor._on_sql_completion_requested("SELECT o.", 2, 9, 42)

            service.get_completions.assert_called_once_with("SELECT o.", 1, 8)
            emitted = editor._run_js_when_ready.call_args[0][0]
            assert "receiveSqlCompletions(42," in emitted
            assert '"label": "total"' in emitted
            assert '"kind": "field"' in emitted

    def test_sql_context_completion_preserves_variable_kind(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._run_js_when_ready = Mock()

        with patch("src.services.sql_autocomplete_service.SqlAutoCompleteService") as service_cls:
            service = service_cls.return_value
            service.get_completions.return_value = [("@status", "variable", "VARCHAR(20)")]

            with qtbot.waitSignal(editor._completion_service.sql_context_completions_ready, timeout=3000):
                editor._on_sql_context_requested("SELECT @", "@", 1, 8, 7)

            service.get_completions.assert_called_once_with("SELECT @", 0, 7)
            emitted = editor._run_js_when_ready.call_args[0][0]
            assert "receiveSqlContextCompletions(7," in emitted
            assert '"label": "@status"' in emitted
            assert '"kind": "variable"' in emitted


class TestMonacoCompletionWorkers:
    """Regression tests for async SQL/Python completion worker lifecycle."""

    def test_update_sql_completions_registers_schema_index_not_bulk_list(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._push_merged_completions = Mock()
        editor._run_js_when_ready = Mock()

        schema = {"tables": ["orders"], "columns": {"orders": ["id"]}}
        editor.update_sql_completions(schema)
        editor.update_sql_completions(schema)

        editor._push_merged_completions.assert_not_called()
        assert editor._run_js_when_ready.call_count >= 1
        emitted = editor._run_js_when_ready.call_args_list[-1][0][0]
        assert "registerSqlSchemaIndex" in emitted
        assert "registerCompletions" not in emitted

    def test_update_python_completions_survives_finished_worker(self, qtbot):
        from src.editors.monaco.monaco_editor import MonacoEditor

        editor = MonacoEditor()
        qtbot.addWidget(editor)
        editor._push_merged_completions = Mock()

        namespace = {"df": object()}
        editor.update_python_completions(namespace)
        qtbot.waitUntil(lambda: editor._python_completion_worker is None, timeout=5000)

        editor.update_python_completions(namespace)
        qtbot.waitUntil(lambda: editor._python_completion_worker is None, timeout=5000)

        assert editor._push_merged_completions.call_count >= 1

