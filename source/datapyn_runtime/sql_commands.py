"""Small, detached SQL execution metadata; never infer commands from rows."""

from __future__ import annotations

import re
from numbers import Integral


def command_result(value):
    """Return a wire-safe copy, accepting only the explicit connector contract."""
    if not isinstance(value, dict):
        return None
    index, command = value.get("statement_index"), value.get("command")
    if not isinstance(index, Integral) or isinstance(index, bool) or index < 1:
        return None
    if not isinstance(command, str) or not command.strip():
        return None
    rows = value.get("rows_affected")
    return {
        "statement_index": int(index), "command": command.strip(),
        "rows_affected": int(rows) if isinstance(rows, Integral) and not isinstance(rows, bool) and rows >= 0 else None,
    }


def command_results(values):
    if not isinstance(values, list):
        return []
    return sorted((result for value in values if (result := command_result(value)) is not None),
                  key=lambda result: result["statement_index"])


def frame_command_results(frames):
    """Metadata is attached once, to the first returned frame."""
    for frame in frames:
        attrs = getattr(frame, "attrs", {})
        if isinstance(attrs, dict) and "datapyn_command_results" in attrs:
            return command_results(attrs["datapyn_command_results"])
    return None


def is_command_frame(frame):
    attrs = getattr(frame, "attrs", {})
    return isinstance(attrs, dict) and attrs.get("datapyn_command_result") is True


def command_label(statement, db_type="sqlite"):
    from .sql_context import sql_code_mask

    words = re.finditer(r"[A-Za-z_]+|[()]", sql_code_mask(statement, db_type, identifiers=True).strip())
    head = next(words, None)
    if head is None:
        return "SQL"
    label = head.group().upper()
    if label == "WITH":
        depth = 0
        for word in words:
            token = word.group().upper()
            if token == "(":
                depth += 1
            elif token == ")":
                depth = max(0, depth - 1)
            elif not depth and token in {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE"}:
                return token
    return label
