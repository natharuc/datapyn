"""Strip model tool-call markup from reasoning text shown in the chat UI."""

from __future__ import annotations

import re

# DeepSeek / some OpenRouter models embed tool calls in reasoning streams as DSML.
_TOOL_MARKUP_RE = re.compile(
    r"<\|[^>]*\|>|</\|[^>]*\|>|DSML|tool_calls?|invoke\s+name\s*=|parameter\s+name\s*=",
    re.IGNORECASE,
)


def should_skip_thinking_stream(chunk: str) -> bool:
    """Return True when a delta is internal tool syntax, not user-facing reasoning."""
    text = chunk or ""
    stripped = text.strip()
    if not stripped:
        return True
    if "DSML" in stripped or "<|" in stripped or "|>" in stripped:
        return True
    if _TOOL_MARKUP_RE.search(stripped):
        return True
    return False


def sanitize_thinking_chunk(chunk: str) -> str:
    """Remove tool markup fragments; return empty when nothing readable remains."""
    if should_skip_thinking_stream(chunk):
        return ""
    cleaned = _TOOL_MARKUP_RE.sub("", chunk)
    return cleaned if cleaned.strip() else ""
