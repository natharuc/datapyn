"""Pynia native system prompt tests."""

from src.services.pynia.system_prompt import build_request_prompt, build_system_prompt


def test_system_prompt_is_pynia_native():
    text = build_system_prompt(include_tool_catalog=False)
    assert "Pynia" in text
    assert "DataPyn" in text
    assert "SPEED" in text
    assert "do not" in text.lower() and "get_context" in text


def test_request_prompt_includes_directive():
    req = build_request_prompt("fix vendas query", '{"blocks":[]}')
    assert "Pynia directive" in req
    assert "fix vendas query" in req
