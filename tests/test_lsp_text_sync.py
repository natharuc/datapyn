"""Tests for incremental LSP text sync helpers."""

from src.services.copilot.lsp_text_sync import compute_incremental_change, offset_to_position


def test_offset_to_position():
    text = "abc\ndef\nghi"
    assert offset_to_position(text, 0) == (0, 0)
    assert offset_to_position(text, 4) == (1, 0)
    assert offset_to_position(text, 6) == (1, 2)


def test_compute_incremental_change_inserts_middle():
    old = "hello world"
    new = "hello brave world"
    change = compute_incremental_change(old, new)
    assert change is not None
    assert change["range"]["start"] == {"line": 0, "character": 6}
    assert change["range"]["end"] == {"line": 0, "character": 6}
    assert change["text"] == "brave "


def test_compute_incremental_change_full_replace_on_empty_old():
    change = compute_incremental_change("", "print(1)")
    assert change == {"text": "print(1)"}


def test_compute_incremental_change_none_when_equal():
    assert compute_incremental_change("same", "same") is None
