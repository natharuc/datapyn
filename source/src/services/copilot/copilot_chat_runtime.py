"""Turn state machine for the Copilot chat WebView runtime."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


ACTIVE_STATES = {"sending", "thinking", "streaming", "running_tool"}
TERMINAL_STATES = {"complete", "error", "cancelled", "timed_out"}


class CopilotChatRuntime(QObject):
    """Small state machine that makes chat turns recoverable.

    The WebView and SDK do not get to own the source of truth for a turn. Every
    UI update is tagged with the active turn id so stale events can be ignored.
    """

    state_changed = pyqtSignal(dict)
    timeout = pyqtSignal(str)

    def __init__(
        self,
        timeout_ms: int = 180_000,
        max_turn_ms: int = 600_000,
        timeout_message: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._idle_timeout_ms = timeout_ms
        self.timeout_ms = timeout_ms
        self._max_turn_ms = max_turn_ms
        self.timeout_message = timeout_message or "timeout"
        self._active_turn: Optional[Dict[str, Any]] = None
        self._last_turn: Optional[Dict[str, Any]] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    @property
    def active_turn_id(self) -> str:
        return str((self._active_turn or {}).get("turn_id", ""))

    @property
    def is_active(self) -> bool:
        return bool(self._active_turn and self._active_turn.get("state") in ACTIVE_STATES)

    @property
    def last_turn(self) -> Dict[str, Any]:
        return dict(self._last_turn or {})

    def start_turn(
        self,
        prompt: str,
        references: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        turn = {
            "turn_id": uuid.uuid4().hex,
            "request_id": uuid.uuid4().hex,
            "state": "sending",
            "prompt": prompt,
            "references": list(references or []),
            "attachments": list(attachments or []),
            "started_at": time.time(),
            "updated_at": time.time(),
            "elapsed_ms": 0,
            "error": "",
            "can_retry": False,
        }
        self._active_turn = turn
        self._last_turn = dict(turn)
        self._touch_activity()
        self._emit(turn)
        return dict(turn)

    def touch_activity(self) -> None:
        """Reset the idle timeout while a turn is still active."""
        self._touch_activity()

    def _touch_activity(self) -> None:
        if not self._active_turn:
            return
        elapsed_ms = int((time.time() - self._active_turn["started_at"]) * 1000)
        if elapsed_ms >= self._max_turn_ms:
            self._on_timeout()
            return
        self._timer.start(self._idle_timeout_ms)

    def transition(self, state: str, **extra: Any) -> Dict[str, Any]:
        if not self._active_turn:
            return {}
        self._active_turn.update(extra)
        self._active_turn["state"] = state
        self._active_turn["updated_at"] = time.time()
        self._active_turn["elapsed_ms"] = int((time.time() - self._active_turn["started_at"]) * 1000)
        if state in TERMINAL_STATES:
            self._timer.stop()
            self._active_turn["can_retry"] = state in {"error", "timed_out", "cancelled"}
        else:
            self._touch_activity()
        self._last_turn = dict(self._active_turn)
        self._emit(self._active_turn)
        if state in TERMINAL_STATES:
            self._active_turn = None
        return dict(self._last_turn)

    def mark_thinking(self, text: str = "") -> Dict[str, Any]:
        return self.transition("thinking", thinking=text)

    def mark_streaming(self) -> Dict[str, Any]:
        return self.transition("streaming")

    def mark_tool(self, tool_name: str, status: str = "running") -> Dict[str, Any]:
        return self.transition("running_tool", tool={"name": tool_name, "status": status})

    def complete(self, response: str = "") -> Dict[str, Any]:
        return self.transition("complete", response=response, error="")

    def fail(self, error: str, state: str = "error") -> Dict[str, Any]:
        state = state if state in {"error", "timed_out"} else "error"
        return self.transition(state, error=str(error or "Unknown error"))

    def cancel(self) -> Dict[str, Any]:
        if not self._active_turn:
            return {}
        return self.transition("cancelled", error="")

    def retry_payload(self) -> Dict[str, Any]:
        last = self._last_turn or {}
        return {
            "prompt": last.get("prompt", ""),
            "references": list(last.get("references", []) or []),
            "attachments": list(last.get("attachments", []) or []),
        }

    def _on_timeout(self) -> None:
        turn_id = self.active_turn_id
        if not turn_id:
            return
        self.fail(self.timeout_message, state="timed_out")
        self.timeout.emit(turn_id)

    def _emit(self, turn: Dict[str, Any]) -> None:
        self.state_changed.emit(dict(turn))
