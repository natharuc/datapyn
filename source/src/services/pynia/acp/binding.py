"""Per-tab Pynia chat state (one ACP conversation per DataPyn session tab)."""

from __future__ import annotations

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
