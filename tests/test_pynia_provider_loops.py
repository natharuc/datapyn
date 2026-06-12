"""End-to-end agent-loop tests for API providers (mocked HTTP streams).

Validates that the OpenAI-compatible and Anthropic loops parse streamed tool
calls, execute them, feed results back, and return the final answer — the
same path real OpenAI/OpenRouter/Anthropic traffic takes.
"""

import json
from unittest.mock import patch

from src.services.pynia.anthropic_agent_loop import (
    _convert_user_content,
    run_anthropic_agent_turn,
)
from src.services.pynia.openai_agent_loop import run_openai_agent_turn


class FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self.status_code = status_code
        self._lines = lines
        self.text = ""

    def iter_lines(self):
        for line in self._lines:
            yield line.encode("utf-8") if isinstance(line, str) else line


def _sse(payload) -> str:
    return "data: " + json.dumps(payload)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "datapyn_snapshot",
            "description": "Read state.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
        },
    }
]

MESSAGES = [
    {"role": "system", "content": "You are Pynia."},
    {"role": "user", "content": "lista os blocos"},
]


class TestOpenAILoop:
    def _round0_tool_call(self):
        return FakeStreamResponse([
            _sse({
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "datapyn_snapshot",
                                "arguments": json.dumps({"action": "blocks"}),
                            },
                        }]
                    }
                }]
            }),
            "data: [DONE]",
        ])

    def _round1_answer(self):
        return FakeStreamResponse([
            _sse({"choices": [{"delta": {"content": "4 blocos na aba."}}]}),
            "data: [DONE]",
        ])

    def test_full_turn_with_tool_call(self):
        executed = []

        def execute_tool(name, args):
            executed.append((name, args))
            return "blocks: sun, gecon"

        posted = []

        def fake_post(url, json=None, headers=None, stream=False, timeout=None):
            posted.append({"url": url, "payload": json, "headers": headers})
            return self._round0_tool_call() if len(posted) == 1 else self._round1_answer()

        with (
            patch("src.services.pynia.agent_loop_policy.FORCE_ANSWER_AFTER_ROUND", 1),
            patch("requests.post", side_effect=fake_post),
        ):
            final = run_openai_agent_turn(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="gpt-4o",
                messages=MESSAGES,
                tools=TOOLS,
                attachments=None,
                execute_tool=execute_tool,
                on_chunk=lambda _c: None,
                on_tool_call=lambda *_a: None,
                on_tool_result=lambda *_a: None,
                is_cancelled=lambda: False,
            )

        assert final == "4 blocos na aba."
        assert executed == [("datapyn_snapshot", {"action": "blocks"})]

        assert posted[0]["url"] == "https://api.openai.com/v1/chat/completions"
        assert posted[0]["headers"]["Authorization"] == "Bearer sk-test"
        assert posted[0]["payload"]["tools"] == TOOLS

        # Round 1 must carry the assistant tool call + the tool result back.
        convo = posted[1]["payload"]["messages"]
        roles = [m["role"] for m in convo]
        assert "tool" in roles
        tool_msg = next(m for m in convo if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "call_1"
        assert "blocks: sun, gecon" in tool_msg["content"]

    def test_synthesis_after_tools_when_final_round_empty(self):
        """Planning text during tool rounds must not become the user-visible answer."""
        chunks: list[str] = []
        posted = []

        def fake_post(url, json=None, headers=None, stream=False, timeout=None):
            posted.append(json)
            payload = json
            if len(posted) == 1:
                return FakeStreamResponse([
                    _sse({
                        "choices": [{
                            "delta": {
                                "content": "Vou verificar os blocos.",
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "datapyn_snapshot",
                                        "arguments": '{"action": "blocks"}',
                                    },
                                }],
                            },
                        }]
                    }),
                    "data: [DONE]",
                ])
            if len(posted) == 2:
                return FakeStreamResponse([
                    _sse({"choices": [{"delta": {}}]}),
                    "data: [DONE]",
                ])
            return FakeStreamResponse([
                _sse({"choices": [{"delta": {"content": "Encontrei 4 blocos na aba."}}]}),
                "data: [DONE]",
            ])

        with (
            patch("src.services.pynia.agent_loop_policy.FORCE_ANSWER_AFTER_ROUND", 1),
            patch("requests.post", side_effect=fake_post),
        ):
            final = run_openai_agent_turn(
                base_url="https://openrouter.ai/api/v1",
                api_key="sk-test",
                model="anthropic/claude-sonnet-4.6",
                messages=MESSAGES,
                tools=TOOLS,
                attachments=None,
                execute_tool=lambda n, a: "blocks: sun, gecon",
                on_chunk=chunks.append,
                on_tool_call=lambda *_a: None,
                on_tool_result=lambda *_a: None,
                is_cancelled=lambda: False,
            )

        assert final == "Encontrei 4 blocos na aba."
        assert "Vou verificar" not in final
        assert chunks == ["Encontrei 4 blocos na aba."]
        assert len(posted) == 3

    def test_http_error_raises_readable_message(self):
        resp = FakeStreamResponse([], status_code=500)
        resp.text = "boom"
        with patch("requests.post", return_value=resp):
            try:
                run_openai_agent_turn(
                    base_url="https://api.openai.com/v1",
                    api_key="sk-test",
                    model="gpt-4o",
                    messages=MESSAGES,
                    tools=[],
                    attachments=None,
                    execute_tool=lambda n, a: "",
                    on_chunk=lambda _c: None,
                    on_tool_call=lambda *_a: None,
                    on_tool_result=lambda *_a: None,
                    is_cancelled=lambda: False,
                )
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "500" in str(exc)


