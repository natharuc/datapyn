"""Helpers for incremental LSP textDocument/didChange payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional


def offset_to_position(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(offset, len(text)))
    line = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset)
    character = offset if line_start < 0 else offset - line_start - 1
    return line, character


def compute_incremental_change(old_text: str, new_text: str) -> Optional[Dict[str, Any]]:
    """Return a single LSP content change entry, or None when unchanged."""
    if old_text == new_text:
        return None
    if not old_text:
        return {"text": new_text}

    prefix = 0
    max_prefix = min(len(old_text), len(new_text))
    while prefix < max_prefix and old_text[prefix] == new_text[prefix]:
        prefix += 1

    old_suffix = len(old_text)
    new_suffix = len(new_text)
    while (
        old_suffix > prefix
        and new_suffix > prefix
        and old_text[old_suffix - 1] == new_text[new_suffix - 1]
    ):
        old_suffix -= 1
        new_suffix -= 1

    start_line, start_char = offset_to_position(old_text, prefix)
    end_line, end_char = offset_to_position(old_text, old_suffix)
    inserted = new_text[prefix:new_suffix]

    if prefix == 0 and old_suffix == len(old_text) and new_suffix == len(new_text):
        return {"text": new_text}

    return {
        "range": {
            "start": {"line": start_line, "character": start_char},
            "end": {"line": end_line, "character": end_char},
        },
        "text": inserted,
    }
