"""Integration tests for Pynia chat tool loop (no live API)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.pynia.openai_agent_loop import run_openai_agent_turn
from src.services.pynia.tools.registry import PyniaToolRegistry


def test_block_editor_exposes_set_pynia_client(qapp):
    from src.editors.block_editor import BlockEditor

    editor = BlockEditor()
    assert hasattr(editor, "set_pynia_client")
    client = MagicMock()
    editor.set_pynia_client(client)
    assert editor._pynia_client is client
    for block in editor.blocks:
        assert block._completion_service._pynia_client is client
    editor.close()


def test_pynia_registry_pins_legacy_session():
    legacy = MagicMock()
    registry = PyniaToolRegistry(parent=None, legacy_registry=legacy)
    registry.pin_session("sess-1")
    legacy.pin_session.assert_called_once_with("sess-1")
    registry.unpin_session()
    legacy.unpin_session.assert_called_once()


def test_openai_loop_completes_after_tool_round():
    """Smoke test: tool round then assistant text (regression guard)."""
    tool_results = []

    def execute_tool(name, args):
        tool_results.append(name)
        return "block outline ok"

    sse_round1 = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"datapyn_inspect","arguments":"{\\"kind\\":\\"block\\",\\"block_name\\":\\"b3\\",\\"detail\\":\\"structure\\"}"}}]}}]}',
        "data: [DONE]",
    ]
    sse_round2 = [
        'data: {"choices":[{"delta":{"content":"Pronto."}}]}',
        "data: [DONE]",
    ]
    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        text = ""

        def iter_lines(self):
            lines = sse_round1 if call_count["n"] == 1 else sse_round2
            for line in lines:
                yield line.encode("utf-8")

    def fake_post(*_a, **_k):
        call_count["n"] += 1
        return FakeResp()

    with patch("requests.post", side_effect=fake_post):
        final = run_openai_agent_turn(
            base_url="https://api.example.com/v1",
            api_key="key",
            model="gpt-4o",
            messages=[{"role": "user", "content": "fix filters"}],
            tools=[],
            attachments=None,
            execute_tool=execute_tool,
            on_chunk=lambda _c: None,
            on_tool_call=lambda _n, _a, _i: None,
            on_tool_result=lambda _n, _r, _i: None,
            is_cancelled=lambda: False,
        )

    assert final == "Pronto."
    assert tool_results == ["datapyn_inspect"]
