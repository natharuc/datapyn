"""Tests for reasoning stream sanitization (DSML / tool markup)."""

from src.services.pynia.thinking_sanitize import sanitize_thinking_chunk, should_skip_thinking_stream


def test_skips_dsml_tool_invoke():
    raw = "<|DSML|invoke name=\"datapyn_inspect\">"
    assert should_skip_thinking_stream(raw)
    assert sanitize_thinking_chunk(raw) == ""


def test_allows_normal_reasoning():
    text = "Reviewing block1 SQL for missing GROUP BY."
    assert not should_skip_thinking_stream(text)
    assert sanitize_thinking_chunk(text) == text
