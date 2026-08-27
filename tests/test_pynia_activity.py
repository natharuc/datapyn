"""Collapsible Pynia activity block: thinking + tool rows."""

from src.services.pynia.acp.activity import (
    display_tool_title,
    format_activity_tool,
    merge_activity_tool,
)
from src.services.pynia.acp.binding import TabChatState


def test_display_tool_title_strips_copilot_prefix():
    assert display_tool_title("datapyn-datapyn_query") == "datapyn_query"
    assert display_tool_title("datapyn/datapyn_edit") == "datapyn_edit"
    assert display_tool_title("datapyn_snapshot") == "datapyn_snapshot"


def test_format_activity_tool_start():
    card = format_activity_tool({
        "sessionUpdate": "tool_call",
        "toolCallId": "call-1",
        "title": "datapyn-datapyn_query",
        "status": "pending",
    })
    assert card == {
        "id": "call-1",
        "title": "datapyn_query",
        "status": "running",
    }


def test_format_activity_tool_update_keeps_id_without_blank_title():
    card = format_activity_tool({
        "sessionUpdate": "tool_call_update",
        "toolCallId": "call-1",
        "status": "completed",
    })
    assert card["id"] == "call-1"
    assert card["status"] == "completed"
    assert "title" not in card


def test_format_activity_tool_skips_generic_execute():
    assert format_activity_tool({
        "sessionUpdate": "tool_call",
        "title": "execute",
        "kind": "execute",
    }) is None


def test_format_activity_tool_error():
    card = format_activity_tool({
        "sessionUpdate": "tool_call_update",
        "title": "datapyn_query",
        "status": "failed",
        "isError": True,
        "content": [{"type": "text", "text": "boom"}],
    })
    assert card["status"] == "error"
    assert card["error"] == "boom"


def test_merge_activity_tool_updates_status_not_title():
    tools = [{"id": "call-1", "title": "datapyn_query", "status": "running"}]
    merge_activity_tool(tools, {"id": "call-1", "status": "completed"})
    assert tools == [{"id": "call-1", "title": "datapyn_query", "status": "completed"}]


def test_tab_state_records_and_consumes_activity():
    state = TabChatState(tab_id="t1")
    state.record_thinking("hmm ")
    state.record_thinking("yes")
    state.record_tool({"id": "a", "title": "datapyn_edit", "status": "running"})
    state.record_tool({"id": "a", "status": "completed"})
    activity = state.consume_activity()
    assert activity["thinking"] == "hmm yes"
    assert activity["tools"] == [
        {"id": "a", "title": "datapyn_edit", "status": "completed"}
    ]
    assert state.consume_activity() is None
