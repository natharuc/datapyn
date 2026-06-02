"""Callbacks for agent-turn progress (chat UI)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]


def emit_progress(
    callback: Optional[ProgressCallback],
    *,
    phase_key: str,
    detail: str = "",
    step_id: str = "",
    step_state: str = "active",
    reasoning: str = "",
) -> None:
    if not callback:
        return
    payload: Dict[str, Any] = {"phase_key": phase_key}
    if detail:
        payload["detail"] = detail
    if step_id:
        payload["step_id"] = step_id
        payload["step_state"] = step_state
    if reasoning:
        payload["reasoning"] = reasoning
    try:
        callback(payload)
    except Exception:
        pass
