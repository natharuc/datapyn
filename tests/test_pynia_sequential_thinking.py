"""Tests for Pynia sequential thinking helpers."""

from src.services.pynia.sequential_thinking import (
    SEQUENTIAL_THINKING_PROMPT,
    summarize_planned_tools,
)
from src.services.pynia.system_prompt import build_system_prompt


def test_system_prompt_includes_sequential_thinking():
    prompt = build_system_prompt()
    assert "SEQUENTIAL THINKING" in prompt
    assert SEQUENTIAL_THINKING_PROMPT.strip() in prompt


def test_summarize_planned_tools_lists_actions():
    prepared = [
        ("datapyn_edit", {"block_name": "calendario", "operation": "lines"}, "t1", True),
        ("datapyn_inspect", {"block_name": "x"}, "t2", False),
    ]
    text = summarize_planned_tools(prepared)
    assert "calendario" in text
    assert "datapyn_inspect" not in text
