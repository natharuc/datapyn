"""Tests for human-readable Pynia agent status labels."""

from src.services.pynia.agent_status import format_tool_display


def test_format_inspect_block():
    title, detail = format_tool_display(
        "datapyn_inspect",
        {"kind": "block", "block_name": "sales", "detail": "code"},
    )
    assert "sales" in title
    assert detail == ""
    assert activity_line_for_tool(
        "datapyn_inspect",
        {"kind": "block", "block_name": "sales", "detail": "code"},
    )


def test_format_subagent():
    title, detail = format_tool_display(
        "datapyn_subagent",
        {"instruction": "List schema and variables"},
    )
    assert "Explore" in title or "explore" in title.lower()
    assert "schema" in detail
