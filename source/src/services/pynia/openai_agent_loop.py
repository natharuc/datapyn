"""OpenAI-compatible chat completions with tool calling (OpenAI, OpenRouter)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _strip_optional_from_schema(properties: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {}
    for name, spec in properties.items():
        item = dict(spec)
        item.pop("optional", None)
        cleaned[name] = item
    return cleaned


def tools_to_openai(registry_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tool schemas to OpenAI tools format."""
    return registry_tools


def run_openai_agent_turn(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    attachments: Optional[List[Dict[str, Any]]],
    execute_tool: Callable[[str, Dict[str, Any]], str],
    on_chunk: Callable[[str], None],
    on_tool_call: Callable[[str, dict, str], None],
    on_tool_result: Callable[[str, str, str], None],
    is_cancelled: Callable[[], bool],
    max_tool_rounds: int = 24,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Run a full agent turn with streaming and tool loops.

    Returns the final assistant text for the turn.
    """
    import requests

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    conversation = _inject_attachments(messages, attachments)
    final_text = ""

    for _round in range(max_tool_rounds):
        if is_cancelled():
            return final_text

        payload: Dict[str, Any] = {
            "model": model,
            "messages": conversation,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=180)
        if resp.status_code == 401:
            raise RuntimeError("Invalid API token. Check your connector settings.")
        if resp.status_code != 200:
            body = resp.text[:500] if resp.text else ""
            raise RuntimeError(f"API error HTTP {resp.status_code}: {body}")

        assistant_content = ""
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}

        for line in resp.iter_lines():
            if is_cancelled():
                return final_text + assistant_content
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content") or ""
            if content:
                assistant_content += content
                final_text += content
                on_chunk(content)

            for tc_delta in delta.get("tool_calls") or []:
                idx = tc_delta.get("index", 0)
                entry = tool_calls_acc.setdefault(
                    idx,
                    {"id": "", "name": "", "arguments": ""},
                )
                if tc_delta.get("id"):
                    entry["id"] = tc_delta["id"]
                fn = tc_delta.get("function") or {}
                if fn.get("name"):
                    entry["name"] = fn["name"]
                if fn.get("arguments"):
                    entry["arguments"] += fn["arguments"]

        if not tool_calls_acc:
            return final_text

        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": assistant_content or None}
        openai_tool_calls = []
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            tc_id = tc["id"] or f"call_{uuid.uuid4().hex[:12]}"
            openai_tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"] or "{}",
                    },
                }
            )
        assistant_msg["tool_calls"] = openai_tool_calls
        conversation.append(assistant_msg)

        for tc in openai_tool_calls:
            if is_cancelled():
                return final_text
            fn = tc["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            on_tool_call(name, args, tc["id"])
            result = execute_tool(name, args)
            on_tool_result(name, result, tc["id"])
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
            )

    return final_text


def _inject_attachments(
    messages: List[Dict[str, Any]],
    attachments: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    if not attachments:
        return [dict(m) for m in messages]

    result = [dict(m) for m in messages]
    for idx in range(len(result) - 1, -1, -1):
        if result[idx].get("role") != "user":
            continue
        text = result[idx].get("content", "")
        parts: List[Dict[str, Any]] = [{"type": "text", "text": text}]
        for att in attachments:
            path = att.get("path") or att.get("file_path")
            mime = att.get("mime_type") or att.get("media_type") or "image/png"
            if not path:
                continue
            try:
                import base64
                from pathlib import Path

                data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )
            except Exception as exc:
                logger.warning("Skipping attachment %s: %s", path, exc)
        result[idx] = {"role": "user", "content": parts}
        break
    return result


def fetch_openai_models(base_url: str, api_key: str) -> List[Dict[str, Any]]:
    import requests

    url = f"{base_url.rstrip('/')}/models"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    models = []
    for item in data.get("data", []):
        mid = item.get("id", "")
        if mid:
            models.append({"id": mid, "name": mid, "multiplier": 1.0})
    return models
