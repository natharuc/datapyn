"""Conversation memory for API providers (Copilot SDK keeps its own session)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 14
MAX_ASSISTANT_CHARS = 4000
MAX_TOOL_RESULT_CHARS_IN_HISTORY = 800


FORCE_ANSWER_NUDGE = (
    "**Pynia**: You have enough context from tools and focused_block_detail. "
    "Do not call more tools. Reply in chat with a concise answer, a short plan, "
    "or perform one `datapyn_edit` / `datapyn_run` if the user asked for a change."
)


def _truncate(text: str, limit: int) -> str:
    if not text or len(text) <= limit:
        return text or ""
    return text[: limit - 3].rstrip() + "..."


def history_from_ui_messages(
    messages: List[Dict[str, Any]],
    *,
    exclude_last: bool = True,
) -> List[Dict[str, str]]:
    """Extract user/assistant text pairs from panel storage (no tool payloads)."""
    items = messages[:-1] if exclude_last and messages else list(messages)
    out: List[Dict[str, str]] = []
    for msg in items:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            content = _truncate(content, MAX_ASSISTANT_CHARS)
        out.append({"role": role, "content": content})
    if len(out) > MAX_HISTORY_MESSAGES:
        out = out[-MAX_HISTORY_MESSAGES:]
    return out


def rolling_summary_from_history(history: List[Dict[str, str]]) -> str:
    """Lightweight session recap without an extra LLM call."""
    if not history:
        return ""
    user_turns = [m["content"] for m in history if m["role"] == "user"]
    if not user_turns:
        return ""
    recent = user_turns[-3:]
    lines = ["**Session recap** (prior turns in this chat):"]
    for i, text in enumerate(recent, 1):
        lines.append(f"{i}. {_truncate(text, 220)}")
    return "\n".join(lines)


def build_api_messages(
    *,
    system_prompt: str,
    current_user_prompt: str,
    ui_messages: Optional[List[Dict[str, Any]]] = None,
    include_history: bool = True,
) -> List[Dict[str, Any]]:
    """
    Messages for OpenAI / Anthropic / OpenRouter turns.

    Copilot uses SDK session memory; API providers get compact multi-turn history.
    """
    api: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if include_history and ui_messages:
        history = history_from_ui_messages(ui_messages)
        recap = rolling_summary_from_history(history)
        if recap:
            api.append({"role": "user", "content": recap})
            api.append(
                {
                    "role": "assistant",
                    "content": "Understood. I will use the recap and current workspace context.",
                }
            )
        for entry in history:
            api.append(dict(entry))
    api.append({"role": "user", "content": current_user_prompt})
    return api


def _last_tool_round_start(conversation: List[Dict[str, Any]]) -> int:
    """Index of the assistant message that issued the most recent tool round."""
    for i in range(len(conversation) - 1, -1, -1):
        msg = conversation[i]
        if msg.get("role") != "assistant":
            continue
        if msg.get("tool_calls"):
            return i
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in content
        ):
            return i
    return len(conversation)


def _compact_text(text: str, max_tool_chars: int) -> str:
    return _truncate(text, max_tool_chars) + "\n[truncated for session memory]"


def compact_conversation_in_place(
    conversation: List[Dict[str, Any]],
    *,
    max_tool_chars: int = MAX_TOOL_RESULT_CHARS_IN_HISTORY,
) -> None:
    """Shrink tool results from OLDER rounds to control token growth.

    The most recent round is left intact: the model still has to act on what
    it just read (e.g. block code fetched right before an edit). Handles both
    OpenAI-style (role="tool") and Anthropic-style (user message with
    tool_result blocks) conversations.
    """
    cutoff = _last_tool_round_start(conversation)
    for msg in conversation[:cutoff]:
        role = msg.get("role")
        content = msg.get("content")
        if role == "tool":
            if isinstance(content, str) and len(content) > max_tool_chars:
                msg["content"] = _compact_text(content, max_tool_chars)
        elif role == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if isinstance(inner, str) and len(inner) > max_tool_chars:
                    block["content"] = _compact_text(inner, max_tool_chars)
