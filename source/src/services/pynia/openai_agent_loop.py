"""OpenAI-compatible chat completions with tool calling (OpenAI, OpenRouter)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from src.services.pynia.agent_progress import ProgressCallback, emit_progress
from src.services.pynia.agent_loop_policy import (
    FORCE_ANSWER_AFTER_ROUND,
    MAX_TOOL_ROUNDS,
    invalidate_block_reads,
    prepare_tool_calls,
    should_offer_tools,
)
from src.services.pynia.session_memory import FORCE_ANSWER_NUDGE, compact_conversation_in_place
from src.services.pynia.agent_status import PHASE_ANALYZING, PHASE_PLANNING, PHASE_SYNTHESIZING
from src.services.pynia.tool_round_executor import process_tool_round

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


def _merge_reasoning_detail_deltas(acc: List[Dict[str, Any]], delta_items: Any) -> None:
    """Merge OpenRouter reasoning_details stream chunks (required for tool loops)."""
    if not isinstance(delta_items, list):
        return
    for item in delta_items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if index is None:
            acc.append(dict(item))
            continue
        try:
            idx = int(index)
        except (TypeError, ValueError):
            acc.append(dict(item))
            continue
        while len(acc) <= idx:
            acc.append({})
        merged = acc[idx]
        for key, val in item.items():
            if key in ("text", "summary") and isinstance(val, str):
                merged[key] = str(merged.get(key, "")) + val
            elif key != "index":
                merged[key] = val


def _stream_openai_completion(
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    on_chunk: Callable[[str], None],
    on_progress: ProgressCallback,
    round_idx: int,
    is_cancelled: Callable[[], bool],
) -> tuple[str, List[Dict[str, Any]], str, List[Dict[str, Any]]]:
    """Stream one chat completion; returns content, tool calls, reasoning text, reasoning_details."""
    import requests

    from src.services.pynia.sequential_thinking import emit_thinking_step

    resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=180)
    if resp.status_code == 401:
        raise RuntimeError("Invalid API token. Check your connector settings.")
    if resp.status_code != 200:
        body = resp.text[:500] if resp.text else ""
        raise RuntimeError(f"API error HTTP {resp.status_code}: {body}")

    assistant_content = ""
    tool_calls_acc: Dict[int, Dict[str, Any]] = {}
    reasoning_stream = ""
    reasoning_details_acc: List[Dict[str, Any]] = []

    for line in resp.iter_lines():
        if is_cancelled():
            break
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

        for key in ("reasoning_content", "reasoning"):
            part = delta.get(key) or ""
            if part:
                reasoning_stream += part
                if on_progress:
                    from src.services.pynia.agent_progress import emit_progress

                    emit_progress(
                        on_progress,
                        phase_key=PHASE_PLANNING,
                        step_id=f"reasoning-{round_idx}",
                        reasoning=part,
                        reasoning_delta=True,
                    )

        _merge_reasoning_detail_deltas(reasoning_details_acc, delta.get("reasoning_details"))

        content = delta.get("content") or ""
        if content:
            assistant_content += content
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

    openai_tool_calls: List[Dict[str, Any]] = []
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

    return assistant_content, openai_tool_calls, reasoning_stream, reasoning_details_acc


def _run_final_synthesis(
    *,
    url: str,
    headers: Dict[str, str],
    model: str,
    conversation: List[Dict[str, Any]],
    on_chunk: Callable[[str], None],
    is_cancelled: Callable[[], bool],
) -> str:
    """One last no-tools call when the model returned only reasoning/tool rounds."""
    synthesis_messages = list(conversation)
    synthesis_messages.append(
        {
            "role": "user",
            "content": (
                "Reply to the user now in their language. Summarize tool results and errors. "
                "If the task is incomplete, state what is still missing. Do not call tools."
            ),
        }
    )
    text, _, _, _ = _stream_openai_completion(
        url=url,
        headers=headers,
        payload={"model": model, "messages": synthesis_messages, "stream": True},
        on_chunk=on_chunk,
        on_progress=None,
        round_idx=99,
        is_cancelled=is_cancelled,
    )
    return text


def run_openai_agent_turn(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    attachments: Optional[List[Dict[str, Any]]],
    execute_tool: Callable[[str, Dict[str, Any]], str],
    tool_executor: Any = None,
    subagent_orchestrator: Any = None,
    on_progress: ProgressCallback = None,
    on_chunk: Callable[[str], None],
    on_tool_call: Callable[[str, dict, str], None],
    on_tool_result: Callable[[str, str, str], None],
    is_cancelled: Callable[[], bool],
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Run a full agent turn with streaming and tool loops.

    Returns the final assistant text for the turn.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    conversation = _inject_attachments(messages, attachments)
    final_text = ""
    planning_buffer = ""
    tools_were_used = False
    seen_tool_keys: set[str] = set()
    block_inspect_counts: dict[str, int] = {}

    from src.services.pynia.sequential_thinking import emit_thinking_step, round_step_title

    emit_thinking_step(
        on_progress,
        title=round_step_title(0, planning=True),
        body="Reviewing focused block and workspace context.",
        step_id="plan-start",
    )

    for round_idx in range(max_tool_rounds):
        if is_cancelled():
            return final_text

        emit_progress(
            on_progress,
            phase_key=PHASE_ANALYZING if round_idx == 0 else PHASE_SYNTHESIZING,
            step_id="model",
            step_state="active",
        )

        offer_tools = should_offer_tools(round_idx, max_rounds=max_tool_rounds) and bool(tools)
        if round_idx == FORCE_ANSWER_AFTER_ROUND:
            conversation.append({"role": "user", "content": FORCE_ANSWER_NUDGE})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": conversation,
            "stream": True,
        }
        if offer_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        round_content_buffer = ""

        def _stream_chunk(chunk: str) -> None:
            nonlocal round_content_buffer
            round_content_buffer += chunk

        assistant_content, openai_tool_calls, reasoning_stream, reasoning_details_acc = (
            _stream_openai_completion(
                url=url,
                headers=headers,
                payload=payload,
                on_chunk=_stream_chunk,
                on_progress=on_progress,
                round_idx=round_idx,
                is_cancelled=is_cancelled,
            )
        )

        if openai_tool_calls:
            if round_content_buffer:
                planning_buffer += round_content_buffer
        elif round_content_buffer:
            if not offer_tools:
                final_text += round_content_buffer
                on_chunk(round_content_buffer)
            else:
                planning_buffer += round_content_buffer

        if not openai_tool_calls:
            if assistant_content.strip() and not offer_tools:
                return final_text
            if not offer_tools:
                logger.warning(
                    "OpenAI-compatible turn: empty final response at round %s",
                    round_idx,
                )
                break
            continue

        tools_were_used = True
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": assistant_content or None}
        if reasoning_stream:
            assistant_msg["reasoning"] = reasoning_stream
        if reasoning_details_acc:
            details = [d for d in reasoning_details_acc if d]
            if details:
                assistant_msg["reasoning_details"] = details
        assistant_msg["tool_calls"] = openai_tool_calls
        conversation.append(assistant_msg)

        parsed_calls = []
        for tc in openai_tool_calls:
            fn = tc["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append((name, args, tc["id"]))

        prepared = prepare_tool_calls(
            parsed_calls,
            seen_keys=seen_tool_keys,
            block_inspect_counts=block_inspect_counts,
        )

        from src.services.pynia.sequential_thinking import emit_planned_tools_thinking

        emit_planned_tools_thinking(on_progress, round_idx, prepared)

        if len(parsed_calls) > len([p for p in prepared if p[3]]) and round_idx == 0:
            logger.info(
                "Tool round: %s requested, %s executing (dedupe/limit)",
                len(parsed_calls),
                sum(1 for p in prepared if p[3]),
            )

        round_outcomes = process_tool_round(
            prepared,
            seen_keys=seen_tool_keys,
            execute_tool=execute_tool,
            tool_executor=tool_executor,
            subagent_orchestrator=subagent_orchestrator,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
        for tc_id, _name, result in round_outcomes:
            conversation.append(
                {"role": "tool", "tool_call_id": tc_id, "content": result}
            )
        compact_conversation_in_place(conversation)
        for name, args, _tc_id, should_execute in prepared:
            if should_execute:
                invalidate_block_reads(
                    name,
                    args,
                    seen_keys=seen_tool_keys,
                    block_inspect_counts=block_inspect_counts,
                )

        if not offer_tools:
            continue

        if round_idx >= max_tool_rounds - 1:
            logger.warning("Max tool rounds (%s) reached", max_tool_rounds)
            break

    needs_synthesis = tools_were_used and not final_text.strip()
    if needs_synthesis:
        logger.info(
            "OpenAI-compatible turn: running final synthesis (tools=%s, planning_chars=%s)",
            tools_were_used,
            len(planning_buffer),
        )
        synthesis_text = ""

        def _append_synthesis(chunk: str) -> None:
            nonlocal synthesis_text
            synthesis_text += chunk
            on_chunk(chunk)

        _run_final_synthesis(
            url=url,
            headers=headers,
            model=model,
            conversation=conversation,
            on_chunk=_append_synthesis,
            is_cancelled=is_cancelled,
        )
        if synthesis_text.strip():
            final_text = synthesis_text

    logger.info(
        "OpenAI-compatible turn complete: final_chars=%s synthesis=%s planning_chars=%s",
        len(final_text),
        needs_synthesis,
        len(planning_buffer),
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


def _format_usd_per_million(rate: Any) -> str:
    try:
        per_token = float(rate)
    except (TypeError, ValueError):
        return ""
    if per_token <= 0:
        return "free"
    per_m = per_token * 1_000_000
    if per_m >= 1:
        return f"${per_m:.2f}/M"
    if per_m >= 0.01:
        return f"${per_m:.2f}/M"
    return f"${per_m:.3f}/M"


def _openrouter_price_label(item: dict) -> str:
    pricing = item.get("pricing") or {}
    if not isinstance(pricing, dict):
        return ""
    in_price = _format_usd_per_million(pricing.get("prompt"))
    out_price = _format_usd_per_million(pricing.get("completion"))
    if in_price and out_price:
        return f"{in_price} in · {out_price} out"
    return in_price or out_price


def _openrouter_chat_model(item: dict) -> bool:
    mid = str(item.get("id") or "").lower()
    if not mid or "embed" in mid:
        return False
    arch = item.get("architecture") or {}
    if isinstance(arch, dict):
        outputs = arch.get("output_modalities") or []
        modality = str(arch.get("modality") or "").lower()
        if outputs and "text" not in outputs:
            return False
        if modality and "text" not in modality and "->" in modality:
            return False
    return True


def fetch_openai_models(
    base_url: str,
    api_key: str,
    *,
    extra_headers: Optional[Dict[str, str]] = None,
    provider_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    import requests

    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code != 200:
        logger.warning("Model list failed (%s): HTTP %s", url, resp.status_code)
        return []
    data = resp.json()
    is_openrouter = provider_id == "openrouter" or "openrouter.ai" in base_url
    models = []
    for item in data.get("data", []):
        if not isinstance(item, dict):
            continue
        if is_openrouter and not _openrouter_chat_model(item):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        name = str(item.get("name") or mid).strip() or mid
        entry: Dict[str, Any] = {"id": mid, "name": name}
        if is_openrouter:
            price_label = _openrouter_price_label(item)
            if price_label:
                entry["price_label"] = price_label
            ctx = item.get("context_length")
            if ctx:
                entry["context_length"] = ctx
        else:
            entry["multiplier"] = 1.0
        models.append(entry)
    return models
