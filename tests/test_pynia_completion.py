"""Tests for Pynia inline autocomplete helpers."""

from unittest.mock import MagicMock, patch

from src.services.pynia.completion import (
    build_inline_prompt,
    clean_completion_text,
    fetch_inline_completion,
)


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


@patch("requests.post")
@patch("src.services.pynia.completion.get_provider_secret", return_value="sk-test")
@patch("src.services.pynia.completion.get_pynia_settings")
def test_fetch_openai_compatible(mock_settings, _mock_secret, mock_post):
    mock_settings.return_value.base_url.return_value = "https://api.openai.com/v1"
    mock_post.return_value = MagicMock(
        status_code=200,
        text="",
        json=lambda: {"choices": [{"message": {"content": "COUNT(*)"}}]},
    )
    result = fetch_inline_completion(
        "openai",
        model="gpt-4o-mini",
        language="sql",
        prompt="complete",
    )
    assert result == "COUNT(*)"
