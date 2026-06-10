"""Session memory helpers for API providers."""

from src.services.pynia.session_memory import (
    build_api_messages,
    compact_conversation_in_place,
    history_from_ui_messages,
    rolling_summary_from_history,
)


def test_history_from_ui_messages_truncates_assistant():
    ui = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "x" * 5000},
        {"role": "user", "content": "next"},
    ]
    hist = history_from_ui_messages(ui, exclude_last=True)
    assert len(hist) == 2
    assert len(hist[1]["content"]) <= 4003


def test_build_api_messages_includes_history():
    ui = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second"},
    ]
    msgs = build_api_messages(
        system_prompt="sys",
        current_user_prompt="current",
        ui_messages=ui,
    )
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "current"
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles


def test_compact_preserves_latest_round_openai_format():
    """The round the model is about to act on must keep its full tool results."""
    old_result = "old " * 500
    fresh_result = "fresh " * 500
    conversation = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": old_result},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "b"}]},
        {"role": "tool", "tool_call_id": "b", "content": fresh_result},
    ]
    compact_conversation_in_place(conversation)
    assert len(conversation[3]["content"]) < len(old_result)
    assert "[truncated for session memory]" in conversation[3]["content"]
    assert conversation[5]["content"] == fresh_result


def test_compact_preserves_latest_round_anthropic_format():
    old_result = "old " * 500
    fresh_result = "fresh " * 500
    conversation = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "a", "name": "datapyn_inspect", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "a", "content": old_result}],
        },
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "b", "name": "datapyn_edit", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "b", "content": fresh_result}],
        },
    ]
    compact_conversation_in_place(conversation)
    assert len(conversation[2]["content"][0]["content"]) < len(old_result)
    assert conversation[4]["content"][0]["content"] == fresh_result


def test_compact_without_tool_rounds_is_noop():
    conversation = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "x" * 5000},
    ]
    before = [dict(m) for m in conversation]
    compact_conversation_in_place(conversation)
    assert conversation == before


def test_rolling_summary():
    hist = history_from_ui_messages(
        [
            {"role": "user", "content": "analyze sales"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "add chart"},
        ],
        exclude_last=False,
    )
    recap = rolling_summary_from_history(hist)
    assert "Session recap" in recap
    assert "analyze" in recap
