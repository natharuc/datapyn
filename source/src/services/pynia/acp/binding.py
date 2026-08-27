"""Per-tab Pynia chat state (one ACP conversation per DataPyn session tab)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


def empty_pynia_state() -> dict[str, Any]:
    return {
        "agent_id": None,
        "acp_session_id": None,
        "completion_session_id": None,
        "locked": False,
        "messages": [],
        "acp_session_recreated": False,
    }


def _ready_event() -> threading.Event:
    event = threading.Event()
    event.set()
    return event


@dataclass
class TabChatState:
    tab_id: str
    agent_id: Optional[str] = None
    acp_session_id: Optional[str] = None
    completion_session_id: Optional[str] = None
    locked: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)
    acp_session_recreated: bool = False
    busy: bool = False
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    config_loading: bool = False
    session_ready: threading.Event = field(default_factory=_ready_event)
    turn_activity: dict[str, Any] = field(default_factory=dict)

    def reset_activity(self) -> None:
        self.turn_activity = {"thinking": "", "tools": []}

    def record_thinking(self, text: str) -> None:
        from src.services.pynia.acp.activity import clip_thinking

        if not self.turn_activity:
            self.reset_activity()
        self.turn_activity["thinking"] = clip_thinking(
            self.turn_activity.get("thinking") or "", text or ""
        )

    def record_tool(self, card: dict[str, Any]) -> None:
        from src.services.pynia.acp.activity import merge_activity_tool

        if not self.turn_activity:
            self.reset_activity()
        tools = list(self.turn_activity.get("tools") or [])
        self.turn_activity["tools"] = merge_activity_tool(tools, card)

    def consume_activity(self) -> Optional[dict[str, Any]]:
        activity = self.turn_activity or {}
        self.reset_activity()
        thinking = (activity.get("thinking") or "").strip()
        tools = [item for item in (activity.get("tools") or []) if isinstance(item, dict)]
        if not thinking and not tools:
            return None
        return {"thinking": thinking, "tools": tools}

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "acp_session_id": self.acp_session_id,
            "completion_session_id": self.completion_session_id,
            "locked": self.locked,
            "messages": list(self.messages),
            "acp_session_recreated": self.acp_session_recreated,
        }

    @classmethod
    def from_dict(cls, tab_id: str, data: Optional[dict[str, Any]]) -> "TabChatState":
        raw = data or {}
        messages = raw.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        return cls(
            tab_id=tab_id,
            agent_id=raw.get("agent_id") or None,
            acp_session_id=raw.get("acp_session_id") or None,
            completion_session_id=raw.get("completion_session_id") or None,
            locked=bool(raw.get("locked")),
            messages=list(messages),
            acp_session_recreated=bool(raw.get("acp_session_recreated")),
        )

    def append_message(self, role: str, content: str, **extra: Any) -> dict[str, Any]:
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        return msg

    def can_change_agent(self) -> bool:
        return not self.locked
