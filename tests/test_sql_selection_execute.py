"""Regression: SQL selection execute must use live editor selection, not stale cache."""

from unittest.mock import MagicMock, call

import pytest

from src.editors.block_editor import BlockEditor


def test_execute_smart_uses_monaco_request_execute(qtbot):
    editor = BlockEditor()
    qtbot.addWidget(editor)

    block = MagicMock()
    monaco = MagicMock()
    monaco.request_execute = MagicMock()
    block.editor = monaco
    block.has_selection.return_value = True
    block.get_selected_text.return_value = "stale selection"
    block.get_language.return_value = "sql"

    editor._focused_block = block
    editor._execute_smart()

    monaco.request_execute.assert_called_once()
    block.get_selected_text.assert_not_called()


def test_run_button_uses_request_execute(qtbot):
    from src.editors.code_block import CodeBlock

    block = CodeBlock.__new__(CodeBlock)
    block._is_running = False
    block.editor = MagicMock()
    block.editor.request_execute = MagicMock()
    block.cancel_requested = MagicMock()
    block.execute_requested = MagicMock()

    block._on_run_btn_clicked()

    block.editor.request_execute.assert_called_once()
    block.execute_requested.emit.assert_not_called()


def test_monaco_request_execute_runs_trigger_js(qtbot):
    from src.editors.monaco.monaco_editor import MonacoEditor

    monaco = MonacoEditor()
    qtbot.addWidget(monaco)
    monaco._is_ready = True
    monaco._run_js = MagicMock()

    monaco.request_execute()

    monaco._run_js.assert_called_once_with("triggerExecute()")
