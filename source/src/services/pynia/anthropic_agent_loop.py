"""Anthropic Messages API with tool use."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"


def _mcp_tools_to_anthropic(openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for tool in openai_tools:
        fn = tool.get("function") or {}
        props = (fn.get("parameters") or {}).get("properties") or {}
        required = (fn.get("parameters") or {}).get("required") or []
        schema = {
            "type": "object",
            "properties": props,
            "required": required,
        }
        out.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": schema,
            }
        )
    return out


def _split_system(messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    system_parts = []
    rest = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg.get("content", "")))
        else:
            rest.append(msg)
    return "\n\n".join(system_parts), rest


def _to_anthropic_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    converted = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            converted.append({"role": "user", "content": msg.get("content", "")})
        elif role == "assistant":
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": json.loads(fn.get("arguments") or "{}"),
                    }
                )
            converted.append({"role": "assistant", "content": content or msg.get("content", "")})
        elif role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id"),
                            "content": msg.get("content", ""),
                        }
                    ],
                }
            )
    return converted


def run_anthropic_agent_turn(
    *,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    attachments: Optional[List[Dict[str, Any]]],
    execute_tool: Callable[[str, Dict[str, Any]], str],
    tool_executor: Any = None,
    subagent_orchestrator: Any = None,
    on_chunk: Callable[[str], None],
    on_tool_call: Callable[[str, dict, str], None],
    on_tool_result: Callable[[str, str, str], None],
    is_cancelled: Callable[[], bool],
    max_tool_rounds: int = 10,
) -> str:
    from src.services.pynia.agent_loop_policy import MAX_TOOL_ROUNDS, prepare_tool_calls
    from src.services.pynia.tool_round_executor import process_tool_round

    max_tool_rounds = min(max_tool_rounds, MAX_TOOL_ROUNDS)
    import requests

    from .openai_agent_loop import _inject_attachments

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    anthropic_tools = _mcp_tools_to_anthropic(tools)
    conversation = _inject_attachments(messages, attachments)
    system_text, conv_msgs = _split_system(conversation)
    anthropic_messages = _to_anthropic_messages(conv_msgs)
    final_text = ""
    seen_tool_keys: set[str] = set()

    for _round in range(max_tool_rounds):
        if is_cancelled():
            return final_text

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "messages": anthropic_messages,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=180)
        if resp.status_code == 401:
            raise RuntimeError("Invalid Claude API token.")
        if resp.status_code != 200:
            body = resp.text[:500] if resp.text else ""
            raise RuntimeError(f"Claude API error HTTP {resp.status_code}: {body}")

        round_text = ""
        tool_uses: List[Dict[str, Any]] = []
        current_tool: Optional[Dict[str, Any]] = None

        for line in resp.iter_lines():
            if is_cancelled():
                return final_text + round_text
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    round_text += text
                    final_text += text
                    on_chunk(text)
            elif etype == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    current_tool = {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input_json": "",
                    }
            elif etype == "content_block_delta" and (event.get("delta") or {}).get("type") == "input_json_delta":
                if current_tool is not None:
                    current_tool["input_json"] += event["delta"].get("partial_json", "")
            elif etype == "content_block_stop" and current_tool is not None:
                try:
                    args = json.loads(current_tool.get("input_json") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_uses.append(
                    {
                        "id": current_tool["id"],
                        "name": current_tool["name"],
                        "input": args,
                    }
                )
                current_tool = None

        if not tool_uses:
            return final_text

        assistant_content: List[Dict[str, Any]] = []
        if round_text:
            assistant_content.append({"type": "text", "text": round_text})
        openai_tool_calls = []
        for tu in tool_uses:
            tc_id = tu["id"] or f"toolu_{uuid.uuid4().hex[:12]}"
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tc_id,
                    "name": tu["name"],
                    "input": tu["input"],
                }
            )
            openai_tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tu["name"],
                        "arguments": json.dumps(tu["input"]),
                    },
                }
            )
        anthropic_messages.append({"role": "assistant", "content": assistant_content})

        parsed = [
            (tu["name"], tu["input"], tu["id"] or f"toolu_{uuid.uuid4().hex[:12]}")
            for tu in tool_uses
        ]
        prepared = prepare_tool_calls(parsed, seen_keys=seen_tool_keys)

        round_outcomes = process_tool_round(
            prepared,
            seen_keys=seen_tool_keys,
            execute_tool=execute_tool,
            tool_executor=tool_executor,
            subagent_orchestrator=subagent_orchestrator,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            is_cancelled=is_cancelled,
        )
        tool_results = [
            {"type": "tool_result", "tool_use_id": tc_id, "content": result}
            for tc_id, _name, result in round_outcomes
        ]
        anthropic_messages.append({"role": "user", "content": tool_results})

    return final_text