class TestAnthropicLoop:
    def _round0_tool_use(self):
        return FakeStreamResponse([
            _sse({
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "datapyn_snapshot",
                },
            }),
            _sse({
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '{"action": '},
            }),
            _sse({
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '"blocks"}'},
            }),
            _sse({"type": "content_block_stop"}),
            _sse({"type": "message_stop"}),
        ])

    def _round1_answer(self):
        return FakeStreamResponse([
            _sse({
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "4 blocos na aba."},
            }),
            _sse({"type": "message_stop"}),
        ])

    def test_full_turn_streams_tool_arguments(self):
        """Tool inputs stream as partial JSON — they must reach the tool intact."""
        executed = []

        def execute_tool(name, args):
            executed.append((name, args))
            return "blocks: sun, gecon"

        posted = []

        def fake_post(url, json=None, headers=None, stream=False, timeout=None):
            posted.append({"url": url, "payload": json, "headers": headers})
            return self._round0_tool_use() if len(posted) == 1 else self._round1_answer()

        with patch("requests.post", side_effect=fake_post):
            final = run_anthropic_agent_turn(
                api_key="sk-ant-test",
                model="claude-sonnet-4-6",
                messages=MESSAGES,
                tools=TOOLS,
                attachments=None,
                execute_tool=execute_tool,
                on_chunk=lambda _c: None,
                on_tool_call=lambda *_a: None,
                on_tool_result=lambda *_a: None,
                is_cancelled=lambda: False,
            )

        assert final == "4 blocos na aba."
        # The regression this guards: input_json_delta was unreachable and all
        # Anthropic tool calls arrived with empty arguments.
        assert executed == [("datapyn_snapshot", {"action": "blocks"})]

        assert posted[0]["headers"]["x-api-key"] == "sk-ant-test"
        assert posted[0]["payload"]["system"] == "You are Pynia."
        assert posted[0]["payload"]["tools"][0]["name"] == "datapyn_snapshot"

        # Round 1 conversation carries tool_use + tool_result blocks.
        convo = posted[1]["payload"]["messages"]
        tool_result_msg = convo[-1]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "toolu_1"


def test_convert_user_content_maps_openai_image_parts():
    parts = [
        {"type": "text", "text": "veja o print"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]
    converted = _convert_user_content(parts)
    assert converted[0] == {"type": "text", "text": "veja o print"}
    assert converted[1]["type"] == "image"
    assert converted[1]["source"]["media_type"] == "image/png"
    assert converted[1]["source"]["data"] == "QUJD"


def test_fetch_anthropic_models_parses_listing():
    from src.services.pynia.anthropic_agent_loop import fetch_anthropic_models

    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [
                {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6"},
                {"id": "claude-opus-4-8", "display_name": "Claude Opus 4.8"},
            ]}

    with patch("requests.get", return_value=FakeResp()):
        models = fetch_anthropic_models("sk-ant-test")

    assert models[0]["id"] == "claude-sonnet-4-6"
    assert models[0]["name"] == "Claude Sonnet 4.6"
    assert len(models) == 2
