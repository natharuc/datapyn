"""Tests for the Copilot chat runtime state machine."""

from PyQt6.QtTest import QTest


def test_start_turn_emits_sending_state(qapp):
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=5000)
    states = []
    runtime.state_changed.connect(states.append)

    turn = runtime.start_turn("hello", references=[{"reference": "#block1"}])

    assert runtime.is_active is True
    assert turn["state"] == "sending"
    assert turn["prompt"] == "hello"
    assert turn["references"] == [{"reference": "#block1"}]
    assert states[-1]["turn_id"] == turn["turn_id"]


def test_terminal_states_clear_active_turn_and_keep_retry_payload(qapp):
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=5000)
    runtime.start_turn("retry me", references=[{"reference": "#tab0"}])

    final_state = runtime.fail("network failure")

    assert runtime.is_active is False
    assert runtime.active_turn_id == ""
    assert final_state["state"] == "error"
    assert final_state["can_retry"] is True
    assert runtime.retry_payload() == {
        "prompt": "retry me",
        "references": [{"reference": "#tab0"}],
        "attachments": [],
    }


def test_start_turn_keeps_attachments_for_retry(qapp):
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=5000)
    attachments = [{"name": "shot.png", "mimeType": "image/png", "data": "abc", "size": 3}]
    runtime.start_turn("look at this", attachments=attachments)
    runtime.fail("vision error")

    assert runtime.retry_payload()["attachments"] == attachments


def test_timeout_emits_terminal_state_and_timeout_signal(qapp):
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=20, timeout_message="timeout translated")
    states = []
    timeouts = []
    runtime.state_changed.connect(states.append)
    runtime.timeout.connect(timeouts.append)

    started = runtime.start_turn("slow request")
    QTest.qWait(60)

    assert runtime.is_active is False
    assert timeouts == [started["turn_id"]]
    assert states[-1]["state"] == "timed_out"
    assert states[-1]["error"] == "timeout translated"
    assert states[-1]["can_retry"] is True


def test_cancel_is_terminal_and_retryable(qapp):
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=5000)
    runtime.start_turn("cancel me")

    state = runtime.cancel()

    assert state["state"] == "cancelled"
    assert state["can_retry"] is True
    assert runtime.is_active is False


def test_touch_activity_resets_idle_timeout(qapp):
    from PyQt6.QtTest import QTest
    from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime

    runtime = CopilotChatRuntime(timeout_ms=40, max_turn_ms=60_000)
    runtime.start_turn("long agent turn")
    QTest.qWait(25)
    runtime.touch_activity()
    QTest.qWait(25)

    assert runtime.is_active is True