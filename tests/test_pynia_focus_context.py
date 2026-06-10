"""Tests for Pynia focused-block context."""

from unittest.mock import MagicMock

from src.services.pynia.focus_context import (
    apply_focused_block_defaults,
    focused_block_chip_payload,
    focused_block_payload,
    start_here_directive,
)


def test_focused_block_payload_includes_code():
    block = MagicMock()
    block.get_code.return_value = "SELECT 1\n" * 50
    block.get_block_name.return_value = "vendas"
    block.get_language.return_value = "sql"
    block.has_selection.return_value = False

    editor = MagicMock()
    editor.get_last_focused_block.return_value = block
    editor.blocks = [block]

    payload = focused_block_payload(editor, max_lines=100)
    assert payload is not None
    assert payload["name"] == "vendas"
    assert "SELECT 1" in payload["code"]


def test_focused_block_chip_payload_label():
    block = MagicMock()
    block.get_code.return_value = "x = 1\n" * 10
    block.get_block_name.return_value = "calendario"
    block.get_language.return_value = "python"
    block.has_selection.return_value = False

    editor = MagicMock()
    editor.get_last_focused_block.return_value = block
    editor.blocks = [block]

    chip = focused_block_chip_payload(editor)
    assert chip is not None
    assert chip["label"] == "calendario:1-10"
    assert chip["type"] == "focused_block"
    assert chip["block_name"] == "calendario"


def test_start_here_directive_names_block():
    text = start_here_directive({"name": "home_ui", "language": "python", "lines": 400, "hints": []})
    assert "home_ui" in text
    assert "START HERE" in text


def test_apply_focus_defaults_adds_block_name():
    legacy = MagicMock()
    legacy._main_window = MagicMock()
    legacy._get_active_session_widget.return_value = MagicMock()
    block = MagicMock()
    block.get_code.return_value = "x = 1"
    block.get_block_name.return_value = "main"
    block.get_language.return_value = "python"
    block.has_selection.return_value = False
    editor = MagicMock()
    editor.get_last_focused_block.return_value = block
    editor.blocks = [block]
    legacy._get_block_editor.return_value = editor

    out = apply_focused_block_defaults("datapyn_edit", {"operation": "lines"}, legacy)
    assert out.get("block_name") == "main"


def _legacy_with_focused_block(name: str = "main"):
    legacy = MagicMock()
    legacy._main_window = MagicMock()
    legacy._get_active_session_widget.return_value = MagicMock()
    block = MagicMock()
    block.get_code.return_value = "x = 1"
    block.get_block_name.return_value = name
    block.get_language.return_value = "python"
    block.has_selection.return_value = False
    editor = MagicMock()
    editor.get_last_focused_block.return_value = block
    editor.blocks = [block]
    legacy._get_block_editor.return_value = editor
    return legacy


def test_apply_focus_defaults_skips_run_mode_write():
    """mode=write without block_name means CREATE — must not target the focused block."""
    legacy = _legacy_with_focused_block()
    out = apply_focused_block_defaults(
        "datapyn_run", {"mode": "write", "code": "SELECT 1"}, legacy
    )
    assert "block_name" not in out


def test_apply_focus_defaults_still_applies_to_run_mode_block():
    legacy = _legacy_with_focused_block("main")
    out = apply_focused_block_defaults("datapyn_run", {"mode": "block"}, legacy)
    assert out.get("block_name") == "main"
