"""Recording IAcpAgentListener for unit tests."""

from __future__ import annotations

import threading
from typing import Any

from src.services.pynia.acp.agent import ActionRequest, QuestionRequest


class RecordingAcpListener:
    def __init__(self):
        self.messages: list[str] = []
        self.thinking: list[str] = []
        self.actions: list[ActionRequest] = []
        self.questions: list[QuestionRequest] = []
        self.tools: list[dict[str, Any]] = []
        self.config_events = 0
        self.got_message = threading.Event()
        self.got_thinking = threading.Event()
        self.got_action = threading.Event()

    def on_receive_message(self, text: str) -> None:
        self.messages.append(text)
        self.got_message.set()

    def on_thinking(self, text: str) -> None:
        self.thinking.append(text)
        self.got_thinking.set()

    def on_action(self, request: ActionRequest) -> None:
        self.actions.append(request)
        self.got_action.set()

    def on_questions(self, request: QuestionRequest) -> None:
        self.questions.append(request)

    def on_tool_event(self, payload: dict[str, Any]) -> None:
        self.tools.append(payload)

    def on_config_changed(self) -> None:
        self.config_events += 1
