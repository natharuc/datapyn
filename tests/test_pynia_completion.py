"""Tests for Pynia inline autocomplete helpers."""

from src.services.pynia.completion import build_inline_prompt, clean_completion_text


def test_build_inline_prompt_includes_cursor():
    prompt = build_inline_prompt(
        language="sql",
        prefix="SELECT ",
        suffix=" FROM t",
        context="tables: t",
    )
    assert "<CURSOR>" in prompt
    assert "sql" in prompt.lower()
    assert "tables: t" in prompt


def test_clean_completion_strips_fences():
    raw = "```python\nfoo()\n```"
    assert clean_completion_text(raw, "SELECT ", "") == "foo()"
