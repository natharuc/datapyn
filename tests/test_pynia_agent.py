"""Tests for Pynia multi-provider agent layer."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.pynia.openai_agent_loop import run_openai_agent_turn
from src.services.pynia.settings import get_pynia_settings, set_provider_secret
from src.services.pynia.types import PROVIDERS


class TestPyniaSettings:
    def test_provider_defaults(self):
        assert "openai" in PROVIDERS
        assert PROVIDERS["openai"].auth_kind == "api_token"
        assert PROVIDERS["copilot"].auth_kind == "device_mfa"

    def test_token_storage_roundtrip(self):
        set_provider_secret("openai", "test-token-xyz")
        from src.services.pynia.settings import get_provider_secret

        assert get_provider_secret("openai") == "test-token-xyz"
        set_provider_secret("openai", "")


class TestOpenAIAgentLoop:
    def test_tool_loop_executes_and_continues(self):
        chunks = []
        tool_calls = []
        tool_results = []

        def execute_tool(name, args):
            tool_results.append((name, args))
            return "ok-result"

        sse_lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"datapyn_notify","arguments":"{\\"title\\":\\"t\\",\\"message\\":\\"hi\\"}"}}]}}]}',
            "data: [DONE]",
        ]

        class FakeResp:
            status_code = 200
            text = ""

            def iter_lines(self):
                for line in sse_lines:
                    yield line.encode("utf-8")

        second_sse = [
            'data: {"choices":[{"delta":{"content":"Done."}}]}',
            "data: [DONE]",
        ]

        call_count = {"n": 0}

        def fake_post(*_args, **_kwargs):
            call_count["n"] += 1
            resp = FakeResp()
            if call_count["n"] == 1:
                resp.iter_lines = lambda: (line.encode("utf-8") for line in sse_lines)
            else:
                resp.iter_lines = lambda: (line.encode("utf-8") for line in second_sse)
            return resp

        with patch("requests.post", side_effect=fake_post):
            final = run_openai_agent_turn(
                base_url="https://api.example.com/v1",
                api_key="key",
                model="gpt-4o",
                messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "datapyn_notify",
                            "description": "notify",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                attachments=None,
                execute_tool=execute_tool,
                on_chunk=chunks.append,
                on_tool_call=lambda n, a, i: tool_calls.append((n, a, i)),
                on_tool_result=lambda n, r, i: None,
                is_cancelled=lambda: False,
            )

        assert tool_calls
        assert tool_results
        assert "Done." in final


@pytest.mark.qt
class TestPyniaAgentClient:
    def test_set_provider_emits_signal(self, qtbot):
        from src.services.pynia.agent_client import PyniaAgentClient

        client = PyniaAgentClient()
        start_provider = client.provider_id
        target = "anthropic" if start_provider != "anthropic" else "openai"
        with qtbot.waitSignal(client.provider_changed, timeout=1000):
            client.set_provider(target)
        assert client.provider_id == target
        client.cleanup()
