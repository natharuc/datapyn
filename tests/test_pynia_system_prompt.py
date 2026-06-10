"""Pynia native system prompt tests."""

from src.services.pynia.system_prompt import build_request_prompt, build_system_prompt


def test_system_prompt_is_pynia_native():
    text = build_system_prompt(include_tool_catalog=False)
    assert "Pynia" in text
    assert "DataPyn" in text
    assert "SPEED" in text
    assert "datapyn_snapshot" in text
    assert "datapyn_" in text
    assert "get_context" not in text or "no `get_context`" in text.lower() or "There is no" in text


def test_request_prompt_includes_directive():
    req = build_request_prompt("fix vendas query", '{"blocks":[]}')
    assert "Pynia directive" in req
    assert "fix vendas query" in req


def test_system_prompt_includes_subagents_by_default():
    text = build_system_prompt()
    assert "datapyn_subagent" in text
    assert "Parallel discovery" in text


def test_system_prompt_demands_honesty_about_actions():
    """The model must never narrate skipped/failed edits as applied."""
    text = build_system_prompt()
    assert "Honesty about actions" in text
    assert "NOT APPLIED" in text


def test_system_prompt_without_subagents_for_copilot():
    """Copilot has no API token for subagent workers — no mention should remain."""
    text = build_system_prompt(include_subagents=False)
    assert "datapyn_subagent" not in text
    assert "Parallel discovery" not in text
    # The rest of the prompt is intact.
    assert "datapyn_snapshot" in text
    assert "SPEED" in text
